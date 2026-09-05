"""Project-owned execution of one SciTaste-selected substrate action."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.autoresearchclaw import (
    ACTION_TO_STAGE,
    PINNED_COMMIT,
    AutoResearchClawExecutor,
    CommandRunner,
)
from scitaste.executor.base import ExecutionStatus
from scitaste.executor.workflow import SubstrateActionWorkflow
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.schema.actions import MetaAction


class ProjectSubstrateWorkflowConfig(BaseModel):
    """Stable identity and limits for one project-owned substrate action."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    config_id: str
    project_id: str
    title: str = Field(min_length=1)
    research_direction: str = Field(min_length=1)
    target_domain: str | None = None
    execution_target_domain: str = Field(default="autonomous-research", min_length=1)
    target_venue: str | None = None
    action_type: MetaAction
    provider: Literal["autoresearchclaw"] = "autoresearchclaw"
    model: str = Field(min_length=1)
    condition: str = "project_substrate_action"
    evidence_scope: str = "online-engineering-only"
    live_enabled: bool = False
    autoresearchclaw_config: Path
    timeout_seconds: float = Field(default=1800.0, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    max_total_tokens: int = Field(default=100_000, gt=0)
    max_snapshot_bytes: int = Field(default=2_147_483_648, gt=0)

    @field_validator("config_id")
    @classmethod
    def config_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="config_id")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @model_validator(mode="after")
    def action_is_executable_by_substrate(self) -> ProjectSubstrateWorkflowConfig:
        if self.action_type not in ACTION_TO_STAGE:
            raise ValueError("project substrate workflow requires an executable action type")
        return self


class ProjectSubstrateRunManifest(BaseModel):
    """Immutable identity published before the provider-backed action starts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    action_type: MetaAction
    upstream_stage: str
    seed: int = Field(ge=0)
    workflow_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_file_count: int = Field(ge=1)
    source_bytes: int = Field(ge=1)
    expected_substrate_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    actual_substrate_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @classmethod
    def create(cls, **payload: Any) -> ProjectSubstrateRunManifest:
        digest = content_sha256(payload)
        return cls.model_validate({**payload, "manifest_sha256": digest})

    @model_validator(mode="after")
    def manifest_hash_matches(self) -> ProjectSubstrateRunManifest:
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("project substrate manifest hash mismatch")
        return self


class ProjectSubstrateVerification(BaseModel):
    """Exact output evidence for one completed or failed selected action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_status: ExecutionStatus
    transition_applied: bool
    input_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    working_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    working_file_count: int = Field(ge=1)
    working_bytes: int = Field(ge=1)
    evidence_sha256: dict[str, str]
    verification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evidence_sha256")
    @classmethod
    def evidence_is_nonempty_and_hashed(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("project substrate verification requires evidence")
        for locator, digest in value.items():
            parsed = PurePosixPath(locator)
            if (
                not locator
                or parsed.is_absolute()
                or any(part in {"", ".", ".."} for part in parsed.parts)
            ):
                raise ValueError("project substrate evidence locators must be owned paths")
            if not _is_sha256(digest):
                raise ValueError("project substrate evidence hashes must be SHA-256")
        return value

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @classmethod
    def create(cls, **payload: Any) -> ProjectSubstrateVerification:
        digest = content_sha256(payload)
        return cls.model_validate({**payload, "verification_sha256": digest})

    @model_validator(mode="after")
    def verification_hash_matches(self) -> ProjectSubstrateVerification:
        expected = content_sha256(self.model_dump(mode="json", exclude={"verification_sha256"}))
        if self.verification_sha256 != expected:
            raise ValueError("project substrate verification hash mismatch")
        return self


class ProjectSubstrateActionWorkflow:
    """Run a selected action against an immutable imported substrate snapshot."""

    def __init__(
        self,
        *,
        seed: int = 0,
        command_runner: CommandRunner | None = None,
    ) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.seed = seed
        self.command_runner = command_runner

    def plan(
        self,
        config: ProjectSubstrateWorkflowConfig,
        *,
        outputs_root: str | Path,
        run_id: str,
        source_run_dir: str | Path | None,
        resume: bool = False,
        allow_live: bool = False,
    ) -> dict[str, object]:
        validate_entry_id(run_id, field_name="run_id")
        runtime = ProjectRuntime(outputs_root)
        executor = self._executor(config, dry_run=True)
        substrate = executor.verify_substrate()
        if not substrate["initialized"] or not substrate["pinned"]:
            raise ValueError("AutoResearchClaw does not match the audited substrate pin")
        executor_config_sha256 = _file_sha256(config.autoresearchclaw_config)
        workflow_config_sha256 = _workflow_config_sha256(config)
        source_summary: _TreeSummary | None = None
        if resume:
            snapshot = runtime.open(config.project_id)
            registered = _registered_run(snapshot, run_id)
            manifest = _load_manifest(_run_root(runtime, config.project_id, run_id))
            self._validate_resume_identity(
                config,
                registered,
                manifest,
                seed=self.seed,
                workflow_config_sha256=workflow_config_sha256,
                executor_config_sha256=executor_config_sha256,
            )
            source_summary = _tree_summary(
                _run_root(runtime, config.project_id, run_id) / "inputs/autoresearchclaw",
                max_bytes=config.max_snapshot_bytes,
            )
            if source_summary.fingerprint != manifest.source_snapshot_sha256:
                raise ValueError("owned AutoResearchClaw input snapshot hash drift")
            revision = snapshot.revision
        else:
            if source_run_dir is None:
                raise ValueError("a source AutoResearchClaw run is required for a new run")
            source_summary = _tree_summary(
                Path(source_run_dir),
                max_bytes=config.max_snapshot_bytes,
            )
            try:
                existing = runtime.open(config.project_id)
            except FileNotFoundError:
                revision = 0
            else:
                self._validate_project_identity(existing, config)
                revision = existing.revision
        return {
            "schema_version": "1.0",
            "status": "planned",
            "project_id": config.project_id,
            "run_id": run_id,
            "project_revision": revision,
            "action_type": config.action_type.value,
            "upstream_stage": ACTION_TO_STAGE[config.action_type],
            "seed": self.seed,
            "resume": resume,
            "live_config_enabled": config.live_enabled,
            "caller_live_authorized": allow_live,
            "would_contact_provider": bool(config.live_enabled and allow_live),
            "workflow_config_sha256": workflow_config_sha256,
            "executor_config_sha256": executor_config_sha256,
            "source_snapshot_sha256": source_summary.fingerprint,
            "source_file_count": source_summary.file_count,
            "source_bytes": source_summary.total_bytes,
            "expected_substrate_commit": PINNED_COMMIT,
            "actual_substrate_commit": str(substrate["actual_commit"]),
            "run_locator": f"projects/{config.project_id}/runs/{run_id}",
        }

    def run(
        self,
        config: ProjectSubstrateWorkflowConfig,
        *,
        outputs_root: str | Path,
        run_id: str,
        source_run_dir: str | Path | None = None,
        resume: bool = False,
        allow_live: bool = False,
    ) -> dict[str, object]:
        plan = self.plan(
            config,
            outputs_root=outputs_root,
            run_id=run_id,
            source_run_dir=source_run_dir,
            resume=resume,
            allow_live=allow_live,
        )
        if not config.live_enabled:
            raise ValueError("project substrate execution is disabled by configuration")
        if not allow_live:
            raise ValueError("project substrate execution requires explicit caller live opt-in")
        runtime = ProjectRuntime(outputs_root)
        snapshot = self._open_or_create_project(runtime, config, resume=resume)
        if resume:
            snapshot, resume_attempt = self._resume(runtime, snapshot, config, run_id, plan)
        else:
            snapshot = runtime.begin_run(
                config.project_id,
                ProjectRun(
                    run_id=run_id,
                    provider=config.provider,
                    model=config.model,
                    condition=config.condition,
                    seed=self.seed,
                    status="running",
                    evidence_scope=config.evidence_scope,
                    stage_path="substrate_action",
                    workflow_config_sha256=plan["workflow_config_sha256"],
                    source_snapshot_sha256=plan["source_snapshot_sha256"],
                    action_type=config.action_type.value,
                    resume_attempt=0,
                ),
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
            resume_attempt = 0
        run_root = _run_root(runtime, config.project_id, run_id)
        try:
            if resume:
                archived_attempt = _archive_attempt(run_root)
            else:
                assert source_run_dir is not None
                _copy_tree_exclusive(Path(source_run_dir), run_root / "inputs/autoresearchclaw")
                _copy_file_exclusive(
                    config.autoresearchclaw_config,
                    run_root / "inputs/autoresearchclaw-config.yaml",
                )
                archived_attempt = None
            source_summary = _tree_summary(
                run_root / "inputs/autoresearchclaw",
                max_bytes=config.max_snapshot_bytes,
            )
            if source_summary.fingerprint != plan["source_snapshot_sha256"]:
                raise ValueError("owned AutoResearchClaw input snapshot changed before execution")
            manifest = self._publish_or_validate_manifest(run_root, config, plan, source_summary)
            work_root = run_root / "work/autoresearchclaw"
            _copy_tree_exclusive(run_root / "inputs/autoresearchclaw", work_root)
            executor = self._executor(config, dry_run=False)
            action_summary = SubstrateActionWorkflow(executor=executor, seed=self.seed).run(
                action_type=config.action_type,
                run_dir=work_root,
                output_dir=run_root / "substrate_action",
                project_id=config.project_id,
                topic=config.research_direction,
                target_domain=config.execution_target_domain,
            )
            if _workflow_config_sha256(config) != plan["workflow_config_sha256"]:
                raise ValueError(
                    "project substrate workflow configuration changed during execution"
                )
            verification = _build_verification(
                run_root,
                manifest,
                action_summary,
                max_bytes=config.max_snapshot_bytes,
            )
            _write_model_exclusive(run_root / "substrate_action/verification.json", verification)
            completed = action_summary["execution_status"] == ExecutionStatus.SUCCEEDED.value
            final_status = "complete" if completed else "failed"
            snapshot = runtime.update_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
                status=final_status,
                artifact=f"runs/{run_id}/substrate_action/verification.json",
                final_state=f"runs/{run_id}/substrate_action/research_state.json",
                manifest_sha256=manifest.manifest_sha256,
                verification_sha256=verification.verification_sha256,
                execution_status=action_summary["execution_status"],
            )
        except BaseException as exc:
            self._mark_failed(runtime, config.project_id, run_id, exc)
            raise
        return {
            **plan,
            "status": final_status,
            "project_revision": snapshot.revision,
            "resume_attempt": resume_attempt,
            "archived_attempt": archived_attempt,
            "manifest_sha256": manifest.manifest_sha256,
            "verification_sha256": verification.verification_sha256,
            "execution_status": action_summary["execution_status"],
            "transition_applied": action_summary["transition_applied"],
            "state_revision": action_summary["state_revision"],
            "artifact_count": action_summary["artifact_count"],
            "verification_locator": (
                f"projects/{config.project_id}/runs/{run_id}/substrate_action/verification.json"
            ),
        }

    def status(
        self,
        *,
        outputs_root: str | Path,
        project_id: str,
        run_id: str,
    ) -> dict[str, object]:
        runtime = ProjectRuntime(outputs_root)
        snapshot = runtime.open(project_id)
        run = _registered_run(snapshot, run_id)
        run_root = _run_root(runtime, project_id, run_id)
        manifest = _load_manifest(run_root)
        verification = ProjectSubstrateVerification.model_validate_json(
            (run_root / "substrate_action/verification.json").read_text(encoding="utf-8")
        )
        _verify_final_evidence(run_root, manifest, verification)
        extra = run.model_extra or {}
        expected = {
            "manifest_sha256": manifest.manifest_sha256,
            "verification_sha256": verification.verification_sha256,
            "execution_status": verification.execution_status.value,
        }
        if any(extra.get(key) != value for key, value in expected.items()):
            raise ValueError("registered substrate run metadata drift")
        expected_status = (
            "complete" if verification.execution_status is ExecutionStatus.SUCCEEDED else "failed"
        )
        if run.status != expected_status:
            raise ValueError("registered substrate run status drift")
        return {
            "schema_version": "1.0",
            "status": "verified",
            "project_id": project_id,
            "run_id": run_id,
            "project_revision": snapshot.revision,
            "run_status": run.status,
            "action_type": manifest.action_type.value,
            "upstream_stage": manifest.upstream_stage,
            "execution_status": verification.execution_status.value,
            "transition_applied": verification.transition_applied,
            "manifest_sha256": manifest.manifest_sha256,
            "verification_sha256": verification.verification_sha256,
            "run_locator": f"projects/{project_id}/runs/{run_id}",
        }

    def _executor(
        self,
        config: ProjectSubstrateWorkflowConfig,
        *,
        dry_run: bool,
    ) -> AutoResearchClawExecutor:
        return AutoResearchClawExecutor(
            config_path=config.autoresearchclaw_config,
            dry_run=dry_run,
            timeout_seconds=config.timeout_seconds,
            max_output_tokens=config.max_output_tokens,
            max_total_tokens=config.max_total_tokens,
            command_runner=self.command_runner,
        )

    @staticmethod
    def _open_or_create_project(
        runtime: ProjectRuntime,
        config: ProjectSubstrateWorkflowConfig,
        *,
        resume: bool,
    ) -> ProjectSnapshot:
        try:
            snapshot = runtime.open(config.project_id)
        except FileNotFoundError:
            if resume:
                raise ValueError("cannot resume a project that does not exist") from None
            return runtime.create(
                ProjectManifest(
                    project_id=config.project_id,
                    title=config.title,
                    research_direction=config.research_direction,
                    target_domain=config.target_domain,
                    target_venue=config.target_venue,
                    status="active",
                    stage_semantics="scitaste-substrate-actions",
                )
            )
        ProjectSubstrateActionWorkflow._validate_project_identity(snapshot, config)
        return snapshot

    @staticmethod
    def _validate_project_identity(
        snapshot: ProjectSnapshot,
        config: ProjectSubstrateWorkflowConfig,
    ) -> None:
        identity = (
            snapshot.manifest.research_direction,
            snapshot.manifest.target_domain,
            snapshot.manifest.target_venue,
        )
        expected = (config.research_direction, config.target_domain, config.target_venue)
        if identity != expected:
            raise ValueError("existing project identity does not match substrate configuration")

    def _resume(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: ProjectSubstrateWorkflowConfig,
        run_id: str,
        plan: dict[str, object],
    ) -> tuple[ProjectSnapshot, int]:
        run = _registered_run(snapshot, run_id)
        manifest = _load_manifest(_run_root(runtime, config.project_id, run_id))
        self._validate_resume_identity(
            config,
            run,
            manifest,
            seed=self.seed,
            workflow_config_sha256=str(plan["workflow_config_sha256"]),
            executor_config_sha256=str(plan["executor_config_sha256"]),
        )
        if run.status != "failed":
            raise ValueError("only a failed project substrate run can be resumed")
        raw_attempt = (run.model_extra or {}).get("resume_attempt", 0)
        if not isinstance(raw_attempt, int) or isinstance(raw_attempt, bool) or raw_attempt < 0:
            raise ValueError("registered substrate run has an invalid resume_attempt")
        attempt = raw_attempt + 1
        snapshot = runtime.update_run(
            config.project_id,
            run_id,
            expected_revision=snapshot.revision,
            status="running",
            resume_attempt=attempt,
        )
        if snapshot.manifest.current_run != run_id:
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
        return snapshot, attempt

    @staticmethod
    def _validate_resume_identity(
        config: ProjectSubstrateWorkflowConfig,
        run: ProjectRun,
        manifest: ProjectSubstrateRunManifest,
        *,
        seed: int,
        workflow_config_sha256: str,
        executor_config_sha256: str,
    ) -> None:
        if run.seed != seed or manifest.seed != seed:
            raise ValueError("resume seed does not match owned substrate run")
        observed = (
            run.provider,
            run.model,
            run.condition,
            run.evidence_scope,
            run.stage_path,
            (run.model_extra or {}).get("action_type"),
        )
        expected = (
            config.provider,
            config.model,
            config.condition,
            config.evidence_scope,
            "substrate_action",
            config.action_type.value,
        )
        if observed != expected:
            raise ValueError("resume configuration does not match substrate run identity")
        extra = run.model_extra or {}
        if extra.get("workflow_config_sha256") != workflow_config_sha256:
            raise ValueError("workflow configuration does not match registered substrate run")
        if manifest.workflow_config_sha256 != workflow_config_sha256:
            raise ValueError("workflow configuration does not match owned substrate manifest")
        if manifest.executor_config_sha256 != executor_config_sha256:
            raise ValueError("executor configuration does not match owned substrate manifest")

    @staticmethod
    def _publish_or_validate_manifest(
        run_root: Path,
        config: ProjectSubstrateWorkflowConfig,
        plan: dict[str, object],
        source: _TreeSummary,
    ) -> ProjectSubstrateRunManifest:
        path = run_root / "substrate_manifest.json"
        if path.exists():
            manifest = _load_manifest(run_root)
            expected = (
                config.project_id,
                run_root.name,
                config.action_type,
                ACTION_TO_STAGE[config.action_type],
                int(plan["seed"]),
                plan["workflow_config_sha256"],
                plan["executor_config_sha256"],
                source.fingerprint,
                source.file_count,
                source.total_bytes,
                PINNED_COMMIT,
                plan["actual_substrate_commit"],
            )
            observed = (
                manifest.project_id,
                manifest.run_id,
                manifest.action_type,
                manifest.upstream_stage,
                manifest.seed,
                manifest.workflow_config_sha256,
                manifest.executor_config_sha256,
                manifest.source_snapshot_sha256,
                manifest.source_file_count,
                manifest.source_bytes,
                manifest.expected_substrate_commit,
                manifest.actual_substrate_commit,
            )
            if observed != expected:
                raise ValueError("owned substrate manifest no longer matches execution plan")
            return manifest
        manifest = ProjectSubstrateRunManifest.create(
            schema_version="1.0",
            project_id=config.project_id,
            run_id=run_root.name,
            action_type=config.action_type,
            upstream_stage=ACTION_TO_STAGE[config.action_type],
            seed=int(plan.get("seed", 0)),
            workflow_config_sha256=plan["workflow_config_sha256"],
            executor_config_sha256=plan["executor_config_sha256"],
            source_snapshot_sha256=source.fingerprint,
            source_file_count=source.file_count,
            source_bytes=source.total_bytes,
            expected_substrate_commit=PINNED_COMMIT,
            actual_substrate_commit=plan["actual_substrate_commit"],
        )
        _write_model_exclusive(path, manifest)
        return manifest

    @staticmethod
    def _mark_failed(
        runtime: ProjectRuntime,
        project_id: str,
        run_id: str,
        error: BaseException,
    ) -> None:
        try:
            snapshot = runtime.open(project_id)
            runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
                status="failed",
                failure_type=type(error).__name__,
                failure_message=str(error)[:1000],
            )
        except (FileNotFoundError, ValueError):
            return


class _TreeSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str
    file_count: int
    total_bytes: int
    files: dict[str, str]


def load_project_substrate_config(path: str | Path) -> ProjectSubstrateWorkflowConfig:
    config_path = Path(path).resolve(strict=True)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("project substrate configuration must be a mapping")
    executor_config = Path(payload["autoresearchclaw_config"])
    if not executor_config.is_absolute():
        executor_config = (config_path.parent / executor_config).resolve()
    payload["autoresearchclaw_config"] = executor_config
    return ProjectSubstrateWorkflowConfig.model_validate(payload)


def _registered_run(snapshot: ProjectSnapshot, run_id: str) -> ProjectRun:
    matches = [run for run in snapshot.manifest.runs if run.run_id == run_id]
    if not matches:
        raise ValueError(f"unknown project substrate run {run_id!r}")
    return matches[0]


def _run_root(runtime: ProjectRuntime, project_id: str, run_id: str) -> Path:
    return runtime.projects_root / project_id / "runs" / run_id


def _load_manifest(run_root: Path) -> ProjectSubstrateRunManifest:
    return ProjectSubstrateRunManifest.model_validate_json(
        (run_root / "substrate_manifest.json").read_text(encoding="utf-8")
    )


def _workflow_config_sha256(config: ProjectSubstrateWorkflowConfig) -> str:
    payload = config.model_dump(mode="json")
    payload["autoresearchclaw_config"] = {
        "content_sha256": _file_sha256(config.autoresearchclaw_config)
    }
    return content_sha256(payload)


def _tree_summary(path: Path, *, max_bytes: int) -> _TreeSummary:
    root = path.resolve(strict=True)
    if not root.is_dir() or path.is_symlink():
        raise ValueError("AutoResearchClaw source snapshot must be a regular directory")
    files: dict[str, str] = {}
    total = 0
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("AutoResearchClaw snapshot cannot contain symlinks")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("AutoResearchClaw snapshot contains a non-regular entry")
        total += candidate.stat().st_size
        if total > max_bytes:
            raise ValueError("AutoResearchClaw snapshot exceeds the configured byte limit")
        files[candidate.relative_to(root).as_posix()] = _file_sha256(candidate)
    if not files:
        raise ValueError("AutoResearchClaw source snapshot cannot be empty")
    return _TreeSummary(
        fingerprint=content_sha256(files),
        file_count=len(files),
        total_bytes=total,
        files=files,
    )


def _copy_tree_exclusive(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source_summary = _tree_summary(source, max_bytes=2**63 - 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        shutil.rmtree(temporary)
        shutil.copytree(source, temporary, symlinks=False)
        copied = _tree_summary(temporary, max_bytes=2**63 - 1)
        if copied.fingerprint != source_summary.fingerprint:
            raise ValueError("AutoResearchClaw snapshot changed while it was copied")
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _copy_file_exclusive(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if _file_sha256(temporary) != _file_sha256(source):
            raise ValueError("executor configuration changed while it was copied")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _build_verification(
    run_root: Path,
    manifest: ProjectSubstrateRunManifest,
    action_summary: dict[str, object],
    *,
    max_bytes: int,
) -> ProjectSubstrateVerification:
    input_summary = _tree_summary(
        run_root / "inputs/autoresearchclaw",
        max_bytes=max_bytes,
    )
    work_summary = _tree_summary(
        run_root / "work/autoresearchclaw",
        max_bytes=max_bytes,
    )
    stage = run_root / "substrate_action"
    required = (
        "decisions.jsonl",
        "executor_result.json",
        "research_state.json",
        "substrate_summary.json",
    )
    evidence = {f"substrate_action/{name}": _file_sha256(stage / name) for name in required}
    return ProjectSubstrateVerification.create(
        schema_version="1.0",
        project_id=manifest.project_id,
        run_id=manifest.run_id,
        manifest_sha256=manifest.manifest_sha256,
        execution_status=ExecutionStatus(str(action_summary["execution_status"])),
        transition_applied=bool(action_summary["transition_applied"]),
        input_snapshot_sha256=input_summary.fingerprint,
        working_tree_sha256=work_summary.fingerprint,
        working_file_count=work_summary.file_count,
        working_bytes=work_summary.total_bytes,
        evidence_sha256=evidence,
    )


def _verify_final_evidence(
    run_root: Path,
    manifest: ProjectSubstrateRunManifest,
    verification: ProjectSubstrateVerification,
) -> None:
    if verification.project_id != manifest.project_id or verification.run_id != manifest.run_id:
        raise ValueError("substrate verification belongs to another project run")
    if (
        manifest.expected_substrate_commit != PINNED_COMMIT
        or manifest.actual_substrate_commit != PINNED_COMMIT
    ):
        raise ValueError("owned substrate manifest does not retain the audited pin")
    if verification.manifest_sha256 != manifest.manifest_sha256:
        raise ValueError("substrate verification manifest binding drift")
    inputs = _tree_summary(run_root / "inputs/autoresearchclaw", max_bytes=2**63 - 1)
    work = _tree_summary(run_root / "work/autoresearchclaw", max_bytes=2**63 - 1)
    if inputs.fingerprint != verification.input_snapshot_sha256:
        raise ValueError("substrate input snapshot hash drift")
    if work.fingerprint != verification.working_tree_sha256:
        raise ValueError("substrate working tree hash drift")
    if _file_sha256(run_root / "inputs/autoresearchclaw-config.yaml") != (
        manifest.executor_config_sha256
    ):
        raise ValueError("owned AutoResearchClaw configuration hash drift")
    for locator, digest in verification.evidence_sha256.items():
        path = run_root / locator
        if path.is_symlink() or not path.is_file() or _file_sha256(path) != digest:
            raise ValueError("substrate stage evidence hash drift")


def _archive_attempt(run_root: Path) -> str | None:
    sources = [run_root / "work", run_root / "substrate_action"]
    existing = [path for path in sources if path.exists()]
    if not existing:
        return None
    archive_root = run_root / "failed_attempts"
    archive_root.mkdir(parents=True, exist_ok=True)
    index = 1
    while (archive_root / f"attempt-{index:03d}").exists():
        index += 1
    destination = archive_root / f"attempt-{index:03d}"
    destination.mkdir()
    for source in existing:
        os.replace(source, destination / source.name)
    return destination.relative_to(run_root).as_posix()


def _write_model_exclusive(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = model.model_dump_json(indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)

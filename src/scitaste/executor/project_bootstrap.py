"""Project-owned creation of a verified AutoResearchClaw prerequisite source."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.autoresearchclaw import PINNED_COMMIT, AutoResearchClawExecutor
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.call_protocol import (
    ExternalCallProtocol,
    tree_fingerprint,
)
from scitaste.executor.project_workflow import (
    ProjectSubstrateActionWorkflow,
    ProjectSubstrateWorkflowConfig,
    _acquire_run_lock,
    _copy_file_exclusive,
    _copy_tree_exclusive,
    _external_call_attempt,
    _file_sha256,
    _fsync_directory,
    _is_sha256,
    _prepare_owned_parent,
    _registered_run,
    _release_run_lock,
    _require_owned_directory,
    _require_owned_run_root,
    _run_root,
    _tree_summary,
    _TreeSummary,
    _validate_call_phase_cache,
    _workflow_config_sha256,
    _write_model_exclusive,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.schema.actions import MetaAction

_BOOTSTRAP_TARGET = "PROBLEM_DECOMPOSE"
_PREFIX_ARTIFACTS = (
    "stage-01/goal.md",
    "stage-01/hardware_profile.json",
    "stage-02/problem_tree.md",
    "checkpoint.json",
    "pipeline_summary.json",
)


class ProjectSubstrateBootstrapManifest(BaseModel):
    """Immutable request identity published before the bootstrap provider call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    project_id: str
    run_id: str
    selected_action_type: Literal[MetaAction.SEARCH] = MetaAction.SEARCH
    target_stage: Literal["PROBLEM_DECOMPOSE"] = _BOOTSTRAP_TARGET
    seed: int = Field(ge=0)
    workflow_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_substrate_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    actual_substrate_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    external_call_protocol_version: Literal["1.0"] | None = None
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
    def create(cls, **payload: Any) -> ProjectSubstrateBootstrapManifest:
        canonical = {key: value for key, value in payload.items() if value is not None}
        draft = cls.model_construct(**canonical, manifest_sha256="0" * 64)
        identity = draft.model_dump(
            mode="json",
            exclude={"manifest_sha256"},
            exclude_none=True,
        )
        return cls.model_validate({**identity, "manifest_sha256": content_sha256(identity)})

    @model_validator(mode="after")
    def self_hash_matches(self) -> ProjectSubstrateBootstrapManifest:
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"}, exclude_none=True)
        )
        if self.manifest_sha256 != expected:
            raise ValueError("project substrate bootstrap manifest hash mismatch")
        if (
            self.expected_substrate_commit != PINNED_COMMIT
            or self.actual_substrate_commit != PINNED_COMMIT
        ):
            raise ValueError("project substrate bootstrap manifest pin mismatch")
        if (self.schema_version == "1.2") != (self.external_call_protocol_version == "1.0"):
            raise ValueError("bootstrap call protocol version disagrees with schema")
        return self


class ProjectSubstrateSourceReceipt(BaseModel):
    """Verified result of creating a reusable project-owned source snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_status: ExecutionStatus
    executor_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_file_count: int = Field(ge=0)
    work_bytes: int = Field(ge=0)
    source_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_file_count: int | None = Field(default=None, ge=1)
    source_bytes: int | None = Field(default=None, ge=1)
    prefix_artifact_sha256: dict[str, str]
    telemetry_calls: int = Field(ge=0)
    telemetry_prompt_tokens: int = Field(ge=0)
    telemetry_completion_tokens: int = Field(ge=0)
    telemetry_total_tokens: int = Field(ge=0)
    api_cost_measured: bool
    api_cost_usd: float | None = Field(default=None, ge=0)
    wall_time_hours: float = Field(ge=0)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @field_validator("prefix_artifact_sha256")
    @classmethod
    def prefix_hashes_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        if any(locator not in _PREFIX_ARTIFACTS for locator in value):
            raise ValueError("bootstrap receipt contains an unknown prefix artifact")
        if any(not _is_sha256(digest) for digest in value.values()):
            raise ValueError("bootstrap prefix artifact hashes must be SHA-256")
        return value

    @classmethod
    def create(cls, **payload: Any) -> ProjectSubstrateSourceReceipt:
        return cls.model_validate({**payload, "receipt_sha256": content_sha256(payload)})

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> ProjectSubstrateSourceReceipt:
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("project substrate source receipt hash mismatch")
        if self.telemetry_total_tokens != (
            self.telemetry_prompt_tokens + self.telemetry_completion_tokens
        ):
            raise ValueError("bootstrap telemetry token totals disagree")
        succeeded = self.execution_status is ExecutionStatus.SUCCEEDED
        complete_source = (
            self.source_snapshot_sha256 is not None
            and self.source_file_count is not None
            and self.source_bytes is not None
            and set(self.prefix_artifact_sha256) == set(_PREFIX_ARTIFACTS)
        )
        if succeeded != complete_source:
            raise ValueError("bootstrap success and reusable source evidence disagree")
        if self.api_cost_measured != (self.api_cost_usd is not None):
            raise ValueError("bootstrap API-cost measurement fields disagree")
        return self


class ProjectSubstrateBootstrapWorkflow:
    """Create Stage 1--2 evidence for a later project-owned SEARCH action."""

    def __init__(self, *, seed: int = 0, command_runner: Any | None = None) -> None:
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
        resume: bool = False,
        allow_live: bool = False,
    ) -> dict[str, object]:
        self._validate_config(config)
        validate_entry_id(run_id, field_name="run_id")
        runtime = ProjectRuntime(outputs_root)
        executor = self._executor(config, dry_run=True)
        substrate = executor.verify_substrate()
        if not substrate["initialized"] or not substrate["pinned"]:
            raise ValueError("AutoResearchClaw does not match the audited substrate pin")
        workflow_hash = _workflow_config_sha256(config)
        executor_hash = _file_sha256(config.autoresearchclaw_config)
        recovery_without_provider_available = False
        resume_disposition = "prepare_and_call"
        call_phase: str | None = None
        if resume:
            snapshot = runtime.open(config.project_id)
            run = _registered_run(snapshot, run_id)
            _require_owned_run_root(runtime, config.project_id, run_id)
            manifest = _load_manifest(_run_root(runtime, config.project_id, run_id))
            self._validate_resume_identity(
                config,
                run,
                manifest,
                workflow_hash=workflow_hash,
                executor_hash=executor_hash,
            )
            if (
                _file_sha256(
                    _run_root(runtime, config.project_id, run_id)
                    / "inputs/autoresearchclaw-config.yaml"
                )
                != executor_hash
            ):
                raise ValueError("owned bootstrap executor configuration hash drift")
            revision = snapshot.revision
            recovery_without_provider_available = _bootstrap_success_available(
                _run_root(runtime, config.project_id, run_id)
            )
            resume_disposition, call_phase = self._resume_disposition(
                runtime,
                snapshot,
                config,
                run_id,
                manifest,
            )
            recovery_without_provider_available = resume_disposition == "recover_result"
        else:
            try:
                existing = runtime.open(config.project_id)
            except FileNotFoundError:
                revision = 0
            else:
                ProjectSubstrateActionWorkflow._validate_project_identity(existing, config)
                revision = existing.revision
        return {
            "schema_version": "1.0",
            "status": "planned",
            "project_id": config.project_id,
            "run_id": run_id,
            "project_revision": revision,
            "selected_action_type": MetaAction.SEARCH.value,
            "target_stage": _BOOTSTRAP_TARGET,
            "seed": self.seed,
            "resume": resume,
            "live_config_enabled": config.live_enabled,
            "caller_live_authorized": allow_live,
            "would_contact_provider": bool(
                config.live_enabled
                and allow_live
                and resume_disposition in {"prepare_and_call", "retry_verified_failure"}
            ),
            "recovery_without_provider_available": recovery_without_provider_available,
            "resume_disposition": resume_disposition,
            "external_call_phase": call_phase,
            "workflow_config_sha256": workflow_hash,
            "executor_config_sha256": executor_hash,
            "expected_substrate_commit": PINNED_COMMIT,
            "actual_substrate_commit": str(substrate["actual_commit"]),
            "source_locator": f"projects/{config.project_id}/runs/{run_id}/source/autoresearchclaw",
        }

    def run(
        self,
        config: ProjectSubstrateWorkflowConfig,
        *,
        outputs_root: str | Path,
        run_id: str,
        resume: bool = False,
        allow_live: bool = False,
    ) -> dict[str, object]:
        plan = self.plan(
            config,
            outputs_root=outputs_root,
            run_id=run_id,
            resume=resume,
            allow_live=allow_live,
        )
        if not config.live_enabled:
            raise ValueError("project substrate bootstrap is disabled by configuration")
        if not allow_live:
            raise ValueError("project substrate bootstrap requires explicit caller live opt-in")
        runtime = ProjectRuntime(outputs_root)
        snapshot = ProjectSubstrateActionWorkflow._open_or_create_project(
            runtime,
            config,
            resume=resume,
        )
        if not resume:
            snapshot = runtime.begin_run(
                config.project_id,
                ProjectRun(
                    run_id=run_id,
                    provider=config.provider,
                    model=config.model,
                    condition=f"{config.condition}_bootstrap",
                    seed=self.seed,
                    status="running",
                    evidence_scope=config.evidence_scope,
                    stage_path="substrate_bootstrap",
                    workflow_config_sha256=plan["workflow_config_sha256"],
                    bootstrap_target_stage=_BOOTSTRAP_TARGET,
                    resume_attempt=0,
                    external_call_protocol_version="1.0",
                    external_call_attempt=1,
                ),
                expected_revision=snapshot.revision,
            )
        run_root = _run_root(runtime, config.project_id, run_id)
        _require_owned_run_root(runtime, config.project_id, run_id)
        run_lock = _acquire_run_lock(run_root)
        try:
            _require_owned_directory(
                run_root,
                run_root / "substrate_bootstrap",
                label="substrate bootstrap",
            )
            snapshot = runtime.open(config.project_id)
            resume_prepared = False
            if resume:
                for name in ("inputs", "work"):
                    _require_owned_directory(
                        run_root,
                        run_root / name,
                        label=f"bootstrap {name}",
                    )
                snapshot, resume_attempt = self._resume_run(
                    runtime,
                    snapshot,
                    config,
                    run_id,
                    workflow_hash=str(plan["workflow_config_sha256"]),
                    resume_disposition=str(plan["resume_disposition"]),
                )
                registered = _registered_run(snapshot, run_id)
                external_call_attempt = (
                    _external_call_attempt(registered)
                    if (registered.model_extra or {}).get("external_call_protocol_version") == "1.0"
                    else 1
                )
            else:
                resume_attempt = 0
                external_call_attempt = 1
            if not resume:
                _copy_file_exclusive(
                    config.autoresearchclaw_config,
                    run_root / "inputs/autoresearchclaw-config.yaml",
                )
                if (
                    _file_sha256(run_root / "inputs/autoresearchclaw-config.yaml")
                    != plan["executor_config_sha256"]
                ):
                    raise ValueError("executor configuration changed before bootstrap execution")
                manifest = self._publish_manifest(run_root, config, plan)
                snapshot = runtime.update_run(
                    config.project_id,
                    run_id,
                    expected_revision=snapshot.revision,
                    bootstrap_manifest_sha256=manifest.manifest_sha256,
                )
                snapshot = runtime.select_run(
                    config.project_id,
                    run_id,
                    expected_revision=snapshot.revision,
                )
                archived_attempt = None
            else:
                manifest = _load_manifest(run_root)
                recovered = self._recover_paid_success(run_root, manifest, config)
                if recovered is not None:
                    return self._register_result(
                        runtime,
                        snapshot,
                        config,
                        run_id,
                        plan,
                        manifest,
                        recovered,
                        resume_attempt=resume_attempt,
                        archived_attempt=None,
                        recovered_without_provider=True,
                    )
                if plan["resume_disposition"] == "prepare_and_call":
                    self._require_prepared_retry(
                        runtime,
                        snapshot,
                        run_root,
                        manifest,
                        config,
                        run_id,
                    )
                    resume_prepared = True
                    archived_attempt = None
                else:
                    self._require_retry_safe(run_root, manifest, config)
                    archived_attempt = _archive_attempt(run_root)
                    external_call_attempt += 1
                    snapshot = runtime.update_run(
                        config.project_id,
                        run_id,
                        expected_revision=snapshot.revision,
                        external_call_protocol_version="1.0",
                        external_call_attempt=external_call_attempt,
                        external_call_phase=None,
                        external_call_phase_sha256=None,
                        external_call_request_sha256=None,
                    )
                    (run_root / "substrate_bootstrap").mkdir(parents=True, exist_ok=False)
            work_root = run_root / "work/autoresearchclaw"
            if not resume_prepared:
                _prepare_owned_parent(run_root, work_root.parent)
                work_root.mkdir(exist_ok=False)
            protocol = ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol")
            call_spec_sha256 = _bootstrap_call_spec_sha256(config, run_root)
            if resume_prepared:
                prepared = protocol.require_prepared(
                    project_id=config.project_id,
                    run_id=run_id,
                    operation="bootstrap",
                    external_call_attempt=external_call_attempt,
                    request_sha256=manifest.manifest_sha256,
                    call_spec_sha256=call_spec_sha256,
                    pre_call_work_sha256=tree_fingerprint(work_root),
                )
            else:
                prepared = protocol.publish_prepared(
                    project_id=config.project_id,
                    run_id=run_id,
                    operation="bootstrap",
                    external_call_attempt=external_call_attempt,
                    request_sha256=manifest.manifest_sha256,
                    call_spec_sha256=call_spec_sha256,
                    pre_call_work_sha256=tree_fingerprint(work_root),
                )
            snapshot = runtime.update_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
                external_call_protocol_version="1.0",
                external_call_attempt=external_call_attempt,
                external_call_phase=prepared.phase.value,
                external_call_phase_sha256=prepared.receipt_sha256,
                external_call_request_sha256=manifest.manifest_sha256,
            )
            live_executor = self._executor(
                config,
                dry_run=False,
                config_path=run_root / "inputs/autoresearchclaw-config.yaml",
            )
            substrate = live_executor.verify_substrate()
            if (
                not substrate["initialized"]
                or not substrate["pinned"]
                or _file_sha256(run_root / "inputs/autoresearchclaw-config.yaml")
                != manifest.executor_config_sha256
                or tree_fingerprint(work_root) != prepared.pre_call_work_sha256
                or _bootstrap_call_spec_sha256(config, run_root) != prepared.call_spec_sha256
            ):
                raise ValueError("bootstrap call failed its final local preflight")
            started = protocol.publish_call_started()
            result = live_executor.baseline_run(
                topic=config.research_direction,
                output_dir=work_root,
                to_stage=_BOOTSTRAP_TARGET,
            )
            result = result.model_copy(
                update={
                    "data": {
                        **result.data,
                        "bootstrap_manifest_sha256": manifest.manifest_sha256,
                        "call_started_sha256": started.receipt_sha256,
                    }
                }
            )
            result_path = run_root / "substrate_bootstrap/executor_result.json"
            _write_model_exclusive(result_path, result)
            protocol.publish_result(
                executor_result_sha256=_file_sha256(result_path),
                result_work_tree_sha256=tree_fingerprint(work_root),
                result_id=result.result_id,
                execution_status=result.status,
            )
            receipt = self._build_receipt(run_root, manifest, result, config)
            _write_model_exclusive(
                run_root / "substrate_bootstrap/source_receipt.json",
                receipt,
            )
            return self._register_result(
                runtime,
                snapshot,
                config,
                run_id,
                plan,
                manifest,
                receipt,
                resume_attempt=resume_attempt,
                archived_attempt=archived_attempt,
                recovered_without_provider=False,
            )
        except BaseException as exc:
            ProjectSubstrateActionWorkflow._mark_failed(runtime, config.project_id, run_id, exc)
            raise
        finally:
            _release_run_lock(run_lock)

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
        run_root = _require_owned_run_root(runtime, project_id, run_id)
        for name in ("inputs", "work", "substrate_bootstrap"):
            _require_owned_directory(
                run_root,
                run_root / name,
                label=f"bootstrap {name}",
            )
        manifest = _load_manifest(run_root)
        receipt = _load_receipt(run_root)
        if receipt.execution_status is ExecutionStatus.SUCCEEDED:
            _require_owned_directory(
                run_root,
                run_root / "source",
                label="bootstrap source",
            )
        _verify_receipt(run_root, manifest, receipt)
        extra = run.model_extra or {}
        phase_aware = (
            manifest.schema_version == "1.2" or extra.get("external_call_protocol_version") == "1.0"
        )
        call_phase = "legacy_unjournaled"
        call_phase_sha256: str | None = None
        if phase_aware:
            result = _load_bootstrap_result(run_root)
            if result is None:
                raise ValueError("completed bootstrap has no executor result")
            protocol = ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol")
            chain = protocol.load(required=True)
            _validate_call_phase_cache(run, chain)
            if len(chain) < 2 or result.data.get("call_started_sha256") != chain[1].receipt_sha256:
                raise ValueError("completed bootstrap result call-start binding drift")
            phase_receipt = protocol.require_result(
                project_id=project_id,
                run_id=run_id,
                operation="bootstrap",
                external_call_attempt=_external_call_attempt(run),
                request_sha256=manifest.manifest_sha256,
                call_spec_sha256=chain[0].call_spec_sha256,
                pre_call_work_sha256=chain[0].pre_call_work_sha256,
                result_path=run_root / "substrate_bootstrap/executor_result.json",
                result_work_tree_sha256=tree_fingerprint(run_root / "work/autoresearchclaw"),
                result_id=result.result_id,
                execution_status=result.status,
            )
            call_phase = phase_receipt.phase.value
            call_phase_sha256 = phase_receipt.receipt_sha256
        expected_status = (
            "complete" if receipt.execution_status is ExecutionStatus.SUCCEEDED else "failed"
        )
        expected = {
            "workflow_config_sha256": manifest.workflow_config_sha256,
            "bootstrap_target_stage": manifest.target_stage,
            "bootstrap_manifest_sha256": manifest.manifest_sha256,
            "source_receipt_sha256": receipt.receipt_sha256,
            "source_snapshot_sha256": receipt.source_snapshot_sha256,
            "execution_status": receipt.execution_status.value,
        }
        if phase_aware:
            expected.update(
                {
                    "external_call_protocol_version": "1.0",
                    "external_call_attempt": chain[-1].external_call_attempt,
                    "external_call_phase": call_phase,
                    "external_call_phase_sha256": call_phase_sha256,
                    "external_call_request_sha256": manifest.manifest_sha256,
                }
            )
        if (
            run.status != expected_status
            or run.seed != manifest.seed
            or run.stage_path != "substrate_bootstrap"
            or any(extra.get(key) != value for key, value in expected.items())
        ):
            raise ValueError("registered substrate bootstrap metadata drift")
        return {
            "schema_version": "1.0",
            "status": "verified",
            "project_id": project_id,
            "run_id": run_id,
            "project_revision": snapshot.revision,
            "run_status": run.status,
            "execution_status": receipt.execution_status.value,
            "manifest_sha256": manifest.manifest_sha256,
            "source_receipt_sha256": receipt.receipt_sha256,
            "source_snapshot_sha256": receipt.source_snapshot_sha256,
            "source_file_count": receipt.source_file_count,
            "source_bytes": receipt.source_bytes,
            "telemetry_total_tokens": receipt.telemetry_total_tokens,
            "api_cost_measured": receipt.api_cost_measured,
            "external_call_phase": call_phase,
            "external_call_phase_sha256": call_phase_sha256,
            "source_locator": f"projects/{project_id}/runs/{run_id}/source/autoresearchclaw",
        }

    def source_path(
        self,
        *,
        outputs_root: str | Path,
        project_id: str,
        run_id: str,
    ) -> tuple[Path, ProjectSubstrateSourceReceipt]:
        self.status(outputs_root=outputs_root, project_id=project_id, run_id=run_id)
        runtime = ProjectRuntime(outputs_root)
        run_root = _run_root(runtime, project_id, run_id)
        receipt = _load_receipt(run_root)
        if receipt.execution_status is not ExecutionStatus.SUCCEEDED:
            raise ValueError("failed project bootstrap has no reusable source")
        return run_root / "source/autoresearchclaw", receipt

    @staticmethod
    def _validate_config(config: ProjectSubstrateWorkflowConfig) -> None:
        if config.action_type is not MetaAction.SEARCH:
            raise ValueError("project bootstrap currently supports only a SEARCH prerequisite")

    def _executor(
        self,
        config: ProjectSubstrateWorkflowConfig,
        *,
        dry_run: bool,
        config_path: Path | None = None,
    ) -> AutoResearchClawExecutor:
        return AutoResearchClawExecutor(
            config_path=config_path or config.autoresearchclaw_config,
            dry_run=dry_run,
            timeout_seconds=config.timeout_seconds,
            max_output_tokens=config.max_output_tokens,
            max_total_tokens=config.max_total_tokens,
            command_runner=self.command_runner,
        )

    def _publish_manifest(
        self,
        run_root: Path,
        config: ProjectSubstrateWorkflowConfig,
        plan: dict[str, object],
    ) -> ProjectSubstrateBootstrapManifest:
        manifest = ProjectSubstrateBootstrapManifest.create(
            schema_version="1.2",
            project_id=config.project_id,
            run_id=run_root.name,
            selected_action_type=MetaAction.SEARCH,
            target_stage=_BOOTSTRAP_TARGET,
            seed=self.seed,
            workflow_config_sha256=plan["workflow_config_sha256"],
            executor_config_sha256=plan["executor_config_sha256"],
            expected_substrate_commit=PINNED_COMMIT,
            actual_substrate_commit=plan["actual_substrate_commit"],
            external_call_protocol_version="1.0",
        )
        _write_model_exclusive(run_root / "bootstrap_manifest.json", manifest)
        return manifest

    def _resume_run(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: ProjectSubstrateWorkflowConfig,
        run_id: str,
        *,
        workflow_hash: str,
        resume_disposition: str,
    ) -> tuple[ProjectSnapshot, int]:
        run = _registered_run(snapshot, run_id)
        manifest = _load_manifest(_run_root(runtime, config.project_id, run_id))
        self._validate_resume_identity(
            config,
            run,
            manifest,
            workflow_hash=workflow_hash,
            executor_hash=_file_sha256(config.autoresearchclaw_config),
        )
        if run.status not in {"failed", "running"}:
            raise ValueError("only a failed or recoverable running bootstrap can be resumed")
        if resume_disposition in {"blocked_ambiguous", "legacy_read_only"}:
            if run.status == "running":
                raise ValueError(
                    "running bootstrap result publication is ambiguous; refusing a repeated call"
                )
            raise ValueError("bootstrap result publication is ambiguous; refusing a repeated call")
        attempt = (run.model_extra or {}).get("resume_attempt", 0)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            raise ValueError("registered bootstrap run has an invalid resume_attempt")
        snapshot = runtime.update_run(
            config.project_id,
            run_id,
            expected_revision=snapshot.revision,
            status="running",
            resume_attempt=attempt + 1,
        )
        if snapshot.manifest.current_run != run_id:
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
        return snapshot, attempt + 1

    def _validate_resume_identity(
        self,
        config: ProjectSubstrateWorkflowConfig,
        run: ProjectRun,
        manifest: ProjectSubstrateBootstrapManifest,
        *,
        workflow_hash: str,
        executor_hash: str,
    ) -> None:
        if manifest.schema_version == "1.0":
            raise ValueError("legacy bootstrap runs lack no-repeat evidence and are read-only")
        expected = (
            config.project_id,
            run.run_id,
            self.seed,
            workflow_hash,
            executor_hash,
        )
        observed = (
            manifest.project_id,
            manifest.run_id,
            manifest.seed,
            manifest.workflow_config_sha256,
            manifest.executor_config_sha256,
        )
        if observed != expected:
            raise ValueError("resume configuration does not match bootstrap manifest identity")
        run_expected = (
            config.provider,
            config.model,
            f"{config.condition}_bootstrap",
            self.seed,
            config.evidence_scope,
            "substrate_bootstrap",
        )
        run_observed = (
            run.provider,
            run.model,
            run.condition,
            run.seed,
            run.evidence_scope,
            run.stage_path,
        )
        if run_observed != run_expected:
            raise ValueError("resume configuration does not match registered bootstrap run")
        extra = run.model_extra or {}
        if (
            extra.get("workflow_config_sha256") != workflow_hash
            or extra.get("bootstrap_target_stage") != manifest.target_stage
            or extra.get("bootstrap_manifest_sha256") != manifest.manifest_sha256
        ):
            raise ValueError("registered bootstrap pre-call identity drift")

    def _recover_paid_success(
        self,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        config: ProjectSubstrateWorkflowConfig,
    ) -> ProjectSubstrateSourceReceipt | None:
        action_root = run_root / "substrate_bootstrap"
        _require_owned_directory(run_root, action_root, label="substrate bootstrap")
        receipt_path = action_root / "source_receipt.json"
        if receipt_path.exists() or receipt_path.is_symlink():
            receipt = _load_receipt(run_root)
            result = _load_bootstrap_result(run_root)
            if result is None:
                raise ValueError("bootstrap receipt has no recorded executor result")
            self._verify_recorded_result(run_root, manifest, config, result)
            self._verify_or_publish_call_result(run_root, manifest, config, result)
            _verify_receipt(run_root, manifest, receipt)
            if receipt.execution_status is ExecutionStatus.SUCCEEDED:
                return receipt
            return None
        result = _load_bootstrap_result(run_root)
        if result is None:
            return None
        self._verify_recorded_result(run_root, manifest, config, result)
        self._verify_or_publish_call_result(run_root, manifest, config, result)
        if result.status is not ExecutionStatus.SUCCEEDED:
            return None
        receipt = self._build_receipt(run_root, manifest, result, config)
        _write_model_exclusive(receipt_path, receipt)
        return receipt

    def _resume_disposition(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: ProjectSubstrateWorkflowConfig,
        run_id: str,
        manifest: ProjectSubstrateBootstrapManifest,
    ) -> tuple[str, str | None]:
        run_root = _run_root(runtime, config.project_id, run_id)
        result = _load_bootstrap_result(run_root)
        if manifest.schema_version == "1.0":
            return "legacy_read_only", None
        run = _registered_run(snapshot, run_id)
        phase_aware = (
            manifest.schema_version == "1.2"
            or (run.model_extra or {}).get("external_call_protocol_version") == "1.0"
        )
        if not phase_aware:
            if result is None:
                return "blocked_ambiguous", None
            if result.status is ExecutionStatus.SUCCEEDED:
                return "recover_result", "legacy_result_published"
            if result.status is ExecutionStatus.FAILED:
                return "retry_verified_failure", "legacy_result_published"
            return "blocked_ambiguous", None

        if (run.model_extra or {}).get("external_call_protocol_version") != "1.0":
            raise ValueError("registered bootstrap call protocol version drift")
        attempt = _external_call_attempt(run)
        protocol = ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol")
        chain = protocol.load(required=True)
        expected_identity = (
            config.project_id,
            run_id,
            "bootstrap",
            attempt,
            manifest.manifest_sha256,
            _bootstrap_call_spec_sha256(config, run_root),
        )
        observed_identity = (
            chain[0].project_id,
            chain[0].run_id,
            chain[0].operation,
            chain[0].external_call_attempt,
            chain[0].request_sha256,
            chain[0].call_spec_sha256,
        )
        if observed_identity != expected_identity:
            raise ValueError("bootstrap call protocol identity drift")
        _validate_call_phase_cache(run, chain)
        phase = chain[-1].phase.value
        work_root = run_root / "work/autoresearchclaw"
        if len(chain) == 1:
            if result is not None:
                raise ValueError("bootstrap result exists before call-start evidence")
            protocol.require_prepared(
                project_id=config.project_id,
                run_id=run_id,
                operation="bootstrap",
                external_call_attempt=attempt,
                request_sha256=manifest.manifest_sha256,
                call_spec_sha256=_bootstrap_call_spec_sha256(config, run_root),
                pre_call_work_sha256=tree_fingerprint(work_root),
            )
            return "prepare_and_call", phase
        if result is None:
            return "blocked_ambiguous", phase
        if result.data.get("call_started_sha256") != chain[1].receipt_sha256:
            raise ValueError("bootstrap result call-start binding drift")
        if len(chain) == 3:
            protocol.require_result(
                project_id=config.project_id,
                run_id=run_id,
                operation="bootstrap",
                external_call_attempt=attempt,
                request_sha256=manifest.manifest_sha256,
                call_spec_sha256=_bootstrap_call_spec_sha256(config, run_root),
                pre_call_work_sha256=chain[0].pre_call_work_sha256,
                result_path=run_root / "substrate_bootstrap/executor_result.json",
                result_work_tree_sha256=tree_fingerprint(work_root),
                result_id=result.result_id,
                execution_status=result.status,
            )
        if result.status is ExecutionStatus.SUCCEEDED:
            return "recover_result", phase
        if result.status is ExecutionStatus.FAILED:
            return "retry_verified_failure", phase
        return "blocked_ambiguous", phase

    def _require_prepared_retry(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        config: ProjectSubstrateWorkflowConfig,
        run_id: str,
    ) -> None:
        if (
            manifest.schema_version != "1.2"
            and (_registered_run(snapshot, run_id).model_extra or {}).get(
                "external_call_protocol_version"
            )
            != "1.0"
        ):
            raise ValueError("only phase-aware bootstrap runs can resume before call start")
        if _load_bootstrap_result(run_root) is not None:
            raise ValueError("prepared bootstrap attempt unexpectedly has an executor result")
        run = _registered_run(snapshot, run_id)
        ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol").require_prepared(
            project_id=config.project_id,
            run_id=run_id,
            operation="bootstrap",
            external_call_attempt=_external_call_attempt(run),
            request_sha256=manifest.manifest_sha256,
            call_spec_sha256=_bootstrap_call_spec_sha256(config, run_root),
            pre_call_work_sha256=tree_fingerprint(run_root / "work/autoresearchclaw"),
        )

    def _require_retry_safe(
        self,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        config: ProjectSubstrateWorkflowConfig,
    ) -> None:
        result = _load_bootstrap_result(run_root)
        if result is None:
            raise ValueError("bootstrap result publication is ambiguous; refusing a repeated call")
        self._verify_recorded_result(run_root, manifest, config, result)
        self._verify_or_publish_call_result(run_root, manifest, config, result)
        if result.status is not ExecutionStatus.FAILED:
            raise ValueError("a successful bootstrap result must be recovered, not retried")

    def _verify_or_publish_call_result(
        self,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        config: ProjectSubstrateWorkflowConfig,
        result: ExecutionResult,
    ) -> None:
        protocol_root = run_root / "substrate_bootstrap/call_protocol"
        phase_aware = manifest.schema_version == "1.2" or protocol_root.exists()
        if not phase_aware:
            return
        protocol = ExternalCallProtocol(protocol_root)
        chain = protocol.load(required=True)
        if len(chain) < 2 or result.data.get("call_started_sha256") != chain[1].receipt_sha256:
            raise ValueError("recorded bootstrap result call-start binding drift")
        protocol.require_result(
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            operation="bootstrap",
            external_call_attempt=chain[0].external_call_attempt,
            request_sha256=manifest.manifest_sha256,
            call_spec_sha256=_bootstrap_call_spec_sha256(config, run_root),
            pre_call_work_sha256=chain[0].pre_call_work_sha256,
            result_path=run_root / "substrate_bootstrap/executor_result.json",
            result_work_tree_sha256=tree_fingerprint(run_root / "work/autoresearchclaw"),
            result_id=result.result_id,
            execution_status=result.status,
            allow_unjournaled_publication=len(chain) == 2,
        )

    def _verify_recorded_result(
        self,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        config: ProjectSubstrateWorkflowConfig,
        result: ExecutionResult,
    ) -> None:
        work_root = run_root / "work/autoresearchclaw"
        executor = self._executor(
            config,
            dry_run=False,
            config_path=run_root / "inputs/autoresearchclaw-config.yaml",
        )
        substrate = executor.verify_substrate()
        command = executor._base_command(
            topic=config.research_direction,
            output_dir=work_root,
        )
        command.extend(["--to-stage", _BOOTSTRAP_TARGET])
        if (
            result.action_id != "baseline-run"
            or result.executor != "autoresearchclaw"
            or result.data.get("command") != command
            or result.data.get("substrate") != substrate
            or result.data.get("bootstrap_manifest_sha256") != manifest.manifest_sha256
        ):
            raise ValueError("recorded bootstrap result identity drift")
        normalized = executor._normalize_run(
            work_root,
            _BOOTSTRAP_TARGET,
            prior_checkpoint={},
            prior_api_cost_usd=None,
        )
        for key, value in normalized.items():
            if result.data.get(key) != value:
                raise ValueError(f"recorded bootstrap normalized {key} drift")
        if result.artifacts != [item["path"] for item in normalized["artifact_manifest"]]:
            raise ValueError("recorded bootstrap artifact manifest drift")
        expected_api_cost = normalized["cost"].get("api_cost_usd")
        if result.cost.get("api_cost_usd") != expected_api_cost:
            raise ValueError("recorded bootstrap incremental API cost drift")
        wall_time = result.cost.get("wall_time_hours")
        if wall_time is None or not math.isfinite(wall_time) or wall_time < 0:
            raise ValueError("recorded bootstrap wall time drift")
        if set(result.cost) not in ({"wall_time_hours"}, {"api_cost_usd", "wall_time_hours"}):
            raise ValueError("recorded bootstrap cost fields drift")
        validation_error = normalized.get("validation_error")
        if result.status is ExecutionStatus.FAILED and validation_error is None:
            raise ValueError("recorded bootstrap failure contradicts successful terminal evidence")
        if result.data.get("partial_after_timeout") is True:
            expected_error = f"AutoResearchClaw command timed out after {config.timeout_seconds:g}s"
            if (
                result.status is not ExecutionStatus.FAILED
                or "returncode" in result.data
                or result.error != expected_error
            ):
                raise ValueError("recorded bootstrap timeout evidence drift")
            return
        returncode = result.data.get("returncode")
        if not isinstance(returncode, int) or isinstance(returncode, bool):
            raise ValueError("recorded bootstrap result has no trusted process outcome")
        succeeded = returncode == 0 and validation_error is None
        expected_status = ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED
        expected_error = (
            None if succeeded else str(validation_error or "AutoResearchClaw command failed")
        )
        if result.status is not expected_status or result.error != expected_error:
            raise ValueError("recorded bootstrap terminal outcome drift")

    def _build_receipt(
        self,
        run_root: Path,
        manifest: ProjectSubstrateBootstrapManifest,
        result: ExecutionResult,
        config: ProjectSubstrateWorkflowConfig,
    ) -> ProjectSubstrateSourceReceipt:
        work_root = run_root / "work/autoresearchclaw"
        if (
            _file_sha256(run_root / "inputs/autoresearchclaw-config.yaml")
            != manifest.executor_config_sha256
        ):
            raise ValueError("owned bootstrap executor configuration hash drift")
        work = _tree_summary_allow_empty(work_root, max_bytes=config.max_snapshot_bytes)
        prefix: dict[str, str] = {}
        source = None
        if result.status is ExecutionStatus.SUCCEEDED:
            prefix = _validate_prefix(work_root)
            source_root = run_root / "source/autoresearchclaw"
            if not source_root.exists():
                _copy_tree_exclusive(work_root, source_root)
            source = _tree_summary(source_root, max_bytes=config.max_snapshot_bytes)
            if source.fingerprint != work.fingerprint:
                raise ValueError("bootstrap source copy does not match its working tree")
        telemetry = _read_telemetry(work_root / "scitaste_llm_telemetry.jsonl")
        result_path = run_root / "substrate_bootstrap/executor_result.json"
        accounting = result.data.get("cost_accounting", {})
        measured_raw = accounting.get("api_cost_measured") if isinstance(accounting, dict) else None
        if not isinstance(measured_raw, bool):
            raise ValueError("bootstrap executor result has invalid API-cost provenance")
        measured = measured_raw
        api_cost = result.cost.get("api_cost_usd") if measured else None
        wall_time = float(result.cost.get("wall_time_hours", 0.0) or 0.0)
        return ProjectSubstrateSourceReceipt.create(
            schema_version="1.0",
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            manifest_sha256=manifest.manifest_sha256,
            execution_status=result.status,
            executor_result_sha256=_file_sha256(result_path),
            work_snapshot_sha256=work.fingerprint,
            work_file_count=work.file_count,
            work_bytes=work.total_bytes,
            source_snapshot_sha256=source.fingerprint if source else None,
            source_file_count=source.file_count if source else None,
            source_bytes=source.total_bytes if source else None,
            prefix_artifact_sha256=prefix,
            telemetry_calls=telemetry["calls"],
            telemetry_prompt_tokens=telemetry["prompt_tokens"],
            telemetry_completion_tokens=telemetry["completion_tokens"],
            telemetry_total_tokens=telemetry["total_tokens"],
            api_cost_measured=measured,
            api_cost_usd=api_cost,
            wall_time_hours=wall_time,
        )

    @staticmethod
    def _register_result(
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: ProjectSubstrateWorkflowConfig,
        run_id: str,
        plan: dict[str, object],
        manifest: ProjectSubstrateBootstrapManifest,
        receipt: ProjectSubstrateSourceReceipt,
        *,
        resume_attempt: int,
        archived_attempt: str | None,
        recovered_without_provider: bool,
    ) -> dict[str, object]:
        complete = receipt.execution_status is ExecutionStatus.SUCCEEDED
        status = "complete" if complete else "failed"
        run_root = _run_root(runtime, config.project_id, run_id)
        protocol = ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol")
        chain = protocol.load(required=False)
        call_phase = chain[-1].phase.value if chain else "legacy_unjournaled"
        call_phase_sha256 = chain[-1].receipt_sha256 if chain else None
        external_call_attempt = chain[-1].external_call_attempt if chain else None
        snapshot = runtime.update_run(
            config.project_id,
            run_id,
            expected_revision=snapshot.revision,
            status=status,
            artifact=f"runs/{run_id}/substrate_bootstrap/source_receipt.json",
            bootstrap_manifest_sha256=manifest.manifest_sha256,
            source_receipt_sha256=receipt.receipt_sha256,
            source_snapshot_sha256=receipt.source_snapshot_sha256,
            execution_status=receipt.execution_status.value,
            recovered_without_provider=recovered_without_provider,
            external_call_protocol_version="1.0" if chain else None,
            external_call_attempt=external_call_attempt,
            external_call_phase=call_phase,
            external_call_phase_sha256=call_phase_sha256,
            external_call_request_sha256=manifest.manifest_sha256 if chain else None,
            failure_type=None,
            failure_message=None,
        )
        return {
            **plan,
            "status": status,
            "project_revision": snapshot.revision,
            "resume_attempt": resume_attempt,
            "archived_attempt": archived_attempt,
            "recovered_without_provider": recovered_without_provider,
            "execution_status": receipt.execution_status.value,
            "manifest_sha256": manifest.manifest_sha256,
            "source_receipt_sha256": receipt.receipt_sha256,
            "source_snapshot_sha256": receipt.source_snapshot_sha256,
            "source_file_count": receipt.source_file_count,
            "source_bytes": receipt.source_bytes,
            "telemetry_total_tokens": receipt.telemetry_total_tokens,
            "api_cost_measured": receipt.api_cost_measured,
            "external_call_phase": call_phase,
            "external_call_phase_sha256": call_phase_sha256,
        }


def _load_manifest(run_root: Path) -> ProjectSubstrateBootstrapManifest:
    path = run_root / "bootstrap_manifest.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("bootstrap manifest must be a regular owned file")
    return ProjectSubstrateBootstrapManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _bootstrap_call_spec_sha256(
    config: ProjectSubstrateWorkflowConfig,
    run_root: Path,
) -> str:
    config_path = run_root / "inputs/autoresearchclaw-config.yaml"
    executor = AutoResearchClawExecutor(
        config_path=config_path,
        timeout_seconds=config.timeout_seconds,
        max_output_tokens=config.max_output_tokens,
        max_total_tokens=config.max_total_tokens,
    )
    command = executor._base_command(
        topic=config.research_direction,
        output_dir=run_root / "work/autoresearchclaw",
    )
    command.extend(["--to-stage", _BOOTSTRAP_TARGET])
    return content_sha256(
        {
            "schema_version": "1.0",
            "operation": "bootstrap",
            "executor": "autoresearchclaw",
            "command": command,
            "timeout_seconds": config.timeout_seconds,
            "max_output_tokens": config.max_output_tokens,
            "max_total_tokens": config.max_total_tokens,
            "executor_config_sha256": _file_sha256(config_path),
            "substrate_commit": PINNED_COMMIT,
        }
    )


def _load_receipt(run_root: Path) -> ProjectSubstrateSourceReceipt:
    path = run_root / "substrate_bootstrap/source_receipt.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("bootstrap source receipt must be a regular owned file")
    return ProjectSubstrateSourceReceipt.model_validate_json(path.read_text(encoding="utf-8"))


def _load_bootstrap_result(run_root: Path) -> ExecutionResult | None:
    path = run_root / "substrate_bootstrap/executor_result.json"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("bootstrap executor result must be a regular owned file")
    try:
        return ExecutionResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid recorded bootstrap executor result") from exc


def _bootstrap_success_available(run_root: Path) -> bool:
    action_root = run_root / "substrate_bootstrap"
    _require_owned_directory(run_root, action_root, label="substrate bootstrap")
    receipt_path = action_root / "source_receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        return _load_receipt(run_root).execution_status is ExecutionStatus.SUCCEEDED
    result = _load_bootstrap_result(run_root)
    return result is not None and result.status is ExecutionStatus.SUCCEEDED


def _tree_summary_allow_empty(path: Path, *, max_bytes: int) -> _TreeSummary:
    root = path.resolve(strict=True)
    if not root.is_dir() or path.is_symlink():
        raise ValueError("AutoResearchClaw bootstrap work must be a regular directory")
    files: dict[str, str] = {}
    total = 0
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("AutoResearchClaw bootstrap work cannot contain symlinks")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("AutoResearchClaw bootstrap work contains a non-regular entry")
        total += candidate.stat().st_size
        if total > max_bytes:
            raise ValueError("AutoResearchClaw bootstrap work exceeds its byte limit")
        files[candidate.relative_to(root).as_posix()] = _file_sha256(candidate)
    return _TreeSummary(
        fingerprint=content_sha256(files),
        file_count=len(files),
        total_bytes=total,
        files=files,
    )


def _validate_prefix(work_root: Path) -> dict[str, str]:
    checkpoint = json.loads((work_root / "checkpoint.json").read_text(encoding="utf-8"))
    summary = json.loads((work_root / "pipeline_summary.json").read_text(encoding="utf-8"))
    if not isinstance(checkpoint, dict) or (
        checkpoint.get("last_completed_stage") != 2
        or checkpoint.get("last_completed_name") != _BOOTSTRAP_TARGET
    ):
        raise ValueError("bootstrap checkpoint does not confirm Stage 2 completion")
    if not isinstance(summary, dict) or (
        summary.get("final_status") != "done" or summary.get("final_stage") != 2
    ):
        raise ValueError("bootstrap summary does not confirm exact Stage 2 completion")
    evidence: dict[str, str] = {}
    for locator in _PREFIX_ARTIFACTS:
        path = work_root / locator
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"bootstrap omitted regular prefix artifact {locator}")
        evidence[locator] = _file_sha256(path)
    return evidence


def _read_telemetry(path: Path) -> dict[str, int]:
    totals = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if not path.is_file():
        return totals
    if path.is_symlink():
        raise ValueError("bootstrap telemetry cannot be a symbolic link")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            prompt = int(record["prompt_tokens"])
            completion = int(record["completion_tokens"])
            total = int(record["total_tokens"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid bootstrap telemetry at line {line_number}") from exc
        if min(prompt, completion, total) < 0 or total != prompt + completion:
            raise ValueError(f"inconsistent bootstrap telemetry at line {line_number}")
        totals["calls"] += 1
        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["total_tokens"] += total
    return totals


def _verify_receipt(
    run_root: Path,
    manifest: ProjectSubstrateBootstrapManifest,
    receipt: ProjectSubstrateSourceReceipt,
) -> None:
    if receipt.project_id != manifest.project_id or receipt.run_id != manifest.run_id:
        raise ValueError("bootstrap receipt belongs to another project run")
    if receipt.manifest_sha256 != manifest.manifest_sha256:
        raise ValueError("bootstrap receipt manifest binding drift")
    if _file_sha256(run_root / "inputs/autoresearchclaw-config.yaml") != (
        manifest.executor_config_sha256
    ):
        raise ValueError("owned bootstrap executor configuration hash drift")
    result_path = run_root / "substrate_bootstrap/executor_result.json"
    if result_path.is_symlink() or _file_sha256(result_path) != receipt.executor_result_sha256:
        raise ValueError("bootstrap executor result hash drift")
    result = ExecutionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    if result.status is not receipt.execution_status:
        raise ValueError("bootstrap executor result status drift")
    work = _tree_summary_allow_empty(run_root / "work/autoresearchclaw", max_bytes=2**63 - 1)
    if (
        work.fingerprint != receipt.work_snapshot_sha256
        or work.file_count != receipt.work_file_count
        or work.total_bytes != receipt.work_bytes
    ):
        raise ValueError("bootstrap working tree hash drift")
    telemetry = _read_telemetry(run_root / "work/autoresearchclaw/scitaste_llm_telemetry.jsonl")
    observed_telemetry = (
        telemetry["calls"],
        telemetry["prompt_tokens"],
        telemetry["completion_tokens"],
        telemetry["total_tokens"],
    )
    expected_telemetry = (
        receipt.telemetry_calls,
        receipt.telemetry_prompt_tokens,
        receipt.telemetry_completion_tokens,
        receipt.telemetry_total_tokens,
    )
    if observed_telemetry != expected_telemetry:
        raise ValueError("bootstrap telemetry receipt drift")
    accounting = result.data.get("cost_accounting", {})
    measured = accounting.get("api_cost_measured") if isinstance(accounting, dict) else None
    api_cost = result.cost.get("api_cost_usd") if measured is True else None
    wall_time = float(result.cost.get("wall_time_hours", 0.0) or 0.0)
    if (
        not isinstance(measured, bool)
        or receipt.api_cost_measured is not measured
        or receipt.api_cost_usd != api_cost
        or receipt.wall_time_hours != wall_time
    ):
        raise ValueError("bootstrap resource receipt drift")
    if receipt.execution_status is ExecutionStatus.SUCCEEDED:
        source = _tree_summary(
            run_root / "source/autoresearchclaw",
            max_bytes=2**63 - 1,
        )
        if (
            source.fingerprint != receipt.source_snapshot_sha256
            or source.file_count != receipt.source_file_count
            or source.total_bytes != receipt.source_bytes
            or _validate_prefix(run_root / "source/autoresearchclaw")
            != receipt.prefix_artifact_sha256
        ):
            raise ValueError("bootstrap source snapshot hash drift")


def _archive_attempt(run_root: Path) -> str | None:
    sources = [
        run_root / "work",
        run_root / "source",
        run_root / "substrate_bootstrap",
    ]
    existing = [path for path in sources if path.exists()]
    if not existing:
        return None
    archive_root = run_root / "failed_attempts"
    for source in existing:
        _require_owned_directory(run_root, source, label="archived bootstrap attempt")
    _prepare_owned_parent(run_root, archive_root)
    _fsync_directory(run_root)
    index = 1
    while (archive_root / f"attempt-{index:03d}").exists():
        index += 1
    destination = archive_root / f"attempt-{index:03d}"
    destination.mkdir()
    _fsync_directory(archive_root)
    _require_owned_directory(archive_root, destination, label="bootstrap attempt archive")
    for source in existing:
        os.replace(source, destination / source.name)
    _fsync_directory(destination)
    _fsync_directory(run_root)
    return destination.relative_to(run_root).as_posix()


__all__ = [
    "ProjectSubstrateBootstrapManifest",
    "ProjectSubstrateBootstrapWorkflow",
    "ProjectSubstrateSourceReceipt",
]

"""Project-owned orchestration for integrity-checked matched studies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scitaste.benchmark.study_execution import (
    MatchedStudyRunner,
    ProcessRunner,
    StudyLaunchConfig,
    StudyRunSummary,
)
from scitaste.benchmark.study_models import (
    CellStatus,
    MatchedStudyProtocol,
    StudyResults,
    SystemCondition,
)
from scitaste.project import (
    ProjectRevisionConflictError,
    ProjectRun,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import validate_entry_id, validate_project_id


class ProjectStudyConfig(BaseModel):
    """Stable project/run identity for one matched-study execution series."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    condition: str = "matched_budget_study"
    seed: int = Field(default=0, ge=0)
    evidence_scope: str = "phase9-engineering-evidence"

    @field_validator("project_id")
    @classmethod
    def project_id_is_canonical(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")


class ProjectStudySummary(BaseModel):
    """Machine-readable project and study outcome returned to later CLI/API layers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    run_status: Literal["planned", "partial", "complete", "failed"]
    project_revision: int = Field(ge=0)
    project_run_locator: str
    study: StudyRunSummary


class ProjectMatchedStudyRunner:
    """Run a matched study inside one existing ``ProjectRuntime`` project."""

    def __init__(
        self,
        runtime: ProjectRuntime,
        protocol: MatchedStudyProtocol,
        launch_config: StudyLaunchConfig,
        *,
        process_runner: ProcessRunner | None = None,
        clock: Callable[[], float] | None = None,
        asset_root: str | Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.protocol = protocol
        self.launch_config = launch_config
        self.process_runner = process_runner
        self.clock = clock
        self.asset_root = asset_root

    def run(
        self,
        config: ProjectStudyConfig,
        *,
        task_ids: list[str] | None = None,
        conditions: list[SystemCondition] | None = None,
        cell_ids: list[str] | None = None,
        max_cells: int | None = None,
        resume: bool = False,
        dry_run: bool = False,
    ) -> ProjectStudySummary:
        snapshot = self.runtime.open(config.project_id)
        study_runner = self._study_runner(config)
        identity = self._execution_identity(study_runner)
        registered = self._registered_run(snapshot, config.run_id)
        if dry_run:
            self._validate_dry_run(snapshot, registered, config, identity, resume=resume)
            study = study_runner.run(
                task_ids=task_ids,
                conditions=conditions,
                cell_ids=cell_ids,
                max_cells=max_cells,
                resume=resume,
                dry_run=True,
            )
            return self._summary(config, snapshot, study, run_status="planned")

        if resume:
            snapshot = self._resume(snapshot, registered, config, identity)
        else:
            if registered is not None:
                raise FileExistsError(self._run_root(config))
            snapshot = self._begin(snapshot, config, identity)
        expected_final_revision = snapshot.revision

        try:
            study = study_runner.run(
                task_ids=task_ids,
                conditions=conditions,
                cell_ids=cell_ids,
                max_cells=max_cells,
                resume=resume,
                dry_run=False,
            )
            if self._execution_identity(study_runner) != identity:
                raise ValueError("study execution identity changed during the run")
            status, recorded_cells = self._completion_status(config, study_runner)
            snapshot = self.runtime.update_run(
                config.project_id,
                config.run_id,
                expected_revision=expected_final_revision,
                status=status,
                artifact=f"runs/{config.run_id}/study/study_results.json",
                recorded_cells=recorded_cells,
                planned_cells=len(study_runner.plan.cells),
                protocol_sha256=identity[0],
                plan_sha256=identity[1],
                launch_config_sha256=identity[2],
                results_sha256=study.results_sha256,
                run_manifest_sha256=study.run_manifest_sha256,
                archived_attempts=study.archived_attempts,
            )
        except BaseException as exc:
            self._mark_failed(
                config,
                exc,
                expected_revision=expected_final_revision,
            )
            raise
        return self._summary(config, snapshot, study, run_status=status)

    def _study_runner(self, config: ProjectStudyConfig) -> MatchedStudyRunner:
        kwargs: dict[str, Any] = {
            "output_dir": self._run_root(config) / "study",
            "asset_root": self.asset_root,
        }
        if self.process_runner is not None:
            kwargs["process_runner"] = self.process_runner
        if self.clock is not None:
            kwargs["clock"] = self.clock
        return MatchedStudyRunner(self.protocol, self.launch_config, **kwargs)

    @staticmethod
    def _execution_identity(runner: MatchedStudyRunner) -> tuple[str, str, str]:
        return (runner.protocol.sha256, runner.plan.sha256, runner.launch_config.sha256)

    def _run_root(self, config: ProjectStudyConfig) -> Path:
        return self.runtime.projects_root / config.project_id / "runs" / config.run_id

    @staticmethod
    def _registered_run(snapshot: ProjectSnapshot, run_id: str) -> ProjectRun | None:
        return next((run for run in snapshot.manifest.runs if run.run_id == run_id), None)

    def _begin(
        self,
        snapshot: ProjectSnapshot,
        config: ProjectStudyConfig,
        identity: tuple[str, str, str],
    ) -> ProjectSnapshot:
        snapshot = self.runtime.begin_run(
            config.project_id,
            ProjectRun(
                run_id=config.run_id,
                provider=config.provider,
                model=config.model,
                condition=config.condition,
                seed=config.seed,
                status="running",
                evidence_scope=config.evidence_scope,
                stage_path="study",
                artifact=f"runs/{config.run_id}/study/study_results.json",
                protocol_sha256=identity[0],
                plan_sha256=identity[1],
                launch_config_sha256=identity[2],
                resume_attempt=0,
            ),
            expected_revision=snapshot.revision,
        )
        return self.runtime.select_run(
            config.project_id,
            config.run_id,
            expected_revision=snapshot.revision,
        )

    def _resume(
        self,
        snapshot: ProjectSnapshot,
        registered: ProjectRun | None,
        config: ProjectStudyConfig,
        identity: tuple[str, str, str],
    ) -> ProjectSnapshot:
        if registered is None:
            raise ValueError(f"cannot resume unknown project run {config.run_id!r}")
        self._validate_registered_run(registered, config, identity)
        self._validate_resume_status(registered)
        extra = registered.model_extra or {}
        resume_attempt = extra.get("resume_attempt", 0)
        if (
            not isinstance(resume_attempt, int)
            or isinstance(resume_attempt, bool)
            or resume_attempt < 0
        ):
            raise ValueError("registered matched-study run has an invalid resume_attempt")
        snapshot = self.runtime.update_run(
            config.project_id,
            config.run_id,
            expected_revision=snapshot.revision,
            status="running",
            resume_attempt=resume_attempt + 1,
        )
        if snapshot.manifest.current_run != config.run_id:
            snapshot = self.runtime.select_run(
                config.project_id,
                config.run_id,
                expected_revision=snapshot.revision,
            )
        return snapshot

    def _validate_dry_run(
        self,
        snapshot: ProjectSnapshot,
        registered: ProjectRun | None,
        config: ProjectStudyConfig,
        identity: tuple[str, str, str],
        *,
        resume: bool,
    ) -> None:
        if resume:
            if registered is None:
                raise ValueError(f"cannot resume unknown project run {config.run_id!r}")
            self._validate_registered_run(registered, config, identity)
            self._validate_resume_status(registered)
        elif registered is not None or self._run_root(config).exists():
            raise FileExistsError(self._run_root(config))

    @staticmethod
    def _validate_resume_status(run: ProjectRun) -> None:
        if run.status == "complete":
            raise ValueError("a completed matched-study run cannot be resumed")
        if run.status not in {"failed", "partial"}:
            raise ValueError(
                f"only failed or partial matched-study runs can be resumed, got {run.status!r}"
            )

    @staticmethod
    def _validate_registered_run(
        run: ProjectRun,
        config: ProjectStudyConfig,
        identity: tuple[str, str, str],
    ) -> None:
        observed = (
            run.provider,
            run.model,
            run.condition,
            run.seed,
            run.evidence_scope,
            run.stage_path,
        )
        expected = (
            config.provider,
            config.model,
            config.condition,
            config.seed,
            config.evidence_scope,
            "study",
        )
        if observed != expected:
            raise ValueError("resume configuration does not match the registered study run")
        extra = run.model_extra or {}
        recorded_identity = (
            extra.get("protocol_sha256"),
            extra.get("plan_sha256"),
            extra.get("launch_config_sha256"),
        )
        if recorded_identity != identity:
            raise ValueError("resume execution identity does not match the registered study run")

    def _completion_status(
        self,
        config: ProjectStudyConfig,
        runner: MatchedStudyRunner,
    ) -> tuple[Literal["partial", "complete", "failed"], int]:
        path = self._run_root(config) / "study" / "study_results.json"
        results = StudyResults.model_validate_json(path.read_text(encoding="utf-8"))
        if results.protocol_sha256 != self.protocol.sha256:
            raise ValueError("project-owned study results use a different protocol")
        if any(record.status == CellStatus.FAILED for record in results.records):
            return "failed", len(results.records)
        if len(results.records) == len(runner.plan.cells) and all(
            record.status == CellStatus.SUCCEEDED for record in results.records
        ):
            return "complete", len(results.records)
        return "partial", len(results.records)

    def _mark_failed(
        self,
        config: ProjectStudyConfig,
        error: BaseException,
        *,
        expected_revision: int,
    ) -> None:
        if isinstance(error, ProjectRevisionConflictError):
            return
        try:
            self.runtime.update_run(
                config.project_id,
                config.run_id,
                expected_revision=expected_revision,
                status="failed",
                failure_type=type(error).__name__,
                failure_message=str(error)[:1000],
            )
        except (FileNotFoundError, ValueError):
            return

    def _summary(
        self,
        config: ProjectStudyConfig,
        snapshot: ProjectSnapshot,
        study: StudyRunSummary,
        *,
        run_status: Literal["planned", "partial", "complete", "failed"],
    ) -> ProjectStudySummary:
        return ProjectStudySummary(
            project_id=config.project_id,
            run_id=config.run_id,
            run_status=run_status,
            project_revision=snapshot.revision,
            project_run_locator=(f"projects/{config.project_id}/runs/{config.run_id}"),
            study=study,
        )

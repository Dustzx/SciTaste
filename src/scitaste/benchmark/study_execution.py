"""Isolated, resumable execution of matched-budget study cells."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.benchmark.study import MatchedStudyPlanner
from scitaste.benchmark.study_models import (
    CellStatus,
    EvidenceClass,
    ExpertPanelReview,
    MatchedStudyProtocol,
    StudyArtifact,
    StudyCell,
    StudyExecutionRecord,
    StudyOutcome,
    StudyResults,
    StudyUsage,
    SystemCondition,
)


class CommandLauncherConfig(BaseModel):
    """One shell-free command template for a complete system condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: list[str] = Field(min_length=1)
    gpu_count: int = Field(default=1, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    pass_environment: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def environment_names_are_unique(self) -> CommandLauncherConfig:
        if len(set(self.pass_environment)) != len(self.pass_environment):
            raise ValueError("pass_environment entries must be unique")
        if any(not item for item in self.command):
            raise ValueError("launcher command entries cannot be empty")
        return self


class StudyLaunchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    launchers: dict[SystemCondition, CommandLauncherConfig]


class LauncherUsage(BaseModel):
    """Counters reported by an adapter; time and GPU allocation are runner-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiments: int | None = Field(default=None, ge=0)
    api_cost_usd: float | None = Field(default=None, ge=0)
    search_queries: int | None = Field(default=None, ge=0)
    llm_tokens: int | None = Field(default=None, ge=0)


class LauncherResult(BaseModel):
    """Result file written by a real condition adapter inside its cell directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    status: CellStatus
    evidence_class: EvidenceClass
    usage: LauncherUsage
    outcome: StudyOutcome | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def successful_result_is_complete(self) -> LauncherResult:
        if self.status == CellStatus.SUCCEEDED:
            if self.outcome is None:
                raise ValueError("successful launcher results require outcome measures")
            if not self.artifact_paths:
                raise ValueError("successful launcher results require artifact paths")
            missing = [name for name, value in self.usage.model_dump().items() if value is None]
            if missing:
                raise ValueError(
                    "successful launcher results require counters: " + ", ".join(missing)
                )
        return self


class CellLaunchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    task_id: str
    condition: SystemCondition
    command: list[str]
    cell_directory: str


class StudyRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_sha256: str
    selected_cells: int
    executed_cells: int
    resumed_cells: int
    succeeded_cells: int
    failed_cells: int
    dry_run: bool
    results_path: str | None = None
    launches: list[CellLaunchPlan] = Field(default_factory=list)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int


class ProcessRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: float,
    ) -> ProcessResult: ...


class SubprocessRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: float,
    ) -> ProcessResult:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                raise
            except BaseException:
                _terminate_process_group(process)
                raise
        return ProcessResult(returncode=returncode)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


class MatchedStudyRunner:
    """Run selected cells sequentially with stable directories and honest failures."""

    def __init__(
        self,
        protocol: MatchedStudyProtocol,
        launch_config: StudyLaunchConfig,
        *,
        output_dir: str | Path,
        process_runner: ProcessRunner | None = None,
        clock: Callable[[], float] = time.perf_counter,
        asset_root: str | Path | None = None,
    ) -> None:
        self.protocol = protocol
        self.launch_config = launch_config
        self.output_dir = Path(output_dir)
        self.process_runner = process_runner or SubprocessRunner()
        self.clock = clock
        self.asset_root = Path(asset_root) if asset_root is not None else Path.cwd()
        self.plan = MatchedStudyPlanner().plan(protocol)

    def run(
        self,
        *,
        task_ids: list[str] | None = None,
        conditions: list[SystemCondition] | None = None,
        cell_ids: list[str] | None = None,
        max_cells: int | None = None,
        resume: bool = True,
        dry_run: bool = False,
    ) -> StudyRunSummary:
        if self.plan.readiness_blockers:
            raise ValueError(
                "study protocol is not execution-ready: " + "; ".join(self.plan.readiness_blockers)
            )
        selected = self._select_cells(task_ids, conditions, cell_ids, max_cells)
        launches = [self._launch_plan(cell) for cell in selected]
        if dry_run:
            return StudyRunSummary(
                protocol_sha256=self.protocol.sha256,
                selected_cells=len(selected),
                executed_cells=0,
                resumed_cells=0,
                succeeded_cells=0,
                failed_cells=0,
                dry_run=True,
                launches=launches,
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        records, reviews = self._load_existing()
        executed = 0
        resumed = 0
        for cell in selected:
            previous = records.get(cell.cell_id)
            if resume and previous is not None and previous.status == CellStatus.SUCCEEDED:
                resumed += 1
                continue
            records[cell.cell_id] = self._run_cell(cell)
            executed += 1
            self._save_results(records, reviews)
        selected_records = [records[cell.cell_id] for cell in selected if cell.cell_id in records]
        return StudyRunSummary(
            protocol_sha256=self.protocol.sha256,
            selected_cells=len(selected),
            executed_cells=executed,
            resumed_cells=resumed,
            succeeded_cells=sum(
                record.status == CellStatus.SUCCEEDED for record in selected_records
            ),
            failed_cells=sum(record.status == CellStatus.FAILED for record in selected_records),
            dry_run=False,
            results_path=str(self.output_dir / "study_results.json"),
            launches=launches,
        )

    def _select_cells(
        self,
        task_ids: list[str] | None,
        conditions: list[SystemCondition] | None,
        cell_ids: list[str] | None,
        max_cells: int | None,
    ) -> list[StudyCell]:
        known_tasks = {task.task_id for task in self.protocol.tasks}
        requested_tasks = set(task_ids or known_tasks)
        unknown_tasks = requested_tasks - known_tasks
        if unknown_tasks:
            raise ValueError("unknown study tasks: " + ", ".join(sorted(unknown_tasks)))
        enabled = {
            condition.condition for condition in self.protocol.conditions if condition.enabled
        }
        requested_conditions = set(conditions or enabled)
        unavailable = requested_conditions - enabled
        if unavailable:
            raise ValueError(
                "study conditions are not enabled: "
                + ", ".join(sorted(item.value for item in unavailable))
            )
        known_cells = {cell.cell_id for cell in self.plan.cells}
        requested_cells = set(cell_ids or known_cells)
        unknown_cells = requested_cells - known_cells
        if unknown_cells:
            raise ValueError("unknown study cells: " + ", ".join(sorted(unknown_cells)))
        selected = [
            cell
            for cell in self.plan.cells
            if cell.task_id in requested_tasks
            and cell.condition in requested_conditions
            and cell.cell_id in requested_cells
        ]
        if max_cells is not None:
            if max_cells <= 0:
                raise ValueError("max_cells must be positive")
            selected = selected[:max_cells]
        missing_launchers = {cell.condition for cell in selected} - set(
            self.launch_config.launchers
        )
        if missing_launchers:
            raise ValueError(
                "launch config is missing enabled conditions: "
                + ", ".join(sorted(item.value for item in missing_launchers))
            )
        if not selected:
            raise ValueError("no study cells matched the requested filters")
        return selected

    def _launch_plan(self, cell: StudyCell) -> CellLaunchPlan:
        cell_dir = (self.output_dir / "cells" / cell.cell_id).resolve()
        command = self._render_command(cell, cell_dir)
        return CellLaunchPlan(
            cell_id=cell.cell_id,
            task_id=cell.task_id,
            condition=cell.condition,
            command=command,
            cell_directory=str(cell_dir),
        )

    def _run_cell(self, cell: StudyCell) -> StudyExecutionRecord:
        cell_dir = (self.output_dir / "cells" / cell.cell_id).resolve()
        cell_dir.mkdir(parents=True, exist_ok=True)
        request_path = cell_dir / "cell_request.json"
        result_path = cell_dir / "launcher_result.json"
        record_path = cell_dir / "execution_record.json"
        stdout_path = cell_dir / "stdout.log"
        stderr_path = cell_dir / "stderr.log"
        _atomic_json_write(request_path, self._request_payload(cell, result_path))
        if result_path.exists():
            result_path.unlink()
        launcher = self.launch_config.launchers[cell.condition]
        command = self._render_command(cell, cell_dir)
        try:
            environment = self._environment(launcher, request_path, result_path, cell_dir)
        except ValueError as exc:
            record = self._failed_record(cell, 0.0, launcher.gpu_count, str(exc))
            _atomic_json_write(record_path, record.model_dump(mode="json"))
            return record
        timeout = self._timeout_seconds(cell, launcher)
        started = self.clock()
        try:
            process = self.process_runner.run(
                command,
                cwd=cell_dir,
                environment=environment,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_seconds=timeout,
            )
        except subprocess.TimeoutExpired:
            elapsed = max(0.0, self.clock() - started)
            record = self._failed_record(
                cell, elapsed, launcher.gpu_count, f"launcher timed out after {timeout:.3f}s"
            )
            _atomic_json_write(record_path, record.model_dump(mode="json"))
            return record
        except OSError as exc:
            elapsed = max(0.0, self.clock() - started)
            record = self._failed_record(
                cell, elapsed, launcher.gpu_count, f"launcher could not start: {exc}"
            )
            _atomic_json_write(record_path, record.model_dump(mode="json"))
            return record
        elapsed = max(0.0, self.clock() - started)
        if process.returncode != 0:
            record = self._failed_record(
                cell,
                elapsed,
                launcher.gpu_count,
                f"launcher exited with status {process.returncode}",
            )
        elif not result_path.is_file():
            record = self._failed_record(
                cell, elapsed, launcher.gpu_count, "launcher did not write launcher_result.json"
            )
        else:
            try:
                launcher_result = LauncherResult.model_validate_json(
                    result_path.read_text(encoding="utf-8")
                )
                record = self._record_from_launcher(
                    cell, launcher_result, cell_dir, elapsed, launcher.gpu_count
                )
            except (ValueError, OSError) as exc:
                record = self._failed_record(
                    cell, elapsed, launcher.gpu_count, f"invalid launcher result: {exc}"
                )
        _atomic_json_write(record_path, record.model_dump(mode="json"))
        return record

    def _record_from_launcher(
        self,
        cell: StudyCell,
        result: LauncherResult,
        cell_dir: Path,
        elapsed_seconds: float,
        gpu_count: int,
    ) -> StudyExecutionRecord:
        usage = StudyUsage(
            gpu_hours=elapsed_seconds * gpu_count / 3600,
            experiments=result.usage.experiments,
            wall_time_hours=elapsed_seconds / 3600,
            api_cost_usd=result.usage.api_cost_usd,
            search_queries=result.usage.search_queries,
            llm_tokens=result.usage.llm_tokens,
        )
        if result.status == CellStatus.FAILED:
            return StudyExecutionRecord(
                cell_id=cell.cell_id,
                status=CellStatus.FAILED,
                evidence_class=result.evidence_class,
                usage=usage,
                error=result.error or "launcher reported failure",
            )
        artifacts = [self._hash_artifact(path, cell_dir) for path in result.artifact_paths]
        return StudyExecutionRecord(
            cell_id=cell.cell_id,
            status=CellStatus.SUCCEEDED,
            evidence_class=result.evidence_class,
            usage=usage,
            outcome=result.outcome,
            artifacts=artifacts,
        )

    def _failed_record(
        self,
        cell: StudyCell,
        elapsed_seconds: float,
        gpu_count: int,
        error: str,
    ) -> StudyExecutionRecord:
        return StudyExecutionRecord(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            evidence_class=EvidenceClass.REAL,
            usage=StudyUsage(
                gpu_hours=elapsed_seconds * gpu_count / 3600,
                wall_time_hours=elapsed_seconds / 3600,
            ),
            error=error,
        )

    def _hash_artifact(self, value: str, cell_dir: Path) -> StudyArtifact:
        candidate = Path(value)
        path = candidate if candidate.is_absolute() else cell_dir / candidate
        if path.is_symlink():
            raise ValueError(f"artifact cannot be a symlink: {value}")
        resolved = path.resolve()
        if not resolved.is_relative_to(cell_dir):
            raise ValueError(f"artifact escapes its cell directory: {value}")
        if not resolved.is_file():
            raise ValueError(f"artifact is not a file: {value}")
        relative = resolved.relative_to(self.output_dir.resolve()).as_posix()
        return StudyArtifact(path=relative, sha256=_file_sha256(resolved))

    def _render_command(self, cell: StudyCell, cell_dir: Path) -> list[str]:
        task = next(task for task in self.protocol.tasks if task.task_id == cell.task_id)
        values = {
            "cell_id": cell.cell_id,
            "condition": cell.condition.value,
            "seed": str(cell.seed),
            "cell_dir": str(cell_dir),
            "cell_request": str(cell_dir / "cell_request.json"),
            "cell_result": str(cell_dir / "launcher_result.json"),
            "task_asset": str((self.asset_root / task.asset_path).resolve()),
            "asset_root": str(self.asset_root.resolve()),
        }
        rendered: list[str] = []
        for argument in self.launch_config.launchers[cell.condition].command:
            for name, value in values.items():
                argument = argument.replace("{" + name + "}", value)
            if re.search(r"\{[a-z_]+\}", argument):
                raise ValueError(f"unknown launcher placeholder in {argument!r}")
            rendered.append(argument)
        return rendered

    def _request_payload(self, cell: StudyCell, result_path: Path) -> dict[str, Any]:
        task = next(task for task in self.protocol.tasks if task.task_id == cell.task_id)
        condition = next(
            item for item in self.protocol.conditions if item.condition == cell.condition
        )
        return {
            "schema_version": "1.0",
            "protocol_sha256": self.protocol.sha256,
            "cell": cell.model_dump(mode="json"),
            "task": task.model_dump(mode="json"),
            "condition": condition.model_dump(mode="json"),
            "base_model": self.protocol.base_model,
            "base_model_revision": self.protocol.base_model_revision,
            "search_access": self.protocol.search_access.model_dump(mode="json"),
            "result_path": str(result_path),
        }

    def _environment(
        self,
        launcher: CommandLauncherConfig,
        request_path: Path,
        result_path: Path,
        cell_dir: Path,
    ) -> dict[str, str]:
        baseline_names = ["PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "CUDA_VISIBLE_DEVICES"]
        environment = {name: os.environ[name] for name in baseline_names if name in os.environ}
        missing = [name for name in launcher.pass_environment if name not in os.environ]
        if missing:
            raise ValueError("required environment variables are missing: " + ", ".join(missing))
        environment.update({name: os.environ[name] for name in launcher.pass_environment})
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SCITASTE_STUDY_CELL_REQUEST": str(request_path),
                "SCITASTE_STUDY_CELL_RESULT": str(result_path),
                "SCITASTE_STUDY_CELL_DIR": str(cell_dir),
            }
        )
        return environment

    @staticmethod
    def _timeout_seconds(cell: StudyCell, launcher: CommandLauncherConfig) -> float:
        limits = [
            cell.budget.max_wall_time_hours * 3600,
            cell.budget.gpu_hours * 3600 / launcher.gpu_count,
        ]
        if launcher.timeout_seconds is not None:
            limits.append(launcher.timeout_seconds)
        return min(limits)

    def _load_existing(self) -> tuple[dict[str, StudyExecutionRecord], list[ExpertPanelReview]]:
        records: dict[str, StudyExecutionRecord] = {}
        reviews: list[ExpertPanelReview] = []
        results_path = self.output_dir / "study_results.json"
        if results_path.is_file():
            results = StudyResults.model_validate_json(results_path.read_text(encoding="utf-8"))
            if results.protocol_sha256 != self.protocol.sha256:
                raise ValueError("existing study results use a different protocol fingerprint")
            records.update({record.cell_id: record for record in results.records})
            reviews = results.expert_reviews
        cells_dir = self.output_dir / "cells"
        if cells_dir.is_dir():
            for record_path in cells_dir.glob("*/execution_record.json"):
                record = StudyExecutionRecord.model_validate_json(
                    record_path.read_text(encoding="utf-8")
                )
                records[record.cell_id] = record
        known = {cell.cell_id for cell in self.plan.cells}
        unknown = set(records) - known
        if unknown:
            raise ValueError(
                "existing results contain unknown cells: " + ", ".join(sorted(unknown))
            )
        return records, reviews

    def _save_results(
        self,
        records: dict[str, StudyExecutionRecord],
        reviews: list[ExpertPanelReview],
    ) -> None:
        order = {cell.cell_id: index for index, cell in enumerate(self.plan.cells)}
        results = StudyResults(
            protocol_sha256=self.protocol.sha256,
            records=sorted(records.values(), key=lambda record: order[record.cell_id]),
            expert_reviews=reviews,
        )
        _atomic_json_write(self.output_dir / "study_results.json", results.model_dump(mode="json"))


def load_study_launch_config(path: str | Path) -> StudyLaunchConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return StudyLaunchConfig.model_validate(_expand_environment(raw))


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value

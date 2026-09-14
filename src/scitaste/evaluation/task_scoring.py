"""One-way held-out scoring for a frozen autonomous-research candidate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_execution import (
    BenchmarkDevelopmentExecutionReceipt,
    BenchmarkDevelopmentLimits,
    BenchmarkDevelopmentRunner,
    BenchmarkObjectivePayload,
    BenchmarkResourceVerificationReceipt,
    _archive_output_directories,
    _bounded_read,
    _file_sha256,
    _hash_output_directories,
    _limit_process,
    _prepared_dataset_contains,
)
from scitaste.evaluation.task_patch import hash_editable_surface
from scitaste.evaluation.task_research_loop import (
    BenchmarkResearchCellBinding,
    BenchmarkResearchLoopResult,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    PreparedBenchmarkWorkspace,
    hash_protected_surface,
)
from scitaste.executor.native_profile import (
    NativeResourceAvailability,
    PreparedNativeExecutionProfile,
    preflight_native_resources,
)
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_relative_locator,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ENTRYPOINT_MOUNT = "/scitaste/runtime/mlrc_objective_entrypoint.py"


class BenchmarkFrozenCandidate(BaseModel):
    """Development-selected source plus any scorer inputs, frozen before test access."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    cell_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    owner_approval_sha256: str = Field(pattern=_SHA256)
    task_spec_fingerprint: str = Field(pattern=_SHA256)
    workspace_receipt_sha256: str = Field(pattern=_SHA256)
    loop_result_sha256: str = Field(pattern=_SHA256)
    cell_binding_sha256: str = Field(pattern=_SHA256)
    best_iteration: int = Field(ge=0, le=20)
    best_development_receipt_sha256: str = Field(pattern=_SHA256)
    editable_surface_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    artifact_root_locator: str
    input_artifact_sha256: dict[str, str] = Field(max_length=10_000)
    frozen_at: datetime
    heldout_materialized: Literal[False] = False
    candidate_sha256: str = Field(pattern=_SHA256)

    @field_validator("artifact_root_locator")
    @classmethod
    def artifact_locator_is_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="frozen artifact root")

    @model_validator(mode="after")
    def identity_is_closed_and_self_hashed(self) -> BenchmarkFrozenCandidate:
        validate_entry_id(self.candidate_id, field_name="candidate_id")
        validate_entry_id(self.cell_id, field_name="cell_id")
        if self.frozen_at.tzinfo is None:
            raise ValueError("benchmark candidate freeze time must be timezone-aware")
        if any(
            not path or not _is_sha256(digest)
            for path, digest in self.input_artifact_sha256.items()
        ):
            raise ValueError("benchmark frozen input artifact hashes are invalid")
        for path in self.input_artifact_sha256:
            validate_relative_locator(path, field_name="frozen input artifact")
        expected = content_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected:
            raise ValueError("benchmark frozen candidate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkFrozenCandidate:
        payload = {"schema_version": "1.0", **values}
        payload.pop("candidate_sha256", None)
        unsigned = cls.model_construct(candidate_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"candidate_sha256"}))
        return cls(**payload, candidate_sha256=digest)


class BenchmarkHeldoutRunRequest(BaseModel):
    """Separate scorer authority issued only after the development candidate is frozen."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    cell_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    owner_approval_sha256: str = Field(pattern=_SHA256)
    cell_binding_sha256: str = Field(pattern=_SHA256)
    spec_id: str
    spec_fingerprint: str = Field(pattern=_SHA256)
    prepared_workspace_receipt_sha256: str = Field(pattern=_SHA256)
    frozen_candidate_sha256: str = Field(pattern=_SHA256)
    execution_profile_fingerprint: str = Field(pattern=_SHA256)
    resource_verification_receipt_sha256: str = Field(pattern=_SHA256)
    seed: int = Field(ge=0)
    limits: BenchmarkDevelopmentLimits = Field(default_factory=BenchmarkDevelopmentLimits)
    heldout_authorized: Literal[True] = True
    model_authorized: Literal[False] = False
    source_mutation_authorized: Literal[False] = False

    @model_validator(mode="after")
    def identifiers_are_safe(self) -> BenchmarkHeldoutRunRequest:
        for value, label in (
            (self.request_id, "request_id"),
            (self.cell_id, "cell_id"),
            (self.spec_id, "spec_id"),
        ):
            validate_entry_id(value, field_name=label)
        return self

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class BenchmarkHeldoutExecutionReceipt(BaseModel):
    """Scorer-owned hidden-test measurement with an explicit no-model boundary."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_sha256: str = Field(pattern=_SHA256)
    frozen_candidate_sha256: str = Field(pattern=_SHA256)
    spec_fingerprint: str = Field(pattern=_SHA256)
    workspace_receipt_sha256: str = Field(pattern=_SHA256)
    execution_profile_fingerprint: str = Field(pattern=_SHA256)
    resource_verification_receipt_sha256: str = Field(pattern=_SHA256)
    entrypoint_sha256: str = Field(pattern=_SHA256)
    status: Literal["succeeded", "failed"]
    error_code: str | None = None
    returncode: int | None = None
    timed_out: bool
    started_at: datetime
    finished_at: datetime
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)
    gpu_device_count: int = Field(ge=0, le=8)
    gpu_hours: float = Field(ge=0, allow_inf_nan=False)
    editable_surface_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    input_artifact_sha256: dict[str, str] = Field(max_length=10_000)
    objective: BenchmarkObjectivePayload | None = None
    baseline_heldout_score: float = Field(allow_inf_nan=False)
    objective_delta_from_baseline: float | None = Field(default=None, allow_inf_nan=False)
    stdout_sha256: str = Field(pattern=_SHA256)
    stderr_sha256: str = Field(pattern=_SHA256)
    stdout_bytes: int = Field(ge=0)
    stderr_bytes: int = Field(ge=0)
    artifact_bytes: int = Field(ge=0)
    artifact_root_locator: Literal["artifacts"] = "artifacts"
    artifact_sha256: dict[str, str] = Field(max_length=10_000)
    network_access: Literal[False] = False
    api_credentials_exposed: Literal[False] = False
    heldout_materialized: Literal[True] = True
    model_invocations_after_freeze: Literal[0] = 0
    secondary_llm_judge_invoked: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_and_hash_are_consistent(self) -> BenchmarkHeldoutExecutionReceipt:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("benchmark held-out timestamps must be timezone-aware")
        if self.status == "succeeded":
            if self.objective is None or self.objective_delta_from_baseline is None:
                raise ValueError("successful held-out execution requires an objective")
            if self.objective.phase != "test":
                raise ValueError("held-out execution requires a test objective")
            if self.error_code is not None or self.returncode != 0 or self.timed_out:
                raise ValueError("successful held-out execution has failure state")
        elif self.objective is not None or self.objective_delta_from_baseline is not None:
            raise ValueError("failed held-out execution cannot retain an objective")
        if any(not path or not _is_sha256(digest) for path, digest in self.artifact_sha256.items()):
            raise ValueError("benchmark held-out artifact hashes are invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("benchmark held-out execution receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkHeldoutExecutionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


def freeze_benchmark_candidate(
    spec: BenchmarkTaskRuntimeSpec,
    prepared_workspace: PreparedBenchmarkWorkspace,
    cell_binding: BenchmarkResearchCellBinding,
    loop_result: BenchmarkResearchLoopResult,
    development_receipt: BenchmarkDevelopmentExecutionReceipt,
    *,
    loop_directory: str | Path,
    workspace: str | Path,
    output_path: str | Path,
) -> BenchmarkFrozenCandidate:
    """Bind the development winner and its required scorer inputs before hidden data opens."""

    if loop_result.status == "failed" or loop_result.best_iteration is None:
        raise ValueError("a failed development loop cannot yield a held-out candidate")
    if loop_result.cell_binding_sha256 != cell_binding.binding_sha256:
        raise ValueError("development loop belongs to another campaign cell")
    if loop_result.task_spec_fingerprint != spec.fingerprint:
        raise ValueError("development loop belongs to another task spec")
    if development_receipt.status != "succeeded" or development_receipt.objective is None:
        raise ValueError("the selected development result is not successful")
    if (
        development_receipt.spec_fingerprint != spec.fingerprint
        or development_receipt.workspace_receipt_sha256
        != prepared_workspace.receipt_sha256
    ):
        raise ValueError("selected development receipt belongs to another task workspace")
    if development_receipt.objective.phase != "dev":
        raise ValueError("the selected candidate does not come from development scoring")
    if development_receipt.receipt_sha256 not in {
        item.development_receipt_sha256 for item in loop_result.iterations
    }:
        raise ValueError("selected development receipt is outside the research loop")
    selected = loop_result.iterations[loop_result.best_iteration]
    if selected.development_receipt_sha256 != development_receipt.receipt_sha256:
        raise ValueError("selected development receipt is not the loop winner")
    root = Path(loop_directory).resolve(strict=True)
    artifact_root = _best_artifact_root(root, loop_result.best_iteration).resolve(strict=True)
    if not artifact_root.is_relative_to(root):
        raise ValueError("selected development artifacts escape the loop directory")
    editable, _ = hash_editable_surface(spec, workspace)
    protected = hash_protected_surface(spec, workspace)
    if editable != loop_result.best_editable_surface_sha256:
        raise ValueError("workspace source differs from the development winner")
    if editable != development_receipt.editable_surface_sha256:
        raise ValueError("selected development receipt binds another source surface")
    if protected != prepared_workspace.protected_surface_sha256:
        raise ValueError("protected source changed before candidate freeze")
    selected_artifacts = {
        path: digest
        for path, digest in development_receipt.artifact_sha256.items()
        if any(
            _path_is_at_or_under(path, directory)
            for directory in spec.heldout_input_artifact_directories
        )
    }
    for directory in spec.heldout_input_artifact_directories:
        if not any(_path_is_at_or_under(path, directory) for path in selected_artifacts):
            raise ValueError(f"selected development result lacks held-out input: {directory}")
    _verify_artifact_hashes(
        artifact_root,
        selected_artifacts,
        directories=spec.heldout_input_artifact_directories,
    )
    candidate = BenchmarkFrozenCandidate.create(
        candidate_id=f"{loop_result.loop_id}-candidate",
        cell_id=cell_binding.cell_id,
        campaign_manifest_sha256=cell_binding.campaign_manifest_sha256,
        owner_approval_sha256=cell_binding.evaluation_bundle_sha256,
        task_spec_fingerprint=spec.fingerprint,
        workspace_receipt_sha256=prepared_workspace.receipt_sha256,
        loop_result_sha256=loop_result.result_sha256,
        cell_binding_sha256=loop_result.cell_binding_sha256,
        best_iteration=loop_result.best_iteration,
        best_development_receipt_sha256=development_receipt.receipt_sha256,
        editable_surface_sha256=editable,
        protected_surface_sha256=protected,
        artifact_root_locator=artifact_root.relative_to(root).as_posix(),
        input_artifact_sha256=selected_artifacts,
        frozen_at=datetime.now(UTC),
    )
    _write_json(Path(output_path), candidate.model_dump(mode="json"))
    return candidate


class BenchmarkHeldoutRunner(BenchmarkDevelopmentRunner):
    """Run the fixed test command exactly once without any model callback."""

    def __init__(
        self,
        spec: BenchmarkTaskRuntimeSpec,
        prepared_workspace: PreparedBenchmarkWorkspace,
        execution_profile: PreparedNativeExecutionProfile,
        resource_verification: BenchmarkResourceVerificationReceipt,
        frozen_candidate: BenchmarkFrozenCandidate,
        *,
        source_root: str | Path,
        workspace: str | Path,
        loop_directory: str | Path,
        bubblewrap: str | Path | None = None,
    ) -> None:
        super().__init__(
            spec,
            prepared_workspace,
            execution_profile,
            resource_verification,
            source_root=source_root,
            workspace=workspace,
            bubblewrap=bubblewrap,
        )
        self.frozen_candidate = frozen_candidate
        self.loop_directory = Path(loop_directory).resolve(strict=True)

    def run(
        self,
        request: BenchmarkHeldoutRunRequest,
        *,
        result_directory: str | Path,
        allow_heldout_execution: bool = False,
    ) -> BenchmarkHeldoutExecutionReceipt:
        if not allow_heldout_execution:
            raise ValueError("benchmark held-out execution requires explicit authorization")
        resources, entrypoint, editable_before, protected_before = self._validate_heldout(request)
        target = Path(result_directory)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        target.mkdir(parents=True)
        stdout_path = target / "stdout.txt"
        stderr_path = target / "stderr.txt"
        started_at = datetime.now(UTC)
        started = perf_counter()
        timed_out = False
        returncode: int | None = None
        launch_error: str | None = None
        gpu_started: float | None = None
        gpu_finished: float | None = None
        try:
            self._stage_frozen_inputs()
            modes = self._open_output_directories()
            try:
                command = self._command_for(
                    self.spec.heldout_command,
                    entrypoint,
                    resources.gpu_devices,
                )
                environment = self._environment(request.seed, resources.gpu_devices)
                with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                        env=environment,
                        close_fds=True,
                        start_new_session=True,
                        preexec_fn=lambda: _limit_process(request.limits),
                    )
                    if resources.gpu_devices:
                        gpu_started = perf_counter()
                    try:
                        returncode = process.wait(timeout=request.limits.timeout_seconds)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        returncode = process.wait()
                    finally:
                        if gpu_started is not None:
                            gpu_finished = perf_counter()
            finally:
                self._restore_output_directory_modes(modes)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)

        finished_at = datetime.now(UTC)
        wall_seconds = max(0.0, perf_counter() - started)
        stdout = _bounded_read(stdout_path, request.limits.maximum_log_bytes)
        stderr = _bounded_read(stderr_path, request.limits.maximum_log_bytes)
        objective: BenchmarkObjectivePayload | None = None
        error_code: str | None = None
        if launch_error is not None:
            error_code = "launch-error"
        elif timed_out:
            error_code = "timeout"
        elif returncode != 0:
            error_code = "nonzero-exit"
        else:
            try:
                from scitaste.evaluation.task_execution import parse_benchmark_objective

                objective = parse_benchmark_objective(
                    stdout,
                    task_id=self.spec.task_id,
                    expected_phase="test",
                )
            except ValueError:
                error_code = "objective-contract"

        try:
            protected_after = hash_protected_surface(self.spec, self.workspace)
            editable_after, _ = hash_editable_surface(self.spec, self.workspace)
            if protected_after != protected_before:
                error_code = "protected-source-drift"
            if editable_after != editable_before:
                error_code = "editable-source-drift"
            artifacts, artifact_bytes = _hash_output_directories(
                self.spec,
                self.workspace,
                maximum_bytes=request.limits.maximum_artifact_bytes,
            )
            _archive_output_directories(
                self.spec,
                self.workspace,
                destination=target / "artifacts",
            )
        except (OSError, ValueError):
            protected_after = protected_before
            editable_after = editable_before
            artifacts = {}
            artifact_bytes = 0
            error_code = "post-execution-integrity"
        if error_code is not None:
            objective = None
        gpu_seconds = (
            max(0.0, gpu_finished - gpu_started)
            if gpu_started is not None and gpu_finished is not None
            else 0.0
        )
        receipt = BenchmarkHeldoutExecutionReceipt.create(
            request_sha256=request.fingerprint,
            frozen_candidate_sha256=self.frozen_candidate.candidate_sha256,
            spec_fingerprint=self.spec.fingerprint,
            workspace_receipt_sha256=self.prepared_workspace.receipt_sha256,
            execution_profile_fingerprint=self.execution_profile.fingerprint,
            resource_verification_receipt_sha256=self.resource_verification.receipt_sha256,
            entrypoint_sha256=self.spec.objective_entrypoint.file_sha256,
            status="failed" if error_code is not None else "succeeded",
            error_code=error_code,
            returncode=returncode,
            timed_out=timed_out,
            started_at=started_at,
            finished_at=finished_at,
            wall_seconds=wall_seconds,
            gpu_device_count=len(resources.gpu_devices),
            gpu_hours=gpu_seconds * len(resources.gpu_devices) / 3600.0,
            editable_surface_sha256=editable_after,
            protected_surface_sha256=protected_after,
            input_artifact_sha256=self.frozen_candidate.input_artifact_sha256,
            objective=objective,
            baseline_heldout_score=self.spec.baseline_heldout_score,
            objective_delta_from_baseline=(
                None if objective is None else objective.score - self.spec.baseline_heldout_score
            ),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            artifact_bytes=artifact_bytes,
            artifact_sha256=artifacts,
        )
        _write_json(target / "RESULT.json", receipt.model_dump(mode="json"))
        return receipt

    def _validate_heldout(
        self,
        request: BenchmarkHeldoutRunRequest,
    ) -> tuple[NativeResourceAvailability, Path, str, str]:
        candidate = self.frozen_candidate
        if (
            request.cell_id != candidate.cell_id
            or request.cell_binding_sha256 != candidate.cell_binding_sha256
            or request.campaign_manifest_sha256 != candidate.campaign_manifest_sha256
            or request.owner_approval_sha256 != candidate.owner_approval_sha256
        ):
            raise ValueError("held-out request belongs to another campaign cell")
        if request.frozen_candidate_sha256 != candidate.candidate_sha256:
            raise ValueError("held-out request belongs to another frozen candidate")
        if (
            request.spec_id != self.spec.spec_id
            or request.spec_fingerprint != self.spec.fingerprint
        ):
            raise ValueError("held-out request belongs to another task spec")
        if candidate.task_spec_fingerprint != self.spec.fingerprint:
            raise ValueError("frozen candidate belongs to another task spec")
        if request.prepared_workspace_receipt_sha256 != self.prepared_workspace.receipt_sha256:
            raise ValueError("held-out request belongs to another workspace")
        if candidate.workspace_receipt_sha256 != self.prepared_workspace.receipt_sha256:
            raise ValueError("frozen candidate belongs to another workspace")
        if request.execution_profile_fingerprint != self.execution_profile.fingerprint:
            raise ValueError("held-out request belongs to another execution profile")
        if (
            request.resource_verification_receipt_sha256
            != self.resource_verification.receipt_sha256
        ):
            raise ValueError("held-out request lacks its resource verification")
        if (
            self.resource_verification.execution_profile_fingerprint
            != self.execution_profile.fingerprint
            or self.resource_verification.profile_record_sha256
            != self.execution_profile.record_sha256
        ):
            raise ValueError("held-out resource verification belongs to another profile")
        readiness = (
            self.spec.source_status,
            self.spec.archive_status,
            self.spec.license_status,
            self.spec.ingestion_status,
            self.spec.environment_status,
            self.spec.scorer_status,
        )
        if any(status is not ReadinessStatus.VERIFIED for status in readiness):
            raise ValueError("benchmark task is not ready for held-out execution")
        profile = self.execution_profile.profile
        if not profile.writable_workspace or profile.schema_version != "1.2":
            raise ValueError("held-out scoring requires a schema 1.2 task profile")
        if profile.python_runtime is None:
            raise ValueError("held-out scoring requires a pinned Python runtime")
        if len(self.execution_profile.datasets) != len(self.spec.dataset_directories):
            raise ValueError("held-out datasets do not match declared task directories")
        if not all(
            _prepared_dataset_contains(self.spec, self.execution_profile, locator)
            for locator in self.spec.heldout_materialization_paths
        ):
            raise ValueError("held-out execution profile lacks hidden benchmark material")
        availability = preflight_native_resources(
            profile,
            prepared=self.execution_profile,
            verify_prepared_integrity=False,
        )
        if not availability.available:
            raise ValueError(f"held-out resources unavailable: {availability.reason}")
        if self.bubblewrap is None or not self.bubblewrap.is_file():
            raise ValueError("bubblewrap executable is unavailable")
        entrypoint = self.source_root.joinpath(
            *PurePosixPath(self.spec.objective_entrypoint.locator).parts
        ).resolve(strict=True)
        if not entrypoint.is_relative_to(self.source_root) or not entrypoint.is_file():
            raise ValueError("benchmark objective entrypoint is unavailable")
        if _file_sha256(entrypoint) != self.spec.objective_entrypoint.file_sha256:
            raise ValueError("benchmark objective entrypoint hash mismatch")
        if self.spec.heldout_command[:2] != ("python", _ENTRYPOINT_MOUNT):
            raise ValueError("benchmark held-out command does not use the objective entrypoint")
        editable, _ = hash_editable_surface(self.spec, self.workspace)
        protected = hash_protected_surface(self.spec, self.workspace)
        if editable != candidate.editable_surface_sha256:
            raise ValueError("workspace differs from the frozen candidate")
        if protected != candidate.protected_surface_sha256:
            raise ValueError("protected source differs from the frozen candidate")
        for locator in self.spec.writable_output_directories:
            output = self.workspace.joinpath(*PurePosixPath(locator).parts)
            if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
                raise ValueError("held-out execution requires new empty output directories")
        artifact_root = self.loop_directory.joinpath(
            *PurePosixPath(candidate.artifact_root_locator).parts
        ).resolve(strict=True)
        if not artifact_root.is_relative_to(self.loop_directory):
            raise ValueError("frozen development artifacts escape the loop directory")
        _verify_artifact_hashes(
            artifact_root,
            candidate.input_artifact_sha256,
            directories=self.spec.heldout_input_artifact_directories,
        )
        return availability, entrypoint, editable, protected

    def _stage_frozen_inputs(self) -> None:
        artifact_root = self.loop_directory.joinpath(
            *PurePosixPath(self.frozen_candidate.artifact_root_locator).parts
        )
        for locator in self.spec.heldout_input_artifact_directories:
            source = artifact_root.joinpath(*PurePosixPath(locator).parts)
            destination = self.workspace.joinpath(*PurePosixPath(locator).parts)
            if not source.is_dir() or destination.is_symlink() or any(destination.iterdir()):
                raise ValueError("frozen held-out input directory is unavailable")
            shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False)
        staged = {
            path: _file_sha256(self.workspace.joinpath(*PurePosixPath(path).parts))
            for path in self.frozen_candidate.input_artifact_sha256
        }
        if staged != self.frozen_candidate.input_artifact_sha256:
            raise ValueError("held-out input changed while staged")


def load_benchmark_development_execution_receipt(
    path: str | Path,
) -> BenchmarkDevelopmentExecutionReceipt:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("benchmark development receipt is invalid")
    return BenchmarkDevelopmentExecutionReceipt.model_validate_json(source.read_bytes())


def load_benchmark_frozen_candidate(path: str | Path) -> BenchmarkFrozenCandidate:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("benchmark frozen candidate is invalid")
    return BenchmarkFrozenCandidate.model_validate_json(source.read_bytes())


def _best_artifact_root(loop_directory: Path, best_iteration: int) -> Path:
    directory = "000-baseline" if best_iteration == 0 else f"{best_iteration:03d}"
    return loop_directory / "iterations" / directory / "development" / "artifacts"


def _verify_artifact_hashes(
    root: Path,
    expected: dict[str, str],
    *,
    directories: tuple[str, ...],
) -> None:
    observed: dict[str, str] = {}
    for directory in directories:
        source = root.joinpath(*PurePosixPath(directory).parts)
        if source.is_symlink() or not source.is_dir():
            raise ValueError("frozen development input directory is unavailable")
        for candidate in sorted(source.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                if candidate.is_dir() and not candidate.is_symlink():
                    continue
                raise ValueError("frozen development input contains an unsafe entry")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError("frozen development input artifact escapes its root")
            observed[resolved.relative_to(root).as_posix()] = _file_sha256(resolved)
    if observed != expected:
        raise ValueError("frozen development input artifact set or hash mismatch")


def _path_is_at_or_under(path: str, directory: str) -> bool:
    candidate = PurePosixPath(path)
    root = PurePosixPath(directory)
    return candidate == root or root in candidate.parents


def _write_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(
            (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        )
        handle.flush()
        os.fsync(handle.fileno())


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "BenchmarkFrozenCandidate",
    "BenchmarkHeldoutExecutionReceipt",
    "BenchmarkHeldoutRunRequest",
    "BenchmarkHeldoutRunner",
    "freeze_benchmark_candidate",
    "load_benchmark_development_execution_receipt",
    "load_benchmark_frozen_candidate",
]

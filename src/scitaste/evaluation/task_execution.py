"""Isolated development-set execution for content-bound benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_patch import hash_editable_surface
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    PreparedBenchmarkWorkspace,
    hash_protected_surface,
)
from scitaste.executor.native_profile import (
    NativeGPUInventory,
    NativeResourceAvailability,
    PreparedNativeExecutionProfile,
    preflight_native_resources,
    verify_prepared_native_execution_profile,
)
from scitaste.project.models import content_sha256, validate_entry_id

try:
    import resource as _resource
except ImportError:  # pragma: no cover - supported runtime is Linux/POSIX
    _resource = None

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_OBJECTIVE_MARKER = b"SCITASTE_BENCHMARK_OBJECTIVE_JSON="
_ENTRYPOINT_MOUNT = "/scitaste/runtime/mlrc_objective_entrypoint.py"


class BenchmarkDevelopmentLimits(BaseModel):
    model_config = _CONFIG

    timeout_seconds: int = Field(default=18_000, ge=1, le=86_400)
    cpu_seconds: int = Field(default=18_000, ge=1, le=86_400)
    maximum_memory_mb: int = Field(default=131_072, ge=128, le=1_048_576)
    maximum_open_files: int = Field(default=4_096, ge=32, le=65_536)
    maximum_processes: int = Field(default=256, ge=1, le=4_096)
    maximum_log_bytes: int = Field(default=67_108_864, ge=1_024, le=1_073_741_824)
    maximum_artifact_bytes: int = Field(
        default=21_474_836_480,
        ge=1_024,
        le=1_099_511_627_776,
    )


class BenchmarkDevelopmentRunRequest(BaseModel):
    """Exact authorized development attempt inside a campaign cell."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    cell_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    owner_approval_sha256: str = Field(pattern=_SHA256)
    spec_id: str
    spec_fingerprint: str = Field(pattern=_SHA256)
    prepared_workspace_receipt_sha256: str = Field(pattern=_SHA256)
    execution_profile_fingerprint: str = Field(pattern=_SHA256)
    resource_verification_receipt_sha256: str = Field(pattern=_SHA256)
    editable_surface_sha256: str = Field(pattern=_SHA256)
    patch_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    iteration: int = Field(ge=0, le=1_000)
    seed: int = Field(ge=0)
    limits: BenchmarkDevelopmentLimits = Field(default_factory=BenchmarkDevelopmentLimits)
    execution_authorized: Literal[True] = True
    heldout_authorized: Literal[False] = False

    @model_validator(mode="after")
    def identifiers_are_safe(self) -> BenchmarkDevelopmentRunRequest:
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


class BenchmarkObjectivePayload(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    task_id: str
    phase: Literal["dev"]
    method: str
    score: float = Field(allow_inf_nan=False)
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    secondary_llm_judge_invoked: Literal[False] = False


class BenchmarkResourceVerificationReceipt(BaseModel):
    """One full resource hash verification reusable by read-only campaign cells."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    execution_profile_fingerprint: str = Field(pattern=_SHA256)
    profile_record_sha256: str = Field(pattern=_SHA256)
    verified_at: datetime
    resource_sha256: dict[str, str] = Field(min_length=1, max_length=64)
    reusable_for_read_only_cells: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_self_hashed(self) -> BenchmarkResourceVerificationReceipt:
        if self.verified_at.tzinfo is None:
            raise ValueError("benchmark resource verification time must be timezone-aware")
        if any(not key or not _is_sha256(value) for key, value in self.resource_sha256.items()):
            raise ValueError("benchmark resource verification hashes are invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("benchmark resource verification receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkResourceVerificationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


class BenchmarkDevelopmentExecutionReceipt(BaseModel):
    """Measured development result or bounded failure from one isolated attempt."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_sha256: str = Field(pattern=_SHA256)
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
    objective: BenchmarkObjectivePayload | None = None
    baseline_development_score: float = Field(allow_inf_nan=False)
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
    heldout_materialized: Literal[False] = False
    secondary_llm_judge_invoked: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_and_hash_are_consistent(self) -> BenchmarkDevelopmentExecutionReceipt:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("benchmark execution timestamps must be timezone-aware")
        if self.status == "succeeded":
            if self.objective is None or self.objective_delta_from_baseline is None:
                raise ValueError("successful benchmark development execution requires an objective")
            if self.error_code is not None or self.returncode != 0 or self.timed_out:
                raise ValueError("successful benchmark development execution has failure state")
        elif self.objective is not None or self.objective_delta_from_baseline is not None:
            raise ValueError("failed benchmark development execution cannot retain an objective")
        if any(not key or not _is_sha256(value) for key, value in self.artifact_sha256.items()):
            raise ValueError("benchmark output artifact hashes are invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("benchmark development execution receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkDevelopmentExecutionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


class BenchmarkDevelopmentRunner:
    """Run only the development split in Bubblewrap and parse one objective marker."""

    def __init__(
        self,
        spec: BenchmarkTaskRuntimeSpec,
        prepared_workspace: PreparedBenchmarkWorkspace,
        execution_profile: PreparedNativeExecutionProfile,
        resource_verification: BenchmarkResourceVerificationReceipt,
        *,
        source_root: str | Path,
        workspace: str | Path,
        bubblewrap: str | Path | None = None,
    ) -> None:
        self.spec = spec
        self.prepared_workspace = prepared_workspace
        self.execution_profile = execution_profile
        self.resource_verification = resource_verification
        self.source_root = Path(source_root).resolve(strict=True)
        self.workspace = Path(workspace).resolve(strict=True)
        discovered = str(bubblewrap) if bubblewrap is not None else shutil.which("bwrap")
        self.bubblewrap = Path(discovered).resolve() if discovered else None

    def run(
        self,
        request: BenchmarkDevelopmentRunRequest,
        *,
        result_directory: str | Path,
        allow_execution: bool = False,
    ) -> BenchmarkDevelopmentExecutionReceipt:
        if not allow_execution:
            raise ValueError("benchmark development execution requires explicit authorization")
        resources, entrypoint, editable_before, protected_before = self._validate(request)
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
        modes = self._open_output_directories()
        try:
            command = self._command(entrypoint, resources.gpu_devices)
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
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)
        finally:
            self._restore_output_directory_modes(modes)

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
                objective = parse_benchmark_objective(stdout, task_id=self.spec.task_id)
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
        receipt = BenchmarkDevelopmentExecutionReceipt.create(
            request_sha256=request.fingerprint,
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
            objective=objective,
            baseline_development_score=self.spec.baseline_development_score,
            objective_delta_from_baseline=(
                None
                if objective is None
                else objective.score - self.spec.baseline_development_score
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

    def _validate(
        self,
        request: BenchmarkDevelopmentRunRequest,
    ) -> tuple[NativeResourceAvailability, Path, str, str]:
        if (
            request.spec_id != self.spec.spec_id
            or request.spec_fingerprint != self.spec.fingerprint
        ):
            raise ValueError("benchmark development request belongs to another task spec")
        if request.prepared_workspace_receipt_sha256 != self.prepared_workspace.receipt_sha256:
            raise ValueError("benchmark development request belongs to another workspace")
        if request.execution_profile_fingerprint != self.execution_profile.fingerprint:
            raise ValueError("benchmark development request belongs to another execution profile")
        if (
            request.resource_verification_receipt_sha256
            != self.resource_verification.receipt_sha256
        ):
            raise ValueError("benchmark development request lacks campaign resource verification")
        if (
            self.resource_verification.execution_profile_fingerprint
            != self.execution_profile.fingerprint
            or self.resource_verification.profile_record_sha256
            != self.execution_profile.record_sha256
        ):
            raise ValueError("campaign resource verification belongs to another profile")
        if self.prepared_workspace.workspace_locator != self.workspace.name:
            raise ValueError("prepared benchmark workspace locator mismatch")
        readiness = (
            self.spec.source_status,
            self.spec.archive_status,
            self.spec.license_status,
            self.spec.ingestion_status,
            self.spec.environment_status,
            self.spec.scorer_status,
        )
        if any(status is not ReadinessStatus.VERIFIED for status in readiness):
            raise ValueError("benchmark task is not ready for development execution")
        profile = self.execution_profile.profile
        if not profile.writable_workspace or profile.schema_version != "1.2":
            raise ValueError("benchmark development requires a schema 1.2 task profile")
        if profile.python_runtime is None:
            raise ValueError("benchmark development requires a pinned Python runtime")
        if len(self.execution_profile.datasets) != len(self.spec.dataset_directories):
            raise ValueError("prepared datasets do not match declared task dataset directories")
        availability = preflight_native_resources(
            profile,
            prepared=self.execution_profile,
            verify_prepared_integrity=False,
        )
        if not availability.available:
            raise ValueError(f"benchmark resources unavailable: {availability.reason}")
        if self.bubblewrap is None or not self.bubblewrap.is_file():
            raise ValueError("bubblewrap executable is unavailable")
        entrypoint = self.source_root.joinpath(
            *PurePosixPath(self.spec.objective_entrypoint.locator).parts
        ).resolve(strict=True)
        if not entrypoint.is_relative_to(self.source_root) or not entrypoint.is_file():
            raise ValueError("benchmark objective entrypoint is unavailable")
        if _file_sha256(entrypoint) != self.spec.objective_entrypoint.file_sha256:
            raise ValueError("benchmark objective entrypoint hash mismatch")
        if self.spec.development_command[:2] != ("python", _ENTRYPOINT_MOUNT):
            raise ValueError("benchmark development command does not use the objective entrypoint")
        protected = hash_protected_surface(self.spec, self.workspace)
        if protected != self.prepared_workspace.protected_surface_sha256:
            raise ValueError("protected benchmark source changed before execution")
        editable, _ = hash_editable_surface(self.spec, self.workspace)
        if editable != request.editable_surface_sha256:
            raise ValueError("editable benchmark source differs from the execution request")
        for locator in self.spec.writable_output_directories:
            output = self.workspace.joinpath(*PurePosixPath(locator).parts)
            if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
                raise ValueError("benchmark development requires new empty output directories")
        return availability, entrypoint, editable, protected

    def _command(
        self,
        entrypoint: Path,
        gpu_devices: tuple[NativeGPUInventory, ...],
    ) -> list[str]:
        assert self.bubblewrap is not None
        profile = self.execution_profile.profile
        assert profile.python_runtime is not None
        arguments = [
            str(self.bubblewrap),
            "--die-with-parent",
            "--unshare-all",
            "--new-session",
            "--uid",
            "65534",
            "--gid",
            "65534",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/tmp/home",
            "--dir",
            "/tmp/huggingface",
            "--dir",
            "/workspace",
            "--ro-bind",
            str(self.workspace),
            "/workspace",
        ]
        for locator in self.spec.writable_output_directories:
            arguments.extend(
                [
                    "--bind",
                    str(self.workspace.joinpath(*PurePosixPath(locator).parts)),
                    f"/workspace/{locator}",
                ]
            )
        for locator, dataset in zip(
            self.spec.dataset_directories,
            self.execution_profile.datasets,
            strict=True,
        ):
            arguments.extend(
                [
                    "--ro-bind",
                    str(dataset.materialized_path.resolve(strict=True)),
                    f"/workspace/{locator}",
                ]
            )
        arguments.extend(_external_mount_arguments(self.execution_profile))
        arguments.extend(_gpu_mount_arguments(gpu_devices))
        arguments.extend(
            [
                "--dir",
                "/scitaste",
                "--dir",
                "/scitaste/runtime",
                "--ro-bind",
                str(entrypoint),
                _ENTRYPOINT_MOUNT,
                "--chdir",
                "/workspace",
                profile.python_runtime.executable,
                *self.spec.development_command[1:],
            ]
        )
        return arguments

    def _environment(
        self,
        seed: int,
        gpu_devices: tuple[NativeGPUInventory, ...],
    ) -> dict[str, str]:
        runtime = self.execution_profile.profile.python_runtime
        assert runtime is not None
        environment = {
            "HOME": "/tmp/home",
            "HF_HOME": "/tmp/huggingface",
            "HF_HUB_OFFLINE": "1",
            "LANG": "C.UTF-8",
            "PATH": f"{PurePosixPath(runtime.executable).parent}:/usr/bin:/bin",
            "PYTHONHASHSEED": str(seed),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "TZ": "UTC",
            "TOKENIZERS_PARALLELISM": "false",
            "TRANSFORMERS_OFFLINE": "1",
        }
        if runtime.python_paths:
            environment["PYTHONPATH"] = ":".join(runtime.python_paths)
        if runtime.library_paths:
            environment["LD_LIBRARY_PATH"] = ":".join(runtime.library_paths)
        if gpu_devices:
            visible = ",".join(str(device.index) for device in gpu_devices)
            environment["CUDA_VISIBLE_DEVICES"] = visible
            environment["NVIDIA_VISIBLE_DEVICES"] = visible
        return environment

    def _open_output_directories(self) -> tuple[tuple[Path, int], ...]:
        modes: list[tuple[Path, int]] = []
        for locator in self.spec.writable_output_directories:
            output = self.workspace.joinpath(*PurePosixPath(locator).parts)
            mode = stat.S_IMODE(output.stat().st_mode)
            modes.append((output, mode))
            output.chmod(mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        return tuple(modes)

    @staticmethod
    def _restore_output_directory_modes(modes: tuple[tuple[Path, int], ...]) -> None:
        for path, mode in modes:
            path.chmod(mode)


def verify_benchmark_execution_resources(
    prepared: PreparedNativeExecutionProfile,
    *,
    receipt_path: str | Path,
) -> BenchmarkResourceVerificationReceipt:
    """Perform one full hash verification for reuse by read-only campaign cells."""

    verify_prepared_native_execution_profile(prepared)
    hashes = {
        **{f"dataset:{item.dataset_id}": item.content_sha256 for item in prepared.datasets},
        **{
            f"external:{item.resource_id}": item.content_sha256
            for item in prepared.external_resources
        },
        "profile-record": prepared.record_sha256,
    }
    receipt = BenchmarkResourceVerificationReceipt.create(
        execution_profile_fingerprint=prepared.fingerprint,
        profile_record_sha256=prepared.record_sha256,
        verified_at=datetime.now(UTC),
        resource_sha256=hashes,
    )
    path = Path(receipt_path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, receipt.model_dump(mode="json"))
    return receipt


def _external_mount_arguments(prepared: PreparedNativeExecutionProfile) -> list[str]:
    arguments: list[str] = []
    roots = sorted(
        {str(PurePosixPath(item.mount_path).parent) for item in prepared.external_resources}
    )
    for root in roots:
        arguments.extend(["--dir", root])
    for resource in prepared.external_resources:
        arguments.extend(
            [
                "--ro-bind",
                str(resource.source_path.resolve(strict=True)),
                resource.mount_path,
            ]
        )
    return arguments


def _gpu_mount_arguments(gpu_devices: tuple[NativeGPUInventory, ...]) -> list[str]:
    arguments: list[str] = []
    mounted: set[str] = set()
    for device in gpu_devices:
        for node in device.device_nodes:
            if node not in mounted:
                arguments.extend(["--dev-bind", node, node])
                mounted.add(node)
    return arguments


def parse_benchmark_objective(stdout: bytes, *, task_id: str) -> BenchmarkObjectivePayload:
    payloads = [
        line[len(_OBJECTIVE_MARKER) :]
        for line in stdout.splitlines()
        if line.startswith(_OBJECTIVE_MARKER)
    ]
    if len(payloads) != 1:
        raise ValueError("benchmark output must contain exactly one objective marker")
    objective = BenchmarkObjectivePayload.model_validate_json(payloads[0], strict=True)
    if objective.task_id != task_id:
        raise ValueError("benchmark objective task identity mismatch")
    return objective


def _hash_output_directories(
    spec: BenchmarkTaskRuntimeSpec,
    workspace: Path,
    *,
    maximum_bytes: int,
) -> tuple[dict[str, str], int]:
    hashes: dict[str, str] = {}
    total = 0
    for locator in spec.writable_output_directories:
        root = workspace.joinpath(*PurePosixPath(locator).parts)
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_symlink():
                raise ValueError("benchmark output cannot contain symbolic links")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("benchmark output contains a non-regular entry")
            relative = f"{locator}/{path.relative_to(root).as_posix()}"
            size = path.stat().st_size
            total += size
            if total > maximum_bytes:
                raise ValueError("benchmark output exceeds its artifact byte limit")
            hashes[relative] = _file_sha256(path)
            if len(hashes) > 10_000:
                raise ValueError("benchmark output exceeds its artifact file limit")
    return hashes, total


def _archive_output_directories(
    spec: BenchmarkTaskRuntimeSpec,
    workspace: Path,
    *,
    destination: Path,
) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    for locator in spec.writable_output_directories:
        source = workspace.joinpath(*PurePosixPath(locator).parts)
        target = destination.joinpath(*PurePosixPath(locator).parts)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
    for locator in spec.writable_output_directories:
        source = workspace.joinpath(*PurePosixPath(locator).parts)
        target = destination.joinpath(*PurePosixPath(locator).parts)
        mode = stat.S_IMODE(source.stat().st_mode)
        os.replace(source, target)
        source.mkdir(parents=True, exist_ok=False)
        source.chmod(mode)


def _bounded_read(path: Path, maximum_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError("benchmark execution log exceeds its byte limit")
    return path.read_bytes()


def _limit_process(limits: BenchmarkDevelopmentLimits) -> None:
    if _resource is None:
        raise ValueError("POSIX process resource limits are unavailable")
    _resource.setrlimit(_resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    memory = limits.maximum_memory_mb * 1024 * 1024
    _resource.setrlimit(_resource.RLIMIT_AS, (memory, memory))
    _resource.setrlimit(
        _resource.RLIMIT_FSIZE,
        (limits.maximum_log_bytes, limits.maximum_log_bytes),
    )
    _resource.setrlimit(
        _resource.RLIMIT_NOFILE,
        (limits.maximum_open_files, limits.maximum_open_files),
    )
    _resource.setrlimit(
        _resource.RLIMIT_NPROC,
        (limits.maximum_processes, limits.maximum_processes),
    )
    _resource.setrlimit(_resource.RLIMIT_CORE, (0, 0))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    with path.open("xb") as handle:
        encoded = (
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode()
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "BenchmarkDevelopmentExecutionReceipt",
    "BenchmarkDevelopmentLimits",
    "BenchmarkDevelopmentRunRequest",
    "BenchmarkDevelopmentRunner",
    "BenchmarkObjectivePayload",
    "BenchmarkResourceVerificationReceipt",
    "parse_benchmark_objective",
    "verify_benchmark_execution_resources",
]

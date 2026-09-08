"""Bubblewrap-isolated execution for project-owned native experiments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import statistics
import subprocess
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.native_profile import (
    NativeExecutionProfile,
    NativeGPUInventory,
    NativeResourceAvailability,
    PreparedNativeExecutionProfile,
    preflight_native_resources,
)
from scitaste.executor.native_store import NativeExecutionStore
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState

try:
    import resource as _resource
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    _resource = None

_MEASUREMENT_MARKER = "SCITASTE_MEASUREMENTS_JSON="
_METRIC_NAME = r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$"


class MetricDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class NativeExperimentLimits(BaseModel):
    """Hard ceilings applied before the isolated Python process starts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    cpu_seconds: int = Field(default=20, ge=1, le=600)
    max_memory_mb: int = Field(default=512, ge=64, le=32768)
    max_output_bytes: int = Field(default=262_144, ge=1024, le=16_777_216)
    max_open_files: int = Field(default=32, ge=8, le=256)
    max_processes: int = Field(default=16, ge=1, le=256)


class NativeExperimentDefinition(BaseModel):
    """Registered source, metric, and safety contract for one experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0", "1.1"]
    experiment_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source_path: Path
    primary_metric: str = Field(pattern=_METRIC_NAME)
    metric_direction: MetricDirection
    support_threshold: float
    required_metrics: tuple[str, ...] = ()
    limits: NativeExperimentLimits = Field(default_factory=NativeExperimentLimits)

    @field_validator("support_threshold", mode="before")
    @classmethod
    def threshold_is_finite(cls, value: object) -> object:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("native experiment support_threshold must be finite")
        return value

    @field_validator("required_metrics")
    @classmethod
    def required_metrics_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 64 or len(set(value)) != len(value):
            raise ValueError("required native experiment metrics must be unique and bounded")
        if any(re.fullmatch(_METRIC_NAME, name) is None for name in value):
            raise ValueError("required native experiment metrics require safe names")
        return value

    @model_validator(mode="after")
    def schema_matches_metric_contract(self) -> NativeExperimentDefinition:
        if self.schema_version == "1.0" and self.required_metrics:
            raise ValueError("native experiment schema 1.0 cannot declare required_metrics")
        if self.required_metrics and self.primary_metric not in self.required_metrics:
            raise ValueError("the primary metric must appear in required_metrics")
        return self


class NativeMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    replicate_id: str = Field(min_length=1, max_length=128)
    metrics: dict[str, float]

    @field_validator("metrics", mode="before")
    @classmethod
    def raw_metrics_are_numeric(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("measurement metrics must be a mapping")
        if any(
            isinstance(number, bool) or not isinstance(number, (int, float))
            for number in value.values()
        ):
            raise ValueError("measurement metric values must be strict numbers")
        return value

    @field_validator("metrics")
    @classmethod
    def metrics_are_bounded_and_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if not value or len(value) > 64:
            raise ValueError("each measurement requires between 1 and 64 metrics")
        for name, number in value.items():
            if not re.fullmatch(_METRIC_NAME, name) or not math.isfinite(number):
                raise ValueError("measurement metrics require safe names and finite values")
        return value


class NativeMeasurementEnvelope(BaseModel):
    """Only accepted machine-readable stdout record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    measurements: list[NativeMeasurement] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def replicates_and_metric_sets_match(self) -> NativeMeasurementEnvelope:
        identifiers = [item.replicate_id for item in self.measurements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("native experiment replicate IDs must be unique")
        expected = set(self.measurements[0].metrics)
        if any(set(item.metrics) != expected for item in self.measurements[1:]):
            raise ValueError("native experiment replicates must report identical metric sets")
        return self


class NativeExperimentAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    isolation: Literal["bubblewrap"] = "bubblewrap"
    executable: str | None = None
    resources: NativeResourceAvailability | None = None
    reason: str | None = None


class NativeExperimentRunner:
    """Execute one registered source with a shell-free isolated launcher."""

    def __init__(
        self,
        definition: NativeExperimentDefinition,
        *,
        bubblewrap: str | Path | None = None,
        execution_profile: PreparedNativeExecutionProfile | None = None,
    ) -> None:
        self.definition = definition
        self.execution_profile = execution_profile
        self.profile = (
            execution_profile.profile
            if execution_profile is not None
            else NativeExecutionProfile(profile_id="default-deny")
        )
        discovered = str(bubblewrap) if bubblewrap is not None else _find_executable("bwrap")
        self.bubblewrap = Path(discovered).resolve() if discovered else None

    @property
    def input_paths(self) -> tuple[Path, ...]:
        paths = [self.definition.source_path]
        if self.execution_profile is not None:
            paths.append(self.execution_profile.manifest_path)
            for dataset in self.execution_profile.datasets:
                if dataset.kind == "file":
                    paths.append(dataset.materialized_path)
                else:
                    paths.extend(
                        path
                        for path in sorted(dataset.materialized_path.rglob("*"))
                        if path.is_file()
                    )
        return tuple(paths)

    def availability(self) -> NativeExperimentAvailability:
        resources = preflight_native_resources(
            self.profile,
            prepared=self.execution_profile,
        )
        if not resources.available:
            return NativeExperimentAvailability(
                available=False,
                resources=resources,
                reason=f"native execution resource preflight failed: {resources.reason}",
            )
        requested_gpu_hours = (
            self.definition.limits.timeout_seconds * len(resources.gpu_devices) / 3600.0
        )
        if self.profile.gpu.enabled and requested_gpu_hours > self.profile.gpu.max_gpu_hours:
            return NativeExperimentAvailability(
                available=False,
                resources=resources,
                reason="native experiment timeout exceeds the admitted GPU-hour budget",
            )
        if _resource is None:
            return NativeExperimentAvailability(
                available=False,
                resources=resources,
                reason="POSIX process resource limits are unavailable",
            )
        if self.bubblewrap is None:
            return NativeExperimentAvailability(
                available=False,
                resources=resources,
                reason="bubblewrap executable was not found",
            )
        if not self.bubblewrap.is_file() or not os.access(self.bubblewrap, os.X_OK):
            return NativeExperimentAvailability(
                available=False,
                executable=str(self.bubblewrap),
                resources=resources,
                reason="bubblewrap executable is not an executable regular file",
            )
        probe = [
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
            *self._resource_arguments(resources.gpu_devices),
            "/bin/true",
        ]
        try:
            checked = subprocess.run(
                probe,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env={"PATH": "/usr/bin:/bin"},
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return NativeExperimentAvailability(
                available=False,
                executable=str(self.bubblewrap),
                resources=resources,
                reason=f"bubblewrap isolation probe failed: {type(exc).__name__}",
            )
        if checked.returncode != 0:
            detail = checked.stderr.decode("utf-8", errors="replace").strip()[:240]
            return NativeExperimentAvailability(
                available=False,
                executable=str(self.bubblewrap),
                resources=resources,
                reason=f"bubblewrap isolation probe returned {checked.returncode}: {detail}",
            )
        return NativeExperimentAvailability(
            available=True,
            executable=str(self.bubblewrap),
            resources=resources,
        )

    def run(
        self,
        state: ResearchState,
        action: ResearchAction,
        *,
        store: NativeExecutionStore,
    ) -> ExecutionResult:
        result_id = f"res-{uuid4().hex}"
        started_at = datetime.now(UTC)
        started = perf_counter()
        output_root = store.artifact_directory(result_id)
        stdout_path = output_root / "stdout.txt"
        stderr_path = output_root / "stderr.txt"
        availability = self.availability()
        returncode: int | None = None
        timed_out = False
        launch_error: str | None = None
        process_started = False

        requested_id = action.parameters.get("experiment_id")
        if requested_id != self.definition.experiment_id:
            launch_error = "selected action does not name the configured native experiment"
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(b"")
        elif not availability.available:
            launch_error = f"native experiment isolation unavailable: {availability.reason}"
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(b"")
        else:
            assert self.bubblewrap is not None
            source = self.definition.source_path
            if source.is_symlink() or not source.is_file():
                launch_error = "native experiment source must be a regular non-symlink file"
                stdout_path.write_bytes(b"")
                stderr_path.write_bytes(b"")
            else:
                try:
                    command = self._command(source)
                    environment = {
                        "HOME": "/nonexistent",
                        "LANG": "C.UTF-8",
                        "PATH": "/usr/bin:/bin",
                        "PYTHONHASHSEED": "0",
                        "TZ": "UTC",
                    }
                    if availability.resources is not None and availability.resources.gpu_devices:
                        visible = ",".join(
                            str(device.index) for device in availability.resources.gpu_devices
                        )
                        environment["CUDA_VISIBLE_DEVICES"] = visible
                        environment["NVIDIA_VISIBLE_DEVICES"] = visible
                    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                        process = subprocess.Popen(
                            command,
                            stdin=subprocess.DEVNULL,
                            stdout=stdout,
                            stderr=stderr,
                            env=environment,
                            close_fds=True,
                            start_new_session=True,
                            preexec_fn=self._limit_process,
                        )
                        process_started = True
                        try:
                            returncode = process.wait(
                                timeout=self.definition.limits.timeout_seconds
                            )
                        except subprocess.TimeoutExpired:
                            timed_out = True
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            returncode = process.wait()
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    launch_error = f"native experiment launch failed: {type(exc).__name__}: {exc}"
                    stdout_path.touch(exist_ok=True)
                    stderr_path.touch(exist_ok=True)

        elapsed_seconds = max(0.0, perf_counter() - started)
        gpu_count = (
            len(availability.resources.gpu_devices)
            if process_started and availability.resources is not None
            else 0
        )
        gpu_hours = elapsed_seconds * gpu_count / 3600.0
        finished_at = datetime.now(UTC)
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        envelope: NativeMeasurementEnvelope | None = None
        parse_error: str | None = None
        derived: dict[str, object] | None = None
        if launch_error is None and not timed_out and returncode == 0:
            try:
                envelope = parse_measurements(stdout_bytes)
                derived = _derive_metrics(envelope, self.definition)
            except ValueError as exc:
                parse_error = str(exc)

        artifacts = [store.locator(stdout_path), store.locator(stderr_path)]
        metrics_path: Path | None = None
        if envelope is not None and derived is not None:
            metrics_path = store.write_artifact_json(
                result_id,
                "metrics.json",
                {
                    "schema_version": "1.0",
                    "experiment_id": self.definition.experiment_id,
                    "raw_measurements": envelope.model_dump(mode="json")["measurements"],
                    **derived,
                },
            )
            artifacts.append(store.locator(metrics_path))
        execution_path = store.write_artifact_json(
            result_id,
            "execution.json",
            {
                "schema_version": "1.1",
                "experiment_id": self.definition.experiment_id,
                "isolation": "bubblewrap",
                "network": "unshared",
                "host_filesystem": "not-mounted",
                "writable_filesystem": "none",
                "execution_profile_id": self.profile.profile_id,
                "execution_profile_fingerprint": (
                    self.execution_profile.fingerprint
                    if self.execution_profile is not None
                    else None
                ),
                "datasets": (
                    []
                    if self.execution_profile is None
                    else [
                        {
                            "dataset_id": item.dataset_id,
                            "mount_path": item.mount_path,
                            "content_sha256": item.content_sha256,
                            "file_count": item.file_count,
                            "total_bytes": item.total_bytes,
                            "access": "read-only",
                        }
                        for item in self.execution_profile.datasets
                    ]
                ),
                "gpu_devices": (
                    "not-mounted"
                    if gpu_count == 0
                    else [
                        item.model_dump(mode="json")
                        for item in availability.resources.gpu_devices  # type: ignore[union-attr]
                    ]
                ),
                "gpu_hours": gpu_hours,
                "gpu_allocation_started": process_started and gpu_count > 0,
                "returncode": returncode,
                "timed_out": timed_out,
                "elapsed_seconds": elapsed_seconds,
                "limits": self.definition.limits.model_dump(mode="json"),
                "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "stdout_bytes": len(stdout_bytes),
                "stderr_bytes": len(stderr_bytes),
                "launch_error": launch_error,
                "parse_error": parse_error,
            },
        )
        artifacts.append(store.locator(execution_path))

        error = launch_error
        if error is None and timed_out:
            error = "native experiment exceeded its wall-time limit"
        if error is None and returncode != 0:
            error = f"native experiment exited with return code {returncode}"
        if error is None and parse_error is not None:
            error = f"native experiment measurement parsing failed: {parse_error}"
        common_data: dict[str, object] = {
            "action_type": action.type.value,
            "capability": "experiment",
            "execution_mode": "bubblewrap-isolated-python",
            "result_basis": "sandbox-measured-replicates" if error is None else "sandbox-failure",
            "cost_basis": "measured-wall-time",
            "state_revision_before": state.revision,
            "experiment_id": self.definition.experiment_id,
            "isolation": availability.model_dump(mode="json"),
            "network_access": False,
            "execution_profile_id": self.profile.profile_id,
            "dataset_mounts": [item.mount_path for item in self.profile.datasets],
            "gpu_device_count": gpu_count,
        }
        if error is not None or derived is None:
            return ExecutionResult(
                result_id=result_id,
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="scitaste-native",
                started_at=started_at,
                finished_at=finished_at,
                artifacts=artifacts,
                cost={"wall_time_hours": elapsed_seconds / 3600.0, "gpu_hours": gpu_hours},
                data=common_data,
                error=error or "native experiment did not produce measured evidence",
            )

        primary_value = float(derived["metrics"][self.definition.primary_metric])  # type: ignore[index]
        relation = str(derived["relation"])
        comparison = ">=" if self.definition.metric_direction == MetricDirection.MAXIMIZE else "<="
        observation = (
            f"Measured {self.definition.primary_metric}={primary_value:.10g} across "
            f"{derived['replicate_count']} isolated replicates; registered support requires "
            f"{comparison} {self.definition.support_threshold:.10g}."
        )
        return ExecutionResult(
            result_id=result_id,
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            executor="scitaste-native",
            started_at=started_at,
            finished_at=finished_at,
            observations=[observation],
            artifacts=artifacts,
            cost={
                "experiments": 1.0,
                "wall_time_hours": elapsed_seconds / 3600.0,
                "gpu_hours": gpu_hours,
            },
            data={
                **common_data,
                **derived,
                "primary_metric": self.definition.primary_metric,
                "primary_value": primary_value,
                "metric_direction": self.definition.metric_direction.value,
                "support_threshold": self.definition.support_threshold,
                "metric_assessment": relation,
                "metrics_artifact": store.locator(metrics_path) if metrics_path else None,
            },
        )

    def _command(self, source: Path) -> list[str]:
        assert self.bubblewrap is not None
        resources = preflight_native_resources(
            self.profile,
            prepared=self.execution_profile,
        )
        if not resources.available:
            raise ValueError(f"native execution resource preflight failed: {resources.reason}")
        return [
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
            *self._resource_arguments(resources.gpu_devices),
            "--tmpfs",
            "/tmp",
            "--remount-ro",
            "/tmp",
            "--tmpfs",
            "/work",
            "--remount-ro",
            "/work",
            "--dir",
            "/input",
            "--ro-bind",
            str(source.resolve(strict=True)),
            "/input/experiment.py",
            "--chdir",
            "/work",
            "/usr/bin/python3",
            "-I",
            "-B",
            "-c",
            (
                "import resource,runpy;"
                f"resource.setrlimit(resource.RLIMIT_NPROC,({self.definition.limits.max_processes},"
                f"{self.definition.limits.max_processes}));"
                "runpy.run_path('/input/experiment.py',run_name='__main__')"
            ),
        ]

    def _resource_arguments(
        self,
        gpu_devices: tuple[NativeGPUInventory, ...],
    ) -> list[str]:
        arguments: list[str] = []
        if self.execution_profile is not None and self.execution_profile.datasets:
            arguments.extend(["--dir", "/datasets"])
            for dataset in self.execution_profile.datasets:
                arguments.extend(
                    [
                        "--ro-bind",
                        str(dataset.materialized_path.resolve(strict=True)),
                        dataset.mount_path,
                    ]
                )
        mounted_nodes: set[str] = set()
        for device in gpu_devices:
            for node in device.device_nodes:
                if node not in mounted_nodes:
                    arguments.extend(["--dev-bind", node, node])
                    mounted_nodes.add(node)
        return arguments

    def _limit_process(self) -> None:
        assert _resource is not None
        limits = self.definition.limits
        _resource.setrlimit(_resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        memory = limits.max_memory_mb * 1024 * 1024
        _resource.setrlimit(_resource.RLIMIT_AS, (memory, memory))
        _resource.setrlimit(
            _resource.RLIMIT_FSIZE,
            (limits.max_output_bytes, limits.max_output_bytes),
        )
        _resource.setrlimit(
            _resource.RLIMIT_NOFILE,
            (limits.max_open_files, limits.max_open_files),
        )
        _resource.setrlimit(_resource.RLIMIT_CORE, (0, 0))


def load_native_experiment_definition(path: str | Path) -> NativeExperimentDefinition:
    requested_config = Path(path)
    if requested_config.is_symlink():
        raise ValueError("native experiment config must be a regular non-symlink file")
    config_path = requested_config.resolve(strict=True)
    if not config_path.is_file():
        raise ValueError("native experiment config must be a regular non-symlink file")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("native experiment config must contain a mapping")
    source = payload.get("source_path")
    if not isinstance(source, str):
        raise ValueError("native experiment source_path must be a string")
    requested_source = config_path.parent / source
    if requested_source.is_symlink():
        raise ValueError("native experiment source must be a regular non-symlink file")
    payload["source_path"] = requested_source.resolve(strict=True)
    definition = NativeExperimentDefinition.model_validate(payload)
    if not definition.source_path.is_file():
        raise ValueError("native experiment source must be a regular non-symlink file")
    return definition


def parse_measurements(stdout: bytes) -> NativeMeasurementEnvelope:
    if b"\x00" in stdout:
        raise ValueError("native experiment stdout contains NUL bytes")
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("native experiment stdout is not UTF-8") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    machine_lines = [line for line in lines if line.startswith(_MEASUREMENT_MARKER)]
    if len(machine_lines) != 1 or not lines or lines[-1] != machine_lines[0]:
        raise ValueError("stdout must end with exactly one SCITASTE_MEASUREMENTS_JSON record")
    try:
        payload = json.loads(
            machine_lines[0][len(_MEASUREMENT_MARKER) :],
            object_pairs_hook=_unique_json_object,
        )
        return NativeMeasurementEnvelope.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid SCITASTE_MEASUREMENTS_JSON record") from exc


def _derive_metrics(
    envelope: NativeMeasurementEnvelope,
    definition: NativeExperimentDefinition,
) -> dict[str, object]:
    names = sorted(envelope.measurements[0].metrics)
    if definition.primary_metric not in names:
        raise ValueError(
            f"measurements do not contain registered primary metric {definition.primary_metric!r}"
        )
    if definition.required_metrics and set(names) != set(definition.required_metrics):
        missing = sorted(set(definition.required_metrics) - set(names))
        unexpected = sorted(set(names) - set(definition.required_metrics))
        raise ValueError(
            "measurements do not match the admitted metric contract: "
            f"missing={missing}, unexpected={unexpected}"
        )
    columns = {
        name: [float(item.metrics[name]) for item in envelope.measurements] for name in names
    }
    metrics = {name: statistics.fmean(values) for name, values in columns.items()}
    primary_values = columns[definition.primary_metric]
    supports = [
        value >= definition.support_threshold
        if definition.metric_direction == MetricDirection.MAXIMIZE
        else value <= definition.support_threshold
        for value in primary_values
    ]
    primary_mean = metrics[definition.primary_metric]
    dispersion = statistics.pstdev(primary_values) if len(primary_values) > 1 else 0.0
    relative_uncertainty = min(1.0, dispersion / max(abs(primary_mean), 1e-12))
    relation = (
        "supports"
        if (
            primary_mean >= definition.support_threshold
            if definition.metric_direction == MetricDirection.MAXIMIZE
            else primary_mean <= definition.support_threshold
        )
        else "contradicts"
    )
    expected_support = relation == "supports"
    stability = sum(item == expected_support for item in supports) / len(supports)
    return {
        "metrics": metrics,
        "replicate_count": len(envelope.measurements),
        "replicate_ids": [item.replicate_id for item in envelope.measurements],
        "primary_values": primary_values,
        "primary_dispersion": dispersion,
        "reproducible": len(primary_values) >= 2 and stability >= 2 / 3,
        "stability": stability,
        "statistical_uncertainty": relative_uncertainty,
        "relation": relation,
        "metric_derivation": "arithmetic-mean-of-validated-replicates",
    }


def _find_executable(name: str) -> str | None:
    for directory in os.get_exec_path():
        candidate = Path(directory) / name
        if candidate.is_file() and not candidate.is_symlink() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


__all__ = [
    "MetricDirection",
    "NativeExperimentAvailability",
    "NativeExperimentDefinition",
    "NativeExperimentLimits",
    "NativeExperimentRunner",
    "NativeMeasurement",
    "NativeMeasurementEnvelope",
    "load_native_experiment_definition",
    "parse_measurements",
]

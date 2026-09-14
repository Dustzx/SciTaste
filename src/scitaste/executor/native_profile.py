"""Content-bound data, runtime, model, and accelerator profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import content_sha256

_MAX_PROFILE_BYTES = 65_536
_DATASET_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_SHA256 = r"^[0-9a-f]{64}$"
_EXTERNAL_ROOTS = {
    "model": "/models",
    "python-runtime": "/runtime",
    "python-packages": "/runtime",
}


class NativeDatasetInput(BaseModel):
    """One explicitly admitted read-only dataset source."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    dataset_id: str = Field(pattern=_DATASET_ID)
    source_path: Path
    expected_sha256: str = Field(pattern=_SHA256)
    max_files: int = Field(default=10_000, ge=1, le=100_000)
    max_total_bytes: int = Field(default=21_474_836_480, ge=1, le=1_099_511_627_776)

    @property
    def mount_path(self) -> str:
        return f"/datasets/{self.dataset_id}"


class NativeExternalResourceInput(BaseModel):
    """One large immutable host tree admitted without duplicating its bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    resource_id: str = Field(pattern=_DATASET_ID)
    resource_kind: Literal["model", "python-runtime", "python-packages"]
    source_path: Path
    expected_sha256: str = Field(pattern=_SHA256)
    max_files: int = Field(default=100_000, ge=1, le=500_000)
    max_total_bytes: int = Field(default=21_474_836_480, ge=1, le=1_099_511_627_776)
    allow_internal_symlinks: bool = False

    @property
    def mount_path(self) -> str:
        return f"{_EXTERNAL_ROOTS[self.resource_kind]}/{self.resource_id}"


class NativePythonRuntimeRequest(BaseModel):
    """Interpreter and import/library paths selected from admitted runtime trees."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    executable: str
    python_paths: tuple[str, ...] = ()
    library_paths: tuple[str, ...] = ()
    ephemeral_tmp: bool = False

    @field_validator("executable")
    @classmethod
    def executable_is_absolute_and_normalized(cls, value: str) -> str:
        return _validate_sandbox_path(value, label="Python executable")

    @field_validator("python_paths", "library_paths")
    @classmethod
    def paths_are_absolute_unique_and_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 16 or len(set(value)) != len(value):
            raise ValueError("native Python paths must be unique and bounded")
        return tuple(_validate_sandbox_path(item, label="Python path") for item in value)


class NativeGPUDeviceRequest(BaseModel):
    """Expected identity and minimum capacity for one NVIDIA device."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    index: int = Field(ge=0, le=31)
    expected_uuid: str | None = Field(default=None, pattern=r"^GPU-[A-Za-z0-9-]{8,128}$")
    expected_name: str | None = Field(default=None, min_length=1, max_length=128)
    min_memory_mb: int | None = Field(default=None, ge=1, le=1_048_576)


class NativeGPURequest(BaseModel):
    """Default-deny NVIDIA authorization and its hard usage budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    devices: tuple[NativeGPUDeviceRequest, ...] = ()
    max_gpu_hours: float = Field(default=0.0, ge=0.0, le=10_000.0)

    @model_validator(mode="after")
    def enabled_request_is_explicit_and_bounded(self) -> NativeGPURequest:
        indices = [device.index for device in self.devices]
        if len(indices) != len(set(indices)) or len(indices) > 8:
            raise ValueError("native GPU device indices must be unique and bounded")
        if self.enabled and (not self.devices or self.max_gpu_hours <= 0.0):
            raise ValueError("enabled native GPU access requires devices and max_gpu_hours")
        if not self.enabled and (self.devices or self.max_gpu_hours != 0.0):
            raise ValueError("disabled native GPU access cannot retain devices or a budget")
        return self


class NativeExecutionProfile(BaseModel):
    """No-network, read-only resource authority for one native experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    profile_id: str = Field(pattern=_DATASET_ID)
    datasets: tuple[NativeDatasetInput, ...] = ()
    external_resources: tuple[NativeExternalResourceInput, ...] = ()
    python_runtime: NativePythonRuntimeRequest | None = None
    gpu: NativeGPURequest = Field(default_factory=NativeGPURequest)
    network_access: Literal[False] = False
    writable_workspace: bool = False

    @model_validator(mode="after")
    def resource_identities_are_unique_and_runtime_is_admitted(self) -> NativeExecutionProfile:
        identifiers = [dataset.dataset_id for dataset in self.datasets]
        if len(identifiers) != len(set(identifiers)) or len(identifiers) > 32:
            raise ValueError("native dataset identities must be unique and bounded")
        external_ids = [resource.resource_id for resource in self.external_resources]
        if len(external_ids) != len(set(external_ids)) or len(external_ids) > 16:
            raise ValueError("native external resource identities must be unique and bounded")
        mounts = [resource.mount_path for resource in self.external_resources]
        if len(mounts) != len(set(mounts)):
            raise ValueError("native external resource mount paths must be unique")
        if self.schema_version == "1.0" and (self.external_resources or self.python_runtime):
            raise ValueError("native profile schema 1.0 cannot admit external runtime resources")
        if self.writable_workspace and self.schema_version != "1.2":
            raise ValueError("writable task workspaces require native profile schema 1.2")
        if self.python_runtime is not None:
            runtime_mounts = [
                PurePosixPath(resource.mount_path)
                for resource in self.external_resources
                if resource.resource_kind in {"python-runtime", "python-packages"}
            ]
            executable = PurePosixPath(self.python_runtime.executable)
            executable_mounts = [
                PurePosixPath(resource.mount_path)
                for resource in self.external_resources
                if resource.resource_kind == "python-runtime"
            ]
            if not any(_is_beneath(executable, mount) for mount in executable_mounts):
                raise ValueError("native Python executable must be inside a runtime resource")
            for value in (*self.python_runtime.python_paths, *self.python_runtime.library_paths):
                if not any(_is_beneath(PurePosixPath(value), mount) for mount in runtime_mounts):
                    raise ValueError(
                        "native Python paths must be inside admitted runtime resources"
                    )
        return self


class NativeDatasetSnapshot(BaseModel):
    """Verified external dataset identity before project materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(pattern=_DATASET_ID)
    source_path: Path
    kind: Literal["file", "directory"]
    content_sha256: str = Field(pattern=_SHA256)
    file_count: int = Field(ge=1)
    total_bytes: int = Field(ge=0)
    mount_path: str

    @field_validator("mount_path")
    @classmethod
    def mount_is_derived_and_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if len(path.parts) != 3 or path.parts[:2] != ("/", "datasets"):
            raise ValueError("native dataset mount must be beneath /datasets")
        return value


class NativeExternalResourceSnapshot(BaseModel):
    """Verified identity of a large read-only tree at profile inspection time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str = Field(pattern=_DATASET_ID)
    resource_kind: Literal["model", "python-runtime", "python-packages"]
    source_path: Path
    content_sha256: str = Field(pattern=_SHA256)
    file_count: int = Field(ge=1)
    symlink_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    mount_path: str

    @model_validator(mode="after")
    def mount_is_derived_and_safe(self) -> NativeExternalResourceSnapshot:
        expected = f"{_EXTERNAL_ROOTS[self.resource_kind]}/{self.resource_id}"
        if self.mount_path != expected:
            raise ValueError("native external resource mount does not match its identity")
        return self


class NativeExecutionProfileInspection(BaseModel):
    """Content-bound profile inspection that is safe to use in workflow hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_path: Path
    config_sha256: str = Field(pattern=_SHA256)
    profile: NativeExecutionProfile
    datasets: tuple[NativeDatasetSnapshot, ...]
    external_resources: tuple[NativeExternalResourceSnapshot, ...] = ()
    fingerprint: str = Field(pattern=_SHA256)


class NativeExecutionProfileRequest(BaseModel):
    """Resolved profile configuration without reading or hashing its large resources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_path: Path
    config_sha256: str = Field(pattern=_SHA256)
    profile: NativeExecutionProfile


class NativePreparedDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(pattern=_DATASET_ID)
    materialized_path: Path
    kind: Literal["file", "directory"]
    content_sha256: str = Field(pattern=_SHA256)
    file_count: int = Field(ge=1)
    total_bytes: int = Field(ge=0)
    mount_path: str

    @model_validator(mode="after")
    def mount_matches_dataset_identity(self) -> NativePreparedDataset:
        if self.mount_path != f"/datasets/{self.dataset_id}":
            raise ValueError("prepared native dataset mount does not match its identity")
        return self


class NativePreparedExternalResource(NativeExternalResourceSnapshot):
    """Verified external tree retained at its explicit read-only source path."""


class PreparedNativeExecutionProfile(BaseModel):
    """Run-owned profile and dataset copies used by Bubblewrap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: NativeExecutionProfile
    fingerprint: str = Field(pattern=_SHA256)
    manifest_path: Path
    datasets: tuple[NativePreparedDataset, ...]
    external_resources: tuple[NativePreparedExternalResource, ...] = ()
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def prepared_datasets_match_profile(self) -> PreparedNativeExecutionProfile:
        expected = [item.dataset_id for item in self.profile.datasets]
        actual = [item.dataset_id for item in self.datasets]
        if actual != expected:
            raise ValueError("prepared native datasets do not match the execution profile")
        expected_external = [item.resource_id for item in self.profile.external_resources]
        actual_external = [item.resource_id for item in self.external_resources]
        if actual_external != expected_external:
            raise ValueError(
                "prepared native external resources do not match the execution profile"
            )
        return self


class NativeGPUInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    uuid: str
    name: str
    memory_total_mb: int = Field(ge=1)
    device_nodes: tuple[str, ...]


class NativeResourceAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    profile_id: str
    dataset_mounts: tuple[str, ...]
    external_mounts: tuple[str, ...] = ()
    gpu_devices: tuple[NativeGPUInventory, ...] = ()
    reason: str | None = None


def inspect_native_execution_profile(path: str | Path) -> NativeExecutionProfileInspection:
    """Load a strict profile and bind every admitted data/runtime/model tree."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("native execution profile must be a regular non-symlink file")
    config_path = requested.resolve(strict=True)
    if not config_path.is_file() or config_path.stat().st_size > _MAX_PROFILE_BYTES:
        raise ValueError("native execution profile must be a bounded regular file")
    raw = config_path.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("native execution profile is not valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("native execution profile must contain a mapping")
    raw_datasets = payload.get("datasets", [])
    if not isinstance(raw_datasets, list):
        raise ValueError("native execution profile datasets must be a list")
    resolved_datasets: list[dict[str, object]] = []
    for raw_dataset in raw_datasets:
        if not isinstance(raw_dataset, dict):
            raise ValueError("native execution profile dataset entries must be mappings")
        source = raw_dataset.get("source_path")
        if not isinstance(source, str):
            raise ValueError("native dataset source_path must be a string")
        candidate = Path(os.path.expandvars(source))
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        if candidate.is_symlink():
            raise ValueError("native dataset sources cannot be symlinks")
        resolved_datasets.append({**raw_dataset, "source_path": candidate.resolve(strict=True)})
    payload["datasets"] = resolved_datasets
    raw_external = payload.get("external_resources", [])
    if not isinstance(raw_external, list):
        raise ValueError("native execution profile external_resources must be a list")
    resolved_external: list[dict[str, object]] = []
    for raw_resource in raw_external:
        if not isinstance(raw_resource, dict):
            raise ValueError("native external resource entries must be mappings")
        source = raw_resource.get("source_path")
        if not isinstance(source, str):
            raise ValueError("native external resource source_path must be a string")
        candidate = Path(os.path.expandvars(source))
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        if candidate.is_symlink():
            raise ValueError("native external resource sources cannot be symlinks")
        resolved_external.append({**raw_resource, "source_path": candidate.resolve(strict=True)})
    payload["external_resources"] = resolved_external
    profile = NativeExecutionProfile.model_validate(payload)
    snapshots = tuple(_snapshot_dataset(item) for item in profile.datasets)
    external_snapshots = tuple(
        _snapshot_external_resource(item) for item in profile.external_resources
    )
    _verify_python_runtime_layout(profile, external_snapshots)
    semantic = {
        "schema_version": profile.schema_version,
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "profile": _profile_record_payload(profile),
        "datasets": [item.model_dump(mode="json", exclude={"source_path"}) for item in snapshots],
    }
    if profile.schema_version in {"1.1", "1.2"}:
        semantic["external_resources"] = [
            item.model_dump(mode="json", exclude={"source_path"}) for item in external_snapshots
        ]
    return NativeExecutionProfileInspection(
        config_path=config_path,
        config_sha256=semantic["config_sha256"],
        profile=profile,
        datasets=snapshots,
        external_resources=external_snapshots,
        fingerprint=content_sha256(semantic),
    )


def load_native_execution_profile_request(
    path: str | Path,
) -> NativeExecutionProfileRequest:
    """Load expected resource identities without traversing the resource trees."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("native execution profile must be a regular non-symlink file")
    config_path = requested.resolve(strict=True)
    if not config_path.is_file() or config_path.stat().st_size > _MAX_PROFILE_BYTES:
        raise ValueError("native execution profile must be a bounded regular file")
    raw = config_path.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("native execution profile is not valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("native execution profile must contain a mapping")
    for field in ("datasets", "external_resources"):
        items = payload.get(field, [])
        if not isinstance(items, list):
            raise ValueError(f"native execution profile {field} must be a list")
        resolved_items: list[dict[str, object]] = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                raise ValueError(f"native execution profile {field} entries must be mappings")
            source = raw_item.get("source_path")
            if not isinstance(source, str):
                raise ValueError("native execution resource source_path must be a string")
            candidate = Path(os.path.expandvars(source))
            if not candidate.is_absolute():
                candidate = config_path.parent / candidate
            if candidate.is_symlink():
                raise ValueError("native execution resource sources cannot be symlinks")
            resolved_items.append({**raw_item, "source_path": candidate.resolve(strict=True)})
        payload[field] = resolved_items
    return NativeExecutionProfileRequest(
        config_path=config_path,
        config_sha256=hashlib.sha256(raw).hexdigest(),
        profile=NativeExecutionProfile.model_validate(payload),
    )


def prepare_native_execution_profile(
    inspection: NativeExecutionProfileInspection,
    *,
    run_root: str | Path,
) -> PreparedNativeExecutionProfile:
    """Copy admitted datasets once and verify exact copies on every resume."""

    owned_root = Path(run_root).resolve(strict=True)
    resource_root = owned_root / "native_execution" / "context" / "resources"
    manifest_path = resource_root / "PROFILE.json"
    if manifest_path.exists():
        return _load_prepared_profile(inspection, owned_root, manifest_path)
    if resource_root.exists():
        raise ValueError("incomplete native execution resource context requires inspection")
    datasets_root = resource_root / "datasets"
    datasets_root.mkdir(parents=True)
    prepared: list[NativePreparedDataset] = []
    for expected, source in zip(inspection.datasets, inspection.profile.datasets, strict=True):
        current = _snapshot_dataset(source)
        if current != expected:
            raise ValueError(f"native dataset changed before materialization: {source.dataset_id}")
        target = datasets_root / source.dataset_id
        if expected.kind == "file":
            _copy_regular_file(expected.source_path, target)
        else:
            target.mkdir()
            for relative, _size, _digest in _dataset_entries(source):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                _copy_regular_file(expected.source_path / relative, destination)
        copied = _snapshot_dataset(source.model_copy(update={"source_path": target}))
        if copied.content_sha256 != expected.content_sha256:
            raise ValueError(f"native dataset changed while materialized: {source.dataset_id}")
        prepared.append(
            NativePreparedDataset(
                dataset_id=source.dataset_id,
                materialized_path=target,
                kind=expected.kind,
                content_sha256=expected.content_sha256,
                file_count=expected.file_count,
                total_bytes=expected.total_bytes,
                mount_path=expected.mount_path,
            )
        )
    external_resources = tuple(
        NativePreparedExternalResource.model_validate(item.model_dump(mode="python"))
        for item in inspection.external_resources
    )
    profile_payload = _profile_record_payload(inspection.profile)
    payload = {
        "schema_version": inspection.profile.schema_version,
        "profile_fingerprint": inspection.fingerprint,
        "source_config_sha256": inspection.config_sha256,
        "profile": profile_payload,
        "datasets": [
            {
                **item.model_dump(mode="json", exclude={"materialized_path"}),
                "materialized_locator": _owned_locator(owned_root, item.materialized_path),
            }
            for item in prepared
        ],
    }
    if inspection.profile.schema_version in {"1.1", "1.2"}:
        payload["external_resources"] = [
            item.model_dump(mode="json", exclude={"source_path"}) for item in external_resources
        ]
    record_sha256 = content_sha256(payload)
    _write_exclusive_json(manifest_path, {**payload, "record_sha256": record_sha256})
    return PreparedNativeExecutionProfile(
        profile=inspection.profile,
        fingerprint=inspection.fingerprint,
        manifest_path=manifest_path,
        datasets=tuple(prepared),
        external_resources=external_resources,
        record_sha256=record_sha256,
    )


def load_prepared_native_execution_profile(
    inspection: NativeExecutionProfileInspection,
    *,
    run_root: str | Path,
    verify_integrity: bool = True,
) -> PreparedNativeExecutionProfile:
    """Load a prepared profile, optionally relying on a campaign verification receipt."""

    owned_root = Path(run_root).resolve(strict=True)
    manifest_path = owned_root / "native_execution" / "context" / "resources" / "PROFILE.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("prepared native execution profile record is unavailable")
    return _load_prepared_profile(
        inspection,
        owned_root,
        manifest_path,
        verify_integrity=verify_integrity,
    )


def load_prepared_native_execution_profile_record(
    request: NativeExecutionProfileRequest,
    *,
    run_root: str | Path,
) -> PreparedNativeExecutionProfile:
    """Reopen a prepared profile from its small record before receipt validation."""

    owned_root = Path(run_root).resolve(strict=True)
    manifest_path = owned_root / "native_execution" / "context" / "resources" / "PROFILE.json"
    manifest = _read_json_mapping(manifest_path)
    record_sha256 = manifest.pop("record_sha256", None)
    if not isinstance(record_sha256, str) or record_sha256 != content_sha256(manifest):
        raise ValueError("native execution profile record hash mismatch")
    if manifest.get("source_config_sha256") != request.config_sha256:
        raise ValueError("native execution profile source changed since materialization")
    if manifest.get("profile") != _profile_record_payload(request.profile):
        raise ValueError("native execution profile record differs from its request")
    fingerprint = manifest.get("profile_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(_SHA256, fingerprint):
        raise ValueError("native execution profile fingerprint is invalid")
    raw_datasets = manifest.get("datasets")
    if not isinstance(raw_datasets, list) or len(raw_datasets) != len(request.profile.datasets):
        raise ValueError("native execution profile dataset record is incomplete")
    datasets: list[NativePreparedDataset] = []
    for raw_item, declared in zip(raw_datasets, request.profile.datasets, strict=True):
        if not isinstance(raw_item, dict):
            raise ValueError("native execution profile dataset record is invalid")
        item = dict(raw_item)
        locator = item.pop("materialized_locator", None)
        if not isinstance(locator, str):
            raise ValueError("native execution profile dataset locator is missing")
        prepared = NativePreparedDataset.model_validate(
            {
                **item,
                "materialized_path": _owned_regular_tree(owned_root, locator),
            }
        )
        if (
            prepared.dataset_id != declared.dataset_id
            or prepared.content_sha256 != declared.expected_sha256
        ):
            raise ValueError("prepared dataset identity differs from its profile request")
        datasets.append(prepared)
    raw_external = manifest.get("external_resources", [])
    if not isinstance(raw_external, list) or len(raw_external) != len(
        request.profile.external_resources
    ):
        raise ValueError("native execution profile external resource record is incomplete")
    external: list[NativePreparedExternalResource] = []
    for raw_item, declared in zip(
        raw_external,
        request.profile.external_resources,
        strict=True,
    ):
        if not isinstance(raw_item, dict):
            raise ValueError("native execution profile external resource record is invalid")
        prepared = NativePreparedExternalResource.model_validate(
            {**raw_item, "source_path": declared.source_path}
        )
        if (
            prepared.resource_id != declared.resource_id
            or prepared.content_sha256 != declared.expected_sha256
        ):
            raise ValueError("prepared external identity differs from its profile request")
        external.append(prepared)
    return PreparedNativeExecutionProfile(
        profile=request.profile,
        fingerprint=fingerprint,
        manifest_path=manifest_path,
        datasets=tuple(datasets),
        external_resources=tuple(external),
        record_sha256=record_sha256,
    )


def verify_prepared_native_execution_profile(
    prepared: PreparedNativeExecutionProfile,
) -> None:
    """Fail closed if a run-owned profile record or dataset copy drifted."""

    manifest = _read_json_mapping(prepared.manifest_path)
    record_sha256 = manifest.pop("record_sha256", None)
    if record_sha256 != prepared.record_sha256 or record_sha256 != content_sha256(manifest):
        raise ValueError("native execution profile record hash mismatch")
    if manifest.get("profile_fingerprint") != prepared.fingerprint:
        raise ValueError("native execution profile fingerprint mismatch")
    expected_profile = _profile_record_payload(prepared.profile)
    if manifest.get("profile") != expected_profile:
        raise ValueError("native execution profile record does not match the admitted profile")
    manifest_datasets = manifest.get("datasets")
    if not isinstance(manifest_datasets, list) or len(manifest_datasets) != len(prepared.datasets):
        raise ValueError("native execution profile dataset record is incomplete")
    for raw, dataset in zip(manifest_datasets, prepared.datasets, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("native execution profile dataset record is invalid")
        expected = {
            **dataset.model_dump(mode="json", exclude={"materialized_path"}),
            "materialized_locator": _owned_locator(
                prepared.manifest_path.parents[3], dataset.materialized_path
            ),
        }
        if raw != expected:
            raise ValueError("native execution profile dataset record does not match its copy")
    source_by_id = {item.dataset_id: item for item in prepared.profile.datasets}
    for dataset in prepared.datasets:
        source = source_by_id[dataset.dataset_id].model_copy(
            update={"source_path": dataset.materialized_path}
        )
        snapshot = _snapshot_dataset(source)
        if (
            snapshot.content_sha256 != dataset.content_sha256
            or snapshot.file_count != dataset.file_count
            or snapshot.total_bytes != dataset.total_bytes
        ):
            raise ValueError(f"materialized native dataset hash mismatch: {dataset.dataset_id}")
    manifest_external = manifest.get("external_resources", [])
    expected_external = [
        item.model_dump(mode="json", exclude={"source_path"})
        for item in prepared.external_resources
    ]
    if manifest_external != expected_external:
        raise ValueError("native execution profile external resource record is incomplete")
    source_by_id_external = {item.resource_id: item for item in prepared.profile.external_resources}
    for resource in prepared.external_resources:
        current = _snapshot_external_resource(source_by_id_external[resource.resource_id])
        if current.model_dump(mode="json") != resource.model_dump(mode="json"):
            raise ValueError(f"native external resource changed: {resource.resource_id}")


def preflight_native_resources(
    profile: NativeExecutionProfile,
    *,
    prepared: PreparedNativeExecutionProfile | None = None,
    require_materialized_datasets: bool = True,
    verify_prepared_integrity: bool = True,
) -> NativeResourceAvailability:
    """Verify all requested dataset copies and exact NVIDIA devices."""

    mounts = tuple(item.mount_path for item in profile.datasets)
    external_mounts = tuple(item.mount_path for item in profile.external_resources)
    if profile.datasets and prepared is None and require_materialized_datasets:
        return NativeResourceAvailability(
            available=False,
            profile_id=profile.profile_id,
            dataset_mounts=mounts,
            external_mounts=external_mounts,
            reason="native datasets have not been materialized into the project run",
        )
    if prepared is not None and verify_prepared_integrity:
        try:
            verify_prepared_native_execution_profile(prepared)
        except (OSError, ValueError) as exc:
            return NativeResourceAvailability(
                available=False,
                profile_id=profile.profile_id,
                dataset_mounts=mounts,
                external_mounts=external_mounts,
                reason=str(exc),
            )
    elif prepared is not None and prepared.profile != profile:
        return NativeResourceAvailability(
            available=False,
            profile_id=profile.profile_id,
            dataset_mounts=mounts,
            external_mounts=external_mounts,
            reason="prepared native resources belong to another profile",
        )
    if not profile.gpu.enabled:
        return NativeResourceAvailability(
            available=True,
            profile_id=profile.profile_id,
            dataset_mounts=mounts,
            external_mounts=external_mounts,
        )
    inventory, error = _query_nvidia_inventory()
    if error is not None:
        return NativeResourceAvailability(
            available=False,
            profile_id=profile.profile_id,
            dataset_mounts=mounts,
            external_mounts=external_mounts,
            reason=error,
        )
    by_index = {item.index: item for item in inventory}
    selected: list[NativeGPUInventory] = []
    for request in profile.gpu.devices:
        actual = by_index.get(request.index)
        if actual is None:
            return NativeResourceAvailability(
                available=False,
                profile_id=profile.profile_id,
                dataset_mounts=mounts,
                external_mounts=external_mounts,
                reason=f"requested NVIDIA GPU index is unavailable: {request.index}",
            )
        if request.expected_uuid is not None and actual.uuid != request.expected_uuid:
            return _gpu_mismatch(profile, mounts, external_mounts, request.index, "UUID")
        if request.expected_name is not None and actual.name != request.expected_name:
            return _gpu_mismatch(profile, mounts, external_mounts, request.index, "name")
        if request.min_memory_mb is not None and actual.memory_total_mb < request.min_memory_mb:
            return _gpu_mismatch(profile, mounts, external_mounts, request.index, "memory")
        missing = [node for node in actual.device_nodes if not Path(node).exists()]
        if missing:
            return NativeResourceAvailability(
                available=False,
                profile_id=profile.profile_id,
                dataset_mounts=mounts,
                external_mounts=external_mounts,
                reason=f"requested NVIDIA device nodes are unavailable: {missing}",
            )
        selected.append(actual)
    return NativeResourceAvailability(
        available=True,
        profile_id=profile.profile_id,
        dataset_mounts=mounts,
        external_mounts=external_mounts,
        gpu_devices=tuple(selected),
    )


def _load_prepared_profile(
    inspection: NativeExecutionProfileInspection,
    owned_root: Path,
    manifest_path: Path,
    *,
    verify_integrity: bool = True,
) -> PreparedNativeExecutionProfile:
    manifest = _read_json_mapping(manifest_path)
    record_sha256 = manifest.pop("record_sha256", None)
    if not isinstance(record_sha256, str) or record_sha256 != content_sha256(manifest):
        raise ValueError("native execution profile record hash mismatch")
    if manifest.get("profile_fingerprint") != inspection.fingerprint:
        raise ValueError("native execution profile changed since the run was created")
    if manifest.get("source_config_sha256") != inspection.config_sha256:
        raise ValueError("native execution profile source changed since the run was created")
    expected_profile = _profile_record_payload(inspection.profile)
    if manifest.get("profile") != expected_profile:
        raise ValueError("native execution profile record does not match the admitted profile")
    raw_datasets = manifest.get("datasets")
    if not isinstance(raw_datasets, list):
        raise ValueError("native execution profile record is incomplete")
    prepared: list[NativePreparedDataset] = []
    for raw in raw_datasets:
        if not isinstance(raw, dict):
            raise ValueError("native execution profile dataset record is invalid")
        locator = raw.pop("materialized_locator", None)
        if not isinstance(locator, str):
            raise ValueError("native execution profile dataset locator is missing")
        path = _owned_regular_tree(owned_root, locator)
        prepared.append(NativePreparedDataset.model_validate({**raw, "materialized_path": path}))
    raw_external = manifest.get("external_resources", [])
    if not isinstance(raw_external, list) or len(raw_external) != len(
        inspection.external_resources
    ):
        raise ValueError("native execution profile external resource record is incomplete")
    prepared_external: list[NativePreparedExternalResource] = []
    for raw, inspected in zip(raw_external, inspection.external_resources, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("native execution profile external resource record is invalid")
        candidate = NativePreparedExternalResource.model_validate(
            {**raw, "source_path": inspected.source_path}
        )
        if candidate.model_dump(mode="json") != inspected.model_dump(mode="json"):
            raise ValueError("native external resource record does not match its inspection")
        prepared_external.append(candidate)
    result = PreparedNativeExecutionProfile(
        profile=inspection.profile,
        fingerprint=inspection.fingerprint,
        manifest_path=manifest_path,
        datasets=tuple(prepared),
        external_resources=tuple(prepared_external),
        record_sha256=record_sha256,
    )
    if verify_integrity:
        verify_prepared_native_execution_profile(result)
    return result


def _snapshot_dataset(dataset: NativeDatasetInput) -> NativeDatasetSnapshot:
    source = dataset.source_path
    if source.is_symlink() or not (source.is_file() or source.is_dir()):
        raise ValueError("native dataset source must be a regular file or directory")
    entries = _dataset_entries(dataset)
    kind: Literal["file", "directory"] = "file" if source.is_file() else "directory"
    if kind == "file":
        digest = entries[0][2]
    else:
        digest = content_sha256(
            {
                "schema_version": "1.0",
                "entries": [
                    {"path": path.as_posix(), "size": size, "sha256": sha256}
                    for path, size, sha256 in entries
                ],
            }
        )
    if digest != dataset.expected_sha256:
        raise ValueError(f"native dataset content hash mismatch: {dataset.dataset_id}")
    return NativeDatasetSnapshot(
        dataset_id=dataset.dataset_id,
        source_path=source,
        kind=kind,
        content_sha256=digest,
        file_count=len(entries),
        total_bytes=sum(size for _path, size, _digest in entries),
        mount_path=dataset.mount_path,
    )


def _profile_record_payload(profile: NativeExecutionProfile) -> dict[str, object]:
    excluded = {"datasets", "external_resources"}
    if profile.schema_version == "1.0":
        excluded.add("python_runtime")
    return profile.model_dump(mode="json", exclude=excluded)


def _verify_python_runtime_layout(
    profile: NativeExecutionProfile,
    resources: tuple[NativeExternalResourceSnapshot, ...],
) -> None:
    runtime = profile.python_runtime
    if runtime is None:
        return
    mounts = sorted(resources, key=lambda item: len(item.mount_path), reverse=True)

    def host_path(sandbox_path: str) -> Path:
        requested = PurePosixPath(sandbox_path)
        for resource in mounts:
            mount = PurePosixPath(resource.mount_path)
            if _is_beneath(requested, mount):
                relative = requested.relative_to(mount)
                return resource.source_path.joinpath(*relative.parts)
        raise ValueError("native Python path is not backed by an admitted resource")

    executable = host_path(runtime.executable)
    if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("native Python executable is not an executable regular file")
    for value in (*runtime.python_paths, *runtime.library_paths):
        path = host_path(value)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("native Python import/library path is not a regular directory")


def _dataset_entries(dataset: NativeDatasetInput) -> tuple[tuple[Path, int, str], ...]:
    source = dataset.source_path
    candidates = [source] if source.is_file() else sorted(source.rglob("*"))
    entries: list[tuple[Path, int, str]] = []
    total_bytes = 0
    for candidate in candidates:
        if candidate.is_symlink():
            raise ValueError(f"native dataset cannot contain symlinks: {dataset.dataset_id}")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError(f"native dataset cannot contain special files: {dataset.dataset_id}")
        size = candidate.stat().st_size
        total_bytes += size
        if len(entries) + 1 > dataset.max_files or total_bytes > dataset.max_total_bytes:
            raise ValueError(f"native dataset exceeds its declared bounds: {dataset.dataset_id}")
        relative = Path(candidate.name) if source.is_file() else candidate.relative_to(source)
        entries.append((relative, size, _file_sha256(candidate)))
    if not entries:
        raise ValueError(f"native dataset must contain at least one file: {dataset.dataset_id}")
    return tuple(entries)


def native_external_tree_sha256(
    path: str | Path,
    *,
    max_files: int = 100_000,
    max_total_bytes: int = 21_474_836_480,
    allow_internal_symlinks: bool = False,
) -> str:
    """Compute the canonical digest used by large read-only native resources."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("native external resource source must be a non-symlink directory")
    probe = NativeExternalResourceInput(
        resource_id="digest-probe",
        resource_kind="model",
        source_path=requested.resolve(strict=True),
        expected_sha256="0" * 64,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        allow_internal_symlinks=allow_internal_symlinks,
    )
    entries, _total_bytes, _symlinks = _external_resource_entries(probe)
    return _external_entries_sha256(entries)


def _snapshot_external_resource(
    resource: NativeExternalResourceInput,
) -> NativeExternalResourceSnapshot:
    source = resource.source_path
    if source.is_symlink() or not source.is_dir():
        raise ValueError("native external resource source must be a non-symlink directory")
    entries, total_bytes, symlink_count = _external_resource_entries(resource)
    digest = _external_entries_sha256(entries)
    if digest != resource.expected_sha256:
        raise ValueError(f"native external resource content hash mismatch: {resource.resource_id}")
    return NativeExternalResourceSnapshot(
        resource_id=resource.resource_id,
        resource_kind=resource.resource_kind,
        source_path=source,
        content_sha256=digest,
        file_count=len(entries),
        symlink_count=symlink_count,
        total_bytes=total_bytes,
        mount_path=resource.mount_path,
    )


def _external_resource_entries(
    resource: NativeExternalResourceInput,
) -> tuple[tuple[str, str, int, str], int, int]:
    root = resource.source_path
    candidates = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    entries: list[tuple[str, str, int, str]] = []
    total_bytes = 0
    symlink_count = 0
    resolved_root = root.resolve(strict=True)
    for candidate in candidates:
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            if not resource.allow_internal_symlinks:
                raise ValueError(
                    f"native external resource cannot contain symlinks: {resource.resource_id}"
                )
            target = os.readlink(candidate)
            if Path(target).is_absolute():
                raise ValueError("native external resource symlinks must be relative")
            try:
                candidate.resolve(strict=True).relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError("native external resource symlink escapes its tree") from exc
            entries.append(("symlink", relative, len(target.encode()), target))
            symlink_count += 1
        elif candidate.is_dir():
            continue
        elif candidate.is_file():
            size = candidate.stat().st_size
            total_bytes += size
            entries.append(("file", relative, size, _file_sha256(candidate)))
        else:
            raise ValueError(
                f"native external resource contains a special entry: {resource.resource_id}"
            )
        if len(entries) > resource.max_files or total_bytes > resource.max_total_bytes:
            raise ValueError(
                f"native external resource exceeds its declared bounds: {resource.resource_id}"
            )
    if not entries:
        raise ValueError(f"native external resource must contain files: {resource.resource_id}")
    return tuple(entries), total_bytes, symlink_count


def _external_entries_sha256(entries: tuple[tuple[str, str, int, str], ...]) -> str:
    return content_sha256(
        {
            "schema_version": "1.0",
            "entries": [
                {"type": kind, "path": path, "size": size, "identity": identity}
                for kind, path, size, identity in entries
            ],
        }
    )


def _validate_sandbox_path(value: str, *, label: str) -> str:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be an absolute normalized sandbox path")
    if any(re.fullmatch(r"[A-Za-z0-9._+-]+", part) is None for part in path.parts[1:]):
        raise ValueError(f"{label} contains an unsafe path segment")
    return value


def _is_beneath(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _query_nvidia_inventory() -> tuple[tuple[NativeGPUInventory, ...], str | None]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return (), "nvidia-smi executable was not found"
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,uuid,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5.0,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (), f"NVIDIA inventory probe failed: {type(exc).__name__}"
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:240]
        return (), f"nvidia-smi returned {result.returncode}: {detail}"
    inventory: list[NativeGPUInventory] = []
    try:
        for line in result.stdout.decode("utf-8").splitlines():
            index, uuid, name, memory = (part.strip() for part in line.split(",", 3))
            nodes = [f"/dev/nvidia{int(index)}", "/dev/nvidiactl"]
            for optional in ("/dev/nvidia-uvm", "/dev/nvidia-uvm-tools"):
                if Path(optional).exists():
                    nodes.append(optional)
            inventory.append(
                NativeGPUInventory(
                    index=int(index),
                    uuid=uuid,
                    name=name,
                    memory_total_mb=int(memory),
                    device_nodes=tuple(nodes),
                )
            )
    except (UnicodeDecodeError, ValueError) as exc:
        return (), f"invalid nvidia-smi inventory: {type(exc).__name__}"
    return tuple(inventory), None


def _gpu_mismatch(
    profile: NativeExecutionProfile,
    mounts: tuple[str, ...],
    external_mounts: tuple[str, ...],
    index: int,
    field: str,
) -> NativeResourceAvailability:
    return NativeResourceAvailability(
        available=False,
        profile_id=profile.profile_id,
        dataset_mounts=mounts,
        external_mounts=external_mounts,
        reason=f"requested NVIDIA GPU {index} {field} does not match the admitted profile",
    )


def _copy_regular_file(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("native dataset copy source must be a regular file")
    with source.open("rb") as input_stream, target.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream)
        output_stream.flush()
        os.fsync(output_stream.fileno())


def _owned_locator(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError:
        return f"external:{path.resolve(strict=True)}"


def _owned_regular_tree(root: Path, locator: str) -> Path:
    relative = PurePosixPath(locator)
    if relative.is_absolute() or ".." in relative.parts or locator.startswith("external:"):
        raise ValueError("native execution resource locator must be project-owned")
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("native execution resource locator contains a symlink")
    target.resolve(strict=True).relative_to(root)
    if target.is_symlink() or not (target.is_file() or target.is_dir()):
        raise ValueError("native execution resource locator is not a regular tree")
    return target


def _read_json_mapping(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("native execution profile record must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("native execution profile record must contain a mapping")
    return payload


def _write_exclusive_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "NativeDatasetInput",
    "NativeDatasetSnapshot",
    "NativeExecutionProfile",
    "NativeExecutionProfileInspection",
    "NativeExecutionProfileRequest",
    "NativeExternalResourceInput",
    "NativeExternalResourceSnapshot",
    "NativeGPUDeviceRequest",
    "NativeGPUInventory",
    "NativeGPURequest",
    "NativePreparedDataset",
    "NativePreparedExternalResource",
    "NativePythonRuntimeRequest",
    "NativeResourceAvailability",
    "PreparedNativeExecutionProfile",
    "inspect_native_execution_profile",
    "load_native_execution_profile_request",
    "load_prepared_native_execution_profile",
    "load_prepared_native_execution_profile_record",
    "native_external_tree_sha256",
    "preflight_native_resources",
    "prepare_native_execution_profile",
    "verify_prepared_native_execution_profile",
]

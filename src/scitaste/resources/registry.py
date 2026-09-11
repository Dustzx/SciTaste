"""Secret-free catalog and observations for shared API/GPU resources."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_ENV = r"^[A-Z][A-Z0-9_]{2,100}$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 1_048_576


class ResourceKind(StrEnum):
    API_MODEL = "api_model"
    GPU_HOST = "gpu_host"


class ObservationMethod(StrEnum):
    AUTOMATED_PROBE = "automated_probe"
    AUTHENTICATED_CALL = "authenticated_call"
    OFFICIAL_CATALOG = "official_catalog"
    OWNER_REPORT = "owner_report"


class ObservationStatus(StrEnum):
    VERIFIED = "verified"
    REPORTED = "reported"
    PENDING = "pending"
    BLOCKED = "blocked"


class ApiPriceCeiling(BaseModel):
    model_config = _CONFIG

    currency: Literal["USD", "CNY"]
    as_of: date
    input_cache_hit_per_million: float | None = Field(default=None, ge=0)
    input_cache_miss_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    source_url: str = Field(min_length=1, max_length=2_000)
    status: ObservationStatus


class ApiModelDefinition(BaseModel):
    model_config = _CONFIG

    kind: Literal[ResourceKind.API_MODEL] = ResourceKind.API_MODEL
    resource_id: str = Field(pattern=_ID)
    provider_id: str = Field(pattern=_ID)
    endpoint: str = Field(min_length=1, max_length=2_000)
    interface: Literal["openai-chat-completions", "openai-responses"]
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str = Field(min_length=1, max_length=200)
    rolling_alias: bool
    identity_source_url: str = Field(min_length=1, max_length=2_000)
    identity_verified_on: date
    credential_env: str = Field(pattern=_ENV)
    pricing: ApiPriceCeiling | None = None

    @model_validator(mode="after")
    def endpoint_is_https(self) -> ApiModelDefinition:
        if not self.endpoint.startswith("https://"):
            raise ValueError("API resource endpoint must use HTTPS")
        return self


class GpuHostDefinition(BaseModel):
    model_config = _CONFIG

    kind: Literal[ResourceKind.GPU_HOST] = ResourceKind.GPU_HOST
    resource_id: str = Field(pattern=_ID)
    host_alias: str = Field(pattern=_ID)
    access_profile: str = Field(min_length=1, max_length=200)
    device_count: int = Field(gt=0, le=64)
    device_name: str = Field(min_length=1, max_length=200)
    minimum_memory_mb_per_device: int = Field(gt=0)
    baseline_inventory_ref: str = Field(min_length=1, max_length=1_000)
    baseline_inventory_sha256: str = Field(pattern=_SHA256)
    baseline_observed_at: datetime

    @model_validator(mode="after")
    def baseline_time_is_aware(self) -> GpuHostDefinition:
        if self.baseline_observed_at.tzinfo is None:
            raise ValueError("GPU baseline observation time must include a timezone")
        _validate_relative_locator(self.baseline_inventory_ref)
        return self


ComputeResourceDefinition = Annotated[
    ApiModelDefinition | GpuHostDefinition,
    Field(discriminator="kind"),
]


class ComputeResourceCatalog(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    catalog_id: str = Field(pattern=_ID)
    resources: tuple[ComputeResourceDefinition, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def resource_ids_are_unique(self) -> ComputeResourceCatalog:
        resource_ids = [item.resource_id for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("compute resource IDs must be unique")
        return self

    def resource(self, resource_id: str) -> ComputeResourceDefinition:
        try:
            return next(item for item in self.resources if item.resource_id == resource_id)
        except StopIteration as exc:
            raise ValueError(f"unknown compute resource {resource_id!r}") from exc


class LoadedComputeResourceCatalog(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)
    catalog: ComputeResourceCatalog


class ComputeResourceCatalogInspection(BaseModel):
    model_config = _CONFIG

    catalog_id: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)
    resource_ids: tuple[str, ...]
    gpu_host_ids: tuple[str, ...]
    api_model_ids: tuple[str, ...]
    evidence_verified: bool
    evidence_issues: tuple[str, ...]
    secret_values_loaded: Literal[False] = False
    external_action_performed: Literal[False] = False


class ResourceObservation(BaseModel):
    """One bounded observation; it can report availability but cannot reserve work."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    observation_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    resource_kind: ResourceKind
    observed_at: datetime
    method: ObservationMethod
    status: ObservationStatus
    available_storage_bytes: int | None = Field(default=None, ge=0)
    available_storage_gb_reported: float | None = Field(default=None, ge=0)
    observed_device_count: int | None = Field(default=None, ge=0, le=64)
    observed_device_name: str | None = Field(default=None, min_length=1, max_length=200)
    requested_model_id: str | None = Field(default=None, min_length=1, max_length=200)
    returned_model_revision: str | None = Field(default=None, min_length=1, max_length=200)
    request_succeeded: bool | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=2_000)
    notes: tuple[str, ...] = Field(default=(), max_length=20)
    credentials_recorded: Literal[False] = False
    observation_only: Literal[True] = True

    @model_validator(mode="after")
    def observation_is_typed_and_honest(self) -> ResourceObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("resource observation time must include a timezone")
        if (
            self.method is ObservationMethod.OWNER_REPORT
            and self.status is not ObservationStatus.REPORTED
        ):
            raise ValueError(
                "owner reports must retain reported status until independently verified"
            )
        gpu_values = (
            self.available_storage_bytes,
            self.available_storage_gb_reported,
            self.observed_device_count,
            self.observed_device_name,
        )
        api_values = (
            self.requested_model_id,
            self.returned_model_revision,
            self.request_succeeded,
        )
        if self.resource_kind is ResourceKind.API_MODEL and any(
            value is not None for value in gpu_values
        ):
            raise ValueError("API observations cannot contain GPU host fields")
        if self.resource_kind is ResourceKind.GPU_HOST and any(
            value is not None for value in api_values
        ):
            raise ValueError("GPU observations cannot contain API model fields")
        has_fact = any(value is not None for value in (*gpu_values, *api_values, self.source_url))
        if not has_fact and not self.notes:
            raise ValueError("resource observations require at least one bounded fact or note")
        return self


class RegisteredResourceObservation(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    observation: ResourceObservation
    source_sha256: str = Field(pattern=_SHA256)
    source_size_bytes: int = Field(gt=0, le=_MAX_INPUT_BYTES)
    record_sha256: str = Field(pattern=_SHA256)

    def calculated_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"record_sha256"})
        return _semantic_sha256(payload)


class ResourceRegistrySnapshot(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    catalog_id: str
    catalog_file_sha256: str = Field(pattern=_SHA256)
    catalog_semantic_sha256: str = Field(pattern=_SHA256)
    catalog_source: str = Field(min_length=1, max_length=2_000)
    registry_sha256: str = Field(pattern=_SHA256)

    def calculated_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"registry_sha256"})
        return _semantic_sha256(payload)


class ResourceStatusItem(BaseModel):
    model_config = _CONFIG

    resource_id: str
    kind: ResourceKind
    definition: ComputeResourceDefinition
    latest_observation: ResourceObservation | None
    observation_count: int = Field(ge=0)


class ResourceRegistryStatus(BaseModel):
    model_config = _CONFIG

    catalog_id: str
    registry_sha256: str = Field(pattern=_SHA256)
    catalog_semantic_sha256: str = Field(pattern=_SHA256)
    resources: tuple[ResourceStatusItem, ...]
    secret_values_loaded: Literal[False] = False
    remote_probe_performed: Literal[False] = False
    workload_executed: Literal[False] = False


def load_compute_resource_catalog(path: str | Path) -> LoadedComputeResourceCatalog:
    source, payload = _load_yaml(path)
    catalog = ComputeResourceCatalog.model_validate(payload)
    return LoadedComputeResourceCatalog(
        path=source,
        file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        semantic_sha256=_semantic_sha256(catalog.model_dump(mode="json")),
        catalog=catalog,
    )


def inspect_compute_resource_catalog(
    path: str | Path,
    *,
    evidence_root: str | Path = ".",
) -> ComputeResourceCatalogInspection:
    loaded = load_compute_resource_catalog(path)
    root = Path(evidence_root).expanduser().resolve()
    issues: list[str] = []
    for resource in loaded.catalog.resources:
        if not isinstance(resource, GpuHostDefinition):
            continue
        evidence = _resolve_beneath(root, resource.baseline_inventory_ref)
        if not evidence.is_file() or evidence.is_symlink():
            issues.append(f"{resource.resource_id}:baseline_inventory_missing_or_unsafe")
            continue
        if evidence.stat().st_size > _MAX_INPUT_BYTES:
            issues.append(f"{resource.resource_id}:baseline_inventory_too_large")
            continue
        observed = hashlib.sha256(evidence.read_bytes()).hexdigest()
        if observed != resource.baseline_inventory_sha256:
            issues.append(f"{resource.resource_id}:baseline_inventory_hash_mismatch")
    return ComputeResourceCatalogInspection(
        catalog_id=loaded.catalog.catalog_id,
        file_sha256=loaded.file_sha256,
        semantic_sha256=loaded.semantic_sha256,
        resource_ids=tuple(item.resource_id for item in loaded.catalog.resources),
        gpu_host_ids=tuple(
            item.resource_id
            for item in loaded.catalog.resources
            if item.kind is ResourceKind.GPU_HOST
        ),
        api_model_ids=tuple(
            item.resource_id
            for item in loaded.catalog.resources
            if item.kind is ResourceKind.API_MODEL
        ),
        evidence_verified=not issues,
        evidence_issues=tuple(issues),
    )


def load_resource_observation(path: str | Path) -> ResourceObservation:
    _, payload = _load_yaml(path)
    return ResourceObservation.model_validate(payload)


class ComputeResourceRuntime:
    """Own ``outputs/resources`` independently of every project directory."""

    def __init__(self, outputs_root: str | Path) -> None:
        self.outputs_root = Path(outputs_root).expanduser().resolve()
        self.root = self.outputs_root / "resources"

    def initialize(
        self,
        catalog_path: str | Path,
        *,
        evidence_root: str | Path = ".",
    ) -> ResourceRegistrySnapshot:
        inspection = inspect_compute_resource_catalog(catalog_path, evidence_root=evidence_root)
        if not inspection.evidence_verified:
            raise ValueError(
                "compute resource catalog evidence is not verified: "
                + ", ".join(inspection.evidence_issues)
            )
        loaded = load_compute_resource_catalog(catalog_path)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
        with _locked(self.outputs_root / ".outputs.lock"):
            if self.root.is_symlink():
                raise ValueError("compute resource registry root must not be a symlink")
            if self.root.exists():
                snapshot = self.open(loaded)
                return snapshot
            temporary = Path(tempfile.mkdtemp(prefix=".resources-", dir=self.outputs_root))
            try:
                (temporary / "observations").mkdir()
                payload = {
                    "schema_version": "1.0",
                    "catalog_id": loaded.catalog.catalog_id,
                    "catalog_file_sha256": loaded.file_sha256,
                    "catalog_semantic_sha256": loaded.semantic_sha256,
                    "catalog_source": Path(catalog_path).as_posix(),
                }
                payload["registry_sha256"] = _semantic_sha256(payload)
                _atomic_json(temporary / "REGISTRY.json", payload)
                os.replace(temporary, self.root)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self.open(loaded)

    def open(
        self,
        catalog: LoadedComputeResourceCatalog | str | Path,
    ) -> ResourceRegistrySnapshot:
        loaded = (
            catalog
            if isinstance(catalog, LoadedComputeResourceCatalog)
            else load_compute_resource_catalog(catalog)
        )
        record = self.root / "REGISTRY.json"
        if not record.is_file() or record.is_symlink():
            raise FileNotFoundError(record)
        snapshot = ResourceRegistrySnapshot.model_validate_json(record.read_text(encoding="utf-8"))
        if snapshot.calculated_sha256() != snapshot.registry_sha256:
            raise ValueError("compute resource registry hash mismatch")
        if snapshot.catalog_id != loaded.catalog.catalog_id:
            raise ValueError("compute resource catalog identity drift")
        if snapshot.catalog_file_sha256 != loaded.file_sha256:
            raise ValueError("compute resource catalog file drift")
        if snapshot.catalog_semantic_sha256 != loaded.semantic_sha256:
            raise ValueError("compute resource catalog semantic drift")
        return snapshot

    def register_observation(
        self,
        catalog_path: str | Path,
        observation_path: str | Path,
    ) -> RegisteredResourceObservation:
        loaded = load_compute_resource_catalog(catalog_path)
        self.open(loaded)
        source, payload = _load_yaml(observation_path)
        observation = ResourceObservation.model_validate(payload)
        definition = loaded.catalog.resource(observation.resource_id)
        if definition.kind is not observation.resource_kind:
            raise ValueError("resource observation kind does not match its catalog definition")
        if isinstance(definition, ApiModelDefinition):
            if observation.requested_model_id not in {None, definition.model_id}:
                raise ValueError("API observation requested model does not match the catalog")
        source_bytes = source.read_bytes()
        record_payload = {
            "schema_version": "1.0",
            "observation": observation.model_dump(mode="json"),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_size_bytes": len(source_bytes),
        }
        record_payload["record_sha256"] = _semantic_sha256(record_payload)
        registered = RegisteredResourceObservation.model_validate(record_payload)
        target = self.root / "observations" / observation.resource_id / observation.observation_id
        with _locked(self.root / ".resources.lock"):
            if _lexists(target):
                existing = self._open_observation(target)
                if existing == registered:
                    return existing
                raise FileExistsError(target)
            parent = target.parent
            parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".observation-", dir=parent))
            try:
                _atomic_bytes(temporary / "OBSERVATION.yaml", source_bytes)
                _atomic_json(temporary / "RECORD.json", registered.model_dump(mode="json"))
                os.replace(temporary, target)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self._open_observation(target)

    def status(self, catalog_path: str | Path) -> ResourceRegistryStatus:
        loaded = load_compute_resource_catalog(catalog_path)
        snapshot = self.open(loaded)
        items: list[ResourceStatusItem] = []
        for definition in loaded.catalog.resources:
            observation_root = self.root / "observations" / definition.resource_id
            records: list[RegisteredResourceObservation] = []
            if observation_root.exists():
                if observation_root.is_symlink():
                    raise ValueError("resource observation directory must not be a symlink")
                for candidate in sorted(observation_root.iterdir()):
                    if candidate.is_dir() and not candidate.is_symlink():
                        records.append(self._open_observation(candidate))
            latest = (
                max(records, key=lambda item: item.observation.observed_at).observation
                if records
                else None
            )
            items.append(
                ResourceStatusItem(
                    resource_id=definition.resource_id,
                    kind=definition.kind,
                    definition=definition,
                    latest_observation=latest,
                    observation_count=len(records),
                )
            )
        return ResourceRegistryStatus(
            catalog_id=loaded.catalog.catalog_id,
            registry_sha256=snapshot.registry_sha256,
            catalog_semantic_sha256=loaded.semantic_sha256,
            resources=tuple(items),
        )

    def _open_observation(self, directory: Path) -> RegisteredResourceObservation:
        source = directory / "OBSERVATION.yaml"
        record = directory / "RECORD.json"
        if any(path.is_symlink() for path in (directory, source, record)):
            raise ValueError("registered resource observations must not contain symlinks")
        if not source.is_file() or not record.is_file():
            raise FileNotFoundError(directory)
        registered = RegisteredResourceObservation.model_validate_json(
            record.read_text(encoding="utf-8")
        )
        source_bytes = source.read_bytes()
        if len(source_bytes) != registered.source_size_bytes:
            raise ValueError("resource observation size mismatch")
        if hashlib.sha256(source_bytes).hexdigest() != registered.source_sha256:
            raise ValueError("resource observation source hash mismatch")
        if registered.calculated_sha256() != registered.record_sha256:
            raise ValueError("resource observation record hash mismatch")
        if load_resource_observation(source) != registered.observation:
            raise ValueError("resource observation semantic drift")
        return registered


def _load_yaml(path: str | Path) -> tuple[Path, object]:
    supplied = Path(path).expanduser()
    if supplied.is_symlink():
        raise ValueError("resource input must not be a symlink")
    source = supplied.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"resource input exceeds {_MAX_INPUT_BYTES} bytes")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("resource YAML must contain a mapping")
    return source, payload


def _validate_relative_locator(locator: str) -> None:
    if "\\" in locator or "//" in locator:
        raise ValueError("resource evidence locator must use normalized POSIX separators")
    path = PurePosixPath(locator)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("resource evidence locator must be a safe relative path")


def _resolve_beneath(root: Path, locator: str) -> Path:
    _validate_relative_locator(locator)
    candidate = root / locator
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("resource evidence locator escapes the evidence root") from exc
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("resource evidence locator must not traverse a symlink")
    return resolved


def _semantic_sha256(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, payload: object) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    _atomic_bytes(path, data)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

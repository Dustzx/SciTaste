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
    MODEL_CHECKPOINT = "model_checkpoint"


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
    availability: ObservationStatus = ObservationStatus.PENDING
    availability_reason: str = Field(default="Not checked in this catalog.", max_length=1_000)
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
    location: Literal["local", "remote"] = "remote"
    access_profile: str = Field(min_length=1, max_length=200)
    connection_alias: str | None = Field(default=None, min_length=1, max_length=200)
    device_count: int = Field(gt=0, le=64)
    device_name: str = Field(min_length=1, max_length=200)
    minimum_memory_mb_per_device: int = Field(gt=0)
    baseline_inventory_ref: str = Field(min_length=1, max_length=1_000)
    baseline_inventory_sha256: str = Field(pattern=_SHA256)
    baseline_observed_at: datetime
    availability: ObservationStatus = ObservationStatus.PENDING
    availability_reason: str = Field(default="Not checked in this catalog.", max_length=1_000)

    @model_validator(mode="after")
    def baseline_time_is_aware(self) -> GpuHostDefinition:
        if self.baseline_observed_at.tzinfo is None:
            raise ValueError("GPU baseline observation time must include a timezone")
        _validate_relative_locator(self.baseline_inventory_ref)
        if self.location == "local" and self.connection_alias is not None:
            raise ValueError("local GPU resources cannot declare a remote connection alias")
        return self


class ModelCheckpointDefinition(BaseModel):
    model_config = _CONFIG

    kind: Literal[ResourceKind.MODEL_CHECKPOINT] = ResourceKind.MODEL_CHECKPOINT
    resource_id: str = Field(pattern=_ID)
    model_id: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    local_path: str = Field(min_length=1, max_length=2_000)
    checkpoint_sha256: str = Field(pattern=_SHA256)
    checkpoint_bytes: int = Field(gt=0)
    format: str = Field(min_length=1, max_length=200)
    license_identifier: str = Field(min_length=1, max_length=200)
    compatible_gpu_resource_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence_ref: str = Field(min_length=1, max_length=1_000)
    evidence_sha256: str = Field(pattern=_SHA256)
    observed_at: datetime
    availability: ObservationStatus
    availability_reason: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def evidence_and_time_are_bounded(self) -> ModelCheckpointDefinition:
        if self.observed_at.tzinfo is None:
            raise ValueError("checkpoint observation time must include a timezone")
        _validate_relative_locator(self.evidence_ref)
        if len(set(self.compatible_gpu_resource_ids)) != len(self.compatible_gpu_resource_ids):
            raise ValueError("compatible GPU resource IDs must be unique")
        return self


ComputeResourceDefinition = Annotated[
    ApiModelDefinition | GpuHostDefinition | ModelCheckpointDefinition,
    Field(discriminator="kind"),
]


class ResourceDefinitionDocument(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    resource: ComputeResourceDefinition


class ResourceDefinitionRef(BaseModel):
    model_config = _CONFIG

    resource_id: str = Field(pattern=_ID)
    kind: ResourceKind
    locator: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> ResourceDefinitionRef:
        _validate_relative_locator(self.locator)
        return self


class ReferencedComputeResourceCatalog(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.1"] = "1.1"
    catalog_id: str = Field(pattern=_ID)
    resource_refs: tuple[ResourceDefinitionRef, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def references_are_unique(self) -> ReferencedComputeResourceCatalog:
        resource_ids = [item.resource_id for item in self.resource_refs]
        locators = [item.locator for item in self.resource_refs]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("compute resource reference IDs must be unique")
        if len(locators) != len(set(locators)):
            raise ValueError("compute resource reference locators must be unique")
        return self


class ComputeResourceCatalog(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    catalog_id: str = Field(pattern=_ID)
    resources: tuple[ComputeResourceDefinition, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def resource_ids_are_unique(self) -> ComputeResourceCatalog:
        resource_ids = [item.resource_id for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("compute resource IDs must be unique")
        gpu_ids = {
            item.resource_id for item in self.resources if item.kind is ResourceKind.GPU_HOST
        }
        for item in self.resources:
            if isinstance(item, ModelCheckpointDefinition):
                missing = set(item.compatible_gpu_resource_ids) - gpu_ids
                if missing:
                    raise ValueError(
                        "checkpoint references unknown GPU resources: " + ", ".join(sorted(missing))
                    )
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
    component_file_sha256: dict[str, str] = Field(default_factory=dict)
    catalog: ComputeResourceCatalog


class ComputeResourceCatalogInspection(BaseModel):
    model_config = _CONFIG

    catalog_id: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)
    resource_ids: tuple[str, ...]
    gpu_host_ids: tuple[str, ...]
    api_model_ids: tuple[str, ...]
    model_checkpoint_ids: tuple[str, ...]
    component_file_sha256: dict[str, str]
    evidence_verified: bool
    evidence_issues: tuple[str, ...]
    secret_values_loaded: Literal[False] = False
    external_action_performed: Literal[False] = False


class ProjectResourceBindingEntry(BaseModel):
    model_config = _CONFIG

    binding_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    expected_kind: ResourceKind
    role: str = Field(pattern=_ID)
    priority: int = Field(ge=1, le=100)
    status: ObservationStatus
    purpose: str = Field(min_length=1, max_length=1_000)
    required_for: tuple[str, ...] = Field(default=(), max_length=20)


class ProjectResourceBinding(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    binding_set_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    catalog_id: str = Field(pattern=_ID)
    catalog_semantic_sha256: str = Field(pattern=_SHA256)
    bindings: tuple[ProjectResourceBindingEntry, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def bindings_are_unique(self) -> ProjectResourceBinding:
        binding_ids = [item.binding_id for item in self.bindings]
        role_priorities = [(item.role, item.priority) for item in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("project resource binding IDs must be unique")
        if len(role_priorities) != len(set(role_priorities)):
            raise ValueError("project resource role priorities must be unique")
        return self


class ProjectResourceBindingInspection(BaseModel):
    model_config = _CONFIG

    binding_set_id: str
    project_id: str
    catalog_id: str
    binding_file_sha256: str = Field(pattern=_SHA256)
    binding_semantic_sha256: str = Field(pattern=_SHA256)
    resource_ids: tuple[str, ...]
    api_resource_ids: tuple[str, ...]
    gpu_resource_ids: tuple[str, ...]
    checkpoint_resource_ids: tuple[str, ...]
    valid: bool
    issues: tuple[str, ...]
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
    observed_checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
    observed_checkpoint_bytes: int | None = Field(default=None, gt=0)
    destination_present: bool | None = None
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
        checkpoint_values = (
            self.observed_checkpoint_sha256,
            self.observed_checkpoint_bytes,
            self.destination_present,
        )
        if self.resource_kind is ResourceKind.API_MODEL and any(
            value is not None for value in (*gpu_values, *checkpoint_values)
        ):
            raise ValueError("API observations cannot contain GPU host or checkpoint fields")
        if self.resource_kind is ResourceKind.GPU_HOST and any(
            value is not None for value in (*api_values, *checkpoint_values)
        ):
            raise ValueError("GPU observations cannot contain API model or checkpoint fields")
        if self.resource_kind is ResourceKind.MODEL_CHECKPOINT and any(
            value is not None for value in (*gpu_values, *api_values)
        ):
            raise ValueError("checkpoint observations cannot contain API model or GPU host fields")
        has_fact = any(
            value is not None
            for value in (*gpu_values, *api_values, *checkpoint_values, self.source_url)
        )
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
        _strip_empty_checkpoint_observation_fields(payload["observation"])
        return _semantic_sha256(payload)


class RegisteredProjectResourceBinding(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    binding: ProjectResourceBinding
    source_sha256: str = Field(pattern=_SHA256)
    source_size_bytes: int = Field(gt=0, le=_MAX_INPUT_BYTES)
    record_sha256: str = Field(pattern=_SHA256)

    def calculated_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"record_sha256"})
        return _semantic_sha256(payload)


class ResourceRegistrySnapshot(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    revision: int = Field(default=1, ge=1)
    predecessor_registry_sha256: str | None = Field(default=None, pattern=_SHA256)
    catalog_id: str
    catalog_file_sha256: str = Field(pattern=_SHA256)
    catalog_semantic_sha256: str = Field(pattern=_SHA256)
    catalog_source: str = Field(min_length=1, max_length=2_000)
    registry_sha256: str = Field(pattern=_SHA256)

    def calculated_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"registry_sha256"})
        if self.schema_version == "1.0":
            payload.pop("revision", None)
            payload.pop("predecessor_registry_sha256", None)
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
    project_binding_ids: tuple[str, ...] = ()
    secret_values_loaded: Literal[False] = False
    remote_probe_performed: Literal[False] = False
    workload_executed: Literal[False] = False


def load_compute_resource_catalog(path: str | Path) -> LoadedComputeResourceCatalog:
    source, payload = _load_yaml(path)
    component_hashes: dict[str, str] = {}
    if payload.get("schema_version") == "1.1":
        referenced = ReferencedComputeResourceCatalog.model_validate(payload)
        definitions: list[ComputeResourceDefinition] = []
        for reference in referenced.resource_refs:
            definition_path = _resolve_beneath(source.parent, reference.locator)
            definition_bytes = _read_bounded_regular_file(definition_path, "resource definition")
            observed_sha256 = hashlib.sha256(definition_bytes).hexdigest()
            if observed_sha256 != reference.sha256:
                raise ValueError(
                    f"compute resource definition hash mismatch: {reference.resource_id}"
                )
            definition_payload = yaml.safe_load(definition_bytes.decode("utf-8"))
            document = ResourceDefinitionDocument.model_validate(definition_payload)
            if document.resource.resource_id != reference.resource_id:
                raise ValueError("compute resource definition ID does not match its reference")
            if document.resource.kind is not reference.kind:
                raise ValueError("compute resource definition kind does not match its reference")
            definitions.append(document.resource)
            component_hashes[reference.locator] = observed_sha256
        catalog = ComputeResourceCatalog(
            schema_version="1.1",
            catalog_id=referenced.catalog_id,
            resources=tuple(definitions),
        )
    else:
        catalog = ComputeResourceCatalog.model_validate(payload)
    return LoadedComputeResourceCatalog(
        path=source,
        file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        semantic_sha256=_semantic_sha256(catalog.model_dump(mode="json")),
        component_file_sha256=component_hashes,
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
        if isinstance(resource, GpuHostDefinition):
            evidence_ref = resource.baseline_inventory_ref
            evidence_sha256 = resource.baseline_inventory_sha256
            issue_prefix = "baseline_inventory"
        elif isinstance(resource, ModelCheckpointDefinition):
            evidence_ref = resource.evidence_ref
            evidence_sha256 = resource.evidence_sha256
            issue_prefix = "checkpoint_evidence"
        else:
            continue
        evidence = _resolve_beneath(root, evidence_ref)
        if not evidence.is_file() or evidence.is_symlink():
            issues.append(f"{resource.resource_id}:{issue_prefix}_missing_or_unsafe")
            continue
        if evidence.stat().st_size > _MAX_INPUT_BYTES:
            issues.append(f"{resource.resource_id}:{issue_prefix}_too_large")
            continue
        observed = hashlib.sha256(evidence.read_bytes()).hexdigest()
        if observed != evidence_sha256:
            issues.append(f"{resource.resource_id}:{issue_prefix}_hash_mismatch")
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
        model_checkpoint_ids=tuple(
            item.resource_id
            for item in loaded.catalog.resources
            if item.kind is ResourceKind.MODEL_CHECKPOINT
        ),
        component_file_sha256=loaded.component_file_sha256,
        evidence_verified=not issues,
        evidence_issues=tuple(issues),
    )


def load_resource_observation(path: str | Path) -> ResourceObservation:
    _, payload = _load_yaml(path)
    return ResourceObservation.model_validate(payload)


def load_project_resource_binding(path: str | Path) -> ProjectResourceBinding:
    _, payload = _load_yaml(path)
    return ProjectResourceBinding.model_validate(payload)


def inspect_project_resource_binding(
    catalog_path: str | Path,
    binding_path: str | Path,
) -> ProjectResourceBindingInspection:
    catalog = load_compute_resource_catalog(catalog_path)
    source, payload = _load_yaml(binding_path)
    binding = ProjectResourceBinding.model_validate(payload)
    issues: list[str] = []
    if binding.catalog_id != catalog.catalog.catalog_id:
        issues.append("catalog_id_mismatch")
    if binding.catalog_semantic_sha256 != catalog.semantic_sha256:
        issues.append("catalog_semantic_sha256_mismatch")
    api_ids: list[str] = []
    gpu_ids: list[str] = []
    checkpoint_ids: list[str] = []
    for item in binding.bindings:
        try:
            definition = catalog.catalog.resource(item.resource_id)
        except ValueError:
            issues.append(f"{item.binding_id}:unknown_resource")
            continue
        if definition.kind is not item.expected_kind:
            issues.append(f"{item.binding_id}:resource_kind_mismatch")
        if definition.kind is ResourceKind.API_MODEL:
            api_ids.append(definition.resource_id)
        elif definition.kind is ResourceKind.GPU_HOST:
            gpu_ids.append(definition.resource_id)
        else:
            checkpoint_ids.append(definition.resource_id)
        if item.status is ObservationStatus.VERIFIED and definition.availability in {
            ObservationStatus.PENDING,
            ObservationStatus.BLOCKED,
        }:
            issues.append(f"{item.binding_id}:status_exceeds_resource_availability")
    semantic_sha256 = _semantic_sha256(binding.model_dump(mode="json"))
    return ProjectResourceBindingInspection(
        binding_set_id=binding.binding_set_id,
        project_id=binding.project_id,
        catalog_id=binding.catalog_id,
        binding_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        binding_semantic_sha256=semantic_sha256,
        resource_ids=tuple(item.resource_id for item in binding.bindings),
        api_resource_ids=tuple(api_ids),
        gpu_resource_ids=tuple(gpu_ids),
        checkpoint_resource_ids=tuple(checkpoint_ids),
        valid=not issues,
        issues=tuple(issues),
    )


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

    def update_catalog(
        self,
        catalog_path: str | Path,
        *,
        evidence_root: str | Path = ".",
    ) -> ResourceRegistrySnapshot:
        """Advance the global catalog while preserving observations and predecessor identity."""

        inspection = inspect_compute_resource_catalog(catalog_path, evidence_root=evidence_root)
        if not inspection.evidence_verified:
            raise ValueError(
                "compute resource catalog evidence is not verified: "
                + ", ".join(inspection.evidence_issues)
            )
        loaded = load_compute_resource_catalog(catalog_path)
        with _locked(self.root / ".resources.lock"):
            previous = self._load_registry_snapshot()
            if (
                previous.catalog_id == loaded.catalog.catalog_id
                and previous.catalog_file_sha256 == loaded.file_sha256
                and previous.catalog_semantic_sha256 == loaded.semantic_sha256
            ):
                return previous
            observation_root = self.root / "observations"
            if observation_root.exists():
                unknown = {
                    item.name
                    for item in observation_root.iterdir()
                    if item.is_dir() and not item.is_symlink()
                } - {item.resource_id for item in loaded.catalog.resources}
                if unknown:
                    raise ValueError(
                        "new compute catalog would orphan observations: "
                        + ", ".join(sorted(unknown))
                    )
            history = self.root / "catalog-history" / previous.registry_sha256
            if _lexists(history):
                if history.is_symlink() or not history.is_dir():
                    raise FileExistsError(history)
                archived_record = history / "REGISTRY.json"
                if not archived_record.is_file() or archived_record.is_symlink():
                    raise FileExistsError(history)
                archived = ResourceRegistrySnapshot.model_validate_json(
                    archived_record.read_text(encoding="utf-8")
                )
                if archived.calculated_sha256() != archived.registry_sha256:
                    raise ValueError("archived compute resource registry hash mismatch")
                if archived != previous:
                    raise ValueError("catalog-history entry does not match predecessor")
            else:
                history.mkdir(parents=True)
                _atomic_json(history / "REGISTRY.json", previous.model_dump(mode="json"))
            payload = {
                "schema_version": "1.1",
                "revision": previous.revision + 1,
                "predecessor_registry_sha256": previous.registry_sha256,
                "catalog_id": loaded.catalog.catalog_id,
                "catalog_file_sha256": loaded.file_sha256,
                "catalog_semantic_sha256": loaded.semantic_sha256,
                "catalog_source": Path(catalog_path).as_posix(),
            }
            payload["registry_sha256"] = _semantic_sha256(payload)
            _atomic_json(self.root / "REGISTRY.json", payload)
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
        snapshot = self._load_registry_snapshot()
        if snapshot.catalog_id != loaded.catalog.catalog_id:
            raise ValueError("compute resource catalog identity drift")
        if snapshot.catalog_file_sha256 != loaded.file_sha256:
            raise ValueError("compute resource catalog file drift")
        if snapshot.catalog_semantic_sha256 != loaded.semantic_sha256:
            raise ValueError("compute resource catalog semantic drift")
        return snapshot

    def register_project_binding(
        self,
        catalog_path: str | Path,
        binding_path: str | Path,
    ) -> RegisteredProjectResourceBinding:
        loaded = load_compute_resource_catalog(catalog_path)
        self.open(loaded)
        inspection = inspect_project_resource_binding(catalog_path, binding_path)
        if not inspection.valid:
            raise ValueError("project resource binding is invalid: " + ", ".join(inspection.issues))
        source, payload = _load_yaml(binding_path)
        binding = ProjectResourceBinding.model_validate(payload)
        project_manifest = self.outputs_root / "projects" / binding.project_id / "PROJECT.json"
        if not project_manifest.is_file() or project_manifest.is_symlink():
            raise ValueError("project resource binding requires an existing project")
        source_bytes = source.read_bytes()
        record_payload = {
            "schema_version": "1.0",
            "binding": binding.model_dump(mode="json"),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_size_bytes": len(source_bytes),
        }
        record_payload["record_sha256"] = _semantic_sha256(record_payload)
        registered = RegisteredProjectResourceBinding.model_validate(record_payload)
        target = self.root / "projects" / binding.project_id
        with _locked(self.root / ".resources.lock"):
            if _lexists(target):
                existing = self._open_project_binding(target)
                if existing == registered:
                    return existing
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".project-binding-", dir=target.parent))
            try:
                _atomic_bytes(temporary / "RESOURCE_BINDING.yaml", source_bytes)
                _atomic_json(temporary / "RECORD.json", registered.model_dump(mode="json"))
                os.replace(temporary, target)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self._open_project_binding(target)

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
        observation_payload = observation.model_dump(mode="json")
        _strip_empty_checkpoint_observation_fields(observation_payload)
        record_payload = {
            "schema_version": "1.0",
            "observation": observation_payload,
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
        project_root = self.root / "projects"
        project_ids = ()
        if project_root.exists():
            if project_root.is_symlink():
                raise ValueError("resource project-binding directory must not be a symlink")
            project_ids = tuple(
                item.name
                for item in sorted(project_root.iterdir())
                if item.is_dir() and not item.is_symlink()
            )
            for project_id in project_ids:
                registered = self._open_project_binding(project_root / project_id)
                if registered.binding.catalog_semantic_sha256 != loaded.semantic_sha256:
                    raise ValueError("registered project resource binding has catalog drift")
        return ResourceRegistryStatus(
            catalog_id=loaded.catalog.catalog_id,
            registry_sha256=snapshot.registry_sha256,
            catalog_semantic_sha256=loaded.semantic_sha256,
            resources=tuple(items),
            project_binding_ids=project_ids,
        )

    def _load_registry_snapshot(self) -> ResourceRegistrySnapshot:
        record = self.root / "REGISTRY.json"
        if not record.is_file() or record.is_symlink():
            raise FileNotFoundError(record)
        snapshot = ResourceRegistrySnapshot.model_validate_json(record.read_text(encoding="utf-8"))
        if snapshot.calculated_sha256() != snapshot.registry_sha256:
            raise ValueError("compute resource registry hash mismatch")
        return snapshot

    def _open_project_binding(self, directory: Path) -> RegisteredProjectResourceBinding:
        source = directory / "RESOURCE_BINDING.yaml"
        record = directory / "RECORD.json"
        if any(path.is_symlink() for path in (directory, source, record)):
            raise ValueError("registered project resource bindings must not contain symlinks")
        if not source.is_file() or not record.is_file():
            raise FileNotFoundError(directory)
        registered = RegisteredProjectResourceBinding.model_validate_json(
            record.read_text(encoding="utf-8")
        )
        source_bytes = source.read_bytes()
        if len(source_bytes) != registered.source_size_bytes:
            raise ValueError("project resource binding size mismatch")
        if hashlib.sha256(source_bytes).hexdigest() != registered.source_sha256:
            raise ValueError("project resource binding source hash mismatch")
        if registered.calculated_sha256() != registered.record_sha256:
            raise ValueError("project resource binding record hash mismatch")
        if load_project_resource_binding(source) != registered.binding:
            raise ValueError("project resource binding semantic drift")
        return registered

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


def _read_bounded_regular_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds {_MAX_INPUT_BYTES} bytes")
    return path.read_bytes()


def _strip_empty_checkpoint_observation_fields(payload: dict[str, object]) -> None:
    """Keep v1.0 observation hashes stable after checkpoint fields were added."""

    for field in (
        "observed_checkpoint_sha256",
        "observed_checkpoint_bytes",
        "destination_present",
    ):
        if payload.get(field) is None:
            payload.pop(field, None)


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

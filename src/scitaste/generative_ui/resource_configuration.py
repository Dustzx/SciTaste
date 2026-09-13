"""Apply one published resource plan as a project-owned binding revision."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.generative_ui.planning_directive import (
    PlanningDirectivePublication,
    load_latest_planning_directive,
)
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.resources.registry import (
    ComputeResourceCatalog,
    ComputeResourceRuntime,
    ProjectResourceBinding,
    ProjectResourceBindingEntry,
    RegisteredProjectResourceBinding,
    ResourceRegistrySnapshot,
    ResourceSelectionStatus,
    load_compute_resource_catalog,
)

RESOURCE_CONFIGURATION_PROJECTION = "project-resource-configuration-v1"
RESOURCE_CONFIGURATION_STAGE_PATH = "resource_configuration"
_MAX_PUBLICATION_BYTES = 2 * 1024 * 1024
_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)


class ProjectResourceConfigurationRequest(BaseModel):
    """Explicit user confirmation to apply one exact published resource directive."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    publication_id: SafeIdentifier
    publication_sha256: Sha256
    expected_project_revision: int = Field(ge=0)
    expected_snapshot_sha256: Sha256
    expected_binding_record_sha256: Sha256
    expected_registry_sha256: Sha256
    confirm_apply: Literal[True]

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))


class ProjectResourceConfigurationPriority(BaseModel):
    model_config = _MODEL_CONFIG

    binding_id: SafeIdentifier
    resource_id: SafeIdentifier
    role: SafeIdentifier
    priority: int = Field(ge=1, le=100)


class ProjectResourceConfigurationPublication(BaseModel):
    """Immutable receipt for a local binding update; it cannot launch a workload."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    configuration_id: SafeIdentifier
    project_id: ProjectIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    applied_at: datetime
    request_fingerprint: Sha256
    source_publication_id: SafeIdentifier
    source_publication_sha256: Sha256
    source_proposal_id: SafeIdentifier
    source_binding_set_id: SafeIdentifier
    source_binding_record_sha256: Sha256
    configured_binding_set_id: SafeIdentifier
    configured_binding_record_sha256: Sha256
    registry_sha256: Sha256
    requested_resource_roles: tuple[SafeIdentifier, ...] = ()
    requested_resource_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    priorities: tuple[ProjectResourceConfigurationPriority, ...] = Field(min_length=1)
    registry_catalog_unchanged: Literal[True] = True
    credential_bindings_unchanged: Literal[True] = True
    remote_probe_performed: Literal[False] = False
    workload_executed: Literal[False] = False
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    verification_route: Literal[VerificationRoute.DIRECT_PATH] = VerificationRoute.DIRECT_PATH
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    configuration_sha256: Sha256

    @model_validator(mode="after")
    def configuration_is_closed(self) -> ProjectResourceConfigurationPublication:
        if self.applied_at.tzinfo is None:
            raise ValueError("resource configuration time must include a timezone")
        if len(self.requested_resource_ids) != len(set(self.requested_resource_ids)):
            raise ValueError("requested resource IDs must be unique")
        if len(self.requested_resource_roles) != len(set(self.requested_resource_roles)):
            raise ValueError("requested resource roles must be unique")
        if len({item.binding_id for item in self.priorities}) != len(self.priorities):
            raise ValueError("configured resource binding IDs must be unique")
        expected = _fingerprint(self.model_dump(mode="json", exclude={"configuration_sha256"}))
        if self.configuration_sha256 != expected:
            raise ValueError("project resource configuration hash mismatch")
        return self


def apply_project_resource_configuration(
    runtime: ProjectRuntime,
    request: ProjectResourceConfigurationRequest | dict[str, object],
) -> tuple[ProjectSnapshot, ProjectResourceConfigurationPublication]:
    """Apply only resource changes named by an accepted, published model plan."""

    parsed = (
        request
        if isinstance(request, ProjectResourceConfigurationRequest)
        else ProjectResourceConfigurationRequest.model_validate(request)
    )
    snapshot = runtime.open(parsed.project_id)
    run_id = _run_id(parsed.publication_sha256)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if existing is not None:
        if existing.status != "complete-project-resource-configuration":
            raise ValueError("project resource configuration run is incomplete")
        publication = inspect_project_resource_configuration(runtime, parsed.project_id, run_id)
        if publication.request_fingerprint != parsed.fingerprint:
            raise ValueError("project resource configuration request differs from existing run")
        return snapshot, publication

    directive = load_latest_planning_directive(runtime, parsed.project_id)
    if (
        directive is None
        or directive.publication_id != parsed.publication_id
        or directive.publication_sha256 != parsed.publication_sha256
        or directive.draft.change_kind != "request_resource_revision"
    ):
        raise ValueError("resource configuration requires the latest published resource directive")
    if (
        snapshot.revision != parsed.expected_project_revision
        or snapshot.snapshot_sha256 != parsed.expected_snapshot_sha256
    ):
        raise ValueError("project resource configuration request is stale")

    resource_runtime, registry, current = _resource_context(runtime, parsed.project_id)
    if (
        current.record_sha256 != parsed.expected_binding_record_sha256
        or registry.registry_sha256 != parsed.expected_registry_sha256
    ):
        raise ValueError("project resource configuration binding is stale")
    loaded_catalog = load_compute_resource_catalog(_catalog_path(runtime, registry))
    configured_binding = compile_project_resource_binding(
        current.binding,
        directive,
        catalog=loaded_catalog.catalog,
        selection_status_by_id=loaded_catalog.selection_status_by_id,
    )
    verification = decide_verification_route(
        VerificationDecisionInput(
            action_id="apply-project-resource-configuration",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.FILESYSTEM_WRITE,),
            evidence_state="current",
            semantic_uncertainty="low",
            failure_probability=0.02,
            failure_impact_units=10.0,
            targeted_check_cost_units=0.5,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=2.0,
            full_preflight_detection_probability=0.95,
        )
    )
    if verification.route is not VerificationRoute.DIRECT_PATH:
        raise ValueError("local resource configuration unexpectedly requires verification")

    artifact = f"runs/{run_id}/{RESOURCE_CONFIGURATION_STAGE_PATH}/PUBLICATION.json"
    prepared = runtime.begin_run(
        parsed.project_id,
        ProjectRun(
            run_id=run_id,
            provider="scitaste-native",
            model="deterministic-resource-binding-compiler",
            condition="generation-as-content-resource-configuration",
            seed=0,
            status="preparing-project-resource-configuration",
            evidence_scope="project-resource-membership-and-priorities-no-probe-no-workload",
            stage_path=RESOURCE_CONFIGURATION_STAGE_PATH,
            artifact=artifact,
            generative_ui_projection=RESOURCE_CONFIGURATION_PROJECTION,
            source_planning_publication_id=directive.publication_id,
            source_planning_publication_sha256=directive.publication_sha256,
            source_binding_record_sha256=current.record_sha256,
            authorizes_external_action=False,
            authorizes_execution=False,
            no_execution_performed=True,
        ),
        expected_revision=snapshot.revision,
    )
    try:
        configured = _register_compiled_binding(resource_runtime, registry, configured_binding)
    except Exception:
        runtime.update_run(
            parsed.project_id,
            run_id,
            expected_revision=prepared.revision,
            status="failed-project-resource-configuration",
        )
        raise

    publication = _configuration_publication(
        parsed,
        run_id=run_id,
        directive=directive,
        current=current,
        configured=configured,
        registry=registry,
        verification_reason_codes=verification.reason_codes,
    )
    publication_path = runtime.projects_root / parsed.project_id / artifact
    _atomic_json(
        publication_path,
        publication.model_dump(mode="json", exclude_computed_fields=True),
    )
    completed = runtime.update_run(
        parsed.project_id,
        run_id,
        expected_revision=prepared.revision,
        status="complete-project-resource-configuration",
        configured_binding_set_id=configured.binding.binding_set_id,
        configured_binding_record_sha256=configured.record_sha256,
        resource_configuration_sha256=publication.configuration_sha256,
        verification_route=verification.route.value,
        verification_reason_codes=list(verification.reason_codes),
        credential_bindings_unchanged=True,
        remote_probe_performed=False,
        workload_executed=False,
    )
    return completed, publication


def compile_project_resource_binding(
    current: ProjectResourceBinding,
    directive: PlanningDirectivePublication,
    *,
    catalog: ComputeResourceCatalog | None = None,
    selection_status_by_id: Mapping[str, ResourceSelectionStatus] | None = None,
) -> ProjectResourceBinding:
    """Compile catalog attachment and priority changes without accessing a resource."""

    draft = directive.draft
    if draft.change_kind != "request_resource_revision" or not draft.requested_resource_ids:
        raise ValueError("planning directive does not contain a resource revision")
    by_resource = {item.resource_id: item for item in current.bindings}
    unattached_resource_ids = set(draft.requested_resource_ids) - set(by_resource)
    if unattached_resource_ids and catalog is None:
        raise ValueError("resource attachment compilation requires the bound catalog")
    if unattached_resource_ids and selection_status_by_id is None:
        raise ValueError("resource attachment compilation requires catalog lifecycle state")
    bindings = list(current.bindings)
    existing_binding_ids = {item.binding_id for item in bindings}
    for resource_id in sorted(unattached_resource_ids):
        assert catalog is not None
        assert selection_status_by_id is not None
        if selection_status_by_id.get(resource_id) is not ResourceSelectionStatus.CURRENT:
            raise ValueError("historical or disabled catalog resources cannot be newly attached")
        definition = catalog.resource(resource_id)
        compatible_roles = {
            item.role for item in bindings if item.expected_kind is definition.kind
        }.intersection(draft.requested_resource_roles)
        if len(compatible_roles) != 1:
            raise ValueError("resource attachment requires exactly one compatible project role")
        role = compatible_roles.pop()
        binding_id = f"ui-{role}-{resource_id}"
        if binding_id in existing_binding_ids:
            raise ValueError("resource attachment binding identity already exists")
        priorities = [item.priority for item in bindings if item.role == role]
        bindings.append(
            ProjectResourceBindingEntry(
                binding_id=binding_id,
                resource_id=resource_id,
                expected_kind=definition.kind,
                role=role,
                priority=max(priorities, default=0) + 1,
                status=definition.availability,
                purpose=draft.summary,
                required_for=(draft.target_stage_id,),
            )
        )
        existing_binding_ids.add(binding_id)

    by_resource = {item.resource_id: item for item in bindings}
    unknown = set(draft.requested_resource_ids) - set(by_resource)
    if unknown:
        raise ValueError("planning directive names resources outside the project binding")
    selected_roles = {by_resource[item].role for item in draft.requested_resource_ids}
    requested_roles = set(draft.requested_resource_roles) or selected_roles
    if selected_roles - requested_roles:
        raise ValueError("requested resources do not belong to the requested project roles")
    if requested_roles - {item.role for item in bindings}:
        raise ValueError("planning directive names unknown project resource roles")
    uncovered = requested_roles - selected_roles
    if uncovered:
        raise ValueError("every requested resource role requires one selected resource")

    requested_order = {value: index for index, value in enumerate(draft.requested_resource_ids)}
    configured: list[ProjectResourceBindingEntry] = []
    for role in dict.fromkeys(item.role for item in bindings):
        rows = [item for item in bindings if item.role == role]
        if role in requested_roles:
            rows.sort(
                key=lambda item: (
                    item.resource_id not in requested_order,
                    requested_order.get(item.resource_id, item.priority),
                    item.priority,
                    item.binding_id,
                )
            )
            rows = [
                item.model_copy(update={"priority": index}) for index, item in enumerate(rows, 1)
            ]
        configured.extend(rows)
    return ProjectResourceBinding(
        schema_version="1.0",
        binding_set_id=f"resource-plan-{directive.publication_sha256[:16]}",
        project_id=current.project_id,
        catalog_id=current.catalog_id,
        catalog_semantic_sha256=current.catalog_semantic_sha256,
        bindings=tuple(configured),
    )


def inspect_project_resource_configuration(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectResourceConfigurationPublication:
    """Validate one configuration receipt and its live or archived binding record."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    expected_artifact = f"runs/{run_id}/{RESOURCE_CONFIGURATION_STAGE_PATH}/PUBLICATION.json"
    if (
        run is None
        or run.status != "complete-project-resource-configuration"
        or run.stage_path != RESOURCE_CONFIGURATION_STAGE_PATH
        or run.artifact != expected_artifact
        or getattr(run, "generative_ui_projection", None) != RESOURCE_CONFIGURATION_PROJECTION
    ):
        raise ValueError("unknown complete project resource configuration")
    path = runtime.projects_root / project_id / expected_artifact
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_PUBLICATION_BYTES:
        raise ValueError("project resource configuration artifact is unavailable")
    publication = ProjectResourceConfigurationPublication.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if (
        publication.project_id != project_id
        or publication.run_id != run_id
        or getattr(run, "resource_configuration_sha256", None) != publication.configuration_sha256
    ):
        raise ValueError("project resource configuration differs from its run")
    _, _, current = _resource_context(runtime, project_id)
    if current.record_sha256 != publication.configured_binding_record_sha256:
        history = (
            runtime.outputs_root
            / "resources/project-binding-history"
            / project_id
            / publication.configured_binding_record_sha256
        )
        archived = _load_registered_binding(history)
        if archived.record_sha256 != publication.configured_binding_record_sha256:
            raise ValueError("configured project resource binding is not retained")
    return publication


def load_latest_project_resource_configuration(
    runtime: ProjectRuntime,
    project_id: str,
) -> ProjectResourceConfigurationPublication | None:
    snapshot = runtime.open(project_id)
    run = next(
        (
            item
            for item in reversed(snapshot.manifest.runs)
            if getattr(item, "generative_ui_projection", None) == RESOURCE_CONFIGURATION_PROJECTION
            and item.status == "complete-project-resource-configuration"
        ),
        None,
    )
    return (
        inspect_project_resource_configuration(runtime, project_id, run.run_id)
        if run is not None
        else None
    )


def _resource_context(
    runtime: ProjectRuntime,
    project_id: str,
) -> tuple[ComputeResourceRuntime, ResourceRegistrySnapshot, RegisteredProjectResourceBinding]:
    resource_runtime = ComputeResourceRuntime(runtime.outputs_root)
    registry_path = runtime.outputs_root / "resources/REGISTRY.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise ValueError("project has no shared resource registry")
    registry = ResourceRegistrySnapshot.model_validate_json(
        registry_path.read_text(encoding="utf-8")
    )
    if registry.calculated_sha256() != registry.registry_sha256:
        raise ValueError("project resource registry hash mismatch")
    catalog_path = _catalog_path(runtime, registry)
    resource_runtime.open(catalog_path)
    current = _load_registered_binding(runtime.outputs_root / "resources/projects" / project_id)
    return resource_runtime, registry, current


def _catalog_path(runtime: ProjectRuntime, registry: ResourceRegistrySnapshot) -> Path:
    repository_root = runtime.outputs_root.parent.resolve()
    source = Path(registry.catalog_source).expanduser()
    path = (source if source.is_absolute() else repository_root / source).resolve()
    if not path.is_relative_to(repository_root):
        raise ValueError("project resource catalog escapes the repository")
    return path


def _load_registered_binding(directory: Path) -> RegisteredProjectResourceBinding:
    source = directory / "RESOURCE_BINDING.yaml"
    record = directory / "RECORD.json"
    if any(item.is_symlink() for item in (directory, source, record)):
        raise ValueError("project resource binding files must not be symlinks")
    if not source.is_file() or not record.is_file():
        raise FileNotFoundError(directory)
    registered = RegisteredProjectResourceBinding.model_validate_json(
        record.read_text(encoding="utf-8")
    )
    source_bytes = source.read_bytes()
    if (
        len(source_bytes) != registered.source_size_bytes
        or hashlib.sha256(source_bytes).hexdigest() != registered.source_sha256
        or registered.calculated_sha256() != registered.record_sha256
        or ProjectResourceBinding.model_validate(yaml.safe_load(source_bytes)) != registered.binding
    ):
        raise ValueError("project resource binding integrity check failed")
    return registered


def _register_compiled_binding(
    resource_runtime: ComputeResourceRuntime,
    registry: ResourceRegistrySnapshot,
    binding: ProjectResourceBinding,
) -> RegisteredProjectResourceBinding:
    catalog_path = _catalog_path_from_runtime(resource_runtime, registry)
    temporary = Path(
        tempfile.mkdtemp(prefix=".ui-resource-configuration-", dir=resource_runtime.root)
    )
    try:
        source = temporary / "RESOURCE_BINDING.yaml"
        source.write_text(
            yaml.safe_dump(
                binding.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return resource_runtime.update_project_binding(catalog_path, source)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _catalog_path_from_runtime(
    resource_runtime: ComputeResourceRuntime,
    registry: ResourceRegistrySnapshot,
) -> Path:
    repository_root = resource_runtime.outputs_root.parent.resolve()
    source = Path(registry.catalog_source).expanduser()
    path = (source if source.is_absolute() else repository_root / source).resolve()
    if not path.is_relative_to(repository_root):
        raise ValueError("project resource catalog escapes the repository")
    return path


def _configuration_publication(
    request: ProjectResourceConfigurationRequest,
    *,
    run_id: str,
    directive: PlanningDirectivePublication,
    current: RegisteredProjectResourceBinding,
    configured: RegisteredProjectResourceBinding,
    registry: ResourceRegistrySnapshot,
    verification_reason_codes: tuple[str, ...],
) -> ProjectResourceConfigurationPublication:
    values = {
        "schema_version": "1.0",
        "configuration_id": f"resource-configuration-{directive.publication_sha256[:20]}",
        "project_id": request.project_id,
        "run_id": run_id,
        "applied_at": datetime.now(UTC),
        "request_fingerprint": request.fingerprint,
        "source_publication_id": directive.publication_id,
        "source_publication_sha256": directive.publication_sha256,
        "source_proposal_id": directive.proposal_id,
        "source_binding_set_id": current.binding.binding_set_id,
        "source_binding_record_sha256": current.record_sha256,
        "configured_binding_set_id": configured.binding.binding_set_id,
        "configured_binding_record_sha256": configured.record_sha256,
        "registry_sha256": registry.registry_sha256,
        "requested_resource_roles": directive.draft.requested_resource_roles,
        "requested_resource_ids": directive.draft.requested_resource_ids,
        "priorities": tuple(
            ProjectResourceConfigurationPriority(
                binding_id=item.binding_id,
                resource_id=item.resource_id,
                role=item.role,
                priority=item.priority,
            )
            for item in configured.binding.bindings
        ),
        "registry_catalog_unchanged": True,
        "credential_bindings_unchanged": True,
        "remote_probe_performed": False,
        "workload_executed": False,
        "authorizes_external_action": False,
        "authorizes_execution": False,
        "verification_route": VerificationRoute.DIRECT_PATH,
        "verification_reason_codes": verification_reason_codes,
    }
    prototype = ProjectResourceConfigurationPublication.model_construct(
        **values,
        configuration_sha256="0" * 64,
    )
    return ProjectResourceConfigurationPublication(
        **values,
        configuration_sha256=_fingerprint(
            prototype.model_dump(mode="json", exclude={"configuration_sha256"})
        ),
    )


def _run_id(publication_sha256: str) -> str:
    return f"resource-config-{publication_sha256[:20]}"


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: item.isoformat(),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "RESOURCE_CONFIGURATION_PROJECTION",
    "RESOURCE_CONFIGURATION_STAGE_PATH",
    "ProjectResourceConfigurationPriority",
    "ProjectResourceConfigurationPublication",
    "ProjectResourceConfigurationRequest",
    "apply_project_resource_configuration",
    "compile_project_resource_binding",
    "inspect_project_resource_configuration",
    "load_latest_project_resource_configuration",
]

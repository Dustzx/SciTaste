"""Secret-free project projection of the shared API, GPU, and checkpoint registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scitaste.generative_ui.models import ProjectResourcePortfolioData
from scitaste.project import ProjectRuntime
from scitaste.resources.registry import (
    ComputeResourceRuntime,
    CredentialBindingSource,
    RegisteredProjectResourceBinding,
    ResourceAccessBindingItem,
    ResourceRegistrySnapshot,
    inspect_resource_access,
    load_compute_resource_catalog,
)


def load_project_resource_portfolio(
    runtime: ProjectRuntime,
    project_id: str,
) -> ProjectResourcePortfolioData | None:
    """Load an integrity-checked project binding without probing or exposing credentials."""

    runtime.open(project_id)
    registry_root = runtime.outputs_root / "resources"
    registry_file = registry_root / "REGISTRY.json"
    binding_file = registry_root / "projects" / project_id / "RECORD.json"
    if not registry_file.is_file() or not binding_file.is_file():
        return None
    if registry_file.is_symlink() or binding_file.is_symlink():
        raise ValueError("project resource portfolio records must not be symlinks")
    registry = ResourceRegistrySnapshot.model_validate_json(
        registry_file.read_text(encoding="utf-8")
    )
    if registry.calculated_sha256() != registry.registry_sha256:
        raise ValueError("project resource portfolio registry hash mismatch")
    repository_root = runtime.outputs_root.parent.resolve()
    catalog_path = Path(registry.catalog_source).expanduser()
    if not catalog_path.is_absolute():
        catalog_path = repository_root / catalog_path
    catalog_path = catalog_path.resolve()
    try:
        catalog_path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("project resource catalog escapes the repository") from exc

    loaded_catalog = load_compute_resource_catalog(catalog_path)
    status = ComputeResourceRuntime(runtime.outputs_root).status(catalog_path)
    registered = RegisteredProjectResourceBinding.model_validate_json(
        binding_file.read_text(encoding="utf-8")
    )
    if registered.calculated_sha256() != registered.record_sha256:
        raise ValueError("project resource portfolio binding hash mismatch")
    if registered.binding.project_id != project_id:
        raise ValueError("project resource portfolio belongs to another project")
    credential_file = registry_root / "access" / "credentials.env"
    access = inspect_resource_access(
        catalog_path,
        credential_file=credential_file if credential_file.is_file() else None,
    )
    status_by_id = {item.resource_id: item for item in status.resources}
    access_by_id = {item.resource_id: item for item in access.resources}
    resources = []
    roles_by_kind: dict[str, list[str]] = {}
    for binding in registered.binding.bindings:
        resource_status = status_by_id[binding.resource_id]
        resource_access = access_by_id[binding.resource_id]
        access_state = _access_state(resource_access)
        roles_by_kind.setdefault(binding.expected_kind.value, [])
        if binding.role not in roles_by_kind[binding.expected_kind.value]:
            roles_by_kind[binding.expected_kind.value].append(binding.role)
        resources.append(
            {
                "binding_id": binding.binding_id,
                "resource_id": binding.resource_id,
                "kind": binding.expected_kind.value,
                "role": binding.role,
                "priority": binding.priority,
                "binding_status": binding.status.value,
                "observed_status": (
                    resource_status.latest_observation.status.value
                    if resource_status.latest_observation is not None
                    else "unobserved"
                ),
                "access_state": access_state,
                "connection_metadata_complete": resource_access.connection_metadata_complete,
                "local_path_present": resource_access.local_path_present,
                "required_for": binding.required_for,
            }
        )
    planner_binding = next(
        iter(
            sorted(
                (
                    item
                    for item in registered.binding.bindings
                    if item.expected_kind.value == "api_model"
                    and "generation-as-content-planner" in item.required_for
                ),
                key=lambda item: (item.priority, item.binding_id),
            )
        ),
        None,
    )
    planner_definition = (
        loaded_catalog.catalog.resource(planner_binding.resource_id)
        if planner_binding is not None
        else None
    )
    planner_access = (
        access_by_id[planner_binding.resource_id] if planner_binding is not None else None
    )
    planner_state = "unmanaged"
    if (
        planner_binding is not None
        and planner_definition is not None
        and planner_access is not None
    ):
        planner_state = (
            "ready"
            if planner_binding.status.value == "verified"
            and planner_definition.availability.value == "verified"
            and _access_state(planner_access) == "configured"
            else "unavailable"
        )
    bound_resource_ids = {item.resource_id for item in registered.binding.bindings}
    available_resources = []
    for item in status.resources:
        if item.resource_id in bound_resource_ids:
            continue
        compatible_roles = tuple(roles_by_kind.get(item.kind.value, ()))
        if not compatible_roles:
            continue
        resource_access = access_by_id[item.resource_id]
        available_resources.append(
            {
                "resource_id": item.resource_id,
                "kind": item.kind.value,
                "selection_status": loaded_catalog.selection_status_by_id[item.resource_id].value,
                "attachable": (
                    loaded_catalog.selection_status_by_id[item.resource_id].value == "current"
                ),
                "observed_status": (
                    item.latest_observation.status.value
                    if item.latest_observation is not None
                    else "unobserved"
                ),
                "access_state": _access_state(resource_access),
                "compatible_roles": compatible_roles,
                "connection_metadata_complete": resource_access.connection_metadata_complete,
                "local_path_present": resource_access.local_path_present,
            }
        )
    statuses = [item.status.value for item in registered.binding.bindings]
    from scitaste.generative_ui.resource_configuration import (
        load_latest_project_resource_configuration,
    )

    configuration = load_latest_project_resource_configuration(runtime, project_id)
    if (
        configuration is not None
        and configuration.configured_binding_record_sha256 != registered.record_sha256
    ):
        configuration = None
    return ProjectResourcePortfolioData(
        project_id=project_id,
        binding_set_id=registered.binding.binding_set_id,
        binding_record_sha256=registered.record_sha256,
        registry_revision=registry.revision,
        registry_sha256=registry.registry_sha256,
        catalog_id=registry.catalog_id,
        catalog_semantic_sha256=registry.catalog_semantic_sha256,
        resource_count=len(resources),
        verified_binding_count=statuses.count("verified"),
        pending_binding_count=statuses.count("pending"),
        blocked_binding_count=statuses.count("blocked"),
        resources=resources,
        available_resource_count=len(available_resources),
        available_resources=available_resources,
        planner_binding_state=planner_state,
        planner_resource_id=(planner_binding.resource_id if planner_binding is not None else None),
        planner_provider_id=(
            planner_definition.provider_id if planner_definition is not None else None
        ),
        planner_model_id=(planner_definition.model_id if planner_definition is not None else None),
        configuration_authority="user_applied" if configuration is not None else "proposal_only",
        configuration_run_id=configuration.run_id if configuration is not None else None,
        source_planning_publication_id=(
            configuration.source_publication_id if configuration is not None else None
        ),
        source_planning_publication_sha256=(
            configuration.source_publication_sha256 if configuration is not None else None
        ),
        predecessor_binding_record_sha256=(
            configuration.source_binding_record_sha256 if configuration is not None else None
        ),
        configuration_verification_route=(
            configuration.verification_route.value if configuration is not None else None
        ),
    )


@dataclass(frozen=True)
class ProjectPlannerAdmission:
    """Decision made from existing local bindings; it performs no resource probe."""

    admitted: bool
    managed: bool
    reason_code: str
    resource_id: str | None = None


def inspect_project_planner_admission(
    runtime: ProjectRuntime,
    project_id: str,
    *,
    planner_implementation: str,
    planner_backend: str | None,
    planner_model: str | None,
) -> ProjectPlannerAdmission:
    """Admit a live planner only when its exact project resource is ready."""

    if planner_implementation == "deterministic-v1":
        return ProjectPlannerAdmission(
            admitted=True,
            managed=False,
            reason_code="deterministic-planner-needs-no-resource",
        )
    portfolio = load_project_resource_portfolio(runtime, project_id)
    if portfolio is None or portfolio.planner_binding_state == "unmanaged":
        # Projects created before the resource registry remain compatible. Once
        # a planner binding exists, however, it becomes authoritative.
        return ProjectPlannerAdmission(
            admitted=True,
            managed=False,
            reason_code="project-planner-resource-unmanaged",
        )
    identity_matches = (
        planner_backend is not None
        and planner_model is not None
        and portfolio.planner_provider_id is not None
        and portfolio.planner_model_id == planner_model
        and (
            planner_backend == portfolio.planner_provider_id
            or planner_backend.startswith(f"{portfolio.planner_provider_id}-")
        )
    )
    admitted = portfolio.planner_binding_state == "ready" and identity_matches
    return ProjectPlannerAdmission(
        admitted=admitted,
        managed=True,
        reason_code=(
            "project-planner-resource-admitted"
            if admitted
            else "project-planner-resource-not-admitted"
        ),
        resource_id=portfolio.planner_resource_id,
    )


def _access_state(resource_access: ResourceAccessBindingItem) -> str:
    if resource_access.credential_source is CredentialBindingSource.NOT_REQUIRED:
        return "not_required"
    return "configured" if resource_access.credential_present else "missing"


__all__ = [
    "ProjectPlannerAdmission",
    "inspect_project_planner_admission",
    "load_project_resource_portfolio",
]

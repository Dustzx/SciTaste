"""Secret-free project projection of the shared API, GPU, and checkpoint registry."""

from __future__ import annotations

from pathlib import Path

from scitaste.generative_ui.models import ProjectResourcePortfolioData
from scitaste.project import ProjectRuntime
from scitaste.resources.registry import (
    ComputeResourceRuntime,
    CredentialBindingSource,
    RegisteredProjectResourceBinding,
    ResourceRegistrySnapshot,
    inspect_resource_access,
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
    for binding in registered.binding.bindings:
        resource_status = status_by_id[binding.resource_id]
        resource_access = access_by_id[binding.resource_id]
        if resource_access.credential_source is CredentialBindingSource.NOT_REQUIRED:
            access_state = "not_required"
        elif resource_access.credential_present:
            access_state = "configured"
        else:
            access_state = "missing"
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


__all__ = ["load_project_resource_portfolio"]

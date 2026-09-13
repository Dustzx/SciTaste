from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scitaste.generative_ui import resource_configuration as configuration_module
from scitaste.generative_ui.planning_directive import PlanningDirectivePublication
from scitaste.generative_ui.program_revision import ProgramRevisionDraft
from scitaste.generative_ui.project_resources import (
    inspect_project_planner_admission,
    load_project_resource_portfolio,
)
from scitaste.generative_ui.resource_configuration import (
    ProjectResourceConfigurationRequest,
    apply_project_resource_configuration,
    compile_project_resource_binding,
    inspect_project_resource_configuration,
)
from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.resources import (
    ComputeResourceRuntime,
    ResourceSelectionStatus,
    load_compute_resource_catalog,
    load_project_resource_binding,
)


def _sha(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: item.isoformat(),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _publication(draft: ProgramRevisionDraft | None = None) -> PlanningDirectivePublication:
    draft = draft or ProgramRevisionDraft(
        base_dossier_sha256="d" * 64,
        change_kind="request_resource_revision",
        target_stage_id="run-api-prepilot",
        summary="Prefer API B for the next bounded prepilot.",
        rationale="The user requested this exact registered resource preference.",
        requested_resource_roles=("primary-api",),
        requested_resource_ids=("api-b",),
    )
    values = {
        "schema_version": "1.0",
        "publication_id": "program-directive-resource-test",
        "project_id": "resource-project",
        "run_id": "planning-resource-test",
        "published_at": datetime.now(UTC),
        "source_project_revision": 0,
        "source_snapshot_sha256": "a" * 64,
        "source_dossier_id": "iclr-program",
        "source_dossier_sha256": "d" * 64,
        "proposal_id": "program-revision-resource-test",
        "proposal_record_sha256": "b" * 64,
        "decision_id": "program-decision-resource-test",
        "decision_sha256": "c" * 64,
        "draft": draft,
        "source_dossier_unchanged": True,
        "source_resource_binding_unchanged": True,
        "authorizes_external_action": False,
        "authorizes_execution": False,
        "execution_authority": "none",
        "verification_route": "direct_path",
        "verification_reason_codes": ("verification-cost-exceeds-avoidable-loss",),
    }
    prototype = PlanningDirectivePublication.model_construct(
        **values,
        publication_sha256="0" * 64,
    )
    return PlanningDirectivePublication(
        **values,
        publication_sha256=_sha(prototype.model_dump(mode="json", exclude={"publication_sha256"})),
    )


def _resource_runtime(
    tmp_path: Path,
    *,
    planner_ready: bool = False,
) -> tuple[ProjectRuntime, object, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="resource-project",
            title="Resource project",
            research_direction="Apply model-authored resource priorities.",
            status="active",
        )
    )
    catalog_path = tmp_path / "compute.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "catalog_id": "test-compute",
                "resources": [
                    {
                        "kind": "api_model",
                        "resource_id": resource_id,
                        "provider_id": resource_id,
                        "endpoint": f"https://{resource_id}.example.test/v1",
                        "interface": "openai-chat-completions",
                        "model_id": resource_id,
                        "model_revision": "test",
                        "rolling_alias": False,
                        "identity_source_url": f"https://{resource_id}.example.test/models",
                        "identity_verified_on": "2026-09-13",
                        "credential_env": f"{resource_id.upper().replace('-', '_')}_KEY",
                        "availability": (
                            "verified" if planner_ready and resource_id == "api-a" else "pending"
                        ),
                    }
                    for resource_id in ("api-a", "api-b", "api-c")
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    resource_runtime = ComputeResourceRuntime(runtime.outputs_root)
    registry = resource_runtime.initialize(catalog_path, evidence_root=tmp_path)
    binding_path = tmp_path / "binding.yaml"
    binding_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "binding_set_id": "resource-project-initial",
                "project_id": "resource-project",
                "catalog_id": "test-compute",
                "catalog_semantic_sha256": registry.catalog_semantic_sha256,
                "bindings": [
                    {
                        "binding_id": f"primary-{resource_id}",
                        "resource_id": resource_id,
                        "expected_kind": "api_model",
                        "role": "primary-api",
                        "priority": priority,
                        "status": (
                            "verified" if planner_ready and resource_id == "api-a" else "pending"
                        ),
                        "purpose": "Registered candidate for a later owner-approved API study.",
                        "required_for": (
                            ["generation-as-content-planner"]
                            if planner_ready and resource_id == "api-a"
                            else ["api-prepilot"]
                        ),
                    }
                    for priority, resource_id in enumerate(("api-a", "api-b"), 1)
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registered = resource_runtime.register_project_binding(catalog_path, binding_path)
    return runtime, registry, registered


def test_project_binding_admits_only_its_configured_generation_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("API_A_KEY", "local-test-only")
    runtime, _, _ = _resource_runtime(tmp_path, planner_ready=True)

    portfolio = load_project_resource_portfolio(runtime, "resource-project")
    assert portfolio is not None
    assert portfolio.planner_binding_state == "ready"
    assert portfolio.planner_resource_id == "api-a"
    assert inspect_project_planner_admission(
        runtime,
        "resource-project",
        planner_implementation="structured-model-v1",
        planner_backend="api-a",
        planner_model="api-a",
    ).admitted is True
    mismatch = inspect_project_planner_admission(
        runtime,
        "resource-project",
        planner_implementation="structured-model-v1",
        planner_backend="api-b",
        planner_model="api-b",
    )
    assert mismatch.admitted is False
    assert mismatch.reason_code == "project-planner-resource-not-admitted"


def test_published_resource_plan_requires_explicit_apply_and_updates_only_priorities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime, registry, registered = _resource_runtime(tmp_path)
    directive = _publication()
    monkeypatch.setattr(
        configuration_module,
        "load_latest_planning_directive",
        lambda _runtime, _project_id: directive,
    )
    before = runtime.open("resource-project")
    request = ProjectResourceConfigurationRequest(
        project_id="resource-project",
        publication_id=directive.publication_id,
        publication_sha256=directive.publication_sha256,
        expected_project_revision=before.revision,
        expected_snapshot_sha256=before.snapshot_sha256,
        expected_binding_record_sha256=registered.record_sha256,
        expected_registry_sha256=registry.registry_sha256,
        confirm_apply=True,
    )

    snapshot, publication = apply_project_resource_configuration(runtime, request)

    assert snapshot.revision == 2
    assert publication.source_binding_record_sha256 == registered.record_sha256
    assert publication.credential_bindings_unchanged is True
    assert publication.remote_probe_performed is False
    assert publication.workload_executed is False
    assert publication.authorizes_execution is False
    assert publication.verification_route == "direct_path"
    binding = load_project_resource_binding(
        runtime.outputs_root / "resources/projects/resource-project/RESOURCE_BINDING.yaml"
    )
    priorities = {item.resource_id: item.priority for item in binding.bindings}
    assert priorities == {"api-a": 2, "api-b": 1}
    assert binding.catalog_semantic_sha256 == registry.catalog_semantic_sha256
    assert (
        inspect_project_resource_configuration(
            runtime,
            "resource-project",
            publication.run_id,
        )
        == publication
    )
    portfolio = load_project_resource_portfolio(runtime, "resource-project")
    assert portfolio is not None
    assert portfolio.configuration_authority == "user_applied"
    assert portfolio.source_planning_publication_id == directive.publication_id
    assert portfolio.binding_record_sha256 == publication.configured_binding_record_sha256
    assert portfolio.available_resource_count == 1
    assert portfolio.available_resources[0].resource_id == "api-c"
    assert portfolio.available_resources[0].compatible_roles == ("primary-api",)
    assert portfolio.available_resources[0].selection_status == "current"
    assert portfolio.available_resources[0].attachable is True

    repeated_snapshot, repeated = apply_project_resource_configuration(runtime, request)
    assert repeated_snapshot.revision == snapshot.revision
    assert repeated == publication


def test_model_planned_catalog_attachment_becomes_project_metadata_without_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime, registry, registered = _resource_runtime(tmp_path)
    directive = _publication(
        ProgramRevisionDraft(
            base_dossier_sha256="d" * 64,
            change_kind="request_resource_revision",
            target_stage_id="run-api-prepilot",
            summary="Attach API C to the primary API role.",
            rationale="Keep the alternative visible to this project before model selection.",
            requested_resource_roles=("primary-api",),
            requested_resource_ids=("api-c",),
        )
    )
    monkeypatch.setattr(
        configuration_module,
        "load_latest_planning_directive",
        lambda _runtime, _project_id: directive,
    )
    before = runtime.open("resource-project")
    request = ProjectResourceConfigurationRequest(
        project_id="resource-project",
        publication_id=directive.publication_id,
        publication_sha256=directive.publication_sha256,
        expected_project_revision=before.revision,
        expected_snapshot_sha256=before.snapshot_sha256,
        expected_binding_record_sha256=registered.record_sha256,
        expected_registry_sha256=registry.registry_sha256,
        confirm_apply=True,
    )

    _, publication = apply_project_resource_configuration(runtime, request)

    assert publication.verification_route == "direct_path"
    assert publication.remote_probe_performed is False
    assert publication.workload_executed is False
    portfolio = load_project_resource_portfolio(runtime, "resource-project")
    assert portfolio is not None
    assert portfolio.available_resource_count == 0
    attached = next(item for item in portfolio.resources if item.resource_id == "api-c")
    assert attached.role == "primary-api"
    assert attached.priority == 1
    assert attached.access_state == "missing"
    assert attached.required_for == ("run-api-prepilot",)


def test_historical_catalog_resource_cannot_be_newly_attached(tmp_path: Path) -> None:
    runtime, _, _ = _resource_runtime(tmp_path)
    current = load_project_resource_binding(
        runtime.outputs_root / "resources/projects/resource-project/RESOURCE_BINDING.yaml"
    )
    directive = _publication(
        ProgramRevisionDraft(
            base_dossier_sha256="d" * 64,
            change_kind="request_resource_revision",
            target_stage_id="run-api-prepilot",
            summary="Reattach the historical API.",
            rationale="This should be rejected by catalog lifecycle policy.",
            requested_resource_roles=("primary-api",),
            requested_resource_ids=("api-c",),
        )
    )
    loaded = load_compute_resource_catalog(tmp_path / "compute.yaml")
    selection = dict(loaded.selection_status_by_id)
    selection["api-c"] = ResourceSelectionStatus.HISTORICAL

    with pytest.raises(ValueError, match="historical or disabled"):
        compile_project_resource_binding(
            current,
            directive,
            catalog=loaded.catalog,
            selection_status_by_id=selection,
        )

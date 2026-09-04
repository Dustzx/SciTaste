from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    COMPONENT_REGISTRY,
    ActionProposal,
    ComponentSpec,
    ProposalKind,
    ProposeTransitionPayload,
    SurfacePurpose,
    SurfaceRevision,
    SurfaceSpec,
    TrustedComponent,
    build_fixture_surfaces,
    build_paper_status_fixture,
    build_project_overview_fixture,
    build_run_comparison_fixture,
)
from scitaste.schema.actions import MetaAction


def test_registry_is_closed_and_contains_all_initial_trusted_components() -> None:
    assert set(COMPONENT_REGISTRY) == set(TrustedComponent)
    assert {item.value for item in TrustedComponent} == {
        "ProjectSummaryCard",
        "StageTimeline",
        "BlockerList",
        "RunHealth",
        "BudgetMeter",
        "DecisionComparison",
        "EvidenceGraph",
        "ClaimMatrix",
        "ReviewerQueue",
        "ArtifactViewer",
        "PaperPreview",
    }


def test_five_deterministic_fixture_surfaces_are_evidence_grounded() -> None:
    surfaces = build_fixture_surfaces()

    assert set(surfaces) == set(SurfacePurpose)
    for purpose, surface in surfaces.items():
        assert surface.purpose == purpose
        assert surface.project_id == surface.snapshot.project_id
        assert surface.snapshot.evidence_refs
        assert all(component.evidence_ref_ids for component in surface.components)
        assert len(surface.fingerprint) == 64


def test_surface_json_round_trip_and_fingerprint_are_stable() -> None:
    surface = build_project_overview_fixture()

    restored = SurfaceSpec.model_validate_json(surface.model_dump_json())
    reordered = json.loads(surface.canonical_json())
    reordered["components"][0]["data"] = {
        key: reordered["components"][0]["data"][key]
        for key in reversed(reordered["components"][0]["data"])
    }

    assert restored == surface
    assert restored.fingerprint == surface.fingerprint
    assert SurfaceSpec.model_validate(reordered).fingerprint == surface.fingerprint
    assert surface.canonical_json() == restored.canonical_json()


def test_fingerprint_changes_when_visible_content_changes() -> None:
    surface = build_project_overview_fixture()
    changed = surface.model_copy(update={"title": "Changed project overview"})

    assert changed.fingerprint != surface.fingerprint


@pytest.mark.parametrize(
    "data",
    [
        {"summary": "<script>alert(1)</script>"},
        {"summary": "javascript:alert(1)"},
        {"summary": "rm -rf /tmp/project"},
        {"summary": "https://attacker.example/payload"},
        {"artifact_path": "../../etc/passwd"},
        {"score": float("nan")},
        {"score": float("inf")},
    ],
)
def test_component_rejects_active_or_unsafe_payloads(data) -> None:
    with pytest.raises(ValidationError):
        ComponentSpec(
            component_id="unsafe-component",
            component=TrustedComponent.ARTIFACT_VIEWER,
            title="Unsafe component",
            evidence_ref_ids=["paper-artifact"],
            data=data,
        )


def test_component_rejects_executable_keys_and_unregistered_types() -> None:
    with pytest.raises(ValidationError, match="executable content"):
        ComponentSpec(
            component_id="unsafe-component",
            component=TrustedComponent.ARTIFACT_VIEWER,
            title="Unsafe component",
            evidence_ref_ids=["paper-artifact"],
            data={"command": "render"},
        )
    with pytest.raises(ValidationError):
        ComponentSpec.model_validate(
            {
                "component_id": "unknown-component",
                "component": "RawHtmlPanel",
                "title": "Unknown",
                "evidence_ref_ids": ["paper-artifact"],
                "data": {},
            }
        )


def test_surface_rejects_duplicate_component_and_action_ids() -> None:
    overview = build_project_overview_fixture().model_dump(mode="json")
    overview["components"].append(overview["components"][0])
    with pytest.raises(ValidationError, match="component IDs must be unique"):
        SurfaceSpec.model_validate(overview)

    paper = build_paper_status_fixture().model_dump(mode="json")
    paper["actions"].append(paper["actions"][0])
    with pytest.raises(ValidationError, match="action IDs must be unique"):
        SurfaceSpec.model_validate(paper)


def test_surface_rejects_missing_evidence_and_unknown_component_binding() -> None:
    missing = build_project_overview_fixture().model_dump(mode="json")
    missing["components"][0]["evidence_ref_ids"] = ["missing-evidence"]
    with pytest.raises(ValidationError, match="missing evidence"):
        SurfaceSpec.model_validate(missing)

    unknown_component = build_paper_status_fixture().model_dump(mode="json")
    unknown_component["actions"][0]["component_id"] = "missing-component"
    with pytest.raises(ValidationError, match="unknown component"):
        SurfaceSpec.model_validate(unknown_component)


def test_surface_rejects_unsubstantiated_status_and_paper_claims() -> None:
    status = build_paper_status_fixture().model_dump(mode="json")
    status["components"][1]["data"]["status"] = "publication_ready"
    with pytest.raises(ValidationError, match="ungrounded status claim"):
        SurfaceSpec.model_validate(status)

    paper = build_run_comparison_fixture().model_dump(mode="json")
    paper["components"][1]["data"]["paper_title"] = "Unsupported paper title"
    with pytest.raises(ValidationError, match="ungrounded paper claim"):
        SurfaceSpec.model_validate(paper)


def test_surface_rejects_component_with_wrong_evidence_kind() -> None:
    payload = build_project_overview_fixture().model_dump(mode="json")
    payload["components"][0]["evidence_ref_ids"] = ["paper-artifact"]

    with pytest.raises(ValidationError, match="required evidence kinds"):
        SurfaceSpec.model_validate(payload)


def test_action_proposal_has_no_execution_authority_or_command_slot() -> None:
    proposal = build_paper_status_fixture().actions[0].proposal

    assert proposal.authority == "proposal_only"
    payload = proposal.model_dump(mode="json")
    payload["authority"] = "execute"
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(payload)
    payload = proposal.model_dump(mode="json")
    payload["command"] = "render-paper"
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(payload)


def test_transition_proposal_requires_approval() -> None:
    with pytest.raises(ValidationError, match="require human approval"):
        ActionProposal(
            payload=ProposeTransitionPayload(
                kind=ProposalKind.PROPOSE_TRANSITION,
                from_stage="evidence",
                proposed_action=MetaAction.COLLECT_EVIDENCE,
                decision_ref_id="decision-record",
            ),
            rationale="Resolve the registered evidence gap.",
            evidence_ref_ids=["decision-record"],
        )


def test_action_must_be_grounded_by_its_bound_component() -> None:
    payload = build_paper_status_fixture().model_dump(mode="json")
    proposal = payload["actions"][0]["proposal"]
    proposal["payload"]["artifact_ref_id"] = "paper-record"
    proposal["evidence_ref_ids"] = ["paper-record"]

    with pytest.raises(ValidationError, match="not grounded by its component"):
        SurfaceSpec.model_validate(payload)


def test_compare_runs_requires_run_record_evidence() -> None:
    payload = build_run_comparison_fixture().model_dump(mode="json")
    component = payload["components"][0]
    component["evidence_ref_ids"].append("paper-record")
    proposal = payload["actions"][0]["proposal"]
    proposal["payload"]["candidate_run_ref_id"] = "paper-record"
    proposal["evidence_ref_ids"] = ["run-a", "paper-record"]

    with pytest.raises(ValidationError, match="two run records"):
        SurfaceSpec.model_validate(payload)


def test_surface_revision_is_auditable_and_round_trips() -> None:
    previous = build_project_overview_fixture()
    replacement = previous.model_copy(update={"revision": 2, "title": "Updated overview"})
    revision = SurfaceRevision(
        revision_id="overview-revision-two",
        surface_id=previous.surface_id,
        previous_revision=previous.revision,
        previous_fingerprint=previous.fingerprint,
        surface=replacement,
        changed_component_ids=["project-summary"],
        evidence_ref_ids=["project-manifest"],
        reason="Refresh the summary after a project snapshot update.",
    )

    restored = SurfaceRevision.model_validate_json(revision.model_dump_json())
    assert restored == revision
    assert restored.fingerprint == revision.fingerprint


def test_surface_revision_rejects_non_increasing_or_invalid_component_changes() -> None:
    previous = build_project_overview_fixture()
    with pytest.raises(ValidationError, match="must increase"):
        SurfaceRevision(
            revision_id="invalid-revision",
            surface_id=previous.surface_id,
            previous_revision=previous.revision,
            previous_fingerprint=previous.fingerprint,
            surface=previous,
            evidence_ref_ids=["project-manifest"],
            reason="This revision does not advance.",
        )

    replacement = previous.model_copy(update={"revision": 2})
    with pytest.raises(ValidationError, match="remain present"):
        SurfaceRevision(
            revision_id="invalid-removal",
            surface_id=previous.surface_id,
            previous_revision=previous.revision,
            previous_fingerprint=previous.fingerprint,
            surface=replacement,
            removed_component_ids=["project-summary"],
            evidence_ref_ids=["project-manifest"],
            reason="The declared removal contradicts the replacement surface.",
        )

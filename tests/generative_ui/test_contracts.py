from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    APPROVAL_EVIDENCE_KINDS,
    COMPONENT_REGISTRY,
    ActionProposal,
    ApprovalSubject,
    ComponentSpec,
    EvidenceRef,
    ProposalKind,
    ProposeTransitionPayload,
    RunBlockerPanelData,
    SnapshotBinding,
    SurfacePurpose,
    SurfaceRevision,
    SurfaceSpec,
    TrustedComponent,
    build_blocked_run_fixture,
    build_fixture_surfaces,
    build_paper_status_fixture,
    build_project_overview_fixture,
    build_run_comparison_fixture,
    component_data_json_schema,
    compute_snapshot_sha256,
    fixture_snapshot_binding,
)
from scitaste.schema.actions import MetaAction


def test_registry_is_closed_and_contains_all_initial_trusted_components() -> None:
    assert set(COMPONENT_REGISTRY) == set(TrustedComponent)
    assert {
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
    } <= {item.value for item in TrustedComponent}
    assert set(APPROVAL_EVIDENCE_KINDS) == set(ApprovalSubject)


def test_five_deterministic_fixture_surfaces_are_evidence_grounded() -> None:
    surfaces = build_fixture_surfaces()

    assert set(surfaces) == {
        SurfacePurpose.PROJECT_OVERVIEW,
        SurfacePurpose.PAPER_STATUS,
        SurfacePurpose.BLOCKED_RUN,
        SurfacePurpose.NEXT_STEP,
        SurfacePurpose.RUN_COMPARISON,
    }
    for purpose, surface in surfaces.items():
        assert surface.purpose == purpose
        assert surface.project_id == surface.snapshot.project_id
        assert surface.snapshot.evidence_refs
        assert all(component.evidence_ref_ids for component in surface.components)
        assert len(surface.fingerprint) == 64
    covered = {
        component.component for surface in surfaces.values() for component in surface.components
    }
    assert {item.value for item in covered} == {
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
    "unsafe_text",
    [
        "<script>alert(1)</script>",
        "<!doctype html>",
        "javascript:alert(1)",
        "alert(1)",
        "fetch('/api')",
        "rm -rf /tmp/project",
        "/bin/sh -c id",
        "cat /etc/passwd",
        "touch /tmp/project",
        "https://attacker.example/payload",
        "//attacker.example/payload",
        "ws://attacker.example/socket",
        "ssh://attacker.example/payload",
    ],
)
def test_component_rejects_common_active_or_unsafe_text(unsafe_text: str) -> None:
    payload = build_paper_status_fixture().model_dump(mode="json")
    payload["components"][0]["data"]["excerpt"] = unsafe_text
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../../etc/passwd",
        "papers//paper.pdf",
        "papers/./paper.pdf",
        "papers/paper.pdf/",
        "papers/%2e%2e/etc/passwd",
        "papers/%252e%252e%252fetc/passwd",
    ],
)
def test_component_rejects_traversal_or_non_normalized_locators(unsafe_path: str) -> None:
    payload = build_paper_status_fixture().model_dump(mode="json")
    payload["components"][1]["data"]["artifact_path"] = unsafe_path
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)


@pytest.mark.parametrize("unsafe_number", [float("nan"), float("inf")])
def test_component_rejects_non_finite_numbers(unsafe_number: float) -> None:
    payload = build_run_comparison_fixture().model_dump(mode="json")
    payload["components"][0]["data"]["baseline_score"] = unsafe_number
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)


def test_component_rejects_executable_keys_and_unregistered_types() -> None:
    with pytest.raises(ValidationError, match="executable content"):
        ComponentSpec(
            component_id="unsafe-component",
            component=TrustedComponent.PAPER_PREVIEW,
            title="Unsafe component",
            evidence_ref_ids=["paper-record"],
            data={"command": "render"},
        )


def test_blocker_detail_cannot_claim_missing_or_unavailable_reasons() -> None:
    common = {
        "run_ref_id": "run-evidence",
        "run_id": "blocked-run",
        "run_status": "blocked",
        "classification": "blocked",
        "reason_code": "registered-status-blocked",
        "source_locator": "runs/blocked-run",
    }
    with pytest.raises(ValidationError, match="requires at least one reason"):
        RunBlockerPanelData.model_validate({"blockers": [{**common, "detail_state": "recorded"}]})
    with pytest.raises(ValidationError, match="cannot contain reasons"):
        RunBlockerPanelData.model_validate(
            {
                "blockers": [
                    {
                        **common,
                        "detail_state": "unavailable",
                        "recorded_reasons": ["Unsupported reason"],
                    }
                ]
            }
        )


def test_every_component_uses_a_closed_required_data_schema() -> None:
    for component in TrustedComponent:
        schema_json = json.dumps(component_data_json_schema(component), sort_keys=True)
        assert '"additionalProperties": false' in schema_json

    for surface in build_fixture_surfaces().values():
        for component in surface.components:
            payload = component.model_dump(mode="json")
            payload["data"]["unexpected_field"] = "not registered"
            with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
                ComponentSpec.model_validate(payload)

            payload = component.model_dump(mode="json")
            payload["data"] = {}
            with pytest.raises(ValidationError):
                ComponentSpec.model_validate(payload)
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
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SurfaceSpec.model_validate(status)

    paper = build_run_comparison_fixture().model_dump(mode="json")
    paper["components"][1]["data"]["paper_title"] = "Unsupported paper title"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SurfaceSpec.model_validate(paper)


def test_surface_rejects_component_with_wrong_evidence_kind() -> None:
    payload = build_project_overview_fixture().model_dump(mode="json")
    payload["components"][0]["evidence_ref_ids"] = ["paper-artifact"]

    with pytest.raises(ValidationError, match="required evidence kinds"):
        SurfaceSpec.model_validate(payload)


def test_component_data_references_and_artifact_locator_are_evidence_bound() -> None:
    outside = build_project_overview_fixture().model_dump(mode="json")
    outside["components"][0]["data"]["project_ref_id"] = "stage-analysis"
    with pytest.raises(ValidationError, match="data references undeclared evidence"):
        SurfaceSpec.model_validate(outside)

    wrong_kind = build_project_overview_fixture().model_dump(mode="json")
    wrong_kind["components"][0]["evidence_ref_ids"].append("stage-analysis")
    wrong_kind["components"][0]["data"]["project_ref_id"] = "stage-analysis"
    with pytest.raises(ValidationError, match="requires evidence kinds"):
        SurfaceSpec.model_validate(wrong_kind)

    wrong_path = build_paper_status_fixture().model_dump(mode="json")
    wrong_path["components"][1]["data"]["artifact_path"] = "papers/paper-a/other.pdf"
    with pytest.raises(ValidationError, match="path must match"):
        SurfaceSpec.model_validate(wrong_path)


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


def test_approval_subject_requires_matching_evidence_kind() -> None:
    payload = build_blocked_run_fixture().model_dump(mode="json")
    payload["actions"][0]["proposal"]["payload"]["subject"] = "paper_selection"

    with pytest.raises(ValidationError, match="paper_selection approval requires"):
        SurfaceSpec.model_validate(payload)


def test_snapshot_hash_is_canonical_and_manifest_bound() -> None:
    snapshot = fixture_snapshot_binding()
    assert snapshot.snapshot_sha256 == (
        "b54d7b362d979e69ebd709ca2d347cfef09ae600b0ff00d8f1937acac7bb0fdb"
    )
    assert snapshot.snapshot_sha256 == compute_snapshot_sha256(
        project_id=snapshot.project_id,
        snapshot_revision=snapshot.snapshot_revision,
        evidence_refs=reversed(snapshot.evidence_refs),
    )
    assert snapshot == SnapshotBinding.from_trusted_evidence(
        project_id=snapshot.project_id,
        snapshot_revision=snapshot.snapshot_revision,
        evidence_refs=reversed(snapshot.evidence_refs),
    )

    payload = snapshot.model_dump(mode="json")
    payload["evidence_refs"][0]["sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="canonical evidence manifest"):
        SnapshotBinding.model_validate(payload)


def test_project_identifier_is_canonical_kebab_case_without_normalization() -> None:
    valid = fixture_snapshot_binding().evidence_refs[0].model_dump(mode="json")
    for project_id in ["Project_1", " project-one", "project-one "]:
        invalid = {**valid, "project_id": project_id}
        with pytest.raises(ValidationError):
            EvidenceRef.model_validate(invalid)


def test_snapshot_rejects_duplicate_locators() -> None:
    snapshot = fixture_snapshot_binding()
    refs = [item.model_copy() for item in snapshot.evidence_refs]
    refs[1] = refs[1].model_copy(update={"locator": refs[0].locator})
    digest = compute_snapshot_sha256(
        project_id=snapshot.project_id,
        snapshot_revision=snapshot.snapshot_revision,
        evidence_refs=refs,
    )
    with pytest.raises(ValidationError, match="locators must be unique"):
        SnapshotBinding(
            project_id=snapshot.project_id,
            snapshot_revision=snapshot.snapshot_revision,
            snapshot_sha256=digest,
            evidence_refs=refs,
        )


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

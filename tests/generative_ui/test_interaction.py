from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    DuplicateEventError,
    RendererComponent,
    RendererDocument,
    RevisionConflictError,
    StaleSurfaceError,
    SurfaceEvent,
    SurfaceRevision,
    SurfaceSession,
    TrustedComponent,
    UnknownActionError,
    build_paper_status_fixture,
    make_surface_event,
    project_surface,
)


def test_projection_populates_only_the_fixed_workspace_shell() -> None:
    surface = build_paper_status_fixture()
    document = project_surface(surface)

    assert document.shell.shell_id == "scitaste-research-shell"
    assert document.shell.fixed_regions == (
        "header",
        "project_nav",
        "workspace",
        "inspector",
    )
    assert document.shell.generated_region == "workspace"
    assert {item.renderer for item in document.components} == {
        TrustedComponent.PAPER_PREVIEW,
        TrustedComponent.ARTIFACT_VIEWER,
    }
    assert all(item.region == "workspace" for item in document.components)
    assert document.execution_authority == "none"


def test_renderer_document_round_trips_without_exposing_server_proposal_payloads() -> None:
    document = project_surface(build_paper_status_fixture())
    serialized = document.model_dump_json()
    restored = RendererDocument.model_validate_json(serialized)

    assert restored == document
    assert restored.fingerprint == document.fingerprint
    assert '"proposal"' not in serialized
    assert '"rationale"' not in serialized
    assert restored.actions[0].proposal_kind.value == "inspect_artifact"


def test_renderer_contract_rejects_a_mutable_shell_or_unsafe_component_data() -> None:
    document = project_surface(build_paper_status_fixture()).model_dump(mode="json")
    document["shell"]["fixed_regions"] = ["workspace"]
    with pytest.raises(ValidationError):
        RendererDocument.model_validate(document)

    component = project_surface(build_paper_status_fixture()).components[0]
    with pytest.raises(ValidationError, match="URIs are not allowed"):
        RendererComponent(
            component_id=component.component_id,
            renderer=component.renderer,
            title=component.title,
            evidence_ref_ids=component.evidence_ref_ids,
            data={"paper_path": "https://attacker.example/paper.pdf"},
        )


def test_identity_only_event_round_trips_and_rejects_arbitrary_payload() -> None:
    surface = build_paper_status_fixture()
    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")

    restored = SurfaceEvent.model_validate_json(event.model_dump_json())
    assert restored == event
    assert restored.fingerprint == event.fingerprint
    payload = event.model_dump(mode="json")
    payload["command"] = "inspect-paper"
    with pytest.raises(ValidationError):
        SurfaceEvent.model_validate(payload)


def test_session_activation_returns_pending_proposal_without_execution_authority() -> None:
    surface = build_paper_status_fixture()
    session = SurfaceSession(surface)
    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")

    receipt = session.activate(event)

    assert receipt.status == "proposal_pending"
    assert receipt.proposal == surface.actions[0].proposal
    assert receipt.proposal.authority == "proposal_only"
    assert receipt.execution_authority == "none"
    assert receipt.next_boundary == "deterministic_controller"
    assert receipt.event_fingerprint == event.fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "another-project"),
        ("surface_id", "another-surface"),
        ("surface_revision", 99),
        ("surface_fingerprint", "0" * 64),
        ("snapshot_revision", 99),
        ("snapshot_sha256", "0" * 64),
    ],
)
def test_session_rejects_stale_or_cross_project_events(field: str, value: object) -> None:
    surface = build_paper_status_fixture()
    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")
    stale = event.model_copy(update={field: value})

    with pytest.raises(StaleSurfaceError, match=field):
        SurfaceSession(surface).activate(stale)


def test_session_rejects_unknown_actions_and_accepted_event_replays() -> None:
    surface = build_paper_status_fixture()
    session = SurfaceSession(surface)
    unknown = make_surface_event(surface, event_id="unknown-event", action_id="unknown-action")
    with pytest.raises(UnknownActionError):
        session.activate(unknown)

    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")
    session.activate(event)
    with pytest.raises(DuplicateEventError):
        session.activate(event)


def test_session_replaces_a_surface_and_invalidates_old_events() -> None:
    previous = build_paper_status_fixture()
    session = SurfaceSession(previous)
    old_event = make_surface_event(previous, event_id="old-event", action_id="inspect-paper")
    replacement = previous.model_copy(update={"revision": 2, "title": "Updated paper status"})
    revision = _revision(previous, replacement)

    assert session.replace(revision) == replacement
    with pytest.raises(StaleSurfaceError):
        session.activate(old_event)
    new_event = make_surface_event(
        replacement,
        event_id="new-event",
        action_id="inspect-paper",
    )
    assert session.activate(new_event).surface_revision == 2


def test_session_rejects_a_stale_revision_base() -> None:
    previous = build_paper_status_fixture()
    replacement = previous.model_copy(update={"revision": 2})
    revision = _revision(previous, replacement).model_copy(
        update={"previous_fingerprint": "0" * 64}
    )

    with pytest.raises(RevisionConflictError, match="fingerprint"):
        SurfaceSession(previous).replace(revision)


def test_session_rejects_snapshot_regression_or_hash_collision() -> None:
    previous = build_paper_status_fixture()
    regressed_snapshot = previous.snapshot.model_copy(update={"snapshot_revision": 6})
    regressed_surface = previous.model_copy(update={"revision": 2, "snapshot": regressed_snapshot})
    with pytest.raises(RevisionConflictError, match="regresses"):
        SurfaceSession(previous).replace(_revision(previous, regressed_surface))

    colliding_snapshot = previous.snapshot.model_copy(update={"snapshot_sha256": "f" * 64})
    colliding_surface = previous.model_copy(update={"revision": 2, "snapshot": colliding_snapshot})
    with pytest.raises(RevisionConflictError, match="two different content hashes"):
        SurfaceSession(previous).replace(_revision(previous, colliding_surface))


def test_receipt_is_stable_json_and_contains_only_registered_evidence() -> None:
    surface = build_paper_status_fixture()
    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")
    receipt = SurfaceSession(surface).activate(event)
    restored = type(receipt).model_validate_json(receipt.model_dump_json())
    available = {item.evidence_id for item in surface.snapshot.evidence_refs}

    assert restored == receipt
    assert set(receipt.proposal.evidence_ref_ids) <= available
    assert json.loads(receipt.model_dump_json())["execution_authority"] == "none"


def _revision(previous, replacement) -> SurfaceRevision:
    return SurfaceRevision(
        revision_id="paper-status-revision-two",
        surface_id=previous.surface_id,
        previous_revision=previous.revision,
        previous_fingerprint=previous.fingerprint,
        surface=replacement,
        changed_component_ids=["paper-preview"],
        evidence_ref_ids=["paper-record"],
        reason="Refresh the paper status surface.",
    )

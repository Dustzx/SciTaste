from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scitaste.generative_ui import (
    AuditIntegrityError,
    DuplicateEventError,
    SurfaceAuditLog,
    SurfaceRevision,
    SurfaceSession,
    SurfaceSpec,
    build_paper_status_fixture,
    make_surface_event,
)


def test_audit_log_starts_with_a_self_hashed_surface(tmp_path) -> None:
    surface = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")

    opened = log.start(surface)
    records = log.records()

    assert records == [opened]
    assert opened.sequence == 0
    assert opened.previous_record_sha256 is None
    assert opened.payload.kind == "surface_opened"
    assert opened.payload.surface == surface
    assert len(opened.record_sha256) == 64
    assert log.path.read_text(encoding="utf-8").endswith("\n")


def test_audit_log_cannot_replace_an_existing_history(tmp_path) -> None:
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    surface = build_paper_status_fixture()
    log.start(surface)

    with pytest.raises(FileExistsError):
        log.start(surface)


def test_audit_log_replays_interactions_and_surface_revisions(tmp_path) -> None:
    initial = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(initial)

    first_event = make_surface_event(
        initial,
        event_id="inspect-initial-paper",
        action_id="inspect-paper",
    )
    first_receipt = SurfaceSession(initial).activate(first_event)
    interaction_record = log.append_interaction(first_event, first_receipt)

    replacement = initial.model_copy(update={"revision": 2, "title": "Updated paper status"})
    revision = _revision(initial, replacement)
    revision_record = log.append_revision(revision)

    second_event = make_surface_event(
        replacement,
        event_id="inspect-updated-paper",
        action_id="inspect-paper",
    )
    second_receipt = SurfaceSession(replacement).activate(second_event)
    final_record = log.append_interaction(second_event, second_receipt)

    records = log.records()
    assert [record.sequence for record in records] == [0, 1, 2, 3]
    assert interaction_record.previous_record_sha256 == records[0].record_sha256
    assert revision_record.previous_record_sha256 == interaction_record.record_sha256
    assert final_record.previous_record_sha256 == revision_record.record_sha256

    replayed = log.replay_session()
    assert replayed.surface == replacement
    with pytest.raises(DuplicateEventError):
        replayed.activate(second_event)


def test_audit_log_rejects_a_forged_receipt_without_writing(tmp_path) -> None:
    surface = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(surface)
    event = make_surface_event(surface, event_id="inspect-paper-once", action_id="inspect-paper")
    receipt = SurfaceSession(surface).activate(event)
    forged = receipt.model_copy(update={"action_id": "different-action"})

    before = log.path.read_bytes()
    with pytest.raises(AuditIntegrityError):
        log.append_interaction(event, forged)

    assert log.path.read_bytes() == before
    assert len(log.records()) == 1


def test_audit_log_rejects_a_substituted_proposal_without_writing(tmp_path) -> None:
    surface = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(surface)
    event = make_surface_event(surface, event_id="substituted-proposal", action_id="inspect-paper")
    receipt = SurfaceSession(surface).activate(event)
    forged_proposal = receipt.proposal.model_copy(
        update={"rationale": "A caller-substituted proposal."}
    )
    forged = receipt.model_copy(update={"proposal": forged_proposal})

    before = log.path.read_bytes()
    with pytest.raises(AuditIntegrityError, match="server-owned surface action"):
        log.append_interaction(event, forged)

    assert log.path.read_bytes() == before


def test_audit_log_rejects_stale_events_without_writing(tmp_path) -> None:
    surface = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(surface)
    event = make_surface_event(surface, event_id="stale-event", action_id="inspect-paper")
    stale = event.model_copy(update={"surface_fingerprint": "0" * 64})
    receipt = SurfaceSession(surface).activate(event)
    stale_receipt = receipt.model_copy(
        update={
            "event_fingerprint": stale.fingerprint,
            "surface_fingerprint": stale.surface_fingerprint,
        }
    )

    before = log.path.read_bytes()
    with pytest.raises(AuditIntegrityError, match="cannot be replayed"):
        log.append_interaction(stale, stale_receipt)

    assert log.path.read_bytes() == before


def test_audit_log_rejects_a_stale_revision_without_writing(tmp_path) -> None:
    initial = build_paper_status_fixture()
    replacement = initial.model_copy(update={"revision": 2})
    stale = _revision(initial, replacement).model_copy(update={"previous_fingerprint": "0" * 64})
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(initial)

    before = log.path.read_bytes()
    with pytest.raises(AuditIntegrityError, match="revision cannot be replayed"):
        log.append_revision(stale)

    assert log.path.read_bytes() == before


def test_audit_log_requires_an_initialized_history(tmp_path) -> None:
    log = SurfaceAuditLog(tmp_path / "missing-audit.jsonl")

    with pytest.raises(FileNotFoundError):
        log.records()


def test_audit_log_detects_payload_tampering_and_truncation(tmp_path) -> None:
    surface = build_paper_status_fixture()
    path = tmp_path / "surface-audit.jsonl"
    log = SurfaceAuditLog(path)
    log.start(surface)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"]["surface"]["title"] = "Tampered paper status"
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="invalid surface audit record"):
        log.records()

    log = SurfaceAuditLog(tmp_path / "truncated-audit.jsonl")
    log.start(surface)
    log.path.write_bytes(log.path.read_bytes().rstrip(b"\n"))
    with pytest.raises(AuditIntegrityError, match="truncated"):
        log.records()


def test_audit_log_detects_reordered_records(tmp_path) -> None:
    surface = build_paper_status_fixture()
    path = tmp_path / "surface-audit.jsonl"
    log = SurfaceAuditLog(path)
    log.start(surface)
    event = make_surface_event(surface, event_id="event-one", action_id="inspect-paper")
    log.append_interaction(event, SurfaceSession(surface).activate(event))

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="sequence mismatch"):
        log.records()


def test_concurrent_log_instances_serialize_the_hash_chain(tmp_path) -> None:
    surface = build_paper_status_fixture()
    path = tmp_path / "surface-audit.jsonl"
    SurfaceAuditLog(path).start(surface)

    def append(index: int) -> None:
        event = make_surface_event(
            surface,
            event_id=f"concurrent-event-{index}",
            action_id="inspect-paper",
        )
        receipt = SurfaceSession(surface).activate(event)
        SurfaceAuditLog(path).append_interaction(event, receipt)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(append, range(8)))

    records = SurfaceAuditLog(path).records()
    assert [record.sequence for record in records] == list(range(9))
    assert len({record.record_sha256 for record in records}) == 9
    assert records[-1].payload.kind == "proposal_issued"


def test_persisted_proposals_retain_no_execution_authority(tmp_path) -> None:
    surface = build_paper_status_fixture()
    log = SurfaceAuditLog(tmp_path / "surface-audit.jsonl")
    log.start(surface)
    event = make_surface_event(surface, event_id="proposal-only-event", action_id="inspect-paper")
    log.append_interaction(event, SurfaceSession(surface).activate(event))

    payload = json.loads(log.path.read_text(encoding="utf-8").splitlines()[1])
    persisted_receipt = payload["payload"]["receipt"]

    assert persisted_receipt["execution_authority"] == "none"
    assert persisted_receipt["proposal"]["authority"] == "proposal_only"
    assert "command" not in log.path.read_text(encoding="utf-8")


def _revision(previous: SurfaceSpec, replacement: SurfaceSpec) -> SurfaceRevision:
    return SurfaceRevision(
        revision_id="paper-status-revision-two",
        surface_id=previous.surface_id,
        previous_revision=previous.revision,
        previous_fingerprint=previous.fingerprint,
        surface=replacement,
        changed_component_ids=["paper-preview"],
        evidence_ref_ids=["paper-record"],
        reason="Refresh the evidence-grounded paper status.",
    )

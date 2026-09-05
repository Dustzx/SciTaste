from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

import scitaste.generative_ui.audit as audit_module
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


def test_audit_reader_rejects_symlink_and_oversized_history(tmp_path) -> None:
    surface = build_paper_status_fixture()
    target = tmp_path / "target.jsonl"
    SurfaceAuditLog(target).start(surface)
    link = tmp_path / "linked.jsonl"
    link.symlink_to(target)

    with pytest.raises(AuditIntegrityError, match="symbolic link"):
        SurfaceAuditLog(link).records()

    oversized = tmp_path / "oversized.jsonl"
    oversized.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(AuditIntegrityError, match="byte limit"):
        SurfaceAuditLog(oversized).records()


def test_audit_reader_rejects_atomic_identity_swap(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = build_paper_status_fixture()
    path = tmp_path / "surface-audit.jsonl"
    SurfaceAuditLog(path).start(surface)
    replacement = tmp_path / "replacement.jsonl"
    original_read = os.read
    swapped = False

    def racing_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, count)
        if not swapped:
            swapped = True
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        return content

    monkeypatch.setattr("scitaste.generative_ui.audit.os.read", racing_read)

    with pytest.raises(AuditIntegrityError, match="identity changed"):
        SurfaceAuditLog(path).records()


def test_audit_reader_binds_every_record_to_expected_project(tmp_path) -> None:
    foreign_surface = build_paper_status_fixture()
    path = tmp_path / "foreign-audit.jsonl"
    SurfaceAuditLog(path).start(foreign_surface)

    with pytest.raises(AuditIntegrityError, match="another project"):
        SurfaceAuditLog(path, expected_project_id="different-project").records()

    new_path = tmp_path / "new-audit.jsonl"
    with pytest.raises(AuditIntegrityError, match="another project"):
        SurfaceAuditLog(
            new_path,
            expected_project_id="different-project",
        ).start(foreign_surface)
    assert not new_path.exists()


def test_audit_writer_rejects_symlinked_lock_without_touching_target(tmp_path) -> None:
    surface = build_paper_status_fixture()
    audit_root = tmp_path / "audits"
    audit_root.mkdir()
    path = audit_root / "surface-audit.jsonl"
    outside_lock = tmp_path / "outside-lock"
    outside_lock.write_text("outside sentinel\n", encoding="utf-8")
    (audit_root / ".surface-audit.jsonl.lock").symlink_to(outside_lock)

    with pytest.raises(AuditIntegrityError, match="storage is unavailable"):
        SurfaceAuditLog(path).start(surface)

    assert outside_lock.read_text(encoding="utf-8") == "outside sentinel\n"
    assert not path.exists()


def test_audit_writer_rejects_symlinked_directory_without_touching_target(tmp_path) -> None:
    surface = build_paper_status_fixture()
    outside = tmp_path / "outside"
    outside.mkdir()
    audit_root = tmp_path / "audits"
    audit_root.symlink_to(outside, target_is_directory=True)
    path = audit_root / "surface-audit.jsonl"

    with pytest.raises(AuditIntegrityError, match="symbolic link"):
        SurfaceAuditLog(path).start(surface)

    assert list(outside.iterdir()) == []


def test_audit_writer_cannot_escape_directory_replaced_during_write(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = build_paper_status_fixture()
    trusted_parent = tmp_path / "trusted"
    audit_root = trusted_parent / "audits"
    detached_root = trusted_parent / "detached-audits"
    outside_root = tmp_path / "outside"
    audit_root.mkdir(parents=True)
    outside_root.mkdir()
    path = audit_root / "surface-audit.jsonl"
    outside_target = outside_root / path.name
    outside_target.write_text("outside sentinel\n", encoding="utf-8")
    original_write = os.write
    swapped = False

    def racing_write(descriptor: int, content: bytes) -> int:
        nonlocal swapped
        if not swapped:
            swapped = True
            audit_root.rename(detached_root)
            audit_root.symlink_to(outside_root, target_is_directory=True)
        return original_write(descriptor, content)

    monkeypatch.setattr("scitaste.generative_ui.audit.os.write", racing_write)

    with pytest.raises(AuditIntegrityError, match="directory"):
        SurfaceAuditLog(path).start(surface)

    assert outside_target.read_text(encoding="utf-8") == "outside sentinel\n"
    assert not (detached_root / path.name).exists()
    assert not list(detached_root.glob("*.tmp"))


def test_audit_writer_rejects_lock_replaced_after_flock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = build_paper_status_fixture()
    audit_root = tmp_path / "audits"
    audit_root.mkdir()
    path = audit_root / "surface-audit.jsonl"
    outside = tmp_path / "outside-lock"
    outside.write_text("outside sentinel\n", encoding="utf-8")
    original_write = os.write
    swapped = False

    def racing_write(descriptor: int, content: bytes) -> int:
        nonlocal swapped
        if not swapped:
            swapped = True
            lock_path = audit_root / f".{path.name}.lock"
            lock_path.unlink()
            lock_path.symlink_to(outside)
        return original_write(descriptor, content)

    monkeypatch.setattr("scitaste.generative_ui.audit.os.write", racing_write)

    with pytest.raises(AuditIntegrityError, match="lock"):
        SurfaceAuditLog(path).start(surface)

    assert outside.read_text(encoding="utf-8") == "outside sentinel\n"
    assert not path.exists()


def test_audit_writer_rejects_temporary_entry_replaced_before_publish(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = build_paper_status_fixture()
    audit_root = tmp_path / "audits"
    audit_root.mkdir()
    path = audit_root / "surface-audit.jsonl"
    outside = tmp_path / "outside-temporary"
    outside.write_text("outside sentinel\n", encoding="utf-8")
    original_fsync = os.fsync
    swapped = False

    def racing_fsync(descriptor: int) -> None:
        nonlocal swapped
        original_fsync(descriptor)
        temporary = list(audit_root.glob(f".{path.name}.*.tmp"))
        if not swapped and temporary:
            swapped = True
            temporary[0].unlink()
            temporary[0].symlink_to(outside)

    monkeypatch.setattr("scitaste.generative_ui.audit.os.fsync", racing_fsync)

    with pytest.raises(AuditIntegrityError, match="temporary file"):
        SurfaceAuditLog(path).start(surface)

    assert outside.read_text(encoding="utf-8") == "outside sentinel\n"
    assert not path.exists()
    assert not list(audit_root.glob("*.tmp"))


def test_audit_writer_rolls_back_target_replaced_at_exchange(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = build_paper_status_fixture()
    path = tmp_path / "surface-audit.jsonl"
    log = SurfaceAuditLog(path)
    log.start(surface)
    original = path.read_bytes()
    displaced = tmp_path / "displaced-original.jsonl"
    attacker = b"attacker sentinel\n"
    event = make_surface_event(
        surface,
        event_id="target-race-event",
        action_id="inspect-paper",
    )
    receipt = SurfaceSession(surface).activate(event)
    original_renameat2 = audit_module._renameat2
    swapped = False

    def racing_renameat2(
        source_directory_fd: int,
        source: str,
        destination_directory_fd: int,
        destination: str,
        flags: int,
    ) -> None:
        nonlocal swapped
        if flags == audit_module._RENAME_EXCHANGE and not swapped:
            swapped = True
            path.rename(displaced)
            path.write_bytes(attacker)
        original_renameat2(
            source_directory_fd,
            source,
            destination_directory_fd,
            destination,
            flags,
        )

    monkeypatch.setattr(audit_module, "_renameat2", racing_renameat2)

    with pytest.raises(AuditIntegrityError, match="replaced audit"):
        log.append_interaction(event, receipt)

    assert path.read_bytes() == attacker
    assert displaced.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


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

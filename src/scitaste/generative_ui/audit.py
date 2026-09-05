"""Hash-chained persistence and semantic replay for surface interactions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scitaste.generative_ui.inspection import (
    ArtifactInspectionEvent,
    ArtifactInspectionReceipt,
    ArtifactUnavailableError,
    validate_inspection_binding,
)
from scitaste.generative_ui.interaction import (
    DuplicateEventError,
    ProposalReceipt,
    SurfaceEvent,
    SurfaceInteractionError,
    SurfaceSession,
)
from scitaste.generative_ui.models import SurfaceRevision, SurfaceSpec
from scitaste.generative_ui.safety import Sha256

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)


class AuditIntegrityError(ValueError):
    """The audit stream is corrupt or cannot be replayed consistently."""


class SurfaceOpenedAudit(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal["surface_opened"] = "surface_opened"
    surface: SurfaceSpec


class SurfaceRevisedAudit(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal["surface_revised"] = "surface_revised"
    revision: SurfaceRevision


class ProposalIssuedAudit(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal["proposal_issued"] = "proposal_issued"
    event: SurfaceEvent
    receipt: ProposalReceipt

    @model_validator(mode="after")
    def event_matches_receipt(self) -> ProposalIssuedAudit:
        expected = {
            "event_id": self.event.event_id,
            "event_fingerprint": self.event.fingerprint,
            "project_id": self.event.project_id,
            "surface_id": self.event.surface_id,
            "surface_revision": self.event.surface_revision,
            "surface_fingerprint": self.event.surface_fingerprint,
            "snapshot_revision": self.event.snapshot_revision,
            "snapshot_sha256": self.event.snapshot_sha256,
            "action_id": self.event.action_id,
        }
        actual = {key: getattr(self.receipt, key) for key in expected}
        mismatched = sorted(key for key in expected if expected[key] != actual[key])
        if mismatched:
            raise ValueError(f"proposal receipt does not match its event: {mismatched}")
        return self


class ArtifactInspectedAudit(BaseModel):
    """One completed read-only inspection bound to the opened surface."""

    model_config = _MODEL_CONFIG

    kind: Literal["artifact_inspected"] = "artifact_inspected"
    event: ArtifactInspectionEvent
    receipt: ArtifactInspectionReceipt

    @model_validator(mode="after")
    def event_matches_receipt(self) -> ArtifactInspectedAudit:
        expected = {
            "event_id": self.event.event_id,
            "event_fingerprint": self.event.fingerprint,
            "project_id": self.event.project_id,
            "surface_id": self.event.surface_id,
            "surface_revision": self.event.surface_revision,
            "surface_fingerprint": self.event.surface_fingerprint,
            "snapshot_revision": self.event.snapshot_revision,
            "snapshot_sha256": self.event.snapshot_sha256,
            "artifact_ref_id": self.event.artifact_ref_id,
        }
        actual = {key: getattr(self.receipt, key) for key in expected}
        if expected != actual:
            raise ValueError("artifact inspection receipt does not match its event")
        return self


AuditPayload = Annotated[
    SurfaceOpenedAudit | SurfaceRevisedAudit | ProposalIssuedAudit | ArtifactInspectedAudit,
    Field(discriminator="kind"),
]


class SurfaceAuditRecord(BaseModel):
    """One self-hashed record whose predecessor hash closes the audit chain."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=0)
    previous_record_sha256: Sha256 | None
    payload: AuditPayload
    record_sha256: Sha256

    @model_validator(mode="after")
    def self_hash_is_valid(self) -> SurfaceAuditRecord:
        expected = _record_digest(
            sequence=self.sequence,
            previous_record_sha256=self.previous_record_sha256,
            payload=self.payload,
        )
        if self.record_sha256 != expected:
            raise ValueError("surface audit record hash mismatch")
        return self


class SurfaceAuditLog:
    """Atomic JSONL audit storage guarded across threads and local processes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._thread_lock = RLock()

    def start(self, surface: SurfaceSpec) -> SurfaceAuditRecord:
        """Create a new audit stream rooted at a complete validated surface."""

        with self._locked(exclusive=True):
            if self.path.exists():
                raise FileExistsError(f"surface audit log already exists: {self.path}")
            record = _new_record(
                sequence=0,
                previous_record_sha256=None,
                payload=SurfaceOpenedAudit(surface=surface),
            )
            self._atomic_write([record])
            return record

    def append_revision(self, revision: SurfaceRevision) -> SurfaceAuditRecord:
        """Validate a revision against replayed state before extending the chain."""

        with self._locked(exclusive=True):
            records = self._load_verified()
            session = _replay(records)
            try:
                session.replace(revision)
            except SurfaceInteractionError as exc:
                raise AuditIntegrityError(f"surface revision cannot be replayed: {exc}") from exc
            record = _new_record(
                sequence=len(records),
                previous_record_sha256=records[-1].record_sha256,
                payload=SurfaceRevisedAudit(revision=revision),
            )
            self._atomic_write([*records, record])
            return record

    def append_interaction(
        self,
        event: SurfaceEvent,
        receipt: ProposalReceipt,
    ) -> SurfaceAuditRecord:
        """Persist only a receipt reproduced from the current server-owned surface."""

        try:
            payload = ProposalIssuedAudit(event=event, receipt=receipt)
        except ValidationError as exc:
            raise AuditIntegrityError("proposal receipt and event identities differ") from exc
        with self._locked(exclusive=True):
            records = self._load_verified()
            session = _replay(records)
            if event.event_id in _recorded_event_ids(records):
                raise AuditIntegrityError(
                    "surface event cannot be replayed: duplicate event_id"
                ) from DuplicateEventError("event_id was already accepted")
            try:
                replayed = session.activate(event)
            except SurfaceInteractionError as exc:
                raise AuditIntegrityError(f"surface event cannot be replayed: {exc}") from exc
            if replayed != receipt:
                raise AuditIntegrityError(
                    "proposal receipt differs from the server-owned surface action"
                )
            record = _new_record(
                sequence=len(records),
                previous_record_sha256=records[-1].record_sha256,
                payload=payload,
            )
            self._atomic_write([*records, record])
            return record

    def append_inspection(
        self,
        event: ArtifactInspectionEvent,
        receipt: ArtifactInspectionReceipt,
    ) -> SurfaceAuditRecord:
        """Append a reproduced read-only inspection to the shared event chain."""

        try:
            payload = ArtifactInspectedAudit(event=event, receipt=receipt)
        except ValidationError as exc:
            raise AuditIntegrityError("inspection receipt and event identities differ") from exc
        with self._locked(exclusive=True):
            records = self._load_verified()
            session = _replay(records)
            if event.event_id in _recorded_event_ids(records):
                raise AuditIntegrityError(
                    "surface event cannot be replayed: duplicate event_id"
                ) from DuplicateEventError("event_id was already accepted")
            try:
                validate_inspection_binding(session.surface, event, receipt)
            except ArtifactUnavailableError as exc:
                raise AuditIntegrityError(f"artifact inspection cannot be replayed: {exc}") from exc
            record = _new_record(
                sequence=len(records),
                previous_record_sha256=records[-1].record_sha256,
                payload=payload,
            )
            self._atomic_write([*records, record])
            return record

    def records(self) -> list[SurfaceAuditRecord]:
        with self._locked(exclusive=False):
            return self._load_verified()

    def replay_session(self) -> SurfaceSession:
        """Reconstruct the current surface and accepted-event set from verified records."""

        with self._locked(exclusive=False):
            return _replay(self._load_verified())

    @contextmanager
    def _locked(self, *, exclusive: bool) -> Iterator[None]:
        with self._thread_lock:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+", encoding="utf-8") as handle:
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(handle.fileno(), operation)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_verified(self) -> list[SurfaceAuditRecord]:
        if not self.path.is_file():
            raise FileNotFoundError(f"surface audit log does not exist: {self.path}")
        text = self.path.read_text(encoding="utf-8")
        if not text or not text.endswith("\n"):
            raise AuditIntegrityError("surface audit log is empty or truncated")
        lines = text.splitlines()
        if any(not line.strip() for line in lines):
            raise AuditIntegrityError("surface audit log contains a blank record")
        records: list[SurfaceAuditRecord] = []
        for index, line in enumerate(lines):
            try:
                record = SurfaceAuditRecord.model_validate_json(line)
            except ValidationError as exc:
                raise AuditIntegrityError(f"invalid surface audit record {index}") from exc
            if record.sequence != index:
                raise AuditIntegrityError(f"surface audit sequence mismatch at record {index}")
            expected_previous = records[-1].record_sha256 if records else None
            if record.previous_record_sha256 != expected_previous:
                raise AuditIntegrityError(f"surface audit chain mismatch at record {index}")
            records.append(record)
        _replay(records)
        return records

    def _atomic_write(self, records: list[SurfaceAuditRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        content = "".join(record.model_dump_json() + "\n" for record in records)
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def _new_record(
    *,
    sequence: int,
    previous_record_sha256: str | None,
    payload: AuditPayload,
) -> SurfaceAuditRecord:
    return SurfaceAuditRecord(
        sequence=sequence,
        previous_record_sha256=previous_record_sha256,
        payload=payload,
        record_sha256=_record_digest(
            sequence=sequence,
            previous_record_sha256=previous_record_sha256,
            payload=payload,
        ),
    )


def _record_digest(
    *,
    sequence: int,
    previous_record_sha256: str | None,
    payload: AuditPayload,
) -> str:
    canonical = json.dumps(
        {
            "payload": payload.model_dump(mode="json"),
            "previous_record_sha256": previous_record_sha256,
            "schema_version": "1.0",
            "sequence": sequence,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _replay(records: list[SurfaceAuditRecord]) -> SurfaceSession:
    if not records or not isinstance(records[0].payload, SurfaceOpenedAudit):
        raise AuditIntegrityError("surface audit must begin with surface_opened")
    _recorded_event_ids(records)
    session = SurfaceSession(records[0].payload.surface)
    for record in records[1:]:
        payload = record.payload
        try:
            if isinstance(payload, SurfaceRevisedAudit):
                session.replace(payload.revision)
            elif isinstance(payload, ProposalIssuedAudit):
                receipt = session.activate(payload.event)
                if receipt != payload.receipt:
                    raise AuditIntegrityError(
                        f"proposal receipt mismatch at record {record.sequence}"
                    )
            elif isinstance(payload, ArtifactInspectedAudit):
                validate_inspection_binding(session.surface, payload.event, payload.receipt)
            else:
                raise AuditIntegrityError(
                    f"surface_opened may appear only at record zero, got {record.sequence}"
                )
        except (SurfaceInteractionError, ArtifactUnavailableError) as exc:
            raise AuditIntegrityError(
                f"surface audit semantic replay failed at record {record.sequence}: {exc}"
            ) from exc
    return session


def _recorded_event_ids(records: list[SurfaceAuditRecord]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        payload = record.payload
        if isinstance(payload, (ProposalIssuedAudit, ArtifactInspectedAudit)):
            if payload.event.event_id in ids:
                raise AuditIntegrityError("surface audit contains a duplicate event_id")
            ids.add(payload.event.event_id)
    return ids

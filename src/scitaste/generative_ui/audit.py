"""Hash-chained persistence and semantic replay for surface interactions."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
    ProposalController,
    ProposalControllerDecision,
    ProposalControllerRequest,
    ProposalReceipt,
    SurfaceEvent,
    SurfaceInteractionError,
    SurfaceSession,
)
from scitaste.generative_ui.models import SurfaceRevision, SurfaceSpec
from scitaste.generative_ui.safety import ProjectIdentifier, Sha256

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_AUDIT_BYTES = 8 * 1024 * 1024
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
_FileIdentity = tuple[int, int]


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


class ProposalControlledAudit(BaseModel):
    """One deterministic decision over a previously audited proposal."""

    model_config = _MODEL_CONFIG

    kind: Literal["proposal_controlled"] = "proposal_controlled"
    request: ProposalControllerRequest
    decision: ProposalControllerDecision

    @model_validator(mode="after")
    def request_matches_decision(self) -> ProposalControlledAudit:
        expected = {
            "controller_request_id": self.request.controller_request_id,
            "controller_request_fingerprint": self.request.fingerprint,
            "proposal_event_id": self.request.proposal_event_id,
            "requested_decision": self.request.requested_decision,
        }
        actual = {key: getattr(self.decision, key) for key in expected}
        if expected != actual:
            raise ValueError("controller decision does not match its request")
        return self


AuditPayload = Annotated[
    SurfaceOpenedAudit
    | SurfaceRevisedAudit
    | ProposalIssuedAudit
    | ArtifactInspectedAudit
    | ProposalControlledAudit,
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

    def __init__(
        self,
        path: str | Path,
        *,
        expected_project_id: ProjectIdentifier | None = None,
    ) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._expected_project_id = expected_project_id
        self._thread_lock = RLock()

    def start(self, surface: SurfaceSpec) -> SurfaceAuditRecord:
        """Create a new audit stream rooted at a complete validated surface."""

        if (
            self._expected_project_id is not None
            and surface.project_id != self._expected_project_id
        ):
            raise AuditIntegrityError("surface audit root belongs to another project")
        with self._locked(exclusive=True, create_directory=True) as storage:
            record = _new_record(
                sequence=0,
                previous_record_sha256=None,
                payload=SurfaceOpenedAudit(surface=surface),
            )
            self._atomic_write(storage, [record], expected_identity=None)
            return record

    def append_revision(self, revision: SurfaceRevision) -> SurfaceAuditRecord:
        """Validate a revision against replayed state before extending the chain."""

        with self._locked(exclusive=True) as storage:
            records, identity = self._load_verified(storage)
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
            self._atomic_write(storage, [*records, record], expected_identity=identity)
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
        with self._locked(exclusive=True) as storage:
            records, identity = self._load_verified(storage)
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
            self._atomic_write(storage, [*records, record], expected_identity=identity)
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
        with self._locked(exclusive=True) as storage:
            records, identity = self._load_verified(storage)
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
            self._atomic_write(storage, [*records, record], expected_identity=identity)
            return record

    def append_controller_decision(
        self,
        request: ProposalControllerRequest,
    ) -> SurfaceAuditRecord:
        """Reproduce and append one bounded controller decision exactly once."""

        request = ProposalControllerRequest.model_validate(request.model_dump(mode="json"))
        with self._locked(exclusive=True) as storage:
            records, identity = self._load_verified(storage)
            if request.controller_request_id in _recorded_controller_request_ids(records):
                raise AuditIntegrityError(
                    "controller request cannot be replayed: duplicate controller_request_id"
                ) from DuplicateEventError("controller_request_id was already accepted")
            if request.proposal_event_id in _controlled_proposal_event_ids(records):
                raise AuditIntegrityError(
                    "proposal already has a controller decision"
                ) from DuplicateEventError("proposal already has a controller decision")
            receipts = _issued_proposal_receipts(records)
            receipt = receipts.get(request.proposal_event_id)
            if receipt is None:
                raise AuditIntegrityError("controller request references an unknown proposal")
            session = _replay(records)
            try:
                decision = ProposalController(session.surface).decide(
                    receipt,
                    request,
                    current_snapshot=session.surface.snapshot,
                )
            except SurfaceInteractionError as exc:
                raise AuditIntegrityError(f"controller request cannot be replayed: {exc}") from exc
            record = _new_record(
                sequence=len(records),
                previous_record_sha256=records[-1].record_sha256,
                payload=ProposalControlledAudit(request=request, decision=decision),
            )
            self._atomic_write(storage, [*records, record], expected_identity=identity)
            return record

    def records(self) -> list[SurfaceAuditRecord]:
        with self._locked(exclusive=False) as storage:
            records, _ = self._load_verified(storage)
            return records

    def records_with_digest(self) -> tuple[list[SurfaceAuditRecord], str]:
        """Return records and the digest of the exact bounded bytes that were replayed."""

        with self._locked(exclusive=False) as storage:
            storage.assert_bound()
            content, _ = _read_audit_bytes(storage.directory_fd, self.path.name)
            storage.assert_bound()
            return self._parse_verified(content), hashlib.sha256(content).hexdigest()

    def replay_session(self) -> SurfaceSession:
        """Reconstruct the current surface and accepted-event set from verified records."""

        with self._locked(exclusive=False) as storage:
            records, _ = self._load_verified(storage)
            return _replay(records)

    @contextmanager
    def _locked(
        self,
        *,
        exclusive: bool,
        create_directory: bool = False,
    ) -> Iterator[_BoundAuditStorage]:
        with self._thread_lock:
            directory_fd = _open_directory_tree(self.path.parent, create=create_directory)
            lock_fd = -1
            locked = False
            yielded = False
            try:
                _assert_directory_identity(self.path.parent, directory_fd)
                lock_fd = os.open(
                    self._lock_path.name,
                    os.O_RDWR
                    | os.O_APPEND
                    | os.O_CREAT
                    | getattr(os, "O_NONBLOCK", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                _assert_regular_entry(directory_fd, self._lock_path.name, lock_fd, "lock")
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(lock_fd, operation)
                locked = True
                storage = _BoundAuditStorage(
                    directory_path=self.path.parent,
                    directory_fd=directory_fd,
                    lock_name=self._lock_path.name,
                    lock_fd=lock_fd,
                )
                storage.assert_bound()
                yielded = True
                yield storage
                storage.assert_bound()
            except AuditIntegrityError:
                raise
            except OSError as exc:
                if yielded:
                    raise
                raise AuditIntegrityError("surface audit storage is unavailable") from exc
            finally:
                if locked:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                if lock_fd >= 0:
                    os.close(lock_fd)
                os.close(directory_fd)

    def _load_verified(
        self,
        storage: _BoundAuditStorage,
    ) -> tuple[list[SurfaceAuditRecord], _FileIdentity]:
        storage.assert_bound()
        content, identity = _read_audit_bytes(storage.directory_fd, self.path.name)
        storage.assert_bound()
        return self._parse_verified(content), identity

    def _parse_verified(self, content: bytes) -> list[SurfaceAuditRecord]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuditIntegrityError("surface audit log is not valid UTF-8") from exc
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
        _validate_audit_project(records, self._expected_project_id)
        return records

    def _atomic_write(
        self,
        storage: _BoundAuditStorage,
        records: list[SurfaceAuditRecord],
        *,
        expected_identity: _FileIdentity | None,
    ) -> None:
        temporary_name = f".{self.path.name}.{uuid4().hex}.tmp"
        content = "".join(record.model_dump_json() + "\n" for record in records)
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_AUDIT_BYTES:
            raise AuditIntegrityError("surface audit log exceeds its fixed byte limit")
        descriptor = -1
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=storage.directory_fd,
            )
            written = 0
            while written < len(encoded):
                count = os.write(descriptor, encoded[written:])
                if count <= 0:  # pragma: no cover - guarded OS contract
                    raise OSError("audit write made no progress")
                written += count
            os.fsync(descriptor)
            _assert_regular_entry(
                storage.directory_fd,
                temporary_name,
                descriptor,
                "temporary file",
            )
            storage.assert_bound()
            _assert_expected_entry(storage.directory_fd, self.path.name, expected_identity)
            flag = _RENAME_NOREPLACE if expected_identity is None else _RENAME_EXCHANGE
            _renameat2(
                storage.directory_fd,
                temporary_name,
                storage.directory_fd,
                self.path.name,
                flag,
            )
            try:
                _assert_named_identity(
                    storage.directory_fd,
                    self.path.name,
                    _descriptor_identity(descriptor),
                    "published audit",
                )
                if expected_identity is not None:
                    _assert_named_identity(
                        storage.directory_fd,
                        temporary_name,
                        expected_identity,
                        "replaced audit",
                    )
                storage.assert_bound()
            except Exception:
                if expected_identity is not None:
                    _rollback_exchange(storage.directory_fd, temporary_name, self.path.name)
                else:
                    _rollback_new_publication(
                        storage.directory_fd,
                        self.path.name,
                        _descriptor_identity(descriptor),
                    )
                raise
            if expected_identity is not None:
                os.unlink(temporary_name, dir_fd=storage.directory_fd)
            os.fsync(storage.directory_fd)
            storage.assert_bound()
        except OSError as exc:
            if expected_identity is None and exc.errno == errno.EEXIST:
                raise FileExistsError(f"surface audit log already exists: {self.path}") from exc
            raise AuditIntegrityError("surface audit publication failed closed") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=storage.directory_fd)
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class _BoundAuditStorage:
    directory_path: Path
    directory_fd: int
    lock_name: str
    lock_fd: int

    def assert_bound(self) -> None:
        _assert_regular_entry(self.directory_fd, self.lock_name, self.lock_fd, "lock")
        _assert_directory_identity(self.directory_path, self.directory_fd)


def _read_audit_bytes(directory_fd: int, name: str) -> tuple[bytes, _FileIdentity]:
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise FileNotFoundError("surface audit log does not exist") from None
    if stat.S_ISLNK(entry.st_mode):
        raise AuditIntegrityError("surface audit log must not be a symbolic link")
    if not stat.S_ISREG(entry.st_mode):
        raise AuditIntegrityError("surface audit log must be a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        raise FileNotFoundError("surface audit log does not exist") from None
    except OSError as exc:
        raise AuditIntegrityError("surface audit log is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuditIntegrityError("surface audit log must be a regular file")
        if before.st_size > _MAX_AUDIT_BYTES:
            raise AuditIntegrityError("surface audit log exceeds its fixed byte limit")
        chunks: list[bytes] = []
        remaining = _MAX_AUDIT_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        path_metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = (before.st_dev, before.st_ino)
        if identity != (after.st_dev, after.st_ino) or identity != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise AuditIntegrityError("surface audit log identity changed while reading")
        if (
            len(content) > _MAX_AUDIT_BYTES
            or before.st_size != after.st_size
            or len(content) != after.st_size
        ):
            raise AuditIntegrityError("surface audit log size changed or exceeds its limit")
        return content, identity
    except OSError as exc:
        raise AuditIntegrityError("surface audit log changed while reading") from exc
    finally:
        os.close(descriptor)


def _open_directory_tree(path: Path, *, create: bool) -> int:
    """Open every absolute path component without following symbolic links."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except OSError as exc:
        os.close(current)
        raise AuditIntegrityError(
            "surface audit directory is unavailable or contains a symbolic link"
        ) from exc


def _assert_directory_identity(path: Path, expected_fd: int) -> None:
    actual_fd = -1
    try:
        actual_fd = _open_directory_tree(path, create=False)
        expected = os.fstat(expected_fd)
        actual = os.fstat(actual_fd)
        if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
            raise AuditIntegrityError("surface audit directory identity changed")
    except AuditIntegrityError:
        raise
    except OSError as exc:
        raise AuditIntegrityError("surface audit directory identity changed") from exc
    finally:
        if actual_fd >= 0:
            os.close(actual_fd)


def _assert_regular_entry(directory_fd: int, name: str, descriptor: int, kind: str) -> None:
    opened = os.fstat(descriptor)
    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode):
        raise AuditIntegrityError(f"surface audit {kind} must be a regular file")
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise AuditIntegrityError(f"surface audit {kind} identity changed")


def _descriptor_identity(descriptor: int) -> _FileIdentity:
    metadata = os.fstat(descriptor)
    return metadata.st_dev, metadata.st_ino


def _named_identity(directory_fd: int, name: str) -> _FileIdentity | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise AuditIntegrityError("surface audit entry must be a regular file")
    return metadata.st_dev, metadata.st_ino


def _assert_named_identity(
    directory_fd: int,
    name: str,
    expected: _FileIdentity,
    kind: str,
) -> None:
    if _named_identity(directory_fd, name) != expected:
        raise AuditIntegrityError(f"surface audit {kind} identity changed")


def _assert_expected_entry(
    directory_fd: int,
    name: str,
    expected: _FileIdentity | None,
) -> None:
    actual = _named_identity(directory_fd, name)
    if expected is None:
        if actual is not None:
            raise FileExistsError(errno.EEXIST, "surface audit log already exists", name)
    elif actual != expected:
        raise AuditIntegrityError("surface audit target identity changed")


def _renameat2(
    source_directory_fd: int,
    source: str,
    destination_directory_fd: int,
    destination: str,
    flags: int,
) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "atomic audit publication is unavailable") from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renameat2(
        source_directory_fd,
        os.fsencode(source),
        destination_directory_fd,
        os.fsencode(destination),
        flags,
    )
    if result != 0:
        error = ctypes.get_errno() or errno.EIO
        raise OSError(error, os.strerror(error))


def _rollback_exchange(directory_fd: int, temporary_name: str, target_name: str) -> None:
    try:
        _renameat2(
            directory_fd,
            temporary_name,
            directory_fd,
            target_name,
            _RENAME_EXCHANGE,
        )
    except OSError as exc:
        raise AuditIntegrityError("surface audit exchange rollback failed closed") from exc


def _rollback_new_publication(
    directory_fd: int,
    target_name: str,
    published_identity: _FileIdentity,
) -> None:
    if _named_identity(directory_fd, target_name) != published_identity:
        raise AuditIntegrityError("surface audit no-replace rollback failed closed")
    try:
        os.unlink(target_name, dir_fd=directory_fd)
    except OSError as exc:
        raise AuditIntegrityError("surface audit no-replace rollback failed closed") from exc


def _validate_audit_project(
    records: list[SurfaceAuditRecord],
    expected_project_id: str | None,
) -> None:
    if expected_project_id is None:
        return
    for record in records:
        payload = record.payload
        if isinstance(payload, SurfaceOpenedAudit):
            project_ids = (payload.surface.project_id,)
        elif isinstance(payload, SurfaceRevisedAudit):
            project_ids = (payload.revision.surface.project_id,)
        elif isinstance(payload, (ProposalIssuedAudit, ArtifactInspectedAudit)):
            project_ids = (payload.event.project_id, payload.receipt.project_id)
        elif isinstance(payload, ProposalControlledAudit):
            project_ids = (payload.decision.project_id,)
        else:  # pragma: no cover - discriminated audit models are closed
            raise AuditIntegrityError("surface audit contains an unsupported record")
        if any(project_id != expected_project_id for project_id in project_ids):
            raise AuditIntegrityError("surface audit record belongs to another project")


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
    issued: dict[str, ProposalReceipt] = {}
    controller_request_ids: set[str] = set()
    controlled_event_ids: set[str] = set()
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
                issued[receipt.event_id] = receipt
            elif isinstance(payload, ArtifactInspectedAudit):
                validate_inspection_binding(session.surface, payload.event, payload.receipt)
            elif isinstance(payload, ProposalControlledAudit):
                if payload.request.controller_request_id in controller_request_ids:
                    raise AuditIntegrityError("surface audit contains a duplicate controller ID")
                if payload.request.proposal_event_id in controlled_event_ids:
                    raise AuditIntegrityError("surface audit controls one proposal more than once")
                receipt = issued.get(payload.request.proposal_event_id)
                if receipt is None:
                    raise AuditIntegrityError(
                        f"controller decision lacks a prior proposal at record {record.sequence}"
                    )
                decision = ProposalController(session.surface).decide(
                    receipt,
                    payload.request,
                    current_snapshot=session.surface.snapshot,
                )
                if decision != payload.decision:
                    raise AuditIntegrityError(
                        f"controller decision mismatch at record {record.sequence}"
                    )
                controller_request_ids.add(payload.request.controller_request_id)
                controlled_event_ids.add(payload.request.proposal_event_id)
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


def _issued_proposal_receipts(
    records: list[SurfaceAuditRecord],
) -> dict[str, ProposalReceipt]:
    return {
        record.payload.receipt.event_id: record.payload.receipt
        for record in records
        if isinstance(record.payload, ProposalIssuedAudit)
    }


def _recorded_controller_request_ids(records: list[SurfaceAuditRecord]) -> set[str]:
    return {
        record.payload.request.controller_request_id
        for record in records
        if isinstance(record.payload, ProposalControlledAudit)
    }


def _controlled_proposal_event_ids(records: list[SurfaceAuditRecord]) -> set[str]:
    return {
        record.payload.request.proposal_event_id
        for record in records
        if isinstance(record.payload, ProposalControlledAudit)
    }

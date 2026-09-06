"""Append-only evidence for one externally observable executor call."""

from __future__ import annotations

import hashlib
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.base import ExecutionStatus
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id


class ExternalCallPhase(StrEnum):
    """Durable phases around a call that SciTaste must never guess about."""

    PREPARED = "prepared"
    CALL_STARTED = "call_started"
    RESULT_PUBLISHED = "result_published"


_PHASE_FILES = {
    ExternalCallPhase.PREPARED: "prepared.json",
    ExternalCallPhase.CALL_STARTED: "call_started.json",
    ExternalCallPhase.RESULT_PUBLISHED: "result_published.json",
}


class ExternalCallPhaseReceipt(BaseModel):
    """One immutable, self-hashed entry in an external-call phase chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    operation: Literal["selected_action", "bootstrap"]
    external_call_attempt: int = Field(ge=1)
    phase: ExternalCallPhase
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pre_call_work_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    executor_result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_work_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_id: str | None = None
    execution_status: ExecutionStatus | None = None
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @field_validator("result_id")
    @classmethod
    def result_id_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("external call result_id cannot be blank")
        return value

    @classmethod
    def create(cls, **payload: Any) -> ExternalCallPhaseReceipt:
        canonical = {key: value for key, value in payload.items() if value is not None}
        return cls.model_validate({**canonical, "receipt_sha256": content_sha256(canonical)})

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> ExternalCallPhaseReceipt:
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"}, exclude_none=True)
        )
        if self.receipt_sha256 != expected:
            raise ValueError("external call phase receipt hash mismatch")
        result_fields = (
            self.executor_result_sha256,
            self.result_work_tree_sha256,
            self.result_id,
            self.execution_status,
        )
        if self.phase is ExternalCallPhase.PREPARED:
            if self.previous_receipt_sha256 is not None or any(
                value is not None for value in result_fields
            ):
                raise ValueError("prepared call receipt cannot have predecessor or result")
        elif self.phase is ExternalCallPhase.CALL_STARTED:
            if self.previous_receipt_sha256 is None or any(
                value is not None for value in result_fields
            ):
                raise ValueError("call-started receipt requires only a predecessor")
        elif self.previous_receipt_sha256 is None or any(value is None for value in result_fields):
            raise ValueError("result-published receipt requires predecessor and result")
        return self


class ExternalCallProtocol:
    """Publish and verify a single append-only external-call phase chain."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load(self, *, required: bool = False) -> tuple[ExternalCallPhaseReceipt, ...]:
        if not self.root.exists() and not self.root.is_symlink():
            if required:
                raise ValueError("external call phase protocol is missing")
            return ()
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("external call phase protocol must be an owned directory")
        allowed = set(_PHASE_FILES.values())
        entries = list(self.root.iterdir())
        if any(
            entry.name not in allowed or entry.is_symlink() or not entry.is_file()
            for entry in entries
        ):
            raise ValueError("external call phase protocol contains an unexpected entry")

        receipts: list[ExternalCallPhaseReceipt] = []
        missing_seen = False
        for phase, filename in _PHASE_FILES.items():
            path = self.root / filename
            if not path.exists() and not path.is_symlink():
                missing_seen = True
                continue
            if missing_seen:
                raise ValueError("external call phase protocol is not a contiguous chain")
            if path.is_symlink() or not path.is_file():
                raise ValueError("external call phase receipt must be a regular owned file")
            try:
                receipt = ExternalCallPhaseReceipt.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise ValueError("invalid external call phase receipt") from exc
            if receipt.phase is not phase:
                raise ValueError("external call phase filename and payload disagree")
            receipts.append(receipt)
        if required and not receipts:
            raise ValueError("external call phase protocol is empty")
        self._validate_chain(receipts)
        return tuple(receipts)

    def publish_prepared(
        self,
        *,
        project_id: str,
        run_id: str,
        operation: Literal["selected_action", "bootstrap"],
        external_call_attempt: int,
        request_sha256: str,
        call_spec_sha256: str,
        pre_call_work_sha256: str,
    ) -> ExternalCallPhaseReceipt:
        receipt = ExternalCallPhaseReceipt.create(
            schema_version="1.0",
            project_id=project_id,
            run_id=run_id,
            operation=operation,
            external_call_attempt=external_call_attempt,
            phase=ExternalCallPhase.PREPARED,
            request_sha256=request_sha256,
            call_spec_sha256=call_spec_sha256,
            pre_call_work_sha256=pre_call_work_sha256,
        )
        return self._publish(receipt, expected_count=0)

    def publish_call_started(self) -> ExternalCallPhaseReceipt:
        chain = self.load(required=True)
        if len(chain) != 1 or chain[-1].phase is not ExternalCallPhase.PREPARED:
            raise ValueError("external call can start only from the prepared phase")
        prepared = chain[0]
        receipt = ExternalCallPhaseReceipt.create(
            **self._identity(prepared),
            phase=ExternalCallPhase.CALL_STARTED,
            previous_receipt_sha256=prepared.receipt_sha256,
        )
        return self._publish(receipt, expected_count=1)

    def publish_result(
        self,
        *,
        executor_result_sha256: str,
        result_work_tree_sha256: str,
        result_id: str,
        execution_status: ExecutionStatus,
    ) -> ExternalCallPhaseReceipt:
        chain = self.load(required=True)
        if len(chain) != 2 or chain[-1].phase is not ExternalCallPhase.CALL_STARTED:
            raise ValueError("external result can be published only after call start")
        started = chain[-1]
        receipt = ExternalCallPhaseReceipt.create(
            **self._identity(started),
            phase=ExternalCallPhase.RESULT_PUBLISHED,
            previous_receipt_sha256=started.receipt_sha256,
            executor_result_sha256=executor_result_sha256,
            result_work_tree_sha256=result_work_tree_sha256,
            result_id=result_id,
            execution_status=execution_status,
        )
        return self._publish(receipt, expected_count=2)

    def require_prepared(
        self,
        *,
        project_id: str,
        run_id: str,
        operation: Literal["selected_action", "bootstrap"],
        external_call_attempt: int,
        request_sha256: str,
        call_spec_sha256: str,
        pre_call_work_sha256: str,
    ) -> ExternalCallPhaseReceipt:
        chain = self.load(required=True)
        if len(chain) != 1:
            raise ValueError("external call is no longer in the prepared phase")
        prepared = chain[0]
        expected = {
            "schema_version": "1.0",
            "project_id": project_id,
            "run_id": run_id,
            "operation": operation,
            "external_call_attempt": external_call_attempt,
            "request_sha256": request_sha256,
            "call_spec_sha256": call_spec_sha256,
            "pre_call_work_sha256": pre_call_work_sha256,
        }
        if self._identity(prepared) != expected:
            raise ValueError("prepared external call identity drift")
        return prepared

    def require_result(
        self,
        *,
        project_id: str,
        run_id: str,
        operation: Literal["selected_action", "bootstrap"],
        external_call_attempt: int,
        request_sha256: str,
        call_spec_sha256: str,
        pre_call_work_sha256: str,
        result_path: str | Path,
        result_work_tree_sha256: str,
        result_id: str,
        execution_status: ExecutionStatus,
        allow_unjournaled_publication: bool = False,
    ) -> ExternalCallPhaseReceipt:
        """Verify a result entry, or finish its journal after result fsync.

        A process may die after the immutable result file is linked but before the
        final phase receipt is linked. The caller must independently validate the
        result before opting into ``allow_unjournaled_publication``.
        """

        chain = self.load(required=True)
        expected_identity = {
            "schema_version": "1.0",
            "project_id": project_id,
            "run_id": run_id,
            "operation": operation,
            "external_call_attempt": external_call_attempt,
            "request_sha256": request_sha256,
            "call_spec_sha256": call_spec_sha256,
            "pre_call_work_sha256": pre_call_work_sha256,
        }
        result_digest = file_sha256(result_path)
        if len(chain) == 2 and allow_unjournaled_publication:
            if (
                chain[-1].phase is not ExternalCallPhase.CALL_STARTED
                or self._identity(chain[-1]) != expected_identity
            ):
                raise ValueError("unjournaled external result identity drift")
            return self.publish_result(
                executor_result_sha256=result_digest,
                result_work_tree_sha256=result_work_tree_sha256,
                result_id=result_id,
                execution_status=execution_status,
            )
        if len(chain) != 3:
            raise ValueError("external call has no durable result-published phase")
        published = chain[-1]
        if (
            self._identity(published) != expected_identity
            or published.executor_result_sha256 != result_digest
            or published.result_work_tree_sha256 != result_work_tree_sha256
            or published.result_id != result_id
            or published.execution_status is not execution_status
        ):
            raise ValueError("published external result identity drift")
        return published

    def _publish(
        self,
        receipt: ExternalCallPhaseReceipt,
        *,
        expected_count: int,
    ) -> ExternalCallPhaseReceipt:
        chain = self.load(required=False)
        if len(chain) != expected_count:
            raise ValueError("external call phase transition raced or was repeated")
        created = not self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("external call phase protocol must be an owned directory")
        if created:
            _fsync_directory(self.root.parent)
        _write_model_exclusive(self.root / _PHASE_FILES[receipt.phase], receipt)
        _fsync_directory(self.root)
        observed = self.load(required=True)
        if observed[-1] != receipt:
            raise ValueError("external call phase receipt changed during publication")
        return receipt

    @staticmethod
    def _identity(receipt: ExternalCallPhaseReceipt) -> dict[str, object]:
        return {
            "schema_version": receipt.schema_version,
            "project_id": receipt.project_id,
            "run_id": receipt.run_id,
            "operation": receipt.operation,
            "external_call_attempt": receipt.external_call_attempt,
            "request_sha256": receipt.request_sha256,
            "call_spec_sha256": receipt.call_spec_sha256,
            "pre_call_work_sha256": receipt.pre_call_work_sha256,
        }

    @classmethod
    def _validate_chain(cls, receipts: list[ExternalCallPhaseReceipt]) -> None:
        for index, receipt in enumerate(receipts):
            if index == 0:
                continue
            predecessor = receipts[index - 1]
            if (
                cls._identity(receipt) != cls._identity(predecessor)
                or receipt.previous_receipt_sha256 != predecessor.receipt_sha256
            ):
                raise ValueError("external call phase chain binding drift")


def tree_fingerprint(path: str | Path) -> str:
    """Hash every regular file in a tree while rejecting symlink ambiguity."""

    supplied = Path(path)
    if supplied.is_symlink():
        raise ValueError("external call work tree must be a regular directory")
    if not supplied.exists():
        return content_sha256({"tree_state": "absent"})
    if not supplied.is_dir():
        raise ValueError("external call work tree must be a regular directory")
    root = supplied.resolve(strict=True)
    files: dict[str, str] = {}
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("external call work tree cannot contain symlinks")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("external call work tree contains a non-regular entry")
        files[candidate.relative_to(root).as_posix()] = file_sha256(candidate)
    return content_sha256(files)


def file_sha256(path: str | Path) -> str:
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_file():
        raise ValueError("external call evidence must be a regular file")
    digest = hashlib.sha256()
    with supplied.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_model_exclusive(path: Path, model: BaseModel) -> None:
    rendered = model.model_dump_json(indent=2) + "\n"
    temporary_parent = path.parent.parent
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.parent.name}-{path.name}.",
        dir=temporary_parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except OSError as exc:
            raise ValueError("external call phase receipt already exists or is unsafe") from exc
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(temporary_parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ExternalCallPhase",
    "ExternalCallPhaseReceipt",
    "ExternalCallProtocol",
    "file_sha256",
    "tree_fingerprint",
]

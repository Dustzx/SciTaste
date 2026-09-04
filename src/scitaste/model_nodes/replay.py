"""Exact record/replay for structured model-node responses."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse


class StructuredReplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: StructuredModelRequest
    response: StructuredModelResponse


class StructuredReplayMissError(KeyError):
    """Raised when no response exists for the exact structured request."""


class RecordingStructuredBackend:
    """Durably append delegate responses before deterministic policy evaluation."""

    def __init__(self, delegate: StructuredModelBackend, path: str | Path) -> None:
        self.delegate = delegate
        self.path = Path(path)
        self.name = delegate.name
        self.model = delegate.model

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        audited_request = _copy_request(request)
        response = _copy_response(self.delegate.complete(request))
        record = StructuredReplayRecord(request=audited_request, response=response)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json(exclude={"request": {"fingerprint"}}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return response


class ReplayStructuredBackend:
    """Replay only byte-identical requests under one pinned backend/model identity."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records, identity = self._load()
        self.name, self.model = identity

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        try:
            response = self._records[request.fingerprint]
        except KeyError as exc:
            raise StructuredReplayMissError(
                f"no exact structured replay for {request.request_id!r} "
                f"({request.fingerprint[:12]})"
            ) from exc
        values = response.model_dump(mode="python")
        values["cached"] = True
        return StructuredModelResponse.model_validate(values, strict=True)

    def _load(self) -> tuple[dict[str, StructuredModelResponse], tuple[str, str]]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        records: dict[str, StructuredModelResponse] = {}
        identities: set[tuple[str, str]] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = StructuredReplayRecord.model_validate_json(line, strict=True)
            except ValueError as exc:
                raise ValueError(f"invalid structured replay line {line_number}") from exc
            fingerprint = record.request.fingerprint
            existing = records.get(fingerprint)
            if existing is not None and existing != record.response:
                raise ValueError(f"conflicting structured replay on line {line_number}")
            records[fingerprint] = record.response
            identities.add((record.request.expected_backend, record.request.expected_model))
        if not records:
            raise ValueError("structured replay file contains no records")
        if len(identities) != 1:
            raise ValueError("structured replay file mixes backend or model identities")
        return records, next(iter(identities))


def _copy_request(request: StructuredModelRequest) -> StructuredModelRequest:
    values = request.model_dump(mode="python", exclude={"fingerprint"})
    return StructuredModelRequest.model_validate(values, strict=True)


def _copy_response(response: StructuredModelResponse) -> StructuredModelResponse:
    validated = StructuredModelResponse.model_validate(response, strict=True)
    return StructuredModelResponse.model_validate(
        validated.model_dump(mode="python"),
        strict=True,
    )

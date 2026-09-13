"""Record and replay exact model judgments without API access."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from scitaste.backends.base import PreferenceBackend, PreferenceRequest, PreferenceResponse


class ReplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: PreferenceRequest
    response: PreferenceResponse
    recorded_at: datetime | None = None

    @model_validator(mode="after")
    def timestamp_is_aware_when_present(self) -> ReplayRecord:
        if self.recorded_at is not None and self.recorded_at.utcoffset() is None:
            raise ValueError("replay recording timestamp must include a timezone")
        return self


class ReplayMissError(KeyError):
    """Raised when an exact request was not captured in the replay fixture."""


class ReplayBackend:
    name = "replay"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records = self._load()

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        try:
            response = self._records[request.fingerprint]
        except KeyError as exc:
            raise ReplayMissError(
                f"no exact replay for request {request.request_id!r} ({request.fingerprint[:12]})"
            ) from exc
        return response.model_copy(update={"cached": True})

    def _load(self) -> dict[str, PreferenceResponse]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        records: dict[str, PreferenceResponse] = {}
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = ReplayRecord.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(f"invalid replay line {line_number}") from exc
            if record.request.fingerprint != record.response.request_fingerprint:
                raise ValueError(f"replay fingerprint mismatch on line {line_number}")
            records[record.request.fingerprint] = record.response
        return records


class RecordingBackend:
    """Append delegate responses so later runs can be fully offline and exact."""

    name = "recording"

    def __init__(self, delegate: PreferenceBackend, path: str | Path) -> None:
        self.delegate = delegate
        self.path = Path(path)

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        response = self.delegate.rank(request)
        if response.request_fingerprint != request.fingerprint:
            raise ValueError("delegate returned a response for a different request")
        record = ReplayRecord(
            request=request,
            response=response,
            recorded_at=datetime.now(UTC),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json(exclude={"request": {"fingerprint"}}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return response

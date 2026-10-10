"""Record and replay exact model judgments without API access."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from scitaste.backends.base import (
    CandidateGenerationBackend,
    CandidateGenerationRequest,
    CandidateGenerationResponse,
    PreferenceBackend,
    PreferenceRequest,
    PreferenceResponse,
)


class CandidateReplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: CandidateGenerationRequest
    response: CandidateGenerationResponse


def _candidate_call(delegate, path: Path, request: CandidateGenerationRequest, *, resume: bool):
    """Keep candidate records separate from backward-compatible ranking JSONL."""
    target = path.with_name(path.name + ".candidates")
    if resume and target.is_file():
        matches = []
        for line in target.read_text().splitlines():
            item = CandidateReplayRecord.model_validate_json(line)
            if item.request.fingerprint == request.fingerprint:
                if item.response.request_fingerprint != request.fingerprint:
                    raise ValueError("candidate replay response identity differs")
                matches.append(item.response)
        if matches:
            if any(response != matches[0] for response in matches[1:]):
                raise ValueError("conflicting candidate replay responses")
            return matches[0].model_copy(update={"cached": True})
    if delegate is None:
        raise ReplayMissError(f"no exact candidate replay for {request.request_id!r}")
    if not isinstance(delegate, CandidateGenerationBackend):
        raise TypeError("delegate does not implement candidate generation")
    response = delegate.generate_candidates(request)
    if response.request_fingerprint != request.fingerprint:
        raise ValueError("candidate response belongs to another request")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as stream:
        stream.write(
            CandidateReplayRecord(request=request, response=response).model_dump_json(
                round_trip=True
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    return response


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

    def generate_candidates(
        self, request: CandidateGenerationRequest
    ) -> CandidateGenerationResponse:
        return _candidate_call(None, self.path, request, resume=True)

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

    def generate_candidates(
        self, request: CandidateGenerationRequest
    ) -> CandidateGenerationResponse:
        return _candidate_call(self.delegate, self.path, request, resume=False)

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


class ResumableRecordingBackend:
    """Replay completed requests and append only missing live responses."""

    name = "resumable-recording"

    def __init__(self, delegate: PreferenceBackend, path: str | Path) -> None:
        self.delegate = delegate
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.replay = ReplayBackend(self.path)

    def generate_candidates(
        self, request: CandidateGenerationRequest
    ) -> CandidateGenerationResponse:
        return _candidate_call(self.delegate, self.path, request, resume=True)

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        try:
            return self.replay.rank(request)
        except ReplayMissError:
            response = self.delegate.rank(request)
            if response.request_fingerprint != request.fingerprint:
                raise ValueError("delegate returned a response for a different request") from None
            record = ReplayRecord(
                request=request,
                response=response,
                recorded_at=datetime.now(UTC),
            )
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json(exclude={"request": {"fingerprint"}}) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.replay._records[request.fingerprint] = response
            return response

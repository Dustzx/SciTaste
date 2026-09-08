"""Durable, project-owned execution receipts for bounded Tool Intelligence."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from scitaste.backends.base import Usage
from scitaste.model_nodes.tool_execution import (
    ActionLease,
    ControlledToolExecutor,
    ToolObservation,
    ToolObservationStatus,
)
from scitaste.model_nodes.tool_intelligence import canonical_sha256
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRuntime

TOOL_INTELLIGENCE_STAGE_PATH = "tool_intelligence"
_ZERO_HASH = "0" * 64
_STAGE_DIRECTORIES = frozenset(
    {"attempts", "decisions", "leases", "ledger", "observations", "pending"}
)
_FIRST_PARTY_REPLAY_SAFE_HANDLERS = frozenset(
    {
        "scitaste.evidence-inspect.bound-v1",
        "scitaste.knowledge-query.lexical-v1",
        "scitaste.registered-run.compare-v1",
    }
)
_LEASE_FILE_PATTERN = re.compile(r"^lease-[0-9a-f]{24}\.json$")
_LEDGER_FILE_PATTERN = re.compile(r"^[0-9]{8}__lease-[0-9a-f]{24}\.json$")
_ATTEMPT_DIRECTORY_PATTERN = re.compile(r"^lease-[0-9a-f]{24}$")
_DECISION_FILE_PATTERN = re.compile(r"^decision-[0-9a-f]{24}\.json$")


class DurableToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def timestamps_are_aware(cls, value: Any) -> Any:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("durable evidence timestamps must include a timezone")
        return value


class DurableToolFaultPoint(StrEnum):
    """Deterministic fault-injection boundaries used by recovery tests."""

    AFTER_LEASE = "after-lease"
    AFTER_CLAIM = "after-claim"
    AFTER_HANDLER_STARTED = "after-handler-started"
    AFTER_HANDLER_RETURNED = "after-handler-returned"
    AFTER_RESULT = "after-result"
    AFTER_OBSERVATION = "after-observation"
    AFTER_LEDGER = "after-ledger"


class DurableToolRuntimeError(ValueError):
    """Raised when durable Tool Intelligence evidence is unsafe or inconsistent."""


class DurableToolRuntimeConflictError(DurableToolRuntimeError):
    """Raised when another process owns the project-run Tool Intelligence lock."""


class DurableToolAmbiguousExecutionError(DurableToolRuntimeError):
    """Raised when an unclassified handler may have run without a durable result."""


class DurableToolLeaseRecord(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    recorded_at: datetime
    lease: ActionLease
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolLeaseRecord:
        return _create_self_hashed(cls, "record_sha256", **values)

    @model_validator(mode="after")
    def identity_and_hash_match(self) -> DurableToolLeaseRecord:
        if self.project_id != self.lease.project.project_id:
            raise ValueError("durable lease record belongs to another project")
        if self.lease_fingerprint != self.lease.fingerprint:
            raise ValueError("durable lease fingerprint drift")
        _require_self_hash(self, "record_sha256")
        return self


class DurableToolClaim(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    claim_id: str = Field(pattern=r"^claim-[0-9a-f]{24}$")
    attempt_id: str = Field(pattern=r"^attempt-[0-9a-f]{24}$")
    project_id: str
    run_id: str
    lease_id: str = Field(pattern=r"^lease-[0-9a-f]{24}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    handler_id: str
    handler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claimed_at: datetime
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolClaim:
        return _create_self_hashed(cls, "claim_sha256", **values)

    @model_validator(mode="after")
    def hash_matches(self) -> DurableToolClaim:
        _require_self_hash(self, "claim_sha256")
        return self


class DurableToolHandlerStarted(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    handler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    marker_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolHandlerStarted:
        return _create_self_hashed(cls, "marker_sha256", **values)

    @model_validator(mode="after")
    def hash_matches(self) -> DurableToolHandlerStarted:
        _require_self_hash(self, "marker_sha256")
        return self


class DurableToolHandlerResult(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime
    observation: ToolObservation
    observation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolHandlerResult:
        return _create_self_hashed(cls, "result_sha256", **values)

    @model_validator(mode="after")
    def identity_and_hash_match(self) -> DurableToolHandlerResult:
        if self.observation_fingerprint != self.observation.fingerprint:
            raise ValueError("durable handler-result observation drift")
        _require_self_hash(self, "result_sha256")
        return self


class DurableToolObservationRecord(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    observation: ToolObservation
    observation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolObservationRecord:
        return _create_self_hashed(cls, "record_sha256", **values)

    @model_validator(mode="after")
    def identity_and_hash_match(self) -> DurableToolObservationRecord:
        if self.observation_fingerprint != self.observation.fingerprint:
            raise ValueError("durable observation fingerprint drift")
        if self.observation.lease_fingerprint != self.lease_fingerprint:
            raise ValueError("durable observation belongs to another lease")
        _require_self_hash(self, "record_sha256")
        return self


class DurableToolAmbiguityRecord(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    lease_id: str = Field(pattern=r"^lease-[0-9a-f]{24}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    handler_id: str
    detected_at: datetime
    reason: Literal["handler may have run without a durable result"]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolAmbiguityRecord:
        return _create_self_hashed(cls, "record_sha256", **values)

    @model_validator(mode="after")
    def hash_matches(self) -> DurableToolAmbiguityRecord:
        _require_self_hash(self, "record_sha256")
        return self


class DurableToolLedgerEntry(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    index: int = Field(ge=0)
    project_id: str
    run_id: str
    lease_id: str = Field(pattern=r"^lease-[0-9a-f]{24}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str = Field(pattern=r"^observation-[0-9a-f]{24}$")
    observation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ToolObservationStatus
    handler_invoked: bool
    source_model_usage: Usage
    source_model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    completed_at: datetime
    predecessor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolLedgerEntry:
        return _create_self_hashed(cls, "entry_sha256", **values)

    @model_validator(mode="after")
    def hash_matches(self) -> DurableToolLedgerEntry:
        _require_self_hash(self, "entry_sha256")
        return self


class DurableToolAttemptArchive(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    attempt_id: str = Field(pattern=r"^attempt-[0-9a-f]{24}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archived_at: datetime
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolAttemptArchive:
        return _create_self_hashed(cls, "archive_sha256", **values)

    @model_validator(mode="after")
    def hash_matches(self) -> DurableToolAttemptArchive:
        _require_self_hash(self, "archive_sha256")
        return self


class DurableToolDecisionEnvelope(DurableToolModel):
    """Generic self-hashed envelope for a typed workflow decision record."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str = Field(pattern=r"^decision-[0-9a-f]{24}$")
    project_id: str
    run_id: str
    record_kind: Literal["hotspot-workflow-decision-v1"]
    payload: dict[str, JsonValue]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> DurableToolDecisionEnvelope:
        return _create_self_hashed(cls, "envelope_sha256", **values)

    @model_validator(mode="after")
    def payload_and_hash_match(self) -> DurableToolDecisionEnvelope:
        if self.payload_sha256 != canonical_sha256(self.payload):
            raise ValueError("durable decision payload hash drift")
        _require_self_hash(self, "envelope_sha256")
        return self


class DurableToolExecutionReceipt(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    lease_id: str
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation: ToolObservation
    observation_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_index: int = Field(ge=0)
    recovered_without_handler: bool = False
    lease_locator: str
    observation_locator: str
    ledger_locator: str
    advisory_only: Literal[True] = True
    state_transition_authorized: Literal[False] = False


class DurableToolRuntimeVerification(DurableToolModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    lease_count: int = Field(ge=0)
    ledger_entry_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    archived_attempt_count: int = Field(ge=0)
    pending_attempt_count: int = Field(ge=0)
    ambiguous_attempt_count: int = Field(ge=0)
    incomplete_lease_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    handler_invocation_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0)
    model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    chain_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    structurally_valid: Literal[True] = True


class DurableToolExecutionRuntime:
    """Persist, recover, and verify one bounded tool action per action lease."""

    def __init__(
        self,
        project_runtime: ProjectRuntime,
        *,
        executor_factory: Callable[[], ControlledToolExecutor],
        clock: Callable[[], datetime] | None = None,
        fault_hook: Callable[[DurableToolFaultPoint], None] | None = None,
    ) -> None:
        self.project_runtime = project_runtime
        self.executor_factory = executor_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fault_hook = fault_hook

    def execute(
        self,
        *,
        project_id: str,
        run_id: str,
        lease: ActionLease,
    ) -> DurableToolExecutionReceipt:
        """Execute or exactly resume one lease below its registered project run."""

        lease = _roundtrip(lease, ActionLease)
        stage = self._stage(project_id, run_id, create=True)
        with _exclusive_lock(stage / ".runtime.lock"):
            _validate_stage_layout(stage)
            lease_record = self._publish_or_validate_lease(stage, project_id, run_id, lease)
            self._fault(DurableToolFaultPoint.AFTER_LEASE)
            entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
            completed = [entry for entry in entries if entry.lease_fingerprint == lease.fingerprint]
            if len(completed) > 1:
                raise DurableToolRuntimeError("durable ledger contains a duplicate lease")
            if completed:
                entry = completed[0]
                observation_record = self._load_observation_for_entry(stage, entry, lease)
                self._archive_completed_pending(stage, lease, observation_record, entry)
                return self._receipt(
                    lease_record,
                    observation_record,
                    entry,
                    recovered_without_handler=True,
                )

            existing_observation = self._observation_path(stage, lease).exists()
            if existing_observation:
                observation_record = self._load_observation(stage, lease)
                claim = self._claim_for_lease(stage, lease)
                entry = self._append_ledger(
                    stage,
                    entries,
                    lease,
                    claim,
                    observation_record,
                    project_id=project_id,
                    run_id=run_id,
                )
                self._fault(DurableToolFaultPoint.AFTER_LEDGER)
                self._archive_completed_pending(stage, lease, observation_record, entry)
                return self._receipt(
                    lease_record,
                    observation_record,
                    entry,
                    recovered_without_handler=True,
                )

            pending = self._pending_path(stage, lease)
            if not pending.exists():
                claim = self._create_pending(stage, project_id, run_id, lease)
                self._fault(DurableToolFaultPoint.AFTER_CLAIM)
            else:
                claim = self._load_pending_claim(stage, lease)

            _validate_pending_layout(pending)
            ambiguity_path = pending / "ambiguous.json"
            if ambiguity_path.exists():
                _load_model(ambiguity_path, DurableToolAmbiguityRecord)
                raise DurableToolAmbiguousExecutionError(
                    "handler may have run without a durable result"
                )

            result_path = pending / "result.json"
            recovered_without_handler = False
            if result_path.exists():
                result = self._load_handler_result(result_path, claim, lease)
                recovered_without_handler = True
            else:
                started_path = pending / "handler-started.json"
                if started_path.exists():
                    self._load_handler_started(started_path, claim, lease)
                    if lease.handler.handler_id not in _FIRST_PARTY_REPLAY_SAFE_HANDLERS:
                        self._record_ambiguity(pending, project_id, run_id, lease, claim)
                        raise DurableToolAmbiguousExecutionError(
                            "handler may have run without a durable result"
                        )
                else:
                    started = DurableToolHandlerStarted.create(
                        claim_sha256=claim.claim_sha256,
                        lease_fingerprint=lease.fingerprint,
                        handler_fingerprint=lease.handler.fingerprint,
                        started_at=self._now(),
                    )
                    _write_model_exclusive(started_path, started, owned_root=stage)
                    self._fault(DurableToolFaultPoint.AFTER_HANDLER_STARTED)

                executor = self.executor_factory()
                observation = executor.execute(lease)
                self._validate_observation(lease, observation)
                self._fault(DurableToolFaultPoint.AFTER_HANDLER_RETURNED)
                result = DurableToolHandlerResult.create(
                    claim_sha256=claim.claim_sha256,
                    completed_at=self._now(),
                    observation=observation,
                    observation_fingerprint=observation.fingerprint,
                )
                _write_model_exclusive(result_path, result, owned_root=stage)
                self._fault(DurableToolFaultPoint.AFTER_RESULT)

            observation_record = DurableToolObservationRecord.create(
                project_id=project_id,
                run_id=run_id,
                lease_fingerprint=lease.fingerprint,
                claim_sha256=claim.claim_sha256,
                published_at=self._now(),
                observation=result.observation,
                observation_fingerprint=result.observation.fingerprint,
            )
            self._publish_or_validate_observation(stage, lease, observation_record)
            self._fault(DurableToolFaultPoint.AFTER_OBSERVATION)
            entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
            entry = self._append_ledger(
                stage,
                entries,
                lease,
                claim,
                observation_record,
                project_id=project_id,
                run_id=run_id,
            )
            self._fault(DurableToolFaultPoint.AFTER_LEDGER)
            self._archive_completed_pending(stage, lease, observation_record, entry)
            return self._receipt(
                lease_record,
                observation_record,
                entry,
                recovered_without_handler=recovered_without_handler,
            )

    def verify(self, *, project_id: str, run_id: str) -> DurableToolRuntimeVerification:
        """Verify content identities, hash chain, containment, and recovery state."""

        stage = self._stage(project_id, run_id, create=False)
        if not stage.exists():
            return DurableToolRuntimeVerification(
                project_id=project_id,
                run_id=run_id,
                lease_count=0,
                ledger_entry_count=0,
                observation_count=0,
                archived_attempt_count=0,
                pending_attempt_count=0,
                ambiguous_attempt_count=0,
                incomplete_lease_count=0,
                decision_count=0,
                handler_invocation_count=0,
                input_tokens=0,
                output_tokens=0,
                known_cost_usd=0.0,
                unknown_cost_count=0,
                model_latency_ms=0.0,
                tool_latency_ms=0.0,
                chain_head_sha256=self._root_hash(project_id, run_id),
            )
        with _exclusive_lock(stage / ".runtime.lock"):
            _validate_stage_layout(stage)
            leases = self._load_leases(stage, project_id=project_id, run_id=run_id)
            entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
            observations = self._load_observations(stage, leases)
            pending, ambiguous = self._verify_pending(stage, leases)
            archived = self._verify_attempts(stage, leases, entries, observations)
            decisions = self._verify_decisions(stage, project_id=project_id, run_id=run_id)
            completed = {entry.lease_fingerprint for entry in entries}
            if completed != set(observations):
                raise DurableToolRuntimeError(
                    "durable observations and ledger leases are not closed"
                )
            if completed - set(leases):
                raise DurableToolRuntimeError("durable ledger references an unknown lease")
            active = completed | pending
            return DurableToolRuntimeVerification(
                project_id=project_id,
                run_id=run_id,
                lease_count=len(leases),
                ledger_entry_count=len(entries),
                observation_count=len(observations),
                archived_attempt_count=archived,
                pending_attempt_count=len(pending),
                ambiguous_attempt_count=ambiguous,
                incomplete_lease_count=len(set(leases) - active),
                decision_count=decisions,
                handler_invocation_count=sum(entry.handler_invoked for entry in entries),
                input_tokens=sum(entry.source_model_usage.input_tokens for entry in entries),
                output_tokens=sum(entry.source_model_usage.output_tokens for entry in entries),
                known_cost_usd=sum(entry.source_model_usage.cost_usd or 0.0 for entry in entries),
                unknown_cost_count=sum(
                    entry.source_model_usage.cost_usd is None for entry in entries
                ),
                model_latency_ms=sum(entry.source_model_latency_ms for entry in entries),
                tool_latency_ms=sum(entry.tool_latency_ms for entry in entries),
                chain_head_sha256=(
                    entries[-1].entry_sha256 if entries else self._root_hash(project_id, run_id)
                ),
            )

    def publish_decision(
        self,
        *,
        project_id: str,
        run_id: str,
        decision_id: str,
        payload: dict[str, JsonValue],
    ) -> DurableToolDecisionEnvelope:
        """Idempotently publish one typed workflow record as durable evidence."""

        if not _DECISION_FILE_PATTERN.fullmatch(f"{decision_id}.json"):
            raise DurableToolRuntimeError("invalid durable decision identifier")
        _validate_decision_payload(
            payload,
            decision_id=decision_id,
            project_id=project_id,
            run_id=run_id,
        )
        stage = self._stage(project_id, run_id, create=True)
        with _exclusive_lock(stage / ".runtime.lock"):
            _validate_stage_layout(stage)
            decisions = _stage_directory(stage, "decisions", create=True)
            assert decisions is not None
            path = decisions / f"{decision_id}.json"
            payload_sha256 = canonical_sha256(payload)
            if path.exists():
                existing = _load_model(path, DurableToolDecisionEnvelope)
                if (
                    existing.project_id,
                    existing.run_id,
                    existing.payload_sha256,
                ) != (project_id, run_id, payload_sha256):
                    raise DurableToolRuntimeError("durable workflow decision identity drift")
                return existing
            envelope = DurableToolDecisionEnvelope.create(
                decision_id=decision_id,
                project_id=project_id,
                run_id=run_id,
                record_kind="hotspot-workflow-decision-v1",
                payload=payload,
                payload_sha256=payload_sha256,
            )
            _write_model_exclusive(path, envelope, owned_root=stage)
            return envelope

    def load_decision(
        self,
        *,
        project_id: str,
        run_id: str,
        decision_id: str,
    ) -> DurableToolDecisionEnvelope | None:
        """Load an existing exact workflow decision without changing evidence."""

        if not _DECISION_FILE_PATTERN.fullmatch(f"{decision_id}.json"):
            raise DurableToolRuntimeError("invalid durable decision identifier")
        stage = self._stage(project_id, run_id, create=False)
        if not stage.exists():
            return None
        with _exclusive_lock(stage / ".runtime.lock"):
            _validate_stage_layout(stage)
            root = _stage_directory(stage, "decisions")
            path = root / f"{decision_id}.json" if root is not None else None
            if path is None or not path.exists():
                return None
            envelope = _load_model(path, DurableToolDecisionEnvelope)
            if (envelope.project_id, envelope.run_id) != (project_id, run_id):
                raise DurableToolRuntimeError("durable decision belongs to another run")
            _validate_decision_payload(
                envelope.payload,
                decision_id=decision_id,
                project_id=project_id,
                run_id=run_id,
            )
            return envelope

    def find_lease(
        self,
        *,
        project_id: str,
        run_id: str,
        source_request_fingerprint: str,
        hotspot_trigger_fingerprint: str,
        step_fingerprint: str,
    ) -> ActionLease | None:
        """Find the unique lease already persisted for one workflow action identity."""

        stage = self._stage(project_id, run_id, create=False)
        if not stage.exists():
            return None
        with _exclusive_lock(stage / ".runtime.lock"):
            _validate_stage_layout(stage)
            leases = self._load_leases(stage, project_id=project_id, run_id=run_id)
            matches = [
                record.lease
                for record in leases.values()
                if record.lease.source_request_fingerprint == source_request_fingerprint
                and record.lease.hotspot_trigger_fingerprint == hotspot_trigger_fingerprint
                and record.lease.step_fingerprint == step_fingerprint
            ]
            if len(matches) > 1:
                raise DurableToolRuntimeError("multiple durable leases match one workflow action")
            return matches[0] if matches else None

    def _stage(self, project_id: str, run_id: str, *, create: bool) -> Path:
        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        snapshot = self.project_runtime.open(project_id)
        if run_id not in {item.run_id for item in snapshot.manifest.runs}:
            raise DurableToolRuntimeError(f"unknown project run {run_id!r}")
        project = self.project_runtime.outputs_root / "projects" / project_id
        run = project / "runs" / run_id
        _require_safe_directory_chain(self.project_runtime.outputs_root, run)
        stage = run / TOOL_INTELLIGENCE_STAGE_PATH
        if not os.path.lexists(stage):
            if not create:
                return stage
            try:
                stage.mkdir()
            except FileExistsError:
                pass
            _fsync_directory(run)
        if stage.is_symlink() or not stage.is_dir() or stage.resolve(strict=True) != stage:
            raise DurableToolRuntimeError("Tool Intelligence stage escapes its project-owned run")
        return stage

    def _publish_or_validate_lease(
        self,
        stage: Path,
        project_id: str,
        run_id: str,
        lease: ActionLease,
    ) -> DurableToolLeaseRecord:
        if lease.project.project_id != project_id:
            raise DurableToolRuntimeError("action lease belongs to another project")
        path = self._lease_path(stage, lease)
        if path.exists():
            record = _load_model(path, DurableToolLeaseRecord)
            if record.lease != lease:
                raise DurableToolRuntimeError("durable action lease identity drift")
            return record
        record = DurableToolLeaseRecord.create(
            project_id=project_id,
            run_id=run_id,
            recorded_at=self._now(),
            lease=lease,
            lease_fingerprint=lease.fingerprint,
        )
        _write_model_exclusive(path, record, owned_root=stage)
        return record

    def _create_pending(
        self,
        stage: Path,
        project_id: str,
        run_id: str,
        lease: ActionLease,
    ) -> DurableToolClaim:
        pending_root = _stage_directory(stage, "pending", create=True)
        assert pending_root is not None
        target = pending_root / lease.lease_id
        if os.path.lexists(target):
            raise DurableToolRuntimeError("duplicate durable action-lease claim")
        claimed_at = self._now()
        claim_seed = {
            "project_id": project_id,
            "run_id": run_id,
            "lease_fingerprint": lease.fingerprint,
            "handler_fingerprint": lease.handler.fingerprint,
            "claimed_at": claimed_at.isoformat(),
        }
        claim = DurableToolClaim.create(
            claim_id=f"claim-{canonical_sha256(claim_seed)[:24]}",
            attempt_id=f"attempt-{lease.fingerprint[:24]}",
            project_id=project_id,
            run_id=run_id,
            lease_id=lease.lease_id,
            lease_fingerprint=lease.fingerprint,
            handler_id=lease.handler.handler_id,
            handler_fingerprint=lease.handler.fingerprint,
            claimed_at=claimed_at,
        )
        temporary = Path(tempfile.mkdtemp(prefix=f".{lease.lease_id}.", dir=pending_root))
        try:
            _write_model_exclusive(temporary / "claim.json", claim, owned_root=stage)
            if os.path.lexists(target):
                raise DurableToolRuntimeError("duplicate durable action-lease claim")
            os.rename(temporary, target)
            _fsync_directory(pending_root)
        finally:
            if temporary.exists():
                temporary.rmdir()
        return claim

    def _claim_for_lease(self, stage: Path, lease: ActionLease) -> DurableToolClaim:
        pending = self._pending_path(stage, lease)
        if pending.exists():
            return self._load_pending_claim(stage, lease)
        attempt = self._attempt_path(stage, lease)
        if attempt.exists():
            return self._load_claim(attempt / "claim.json", lease)
        raise DurableToolRuntimeError("durable observation has no matching claim")

    def _load_pending_claim(self, stage: Path, lease: ActionLease) -> DurableToolClaim:
        pending = self._pending_path(stage, lease)
        _require_contained_directory(_stage_directory(stage, "pending"), pending)
        return self._load_claim(pending / "claim.json", lease)

    @staticmethod
    def _load_claim(path: Path, lease: ActionLease) -> DurableToolClaim:
        claim = _load_model(path, DurableToolClaim)
        if (
            claim.lease_id != lease.lease_id
            or claim.lease_fingerprint != lease.fingerprint
            or claim.handler_id != lease.handler.handler_id
            or claim.handler_fingerprint != lease.handler.fingerprint
        ):
            raise DurableToolRuntimeError("durable claim identity drift")
        return claim

    @staticmethod
    def _load_handler_started(
        path: Path,
        claim: DurableToolClaim,
        lease: ActionLease,
    ) -> DurableToolHandlerStarted:
        started = _load_model(path, DurableToolHandlerStarted)
        if (
            started.claim_sha256 != claim.claim_sha256
            or started.lease_fingerprint != lease.fingerprint
            or started.handler_fingerprint != lease.handler.fingerprint
        ):
            raise DurableToolRuntimeError("durable handler-start marker identity drift")
        return started

    @staticmethod
    def _load_handler_result(
        path: Path,
        claim: DurableToolClaim,
        lease: ActionLease,
    ) -> DurableToolHandlerResult:
        result = _load_model(path, DurableToolHandlerResult)
        if result.claim_sha256 != claim.claim_sha256:
            raise DurableToolRuntimeError("durable handler-result claim drift")
        DurableToolExecutionRuntime._validate_observation(lease, result.observation)
        return result

    def _record_ambiguity(
        self,
        pending: Path,
        project_id: str,
        run_id: str,
        lease: ActionLease,
        claim: DurableToolClaim,
    ) -> None:
        path = pending / "ambiguous.json"
        if path.exists():
            record = _load_model(path, DurableToolAmbiguityRecord)
            if record.claim_sha256 != claim.claim_sha256:
                raise DurableToolRuntimeError("durable ambiguity claim drift")
            return
        record = DurableToolAmbiguityRecord.create(
            project_id=project_id,
            run_id=run_id,
            lease_id=lease.lease_id,
            lease_fingerprint=lease.fingerprint,
            claim_sha256=claim.claim_sha256,
            handler_id=lease.handler.handler_id,
            detected_at=self._now(),
            reason="handler may have run without a durable result",
        )
        _write_model_exclusive(path, record, owned_root=pending.parent.parent)

    def _publish_or_validate_observation(
        self,
        stage: Path,
        lease: ActionLease,
        record: DurableToolObservationRecord,
    ) -> None:
        path = self._observation_path(stage, lease)
        if path.exists():
            existing = self._load_observation(stage, lease)
            if existing != record:
                raise DurableToolRuntimeError("durable observation publication drift")
            return
        _write_model_exclusive(path, record, owned_root=stage)

    def _load_observation(
        self,
        stage: Path,
        lease: ActionLease,
    ) -> DurableToolObservationRecord:
        record = _load_model(self._observation_path(stage, lease), DurableToolObservationRecord)
        if record.lease_fingerprint != lease.fingerprint:
            raise DurableToolRuntimeError("durable observation lease drift")
        self._validate_observation(lease, record.observation)
        return record

    def _append_ledger(
        self,
        stage: Path,
        entries: list[DurableToolLedgerEntry],
        lease: ActionLease,
        claim: DurableToolClaim,
        observation_record: DurableToolObservationRecord,
        *,
        project_id: str,
        run_id: str,
    ) -> DurableToolLedgerEntry:
        duplicates = [entry for entry in entries if entry.lease_fingerprint == lease.fingerprint]
        if duplicates:
            if len(duplicates) != 1:
                raise DurableToolRuntimeError("durable ledger contains a duplicate lease")
            return duplicates[0]
        observation = observation_record.observation
        predecessor = entries[-1].entry_sha256 if entries else self._root_hash(project_id, run_id)
        entry = DurableToolLedgerEntry.create(
            index=len(entries),
            project_id=project_id,
            run_id=run_id,
            lease_id=lease.lease_id,
            lease_fingerprint=lease.fingerprint,
            claim_sha256=claim.claim_sha256,
            observation_id=observation.observation_id,
            observation_fingerprint=observation.fingerprint,
            observation_record_sha256=observation_record.record_sha256,
            status=observation.status,
            handler_invoked=observation.handler_invoked,
            source_model_usage=observation.source_model_usage,
            source_model_latency_ms=observation.source_model_latency_ms,
            tool_latency_ms=observation.tool_latency_ms,
            completed_at=self._now(),
            predecessor_sha256=predecessor,
        )
        ledger = _stage_directory(stage, "ledger", create=True)
        assert ledger is not None
        path = ledger / f"{entry.index:08d}__{entry.lease_id}.json"
        _write_model_exclusive(path, entry, owned_root=stage)
        return entry

    def _load_ledger(
        self,
        stage: Path,
        *,
        project_id: str,
        run_id: str,
    ) -> list[DurableToolLedgerEntry]:
        root = _stage_directory(stage, "ledger")
        paths = sorted(root.glob("*.json")) if root is not None else []
        predecessor = self._root_hash(project_id, run_id)
        entries: list[DurableToolLedgerEntry] = []
        lease_fingerprints: set[str] = set()
        for index, path in enumerate(paths):
            entry = _load_model(path, DurableToolLedgerEntry)
            if entry.index != index:
                raise DurableToolRuntimeError("durable ledger is not a contiguous prefix")
            if (entry.project_id, entry.run_id) != (project_id, run_id):
                raise DurableToolRuntimeError("durable ledger entry belongs to another run")
            expected_name = f"{index:08d}__{entry.lease_id}.json"
            if path.name != expected_name:
                raise DurableToolRuntimeError("durable ledger filename identity drift")
            if entry.predecessor_sha256 != predecessor:
                raise DurableToolRuntimeError("durable ledger predecessor chain drift")
            if entry.lease_fingerprint in lease_fingerprints:
                raise DurableToolRuntimeError("durable ledger contains a duplicate lease")
            lease_fingerprints.add(entry.lease_fingerprint)
            entries.append(entry)
            predecessor = entry.entry_sha256
        return entries

    def _load_observation_for_entry(
        self,
        stage: Path,
        entry: DurableToolLedgerEntry,
        lease: ActionLease,
    ) -> DurableToolObservationRecord:
        record = self._load_observation(stage, lease)
        if (
            entry.observation_fingerprint != record.observation.fingerprint
            or entry.observation_record_sha256 != record.record_sha256
            or entry.claim_sha256 != record.claim_sha256
        ):
            raise DurableToolRuntimeError("ledger and observation evidence drift")
        return record

    def _archive_completed_pending(
        self,
        stage: Path,
        lease: ActionLease,
        observation: DurableToolObservationRecord,
        entry: DurableToolLedgerEntry,
    ) -> None:
        pending = self._pending_path(stage, lease)
        if not pending.exists():
            return
        claim = self._load_pending_claim(stage, lease)
        result = self._load_handler_result(pending / "result.json", claim, lease)
        if result.observation_fingerprint != observation.observation_fingerprint:
            raise DurableToolRuntimeError("pending result and observation drift")
        archive = DurableToolAttemptArchive.create(
            project_id=entry.project_id,
            run_id=entry.run_id,
            attempt_id=claim.attempt_id,
            lease_fingerprint=lease.fingerprint,
            claim_sha256=claim.claim_sha256,
            observation_record_sha256=observation.record_sha256,
            ledger_entry_sha256=entry.entry_sha256,
            archived_at=self._now(),
        )
        archive_path = pending / "archive.json"
        if archive_path.exists():
            existing = _load_model(archive_path, DurableToolAttemptArchive)
            if (
                existing.lease_fingerprint != archive.lease_fingerprint
                or existing.claim_sha256 != archive.claim_sha256
                or existing.observation_record_sha256 != archive.observation_record_sha256
                or existing.ledger_entry_sha256 != archive.ledger_entry_sha256
            ):
                raise DurableToolRuntimeError("durable attempt archive identity drift")
        else:
            _write_model_exclusive(archive_path, archive, owned_root=stage)
        attempts = _stage_directory(stage, "attempts", create=True)
        pending_root = _stage_directory(stage, "pending")
        assert attempts is not None and pending_root is not None
        target = attempts / lease.lease_id
        if os.path.lexists(target):
            raise DurableToolRuntimeError("refusing to replace durable attempt evidence")
        os.rename(pending, target)
        _fsync_directory(pending_root)
        _fsync_directory(attempts)

    def _load_leases(
        self,
        stage: Path,
        *,
        project_id: str,
        run_id: str,
    ) -> dict[str, DurableToolLeaseRecord]:
        root = _stage_directory(stage, "leases")
        records: dict[str, DurableToolLeaseRecord] = {}
        for path in sorted(root.glob("*.json")) if root is not None else []:
            record = _load_model(path, DurableToolLeaseRecord)
            if (record.project_id, record.run_id) != (project_id, run_id):
                raise DurableToolRuntimeError("durable lease belongs to another project run")
            if path.name != f"{record.lease.lease_id}.json":
                raise DurableToolRuntimeError("durable lease filename identity drift")
            if record.lease_fingerprint in records:
                raise DurableToolRuntimeError("duplicate durable lease fingerprint")
            records[record.lease_fingerprint] = record
        return records

    def _load_observations(
        self,
        stage: Path,
        leases: dict[str, DurableToolLeaseRecord],
    ) -> dict[str, DurableToolObservationRecord]:
        root = _stage_directory(stage, "observations")
        records: dict[str, DurableToolObservationRecord] = {}
        for path in sorted(root.glob("*.json")) if root is not None else []:
            record = _load_model(path, DurableToolObservationRecord)
            lease_record = leases.get(record.lease_fingerprint)
            if lease_record is None:
                raise DurableToolRuntimeError("durable observation references an unknown lease")
            if path.name != f"{lease_record.lease.lease_id}.json":
                raise DurableToolRuntimeError("durable observation filename identity drift")
            self._validate_observation(lease_record.lease, record.observation)
            records[record.lease_fingerprint] = record
        return records

    def _verify_pending(
        self,
        stage: Path,
        leases: dict[str, DurableToolLeaseRecord],
    ) -> tuple[set[str], int]:
        root = _stage_directory(stage, "pending")
        active: set[str] = set()
        ambiguous = 0
        for path in sorted(root.iterdir()) if root is not None else []:
            _require_contained_directory(root, path)
            claim = _load_model(path / "claim.json", DurableToolClaim)
            lease_record = leases.get(claim.lease_fingerprint)
            if lease_record is None:
                raise DurableToolRuntimeError("pending claim references an unknown lease")
            self._load_claim(path / "claim.json", lease_record.lease)
            allowed = {"claim.json", "handler-started.json", "result.json", "ambiguous.json"}
            names = {item.name for item in path.iterdir()}
            if names - allowed:
                raise DurableToolRuntimeError("pending attempt contains unexpected evidence")
            if "handler-started.json" in names:
                self._load_handler_started(path / "handler-started.json", claim, lease_record.lease)
            if "result.json" in names:
                self._load_handler_result(path / "result.json", claim, lease_record.lease)
            if "ambiguous.json" in names:
                ambiguity = _load_model(path / "ambiguous.json", DurableToolAmbiguityRecord)
                if ambiguity.claim_sha256 != claim.claim_sha256:
                    raise DurableToolRuntimeError("durable ambiguity claim drift")
                ambiguous += 1
            active.add(claim.lease_fingerprint)
        return active, ambiguous

    def _verify_attempts(
        self,
        stage: Path,
        leases: dict[str, DurableToolLeaseRecord],
        entries: list[DurableToolLedgerEntry],
        observations: dict[str, DurableToolObservationRecord],
    ) -> int:
        root = _stage_directory(stage, "attempts")
        entry_by_lease = {entry.lease_fingerprint: entry for entry in entries}
        count = 0
        for path in sorted(root.iterdir()) if root is not None else []:
            _require_contained_directory(root, path)
            claim = _load_model(path / "claim.json", DurableToolClaim)
            lease_record = leases.get(claim.lease_fingerprint)
            entry = entry_by_lease.get(claim.lease_fingerprint)
            observation = observations.get(claim.lease_fingerprint)
            if lease_record is None or entry is None or observation is None:
                raise DurableToolRuntimeError("archived attempt is not evidence-closed")
            self._load_claim(path / "claim.json", lease_record.lease)
            self._load_handler_started(path / "handler-started.json", claim, lease_record.lease)
            result = self._load_handler_result(path / "result.json", claim, lease_record.lease)
            archive = _load_model(path / "archive.json", DurableToolAttemptArchive)
            if path.name != lease_record.lease.lease_id:
                raise DurableToolRuntimeError("archived attempt filename identity drift")
            if (
                result.observation_fingerprint != observation.observation_fingerprint
                or archive.attempt_id != claim.attempt_id
                or archive.lease_fingerprint != claim.lease_fingerprint
                or archive.claim_sha256 != claim.claim_sha256
                or archive.observation_record_sha256 != observation.record_sha256
                or archive.ledger_entry_sha256 != entry.entry_sha256
            ):
                raise DurableToolRuntimeError("archived attempt identity drift")
            expected_names = {
                "archive.json",
                "claim.json",
                "handler-started.json",
                "result.json",
            }
            if {item.name for item in path.iterdir()} != expected_names:
                raise DurableToolRuntimeError("archived attempt contains unexpected evidence")
            count += 1
        return count

    @staticmethod
    def _verify_decisions(stage: Path, *, project_id: str, run_id: str) -> int:
        root = _stage_directory(stage, "decisions")
        count = 0
        for path in sorted(root.iterdir()) if root is not None else []:
            envelope = _load_model(path, DurableToolDecisionEnvelope)
            if path.name != f"{envelope.decision_id}.json":
                raise DurableToolRuntimeError("durable decision filename identity drift")
            if (envelope.project_id, envelope.run_id) != (project_id, run_id):
                raise DurableToolRuntimeError("durable decision belongs to another run")
            _validate_decision_payload(
                envelope.payload,
                decision_id=envelope.decision_id,
                project_id=project_id,
                run_id=run_id,
            )
            count += 1
        return count

    @staticmethod
    def _validate_observation(lease: ActionLease, observation: ToolObservation) -> None:
        if (
            observation.lease_id != lease.lease_id
            or observation.lease_fingerprint != lease.fingerprint
            or observation.tool_name != lease.step.tool_name
            or observation.handler_id != lease.handler.handler_id
            or observation.handler_fingerprint != lease.handler.fingerprint
            or observation.source_request_fingerprint != lease.source_request_fingerprint
            or observation.source_raw_response_sha256 != lease.source_raw_response_sha256
            or observation.source_model_usage != lease.source_model_usage
            or observation.source_model_latency_ms != lease.source_model_latency_ms
        ):
            raise DurableToolRuntimeError("tool observation identity drift")
        if observation.status is ToolObservationStatus.SUCCEEDED and (
            observation.project_revision_before != lease.project.revision
            or observation.project_revision_after != lease.project.revision
            or observation.state_snapshot_id_before != lease.state_snapshot_id
            or observation.state_snapshot_id_after != lease.state_snapshot_id
        ):
            raise DurableToolRuntimeError(
                "successful observation lacks stable project/state evidence"
            )

    def _receipt(
        self,
        lease_record: DurableToolLeaseRecord,
        observation_record: DurableToolObservationRecord,
        entry: DurableToolLedgerEntry,
        *,
        recovered_without_handler: bool,
    ) -> DurableToolExecutionReceipt:
        base = (
            f"projects/{lease_record.project_id}/runs/{lease_record.run_id}/"
            f"{TOOL_INTELLIGENCE_STAGE_PATH}"
        )
        return DurableToolExecutionReceipt(
            project_id=lease_record.project_id,
            run_id=lease_record.run_id,
            lease_id=lease_record.lease.lease_id,
            lease_fingerprint=lease_record.lease_fingerprint,
            observation=observation_record.observation,
            observation_record_sha256=observation_record.record_sha256,
            ledger_entry_sha256=entry.entry_sha256,
            ledger_index=entry.index,
            recovered_without_handler=recovered_without_handler,
            lease_locator=f"{base}/leases/{lease_record.lease.lease_id}.json",
            observation_locator=(f"{base}/observations/{lease_record.lease.lease_id}.json"),
            ledger_locator=f"{base}/ledger",
        )

    @staticmethod
    def _root_hash(project_id: str, run_id: str) -> str:
        return canonical_sha256(
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "run_id": run_id,
                "stage_path": TOOL_INTELLIGENCE_STAGE_PATH,
            }
        )

    @staticmethod
    def _lease_path(stage: Path, lease: ActionLease) -> Path:
        root = _stage_directory(stage, "leases", create=True)
        assert root is not None
        return root / f"{lease.lease_id}.json"

    @staticmethod
    def _observation_path(stage: Path, lease: ActionLease) -> Path:
        root = _stage_directory(stage, "observations", create=True)
        assert root is not None
        return root / f"{lease.lease_id}.json"

    @staticmethod
    def _pending_path(stage: Path, lease: ActionLease) -> Path:
        root = _stage_directory(stage, "pending", create=True)
        assert root is not None
        return root / lease.lease_id

    @staticmethod
    def _attempt_path(stage: Path, lease: ActionLease) -> Path:
        root = _stage_directory(stage, "attempts", create=True)
        assert root is not None
        return root / lease.lease_id

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise DurableToolRuntimeError("durable runtime clock must be timezone-aware")
        return value

    def _fault(self, point: DurableToolFaultPoint) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)


def _create_self_hashed(
    model_type: type[BaseModel],
    hash_field: str,
    **values: Any,
) -> Any:
    payload = {"schema_version": "1.0", **values}
    unsigned = model_type.model_construct(**payload, **{hash_field: _ZERO_HASH})
    payload[hash_field] = canonical_sha256(unsigned.model_dump(mode="json", exclude={hash_field}))
    return model_type.model_validate(payload)


def _validate_decision_payload(
    payload: dict[str, JsonValue],
    *,
    decision_id: str,
    project_id: str,
    run_id: str,
) -> None:
    from scitaste.model_nodes.tool_workflow import ToolHotspotWorkflowDecisionRecord

    try:
        record = ToolHotspotWorkflowDecisionRecord.model_validate_json(
            json.dumps(payload, ensure_ascii=False, allow_nan=False), strict=True
        )
    except ValueError as exc:
        raise DurableToolRuntimeError("invalid durable workflow decision payload") from exc
    if (record.decision_id, record.project_id, record.run_id) != (
        decision_id,
        project_id,
        run_id,
    ):
        raise DurableToolRuntimeError("durable workflow decision payload identity drift")


def _require_self_hash(value: BaseModel, hash_field: str) -> None:
    expected = canonical_sha256(value.model_dump(mode="json", exclude={hash_field}))
    if getattr(value, hash_field) != expected:
        raise ValueError(f"{hash_field} does not match durable evidence")


def _roundtrip(value: BaseModel, model_type: type[BaseModel]) -> Any:
    try:
        return model_type.model_validate_json(
            value.model_dump_json(exclude_computed_fields=True), strict=True
        )
    except ValueError as exc:
        raise DurableToolRuntimeError("invalid durable Tool Intelligence input") from exc


def _load_model(path: Path, model_type: type[BaseModel]) -> Any:
    try:
        descriptor = _open_regular_file_nofollow(path)
        with os.fdopen(descriptor, "rb") as handle:
            payload = handle.read()
        return model_type.model_validate_json(payload, strict=True)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DurableToolRuntimeError(f"invalid durable evidence: {path.name}") from exc


def _open_regular_file_nofollow(path: Path) -> int:
    if path.is_symlink():
        raise DurableToolRuntimeError(f"missing or unsafe durable evidence: {path.name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DurableToolRuntimeError(f"missing or unsafe durable evidence: {path.name}") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise DurableToolRuntimeError(f"durable evidence is not regular: {path.name}")
    return descriptor


def _write_model_exclusive(
    path: Path,
    value: BaseModel,
    *,
    owned_root: Path,
) -> None:
    payload = (
        json.dumps(
            value.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    _require_owned_parent(owned_root, path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise DurableToolRuntimeError(
                f"refusing to replace durable evidence: {path.name}"
            ) from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise DurableToolRuntimeError("durable runtime lock is not a regular file")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise DurableToolRuntimeError("cannot open durable runtime lock safely") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise DurableToolRuntimeError("durable runtime lock is not a regular file")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DurableToolRuntimeConflictError(
                "another process owns this Tool Intelligence ledger"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_stage_layout(stage: Path) -> None:
    if stage.is_symlink() or not stage.is_dir() or stage.resolve(strict=True) != stage:
        raise DurableToolRuntimeError("Tool Intelligence stage escapes its run")
    for child in stage.iterdir():
        if child.is_symlink():
            raise DurableToolRuntimeError("Tool Intelligence stage contains a symbolic link")
        if child.name == ".runtime.lock":
            if not child.is_file():
                raise DurableToolRuntimeError("durable runtime lock is not a regular file")
        elif child.name not in _STAGE_DIRECTORIES:
            raise DurableToolRuntimeError("Tool Intelligence stage contains an unknown entry")
    for name in _STAGE_DIRECTORIES:
        root = _stage_directory(stage, name)
        if root is None:
            continue
        directories = name in {"attempts", "pending"}
        for entry in root.iterdir():
            if entry.is_symlink() or (entry.is_dir() != directories):
                raise DurableToolRuntimeError(f"durable {name} contains an unsafe entry")
            if entry.resolve(strict=True).parent != root.resolve(strict=True):
                raise DurableToolRuntimeError(f"durable {name} entry escapes its root")
            if name in {"leases", "observations"} and not _LEASE_FILE_PATTERN.fullmatch(entry.name):
                raise DurableToolRuntimeError(f"durable {name} contains an unknown entry")
            if name == "decisions" and not _DECISION_FILE_PATTERN.fullmatch(entry.name):
                raise DurableToolRuntimeError("durable decisions contains an unknown entry")
            if name == "ledger" and not _LEDGER_FILE_PATTERN.fullmatch(entry.name):
                raise DurableToolRuntimeError("durable ledger contains an unknown entry")
            if name in {"attempts", "pending"} and not _ATTEMPT_DIRECTORY_PATTERN.fullmatch(
                entry.name
            ):
                raise DurableToolRuntimeError(f"durable {name} contains an unknown entry")


def _stage_directory(stage: Path, name: str, *, create: bool = False) -> Path | None:
    if name not in _STAGE_DIRECTORIES:
        raise ValueError(f"unsupported Tool Intelligence directory {name!r}")
    if stage.is_symlink() or not stage.is_dir() or stage.resolve(strict=True) != stage:
        raise DurableToolRuntimeError("Tool Intelligence stage escapes its run")
    candidate = stage / name
    if not os.path.lexists(candidate):
        if not create:
            return None
        try:
            candidate.mkdir()
        except FileExistsError:
            pass
        _fsync_directory(stage)
    if candidate.is_symlink() or not candidate.is_dir():
        raise DurableToolRuntimeError(f"durable {name} is not a safe directory")
    _require_contained_directory(stage, candidate)
    return candidate


def _validate_pending_layout(path: Path) -> None:
    allowed = {"ambiguous.json", "claim.json", "handler-started.json", "result.json"}
    entries = tuple(path.iterdir())
    names = {entry.name for entry in entries}
    if names - allowed:
        raise DurableToolRuntimeError("pending attempt contains interrupted publication")
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise DurableToolRuntimeError("pending attempt contains unsafe evidence")
    if "claim.json" not in names:
        raise DurableToolRuntimeError("pending attempt is missing its claim")
    if "result.json" in names and "handler-started.json" not in names:
        raise DurableToolRuntimeError("pending result has no handler-start marker")
    if "ambiguous.json" in names and (
        "handler-started.json" not in names or "result.json" in names
    ):
        raise DurableToolRuntimeError("pending ambiguity evidence is inconsistent")


def _require_contained_directory(root: Path | None, path: Path) -> None:
    if root is None or root.is_symlink() or not root.is_dir():
        raise DurableToolRuntimeError("durable evidence root is not a safe directory")
    if path.is_symlink() or not path.is_dir():
        raise DurableToolRuntimeError("durable evidence path is not a safe directory")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise DurableToolRuntimeError("durable evidence path escapes its root") from exc


def _require_owned_parent(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise DurableToolRuntimeError("durable evidence parent escapes its root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise DurableToolRuntimeError("durable evidence parent is unsafe")
    try:
        parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise DurableToolRuntimeError("durable evidence parent escapes its root") from exc


def _require_safe_directory_chain(root: Path, target: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise DurableToolRuntimeError("outputs root is not a safe directory")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise DurableToolRuntimeError("project run escapes the outputs root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise DurableToolRuntimeError("project run contains an unsafe path component")
    if target.resolve(strict=True) != target:
        raise DurableToolRuntimeError("project run escapes its owned path")


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
    "TOOL_INTELLIGENCE_STAGE_PATH",
    "DurableToolAmbiguityRecord",
    "DurableToolAmbiguousExecutionError",
    "DurableToolAttemptArchive",
    "DurableToolClaim",
    "DurableToolDecisionEnvelope",
    "DurableToolExecutionReceipt",
    "DurableToolExecutionRuntime",
    "DurableToolFaultPoint",
    "DurableToolHandlerResult",
    "DurableToolHandlerStarted",
    "DurableToolLeaseRecord",
    "DurableToolLedgerEntry",
    "DurableToolObservationRecord",
    "DurableToolRuntimeConflictError",
    "DurableToolRuntimeError",
    "DurableToolRuntimeVerification",
]

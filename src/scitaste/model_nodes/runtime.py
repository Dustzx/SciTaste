"""Durable, project-scoped execution runtime for bounded model nodes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import (
    NodeContext,
    NodePolicy,
    NodeResult,
    NodeResultStatus,
    StructuredModelResponse,
)
from scitaste.model_nodes.nodes import (
    AmbiguousActionNode,
    InterpretationThreatNode,
    NodeNotApplicableError,
    ReviewSemanticNode,
)
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.replay import (
    RecordingStructuredBackend,
    ReplayStructuredBackend,
    StructuredReplayRecord,
)
from scitaste.model_nodes.schemas import (
    AmbiguousActionInput,
    AmbiguousActionOutput,
    InterpretationThreatInput,
    InterpretationThreatOutput,
    ReviewSemanticInput,
    ReviewSemanticOutput,
)
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRevisionConflictError

MODEL_NODE_STAGE_PATH = "model_nodes"
_ZERO_HASH = "0" * 64


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeBackendMode(StrEnum):
    SCRIPTED = "scripted"
    LIVE = "live"
    REPLAY = "replay"


class RuntimeOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"
    PLANNED = "planned"


class ModelNodeTrigger(RuntimeModel):
    trigger_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    reason: str = Field(min_length=1)


class RuntimeInvocationIntent(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: str = Field(min_length=1)
    project_id: str
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    project_revision: int = Field(ge=0)
    state_revision: int = Field(ge=0)
    node_name: Literal["review-semantic", "interpretation-threat", "ambiguous-action"]
    node_input: dict[str, JsonValue]
    context: NodeContext
    trigger: ModelNodeTrigger
    profile: ModelNodeProfile
    policy: NodePolicy
    backend_mode: RuntimeBackendMode
    replay_source_invocation_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    seed: int = Field(ge=0)
    predecessor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def identity_is_closed(self) -> RuntimeInvocationIntent:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="run_id")
        if self.context.project_id != self.project_id:
            raise ValueError("node context belongs to another project")
        if (self.profile.provider, self.profile.model) != (
            self.policy.expected_backend,
            self.policy.expected_model,
        ):
            raise ValueError("profile and policy provider/model identities differ")
        if self.backend_mode is RuntimeBackendMode.REPLAY:
            if self.replay_source_invocation_id is None:
                raise ValueError("replay mode requires replay_source_invocation_id")
        elif self.replay_source_invocation_id is not None:
            raise ValueError("only replay mode can bind replay_source_invocation_id")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class RuntimeLedgerEntry(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    index: int = Field(ge=0)
    completed_at: datetime
    intent: RuntimeInvocationIntent
    outcome: RuntimeOutcome
    result: dict[str, JsonValue] | None = None
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    token_effect: int = Field(default=0, ge=0)
    cost_effect_usd: float | None = Field(default=0.0, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cached: bool = False
    replayed: bool = False
    blockers: tuple[str, ...] = ()
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> RuntimeLedgerEntry:
        unsigned_payload = dict(payload)
        unsigned_payload.pop("entry_sha256", None)
        unsigned = cls.model_construct(entry_sha256=_ZERO_HASH, **unsigned_payload)
        return cls.model_validate(
            {
                **unsigned_payload,
                "entry_sha256": _canonical_sha256(
                    unsigned.model_dump(mode="json", exclude={"entry_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> RuntimeLedgerEntry:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        if (self.result is None) != (self.result_sha256 is None):
            raise ValueError("result and result_sha256 must be present together")
        if self.result is not None and _canonical_sha256(self.result) != self.result_sha256:
            raise ValueError("result_sha256 does not match the result")
        if self.token_effect not in {0, self.input_tokens + self.output_tokens}:
            raise ValueError("token_effect must be zero or the complete response usage")
        if self.cached and (self.token_effect != 0 or self.cost_effect_usd not in {0}):
            raise ValueError("cached evidence cannot advance token or cost totals")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"entry_sha256"}))
        if self.entry_sha256 != expected:
            raise ValueError("entry_sha256 does not match the ledger entry")
        return self


class RuntimeLedgerTotals(RuntimeModel):
    entry_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    planned_count: int = Field(ge=0)
    replay_count: int = Field(ge=0)
    cached_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    chain_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeInvocationReceipt(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    invocation_id: str
    outcome: RuntimeOutcome
    entry_sha256: str
    request_fingerprint: str | None = None
    result: dict[str, JsonValue] | None = None
    totals: RuntimeLedgerTotals
    ledger_locator: str
    recording_locator: str | None = None
    attempt_locator: str | None = None
    blockers: tuple[str, ...] = ()
    generation_envelope: dict[str, JsonValue]
    admission_budget: dict[str, JsonValue]
    cumulative_project_budget: dict[str, JsonValue]
    advisory_only: Literal[True] = True
    executable: Literal[False] = False


class ModelNodeRuntimeError(ValueError):
    """Fail-closed runtime error safe for CLI display."""


class ModelNodeRuntimeConflictError(ModelNodeRuntimeError):
    """Raised when another process owns the same runtime ledger."""


BeforeBackendHook = Callable[[RuntimeInvocationIntent], None]


_NODE_TYPES = {
    "review-semantic": (ReviewSemanticNode, ReviewSemanticInput, ReviewSemanticOutput),
    "interpretation-threat": (
        InterpretationThreatNode,
        InterpretationThreatInput,
        InterpretationThreatOutput,
    ),
    "ambiguous-action": (AmbiguousActionNode, AmbiguousActionInput, AmbiguousActionOutput),
}


class ModelNodeRuntime:
    """Execute proposal-only nodes beneath one existing project run."""

    def __init__(
        self,
        project_runtime: ProjectRuntime,
        *,
        before_backend: BeforeBackendHook | None = None,
    ) -> None:
        self.project_runtime = project_runtime
        self.before_backend = before_backend

    def plan(
        self,
        *,
        project_id: str,
        run_id: str,
        invocation_id: str,
        expected_project_revision: int,
        state_revision: int,
        node_name: str,
        node_input: BaseModel | dict[str, JsonValue],
        context: NodeContext,
        trigger: ModelNodeTrigger,
        profile: ModelNodeProfile,
        policy: NodePolicy,
        backend_mode: RuntimeBackendMode,
        replay_source_invocation_id: str | None = None,
        request_id: str | None = None,
        seed: int = 0,
        allow_live: bool = False,
    ) -> RuntimeInvocationReceipt:
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=expected_project_revision,
            create_stage=False,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        totals = self._totals(project_id, run_id, entries, stage=stage)
        replay_source = next(
            (
                entry
                for entry in entries
                if entry.intent.invocation_id == replay_source_invocation_id
            ),
            None,
        )
        intent = self._intent(
            project_id=project_id,
            run_id=run_id,
            invocation_id=invocation_id,
            project_revision=expected_project_revision,
            state_revision=state_revision,
            node_name=node_name,
            node_input=node_input,
            context=context,
            trigger=trigger,
            profile=profile,
            policy=policy,
            backend_mode=backend_mode,
            replay_source_invocation_id=replay_source_invocation_id,
            request_id=request_id,
            seed=seed,
            predecessor_sha256=totals.chain_head_sha256,
            cumulative_cost_usd=(
                replay_source.intent.context.cumulative_api_cost_usd
                if replay_source is not None
                else totals.cost_usd
            ),
        )
        blockers = self._preflight_blockers(
            intent,
            totals,
            stage=stage,
            allow_live=allow_live,
        )
        if any(
            entry.intent.profile.cumulative_project != profile.cumulative_project
            for entry in entries
        ):
            blockers = (*blockers, "cumulative project budget differs from the ledger")
        if invocation_id in {entry.intent.invocation_id for entry in entries}:
            blockers = (*blockers, "invocation ID already exists")
        return self._receipt(
            intent,
            outcome=RuntimeOutcome.PLANNED,
            entry_sha256=_ZERO_HASH,
            totals=totals,
            blockers=blockers,
        )

    def execute(
        self,
        *,
        backend: StructuredModelBackend | None,
        resume: bool = False,
        allow_live: bool = False,
        **values: Any,
    ) -> RuntimeInvocationReceipt:
        project_id = values["project_id"]
        run_id = values["run_id"]
        expected_revision = values["expected_project_revision"]
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=expected_revision,
            create_stage=True,
        )
        with _exclusive_lock(stage / ".runtime.lock"):
            return self._execute_locked(
                stage=stage,
                backend=backend,
                resume=resume,
                allow_live=allow_live,
                **values,
            )

    def status(self, *, project_id: str, run_id: str) -> RuntimeLedgerTotals:
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=None,
            create_stage=False,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        return self._totals(project_id, run_id, entries, stage=stage)

    def _execute_locked(
        self,
        *,
        stage: Path,
        backend: StructuredModelBackend | None,
        resume: bool,
        allow_live: bool,
        **values: Any,
    ) -> RuntimeInvocationReceipt:
        project_id = values["project_id"]
        run_id = values["run_id"]
        expected_revision = values["expected_project_revision"]
        self._validate_project_run(
            project_id,
            run_id,
            expected_revision=expected_revision,
            create_stage=True,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        completed_ids = {entry.intent.invocation_id for entry in entries}
        invocation_id = values["invocation_id"]
        if invocation_id in completed_ids:
            raise FileExistsError(f"model-node invocation already exists: {invocation_id}")
        totals = self._totals(project_id, run_id, entries, stage=stage)
        replay_source = next(
            (
                entry
                for entry in entries
                if entry.intent.invocation_id == values.get("replay_source_invocation_id")
            ),
            None,
        )
        intent = self._intent(
            project_id=project_id,
            run_id=run_id,
            invocation_id=invocation_id,
            project_revision=expected_revision,
            state_revision=values["state_revision"],
            node_name=values["node_name"],
            node_input=values["node_input"],
            context=values["context"],
            trigger=values["trigger"],
            profile=values["profile"],
            policy=values["policy"],
            backend_mode=values["backend_mode"],
            replay_source_invocation_id=values.get("replay_source_invocation_id"),
            request_id=values.get("request_id"),
            seed=values.get("seed", 0),
            predecessor_sha256=totals.chain_head_sha256,
            cumulative_cost_usd=(
                replay_source.intent.context.cumulative_api_cost_usd
                if replay_source is not None
                else totals.cost_usd
            ),
        )
        pending = self._pending_directories(stage)
        if pending and not resume:
            raise ModelNodeRuntimeError("incomplete model-node attempts require --resume")
        resumed_unknown = self._archive_pending(
            stage,
            pending,
            expected_intent=intent,
        )
        blockers = list(
            self._preflight_blockers(intent, totals, stage=stage, allow_live=allow_live)
        )
        if resumed_unknown:
            blockers.append("an interrupted live attempt has unknown cost")
        if any(
            entry.intent.profile.cumulative_project != intent.profile.cumulative_project
            for entry in entries
        ):
            blockers.append("cumulative project budget differs from the ledger")
        if intent.backend_mode is RuntimeBackendMode.LIVE and backend is not None:
            backend_config = getattr(backend, "config", None)
            if backend_config is None or not getattr(backend_config, "live_enabled", False):
                blockers.append("live backend is not explicitly enabled")
        if blockers or (backend is None and intent.backend_mode is not RuntimeBackendMode.REPLAY):
            if backend is None and intent.backend_mode is not RuntimeBackendMode.REPLAY:
                blockers.append("no backend is bound")
            return self._publish_without_result(
                stage,
                entries,
                intent,
                outcome=RuntimeOutcome.PLANNED,
                blockers=tuple(dict.fromkeys(blockers)),
            )

        recording_path: Path
        if intent.backend_mode is RuntimeBackendMode.REPLAY:
            source_id = intent.replay_source_invocation_id
            assert source_id is not None
            recording_path = stage / "recordings" / f"{source_id}.jsonl"
            backend = ReplayStructuredBackend(recording_path)
        else:
            assert backend is not None
            recording_path = stage / "recordings" / f"{invocation_id}.jsonl"
            if recording_path.exists():
                raise FileExistsError(recording_path)
            backend = RecordingStructuredBackend(backend, recording_path)

        pending_dir = stage / "pending" / f"{invocation_id}--{time.time_ns()}--{os.getpid()}"
        pending_dir.mkdir(parents=True, exist_ok=False)
        _write_model_exclusive(pending_dir / "intent.json", intent)
        _write_bytes_exclusive(pending_dir / "backend-started", b"started\n")
        try:
            if self.before_backend is not None:
                self.before_backend(intent)
            node_type, input_type, _ = _NODE_TYPES[intent.node_name]
            typed_input = input_type.model_validate(intent.node_input, strict=True)
            result = node_type().run(
                typed_input,
                context=intent.context,
                backend=backend,
                policy=intent.policy,
                request_id=intent.request_id,
                seed=intent.seed,
                profile=intent.profile,
            )
            result = self._apply_cumulative_gates(result, totals, intent.profile)
            entry = self._entry_from_result(
                index=len(entries),
                intent=intent,
                result=result,
                recording_path=recording_path,
                replayed=intent.backend_mode is RuntimeBackendMode.REPLAY,
            )
        except NodeNotApplicableError as exc:
            entry = RuntimeLedgerEntry.create(
                index=len(entries),
                completed_at=datetime.now(UTC),
                intent=intent,
                outcome=RuntimeOutcome.NOT_APPLICABLE,
                blockers=(str(exc),),
                cost_effect_usd=0.0,
                entry_sha256=_ZERO_HASH,
            )
        except Exception:
            recorded_response = _last_recorded_response(recording_path)
            unknown_cost = (
                recorded_response is not None and recorded_response.usage.cost_usd is None
            ) or (recorded_response is None and intent.backend_mode is RuntimeBackendMode.LIVE)
            archived = self._archive_one_pending(stage, pending_dir, unknown_cost=unknown_cost)
            entry = RuntimeLedgerEntry.create(
                index=len(entries),
                completed_at=datetime.now(UTC),
                intent=intent,
                outcome=RuntimeOutcome.FAILED,
                input_tokens=(
                    recorded_response.usage.input_tokens if recorded_response is not None else 0
                ),
                output_tokens=(
                    recorded_response.usage.output_tokens if recorded_response is not None else 0
                ),
                token_effect=(
                    recorded_response.usage.input_tokens + recorded_response.usage.output_tokens
                    if recorded_response is not None and not recorded_response.cached
                    else 0
                ),
                cost_effect_usd=(
                    None
                    if unknown_cost
                    else (
                        recorded_response.usage.cost_usd
                        if recorded_response is not None and not recorded_response.cached
                        else 0.0
                    )
                ),
                latency_ms=(recorded_response.latency_ms if recorded_response is not None else 0),
                cached=(recorded_response.cached if recorded_response is not None else False),
                replayed=intent.backend_mode is RuntimeBackendMode.REPLAY,
                blockers=("model-node invocation failed; inspect archived attempt evidence",),
                entry_sha256=_ZERO_HASH,
            )
            _write_model_exclusive(self._entry_path(stage, entry), entry)
            totals = self._totals(project_id, run_id, [*entries, entry], stage=stage)
            return self._receipt(
                intent,
                outcome=entry.outcome,
                entry_sha256=entry.entry_sha256,
                totals=totals,
                blockers=entry.blockers,
                attempt_locator=archived,
            )

        _write_model_exclusive(self._entry_path(stage, entry), entry)
        if pending_dir.exists():
            _remove_empty_pending(pending_dir)
        totals = self._totals(project_id, run_id, [*entries, entry], stage=stage)
        return self._receipt(
            intent,
            outcome=entry.outcome,
            entry_sha256=entry.entry_sha256,
            totals=totals,
            result=entry.result,
            request_fingerprint=entry.request_fingerprint,
            blockers=entry.blockers,
            recording_path=recording_path if recording_path.is_file() else None,
        )

    def _intent(
        self,
        *,
        cumulative_cost_usd: float,
        node_input: BaseModel | dict[str, JsonValue],
        context: NodeContext,
        profile: ModelNodeProfile,
        policy: NodePolicy,
        node_name: str,
        invocation_id: str,
        request_id: str | None,
        **values: Any,
    ) -> RuntimeInvocationIntent:
        if node_name not in _NODE_TYPES:
            raise ModelNodeRuntimeError(f"unsupported model-node type {node_name!r}")
        validate_profile_binding(profile, policy, node_name=node_name)
        input_type = _NODE_TYPES[node_name][1]
        input_payload = (
            node_input.model_dump(mode="json") if isinstance(node_input, BaseModel) else node_input
        )
        typed_input = input_type.model_validate(input_payload, strict=True)
        effective_context = NodeContext.model_validate(
            {
                **context.model_dump(mode="json"),
                "cumulative_api_cost_usd": cumulative_cost_usd,
            },
            strict=True,
        )
        return RuntimeInvocationIntent(
            invocation_id=invocation_id,
            request_id=request_id or invocation_id,
            node_name=node_name,
            node_input=typed_input.model_dump(mode="json"),
            context=effective_context,
            profile=profile,
            policy=policy,
            **values,
        )

    def _preflight_blockers(
        self,
        intent: RuntimeInvocationIntent,
        totals: RuntimeLedgerTotals,
        *,
        stage: Path,
        allow_live: bool,
    ) -> tuple[str, ...]:
        budget = intent.profile.cumulative_project
        blockers: list[str] = []
        if totals.unknown_cost_count:
            blockers.append("cumulative ledger contains unknown cost")
        if totals.entry_count >= budget.max_invocations:
            blockers.append("cumulative invocation budget exhausted")
        if totals.total_tokens >= budget.max_total_tokens:
            blockers.append("cumulative token budget exhausted")
        if totals.cost_usd >= budget.max_api_cost_usd:
            blockers.append("cumulative API cost budget exhausted")
        if intent.backend_mode is RuntimeBackendMode.LIVE:
            if not intent.profile.live_execution_permitted:
                blockers.append("profile does not permit live execution")
            if not allow_live:
                blockers.append("caller did not opt in to live execution")
        if intent.backend_mode is RuntimeBackendMode.REPLAY:
            source = intent.replay_source_invocation_id
            assert source is not None
            if not (stage / "recordings" / f"{source}.jsonl").is_file():
                blockers.append("exact replay source recording is missing")
        return tuple(blockers)

    def _apply_cumulative_gates(
        self,
        result: NodeResult[Any],
        totals: RuntimeLedgerTotals,
        profile: ModelNodeProfile,
    ) -> NodeResult[Any]:
        if result.response.cached:
            return result
        reasons: list[str] = []
        response_tokens = result.response.usage.input_tokens + result.response.usage.output_tokens
        if totals.total_tokens + response_tokens > profile.cumulative_project.max_total_tokens:
            reasons.append("cumulative project token budget exceeded")
        cost = result.response.usage.cost_usd
        if cost is None:
            reasons.append("cumulative project cost is unknown")
        elif totals.cost_usd + cost > profile.cumulative_project.max_api_cost_usd:
            reasons.append("cumulative project API cost budget exceeded")
        if not reasons:
            return result
        payload = result.model_dump(mode="python", exclude_computed_fields=True)
        proposal = payload.pop("proposal")
        payload["status"] = NodeResultStatus.REJECTED
        payload["proposal"] = None
        if payload.get("untrusted_proposal") is None:
            payload["untrusted_proposal"] = proposal
        payload["rejection_reasons"] = [*payload["rejection_reasons"], *reasons]
        return type(result).model_validate(payload)

    def _entry_from_result(
        self,
        *,
        index: int,
        intent: RuntimeInvocationIntent,
        result: NodeResult[Any],
        recording_path: Path,
        replayed: bool,
    ) -> RuntimeLedgerEntry:
        result_payload = result.model_dump(mode="json", exclude_computed_fields=True)
        response = result.response
        cached = response.cached
        outcome = (
            RuntimeOutcome.ACCEPTED
            if result.status is NodeResultStatus.ACCEPTED
            else RuntimeOutcome.REJECTED
        )
        return RuntimeLedgerEntry.create(
            index=index,
            completed_at=datetime.now(UTC),
            intent=intent,
            outcome=outcome,
            result=result_payload,
            result_sha256=_canonical_sha256(result_payload),
            request_fingerprint=result.request.fingerprint,
            recording_sha256=_sha256_file(recording_path),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            token_effect=(
                0 if cached else response.usage.input_tokens + response.usage.output_tokens
            ),
            cost_effect_usd=0.0 if cached else response.usage.cost_usd,
            latency_ms=response.latency_ms,
            cached=cached,
            replayed=replayed,
            blockers=tuple(result.rejection_reasons),
            entry_sha256=_ZERO_HASH,
        )

    def _publish_without_result(
        self,
        stage: Path,
        entries: list[RuntimeLedgerEntry],
        intent: RuntimeInvocationIntent,
        *,
        outcome: RuntimeOutcome,
        blockers: tuple[str, ...],
    ) -> RuntimeInvocationReceipt:
        entry = RuntimeLedgerEntry.create(
            index=len(entries),
            completed_at=datetime.now(UTC),
            intent=intent,
            outcome=outcome,
            cost_effect_usd=0.0,
            blockers=blockers,
            entry_sha256=_ZERO_HASH,
        )
        _write_model_exclusive(self._entry_path(stage, entry), entry)
        totals = self._totals(
            intent.project_id,
            intent.run_id,
            [*entries, entry],
            stage=stage,
        )
        return self._receipt(
            intent,
            outcome=outcome,
            entry_sha256=entry.entry_sha256,
            totals=totals,
            blockers=blockers,
        )

    def _load_ledger(
        self,
        stage: Path,
        *,
        project_id: str,
        run_id: str,
    ) -> list[RuntimeLedgerEntry]:
        root = stage / "ledger"
        paths = sorted(root.glob("*.json")) if root.exists() else []
        entries: list[RuntimeLedgerEntry] = []
        predecessor = self._root_hash(project_id, run_id)
        for index, path in enumerate(paths):
            expected_name_prefix = f"{index:08d}__"
            if not path.name.startswith(expected_name_prefix):
                raise ModelNodeRuntimeError("runtime ledger is not a contiguous prefix")
            entry = _load_model(path, RuntimeLedgerEntry)
            if entry.index != index:
                raise ModelNodeRuntimeError("runtime ledger index drift")
            if entry.intent.project_id != project_id or entry.intent.run_id != run_id:
                raise ModelNodeRuntimeError("runtime ledger entry belongs to another project run")
            if entry.intent.predecessor_sha256 != predecessor:
                raise ModelNodeRuntimeError("runtime ledger predecessor chain drift")
            if path.name != self._entry_path(stage, entry).name:
                raise ModelNodeRuntimeError("runtime ledger filename identity drift")
            if entry.recording_sha256 is not None:
                source_id = (
                    entry.intent.replay_source_invocation_id
                    if entry.replayed
                    else entry.intent.invocation_id
                )
                assert source_id is not None
                recording = stage / "recordings" / f"{source_id}.jsonl"
                if not recording.is_file() or _sha256_file(recording) != entry.recording_sha256:
                    raise ModelNodeRuntimeError("runtime recording evidence drift")
            try:
                self._validate_typed_result(entry)
            except ValueError as exc:
                raise ModelNodeRuntimeError("invalid typed result in runtime ledger") from exc
            entries.append(entry)
            predecessor = entry.entry_sha256
        return entries

    def _validate_typed_result(self, entry: RuntimeLedgerEntry) -> None:
        if entry.result is None:
            return
        output_type = _NODE_TYPES[entry.intent.node_name][2]
        result_type = NodeResult[output_type]
        result = result_type.model_validate_json(
            json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        if result.node_name != entry.intent.node_name:
            raise ModelNodeRuntimeError("ledger result node identity drift")
        if result.policy_id != entry.intent.policy.policy_id:
            raise ModelNodeRuntimeError("ledger result policy identity drift")
        if result.request.profile_fingerprint != entry.intent.profile.fingerprint:
            raise ModelNodeRuntimeError("ledger result profile identity drift")
        if result.request.fingerprint != entry.request_fingerprint:
            raise ModelNodeRuntimeError("ledger result request fingerprint drift")

    def _totals(
        self,
        project_id: str,
        run_id: str,
        entries: list[RuntimeLedgerEntry],
        *,
        stage: Path,
    ) -> RuntimeLedgerTotals:
        outcomes = [entry.outcome for entry in entries]
        completed_ids = {entry.intent.invocation_id for entry in entries}
        archives = [
            self._load_archived_attempt(path)
            for path in sorted((stage / "attempts").glob("*/failure.json"))
        ]
        unknown_archives = sum(
            archive.unknown_cost and archive.invocation_id not in completed_ids
            for archive in archives
        )
        unknown_pending = sum(
            intent.backend_mode is RuntimeBackendMode.LIVE
            and (directory / "backend-started").is_file()
            and intent.invocation_id not in completed_ids
            for directory in self._pending_directories(stage)
            for intent in [_load_model(directory / "intent.json", RuntimeInvocationIntent)]
        )
        return RuntimeLedgerTotals(
            entry_count=len(entries),
            accepted_count=outcomes.count(RuntimeOutcome.ACCEPTED),
            rejected_count=outcomes.count(RuntimeOutcome.REJECTED),
            not_applicable_count=outcomes.count(RuntimeOutcome.NOT_APPLICABLE),
            failed_count=outcomes.count(RuntimeOutcome.FAILED),
            planned_count=outcomes.count(RuntimeOutcome.PLANNED),
            replay_count=sum(entry.replayed for entry in entries),
            cached_count=sum(entry.cached for entry in entries),
            input_tokens=sum(entry.input_tokens for entry in entries),
            output_tokens=sum(entry.output_tokens for entry in entries),
            total_tokens=sum(entry.token_effect for entry in entries),
            cost_usd=sum(entry.cost_effect_usd or 0.0 for entry in entries),
            unknown_cost_count=sum(entry.cost_effect_usd is None for entry in entries)
            + unknown_archives
            + unknown_pending,
            latency_ms=sum(entry.latency_ms for entry in entries),
            chain_head_sha256=(
                entries[-1].entry_sha256 if entries else self._root_hash(project_id, run_id)
            ),
        )

    @staticmethod
    def _load_archived_attempt(path: Path) -> _ArchivedAttempt:
        archive = _load_model(path, _ArchivedAttempt)
        recording = path.parent / "recording.jsonl"
        if archive.recording_sha256 is None:
            if recording.exists():
                raise ModelNodeRuntimeError("unexpected archived recording evidence")
        elif (
            not recording.is_file()
            or recording.is_symlink()
            or _sha256_file(recording) != archive.recording_sha256
        ):
            raise ModelNodeRuntimeError("archived recording evidence drift")
        return archive

    def _archive_pending(
        self,
        stage: Path,
        pending: list[Path],
        *,
        expected_intent: RuntimeInvocationIntent,
    ) -> bool:
        unknown = False
        for directory in pending:
            intent = _load_model(directory / "intent.json", RuntimeInvocationIntent)
            if (
                intent.invocation_id == expected_intent.invocation_id
                and intent.fingerprint != expected_intent.fingerprint
            ):
                raise ModelNodeRuntimeError("resume invocation identity drift")
            may_have_started = (directory / "backend-started").is_file()
            unknown_cost = may_have_started and intent.backend_mode is RuntimeBackendMode.LIVE
            self._archive_one_pending(stage, directory, unknown_cost=unknown_cost)
            unknown = unknown or unknown_cost
        return unknown

    def _archive_one_pending(
        self,
        stage: Path,
        directory: Path,
        *,
        unknown_cost: bool,
    ) -> str:
        attempt_id = directory.name
        target = stage / "attempts" / attempt_id
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(directory, target)
        intent = _load_model(target / "intent.json", RuntimeInvocationIntent)
        recording_sha256 = None
        if intent.backend_mode is not RuntimeBackendMode.REPLAY:
            recording = stage / "recordings" / f"{intent.invocation_id}.jsonl"
            if recording.is_file():
                recording_sha256 = _sha256_file(recording)
                os.replace(recording, target / "recording.jsonl")
        failure = _ArchivedAttempt.create(
            attempt_id=attempt_id,
            archived_at=datetime.now(UTC),
            invocation_id=intent.invocation_id,
            intent_sha256=intent.fingerprint,
            backend_may_have_started=(target / "backend-started").is_file(),
            unknown_cost=unknown_cost,
            recording_sha256=recording_sha256,
            failure_sha256=_ZERO_HASH,
        )
        _write_model_exclusive(target / "failure.json", failure)
        return (
            f"projects/{intent.project_id}/runs/{intent.run_id}/"
            f"{MODEL_NODE_STAGE_PATH}/attempts/{attempt_id}"
        )

    @staticmethod
    def _pending_directories(stage: Path) -> list[Path]:
        root = stage / "pending"
        return sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []

    def _validate_project_run(
        self,
        project_id: str,
        run_id: str,
        *,
        expected_revision: int | None,
        create_stage: bool,
    ) -> tuple[Path, ProjectRun]:
        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        snapshot = self.project_runtime.open(project_id)
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise ProjectRevisionConflictError(
                f"stale project revision {expected_revision}; current is {snapshot.revision}"
            )
        try:
            run = next(item for item in snapshot.manifest.runs if item.run_id == run_id)
        except StopIteration as exc:
            raise ModelNodeRuntimeError(f"unknown project run {run_id!r}") from exc
        stage = (
            self.project_runtime.outputs_root
            / "projects"
            / project_id
            / "runs"
            / run_id
            / MODEL_NODE_STAGE_PATH
        )
        if os.path.lexists(stage):
            if stage.resolve(strict=True) != stage or not stage.is_dir():
                raise ModelNodeRuntimeError("model-node stage escapes its project-owned path")
        elif create_stage:
            stage.mkdir(parents=False)
        return stage, run

    @staticmethod
    def _root_hash(project_id: str, run_id: str) -> str:
        return _canonical_sha256(
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "run_id": run_id,
                "stage_path": MODEL_NODE_STAGE_PATH,
            }
        )

    @staticmethod
    def _entry_path(stage: Path, entry: RuntimeLedgerEntry) -> Path:
        return stage / "ledger" / f"{entry.index:08d}__{entry.intent.invocation_id}.json"

    def _receipt(
        self,
        intent: RuntimeInvocationIntent,
        *,
        outcome: RuntimeOutcome,
        entry_sha256: str,
        totals: RuntimeLedgerTotals,
        result: dict[str, JsonValue] | None = None,
        request_fingerprint: str | None = None,
        blockers: tuple[str, ...] = (),
        recording_path: Path | None = None,
        attempt_locator: str | None = None,
    ) -> RuntimeInvocationReceipt:
        base = f"projects/{intent.project_id}/runs/{intent.run_id}/{MODEL_NODE_STAGE_PATH}"
        return RuntimeInvocationReceipt(
            project_id=intent.project_id,
            run_id=intent.run_id,
            invocation_id=intent.invocation_id,
            outcome=outcome,
            entry_sha256=entry_sha256,
            request_fingerprint=request_fingerprint,
            result=result,
            totals=totals,
            ledger_locator=f"{base}/ledger",
            recording_locator=(
                f"{base}/recordings/{recording_path.name}" if recording_path is not None else None
            ),
            attempt_locator=attempt_locator,
            blockers=blockers,
            generation_envelope=intent.profile.generation.model_dump(mode="json"),
            admission_budget=intent.profile.admission.model_dump(mode="json"),
            cumulative_project_budget=intent.profile.cumulative_project.model_dump(mode="json"),
        )


class _ArchivedAttempt(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    attempt_id: str
    archived_at: datetime
    invocation_id: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_may_have_started: bool
    unknown_cost: bool
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> _ArchivedAttempt:
        unsigned_payload = dict(payload)
        unsigned_payload.pop("failure_sha256", None)
        unsigned = cls.model_construct(failure_sha256=_ZERO_HASH, **unsigned_payload)
        return cls.model_validate(
            {
                **unsigned_payload,
                "failure_sha256": _canonical_sha256(
                    unsigned.model_dump(mode="json", exclude={"failure_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def hash_matches(self) -> _ArchivedAttempt:
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"failure_sha256"}))
        if self.failure_sha256 != expected:
            raise ValueError("failure_sha256 does not match archived attempt")
        return self


def _canonical_sha256(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_computed_fields=True)
    raw = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _last_recorded_response(path: Path) -> StructuredModelResponse | None:
    """Read trusted response telemetry without reflecting provider payloads in errors."""

    if not path.is_file() or path.is_symlink():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        return StructuredReplayRecord.model_validate_json(lines[-1], strict=True).response
    except (OSError, ValueError):
        return None


def _load_model(path: Path, model_type: type[BaseModel]) -> Any:
    if not path.is_file() or path.is_symlink():
        raise ModelNodeRuntimeError(f"missing or unsafe runtime evidence: {path.name}")
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
    except ValueError as exc:
        raise ModelNodeRuntimeError(f"invalid runtime evidence: {path.name}") from exc


def _write_model_exclusive(path: Path, value: BaseModel) -> None:
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
    _write_bytes_exclusive(path, payload)


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
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
            raise FileExistsError(f"refusing to overwrite runtime evidence: {path}") from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_empty_pending(path: Path) -> None:
    for item in path.iterdir():
        item.unlink()
    path.rmdir()
    _fsync_directory(path.parent)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ModelNodeRuntimeConflictError(
                "another writer owns this model-node ledger"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MODEL_NODE_STAGE_PATH",
    "ModelNodeRuntime",
    "ModelNodeRuntimeConflictError",
    "ModelNodeRuntimeError",
    "ModelNodeTrigger",
    "RuntimeBackendMode",
    "RuntimeInvocationIntent",
    "RuntimeInvocationReceipt",
    "RuntimeLedgerEntry",
    "RuntimeLedgerTotals",
    "RuntimeOutcome",
]

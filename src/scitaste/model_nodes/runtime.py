"""Durable, project-scoped execution runtime for bounded model nodes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
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
    StructuredModelRequest,
    StructuredModelResponse,
)
from scitaste.model_nodes.nodes import (
    AmbiguousActionNode,
    InterpretationThreatNode,
    ModelNode,
    NodeNotApplicableError,
    ReviewSemanticNode,
    StructuredRepairNode,
    ToolPlanNode,
    VenuePaperReviewNode,
)
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.replay import (
    RecordedResponseRecoveryBackend,
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
    VenuePaperReviewInput,
    VenuePaperReviewProposal,
)
from scitaste.model_nodes.tool_intelligence import (
    StructuredRepairInput,
    StructuredRepairOutput,
    ToolPlanInput,
    ToolPlanOutput,
)
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRevisionConflictError

MODEL_NODE_STAGE_PATH = "model_nodes"
_ZERO_HASH = "0" * 64
_RUNTIME_DIRECTORIES = frozenset({"attempts", "ledger", "pending", "recordings"})
_RETIRED_PENDING_PREFIX = ".published--"


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeBackendMode(StrEnum):
    SCRIPTED = "scripted"
    LIVE = "live"
    LOCAL = "local"
    REPLAY = "replay"


def _is_actual_generation_mode(mode: RuntimeBackendMode) -> bool:
    return mode in {RuntimeBackendMode.LIVE, RuntimeBackendMode.LOCAL}


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
    node_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
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
    expected_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
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


class RuntimeInvocationTelemetry(RuntimeModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=0.0, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cached: bool = False
    replayed: bool = False


class RuntimeInvocationReceipt(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    invocation_id: str
    outcome: RuntimeOutcome
    entry_sha256: str
    request_fingerprint: str | None = None
    result: dict[str, JsonValue] | None = None
    telemetry: RuntimeInvocationTelemetry = Field(default_factory=RuntimeInvocationTelemetry)
    totals: RuntimeLedgerTotals
    ledger_locator: str
    recording_locator: str | None = None
    attempt_locator: str | None = None
    blockers: tuple[str, ...] = ()
    recovered_without_provider: bool = False
    generation_envelope: dict[str, JsonValue]
    admission_budget: dict[str, JsonValue]
    cumulative_project_budget: dict[str, JsonValue]
    advisory_only: Literal[True] = True
    executable: Literal[False] = False


class RuntimeVerification(RuntimeModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    verified: Literal[True] = True
    totals: RuntimeLedgerTotals
    profiles: tuple[ModelNodeProfile, ...]
    ledger_locator: str
    attempt_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)


class ModelNodeRuntimeError(ValueError):
    """Fail-closed runtime error safe for CLI display."""


class ModelNodeRuntimeConflictError(ModelNodeRuntimeError):
    """Raised when another process owns the same runtime ledger."""


BeforeBackendHook = Callable[[RuntimeInvocationIntent], None]


@dataclass(frozen=True)
class _PendingResume:
    intent: RuntimeInvocationIntent
    directory: Path
    recording_path: Path
    backend: RecordedResponseRecoveryBackend | None


@dataclass(frozen=True)
class ModelNodeRegistration:
    """One typed node extension understood by the durable runtime."""

    node_type: type[ModelNode[Any, Any]]
    input_type: type[BaseModel]
    output_type: type[BaseModel]


_NODE_TYPES = {
    "review-semantic": ModelNodeRegistration(
        ReviewSemanticNode, ReviewSemanticInput, ReviewSemanticOutput
    ),
    "interpretation-threat": ModelNodeRegistration(
        InterpretationThreatNode,
        InterpretationThreatInput,
        InterpretationThreatOutput,
    ),
    "ambiguous-action": ModelNodeRegistration(
        AmbiguousActionNode, AmbiguousActionInput, AmbiguousActionOutput
    ),
    "tool-plan": ModelNodeRegistration(ToolPlanNode, ToolPlanInput, ToolPlanOutput),
    "structured-repair": ModelNodeRegistration(
        StructuredRepairNode,
        StructuredRepairInput,
        StructuredRepairOutput,
    ),
    "venue-paper-review": ModelNodeRegistration(
        VenuePaperReviewNode,
        VenuePaperReviewInput,
        VenuePaperReviewProposal,
    ),
}


class _PreCallValidatedBackend:
    """Run the revision/attempt guard at the actual backend-call boundary."""

    def __init__(
        self,
        delegate: StructuredModelBackend,
        before_call: Callable[[], None],
    ) -> None:
        self.delegate = delegate
        self.before_call = before_call
        self.name = delegate.name
        self.model = delegate.model

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.before_call()
        return self.delegate.complete(request)


class ModelNodeRuntime:
    """Execute proposal-only nodes beneath one existing project run."""

    def __init__(
        self,
        project_runtime: ProjectRuntime,
        *,
        before_backend: BeforeBackendHook | None = None,
        node_types: Mapping[str, ModelNodeRegistration] | None = None,
    ) -> None:
        self.project_runtime = project_runtime
        self.before_backend = before_backend
        self.node_types = dict(_NODE_TYPES)
        for name, registration in (node_types or {}).items():
            if name in self.node_types:
                raise ValueError(f"model-node extension cannot replace built-in node {name!r}")
            instance = registration.node_type()
            if name != instance.node_name:
                raise ValueError("model-node extension name does not match its node type")
            if (
                instance.input_model is not registration.input_type
                or instance.output_model is not registration.output_type
            ):
                raise ValueError("model-node extension registration types do not match its node")
            self.node_types[name] = registration

    def plan(
        self,
        *,
        backend: StructuredModelBackend | None = None,
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
        allow_local: bool = False,
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
            allow_local=allow_local,
            backend=backend,
        )
        if any(
            entry.intent.profile.cumulative_project != profile.cumulative_project
            for entry in entries
        ):
            blockers = (*blockers, "cumulative project budget differs from the ledger")
        if invocation_id in {entry.intent.invocation_id for entry in entries}:
            blockers = (*blockers, "invocation ID already exists")
        if self._pending_directories(stage):
            blockers = (*blockers, "incomplete model-node attempts require resume")
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
        allow_local: bool = False,
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
        _validate_runtime_layout(stage)
        with _exclusive_lock(stage / ".runtime.lock"):
            return self._execute_locked(
                stage=stage,
                backend=backend,
                resume=resume,
                allow_live=allow_live,
                allow_local=allow_local,
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

    def verify(self, *, project_id: str, run_id: str) -> RuntimeVerification:
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=None,
            create_stage=False,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        totals = self._totals(project_id, run_id, entries, stage=stage)
        profiles = {entry.intent.profile.fingerprint: entry.intent.profile for entry in entries}
        base = f"projects/{project_id}/runs/{run_id}/{MODEL_NODE_STAGE_PATH}"
        return RuntimeVerification(
            project_id=project_id,
            run_id=run_id,
            totals=totals,
            profiles=tuple(profiles[key] for key in sorted(profiles)),
            ledger_locator=f"{base}/ledger",
            attempt_count=len(_archived_attempt_paths(stage)),
            pending_count=len(self._pending_directories(stage)),
        )

    def entry(
        self,
        *,
        project_id: str,
        run_id: str,
        invocation_id: str,
    ) -> RuntimeLedgerEntry:
        """Read one entry only after validating the complete chained ledger."""

        entry = self.find_entry(
            project_id=project_id,
            run_id=run_id,
            invocation_id=invocation_id,
        )
        if entry is None:
            raise ModelNodeRuntimeError(
                f"model-node invocation is not a unique committed entry: {invocation_id!r}"
            )
        return entry

    def find_entry(
        self,
        *,
        project_id: str,
        run_id: str,
        invocation_id: str,
    ) -> RuntimeLedgerEntry | None:
        """Return one verified entry or ``None`` without hiding ledger corruption."""

        validate_entry_id(invocation_id, field_name="invocation_id")
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=None,
            create_stage=False,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        matches = [item for item in entries if item.intent.invocation_id == invocation_id]
        if len(matches) > 1:
            raise ModelNodeRuntimeError(
                f"model-node invocation is not a unique committed entry: {invocation_id!r}"
            )
        return matches[0] if matches else None

    def totals_through_entry(
        self,
        *,
        project_id: str,
        run_id: str,
        invocation_id: str,
    ) -> RuntimeLedgerTotals:
        """Return verified cumulative totals at one historical ledger entry."""

        validate_entry_id(invocation_id, field_name="invocation_id")
        stage, _ = self._validate_project_run(
            project_id,
            run_id,
            expected_revision=None,
            create_stage=False,
        )
        entries = self._load_ledger(stage, project_id=project_id, run_id=run_id)
        matches = [
            index
            for index, item in enumerate(entries)
            if item.intent.invocation_id == invocation_id
        ]
        if len(matches) != 1:
            raise ModelNodeRuntimeError(
                f"model-node invocation is not a unique committed entry: {invocation_id!r}"
            )
        return self._totals(
            project_id,
            run_id,
            entries[: matches[0] + 1],
            stage=stage,
        )

    def _execute_locked(
        self,
        *,
        stage: Path,
        backend: StructuredModelBackend | None,
        resume: bool,
        allow_live: bool,
        allow_local: bool,
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
        _cleanup_retired_pending(stage)
        completed = {entry.intent.invocation_id: entry for entry in entries}
        completed_ids = set(completed)
        invocation_id = values["invocation_id"]
        if invocation_id in completed_ids:
            entry = completed[invocation_id]
            pending = self._pending_directories(stage)
            if not resume:
                if pending:
                    raise ModelNodeRuntimeError("incomplete model-node attempts require --resume")
                raise FileExistsError(f"model-node invocation already exists: {invocation_id}")
            resumed_intent = self._intent(
                project_id=project_id,
                run_id=run_id,
                invocation_id=invocation_id,
                project_revision=entry.intent.project_revision,
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
                predecessor_sha256=entry.intent.predecessor_sha256,
                cumulative_cost_usd=entry.intent.context.cumulative_api_cost_usd,
            )
            if resumed_intent.fingerprint != entry.intent.fingerprint:
                raise ModelNodeRuntimeError("resume invocation identity drift")
            if pending:
                attempt_locator = self._archive_completed_pending(
                    stage,
                    pending,
                    completed=completed,
                    invocation_id=invocation_id,
                )
                totals = self._totals(project_id, run_id, entries, stage=stage)
                recording_id = (
                    entry.intent.replay_source_invocation_id
                    if entry.replayed
                    else entry.intent.invocation_id
                )
                recordings = _runtime_directory(stage, "recordings")
                recording_path = (
                    recordings / f"{recording_id}.jsonl" if recordings is not None else None
                )
                return self._receipt(
                    entry.intent,
                    outcome=entry.outcome,
                    entry_sha256=entry.entry_sha256,
                    totals=totals,
                    result=entry.result,
                    request_fingerprint=entry.request_fingerprint,
                    blockers=entry.blockers,
                    recording_path=(
                        recording_path
                        if recording_path is not None
                        and recording_path.is_file()
                        and not recording_path.is_symlink()
                        else None
                    ),
                    attempt_locator=attempt_locator,
                    recovered_without_provider=(
                        _is_actual_generation_mode(entry.intent.backend_mode)
                    ),
                    entry=entry,
                )
            totals = self._totals(project_id, run_id, entries, stage=stage)
            recording_id = (
                entry.intent.replay_source_invocation_id
                if entry.replayed
                else entry.intent.invocation_id
            )
            recording_path = _runtime_directory(stage, "recordings")
            recording = (
                recording_path / f"{recording_id}.jsonl" if recording_path is not None else None
            )
            return self._receipt(
                entry.intent,
                outcome=entry.outcome,
                entry_sha256=entry.entry_sha256,
                totals=totals,
                result=entry.result,
                request_fingerprint=entry.request_fingerprint,
                blockers=entry.blockers,
                recording_path=(
                    recording if recording is not None and recording.is_file() else None
                ),
                recovered_without_provider=_is_actual_generation_mode(entry.intent.backend_mode),
                entry=entry,
            )
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
        pending_resume = (
            self._resume_pending(
                stage,
                pending,
                totals=totals,
                **values,
            )
            if pending and resume
            else None
        )
        if pending_resume is not None:
            intent = pending_resume.intent
        admission_totals = totals
        if pending_resume is not None and pending_resume.backend is not None:
            admission_totals = totals.model_copy(
                update={"unknown_cost_count": max(0, totals.unknown_cost_count - 1)}
            )
        if pending and not resume:
            raise ModelNodeRuntimeError("incomplete model-node attempts require --resume")
        resumed_unknown = False
        if pending_resume is None or pending_resume.backend is None:
            resumed_unknown = self._archive_pending(
                stage,
                pending,
                expected_intent=intent,
            )
        blockers = list(
            self._preflight_blockers(
                intent,
                admission_totals,
                stage=stage,
                allow_live=allow_live,
                allow_local=allow_local,
                backend=backend,
            )
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
        if intent.backend_mode is RuntimeBackendMode.LOCAL and backend is not None:
            backend_config = getattr(backend, "config", None)
            if backend_config is None or not getattr(backend_config, "execution_enabled", False):
                blockers.append("local backend is not explicitly enabled")
        if blockers or (backend is None and intent.backend_mode is not RuntimeBackendMode.REPLAY):
            if backend is None and intent.backend_mode is not RuntimeBackendMode.REPLAY:
                blockers.append("no backend is bound")
            if pending_resume is not None and pending_resume.backend is not None:
                raise ModelNodeRuntimeError(
                    "recoverable model response requires its original execution authorization"
                )
            return self._publish_without_result(
                stage,
                entries,
                intent,
                outcome=RuntimeOutcome.PLANNED,
                blockers=tuple(dict.fromkeys(blockers)),
            )

        recording_path: Path
        if pending_resume is not None and pending_resume.backend is not None:
            recording_path = pending_resume.recording_path
            backend = pending_resume.backend
        elif intent.backend_mode is RuntimeBackendMode.REPLAY:
            source_id = intent.replay_source_invocation_id
            assert source_id is not None
            recordings = _runtime_directory(stage, "recordings", create=True)
            assert recordings is not None
            recording_path = recordings / f"{source_id}.jsonl"
            backend = ReplayStructuredBackend(recording_path)
        else:
            assert backend is not None
            recordings = _runtime_directory(stage, "recordings", create=True)
            assert recordings is not None
            recording_path = recordings / f"{invocation_id}.jsonl"
            if os.path.lexists(recording_path):
                raise FileExistsError(recording_path)
            backend = RecordingStructuredBackend(backend, recording_path)

        if pending_resume is not None and pending_resume.backend is not None:
            pending_dir = pending_resume.directory
        else:
            pending_root = _runtime_directory(stage, "pending", create=True)
            assert pending_root is not None
            pending_dir = pending_root / f"{invocation_id}--{time.time_ns()}--{os.getpid()}"
            pending_dir.mkdir(parents=True, exist_ok=False)
            _write_model_exclusive(pending_dir / "intent.json", intent, owned_root=stage)
        try:
            if self.before_backend is not None and not (
                pending_resume is not None and pending_resume.backend is not None
            ):
                self.before_backend(intent)

            def before_call() -> None:
                self._validate_project_run(
                    project_id,
                    run_id,
                    expected_revision=expected_revision,
                    create_stage=True,
                )
                _write_bytes_exclusive(
                    pending_dir / "backend-started",
                    b"started\n",
                    owned_root=stage,
                )

            guarded_backend = (
                backend
                if pending_resume is not None and pending_resume.backend is not None
                else _PreCallValidatedBackend(backend, before_call)
            )
            registration = self.node_types[intent.node_name]
            typed_input = registration.input_type.model_validate_json(
                json.dumps(intent.node_input, ensure_ascii=False, allow_nan=False),
                strict=True,
            )
            result = registration.node_type().run(
                typed_input,
                context=intent.context,
                backend=guarded_backend,
                policy=intent.policy,
                request_id=intent.request_id,
                seed=intent.seed,
                profile=intent.profile,
            )
            result = self._apply_cumulative_gates(result, admission_totals, intent.profile)
            result = self._apply_project_revision_gate(
                result,
                project_id=project_id,
                run_id=run_id,
                expected_revision=intent.project_revision,
            )
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
        except Exception as exc:
            recorded_response = (
                None
                if intent.backend_mode is RuntimeBackendMode.REPLAY
                else _last_recorded_response(recording_path)
            )
            backend_may_have_started = (pending_dir / "backend-started").is_file()
            unknown_cost = (
                recorded_response is not None and recorded_response.usage.cost_usd is None
            ) or (
                recorded_response is None
                and intent.backend_mode is RuntimeBackendMode.LIVE
                and backend_may_have_started
            )
            archived = self._archive_one_pending(
                stage,
                pending_dir,
                unknown_cost=unknown_cost,
                exception=exc,
            )
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
            _write_model_exclusive(
                self._entry_path(stage, entry),
                entry,
                owned_root=stage,
            )
            totals = self._totals(project_id, run_id, [*entries, entry], stage=stage)
            return self._receipt(
                intent,
                outcome=entry.outcome,
                entry_sha256=entry.entry_sha256,
                totals=totals,
                blockers=entry.blockers,
                attempt_locator=archived,
                entry=entry,
            )

        _write_model_exclusive(
            self._entry_path(stage, entry),
            entry,
            owned_root=stage,
        )
        if pending_dir.exists():
            _retire_published_pending(pending_dir)
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
            recovered_without_provider=(
                pending_resume is not None and pending_resume.backend is not None
            ),
            entry=entry,
        )

    def _resume_pending(
        self,
        stage: Path,
        pending: list[Path],
        *,
        totals: RuntimeLedgerTotals,
        **values: Any,
    ) -> _PendingResume | None:
        invocation_id = values["invocation_id"]
        matches: list[tuple[Path, RuntimeInvocationIntent]] = []
        for directory in pending:
            pending_intent = _load_model(directory / "intent.json", RuntimeInvocationIntent)
            if pending_intent.invocation_id == invocation_id:
                matches.append((directory, pending_intent))
        if not matches:
            return None
        if len(matches) != 1:
            raise ModelNodeRuntimeError("multiple incomplete attempts share one invocation ID")
        directory, historical = matches[0]
        candidate = self._intent(
            project_id=values["project_id"],
            run_id=values["run_id"],
            invocation_id=invocation_id,
            project_revision=historical.project_revision,
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
            predecessor_sha256=historical.predecessor_sha256,
            cumulative_cost_usd=historical.context.cumulative_api_cost_usd,
        )
        if candidate.fingerprint != historical.fingerprint:
            raise ModelNodeRuntimeError("resume invocation identity drift")
        if historical.predecessor_sha256 != totals.chain_head_sha256:
            raise ModelNodeRuntimeError("resumed invocation predecessor drift")
        if historical.context.cumulative_api_cost_usd != totals.cost_usd:
            raise ModelNodeRuntimeError("resumed invocation cost context drift")
        recordings = _runtime_directory(stage, "recordings")
        recording = recordings / f"{invocation_id}.jsonl" if recordings is not None else None
        recovery_backend = None
        if (
            _is_actual_generation_mode(historical.backend_mode)
            and len(pending) == 1
            and (directory / "backend-started").is_file()
            and recording is not None
            and recording.is_file()
            and not recording.is_symlink()
        ):
            try:
                recovery_backend = RecordedResponseRecoveryBackend(recording)
            except (OSError, ValueError):
                recovery_backend = None
        return _PendingResume(
            intent=historical,
            directory=directory,
            recording_path=recording or stage / "recordings" / f"{invocation_id}.jsonl",
            backend=recovery_backend,
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
        if node_name not in self.node_types:
            raise ModelNodeRuntimeError(f"unsupported model-node type {node_name!r}")
        validate_profile_binding(profile, policy, node_name=node_name)
        registration = self.node_types[node_name]
        input_payload = (
            node_input.model_dump(mode="json") if isinstance(node_input, BaseModel) else node_input
        )
        typed_input = registration.input_type.model_validate_json(
            json.dumps(input_payload, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        if isinstance(typed_input, ToolPlanInput):
            registered_runs = {
                item.run_id
                for item in self.project_runtime.open(values["project_id"]).manifest.runs
            }
            if set(typed_input.scope.run_ids) - registered_runs:
                raise ModelNodeRuntimeError(
                    "controlled tool scope contains a run not registered to the project"
                )
        effective_context = NodeContext.model_validate(
            {
                **context.model_dump(mode="python"),
                "cumulative_api_cost_usd": cumulative_cost_usd,
            },
            strict=True,
        )
        expected_request = registration.node_type()._build_request(
            typed_input,
            context=effective_context,
            policy=policy,
            request_id=request_id or invocation_id,
            seed=values["seed"],
            profile=profile,
        )
        return RuntimeInvocationIntent(
            invocation_id=invocation_id,
            request_id=request_id or invocation_id,
            node_name=node_name,
            node_input=typed_input.model_dump(mode="json"),
            context=effective_context,
            profile=profile,
            policy=policy,
            expected_request_fingerprint=expected_request.fingerprint,
            **values,
        )

    def _preflight_blockers(
        self,
        intent: RuntimeInvocationIntent,
        totals: RuntimeLedgerTotals,
        *,
        stage: Path,
        allow_live: bool,
        allow_local: bool,
        backend: StructuredModelBackend | None,
    ) -> tuple[str, ...]:
        budget = intent.profile.cumulative_project
        blockers: list[str] = []
        if intent.backend_mode is not RuntimeBackendMode.REPLAY:
            if totals.unknown_cost_count:
                blockers.append("cumulative ledger contains unknown cost")
            if totals.entry_count >= budget.max_invocations:
                blockers.append("cumulative invocation budget exhausted")
            if totals.total_tokens >= budget.max_total_tokens:
                blockers.append("cumulative token budget exhausted")
            if (
                intent.backend_mode is not RuntimeBackendMode.LOCAL
                and totals.cost_usd >= budget.max_api_cost_usd
            ):
                blockers.append("cumulative API cost budget exhausted")
        if intent.backend_mode is RuntimeBackendMode.LIVE:
            if not intent.profile.live_execution_permitted:
                blockers.append("profile does not permit live execution")
            if not allow_live:
                blockers.append("caller did not opt in to live execution")
        if intent.backend_mode is RuntimeBackendMode.LOCAL:
            if not intent.profile.local_execution_permitted:
                blockers.append("profile does not permit local execution")
            if not allow_local:
                blockers.append("caller did not opt in to local execution")
        backend_config = getattr(backend, "config", None) if backend is not None else None
        backend_output_limit = (
            getattr(backend_config, "max_output_tokens", None)
            if backend_config is not None
            else None
        )
        if (
            backend_output_limit is not None
            and intent.profile.generation.max_output_tokens > backend_output_limit
        ):
            blockers.append("profile output envelope exceeds the backend configuration ceiling")
        if intent.backend_mode is RuntimeBackendMode.REPLAY:
            source = intent.replay_source_invocation_id
            assert source is not None
            recordings = _runtime_directory(stage, "recordings")
            recording = recordings / f"{source}.jsonl" if recordings is not None else None
            if recording is None or not recording.is_file() or recording.is_symlink():
                blockers.append("exact replay source recording is missing")
        return tuple(blockers)

    def _apply_project_revision_gate(
        self,
        result: NodeResult[Any],
        *,
        project_id: str,
        run_id: str,
        expected_revision: int,
    ) -> NodeResult[Any]:
        try:
            self._validate_project_run(
                project_id,
                run_id,
                expected_revision=expected_revision,
                create_stage=False,
            )
        except ProjectRevisionConflictError:
            return self._reject_result(
                result,
                ["project revision changed while the model-node backend was running"],
            )
        return result

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
        return self._reject_result(result, reasons)

    @staticmethod
    def _reject_result(result: NodeResult[Any], reasons: list[str]) -> NodeResult[Any]:
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
        if result.request.fingerprint != intent.expected_request_fingerprint:
            raise ModelNodeRuntimeError("model-node request identity drift")
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
        _write_model_exclusive(
            self._entry_path(stage, entry),
            entry,
            owned_root=stage,
        )
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
            entry=entry,
        )

    def _load_ledger(
        self,
        stage: Path,
        *,
        project_id: str,
        run_id: str,
    ) -> list[RuntimeLedgerEntry]:
        root = _runtime_directory(stage, "ledger")
        paths = sorted(root.glob("*.json")) if root is not None else []
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
                recordings = _runtime_directory(stage, "recordings")
                recording = recordings / f"{source_id}.jsonl" if recordings else None
                if (
                    recording is None
                    or not recording.is_file()
                    or recording.is_symlink()
                    or _sha256_file(recording) != entry.recording_sha256
                ):
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
        try:
            output_type = self.node_types[entry.intent.node_name].output_type
        except KeyError as exc:
            raise ModelNodeRuntimeError(
                f"runtime is missing model-node extension {entry.intent.node_name!r}"
            ) from exc
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
        if result.request.fingerprint != entry.intent.expected_request_fingerprint:
            raise ModelNodeRuntimeError("ledger intent request fingerprint drift")

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
        archives = [self._load_archived_attempt(path) for path in _archived_attempt_paths(stage)]
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

    def _archive_completed_pending(
        self,
        stage: Path,
        pending: list[Path],
        *,
        completed: dict[str, RuntimeLedgerEntry],
        invocation_id: str,
    ) -> str:
        locator: str | None = None
        for directory in pending:
            intent = _load_model(directory / "intent.json", RuntimeInvocationIntent)
            entry = completed.get(intent.invocation_id)
            if entry is None:
                raise ModelNodeRuntimeError(
                    "an unrelated incomplete attempt must be resumed before this invocation"
                )
            if intent.fingerprint != entry.intent.fingerprint:
                raise ModelNodeRuntimeError("published invocation identity drift")
            archived = self._archive_one_pending(
                stage,
                directory,
                unknown_cost=False,
                preserve_recording=True,
            )
            if intent.invocation_id == invocation_id:
                locator = archived
        if locator is None:
            raise ModelNodeRuntimeError("completed invocation has no matching pending attempt")
        return locator

    def _archive_one_pending(
        self,
        stage: Path,
        directory: Path,
        *,
        unknown_cost: bool,
        preserve_recording: bool = False,
        exception: Exception | None = None,
    ) -> str:
        pending_root = _runtime_directory(stage, "pending")
        if pending_root is None:
            raise ModelNodeRuntimeError("runtime pending directory is missing")
        _require_contained_directory(pending_root, directory)
        attempt_id = directory.name
        attempts = _runtime_directory(stage, "attempts", create=True)
        assert attempts is not None
        target = attempts / attempt_id
        if os.path.lexists(target):
            raise ModelNodeRuntimeError("refusing to replace existing runtime attempt evidence")
        os.replace(directory, target)
        _fsync_directory(attempts)
        _fsync_directory(pending_root)
        _require_contained_directory(attempts, target)
        intent = _load_model(target / "intent.json", RuntimeInvocationIntent)
        recording_sha256 = None
        if intent.backend_mode is not RuntimeBackendMode.REPLAY and not preserve_recording:
            recordings = _runtime_directory(stage, "recordings")
            recording = (
                recordings / f"{intent.invocation_id}.jsonl" if recordings is not None else None
            )
            if recording is not None and recording.is_file() and not recording.is_symlink():
                recording_sha256 = _sha256_file(recording)
                os.replace(recording, target / "recording.jsonl")
        exception_message = _sanitized_exception_message(exception)
        failure = _ArchivedAttempt.create(
            attempt_id=attempt_id,
            archived_at=datetime.now(UTC),
            invocation_id=intent.invocation_id,
            intent_sha256=intent.fingerprint,
            backend_may_have_started=(target / "backend-started").is_file(),
            unknown_cost=unknown_cost,
            recording_sha256=recording_sha256,
            exception_class=(None if exception is None else type(exception).__name__),
            exception_message=exception_message,
            exception_message_sha256=(
                None
                if exception_message is None
                else hashlib.sha256(exception_message.encode("utf-8")).hexdigest()
            ),
            failure_sha256=_ZERO_HASH,
        )
        _write_model_exclusive(target / "failure.json", failure, owned_root=stage)
        return (
            f"projects/{intent.project_id}/runs/{intent.run_id}/"
            f"{MODEL_NODE_STAGE_PATH}/attempts/{attempt_id}"
        )

    @staticmethod
    def _pending_directories(stage: Path) -> list[Path]:
        root = _runtime_directory(stage, "pending")
        if root is None:
            return []
        pending: list[Path] = []
        for path in sorted(root.iterdir()):
            if path.name.startswith(_RETIRED_PENDING_PREFIX):
                if path.is_symlink() or not path.is_dir():
                    raise ModelNodeRuntimeError("unsafe retired runtime pending entry")
                continue
            if path.is_symlink() or not path.is_dir():
                raise ModelNodeRuntimeError("runtime pending entry is not a safe directory")
            _require_contained_directory(root, path)
            pending.append(path)
        return pending

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
        if stage.exists():
            _validate_runtime_layout(stage)
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
        ledger = _runtime_directory(stage, "ledger", create=True)
        assert ledger is not None
        return ledger / f"{entry.index:08d}__{entry.intent.invocation_id}.json"

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
        entry: RuntimeLedgerEntry | None = None,
        recovered_without_provider: bool = False,
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
            telemetry=(
                RuntimeInvocationTelemetry(
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    total_tokens=entry.input_tokens + entry.output_tokens,
                    cost_usd=entry.cost_effect_usd,
                    latency_ms=entry.latency_ms,
                    cached=entry.cached,
                    replayed=entry.replayed,
                )
                if entry is not None
                else RuntimeInvocationTelemetry()
            ),
            totals=totals,
            ledger_locator=f"{base}/ledger",
            recording_locator=(
                f"{base}/recordings/{recording_path.name}" if recording_path is not None else None
            ),
            attempt_locator=attempt_locator,
            blockers=blockers,
            recovered_without_provider=recovered_without_provider,
            generation_envelope=intent.profile.generation.model_dump(mode="json"),
            admission_budget=intent.profile.admission.model_dump(mode="json"),
            cumulative_project_budget=intent.profile.cumulative_project.model_dump(mode="json"),
        )


class _ArchivedAttempt(RuntimeModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    attempt_id: str
    archived_at: datetime
    invocation_id: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_may_have_started: bool
    unknown_cost: bool
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    exception_class: str | None = Field(default=None, min_length=1, max_length=300)
    exception_message: str | None = Field(default=None, min_length=1, max_length=2_000)
    exception_message_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
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
        if (self.exception_message is None) != (self.exception_message_sha256 is None):
            raise ValueError("archived exception message identity is incomplete")
        if (
            self.exception_message is not None
            and self.exception_message_sha256
            != hashlib.sha256(self.exception_message.encode("utf-8")).hexdigest()
        ):
            raise ValueError("archived exception message hash differs")
        payload = self.model_dump(mode="json", exclude={"failure_sha256"})
        if self.schema_version == "1.0":
            for field in (
                "exception_class",
                "exception_message",
                "exception_message_sha256",
            ):
                payload.pop(field)
        expected = _canonical_sha256(payload)
        if self.failure_sha256 != expected:
            raise ValueError("failure_sha256 does not match archived attempt")
        return self


_SECRET_ENV_NAME = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|authorization)",
    re.IGNORECASE,
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]{8,}\b"),
)


def _sanitized_exception_message(exception: Exception | None) -> str | None:
    """Retain bounded diagnostics without persisting ambient credentials."""

    if exception is None:
        return None
    message = " ".join(str(exception).split())
    if not message:
        return None
    for name, value in os.environ.items():
        if _SECRET_ENV_NAME.search(name) and len(value) >= 4:
            message = message.replace(value, "<redacted>")
    for pattern in _CREDENTIAL_PATTERNS:
        message = pattern.sub(
            lambda match: f"{match.group(1)}<redacted>" if match.lastindex else "<redacted>",
            message,
        )
    return message[:2_000] or None


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
    descriptor = _open_regular_file_nofollow(path)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _last_recorded_response(path: Path) -> StructuredModelResponse | None:
    """Read trusted response telemetry without reflecting provider payloads in errors."""

    try:
        descriptor = _open_regular_file_nofollow(path)
        with os.fdopen(descriptor, "rb") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
        if not lines:
            return None
        return StructuredReplayRecord.model_validate_json(lines[-1], strict=True).response
    except (OSError, ValueError):
        return None


def _load_model(path: Path, model_type: type[BaseModel]) -> Any:
    try:
        descriptor = _open_regular_file_nofollow(path)
        with os.fdopen(descriptor, "rb") as handle:
            payload = handle.read()
        return model_type.model_validate_json(payload, strict=True)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ModelNodeRuntimeError(f"invalid runtime evidence: {path.name}") from exc


def _open_regular_file_nofollow(path: Path) -> int:
    if path.is_symlink():
        raise ModelNodeRuntimeError(f"missing or unsafe runtime evidence: {path.name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ModelNodeRuntimeError(f"missing or unsafe runtime evidence: {path.name}") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ModelNodeRuntimeError(f"runtime evidence is not a regular file: {path.name}")
    return descriptor


def _write_model_exclusive(
    path: Path,
    value: BaseModel,
    *,
    owned_root: Path | None = None,
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
    _write_bytes_exclusive(path, payload, owned_root=owned_root)


def _write_bytes_exclusive(
    path: Path,
    payload: bytes,
    *,
    owned_root: Path | None = None,
) -> None:
    if owned_root is not None:
        _require_owned_parent(owned_root, path.parent)
    else:
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


def _retire_published_pending(path: Path) -> None:
    parent = path.parent
    _require_contained_directory(parent, path)
    retired = parent / f"{_RETIRED_PENDING_PREFIX}{path.name}"
    if os.path.lexists(retired):
        raise ModelNodeRuntimeError("retired runtime pending path already exists")
    os.replace(path, retired)
    _fsync_directory(parent)
    _require_contained_directory(parent, retired)
    _purge_retired_pending(retired)


def _purge_retired_pending(path: Path) -> None:
    _require_contained_directory(path.parent, path)
    for item in path.iterdir():
        if item.is_dir() and not item.is_symlink():
            raise ModelNodeRuntimeError("retired runtime pending contains a nested directory")
        item.unlink()
    path.rmdir()
    _fsync_directory(path.parent)


def _retired_pending_directories(stage: Path) -> list[Path]:
    pending = _runtime_directory(stage, "pending")
    if pending is None:
        return []
    retired: list[Path] = []
    for path in sorted(pending.iterdir()):
        if not path.name.startswith(_RETIRED_PENDING_PREFIX):
            continue
        _require_contained_directory(pending, path)
        retired.append(path)
    return retired


def _cleanup_retired_pending(stage: Path) -> None:
    for path in _retired_pending_directories(stage):
        _purge_retired_pending(path)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise ModelNodeRuntimeError("runtime lock is not a safe regular file")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ModelNodeRuntimeError("cannot open the runtime lock safely") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ModelNodeRuntimeError("runtime lock is not a safe regular file")
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


def _validate_runtime_layout(stage: Path) -> None:
    if stage.is_symlink() or not stage.is_dir() or stage.resolve(strict=True) != stage:
        raise ModelNodeRuntimeError("model-node stage escapes its project-owned path")
    for child in stage.iterdir():
        if child.is_symlink():
            raise ModelNodeRuntimeError("runtime stage contains a symbolic link")
        if child.name == ".runtime.lock" and not child.is_file():
            raise ModelNodeRuntimeError("runtime lock is not a safe regular file")
    for name in _RUNTIME_DIRECTORIES:
        root = _runtime_directory(stage, name)
        if root is not None:
            _validate_runtime_directory_entries(root, directories=name in {"attempts", "pending"})


def _runtime_directory(stage: Path, name: str, *, create: bool = False) -> Path | None:
    if name not in _RUNTIME_DIRECTORIES:
        raise ValueError(f"unsupported runtime directory {name!r}")
    if not os.path.lexists(stage) and not create:
        return None
    if stage.is_symlink() or not stage.is_dir() or stage.resolve(strict=True) != stage:
        raise ModelNodeRuntimeError("model-node stage escapes its project-owned path")
    candidate = stage / name
    if not os.path.lexists(candidate):
        if not create:
            return None
        try:
            candidate.mkdir()
        except FileExistsError:
            pass
    if candidate.is_symlink() or not candidate.is_dir():
        raise ModelNodeRuntimeError(f"runtime {name} path is not a safe directory")
    _require_contained_directory(stage, candidate)
    return candidate


def _require_contained_directory(root: Path | None, path: Path) -> None:
    if root is None or root.is_symlink() or not root.is_dir():
        raise ModelNodeRuntimeError("runtime evidence root is not a safe directory")
    if path.is_symlink() or not path.is_dir():
        raise ModelNodeRuntimeError("runtime evidence path is not a safe directory")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ModelNodeRuntimeError("runtime evidence path escapes its owned directory") from exc


def _require_owned_parent(root: Path, parent: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ModelNodeRuntimeError("runtime evidence root is not a safe directory")
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ModelNodeRuntimeError("runtime evidence parent escapes its owned directory") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ModelNodeRuntimeError("runtime evidence parent is not a safe directory")
    try:
        parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ModelNodeRuntimeError("runtime evidence parent escapes its owned directory") from exc


def _validate_runtime_directory_entries(root: Path, *, directories: bool) -> None:
    for entry in root.iterdir():
        if entry.is_symlink():
            raise ModelNodeRuntimeError("runtime directory contains a symbolic link")
        if directories:
            _require_contained_directory(root, entry)
            for evidence in entry.iterdir():
                if evidence.is_symlink() or not evidence.is_file():
                    raise ModelNodeRuntimeError(
                        "runtime nested evidence is not a safe regular file"
                    )
        elif not entry.is_file():
            raise ModelNodeRuntimeError("runtime evidence is not a safe regular file")


def _archived_attempt_paths(stage: Path) -> list[Path]:
    attempts = _runtime_directory(stage, "attempts")
    if attempts is None:
        return []
    paths: list[Path] = []
    for directory in sorted(attempts.iterdir()):
        _require_contained_directory(attempts, directory)
        failure = directory / "failure.json"
        if not failure.is_file() or failure.is_symlink():
            raise ModelNodeRuntimeError("runtime attempt is missing safe failure evidence")
        paths.append(failure)
    return paths


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MODEL_NODE_STAGE_PATH",
    "ModelNodeRegistration",
    "ModelNodeRuntime",
    "ModelNodeRuntimeConflictError",
    "ModelNodeRuntimeError",
    "ModelNodeTrigger",
    "RuntimeBackendMode",
    "RuntimeInvocationIntent",
    "RuntimeInvocationReceipt",
    "RuntimeInvocationTelemetry",
    "RuntimeLedgerEntry",
    "RuntimeLedgerTotals",
    "RuntimeOutcome",
    "RuntimeVerification",
]

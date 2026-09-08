"""Deterministic one-step execution for admitted Tool Intelligence proposals."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from time import perf_counter
from typing import Annotated, Literal, Protocol, TypeAlias, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)

from scitaste.backends.base import Usage
from scitaste.data.models import KnowledgeDocument
from scitaste.data.retrieval import rank_knowledge_documents
from scitaste.model_nodes.models import NodeContext, NodeResult, NodeResultStatus
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    EvidenceInspectArguments,
    EvidenceInspectStep,
    KnowledgeQueryArguments,
    KnowledgeQueryStep,
    RegisteredRunCompareArguments,
    RegisteredRunCompareStep,
    ToolPlanInput,
    ToolPlanOutput,
    ToolPlanStep,
    canonical_json,
    canonical_sha256,
)
from scitaste.project.runtime import ProjectRuntime

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
ToolArguments: TypeAlias = (
    KnowledgeQueryArguments | EvidenceInspectArguments | RegisteredRunCompareArguments
)


class ToolExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticHotspotKind(StrEnum):
    """Named semantic gaps at which deterministic code may request advice."""

    REVIEW_SEMANTICS = "review-semantics"
    INTERPRETATION_THREAT = "interpretation-threat"
    AMBIGUOUS_ACTION = "ambiguous-action"
    STRUCTURED_REPAIR = "structured-repair"
    EVIDENCE_SYNTHESIS = "evidence-synthesis"


class SemanticGapKind(StrEnum):
    """Why the deterministic fast path cannot resolve a hotspot alone."""

    AMBIGUOUS_LANGUAGE = "ambiguous-language"
    OPEN_ENDED_CANDIDATES = "open-ended-candidates"
    COMPETING_INTERPRETATIONS = "competing-interpretations"
    SEMANTIC_DEDUPLICATION = "semantic-deduplication"
    STRUCTURED_OUTPUT_REPAIR = "structured-output-repair"


class SemanticHotspotTrigger(ToolExecutionModel):
    """Content-addressed reason and authority ceiling for one semantic detour."""

    schema_version: Literal["1.0"] = "1.0"
    trigger_id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN, max_length=128)]
    hotspot_kind: SemanticHotspotKind
    semantic_gap: SemanticGapKind
    project_id: str = Field(min_length=1, max_length=128)
    project_revision: int = Field(ge=0)
    project_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_snapshot_id: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=4_000)
    controlled_tool_profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    controlled_tool_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_tool_names: tuple[ControlledToolName, ...] = Field(min_length=1, max_length=3)
    reason_codes: tuple[Annotated[str, Field(pattern=_IDENTIFIER_PATTERN, max_length=128)], ...] = (
        Field(default=(), max_length=16)
    )
    evidence_ids: tuple[Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)], ...] = Field(
        default=(),
        max_length=256,
    )
    deterministic_fast_path_exhausted: Literal[True] = True
    advisory_only: Literal[True] = True
    state_transition_authorized: Literal[False] = False

    @field_validator("candidate_tool_names", "reason_codes", "evidence_ids")
    @classmethod
    def identifiers_are_unique(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        if len(values) != len(set(values)):
            raise ValueError("semantic-hotspot identifiers must be unique")
        return tuple(sorted(values, key=str))

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ReadOnlyHandlerAuthority(ToolExecutionModel):
    """Non-negotiable authority boundary for the v2 deterministic handlers."""

    schema_version: Literal["1.0"] = "1.0"
    read_only: Literal[True] = True
    network_access: Literal[False] = False
    filesystem_write: Literal[False] = False
    process_launch: Literal[False] = False
    state_mutation: Literal[False] = False
    canonical_evidence_admission: Literal[False] = False


class ReadOnlyToolHandlerDescriptor(ToolExecutionModel):
    """Content-addressed identity for trusted deterministic handler code and data."""

    schema_version: Literal["1.0"] = "1.0"
    tool_name: ControlledToolName
    handler_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    handler_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_output_bytes: int = Field(ge=1, le=1_000_000)
    max_result_items: int = Field(ge=1, le=10_000)
    authority: ReadOnlyHandlerAuthority = Field(default_factory=ReadOnlyHandlerAuthority)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolProjectSnapshot(ToolExecutionModel):
    """The ProjectRuntime identity checked at lease issue and tool boundaries."""

    project_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ActionLease(ToolExecutionModel):
    """Single-use authority for exactly one deterministic read-only handler call."""

    schema_version: Literal["1.0"] = "1.0"
    lease_id: str = Field(pattern=r"^lease-[0-9a-f]{24}$")
    issued_at: datetime
    expires_at: datetime
    hotspot_trigger_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    project: ToolProjectSnapshot
    state_snapshot_id: str = Field(min_length=1, max_length=256)
    source_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_model_usage: Usage
    source_model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    controlled_tool_profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    controlled_tool_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    step: ToolPlanStep
    step_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    handler: ReadOnlyToolHandlerDescriptor
    max_observation_bytes: int = Field(ge=1, le=1_000_000)
    tool_execution_authorized: Literal[True] = True
    single_use: Literal[True] = True
    advisory_only: Literal[True] = True
    state_transition_authorized: Literal[False] = False
    canonical_evidence_admission: Literal[False] = False

    @field_validator("issued_at", "expires_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("action lease timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def lease_is_coherent(self) -> ActionLease:
        if self.expires_at <= self.issued_at:
            raise ValueError("action lease must expire after it is issued")
        if self.expires_at - self.issued_at > timedelta(minutes=5):
            raise ValueError("action lease lifetime cannot exceed five minutes")
        if self.step.depends_on:
            raise ValueError("v2 action leases may authorize only dependency-free steps")
        if self.step.tool_name != self.handler.tool_name:
            raise ValueError("action lease step and handler tool names differ")
        expected = canonical_sha256(self.step.model_dump(mode="json"))
        if self.step_fingerprint != expected:
            raise ValueError("action lease step fingerprint does not match the step")
        if self.max_observation_bytes > self.handler.max_output_bytes:
            raise ValueError("action lease output limit exceeds the handler limit")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolObservationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class ToolObservation(ToolExecutionModel):
    """Typed, non-authoritative result of attempting one leased handler call."""

    schema_version: Literal["1.0"] = "1.0"
    status: ToolObservationStatus
    lease_id: str = Field(pattern=r"^lease-[0-9a-f]{24}$")
    lease_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_name: ControlledToolName
    handler_id: str = Field(min_length=1)
    handler_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    finished_at: datetime
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    project_revision_before: int | None = Field(default=None, ge=0)
    project_revision_after: int | None = Field(default=None, ge=0)
    state_snapshot_id_before: str | None = None
    state_snapshot_id_after: str | None = None
    output_payload: dict[str, JsonValue] | None = None
    untrusted_output_payload: dict[str, JsonValue] | None = None
    output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_bytes: int | None = Field(default=None, ge=0)
    rejection_reasons: tuple[str, ...] = ()
    failure_type: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_.]*$")
    source_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_model_usage: Usage
    source_model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    handler_invoked: bool = False
    advisory_only: Literal[True] = True
    executable: Literal[False] = False
    canonical_evidence: Literal[False] = False
    state_transition_authorized: Literal[False] = False

    @field_validator("started_at", "finished_at")
    @classmethod
    def observation_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("tool observation timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def status_matches_payload(self) -> ToolObservation:
        if self.finished_at < self.started_at:
            raise ValueError("tool observation cannot finish before it starts")
        if self.status is ToolObservationStatus.SUCCEEDED:
            if (
                self.output_payload is None
                or self.untrusted_output_payload is not None
                or self.rejection_reasons
                or self.failure_type is not None
            ):
                raise ValueError("successful observations require one clean output")
        elif self.status is ToolObservationStatus.REJECTED:
            if self.output_payload is not None or not self.rejection_reasons:
                raise ValueError("rejected observations require reasons and no accepted output")
        else:
            if (
                self.output_payload is not None
                or self.untrusted_output_payload is not None
                or not self.rejection_reasons
                or self.failure_type is None
            ):
                raise ValueError("failed observations require a failure type and no output")
        if (self.output_sha256 is None) != (self.output_bytes is None):
            raise ValueError("tool output hash and byte count must be recorded together")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"fingerprint", "observation_id"})
        )

    @computed_field
    @property
    def observation_id(self) -> str:
        return f"observation-{self.fingerprint[:24]}"


class ToolLeaseAdmissionError(ValueError):
    """Raised before a model proposal gains any deterministic execution authority."""


@runtime_checkable
class ReadOnlyToolHandler(Protocol):
    """Trusted handler interface; implementations are part of the TCB."""

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor: ...

    def execute(self, arguments: ToolArguments) -> dict[str, JsonValue]: ...


class BoundEvidenceRecord(ToolExecutionModel):
    """Caller-verified evidence made available to the built-in inspector."""

    evidence_id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN, max_length=128)]
    payload: JsonValue
    provenance: JsonValue | None = None

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class EvidenceInspectionHandler:
    """Read bounded evidence records without changing their admission status."""

    def __init__(self, records: Iterable[BoundEvidenceRecord]) -> None:
        values = tuple(records)
        bound = {record.evidence_id: record for record in values}
        if not bound:
            raise ValueError("evidence inspection handler requires at least one record")
        if len(bound) != len(values):
            raise ValueError("bound evidence IDs must be unique")
        self._records = bound
        configuration = canonical_sha256(
            {key: value.model_dump(mode="json") for key, value in sorted(bound.items())}
        )
        self._descriptor = ReadOnlyToolHandlerDescriptor(
            tool_name=ControlledToolName.EVIDENCE_INSPECT,
            handler_id="scitaste.evidence-inspect.bound-v1",
            handler_version="1.0.0",
            configuration_sha256=configuration,
            max_output_bytes=262_144,
            max_result_items=len(bound),
        )

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self._descriptor

    def execute(self, arguments: ToolArguments) -> dict[str, JsonValue]:
        if not isinstance(arguments, EvidenceInspectArguments):
            raise TypeError("evidence inspection received another tool's arguments")
        missing = sorted(set(arguments.evidence_ids) - set(self._records))
        if missing:
            raise KeyError("requested evidence is absent from the bound registry")
        items: list[JsonValue] = []
        for evidence_id in arguments.evidence_ids:
            record = self._records[evidence_id]
            item: dict[str, JsonValue] = {
                "evidence_id": evidence_id,
                "payload": record.payload,
                "record_fingerprint": record.fingerprint,
            }
            if arguments.include_provenance:
                item["provenance"] = record.provenance
            items.append(item)
        return {"tool_name": ControlledToolName.EVIDENCE_INSPECT.value, "items": items}


class KnowledgeQueryHandler:
    """Run deterministic lexical retrieval over caller-bound Knowledge documents."""

    def __init__(self, libraries: Mapping[str, Iterable[KnowledgeDocument]]) -> None:
        if not libraries:
            raise ValueError("knowledge query handler requires at least one library")
        normalized: dict[str, tuple[KnowledgeDocument, ...]] = {}
        for library_id, documents in libraries.items():
            safe_library_id = library_id and all(
                character.isalnum() or character in "._:-" for character in library_id
            )
            if not safe_library_id:
                raise ValueError("knowledge library IDs must be safe identifiers")
            values = tuple(documents)
            identifiers = [item.document_id for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("knowledge document IDs must be unique within a library")
            normalized[library_id] = values
        self._libraries = normalized
        configuration = canonical_sha256(
            {
                library_id: [item.model_dump(mode="json") for item in documents]
                for library_id, documents in sorted(normalized.items())
            }
        )
        self._descriptor = ReadOnlyToolHandlerDescriptor(
            tool_name=ControlledToolName.KNOWLEDGE_QUERY,
            handler_id="scitaste.knowledge-query.lexical-v1",
            handler_version="1.0.0",
            configuration_sha256=configuration,
            max_output_bytes=262_144,
            max_result_items=20,
        )

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self._descriptor

    def execute(self, arguments: ToolArguments) -> dict[str, JsonValue]:
        if not isinstance(arguments, KnowledgeQueryArguments):
            raise TypeError("knowledge query received another tool's arguments")
        missing = sorted(set(arguments.library_ids) - set(self._libraries))
        if missing:
            raise KeyError("requested knowledge library is absent from the bound registry")
        documents_by_id: dict[str, KnowledgeDocument] = {}
        for library_id in arguments.library_ids:
            for document in self._libraries[library_id]:
                existing = documents_by_id.get(document.document_id)
                if existing is not None and existing != document:
                    raise ValueError("one document ID resolves to conflicting bound records")
                documents_by_id[document.document_id] = document
        ranked = rank_knowledge_documents(
            documents_by_id.values(),
            arguments.query,
            limit=arguments.top_k,
        )
        items: list[JsonValue] = [
            {
                "document_id": item.document.document_id,
                "title": item.document.title,
                "score": item.score,
                "document_sha256": canonical_sha256(item.document.model_dump(mode="json")),
            }
            for item in ranked
        ]
        return {
            "tool_name": ControlledToolName.KNOWLEDGE_QUERY.value,
            "query_sha256": canonical_sha256({"query": arguments.query}),
            "items": items,
        }


class RegisteredRunComparisonHandler:
    """Compare finite metrics that the caller bound to registered run IDs."""

    def __init__(self, run_metrics: Mapping[str, Mapping[str, float | int | None]]) -> None:
        if len(run_metrics) < 2:
            raise ValueError("run comparison handler requires at least two runs")
        normalized: dict[str, dict[str, float | int | None]] = {}
        for run_id, metrics in run_metrics.items():
            if not metrics:
                raise ValueError("each bound run requires at least one metric")
            row: dict[str, float | int | None] = {}
            for name, value in metrics.items():
                if (
                    value is not None
                    and (isinstance(value, bool) or not isinstance(value, (int, float)))
                ) or (isinstance(value, float) and not math.isfinite(value)):
                    raise ValueError("run metrics must be finite numbers or null")
                row[name] = value
            normalized[run_id] = row
        self._run_metrics = normalized
        configuration = canonical_sha256(normalized)
        self._descriptor = ReadOnlyToolHandlerDescriptor(
            tool_name=ControlledToolName.REGISTERED_RUN_COMPARE,
            handler_id="scitaste.registered-run.compare-v1",
            handler_version="1.0.0",
            configuration_sha256=configuration,
            max_output_bytes=262_144,
            max_result_items=sum(len(item) for item in normalized.values()),
        )

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self._descriptor

    def execute(self, arguments: ToolArguments) -> dict[str, JsonValue]:
        if not isinstance(arguments, RegisteredRunCompareArguments):
            raise TypeError("run comparison received another tool's arguments")
        missing_runs = sorted(set(arguments.run_ids) - set(self._run_metrics))
        if missing_runs:
            raise KeyError("requested run is absent from the bound metric registry")
        rows: list[JsonValue] = []
        for run_id in arguments.run_ids:
            available = self._run_metrics[run_id]
            missing_metrics = sorted(set(arguments.metric_names) - set(available))
            if missing_metrics:
                raise KeyError("requested metric is absent from a bound run")
            rows.append(
                {
                    "run_id": run_id,
                    "metrics": {name: available[name] for name in arguments.metric_names},
                }
            )
        return {
            "tool_name": ControlledToolName.REGISTERED_RUN_COMPARE.value,
            "baseline_run_id": arguments.run_ids[0],
            "rows": rows,
        }


class ControlledToolExecutor:
    """Issue and consume one-use leases around trusted deterministic handlers."""

    def __init__(
        self,
        *,
        project_runtime: ProjectRuntime,
        state_snapshot_reader: Callable[[], str],
        handlers: Iterable[ReadOnlyToolHandler],
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        registry: dict[ControlledToolName, ReadOnlyToolHandler] = {}
        for handler in handlers:
            descriptor = ReadOnlyToolHandlerDescriptor.model_validate_json(
                handler.descriptor.model_dump_json(exclude_computed_fields=True),
                strict=True,
            )
            if descriptor.tool_name in registry:
                raise ValueError(f"duplicate controlled handler for {descriptor.tool_name.value}")
            registry[descriptor.tool_name] = handler
        if not registry:
            raise ValueError("controlled tool executor requires at least one handler")
        self._project_runtime = project_runtime
        self._state_snapshot_reader = state_snapshot_reader
        self._handlers = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or perf_counter
        self._consumed_leases: set[str] = set()
        self._lease_lock = Lock()

    def issue_lease(
        self,
        result: NodeResult[ToolPlanOutput],
        *,
        hotspot: SemanticHotspotTrigger,
        step_id: str,
        ttl_seconds: int = 60,
        max_observation_bytes: int | None = None,
    ) -> ActionLease:
        """Deterministically admit one fresh dependency-free plan step."""

        try:
            hotspot = SemanticHotspotTrigger.model_validate_json(
                hotspot.model_dump_json(exclude_computed_fields=True),
                strict=True,
            )
            result = NodeResult[ToolPlanOutput].model_validate_json(
                result.model_dump_json(exclude_computed_fields=True),
                strict=True,
            )
        except ValueError as exc:
            raise ToolLeaseAdmissionError(
                "model-node result fails deterministic boundary validation"
            ) from exc
        if isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= 300:
            raise ToolLeaseAdmissionError("action lease TTL must be 1-300 seconds")
        if result.node_name != "tool-plan" or result.status is not NodeResultStatus.ACCEPTED:
            raise ToolLeaseAdmissionError("only an accepted tool-plan result can receive a lease")
        if result.proposal is None or result.untrusted_proposal is not None:
            raise ToolLeaseAdmissionError("tool-plan result does not expose one clean proposal")
        if result.executable or not result.advisory_only:
            raise ToolLeaseAdmissionError(
                "model-node result crossed its advisory authority boundary"
            )
        if result.response.tool_calls:
            raise ToolLeaseAdmissionError("provider-native tool calls cannot receive action leases")
        if result.response.request_id != result.request.request_id or (
            result.response.request_fingerprint != result.request.fingerprint
        ):
            raise ToolLeaseAdmissionError("tool-plan request and response identity differ")
        if result.request.node_name != "tool-plan":
            raise ToolLeaseAdmissionError("source request is not a tool-plan request")
        try:
            response_proposal = ToolPlanOutput.model_validate_json(
                canonical_json(result.response.output_payload),
                strict=True,
            )
        except ValueError as exc:
            raise ToolLeaseAdmissionError(
                "source response no longer contains a valid tool-plan proposal"
            ) from exc
        if response_proposal != result.proposal:
            raise ToolLeaseAdmissionError("accepted proposal differs from its source response")

        source_payload = result.request.input_payload
        try:
            node_input = ToolPlanInput.model_validate_json(
                canonical_json(source_payload["input"]),
                strict=True,
            )
            source_context = NodeContext.model_validate_json(
                canonical_json(source_payload["context"]),
                strict=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolLeaseAdmissionError("source tool-plan input cannot be reconstructed") from exc
        proposal = result.proposal
        if source_context.project_id != hotspot.project_id:
            raise ToolLeaseAdmissionError("source node context belongs to another project")
        if source_context.state_snapshot_id != hotspot.state_snapshot_id:
            raise ToolLeaseAdmissionError("source node context belongs to another state snapshot")
        if set(hotspot.evidence_ids) - set(source_context.evidence_ids):
            raise ToolLeaseAdmissionError("semantic hotspot expands the source evidence scope")
        if node_input.scope.project_id != hotspot.project_id:
            raise ToolLeaseAdmissionError("semantic hotspot belongs to another project")
        if node_input.scope.state_snapshot_id != hotspot.state_snapshot_id:
            raise ToolLeaseAdmissionError("semantic hotspot belongs to another state snapshot")
        if result.request.state_snapshot_id != hotspot.state_snapshot_id:
            raise ToolLeaseAdmissionError("tool-plan request uses another state snapshot")
        if node_input.objective != hotspot.objective:
            raise ToolLeaseAdmissionError("semantic hotspot and tool-plan objectives differ")
        if node_input.tool_profile.profile_id != hotspot.controlled_tool_profile_id or (
            node_input.tool_profile.fingerprint != hotspot.controlled_tool_profile_fingerprint
        ):
            raise ToolLeaseAdmissionError("semantic hotspot and controlled profile differ")
        if proposal.tool_profile_id != node_input.tool_profile.profile_id or (
            proposal.tool_profile_fingerprint != node_input.tool_profile.fingerprint
        ):
            raise ToolLeaseAdmissionError("accepted proposal and controlled profile differ")

        matching_steps = [step for step in proposal.steps if step.step_id == step_id]
        if len(matching_steps) != 1:
            raise ToolLeaseAdmissionError("requested action step is not unique in the proposal")
        step = matching_steps[0]
        if step.depends_on:
            raise ToolLeaseAdmissionError(
                "v2 admits only a dependency-free next step; re-plan after its observation"
            )
        if step.tool_name not in hotspot.candidate_tool_names:
            raise ToolLeaseAdmissionError("step tool is outside the semantic hotspot ceiling")
        if isinstance(step, EvidenceInspectStep) and (
            set(step.arguments.evidence_ids) - set(hotspot.evidence_ids)
        ):
            raise ToolLeaseAdmissionError("step expands the semantic hotspot evidence scope")
        handler = self._handlers.get(step.tool_name)
        if handler is None:
            raise ToolLeaseAdmissionError("no deterministic handler is registered for the step")
        descriptor = handler.descriptor
        requested_items = _requested_result_items(step)
        if requested_items > descriptor.max_result_items:
            raise ToolLeaseAdmissionError("step result count exceeds the handler ceiling")

        project_snapshot = self._project_runtime.open(hotspot.project_id)
        snapshot = ToolProjectSnapshot(
            project_id=project_snapshot.project_id,
            revision=project_snapshot.revision,
            snapshot_sha256=project_snapshot.snapshot_sha256,
        )
        if snapshot.revision != hotspot.project_revision or (
            snapshot.snapshot_sha256 != hotspot.project_snapshot_sha256
        ):
            raise ToolLeaseAdmissionError("project changed before action-lease admission")
        if self._state_snapshot_reader() != hotspot.state_snapshot_id:
            raise ToolLeaseAdmissionError("research state changed before action-lease admission")
        if isinstance(step, RegisteredRunCompareStep):
            registered = {item.run_id for item in project_snapshot.manifest.runs}
            if set(step.arguments.run_ids) - registered:
                raise ToolLeaseAdmissionError(
                    "run comparison references an unregistered project run"
                )

        limit = descriptor.max_output_bytes
        if max_observation_bytes is not None:
            if isinstance(max_observation_bytes, bool) or max_observation_bytes < 1:
                raise ToolLeaseAdmissionError("observation byte limit must be positive")
            limit = min(limit, max_observation_bytes)
        issued_at = self._clock()
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise ToolLeaseAdmissionError("executor clock must return a timezone-aware time")
        step_fingerprint = canonical_sha256(step.model_dump(mode="json"))
        lease_seed = {
            "hotspot": hotspot.fingerprint,
            "request": result.request.fingerprint,
            "step": step_fingerprint,
            "handler": descriptor.fingerprint,
            "issued_at": issued_at.isoformat(),
        }
        lease_id = f"lease-{canonical_sha256(lease_seed)[:24]}"
        return ActionLease(
            lease_id=lease_id,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
            hotspot_trigger_fingerprint=hotspot.fingerprint,
            project=snapshot,
            state_snapshot_id=hotspot.state_snapshot_id,
            source_request_fingerprint=result.request.fingerprint,
            source_raw_response_sha256=result.response.raw_response_sha256,
            source_model_usage=result.response.usage,
            source_model_latency_ms=result.response.latency_ms,
            controlled_tool_profile_id=node_input.tool_profile.profile_id,
            controlled_tool_profile_fingerprint=node_input.tool_profile.fingerprint,
            step=step,
            step_fingerprint=step_fingerprint,
            handler=descriptor,
            max_observation_bytes=limit,
        )

    def execute(self, lease: ActionLease) -> ToolObservation:
        """Consume one lease and return a non-authoritative typed observation."""

        try:
            lease = ActionLease.model_validate_json(
                lease.model_dump_json(exclude_computed_fields=True),
                strict=True,
            )
        except ValueError as exc:
            raise ToolLeaseAdmissionError(
                "action lease fails deterministic boundary validation"
            ) from exc
        started_at = self._clock()
        start_tick = self._monotonic()
        with self._lease_lock:
            if lease.fingerprint in self._consumed_leases:
                return self._observation(
                    lease,
                    status=ToolObservationStatus.REJECTED,
                    started_at=started_at,
                    start_tick=start_tick,
                    reasons=("action lease was already consumed",),
                )
            self._consumed_leases.add(lease.fingerprint)

        if started_at < lease.issued_at:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                reasons=("executor time precedes action-lease issue time",),
            )
        if started_at >= lease.expires_at:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                reasons=("action lease expired before handler execution",),
            )
        handler = self._handlers.get(lease.step.tool_name)
        if handler is None:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                reasons=("leased handler is not registered",),
            )
        if handler.descriptor.fingerprint != lease.handler.fingerprint:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                reasons=("registered handler identity changed after lease admission",),
            )

        before = _project_snapshot(self._project_runtime, lease.project.project_id)
        state_before = self._state_snapshot_reader()
        preflight_reasons: list[str] = []
        if before != lease.project:
            preflight_reasons.append("project changed before handler execution")
        if state_before != lease.state_snapshot_id:
            preflight_reasons.append("research state changed before handler execution")
        if preflight_reasons:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                before=before,
                state_before=state_before,
                reasons=tuple(preflight_reasons),
            )

        try:
            raw_output = handler.execute(lease.step.arguments)
            output = _JSON_OBJECT.validate_python(raw_output, strict=True)
            encoded = canonical_json(output)
            output_sha256 = canonical_sha256(output)
            output_bytes = len(encoded)
        except Exception as exc:
            after = _project_snapshot(self._project_runtime, lease.project.project_id)
            state_after = self._state_snapshot_reader()
            return self._observation(
                lease,
                status=ToolObservationStatus.FAILED,
                started_at=started_at,
                start_tick=start_tick,
                before=before,
                after=after,
                state_before=state_before,
                state_after=state_after,
                reasons=("deterministic read-only handler failed",),
                failure_type=type(exc).__name__,
                handler_invoked=True,
            )

        after = _project_snapshot(self._project_runtime, lease.project.project_id)
        state_after = self._state_snapshot_reader()
        finished_at = self._clock()
        rejection_reasons: list[str] = []
        if output_bytes > lease.max_observation_bytes:
            rejection_reasons.append("handler output exceeds the leased byte ceiling")
        if after != before:
            rejection_reasons.append("project changed during handler execution")
        if state_after != state_before:
            rejection_reasons.append("research state changed during handler execution")
        if finished_at >= lease.expires_at:
            rejection_reasons.append("action lease expired during handler execution")
        if rejection_reasons:
            return self._observation(
                lease,
                status=ToolObservationStatus.REJECTED,
                started_at=started_at,
                start_tick=start_tick,
                finished_at=finished_at,
                before=before,
                after=after,
                state_before=state_before,
                state_after=state_after,
                untrusted_output=(output if output_bytes <= lease.max_observation_bytes else None),
                output_sha256=output_sha256,
                output_bytes=output_bytes,
                reasons=tuple(rejection_reasons),
                handler_invoked=True,
            )
        return self._observation(
            lease,
            status=ToolObservationStatus.SUCCEEDED,
            started_at=started_at,
            start_tick=start_tick,
            finished_at=finished_at,
            before=before,
            after=after,
            state_before=state_before,
            state_after=state_after,
            output=output,
            output_sha256=output_sha256,
            output_bytes=output_bytes,
            handler_invoked=True,
        )

    def _observation(
        self,
        lease: ActionLease,
        *,
        status: ToolObservationStatus,
        started_at: datetime,
        start_tick: float,
        finished_at: datetime | None = None,
        before: ToolProjectSnapshot | None = None,
        after: ToolProjectSnapshot | None = None,
        state_before: str | None = None,
        state_after: str | None = None,
        output: dict[str, JsonValue] | None = None,
        untrusted_output: dict[str, JsonValue] | None = None,
        output_sha256: str | None = None,
        output_bytes: int | None = None,
        reasons: tuple[str, ...] = (),
        failure_type: str | None = None,
        handler_invoked: bool = False,
    ) -> ToolObservation:
        finished = finished_at or self._clock()
        latency_ms = max(0.0, (self._monotonic() - start_tick) * 1_000)
        return ToolObservation(
            status=status,
            lease_id=lease.lease_id,
            lease_fingerprint=lease.fingerprint,
            tool_name=lease.step.tool_name,
            handler_id=lease.handler.handler_id,
            handler_fingerprint=lease.handler.fingerprint,
            started_at=started_at,
            finished_at=finished,
            tool_latency_ms=latency_ms,
            project_revision_before=None if before is None else before.revision,
            project_revision_after=None if after is None else after.revision,
            state_snapshot_id_before=state_before,
            state_snapshot_id_after=state_after,
            output_payload=output,
            untrusted_output_payload=untrusted_output,
            output_sha256=output_sha256,
            output_bytes=output_bytes,
            rejection_reasons=reasons,
            failure_type=failure_type,
            source_request_fingerprint=lease.source_request_fingerprint,
            source_raw_response_sha256=lease.source_raw_response_sha256,
            source_model_usage=lease.source_model_usage,
            source_model_latency_ms=lease.source_model_latency_ms,
            handler_invoked=handler_invoked,
        )


def _project_snapshot(runtime: ProjectRuntime, project_id: str) -> ToolProjectSnapshot:
    snapshot = runtime.open(project_id)
    return ToolProjectSnapshot(
        project_id=snapshot.project_id,
        revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
    )


def _requested_result_items(
    step: KnowledgeQueryStep | EvidenceInspectStep | RegisteredRunCompareStep,
) -> int:
    if isinstance(step, KnowledgeQueryStep):
        return step.arguments.top_k
    if isinstance(step, EvidenceInspectStep):
        return len(step.arguments.evidence_ids)
    return len(step.arguments.run_ids) * len(step.arguments.metric_names)


__all__ = [
    "ActionLease",
    "BoundEvidenceRecord",
    "ControlledToolExecutor",
    "EvidenceInspectionHandler",
    "KnowledgeQueryHandler",
    "ReadOnlyHandlerAuthority",
    "ReadOnlyToolHandler",
    "ReadOnlyToolHandlerDescriptor",
    "RegisteredRunComparisonHandler",
    "SemanticGapKind",
    "SemanticHotspotKind",
    "SemanticHotspotTrigger",
    "ToolLeaseAdmissionError",
    "ToolObservation",
    "ToolObservationStatus",
    "ToolProjectSnapshot",
]

"""Narrow, state-immutable integration facade for bounded model nodes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Generic, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult
from scitaste.model_nodes.profiles import ModelNodeProfile
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    RuntimeInvocationReceipt,
    RuntimeVerification,
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
from scitaste.schema.actions import ResearchAction


class FacadeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImmutableStateProjection(FacadeModel):
    """Explicit read-only state slice; it is never a mutable ``ResearchState``."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    state_snapshot_id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    stage: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    section_ids: tuple[str, ...] = ()
    candidate_actions: tuple[ResearchAction, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references_are_unique(self) -> ImmutableStateProjection:
        for name in ("claim_ids", "evidence_ids", "section_ids"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        action_ids = [item.action_id for item in self.candidate_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("candidate action IDs must not contain duplicates")
        return self

    def to_node_context(self) -> NodeContext:
        return NodeContext(
            project_id=self.project_id,
            stage=self.stage,
            state_snapshot_id=self.state_snapshot_id,
            cumulative_api_cost_usd=0.0,
            claim_ids=list(self.claim_ids),
            evidence_ids=list(self.evidence_ids),
            section_ids=list(self.section_ids),
            candidate_actions=list(self.candidate_actions),
            metadata=self.metadata,
        )


_INPUT_TYPES = {
    "review-semantic": ReviewSemanticInput,
    "interpretation-threat": InterpretationThreatInput,
    "ambiguous-action": AmbiguousActionInput,
    "tool-plan": ToolPlanInput,
    "structured-repair": StructuredRepairInput,
    "venue-paper-review": VenuePaperReviewInput,
}
_OUTPUT_TYPES = {
    "review-semantic": ReviewSemanticOutput,
    "interpretation-threat": InterpretationThreatOutput,
    "ambiguous-action": AmbiguousActionOutput,
    "tool-plan": ToolPlanOutput,
    "structured-repair": StructuredRepairOutput,
    "venue-paper-review": VenuePaperReviewProposal,
}


class ModelNodeFacadeRequest(FacadeModel):
    """Complete immutable request passed from a deterministic workflow controller."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    expected_project_revision: int = Field(ge=0)
    node_name: Literal[
        "review-semantic",
        "interpretation-threat",
        "ambiguous-action",
        "tool-plan",
        "structured-repair",
        "venue-paper-review",
    ]
    node_input: dict[str, JsonValue]
    state_projection: ImmutableStateProjection
    trigger: ModelNodeTrigger
    profile: ModelNodeProfile
    policy: NodePolicy
    backend_mode: RuntimeBackendMode
    replay_source_invocation_id: str | None = None
    seed: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def binding_is_closed(self) -> ModelNodeFacadeRequest:
        if self.state_projection.project_id != self.project_id:
            raise ValueError("state projection belongs to another project")
        input_type = _INPUT_TYPES[self.node_name]
        input_type.model_validate_json(
            json.dumps(self.node_input, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        if self.node_name not in self.profile.allowed_node_names:
            raise ValueError("profile does not allow the selected node")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", exclude={"fingerprint"}),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


ProposalT = TypeVar("ProposalT", bound=BaseModel)


class ModelNodeFacadeResult(FacadeModel, Generic[ProposalT]):
    """Typed advice and durable receipt; neither grants execution authority."""

    receipt: RuntimeInvocationReceipt
    result: NodeResult[ProposalT] | None = None
    advisory_only: Literal[True] = True
    executable: Literal[False] = False


class ModelNodeFacade:
    """Translate immutable workflow projections into durable proposal-only calls."""

    def __init__(self, runtime: ModelNodeRuntime) -> None:
        self.runtime = runtime

    def plan(
        self,
        request: ModelNodeFacadeRequest,
        *,
        backend: StructuredModelBackend | None = None,
        allow_live: bool = False,
    ) -> Any:
        receipt = self.runtime.plan(
            backend=backend,
            allow_live=allow_live,
            **self._runtime_values(request),
        )
        return self._result(request.node_name, receipt)

    def execute(
        self,
        request: ModelNodeFacadeRequest,
        *,
        backend: StructuredModelBackend | None,
        resume: bool = False,
        allow_live: bool = False,
    ) -> Any:
        receipt = self.runtime.execute(
            backend=backend,
            resume=resume,
            allow_live=allow_live,
            **self._runtime_values(request),
        )
        return self._result(request.node_name, receipt)

    def replay(
        self,
        request: ModelNodeFacadeRequest,
        *,
        source_invocation_id: str,
        resume: bool = False,
    ) -> Any:
        payload = request.model_dump(mode="python", exclude_computed_fields=True)
        payload.update(
            backend_mode=RuntimeBackendMode.REPLAY,
            replay_source_invocation_id=source_invocation_id,
        )
        validated = ModelNodeFacadeRequest.model_validate(payload, strict=True)
        return self.execute(validated, backend=None, resume=resume)

    def verify(self, *, project_id: str, run_id: str) -> RuntimeVerification:
        return self.runtime.verify(project_id=project_id, run_id=run_id)

    @staticmethod
    def _runtime_values(request: ModelNodeFacadeRequest) -> dict[str, Any]:
        return {
            "project_id": request.project_id,
            "run_id": request.run_id,
            "invocation_id": request.invocation_id,
            "request_id": request.request_id,
            "expected_project_revision": request.expected_project_revision,
            "state_revision": request.state_projection.state_revision,
            "node_name": request.node_name,
            "node_input": request.node_input,
            "context": request.state_projection.to_node_context(),
            "trigger": request.trigger,
            "profile": request.profile,
            "policy": request.policy,
            "backend_mode": request.backend_mode,
            "replay_source_invocation_id": request.replay_source_invocation_id,
            "seed": request.seed,
        }

    @staticmethod
    def _result(node_name: str, receipt: RuntimeInvocationReceipt) -> Any:
        output_type = _OUTPUT_TYPES[node_name]
        facade_type = ModelNodeFacadeResult[output_type]
        if receipt.result is None:
            return facade_type(receipt=receipt)
        result_type = NodeResult[output_type]
        result = result_type.model_validate_json(
            json.dumps(receipt.result, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        return facade_type(receipt=receipt, result=cast(Any, result))


__all__ = [
    "ImmutableStateProjection",
    "ModelNodeFacade",
    "ModelNodeFacadeRequest",
    "ModelNodeFacadeResult",
]

"""Bounded model nodes whose outputs remain deterministic-policy proposals."""

from __future__ import annotations

import json
from abc import ABC
from typing import Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import (
    NodeContext,
    NodePolicy,
    NodeResult,
    NodeResultStatus,
    StructuredModelRequest,
    StructuredModelResponse,
)
from scitaste.model_nodes.schemas import (
    AmbiguousActionInput,
    AmbiguousActionOutput,
    InterpretationThreatInput,
    InterpretationThreatOutput,
    ReviewSemanticInput,
    ReviewSemanticOutput,
)
from scitaste.schema.actions import MetaAction


class NodePolicyViolationError(ValueError):
    """Raised before a model call when deterministic policy forbids invocation."""


class NodeNotApplicableError(ValueError):
    """Raised when a conditional node should not participate in this decision."""


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelNode(ABC, Generic[InputT, OutputT]):
    """Validate structured semantic advice without granting execution authority."""

    node_name: str
    prompt_version: str
    system_instruction: str
    input_model: type[InputT]
    output_model: type[OutputT]

    def run(
        self,
        input_data: InputT,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
        request_id: str,
        seed: int = 0,
    ) -> NodeResult[OutputT]:
        validated_input = self.input_model.model_validate(input_data)
        self._preflight(validated_input, context=context, backend=backend, policy=policy)
        request = self._build_request(
            validated_input,
            context=context,
            policy=policy,
            request_id=request_id,
            seed=seed,
        )
        request_size = len(
            json.dumps(
                request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        )
        if request_size > policy.max_request_bytes:
            raise NodePolicyViolationError(
                f"structured request exceeds max_request_bytes: {request_size} > "
                f"{policy.max_request_bytes}"
            )

        response = StructuredModelResponse.model_validate(backend.complete(request))
        reasons = self._response_rejections(request, response, policy)
        proposal: OutputT | None = None
        try:
            proposal = self.output_model.model_validate(response.output_payload)
        except ValidationError as exc:
            reasons.append("output schema violation: " + _validation_summary(exc))
        if proposal is not None:
            reasons.extend(
                self._proposal_rejections(
                    proposal,
                    input_data=validated_input,
                    context=context,
                    policy=policy,
                )
            )
            reasons.extend(
                self._action_rejections(
                    proposal,
                    input_data=validated_input,
                    context=context,
                    policy=policy,
                )
            )

        result_type = NodeResult[self.output_model]
        return cast(
            NodeResult[OutputT],
            result_type(
                node_name=self.node_name,
                policy_id=policy.policy_id,
                status=NodeResultStatus.REJECTED if reasons else NodeResultStatus.ACCEPTED,
                request=request,
                response=response,
                proposal=proposal,
                rejection_reasons=reasons,
            ),
        )

    def _build_request(
        self,
        input_data: InputT,
        *,
        context: NodeContext,
        policy: NodePolicy,
        request_id: str,
        seed: int,
    ) -> StructuredModelRequest:
        return StructuredModelRequest(
            request_id=request_id,
            node_name=self.node_name,
            stage=context.stage,
            state_snapshot_id=context.state_snapshot_id,
            expected_backend=policy.expected_backend,
            expected_model=policy.expected_model,
            policy_id=policy.policy_id,
            policy_fingerprint=policy.fingerprint,
            system_instruction=self.system_instruction,
            input_payload={
                "context": context.model_dump(mode="json"),
                "input": input_data.model_dump(mode="json"),
            },
            output_schema=self.output_model.model_json_schema(mode="validation"),
            seed=seed,
            prompt_version=self.prompt_version,
        )

    def _preflight(
        self,
        input_data: InputT,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
    ) -> None:
        del input_data, context
        if not policy.enabled:
            raise NodePolicyViolationError("model node policy is disabled")
        if self.node_name not in policy.allowed_node_names:
            raise NodePolicyViolationError(f"node {self.node_name!r} is not allowlisted")
        if backend.name != policy.expected_backend or backend.model != policy.expected_model:
            raise NodePolicyViolationError(
                "backend identity does not match the pinned policy: "
                f"{backend.name}/{backend.model} != "
                f"{policy.expected_backend}/{policy.expected_model}"
            )

    def _response_rejections(
        self,
        request: StructuredModelRequest,
        response: StructuredModelResponse,
        policy: NodePolicy,
    ) -> list[str]:
        reasons: list[str] = []
        if response.request_id != request.request_id:
            reasons.append("response request id does not match invocation")
        if response.request_fingerprint != request.fingerprint:
            reasons.append("response fingerprint does not match invocation")
        if response.backend != policy.expected_backend:
            reasons.append("response backend differs from pinned backend")
        if response.model != policy.expected_model:
            reasons.append("response model differs from pinned model")
        usage = response.usage
        if usage.input_tokens > policy.max_input_tokens:
            reasons.append("input token budget exceeded")
        if usage.output_tokens > policy.max_output_tokens:
            reasons.append("output token budget exceeded")
        if usage.input_tokens + usage.output_tokens > policy.max_total_tokens:
            reasons.append("total token budget exceeded")
        if usage.cost_usd is None:
            if policy.require_cost_telemetry:
                reasons.append("API cost telemetry is required")
        elif usage.cost_usd > policy.max_api_cost_usd:
            reasons.append("API cost budget exceeded")
        if response.latency_ms > policy.max_latency_ms:
            reasons.append("latency budget exceeded")
        allowed_tools = set(policy.allowed_tool_names)
        for tool_call in response.tool_calls:
            if tool_call.name not in allowed_tools:
                reasons.append(f"tool {tool_call.name!r} is not allowlisted")
        return reasons

    def _proposal_rejections(
        self,
        proposal: OutputT,
        *,
        input_data: InputT,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del proposal, input_data, context, policy
        return []

    def _proposed_action_types(self, proposal: OutputT) -> list[MetaAction]:
        del proposal
        return []

    def _action_rejections(
        self,
        proposal: OutputT,
        *,
        input_data: InputT,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del input_data, context
        allowed = set(policy.allowed_action_types)
        return [
            f"action type {action_type.value!r} is not allowlisted"
            for action_type in self._proposed_action_types(proposal)
            if action_type not in allowed
        ]


class ReviewSemanticNode(ModelNode[ReviewSemanticInput, ReviewSemanticOutput]):
    node_name = "review-semantic"
    prompt_version = "review-semantic-v1"
    system_instruction = (
        "Parse reviewer text into typed concern proposals. Do not close concerns, change "
        "claims, execute actions, or invent claim, section, evidence, or tool identifiers."
    )
    input_model = ReviewSemanticInput
    output_model = ReviewSemanticOutput

    def _proposal_rejections(
        self,
        proposal: ReviewSemanticOutput,
        *,
        input_data: ReviewSemanticInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        known_claims = set(context.claim_ids)
        known_sections = set(context.section_ids)
        permitted_evidence = set(input_data.permitted_evidence_types)
        for concern in proposal.concerns:
            unknown_claims = sorted(set(concern.target_claim_ids) - known_claims)
            if unknown_claims:
                reasons.append(f"concern {concern.concern_id!r} references unknown claims")
            if concern.target_section is not None and concern.target_section not in known_sections:
                reasons.append(f"concern {concern.concern_id!r} references an unknown section")
            if set(concern.required_evidence_types) - permitted_evidence:
                reasons.append(
                    f"concern {concern.concern_id!r} requests an unpermitted evidence type"
                )
        return reasons

    def _proposed_action_types(self, proposal: ReviewSemanticOutput) -> list[MetaAction]:
        return [item.proposed_action_type for item in proposal.concerns]


class InterpretationThreatNode(ModelNode[InterpretationThreatInput, InterpretationThreatOutput]):
    node_name = "interpretation-threat"
    prompt_version = "interpretation-threat-v1"
    system_instruction = (
        "Propose validity threats and alternative explanations. Do not assign claim status, "
        "promote evidence, alter measurements, execute tools, or authorize a state transition."
    )
    input_model = InterpretationThreatInput
    output_model = InterpretationThreatOutput

    def _proposal_rejections(
        self,
        proposal: InterpretationThreatOutput,
        *,
        input_data: InterpretationThreatInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del input_data, policy
        known_evidence = set(context.evidence_ids)
        reasons: list[str] = []
        for threat in proposal.threats:
            if set(threat.evidence_ids) - known_evidence:
                reasons.append(f"threat {threat.threat_id!r} references unknown evidence")
        return reasons

    def _proposed_action_types(self, proposal: InterpretationThreatOutput) -> list[MetaAction]:
        return [proposal.recommended_action_type] if proposal.recommended_action_type else []


class AmbiguousActionNode(ModelNode[AmbiguousActionInput, AmbiguousActionOutput]):
    node_name = "ambiguous-action"
    prompt_version = "ambiguous-action-v1"
    system_instruction = (
        "Rank only the supplied feasible actions when deterministic scores are ambiguous. "
        "Do not create actions, call tools, change budgets, or select an action for execution."
    )
    input_model = AmbiguousActionInput
    output_model = AmbiguousActionOutput

    def _preflight(
        self,
        input_data: AmbiguousActionInput,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
    ) -> None:
        super()._preflight(input_data, context=context, backend=backend, policy=policy)
        if input_data.score_margin > policy.ambiguity_margin_max:
            raise NodeNotApplicableError(
                f"deterministic score margin {input_data.score_margin:.6f} exceeds "
                f"ambiguity threshold {policy.ambiguity_margin_max:.6f}"
            )
        context_ids = {item.action_id for item in context.candidate_actions}
        input_ids = {item.action_id for item in input_data.candidate_actions}
        if context_ids and context_ids != input_ids:
            raise NodePolicyViolationError(
                "ambiguous-action input differs from context candidate actions"
            )

    def _proposal_rejections(
        self,
        proposal: AmbiguousActionOutput,
        *,
        input_data: AmbiguousActionInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        candidate_ids = {item.action_id for item in input_data.candidate_actions}
        if set(proposal.ranked_action_ids) != candidate_ids:
            return ["ranked action ids must cover exactly the supplied candidates"]
        return []

    def _proposed_action_types(self, proposal: AmbiguousActionOutput) -> list[MetaAction]:
        del proposal
        return []

    def _action_rejections(
        self,
        proposal: AmbiguousActionOutput,
        *,
        input_data: AmbiguousActionInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del proposal, context
        allowed = set(policy.allowed_action_types)
        return [
            f"candidate action type {action.type.value!r} is not allowlisted"
            for action in input_data.candidate_actions
            if action.type not in allowed
        ]


def _validation_summary(exc: ValidationError) -> str:
    summaries: list[str] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(item) for item in error["loc"]) or "root"
        summaries.append(f"{location}: {error['type']}")
    return "; ".join(summaries)

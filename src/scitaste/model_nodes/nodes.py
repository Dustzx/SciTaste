"""Bounded model nodes whose outputs remain deterministic-policy proposals."""

from __future__ import annotations

import json
from abc import ABC
from copy import deepcopy
from decimal import Decimal
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
from scitaste.model_nodes.profiles import (
    ModelNodeProfile,
    ProfileConfigurationError,
    validate_profile_binding,
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
    EvidenceInspectPermission,
    EvidenceInspectStep,
    KnowledgeQueryPermission,
    KnowledgeQueryStep,
    RegisteredRunComparePermission,
    RegisteredRunCompareStep,
    StructuredRepairInput,
    StructuredRepairOutput,
    ToolPlanInput,
    ToolPlanOutput,
    output_schema_sha256,
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
        profile: ModelNodeProfile | None = None,
    ) -> NodeResult[OutputT]:
        validated_input = _boundary_copy(self.input_model, input_data)
        validated_context = _boundary_copy(NodeContext, context)
        validated_policy = _boundary_copy(NodePolicy, policy, exclude={"fingerprint"})
        validated_profile = (
            _boundary_copy(ModelNodeProfile, profile, exclude={"fingerprint"})
            if profile is not None
            else None
        )
        if validated_profile is not None:
            try:
                validate_profile_binding(
                    validated_profile,
                    validated_policy,
                    node_name=self.node_name,
                )
            except ProfileConfigurationError as exc:
                raise NodePolicyViolationError(str(exc)) from exc
        self._preflight(
            validated_input,
            context=validated_context,
            backend=backend,
            policy=validated_policy,
        )
        request = self._build_request(
            validated_input,
            context=validated_context,
            policy=validated_policy,
            request_id=request_id,
            seed=seed,
            profile=validated_profile,
        )
        audited_request = _boundary_copy(
            StructuredModelRequest,
            request,
            exclude={"fingerprint"},
        )
        expected_request_fingerprint = audited_request.fingerprint
        request_size = len(
            json.dumps(
                audited_request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        )
        if request_size > validated_policy.max_request_bytes:
            raise NodePolicyViolationError(
                f"structured request exceeds max_request_bytes: {request_size} > "
                f"{validated_policy.max_request_bytes}"
            )
        if (
            validated_profile is not None
            and request_size > validated_profile.generation.max_request_bytes
        ):
            raise NodePolicyViolationError(
                "structured request exceeds the provider generation envelope: "
                f"{request_size} > {validated_profile.generation.max_request_bytes}"
            )

        backend_request = _boundary_copy(
            StructuredModelRequest,
            audited_request,
            exclude={"fingerprint"},
        )
        backend_response = backend.complete(backend_request)
        response = _boundary_copy(StructuredModelResponse, backend_response)
        reasons: list[str] = []
        try:
            backend_request_fingerprint = backend_request.fingerprint
        except (TypeError, ValueError):
            backend_request_fingerprint = None
        if backend_request_fingerprint != expected_request_fingerprint:
            reasons.append("backend mutated structured request after preflight")
        reasons.extend(
            self._response_rejections(
                audited_request,
                response,
                context=validated_context,
                policy=validated_policy,
                profile=validated_profile,
            )
        )
        parsed_proposal: OutputT | None = None
        try:
            payload_json = json.dumps(
                response.output_payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            parsed_proposal = self.output_model.model_validate_json(payload_json, strict=True)
        except ValidationError as exc:
            reasons.append("output schema violation: " + _validation_summary(exc))
        except ValueError as exc:
            reasons.append(f"output schema violation: invalid JSON value ({exc})")
        if parsed_proposal is not None:
            reasons.extend(
                self._proposal_rejections(
                    parsed_proposal,
                    input_data=validated_input,
                    context=validated_context,
                    policy=validated_policy,
                )
            )
            reasons.extend(
                self._action_rejections(
                    parsed_proposal,
                    input_data=validated_input,
                    context=validated_context,
                    policy=validated_policy,
                )
            )

        rejected = bool(reasons)
        result_type = NodeResult[self.output_model]
        return cast(
            NodeResult[OutputT],
            result_type(
                node_name=self.node_name,
                policy_id=validated_policy.policy_id,
                status=NodeResultStatus.REJECTED if rejected else NodeResultStatus.ACCEPTED,
                request=audited_request,
                response=response,
                proposal=None if rejected else parsed_proposal,
                untrusted_proposal=parsed_proposal if rejected else None,
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
        profile: ModelNodeProfile | None = None,
    ) -> StructuredModelRequest:
        profile_fields = (
            {
                "profile_id": profile.profile_id,
                "profile_fingerprint": profile.fingerprint,
                "generation_envelope": profile.generation,
                "admission_budget": profile.admission,
                "cumulative_project_budget": profile.cumulative_project,
            }
            if profile is not None
            else {}
        )
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
            **profile_fields,
        )

    def _preflight(
        self,
        input_data: InputT,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
    ) -> None:
        del input_data
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
        if context.cumulative_api_cost_usd > policy.max_api_cost_usd:
            raise NodePolicyViolationError(
                "cumulative project API cost already exceeds the model-node policy budget: "
                f"{context.cumulative_api_cost_usd} > {policy.max_api_cost_usd}"
            )

    def _response_rejections(
        self,
        request: StructuredModelRequest,
        response: StructuredModelResponse,
        *,
        context: NodeContext,
        policy: NodePolicy,
        profile: ModelNodeProfile | None = None,
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
            reasons.append("API cost telemetry is required")
        elif _cumulative_cost_exceeds(
            context.cumulative_api_cost_usd,
            usage.cost_usd,
            policy.max_api_cost_usd,
        ):
            reasons.append("cumulative project API cost budget exceeded")
        if response.latency_ms > policy.max_latency_ms:
            reasons.append("latency budget exceeded")
        allowed_tools = set(policy.allowed_tool_names)
        for tool_call in response.tool_calls:
            if tool_call.name not in allowed_tools:
                reasons.append(f"tool {tool_call.name!r} is not allowlisted")
        if profile is not None:
            if (
                usage.cost_usd is not None
                and usage.cost_usd > profile.admission.max_response_cost_usd
            ):
                reasons.append("single-response cost budget exceeded")
            if len(response.tool_calls) > profile.admission.max_tool_call_proposals:
                reasons.append("tool-call proposal count exceeded")
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


class VenuePaperReviewNode(ModelNode[VenuePaperReviewInput, VenuePaperReviewProposal]):
    """Review exact paper content without claiming expert or conference authority."""

    node_name = "venue-paper-review"
    prompt_version = "venue-paper-review-v2"
    system_instruction = (
        "Review the supplied anonymous paper against the four venue questions. Return a concise "
        "summary, concrete strengths and weaknesses, one accept/reject recommendation with one "
        "or two key reasons, questions, and only decision-relevant typed concerns. Do not invent "
        "claims, sections, evidence types, numeric conference scores, reviewer identity, official "
        "authority, experiments, citations, or facts absent from the paper. This is internal "
        "model feedback, not independent expert review."
    )
    input_model = VenuePaperReviewInput
    output_model = VenuePaperReviewProposal

    def _build_request(
        self,
        input_data: VenuePaperReviewInput,
        *,
        context: NodeContext,
        policy: NodePolicy,
        request_id: str,
        seed: int,
        profile: ModelNodeProfile | None = None,
    ) -> StructuredModelRequest:
        request = super()._build_request(
            input_data,
            context=context,
            policy=policy,
            request_id=request_id,
            seed=seed,
            profile=profile,
        )
        allowed_actions = tuple(sorted({item.value for item in policy.allowed_action_types}))
        from scitaste.review.routing import ReviewActionRouter

        category_action_map = {
            category: action.value
            for category, action in sorted(ReviewActionRouter.ROUTES.items())
            if action.value in allowed_actions
        }
        closed_world_contract = {
            "registered_claim_ids": list(context.claim_ids),
            "registered_section_ids": list(context.section_ids),
            "permitted_evidence_types": list(input_data.permitted_evidence_types),
            "allowed_action_types": list(allowed_actions),
            "category_action_map": category_action_map,
            "reference_rule": (
                "Use only listed identifiers. Use [] or null when no listed identifier applies."
            ),
            "action_rule": (
                "Use only an allowed action and preserve the deterministic category/action map."
            ),
            "evidence_flag_rules": [
                "requires_new_experiment=true requires requires_new_evidence=true.",
                (
                    "ADD_EXPERIMENT, ADD_BASELINE, and REVISE_METHOD concerns require both "
                    "requires_new_experiment=true and requires_new_evidence=true."
                ),
                "All other allowed actions require requires_new_experiment=false.",
            ],
        }
        input_payload = deepcopy(request.input_payload)
        input_payload["closed_world_contract"] = closed_world_contract
        output_schema = _closed_venue_review_schema(
            request.output_schema,
            claim_ids=tuple(context.claim_ids),
            section_ids=tuple(context.section_ids),
            evidence_types=tuple(input_data.permitted_evidence_types),
            action_types=allowed_actions,
        )
        values = request.model_dump(mode="python", exclude={"fingerprint"})
        values["input_payload"] = input_payload
        values["output_schema"] = output_schema
        return StructuredModelRequest.model_validate(values, strict=True)

    def _proposal_rejections(
        self,
        proposal: VenuePaperReviewProposal,
        *,
        input_data: VenuePaperReviewInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        if proposal.packet_sha256 != input_data.packet_sha256:
            reasons.append("proposal targets a different venue review packet")
        expected_packet = context.metadata.get("review_packet_sha256")
        if expected_packet != input_data.packet_sha256:
            reasons.append("node context does not bind the venue review packet")
        known_claims = set(context.claim_ids)
        known_sections = set(context.section_ids)
        permitted_evidence = set(input_data.permitted_evidence_types)
        from scitaste.review.routing import ReviewActionRouter

        experiment_actions = {
            MetaAction.ADD_EXPERIMENT,
            MetaAction.ADD_BASELINE,
            MetaAction.REVISE_METHOD,
        }
        for concern in proposal.concerns:
            if set(concern.target_claim_ids) - known_claims:
                reasons.append(f"concern {concern.concern_id!r} references unknown claims")
            if concern.target_section is not None and concern.target_section not in known_sections:
                reasons.append(f"concern {concern.concern_id!r} references an unknown section")
            if set(concern.required_evidence_types) - permitted_evidence:
                reasons.append(
                    f"concern {concern.concern_id!r} requests an unpermitted evidence type"
                )
            expected_action = ReviewActionRouter.ROUTES.get(concern.category.value)
            if concern.proposed_action_type is not expected_action:
                reasons.append(f"concern {concern.concern_id!r} action does not match its category")
            if expected_action in experiment_actions and not (
                concern.requires_new_experiment and concern.requires_new_evidence
            ):
                reasons.append(
                    f"concern {concern.concern_id!r} experiment action lacks evidence flags"
                )
            if expected_action not in experiment_actions and concern.requires_new_experiment:
                reasons.append(
                    f"concern {concern.concern_id!r} non-experiment action requests an experiment"
                )
        return reasons

    def _proposed_action_types(self, proposal: VenuePaperReviewProposal) -> list[MetaAction]:
        return [item.proposed_action_type for item in proposal.concerns]


def _closed_venue_review_schema(
    schema: dict[str, object],
    *,
    claim_ids: tuple[str, ...],
    section_ids: tuple[str, ...],
    evidence_types: tuple[str, ...],
    action_types: tuple[str, ...],
) -> dict[str, object]:
    """Bind free-form review references to this invocation's exact vocabularies."""

    closed = deepcopy(schema)
    definitions = closed.get("$defs")
    if not isinstance(definitions, dict):  # pragma: no cover - controlled Pydantic schema
        raise ValueError("venue review output schema has no definitions")
    concern = definitions.get("ReviewConcernProposal")
    if not isinstance(concern, dict):  # pragma: no cover - controlled Pydantic schema
        raise ValueError("venue review output schema has no concern definition")
    properties = concern.get("properties")
    if not isinstance(properties, dict):  # pragma: no cover - controlled Pydantic schema
        raise ValueError("venue review concern schema has no properties")

    _close_array_items(properties, "target_claim_ids", claim_ids)
    _close_nullable_string(properties, "target_section", section_ids)
    _close_array_items(properties, "required_evidence_types", evidence_types)
    action_definition = definitions.get("MetaAction")
    if not isinstance(action_definition, dict):  # pragma: no cover
        raise ValueError("venue review output schema has no action definition")
    action_definition["enum"] = list(action_types)

    from scitaste.review.routing import ReviewActionRouter

    experiment_actions = {
        MetaAction.ADD_EXPERIMENT,
        MetaAction.ADD_BASELINE,
        MetaAction.REVISE_METHOD,
    }
    category_contracts: list[dict[str, object]] = []
    for category, action in sorted(ReviewActionRouter.ROUTES.items()):
        if action.value not in action_types:
            continue
        then_properties: dict[str, object] = {
            "proposed_action_type": {"const": action.value},
        }
        required = ["proposed_action_type"]
        if action in experiment_actions:
            then_properties.update(
                {
                    "requires_new_evidence": {"const": True},
                    "requires_new_experiment": {"const": True},
                }
            )
            required.extend(["requires_new_evidence", "requires_new_experiment"])
        else:
            then_properties["requires_new_experiment"] = {"const": False}
        category_contracts.append(
            {
                "if": {
                    "properties": {"category": {"const": category}},
                    "required": ["category"],
                },
                "then": {
                    "properties": then_properties,
                    "required": required,
                },
            },
        )
    category_contracts.append(
        {
            "if": {
                "properties": {"requires_new_experiment": {"const": True}},
                "required": ["requires_new_experiment"],
            },
            "then": {
                "properties": {"requires_new_evidence": {"const": True}},
                "required": ["requires_new_evidence"],
            },
        }
    )
    concern["allOf"] = category_contracts
    return closed


def _close_array_items(
    properties: dict[str, object],
    field_name: str,
    values: tuple[str, ...],
) -> None:
    field = properties[field_name]
    if not isinstance(field, dict):  # pragma: no cover - controlled Pydantic schema
        raise ValueError(f"venue review field {field_name!r} has an invalid schema")
    if values:
        field["items"] = {"enum": list(values), "type": "string"}
    else:
        field["maxItems"] = 0


def _close_nullable_string(
    properties: dict[str, object],
    field_name: str,
    values: tuple[str, ...],
) -> None:
    field = properties[field_name]
    if not isinstance(field, dict):  # pragma: no cover - controlled Pydantic schema
        raise ValueError(f"venue review field {field_name!r} has an invalid schema")
    field["anyOf"] = (
        [{"enum": list(values), "type": "string"}, {"type": "null"}]
        if values
        else [{"type": "null"}]
    )


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
        if not context.candidate_actions:
            raise NodePolicyViolationError(
                "ambiguous-action requires the complete deterministic candidate context"
            )
        context_actions = {
            item.action_id: _canonical_model_json(item) for item in context.candidate_actions
        }
        input_actions = {
            item.action_id: _canonical_model_json(item) for item in input_data.candidate_actions
        }
        if context_actions != input_actions:
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


class ToolPlanNode(ModelNode[ToolPlanInput, ToolPlanOutput]):
    """Propose a bounded plan over explicit read-only first-party tools."""

    node_name = "tool-plan"
    prompt_version = "tool-plan-v1"
    system_instruction = (
        "Propose an ordered plan using only the supplied read-only tool profile and scope. "
        "Copy controlled_tool_profile_binding.profile_id and "
        "controlled_tool_profile_binding.profile_fingerprint exactly into the corresponding "
        "output fields. "
        "Return data-only steps; do not call a provider tool, execute any step, mutate state, "
        "open network access, launch a process, or expand an identifier scope."
    )
    input_model = ToolPlanInput
    output_model = ToolPlanOutput

    def _build_request(
        self,
        input_data: ToolPlanInput,
        *,
        context: NodeContext,
        policy: NodePolicy,
        request_id: str,
        seed: int,
        profile: ModelNodeProfile | None = None,
    ) -> StructuredModelRequest:
        """Expose the exact deterministic binding that the response must echo.

        Pydantic does not include nested computed fields when ``ToolPlanInput`` is
        serialized. Requiring the model to reproduce a hash that was not present in
        its request made live Tool Plan responses impossible to admit even when the
        semantic action was correct.
        """

        request = super()._build_request(
            input_data,
            context=context,
            policy=policy,
            request_id=request_id,
            seed=seed,
            profile=profile,
        )
        request_values = request.model_dump(mode="python", exclude={"fingerprint"})
        input_payload = dict(request.input_payload)
        input_payload["controlled_tool_profile_binding"] = {
            "profile_id": input_data.tool_profile.profile_id,
            "profile_fingerprint": input_data.tool_profile.fingerprint,
        }
        request_values["input_payload"] = input_payload
        return StructuredModelRequest.model_validate(request_values, strict=True)

    def _preflight(
        self,
        input_data: ToolPlanInput,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
    ) -> None:
        super()._preflight(input_data, context=context, backend=backend, policy=policy)
        if input_data.scope.project_id != context.project_id:
            raise NodePolicyViolationError("tool scope belongs to another project")
        if input_data.scope.state_snapshot_id != context.state_snapshot_id:
            raise NodePolicyViolationError("tool scope belongs to another state snapshot")
        profile_tools = set(input_data.tool_profile.allowed_tool_names)
        if profile_tools != set(policy.allowed_tool_names):
            raise NodePolicyViolationError("controlled tool profile and policy allowlists differ")
        self._validate_profile_scope(input_data, context=context)

    def _response_rejections(
        self,
        request: StructuredModelRequest,
        response: StructuredModelResponse,
        *,
        context: NodeContext,
        policy: NodePolicy,
        profile: ModelNodeProfile | None = None,
    ) -> list[str]:
        reasons = super()._response_rejections(
            request,
            response,
            context=context,
            policy=policy,
            profile=profile,
        )
        if response.tool_calls:
            reasons.append("provider-native tool calls cannot substitute for typed tool-plan steps")
        return reasons

    def _proposal_rejections(
        self,
        proposal: ToolPlanOutput,
        *,
        input_data: ToolPlanInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        controlled = input_data.tool_profile
        reasons: list[str] = []
        if proposal.tool_profile_id != controlled.profile_id:
            reasons.append("tool plan names a different controlled profile")
        if proposal.tool_profile_fingerprint != controlled.fingerprint:
            reasons.append("tool plan fingerprint differs from the controlled profile")
        if len(proposal.steps) > controlled.max_plan_steps:
            reasons.append("tool plan step budget exceeded")
        dependency_edges = sum(len(step.depends_on) for step in proposal.steps)
        if dependency_edges > controlled.max_dependency_edges:
            reasons.append("tool plan dependency-edge budget exceeded")

        prior_steps: set[str] = set()
        for step in proposal.steps:
            unknown_dependencies = sorted(set(step.depends_on) - prior_steps)
            if unknown_dependencies:
                reasons.append(f"step {step.step_id!r} has an unknown or forward dependency")
            reasons.extend(self._step_rejections(step, input_data=input_data))
            prior_steps.add(step.step_id)
        return reasons

    @staticmethod
    def _validate_profile_scope(input_data: ToolPlanInput, *, context: NodeContext) -> None:
        scope = input_data.scope
        for permission in input_data.tool_profile.permissions:
            if isinstance(permission, KnowledgeQueryPermission):
                if set(permission.allowed_library_ids) - set(scope.library_ids):
                    raise NodePolicyViolationError(
                        "knowledge-query permission escapes the supplied library scope"
                    )
            elif isinstance(permission, EvidenceInspectPermission):
                allowed = set(permission.allowed_evidence_ids)
                if allowed - set(scope.evidence_ids):
                    raise NodePolicyViolationError(
                        "evidence-inspect permission escapes the supplied evidence scope"
                    )
                if allowed - set(context.evidence_ids):
                    raise NodePolicyViolationError(
                        "evidence-inspect permission escapes the immutable node context"
                    )
            elif isinstance(permission, RegisteredRunComparePermission):
                if set(permission.allowed_run_ids) - set(scope.run_ids):
                    raise NodePolicyViolationError(
                        "run-comparison permission escapes the supplied run scope"
                    )
                if set(permission.allowed_metric_names) - set(scope.metric_names):
                    raise NodePolicyViolationError(
                        "run-comparison permission escapes the supplied metric scope"
                    )

    @staticmethod
    def _step_rejections(
        step: KnowledgeQueryStep | EvidenceInspectStep | RegisteredRunCompareStep,
        *,
        input_data: ToolPlanInput,
    ) -> list[str]:
        controlled = input_data.tool_profile
        scope = input_data.scope
        permission = controlled.permission_for(step.tool_name)
        if permission is None:
            return [f"step {step.step_id!r} proposes an unavailable tool"]
        reasons: list[str] = []
        if isinstance(step, KnowledgeQueryStep):
            assert isinstance(permission, KnowledgeQueryPermission)
            if set(step.arguments.library_ids) - set(permission.allowed_library_ids):
                reasons.append(f"step {step.step_id!r} escapes the allowed library scope")
            if set(step.arguments.library_ids) - set(scope.library_ids):
                reasons.append(f"step {step.step_id!r} references an unknown library")
            if len(step.arguments.library_ids) > permission.max_library_ids:
                reasons.append(f"step {step.step_id!r} exceeds the library-count limit")
            if len(step.arguments.query) > permission.max_query_chars:
                reasons.append(f"step {step.step_id!r} exceeds the query-length limit")
            if step.arguments.top_k > permission.max_top_k:
                reasons.append(f"step {step.step_id!r} exceeds the retrieval limit")
        elif isinstance(step, EvidenceInspectStep):
            assert isinstance(permission, EvidenceInspectPermission)
            if set(step.arguments.evidence_ids) - set(permission.allowed_evidence_ids):
                reasons.append(f"step {step.step_id!r} escapes the allowed evidence scope")
            if set(step.arguments.evidence_ids) - set(scope.evidence_ids):
                reasons.append(f"step {step.step_id!r} references unknown evidence")
            if len(step.arguments.evidence_ids) > permission.max_evidence_items:
                reasons.append(f"step {step.step_id!r} exceeds the evidence-item limit")
        else:
            assert isinstance(step, RegisteredRunCompareStep)
            assert isinstance(permission, RegisteredRunComparePermission)
            if set(step.arguments.run_ids) - set(permission.allowed_run_ids):
                reasons.append(f"step {step.step_id!r} escapes the allowed run scope")
            if set(step.arguments.run_ids) - set(scope.run_ids):
                reasons.append(f"step {step.step_id!r} references an unknown run")
            if set(step.arguments.metric_names) - set(permission.allowed_metric_names):
                reasons.append(f"step {step.step_id!r} escapes the allowed metric scope")
            if set(step.arguments.metric_names) - set(scope.metric_names):
                reasons.append(f"step {step.step_id!r} references an unknown metric")
            if len(step.arguments.run_ids) > permission.max_runs:
                reasons.append(f"step {step.step_id!r} exceeds the run-count limit")
            if len(step.arguments.metric_names) > permission.max_metrics:
                reasons.append(f"step {step.step_id!r} exceeds the metric-count limit")
        return reasons


_REPAIR_TARGET_TYPES: dict[str, type[BaseModel]] = {
    "review-semantic": ReviewSemanticOutput,
    "interpretation-threat": InterpretationThreatOutput,
    "ambiguous-action": AmbiguousActionOutput,
    "tool-plan": ToolPlanOutput,
}


class StructuredRepairNode(ModelNode[StructuredRepairInput, StructuredRepairOutput]):
    """Propose a schema-valid replacement without accepting it for the target node."""

    node_name = "structured-repair"
    prompt_version = "structured-repair-v1"
    system_instruction = (
        "Propose a repaired JSON payload for the pinned supported target schema. Preserve the "
        "target identity and return only a repair proposal. Do not execute tools, retry or alter "
        "the failed invocation, hide its evidence, or claim target-node acceptance."
    )
    input_model = StructuredRepairInput
    output_model = StructuredRepairOutput

    def _preflight(
        self,
        input_data: StructuredRepairInput,
        *,
        context: NodeContext,
        backend: StructuredModelBackend,
        policy: NodePolicy,
    ) -> None:
        super()._preflight(input_data, context=context, backend=backend, policy=policy)
        if policy.allowed_tool_names:
            raise NodePolicyViolationError("structured repair cannot receive a tool allowlist")
        expected = output_schema_sha256(_REPAIR_TARGET_TYPES[input_data.target_node_name])
        if input_data.target_schema_sha256 != expected:
            raise NodePolicyViolationError("repair target schema fingerprint does not match")

    def _response_rejections(
        self,
        request: StructuredModelRequest,
        response: StructuredModelResponse,
        *,
        context: NodeContext,
        policy: NodePolicy,
        profile: ModelNodeProfile | None = None,
    ) -> list[str]:
        reasons = super()._response_rejections(
            request,
            response,
            context=context,
            policy=policy,
            profile=profile,
        )
        if response.tool_calls:
            reasons.append("structured repair cannot contain provider-native tool calls")
        return reasons

    def _proposal_rejections(
        self,
        proposal: StructuredRepairOutput,
        *,
        input_data: StructuredRepairInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        reasons: list[str] = []
        if proposal.target_node_name != input_data.target_node_name:
            reasons.append("repair proposal names a different target node")
        if proposal.target_schema_sha256 != input_data.target_schema_sha256:
            reasons.append("repair proposal names a different target schema")
        target_type = _REPAIR_TARGET_TYPES[input_data.target_node_name]
        try:
            target_type.model_validate_json(
                json.dumps(
                    proposal.repaired_payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ),
                strict=True,
            )
        except ValidationError as exc:
            reasons.append("repaired payload violates target schema: " + _validation_summary(exc))
        except ValueError as exc:
            reasons.append(f"repaired payload is not strict JSON: {exc}")
        return reasons


def _validation_summary(exc: ValidationError) -> str:
    summaries: list[str] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(item) for item in error["loc"]) or "root"
        summaries.append(f"{location}: {error['type']}")
    return "; ".join(summaries)


ModelT = TypeVar("ModelT", bound=BaseModel)


def _boundary_copy(
    model_type: type[ModelT],
    value: object,
    *,
    exclude: set[str] | None = None,
) -> ModelT:
    """Revalidate a deep model snapshot at an invocation boundary."""

    validated = model_type.model_validate(value)
    payload = validated.model_dump(mode="python", exclude=exclude)
    return model_type.model_validate(payload, strict=True)


def _canonical_model_json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def _cumulative_cost_exceeds(cumulative: float, current: float, limit: float) -> bool:
    return Decimal(str(cumulative)) + Decimal(str(current)) > Decimal(str(limit))

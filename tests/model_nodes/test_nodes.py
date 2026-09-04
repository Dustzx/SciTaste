from __future__ import annotations

import pytest

from scitaste.backends.base import Usage
from scitaste.evidence.interpretation import ClaimRelation, InterpretationContext, ResultRecord
from scitaste.model_nodes import (
    AmbiguousActionInput,
    AmbiguousActionNode,
    InterpretationThreatInput,
    InterpretationThreatNode,
    NodeContext,
    NodeNotApplicableError,
    NodePolicy,
    NodePolicyViolationError,
    NodeResultStatus,
    ReviewSemanticInput,
    ReviewSemanticNode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    ToolCallProposal,
)
from scitaste.schema.actions import MetaAction, ResearchAction


def context(
    *,
    candidate_actions: list[ResearchAction] | None = None,
    cumulative_api_cost_usd: float = 0.0,
) -> NodeContext:
    return NodeContext(
        project_id="project-1",
        stage="COMMUNICATION",
        state_snapshot_id="snapshot-1",
        cumulative_api_cost_usd=cumulative_api_cost_usd,
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
        section_ids=["method"],
        candidate_actions=candidate_actions or [],
    )


def policy(
    node_name: str,
    *,
    actions: list[MetaAction] | None = None,
    **updates: object,
) -> NodePolicy:
    values: dict[str, object] = {
        "policy_id": f"policy-{node_name}",
        "enabled": True,
        "allowed_node_names": [node_name],
        "expected_backend": "scripted",
        "expected_model": "scripted-v1",
        "allowed_action_types": actions or [],
        "max_input_tokens": 100,
        "max_output_tokens": 100,
        "max_total_tokens": 200,
        "max_api_cost_usd": 0.15,
        "max_latency_ms": 1_000,
    }
    values.update(updates)
    return NodePolicy.model_validate(values)


def backend(request_id: str, payload: object, **updates: object) -> ScriptedStructuredBackend:
    reply_values: dict[str, object] = {"output_payload": payload}
    reply_values.update(updates)
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={request_id: ScriptedStructuredReply.model_validate(reply_values)},
    )


def review_payload(**concern_updates: object) -> dict[str, object]:
    concern: dict[str, object] = {
        "concern_id": "concern-1",
        "category": "missing_baseline",
        "severity": "high",
        "target_claim_ids": ["claim-1"],
        "target_section": "method",
        "text": "The claim needs a matched baseline.",
        "requires_new_evidence": True,
        "requires_new_experiment": True,
        "required_evidence_types": ["matched baseline"],
        "proposed_action_type": "ADD_BASELINE",
    }
    concern.update(concern_updates)
    return {
        "concerns": [concern],
        "summary": "One substantive evidence concern.",
        "confidence": 0.91,
    }


def test_review_node_returns_typed_advice_without_execution_authority() -> None:
    node = ReviewSemanticNode()
    result = node.run(
        ReviewSemanticInput(
            review_text="The central claim lacks a matched baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend("review-1", review_payload()),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-1",
        seed=7,
    )

    assert result.status == NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.concerns[0].proposed_action_type == MetaAction.ADD_BASELINE
    assert result.advisory_only is True
    assert result.executable is False
    assert result.request.expected_model == "scripted-v1"
    assert result.response.usage.cost_usd == 0


def test_review_node_rejects_schema_failure_and_retains_response() -> None:
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Unstructured concern."),
        context=context(),
        backend=backend("review-bad-schema", review_payload(category="invented")),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-bad-schema",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert result.proposal is None
    assert result.response.raw_response is not None
    assert result.response.raw_response_sha256
    assert result.rejection_reasons[0].startswith("output schema violation:")


def test_provider_output_validation_does_not_coerce_json_types() -> None:
    payload = review_payload(requires_new_evidence="false", requires_new_experiment="false")
    payload["confidence"] = "0.91"
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Unstructured concern."),
        context=context(),
        backend=backend("review-coerced-schema", payload),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-coerced-schema",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert result.proposal is None
    assert result.untrusted_proposal is None
    assert any("output schema violation" in reason for reason in result.rejection_reasons)


def test_review_node_rejects_unknown_claim_and_non_allowlisted_action() -> None:
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Broaden this claim.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend(
            "review-unauthorized",
            review_payload(target_claim_ids=["claim-invented"], proposed_action_type="STOP"),
        ),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-unauthorized",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert any("unknown claims" in reason for reason in result.rejection_reasons)
    assert any(
        "STOP" in reason and "not allowlisted" in reason for reason in result.rejection_reasons
    )
    assert result.proposal is None
    assert result.untrusted_proposal is not None
    assert result.untrusted_proposal.concerns[0].proposed_action_type == MetaAction.STOP


def test_response_tool_call_is_only_accepted_when_allowlisted() -> None:
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend(
            "review-tool",
            review_payload(),
            tool_calls=[ToolCallProposal(name="shell", arguments={"command": "run"})],
        ),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-tool",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert result.response.tool_calls[0].name == "shell"
    assert "tool 'shell' is not allowlisted" in result.rejection_reasons


@pytest.mark.parametrize(
    ("reply_updates", "policy_updates", "expected_reason"),
    [
        (
            {"usage": Usage(input_tokens=101, output_tokens=2, cost_usd=0.01)},
            {},
            "input token budget exceeded",
        ),
        (
            {"usage": Usage(input_tokens=2, output_tokens=101, cost_usd=0.01)},
            {},
            "output token budget exceeded",
        ),
        (
            {"usage": Usage(input_tokens=80, output_tokens=80, cost_usd=0.01)},
            {"max_total_tokens": 150},
            "total token budget exceeded",
        ),
        (
            {"usage": Usage(input_tokens=2, output_tokens=2, cost_usd=0.16)},
            {},
            "cumulative project API cost budget exceeded",
        ),
        ({"latency_ms": 1_001}, {}, "latency budget exceeded"),
    ],
)
def test_response_over_budget_is_rejected(
    reply_updates: dict[str, object],
    policy_updates: dict[str, object],
    expected_reason: str,
) -> None:
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend("review-budget", review_payload(), **reply_updates),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE], **policy_updates),
        request_id="review-budget",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert expected_reason in result.rejection_reasons


def test_missing_cost_telemetry_is_not_treated_as_zero() -> None:
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend(
            "review-no-cost",
            review_payload(),
            usage=Usage(input_tokens=2, output_tokens=2),
        ),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-no-cost",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert "API cost telemetry is required" in result.rejection_reasons


def test_cumulative_api_cost_is_checked_before_and_after_the_call() -> None:
    scripted = backend(
        "review-spent",
        review_payload(),
        usage=Usage(input_tokens=2, output_tokens=2, cost_usd=0.01),
    )
    with pytest.raises(NodePolicyViolationError, match="already exceeds"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Add a baseline."),
            context=context(cumulative_api_cost_usd=0.16),
            backend=scripted,
            policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
            request_id="review-spent",
        )
    assert scripted.calls == []

    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(cumulative_api_cost_usd=0.10),
        backend=backend(
            "review-cumulative",
            review_payload(),
            usage=Usage(input_tokens=2, output_tokens=2, cost_usd=0.06),
        ),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-cumulative",
    )
    assert result.status == NodeResultStatus.REJECTED
    assert "cumulative project API cost budget exceeded" in result.rejection_reasons

    exact_budget = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(cumulative_api_cost_usd=0.10),
        backend=backend(
            "review-exact-budget",
            review_payload(),
            usage=Usage(input_tokens=2, output_tokens=2, cost_usd=0.05),
        ),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-exact-budget",
    )
    assert exact_budget.status == NodeResultStatus.ACCEPTED


def test_backend_cannot_silently_switch_before_or_after_call() -> None:
    wrong_backend = ScriptedStructuredBackend(
        name="other-provider",
        model="scripted-v1",
        replies={"review-switch": ScriptedStructuredReply(output_payload=review_payload())},
    )
    with pytest.raises(NodePolicyViolationError, match="pinned policy"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Add a baseline."),
            context=context(),
            backend=wrong_backend,
            policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
            request_id="review-switch",
        )
    assert wrong_backend.calls == []

    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add a baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=context(),
        backend=backend("review-drift", review_payload(), response_model="silent-fallback"),
        policy=policy("review-semantic", actions=[MetaAction.ADD_BASELINE]),
        request_id="review-drift",
    )
    assert result.status == NodeResultStatus.REJECTED
    assert "response model differs from pinned model" in result.rejection_reasons


def interpretation_input() -> InterpretationThreatInput:
    return InterpretationThreatInput(
        result=ResultRecord(
            result_id="result-1",
            experiment_id="experiment-1",
            summary="Accuracy increased by five points.",
            metrics={"accuracy": 0.85},
        ),
        interpretation_context=InterpretationContext(
            claim_id="claim-1",
            evidence_type="held-out benchmark",
            expected="The method should improve accuracy.",
            observed="Accuracy increased by five points.",
            relation=ClaimRelation.SUPPORTS,
            reproducible=True,
            stability=0.8,
        ),
    )


def test_interpretation_node_proposes_threats_but_cannot_update_claims() -> None:
    payload = {
        "threats": [
            {
                "threat_id": "threat-1",
                "kind": "benchmark_artifact",
                "statement": "The gain may depend on one benchmark template.",
                "evidence_ids": ["evidence-1"],
                "confidence": 0.72,
            }
        ],
        "alternative_explanations": ["Template-specific lexical overlap"],
        "recommended_action_type": "REPRODUCE",
        "rationale": "Cross-template reproduction separates the explanations.",
        "confidence": 0.79,
    }
    result = InterpretationThreatNode().run(
        interpretation_input(),
        context=context(),
        backend=backend("interpretation-1", payload),
        policy=policy("interpretation-threat", actions=[MetaAction.REPRODUCE]),
        request_id="interpretation-1",
    )

    assert result.status == NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.threats[0].kind.value == "benchmark_artifact"
    assert "claim_assessment" not in result.proposal.model_dump()

    payload["claim_supported"] = True
    rejected = InterpretationThreatNode().run(
        interpretation_input(),
        context=context(),
        backend=backend("interpretation-overreach", payload),
        policy=policy("interpretation-threat", actions=[MetaAction.REPRODUCE]),
        request_id="interpretation-overreach",
    )
    assert rejected.status == NodeResultStatus.REJECTED
    assert rejected.proposal is None


def ambiguous_input(*, scores: dict[str, float] | None = None) -> AmbiguousActionInput:
    actions = [
        ResearchAction(
            action_id="probe",
            type=MetaAction.PROBE,
            description="Run one falsifying probe.",
        ),
        ResearchAction(
            action_id="reproduce",
            type=MetaAction.REPRODUCE,
            description="Reproduce the current result.",
        ),
    ]
    return AmbiguousActionInput(
        decision_context="The two feasible actions have nearly equal deterministic utility.",
        candidate_actions=actions,
        deterministic_scores=scores or {"probe": 0.51, "reproduce": 0.50},
    )


def ambiguous_context(value: AmbiguousActionInput) -> NodeContext:
    return context(candidate_actions=value.candidate_actions)


def test_ambiguous_action_node_ranks_only_existing_feasible_candidates() -> None:
    node_input = ambiguous_input()
    result = AmbiguousActionNode().run(
        node_input,
        context=ambiguous_context(node_input),
        backend=backend(
            "ambiguous-1",
            {
                "ranked_action_ids": ["reproduce", "probe"],
                "preferred_action_id": "reproduce",
                "rationale": "Reproduction resolves the higher-impact uncertainty.",
                "confidence": 0.61,
            },
        ),
        policy=policy(
            "ambiguous-action",
            actions=[MetaAction.PROBE, MetaAction.REPRODUCE],
        ),
        request_id="ambiguous-1",
    )

    assert result.status == NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.preferred_action_id == "reproduce"
    assert result.executable is False


def test_ambiguous_action_node_rejects_invented_or_disallowed_actions() -> None:
    node_input = ambiguous_input()
    result = AmbiguousActionNode().run(
        node_input,
        context=ambiguous_context(node_input),
        backend=backend(
            "ambiguous-invented",
            {
                "ranked_action_ids": ["invented", "probe"],
                "preferred_action_id": "invented",
                "rationale": "Invented action.",
                "confidence": 0.8,
            },
        ),
        policy=policy("ambiguous-action", actions=[MetaAction.PROBE]),
        request_id="ambiguous-invented",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert any(
        "ranked action ids must cover exactly" in reason for reason in result.rejection_reasons
    )
    assert any("REPRODUCE" in reason for reason in result.rejection_reasons)


def test_ambiguous_action_requires_an_exact_complete_context_candidate_set() -> None:
    node_input = ambiguous_input()
    scripted = backend("ambiguous-empty-context", {})
    with pytest.raises(NodePolicyViolationError, match="complete deterministic candidate"):
        AmbiguousActionNode().run(
            node_input,
            context=context(),
            backend=scripted,
            policy=policy(
                "ambiguous-action",
                actions=[MetaAction.PROBE, MetaAction.REPRODUCE],
            ),
            request_id="ambiguous-empty-context",
        )
    assert scripted.calls == []

    changed_actions = [item.model_copy(deep=True) for item in node_input.candidate_actions]
    changed_actions[0] = ResearchAction(
        action_id=changed_actions[0].action_id,
        type=MetaAction.PROBE,
        description="A different action body under the same identifier.",
        expected_cost={"api_cost_usd": 0.1},
    )
    scripted = backend("ambiguous-changed-context", {})
    with pytest.raises(NodePolicyViolationError, match="differs from context"):
        AmbiguousActionNode().run(
            node_input,
            context=context(candidate_actions=changed_actions),
            backend=scripted,
            policy=policy(
                "ambiguous-action",
                actions=[MetaAction.PROBE, MetaAction.REPRODUCE],
            ),
            request_id="ambiguous-changed-context",
        )
    assert scripted.calls == []


def test_ambiguous_action_node_is_not_called_when_deterministic_margin_is_clear() -> None:
    node_input = ambiguous_input(scores={"probe": 0.8, "reproduce": 0.2})
    scripted = backend("ambiguous-clear", {})

    with pytest.raises(NodeNotApplicableError, match="exceeds ambiguity threshold"):
        AmbiguousActionNode().run(
            node_input,
            context=ambiguous_context(node_input),
            backend=scripted,
            policy=policy(
                "ambiguous-action",
                actions=[MetaAction.PROBE, MetaAction.REPRODUCE],
            ),
            request_id="ambiguous-clear",
        )
    assert scripted.calls == []


def test_disabled_node_never_calls_backend() -> None:
    scripted = backend("review-disabled", review_payload())
    with pytest.raises(NodePolicyViolationError, match="disabled"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Add a baseline."),
            context=context(),
            backend=scripted,
            policy=policy(
                "review-semantic",
                actions=[MetaAction.ADD_BASELINE],
                enabled=False,
            ),
            request_id="review-disabled",
        )
    assert scripted.calls == []


def test_oversized_request_never_calls_backend() -> None:
    scripted = backend("review-large", review_payload())
    with pytest.raises(NodePolicyViolationError, match="max_request_bytes"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Add a baseline."),
            context=context(),
            backend=scripted,
            policy=policy(
                "review-semantic",
                actions=[MetaAction.ADD_BASELINE],
                max_request_bytes=1,
            ),
            request_id="review-large",
        )
    assert scripted.calls == []


def test_invocation_snapshots_inputs_policy_context_request_and_response() -> None:
    input_data = ReviewSemanticInput(
        review_text="Add a baseline.",
        permitted_evidence_types=["matched baseline"],
    )
    node_context = context()
    node_policy = policy("review-semantic", actions=[MetaAction.ADD_BASELINE])

    class MutatingBackend(ScriptedStructuredBackend):
        returned_response: object | None = None

        def complete(self, request):  # type: ignore[no-untyped-def]
            input_data.permitted_evidence_types.clear()
            node_context.claim_ids.clear()
            node_policy.allowed_action_types.clear()
            request.input_payload["input"]["review_text"] = "mutated by backend"
            self.returned_response = super().complete(request)
            return self.returned_response

    scripted = MutatingBackend(
        name="scripted",
        model="scripted-v1",
        replies={"review-boundary": ScriptedStructuredReply(output_payload=review_payload())},
    )
    result = ReviewSemanticNode().run(
        input_data,
        context=node_context,
        backend=scripted,
        policy=node_policy,
        request_id="review-boundary",
    )

    assert result.status == NodeResultStatus.REJECTED
    assert "backend mutated structured request after preflight" in result.rejection_reasons
    assert result.request.input_payload["input"]["review_text"] == "Add a baseline."
    assert result.request.input_payload["context"]["claim_ids"] == ["claim-1"]
    assert result.untrusted_proposal is not None

    assert scripted.returned_response is not None
    scripted.returned_response.output_payload["summary"] = "mutated after return"
    assert result.response.output_payload["summary"] == "One substantive evidence concern."

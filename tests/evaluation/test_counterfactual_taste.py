from __future__ import annotations

from scitaste.backends.base import Usage
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionGuidanceProvider,
    CounterfactualActionSetAdequacy,
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import (
    InteractiveAgentDecision,
    InteractiveAgentProposal,
    InteractiveExperimentRequest,
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
    InteractiveObjectiveScore,
    InteractiveResearchLimits,
    InteractiveResearchLoop,
    InteractiveResearchPrefix,
)


class _StatelessToolbox:
    task_id = "counterfactual-task"
    task_prompt = "Infer the hidden relationship."
    task_sha256 = "1" * 64
    environment_sha256 = "2" * 64
    fingerprint = "3" * 64

    def run_experiments(self, requests):
        return {
            "results": [item.parameters for item in requests],
            "environment_sha256": self.environment_sha256,
        }

    def run_code(self, code):
        raise AssertionError(code)

    def score(self, submission):
        value = 1.0 if submission == "right" else 0.0
        return InteractiveObjectiveScore.create(
            primary_metric="accuracy",
            primary_value=value,
            metric_direction="higher",
            metrics={"accuracy": value, "error": 1.0 - value},
            scorer_provider="scripted",
            scorer_model="exact",
            scorer_sha256="4" * 64,
            usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.0),
            latency_ms=1.0,
        )


class _TurnAgent:
    fingerprint = "5" * 64

    def __init__(self, proposals):
        self.proposals = proposals

    def decide(self, context, guidance):
        del guidance
        proposal = self.proposals[context.turn]
        return InteractiveAgentDecision.create(
            proposal=proposal,
            provider="scripted",
            model="scripted-agent",
            request_sha256=f"{context.turn:064x}",
            response_sha256=f"{context.turn + 10:064x}",
            usage=Usage(input_tokens=3, output_tokens=2, cost_usd=0.0),
            latency_ms=1.0,
        )


class _FailingAgent:
    fingerprint = _TurnAgent.fingerprint

    def decide(self, context, guidance):
        del context, guidance
        raise ValueError("invalid structured response")


class _CommonGuidance:
    def guide(self, context):
        is_stop = context.turn > 1
        return InteractiveGuidanceEnvelope.create(
            guidance=InteractiveGuidance(
                action_id=f"common-{context.turn}",
                action_type="STOP" if is_stop else "PROBE",
                instruction=(
                    "Submit the supported hypothesis."
                    if is_stop
                    else "Probe one informative point."
                ),
                decision_sha256=f"{context.turn + 20:064x}",
                allowed_agent_actions=(("submit_hypothesis",) if is_stop else ("run_experiments",)),
            ),
            audit={"rollout": "common", "turn": context.turn},
        )


def _experiment(x: int) -> InteractiveAgentProposal:
    return InteractiveAgentProposal(
        action="run_experiments",
        experiments=(InteractiveExperimentRequest(parameters={"x": x}),),
        rationale="Acquire a controlled observation.",
    )


def _submission(value: str) -> InteractiveAgentProposal:
    return InteractiveAgentProposal(
        action="submit_hypothesis",
        submission=value,
        rationale="Submit the best supported relationship.",
        evidence_status="candidate-supported",
        evidence_confidence=0.9,
        next_experiment_value=0.1,
    )


def test_prefix_matched_branches_produce_objective_action_preference() -> None:
    limits = InteractiveResearchLimits(
        max_turns=3,
        max_experiments=3,
        max_experiments_per_turn=1,
        max_total_tokens=100,
        max_api_cost_usd=1.0,
    )
    source = InteractiveResearchLoop(
        _StatelessToolbox(),
        _TurnAgent({1: _experiment(1), 2: _submission("right")}),
        _CommonGuidance(),
        limits,
    ).run(
        project_id="counterfactual-project",
        run_id="source-run",
        condition_id="common-rollout",
    )
    prefix = InteractiveResearchPrefix.from_receipt(
        source,
        turn_count=1,
        task_sha256=_StatelessToolbox.task_sha256,
        toolbox_sha256=_StatelessToolbox.fingerprint,
        resource_envelope_sha256=limits.fingerprint,
        research_agent_sha256=_TurnAgent.fingerprint,
    )

    receipts = []
    interventions = []
    for action, submission in (
        (CounterfactualResearchAction.PIVOT, "wrong"),
        (CounterfactualResearchAction.REFINE, "right"),
    ):
        provider = CounterfactualActionGuidanceProvider(
            prefix=prefix,
            forced_action=action,
            rollout_provider=_CommonGuidance(),
            rollout_condition_id="common-rollout",
            rollout_policy_sha256="6" * 64,
            study_id="counterfactual-study",
        )
        branch_agent = (
            _FailingAgent()
            if action is CounterfactualResearchAction.PIVOT
            else _TurnAgent({2: _experiment(2), 3: _submission(submission)})
        )
        receipt = InteractiveResearchLoop(
            _StatelessToolbox(),
            branch_agent,
            provider,
            limits,
        ).run(
            project_id="counterfactual-project",
            run_id=f"branch-{action.value.casefold()}",
            condition_id=f"forced-{action.value.casefold()}",
            prefix=prefix,
        )
        assert receipt.prefix_sha256 == prefix.prefix_sha256
        assert receipt.turns[0] == source.turns[0]
        if action is CounterfactualResearchAction.PIVOT:
            assert receipt.status == "agent_failure"
            assert len(receipt.turns) == prefix.turn_count
        else:
            assert receipt.status == "completed"
            intervention_audit = receipt.turns[1].guidance.audit[
                "counterfactual_intervention"
            ]
            assert intervention_audit["forced_action"] == action.value
            assert (
                intervention_audit["action_semantics_profile"]
                == "hidden-law-discovery-v1"
            )
            assert len(intervention_audit["action_semantics_sha256"]) == 64
            if action is CounterfactualResearchAction.REFINE:
                instruction = receipt.turns[1].guidance.guidance.instruction
                assert "functional form" in instruction
                assert "exponents" in instruction
        receipts.append(receipt)
        interventions.append(provider.intervention)

    result = CounterfactualActionSetResult.from_receipts(
        study_id="counterfactual-study",
        prefix=prefix,
        receipts=tuple(receipts),
        interventions=tuple(interventions),
        primary_metric="accuracy",
        metric_direction="higher",
        failure_value=0.0,
    )

    assert result.preferred_actions == (CounterfactualResearchAction.REFINE,)
    assert result.objective_spread == 1.0
    assert sum(item.objective_observed for item in result.outcomes) == 1

    adequacy = CounterfactualActionSetAdequacy.from_result(result)
    assert adequacy.supported_scope == "infrastructure-only"
    assert not adequacy.action_space_complete
    assert adequacy.objective_observation_rate == 0.5
    assert not adequacy.state_conditional_policy_supported
    assert not adequacy.generalization_supported
    assert not adequacy.headline_eligible
    assert "single-observed-research-prefix" in adequacy.blockers
    assert "incomplete-primary-metric-observation" in adequacy.blockers

    secondary = CounterfactualActionSetResult.from_receipts(
        study_id="counterfactual-study",
        prefix=prefix,
        receipts=tuple(receipts),
        interventions=tuple(interventions),
        primary_metric="error",
        metric_direction="lower",
        failure_value=2.0,
    )
    assert secondary.preferred_actions == (CounterfactualResearchAction.REFINE,)

    bounded = CounterfactualActionSetResult.from_receipts(
        study_id="counterfactual-study",
        prefix=prefix,
        receipts=tuple(receipts),
        interventions=tuple(interventions),
        primary_metric="exp-neg-error",
        source_metric="error",
        metric_transform="exp-negative",
        metric_direction="higher",
        failure_value=0.0,
    )
    assert bounded.preferred_actions == (CounterfactualResearchAction.REFINE,)
    assert bounded.outcomes[0].objective_value == 0.0
    assert bounded.outcomes[1].objective_value == 1.0

from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np
import pytest

import scitaste.evaluation.interactive_development as interactive_development_module
from scitaste.backends.base import Usage
from scitaste.evaluation.e2_prelaunch import load_e2_prelaunch_manifest
from scitaste.evaluation.interactive_research import (
    InteractiveAgentDecision,
    InteractiveAgentProposal,
    InteractiveExperimentRequest,
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
    InteractiveObjectiveScore,
    InteractiveResearchContext,
    InteractiveResearchLimits,
    InteractiveResearchLoop,
    guidance_action_complied,
)
from scitaste.evaluation.newtonbench_runtime import NewtonBenchTask, NewtonBenchToolbox
from scitaste.evaluation.research_workload import (
    ResearchWorkloadContract,
    ResearchWorkloadParadigm,
)


class _NoncompliantAgent:
    fingerprint = "a" * 64

    def decide(self, context, guidance):
        del context, guidance
        return InteractiveAgentDecision.create(
            proposal=InteractiveAgentProposal(
                action="submit_hypothesis",
                submission="unsupported",
                rationale="Submit despite an analysis instruction.",
            ),
            provider="scripted",
            model="scripted-agent",
            request_sha256="b" * 64,
            response_sha256="c" * 64,
            usage=Usage(input_tokens=3, output_tokens=2, cost_usd=0.0),
            latency_ms=1.0,
        )


class _AnalyzeGuidance:
    def guide(self, context):
        del context
        return InteractiveGuidanceEnvelope.create(
            guidance=InteractiveGuidance(
                action_id="analyze-now",
                action_type="ANALYZE",
                instruction="Analyze the retained evidence before acting.",
                decision_sha256="d" * 64,
            ),
            audit={"protocol_sha256": "e" * 64},
        )


class _NoCallToolbox:
    task_id = "task-one"
    task_prompt = "Infer the hidden relationship."
    task_sha256 = "f" * 64
    environment_sha256 = "1" * 64
    fingerprint = "2" * 64

    def __init__(self):
        self.score_calls = 0

    def run_experiments(self, requests):
        raise AssertionError(requests)

    def run_code(self, code):
        raise AssertionError(code)

    def score(self, submission):
        self.score_calls += 1
        raise AssertionError(submission)


def test_locked_taste_action_is_an_execution_constraint() -> None:
    toolbox = _NoCallToolbox()
    limits = InteractiveResearchLimits(
        max_turns=2,
        max_experiments=2,
        max_experiments_per_turn=1,
        max_total_tokens=100,
        max_api_cost_usd=1.0,
        require_cost_telemetry=True,
        enforce_guidance_compliance=True,
    )

    receipt = InteractiveResearchLoop(
        toolbox,
        _NoncompliantAgent(),
        _AnalyzeGuidance(),
        limits,
    ).run(
        project_id="project-one",
        run_id="run-one",
        condition_id="development-foundation",
    )

    assert receipt.status == "agent_noncompliance"
    assert receipt.environment_sha256 == toolbox.environment_sha256
    assert len(receipt.turns) == 1
    assert receipt.turns[0].decision.proposal.action == "submit_hypothesis"
    assert toolbox.score_calls == 0


def test_guidance_mapping_fails_closed() -> None:
    assert guidance_action_complied("STOP", "submit_hypothesis")
    assert guidance_action_complied("ANALYZE", "run_code")
    assert guidance_action_complied("PROBE", "run_experiments")
    assert not guidance_action_complied("ANALYZE", "submit_hypothesis")
    assert not guidance_action_complied("UNKNOWN", "run_experiments")


class _EvidenceBackedStopAgent:
    fingerprint = "3" * 64

    def decide(self, context, guidance):
        del context, guidance
        return InteractiveAgentDecision.create(
            proposal=InteractiveAgentProposal(
                action="submit_hypothesis",
                submission="y = x",
                rationale="Six controlled observations support the same law.",
                evidence_status="candidate-supported",
                evidence_confidence=0.97,
                next_experiment_value=0.03,
            ),
            provider="scripted",
            model="scripted-agent",
            request_sha256="4" * 64,
            response_sha256="5" * 64,
            usage=Usage(input_tokens=3, output_tokens=2, cost_usd=0.0),
            latency_ms=1.0,
        )


class _StopAdjudicatingGuidance(_AnalyzeGuidance):
    def adjudicate_submission(self, context, initial_guidance, decision):
        del context
        assert initial_guidance.guidance.action_type == "ANALYZE"
        assert decision.proposal.evidence_status == "candidate-supported"
        return InteractiveGuidanceEnvelope.create(
            guidance=InteractiveGuidance(
                action_id="approved-stop",
                action_type="STOP",
                instruction="Submit the supported hypothesis.",
                decision_sha256="6" * 64,
            ),
            audit={
                "initial_guidance_sha256": initial_guidance.audit_sha256,
                "agent_decision_sha256": decision.decision_sha256,
            },
        )


class _ScoringToolbox(_NoCallToolbox):
    def score(self, submission):
        self.score_calls += 1
        assert submission == "y = x"
        return InteractiveObjectiveScore.create(
            primary_metric="symbolic_accuracy",
            primary_value=1.0,
            metric_direction="higher",
            metrics={"symbolic_accuracy": 1.0},
            scorer_provider="scripted",
            scorer_model="exact-scorer",
            scorer_sha256="7" * 64,
            usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.0),
            latency_ms=1.0,
        )


def test_submission_is_scored_only_after_controller_adjudicates_stop() -> None:
    toolbox = _ScoringToolbox()
    receipt = InteractiveResearchLoop(
        toolbox,
        _EvidenceBackedStopAgent(),
        _StopAdjudicatingGuidance(),
        InteractiveResearchLimits(
            max_turns=2,
            max_experiments=2,
            max_experiments_per_turn=1,
            max_total_tokens=100,
            max_api_cost_usd=1.0,
        ),
    ).run(
        project_id="project-one",
        run_id="run-stop-adjudication",
        condition_id="development-foundation",
    )

    assert receipt.status == "completed"
    assert receipt.turns[0].guidance.guidance.action_type == "STOP"
    assert receipt.objective_score is not None
    assert receipt.objective_score.primary_value == 1.0
    assert toolbox.score_calls == 1


def test_terminal_scientific_credit_preserves_success_and_failure_sign() -> None:
    success = SimpleNamespace(
        status="completed",
        objective_score=SimpleNamespace(primary_value=1.0),
    )
    failure = SimpleNamespace(
        status="completed",
        objective_score=SimpleNamespace(primary_value=0.0),
    )

    assert interactive_development_module._scientific_credit_orientation(
        success,
        is_submission=True,
    ) == (
        interactive_development_module.TasteOutcomePolarity.SUPPORTS,
        interactive_development_module.TasteCreditDirection.BENEFICIAL,
    )
    assert interactive_development_module._scientific_credit_orientation(
        failure,
        is_submission=True,
    ) == (
        interactive_development_module.TasteOutcomePolarity.CHALLENGES,
        interactive_development_module.TasteCreditDirection.HARMFUL,
    )
    assert interactive_development_module._scientific_credit_orientation(
        failure,
        is_submission=False,
    ) == (
        interactive_development_module.TasteOutcomePolarity.MIXED,
        interactive_development_module.TasteCreditDirection.BENEFICIAL,
    )


def _stop_gate_context() -> InteractiveResearchContext:
    history = tuple(
        {
            "turn": turn,
            "high_level_action": phase,
            "model_action": {
                "action": "run_experiments",
                "experiments": [
                    {"parameters": {"x": 2 * turn - 1}},
                    {"parameters": {"x": 2 * turn}},
                ],
                "code": None,
                "submission": None,
                "rationale": "Run a controlled test.",
            },
            "observation": {"results": [2 * turn - 1, 2 * turn]},
        }
        for turn, phase in enumerate(("PROBE", "ANALYZE", "EXPERIMENT"), start=1)
    )
    return InteractiveResearchContext(
        project_id="project-one",
        run_id="run-one",
        condition_id="development-foundation",
        task_id="task-one",
        task_sha256="8" * 64,
        environment_sha256="9" * 64,
        toolbox_sha256="a" * 64,
        resource_envelope_sha256="b" * 64,
        research_agent_sha256="c" * 64,
        task_prompt="Infer the hidden relationship.",
        turn=4,
        remaining_turns=5,
        remaining_experiments=18,
        max_experiments_per_turn=6,
        remaining_code_calls=0,
        history=history,
    )


def test_development_stop_gate_requires_belief_and_observed_coverage() -> None:
    supported = InteractiveAgentProposal(
        action="submit_hypothesis",
        submission="y = x",
        rationale="The controlled predictions all matched.",
        evidence_status="candidate-supported",
        evidence_confidence=0.95,
        next_experiment_value=0.05,
    )
    gate = interactive_development_module._development_submission_stop_gate(
        _stop_gate_context(),
        supported,
    )

    assert gate["approved"] is True
    assert gate["experiment_count"] == 6
    conflicted = supported.model_copy(update={"evidence_status": "candidate-conflicted"})
    rejected = interactive_development_module._development_submission_stop_gate(
        _stop_gate_context(),
        conflicted,
    )
    assert rejected["approved"] is False
    assert rejected["checks"]["structured_support"] is False


def test_development_stop_gate_does_not_force_redundant_evidence_turns() -> None:
    context = _stop_gate_context().model_copy(
        update={
            "turn": 3,
            "remaining_turns": 6,
            "remaining_experiments": 15,
            "history": _stop_gate_context().history[:2],
        }
    )
    proposal = InteractiveAgentProposal(
        action="submit_hypothesis",
        submission="y = x",
        rationale="Nine noiseless controlled observations exactly support one law.",
        evidence_status="candidate-supported",
        evidence_confidence=0.95,
        next_experiment_value=0.05,
    )

    gate = interactive_development_module._development_submission_stop_gate(context, proposal)

    assert gate["approved"] is False  # the synthetic two-turn fixture has only four experiments

    nine_experiment_history = tuple(
        {
            **item,
            "model_action": {
                **item["model_action"],
                "experiments": [
                    {"parameters": {"x": 10 * item["turn"] + offset}}
                    for offset in range(1, count + 1)
                ],
            },
            "observation": {"results": list(range(count))},
        }
        for item, count in zip(context.history, (6, 3), strict=True)
    )
    covered = context.model_copy(update={"history": nine_experiment_history})

    approved = interactive_development_module._development_submission_stop_gate(
        covered,
        proposal,
    )
    assert approved["approved"] is True
    assert approved["experiment_count"] == 9

    single_turn = covered.model_copy(
        update={
            "turn": 2,
            "remaining_turns": 7,
            "history": covered.history[:1],
        }
    )
    six_experiment_history = (
        {
            **single_turn.history[0],
            "model_action": {
                **single_turn.history[0]["model_action"],
                "experiments": [
                    {"parameters": {"mass": mass, "distance": distance}}
                    for mass, distance in ((1, 1), (2, 1), (3, 1), (1, 2), (1, 3), (4, 4))
                ],
            },
            "observation": {"results": [1, 2, 3, 0.5, 0.3, 1]},
        },
    )
    single_turn = single_turn.model_copy(update={"history": six_experiment_history})
    one_turn_gate = interactive_development_module._development_submission_stop_gate(
        single_turn,
        proposal,
    )
    assert one_turn_gate["approved"] is True
    assert one_turn_gate["varied_parameter_count"] == 2


class _RandomNewtonModule:
    @staticmethod
    def run_experiment_for_module(**parameters):
        del parameters
        return [random.random(), float(np.random.random())]


def _random_toolbox(environment_seed: int) -> NewtonBenchToolbox:
    toolbox = object.__new__(NewtonBenchToolbox)
    toolbox.task = NewtonBenchTask(
        module="m0_gravity",
        difficulty="easy",
        system="vanilla_equation",
        law_version="v0",
        noise_level=0.1,
        environment_seed=environment_seed,
        score_seed=7,
    )
    toolbox.module = _RandomNewtonModule()
    toolbox.repository_commit = "3" * 40
    toolbox._module_sha256 = "4" * 64
    toolbox._evaluation_sha256 = "5" * 64
    toolbox._task_prompt = "A hidden deterministic test fixture."
    toolbox._experiment_index = 0
    toolbox.symbolic_judge = SimpleNamespace(fingerprint="6" * 64)
    toolbox.code_runner = None
    return toolbox


def test_newtonbench_measurements_are_seeded_replayable_and_rng_isolated() -> None:
    request = (InteractiveExperimentRequest(parameters={"mass1": 1, "mass2": 2, "distance": 3}),)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    try:
        random.seed(1234)
        np.random.seed(1234)
        expected_python = random.random()
        expected_numpy = float(np.random.random())

        random.seed(1234)
        np.random.seed(1234)
        first = _random_toolbox(17).run_experiments(request)
        observed_python = random.random()
        observed_numpy = float(np.random.random())

        second = _random_toolbox(17).run_experiments(request)
        different = _random_toolbox(18).run_experiments(request)
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)

    assert first == second
    assert first != different
    assert observed_python == expected_python
    assert observed_numpy == expected_numpy
    assert first["environment_sha256"] == _random_toolbox(17).environment_sha256
    assert first["environment_sha256"] != _random_toolbox(18).environment_sha256


def test_workload_training_is_separate_from_scitaste_taste_adaptation() -> None:
    training_free = ResearchWorkloadContract.create(
        contract_id="newtonbench-t0",
        task_id="newtonbench-gravity",
        paradigm=ResearchWorkloadParadigm.TRAINING_FREE,
        task_model_weight_updates=False,
        candidate_checkpoint_required=False,
    )
    training_based = ResearchWorkloadContract.create(
        contract_id="mlrc-perception-t1",
        task_id="perception-temporal-action-loc",
        paradigm=ResearchWorkloadParadigm.TRAINING_BASED,
        task_model_id="loc-point-transformer",
        task_model_weight_updates=True,
        task_model_initialization_sha256="7" * 64,
        training_recipe_sha256="8" * 64,
        candidate_checkpoint_required=True,
    )

    assert training_free.scitaste_research_backbone_weight_updates is False
    assert training_based.scitaste_research_backbone_weight_updates is False
    assert training_free.outcome_updated_taste_state_allowed is True
    assert training_based.outcome_updated_taste_state_allowed is True
    with pytest.raises(ValueError, match="training-free workloads cannot update"):
        ResearchWorkloadContract.create(
            contract_id="invalid-t0",
            task_id="invalid-task",
            paradigm=ResearchWorkloadParadigm.TRAINING_FREE,
            task_model_weight_updates=True,
            candidate_checkpoint_required=False,
        )


def test_mlrc_prelaunch_projects_the_same_unified_t1_contract() -> None:
    manifest, _ = load_e2_prelaunch_manifest(
        "configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v2.yaml"
    )
    contract = manifest.workload.research_workload_contract

    assert contract.paradigm is ResearchWorkloadParadigm.TRAINING_BASED
    assert contract.task_model_weight_updates is True
    assert contract.task_model_id == "loc-point-transformer"
    assert contract.candidate_checkpoint_required is True
    assert contract.scitaste_research_backbone_weight_updates is False


def _sampling_record(
    turn: int,
    *,
    action_type: str,
    model_action: str,
    observation: object | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        turn=turn,
        guidance=SimpleNamespace(guidance=SimpleNamespace(action_type=action_type)),
        decision=SimpleNamespace(proposal=SimpleNamespace(action=model_action)),
        observation=observation,
    )


def test_activation_sampling_selects_one_post_observation_nonterminal_decision() -> None:
    protocol = SimpleNamespace(
        episode_sampling_rule="earliest-executed-nonterminal-after-observation",
        maximum_episode_candidates=1,
    )
    receipt = SimpleNamespace(
        turns=(
            _sampling_record(
                1,
                action_type="PROBE",
                model_action="run_experiments",
                observation={"results": [1]},
            ),
            _sampling_record(
                2,
                action_type="ANALYZE",
                model_action="run_code",
                observation={"stdout": "supported"},
            ),
            _sampling_record(
                3,
                action_type="STOP",
                model_action="submit_hypothesis",
                observation=None,
            ),
        )
    )

    selected = interactive_development_module._selected_development_lock_paths(
        protocol,
        receipt,
        ("turn-1.json", "turn-2.json", "turn-3.json"),
    )

    assert selected == ("turn-2.json",)


def test_activation_sampling_does_not_substitute_terminal_or_unexecuted_turn() -> None:
    protocol = SimpleNamespace(
        episode_sampling_rule="earliest-executed-nonterminal-after-observation",
        maximum_episode_candidates=1,
    )
    receipt = SimpleNamespace(
        turns=(
            _sampling_record(
                1,
                action_type="PROBE",
                model_action="run_experiments",
                observation={"results": [1]},
            ),
            _sampling_record(
                2,
                action_type="STOP",
                model_action="submit_hypothesis",
                observation=None,
            ),
        )
    )

    selected = interactive_development_module._selected_development_lock_paths(
        protocol,
        receipt,
        ("turn-1.json", "turn-2.json"),
    )

    assert selected == ()

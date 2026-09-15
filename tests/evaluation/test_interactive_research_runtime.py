from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np
import pytest

from scitaste.backends.base import Usage
from scitaste.evaluation.e2_prelaunch import load_e2_prelaunch_manifest
from scitaste.evaluation.interactive_research import (
    InteractiveAgentDecision,
    InteractiveAgentProposal,
    InteractiveExperimentRequest,
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
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
    request = (
        InteractiveExperimentRequest(parameters={"mass1": 1, "mass2": 2, "distance": 3}),
    )
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

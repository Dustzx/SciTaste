"""Offline end-to-end demonstration of nonlinear SciTaste research control."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import (
    ResearchIdea,
    ResearchObservation,
    ResearchProblem,
    ResearchState,
    ResourceBudget,
    WorkingHypothesis,
)
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController


def run_nonlinear_demo(
    *,
    output_dir: str | Path,
    seed: int = 7,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run hypothesis → contradictory probe → pivot → new idea → pilot selection."""

    settings = config or {}
    root = Path(output_dir)
    log_path = root / "decisions.jsonl"
    if log_path.exists():
        raise FileExistsError(f"refusing to append to existing demo log: {log_path}")

    budget_values = settings.get("budget", {})
    state = ResearchState(
        project_id=settings.get("project_id", "nonlinear-demo"),
        research_direction=settings.get(
            "research_direction", "Diagnose brittle scientific-agent decisions"
        ),
        target_domain=settings.get("target_domain", "autonomous-research"),
        target_venue=settings.get("target_venue"),
        resource_budget=ResourceBudget.model_validate(budget_values),
    )
    controller = TasteController(seed=seed)
    executor = MockExecutor(seed=seed)
    store = StateStore(root)
    logger = DecisionLogger(log_path)
    store.save(state)

    steps: list[list[ResearchAction]] = [
        [
            ResearchAction(
                action_id="demo-form-hypothesis",
                type=MetaAction.FORM_WORKING_HYPOTHESIS,
                description="Form a falsifiable hypothesis about aggregate-score brittleness",
                expected_cost={"wall_time_hours": 0.02},
                expected_value={"information_gain": 0.55, "problem_validity": 0.45},
            )
        ],
        [
            ResearchAction(
                action_id="demo-probe",
                type=MetaAction.PROBE,
                description="Run a cheap factor-stratified diagnostic probe",
                parameters={
                    "observation": (
                        "Contrary to the hypothesis, model size does not explain failures; "
                        "decision instability concentrates at evidence-conflict boundaries."
                    )
                },
                expected_cost={"experiments": 1.0, "gpu_hours": 0.1},
                expected_value={"information_gain": 0.95, "problem_validity": 0.9},
            ),
            ResearchAction(
                action_id="demo-premature-idea",
                type=MetaAction.IDEATE,
                description="Commit immediately to a larger-model intervention",
                expected_cost={"experiments": 2.0, "gpu_hours": 0.7},
                expected_value={"information_gain": 0.2, "problem_validity": 0.2},
            ),
        ],
        [
            ResearchAction(
                action_id="demo-pivot",
                type=MetaAction.PIVOT,
                description="Pivot from model scale to evidence-conflict sensitivity",
                expected_cost={"wall_time_hours": 0.02},
                expected_value={"information_gain": 0.9, "scientific_importance": 0.75},
            ),
            ResearchAction(
                action_id="demo-refine-old",
                type=MetaAction.REFINE,
                description="Continue refining the contradicted model-scale explanation",
                expected_cost={"experiments": 1.0, "gpu_hours": 0.4},
                expected_value={"information_gain": 0.15, "scientific_importance": 0.2},
            ),
        ],
        [
            ResearchAction(
                action_id="demo-ideate",
                type=MetaAction.IDEATE,
                description="Generate mechanisms for evidence-conflict-aware control",
                expected_cost={"wall_time_hours": 0.05},
                expected_value={"novelty": 0.8, "problem_validity": 0.9, "feasibility": 0.8},
            )
        ],
        [
            ResearchAction(
                action_id="demo-select-pilot",
                type=MetaAction.SELECT_IDEA,
                description="Select a bounded evidence-conflict-aware controller pilot",
                expected_cost={"experiments": 1.0, "gpu_hours": 0.2},
                expected_value={
                    "expected_empirical_signal": 0.8,
                    "evidence_tractability": 0.9,
                    "feasibility": 0.9,
                },
            )
        ],
    ]

    for index, candidates in enumerate(steps):
        decision = controller.decide(state=state, candidate_actions=candidates)
        result = executor.execute(state, decision.selected_action)
        decision.executor_result_id = result.result_id
        decision.actual_outcome = result.model_dump(mode="json")
        logger.append(decision)
        state = apply_transition(state, decision)
        _apply_demo_domain_update(state, index, result.observations)
        store.save(state)

    summary = {
        "project_id": state.project_id,
        "final_stage": state.current_stage.value,
        "revision": state.revision,
        "selected_actions": [
            decision.selected_action.type.value for decision in state.decision_history
        ],
        "transitions": [
            {
                "from": item.from_stage.value,
                "action": item.action_type.value,
                "to": item.to_stage.value,
            }
            for item in state.transition_history
        ],
        "decision_log": str(log_path),
        "latest_state": str(store.latest_path),
    }
    (root / "demo_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def _apply_demo_domain_update(
    state: ResearchState,
    step_index: int,
    observations: list[str],
) -> None:
    if step_index == 0:
        state.working_hypotheses.append(
            WorkingHypothesis(
                hypothesis_id="demo-hypothesis-scale",
                statement="Failures are primarily caused by insufficient model scale.",
                falsifiable_predictions=["Larger models fail substantially less in every stratum."],
                proposed_probe_types=["factor sweep", "failure stratification"],
                confidence=0.4,
            )
        )
        state.active_working_hypothesis_id = "demo-hypothesis-scale"
    elif step_index == 1:
        state.observations.append(
            ResearchObservation(
                observation_id="demo-observation-conflict",
                statement=observations[0],
                reproducible=True,
                stability=0.85,
                expected=False,
            )
        )
        state.working_hypotheses[0].status = "contradicted"
        state.working_hypotheses[0].confidence = 0.1
    elif step_index == 2:
        state.problem_candidates.append(
            ResearchProblem(
                problem_id="demo-problem-conflict",
                observed_phenomenon=(
                    "Research decisions destabilize at evidence-conflict boundaries."
                ),
                boundary_conditions=["conflicting evidence", "similar aggregate utility"],
                explanation_gap="Aggregate scoring hides conflict structure.",
                importance="Unstable choices waste experiments and make pivots unreliable.",
                reproducible=True,
                supporting_evidence_ids=["demo-observation-conflict"],
            )
        )
        state.active_problem_id = "demo-problem-conflict"
    elif step_index == 3:
        state.candidate_ideas.append(
            ResearchIdea(
                idea_id="demo-idea-conflict-controller",
                problem="Decision instability under conflicting evidence",
                observation_evidence="Stable failure concentration at conflict boundaries",
                hypothesis="Explicit conflict features improve action stability and pivot quality.",
                proposed_mechanism="Conflict-aware action ranking with targeted re-probing",
                expected_validation=["stability", "correct pivot rate", "research yield"],
                expected_cost={"experiments": 1.0, "gpu_hours": 0.2},
                main_risk="Synthetic conflicts may not transfer to real research trajectories.",
            )
        )
    elif step_index == 4:
        state.active_idea_id = "demo-idea-conflict-controller"

"""ResearchState-integrated, offline Evidence Loop workflow."""

from __future__ import annotations

import json
import math
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.discovery.evidence_to_idea import (
    ContradictoryPilotEvidence,
    EvidenceToIdeaEngine,
)
from scitaste.discovery.ideas import IdeaSeed
from scitaste.evidence.claim_graph import ClaimGraph
from scitaste.evidence.claim_graph import ScientificClaim as GraphClaim
from scitaste.evidence.interpretation import (
    ClaimRelation,
    InterpretationContext,
    InterpretationCritic,
    ResultRecord,
)
from scitaste.evidence.loop import EvidenceLoop
from scitaste.executor.base import ExecutionResult, ResearchExecutor, require_execution_success
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import (
    EvidenceItem as StateEvidenceItem,
)
from scitaste.state.research_state import (
    ExperimentPlan,
    ExperimentRecord,
    ResearchObservation,
    ResearchState,
    ResourceBudget,
)
from scitaste.state.research_state import (
    ScientificClaim as StateClaim,
)
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController


class PivotSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation_gap: str = Field(min_length=1)
    importance: str = Field(min_length=1)
    boundary_conditions: list[str] = Field(default_factory=list)
    idea_seed: IdeaSeed


class EvidenceWorkflowScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    research_direction: str
    target_domain: str
    target_venue: str | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    claim: GraphClaim
    result: ResultRecord
    interpretation: InterpretationContext
    pivot: PivotSeed | None = None

    @model_validator(mode="after")
    def references_match(self) -> EvidenceWorkflowScenario:
        if self.interpretation.claim_id != self.claim.claim_id:
            raise ValueError("interpretation claim_id must match the configured claim")
        return self


class EvidenceWorkflow:
    def __init__(
        self,
        *,
        controller: TasteController | None = None,
        executor: ResearchExecutor | None = None,
        seed: int = 0,
    ) -> None:
        self.controller = controller or TasteController(seed=seed)
        self.executor = executor or MockExecutor(seed=seed)

    def run(
        self,
        scenario: EvidenceWorkflowScenario,
        *,
        output_dir: str | Path,
        state_path: str | Path | None = None,
    ) -> dict[str, object]:
        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise FileExistsError(f"refusing to append to existing evidence log: {logger.path}")
        store = StateStore(root)
        state = (
            ResearchState.model_validate_json(Path(state_path).read_text(encoding="utf-8"))
            if state_path
            else ResearchState(
                project_id=scenario.project_id,
                research_direction=scenario.research_direction,
                target_domain=scenario.target_domain,
                target_venue=scenario.target_venue,
                resource_budget=scenario.resource_budget,
                current_stage="EVIDENCE",
            )
        )
        if state.current_stage.value not in {"PILOT", "EVIDENCE"}:
            raise ValueError("evidence workflow requires a PILOT or EVIDENCE state")
        store.save(state)

        def act(action: ResearchAction) -> tuple[ResearchDecision, ExecutionResult]:
            nonlocal state
            decision = self.controller.decide(state=state, candidate_actions=[action])
            result = self.executor.execute(state, decision.selected_action)
            decision.executor_result_id = result.result_id
            decision.actual_outcome = result.model_dump(mode="json")
            logger.append(decision)
            require_execution_success(result)
            state = apply_transition(state, decision)
            state = record_resource_usage(state, result.cost)
            return decision, result

        resumed_from_pilot = state.current_stage.value == "PILOT"
        if resumed_from_pilot:
            act(
                ResearchAction(
                    action_id="evidence-run-pilot",
                    type=MetaAction.PILOT,
                    description="Execute the selected idea's bounded pilot",
                    parameters={"observation": scenario.interpretation.observed},
                    expected_value={"information_gain": 0.9, "claim_relevance": 0.9},
                )
            )
            store.save(state)
            act(
                ResearchAction(
                    action_id="evidence-analyze-pilot",
                    type=MetaAction.ANALYZE,
                    description="Separate the pilot result from observation and interpretation",
                    expected_value={"information_gain": 0.85},
                )
            )
            store.save(state)

        graph_claim = scenario.claim.model_copy(deep=True)
        loop = EvidenceLoop(ClaimGraph(claims=[graph_claim]))
        _upsert_state_claim(state, graph_claim)
        initial = loop.assess()
        plan = initial.route.experiment_plan
        if plan is None:
            raise RuntimeError("configured evidence scenario has no initial evidence gap")
        state.current_experiment_plan = ExperimentPlan(
            plan_id=plan.plan_id,
            objective=plan.objective,
            falsifies=[plan.falsification_test],
            estimated_cost=plan.action.expected_cost,
            target_claim_ids=[plan.claim_id],
            target_evidence_type=plan.target_evidence_type,
            counterfactuals=[plan.counterfactual],
            matched_baselines=[plan.matched_baseline],
            negative_controls=[plan.negative_control],
            expected_information_gain=plan.expected_information_gain,
        )
        store.save(state)

        execution_cost = scenario.result.cost
        _, execution = act(
            plan.action.model_copy(
                update={
                    "parameters": {
                        **plan.action.parameters,
                        "observation": scenario.interpretation.observed,
                        "experiment_id": scenario.result.experiment_id,
                    },
                    "expected_cost": execution_cost,
                }
            )
        )
        result_record, interpretation, result_basis = _resolve_result_evidence(
            scenario,
            execution,
        )
        state.experiment_history.append(
            ExperimentRecord(
                experiment_id=result_record.experiment_id,
                action_id=plan.action.action_id,
                status=execution.status.value,
                result_ref=result_record.result_id,
                cost=result_record.cost,
            )
        )
        review = InterpretationCritic().review(result_record, interpretation)
        outcome = loop.add_review(review)
        graph_evidence = loop.evidence.items[-1]
        state.evidence_graph.items.append(
            StateEvidenceItem.model_validate(graph_evidence.model_dump())
        )
        state.observations.append(
            ResearchObservation(
                observation_id=review.observation.observation_id,
                statement=review.observation.statement,
                source_result_id=review.result.result_id,
                reproducible=review.observation.reproducible,
                stability=review.observation.stability,
                expected=review.observation.expected,
            )
        )
        state.interpretation_history.append(review.model_dump(mode="json"))
        _upsert_state_claim(state, graph_claim)
        state.current_experiment_plan = None
        store.save(state)

        act(outcome.route.action)
        if outcome.route.action.type == MetaAction.PIVOT:
            if scenario.pivot is None:
                raise ValueError("a contradictory scenario requires pivot configuration")
            transformed = EvidenceToIdeaEngine().transform(
                ContradictoryPilotEvidence(
                    pilot_id=scenario.result.experiment_id,
                    idea_id=state.active_idea_id or "unlinked-idea",
                    expected=scenario.interpretation.expected,
                    observed=scenario.interpretation.observed,
                    stable=review.observation.reproducible,
                    stability=review.observation.stability,
                    boundary_conditions=scenario.pivot.boundary_conditions,
                    explanation_gap=scenario.pivot.explanation_gap,
                    importance=scenario.pivot.importance,
                ),
                idea_seed=scenario.pivot.idea_seed,
            )
            state.observations.append(transformed.observation)
            state.problem_candidates.append(transformed.problem)
            state.candidate_ideas.append(transformed.idea)
            state.active_problem_id = transformed.problem.problem_id
            state.active_idea_id = transformed.idea.idea_id
        store.save(state)

        summary: dict[str, object] = {
            "project_id": state.project_id,
            "claim_id": graph_claim.claim_id,
            "claim_status": graph_claim.status.value,
            "selected_actions": [
                decision.selected_action.type.value for decision in state.decision_history
            ],
            "route": outcome.route.action.type.value,
            "final_stage": state.current_stage.value,
            "evidence_count": len(state.evidence_graph.items),
            "result_basis": result_basis,
            "result_id": result_record.result_id,
            "measured_metrics": result_record.metrics,
            "resource_usage": state.resource_usage.model_dump(mode="json"),
            "decision_log": str(logger.path),
            "latest_state": str(store.latest_path),
        }
        (root / "evidence_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary


def load_evidence_scenario(path: str | Path) -> EvidenceWorkflowScenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return EvidenceWorkflowScenario.model_validate(data)


def _upsert_state_claim(state: ResearchState, claim: GraphClaim) -> None:
    converted = StateClaim.model_validate(claim.model_dump(mode="json"))
    for index, existing in enumerate(state.claims):
        if existing.claim_id == claim.claim_id:
            state.claims[index] = converted
            return
    state.claims.append(converted)


def _resolve_result_evidence(
    scenario: EvidenceWorkflowScenario,
    execution: ExecutionResult,
) -> tuple[ResultRecord, InterpretationContext, str]:
    """Prefer independently measured sandbox evidence over scenario fixtures."""

    if execution.data.get("result_basis") != "sandbox-measured-replicates":
        return scenario.result, scenario.interpretation, "scenario-declared-result"
    experiment_id = execution.data.get("experiment_id")
    metrics = execution.data.get("metrics")
    relation = execution.data.get("metric_assessment")
    reproducible = execution.data.get("reproducible")
    stability = execution.data.get("stability")
    uncertainty = execution.data.get("statistical_uncertainty")
    primary_metric = execution.data.get("primary_metric")
    primary_value = execution.data.get("primary_value")
    metrics_artifact = execution.data.get("metrics_artifact")
    if (
        execution.executor != "scitaste-native"
        or execution.data.get("execution_mode") != "bubblewrap-isolated-python"
    ):
        raise ValueError("measured experiment does not come from the native isolation boundary")
    if experiment_id != scenario.result.experiment_id:
        raise ValueError("measured experiment identity does not match the evidence scenario")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("measured experiment did not provide a metric mapping")
    measured_metrics: dict[str, float] = {}
    for name, value in metrics.items():
        if (
            not isinstance(name, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("measured experiment metrics must be finite numeric values")
        measured_metrics[name] = float(value)
    if (
        not isinstance(primary_metric, str)
        or primary_metric not in scenario.result.metrics
        or primary_metric not in measured_metrics
        or isinstance(primary_value, bool)
        or not isinstance(primary_value, (int, float))
        or not math.isclose(
            float(primary_value), measured_metrics[primary_metric], rel_tol=1e-12, abs_tol=1e-12
        )
    ):
        raise ValueError("measured experiment primary metric does not match its evidence contract")
    if not isinstance(metrics_artifact, str) or metrics_artifact not in execution.artifacts:
        raise ValueError("measured experiment is missing its parsed metric artifact")
    if relation not in {ClaimRelation.SUPPORTS.value, ClaimRelation.CONTRADICTS.value}:
        raise ValueError("measured experiment did not provide a valid metric assessment")
    if not isinstance(reproducible, bool):
        raise ValueError("measured experiment did not provide reproducibility status")
    if (
        isinstance(stability, bool)
        or not isinstance(stability, (int, float))
        or not 0.0 <= float(stability) <= 1.0
        or isinstance(uncertainty, bool)
        or not isinstance(uncertainty, (int, float))
        or not 0.0 <= float(uncertainty) <= 1.0
    ):
        raise ValueError("measured experiment stability and uncertainty must be normalized")
    if len(execution.observations) != 1:
        raise ValueError("measured experiment must provide one derived observation")
    result = ResultRecord(
        result_id=execution.result_id,
        experiment_id=experiment_id,
        summary="Isolated execution completed with independently parsed replicate metrics.",
        metrics=measured_metrics,
        cost=execution.cost,
    )
    context = scenario.interpretation.model_copy(
        update={
            "observed": execution.observations[0],
            "relation": ClaimRelation(relation),
            "reproducible": reproducible,
            "stability": float(stability),
            "statistical_uncertainty": float(uncertainty),
        }
    )
    return result, context, "sandbox-measured-replicates"

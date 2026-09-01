"""One adaptive Discovery Loop; trajectory labels are outcomes, never switches."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.discovery.hypothesis import HypothesisAgent, HypothesisSeed
from scitaste.discovery.ideas import IdeaPortfolioBuilder, IdeaSeed, MatureIdeaGenerator
from scitaste.discovery.landscape import (
    LandscapeFinding,
    LiteratureLandscapeAgent,
)
from scitaste.discovery.probe_agent import (
    DiagnosticProbeAgent,
    ProbeDisposition,
    ProbeSignal,
)
from scitaste.discovery.problem import ProblemFormationAgent, ProblemSeed
from scitaste.executor.base import ExecutionResult, ResearchExecutor
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController


class IntuitionSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=1)
    source: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class DiscoveryScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    research_direction: str
    target_domain: str
    target_venue: str | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    landscape_findings: list[LandscapeFinding] = Field(min_length=1)
    intuition: IntuitionSeed
    initial_hypothesis: HypothesisSeed
    reformulations: list[HypothesisSeed] = Field(default_factory=list)
    probe_signals: list[ProbeSignal] = Field(min_length=1)
    problem: ProblemSeed
    idea_seeds: list[IdeaSeed] = Field(min_length=3)

    @model_validator(mode="after")
    def has_enough_reformulations(self) -> DiscoveryScenario:
        possible_contradictions = sum(not signal.expected for signal in self.probe_signals[:-1])
        if possible_contradictions > len(self.reformulations):
            raise ValueError("each non-final contradictory probe needs a reformulation seed")
        return self


class DiscoveryLoop:
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
        scenario: DiscoveryScenario,
        *,
        output_dir: str | Path,
    ) -> dict[str, object]:
        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise FileExistsError(f"refusing to append to existing discovery log: {logger.path}")
        store = StateStore(root)
        state = ResearchState(
            project_id=scenario.project_id,
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            resource_budget=scenario.resource_budget,
        )
        store.save(state)

        def act(candidates: list[ResearchAction]) -> tuple[ResearchDecision, ExecutionResult]:
            nonlocal state
            decision = self.controller.decide(state=state, candidate_actions=candidates)
            result = self.executor.execute(state, decision.selected_action)
            decision.executor_result_id = result.result_id
            decision.actual_outcome = result.model_dump(mode="json")
            logger.append(decision)
            state = apply_transition(state, decision)
            return decision, result

        landscape_agent = LiteratureLandscapeAgent()
        hypothesis_agent = HypothesisAgent()
        probe_agent = DiagnosticProbeAgent()

        act(
            [
                ResearchAction(
                    action_id="discovery-search",
                    type=MetaAction.SEARCH,
                    description="Build a source-linked structured literature landscape",
                    expected_cost={"wall_time_hours": 0.05},
                    expected_value={"information_gain": 0.8, "problem_validity": 0.5},
                )
            ]
        )
        state.literature_landscape = landscape_agent.build(scenario.landscape_findings)
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="discovery-form-intuition",
                    type=MetaAction.FORM_INTUITION,
                    description="Form a lightweight direction without treating it as an idea",
                    expected_cost={"wall_time_hours": 0.01},
                    expected_value={"information_gain": 0.4},
                )
            ]
        )
        context_ids = sorted(
            {source for finding in scenario.landscape_findings for source in finding.source_ids}
        )
        intuition = hypothesis_agent.form_intuition(
            intuition_id="intuition-01",
            statement=scenario.intuition.statement,
            source=scenario.intuition.source,
            supporting_context_ids=context_ids,
            confidence=scenario.intuition.confidence,
        )
        state.research_intuitions.append(intuition)
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="discovery-form-hypothesis",
                    type=MetaAction.FORM_WORKING_HYPOTHESIS,
                    description="Turn the intuition into a falsifiable provisional hypothesis",
                    expected_cost={"wall_time_hours": 0.01},
                    expected_value={"information_gain": 0.65, "problem_validity": 0.4},
                )
            ]
        )
        hypothesis = hypothesis_agent.form_working_hypothesis(
            hypothesis_id="working-hypothesis-01",
            seed=scenario.initial_hypothesis,
            intuition_ids=[intuition.intuition_id],
        )
        state.working_hypotheses.append(hypothesis)
        state.active_working_hypothesis_id = hypothesis.hypothesis_id
        store.save(state)

        probe_count = 0
        reformulation_index = 0
        for signal_index, signal in enumerate(scenario.probe_signals):
            hypothesis = _active_hypothesis(state)
            probe_count += 1
            plan = probe_agent.plan(hypothesis, probe_index=probe_count)
            uncertainty = 1.0 - hypothesis.confidence
            decision, result = act(
                [
                    ResearchAction(
                        action_id=plan.probe_id,
                        type=MetaAction.PROBE,
                        description=f"Cheap {plan.probe_type} sanity/diagnostic probe",
                        parameters={"observation": signal.observation, "probe": plan.model_dump()},
                        expected_cost=plan.estimated_cost,
                        expected_value={
                            "information_gain": max(0.65, uncertainty),
                            "problem_validity": 0.7,
                        },
                    ),
                    ResearchAction(
                        action_id=f"premature-formulation-{probe_count:02d}",
                        type=MetaAction.FORMULATE_PROBLEM,
                        description="Formulate a problem before the planned sanity check",
                        expected_cost={"wall_time_hours": 0.01},
                        expected_value={"problem_validity": hypothesis.confidence * 0.35},
                    ),
                ]
            )
            if decision.selected_action.type != MetaAction.PROBE:
                raise RuntimeError("discovery fixture did not make the diagnostic probe worthwhile")
            assessment = probe_agent.assess(plan, result, signal)
            state.observations.append(assessment.observation)
            hypothesis = _active_hypothesis(state)
            hypothesis_agent.incorporate_observation(hypothesis, assessment.observation)
            store.save(state)

            if assessment.disposition == ProbeDisposition.CONTRADICT:
                if reformulation_index >= len(scenario.reformulations):
                    break
                decision, _ = act(
                    [
                        ResearchAction(
                            action_id=f"reformulate-{probe_count:02d}",
                            type=MetaAction.REFORMULATE_HYPOTHESIS,
                            description="Retain the contradiction and propose a new explanation",
                            expected_value={"information_gain": 0.95, "problem_validity": 0.8},
                        ),
                        ResearchAction(
                            action_id=f"discard-{probe_count:02d}",
                            type=MetaAction.DISCARD_HYPOTHESIS,
                            description="Discard the failed run and its observation",
                            expected_value={"information_gain": 0.05},
                        ),
                    ]
                )
                if decision.selected_action.type != MetaAction.REFORMULATE_HYPOTHESIS:
                    raise RuntimeError("stable contradiction was not retained for reformulation")
                revised = hypothesis_agent.form_working_hypothesis(
                    hypothesis_id=f"working-hypothesis-{reformulation_index + 2:02d}",
                    seed=scenario.reformulations[reformulation_index],
                    intuition_ids=[intuition.intuition_id],
                    parent_hypothesis_ids=[hypothesis.hypothesis_id],
                )
                reformulation_index += 1
                state.working_hypotheses.append(revised)
                state.active_working_hypothesis_id = revised.hypothesis_id
                store.save(state)
                continue

            if assessment.disposition == ProbeDisposition.INCONCLUSIVE:
                if signal_index == len(scenario.probe_signals) - 1:
                    raise RuntimeError("discovery ended with only inconclusive probe evidence")
                act(
                    [
                        ResearchAction(
                            action_id=f"re-probe-{probe_count:02d}",
                            type=MetaAction.RE_PROBE,
                            description="Repeat or refine an unstable diagnostic",
                            expected_value={"information_gain": 0.85},
                        )
                    ]
                )
                store.save(state)
                continue

            act(
                [
                    ResearchAction(
                        action_id=f"validate-{probe_count:02d}",
                        type=MetaAction.VALIDATE_HYPOTHESIS,
                        description="Record reproducible support and advance to problem formation",
                        expected_value={"problem_validity": 0.9},
                    )
                ]
            )
            store.save(state)
            break

        act(
            [
                ResearchAction(
                    action_id="discovery-formulate-problem",
                    type=MetaAction.FORMULATE_PROBLEM,
                    description="Convert stable observations into a bounded research problem",
                    expected_value={"problem_validity": 0.95, "scientific_importance": 0.8},
                )
            ]
        )
        problem = ProblemFormationAgent().form(
            problem_id="research-problem-01",
            observations=state.observations,
            seed=scenario.problem,
        )
        state.problem_candidates.append(problem)
        state.active_problem_id = problem.problem_id
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="discovery-generate-ideas",
                    type=MetaAction.IDEATE,
                    description="Generate divergent mechanisms, then normalize their presentation",
                    expected_value={"novelty": 0.8, "problem_validity": 0.95},
                )
            ]
        )
        ideas = MatureIdeaGenerator().generate(
            problem=problem,
            observations=state.observations,
            seeds=scenario.idea_seeds,
        )
        state.candidate_ideas.extend(ideas)
        store.save(state)

        selection_actions = [
            ResearchAction(
                action_id=f"select-{idea.idea_id}",
                type=MetaAction.SELECT_IDEA,
                description=f"Select normalized idea: {idea.proposed_mechanism}",
                parameters={"idea_id": idea.idea_id},
                expected_cost=idea.expected_cost,
                expected_value=idea.expected_value,
            )
            for idea in ideas
        ]
        decision, _ = act(selection_actions)
        selected_id = str(decision.selected_action.parameters["idea_id"])
        state.active_idea_id = selected_id
        for idea in state.candidate_ideas:
            if idea.idea_id == selected_id:
                idea.status = "selected_for_pilot"
        state.idea_portfolio = IdeaPortfolioBuilder().build(
            state.candidate_ideas,
            primary_idea_id=selected_id,
        )
        store.save(state)

        selected_actions = [item.selected_action.type.value for item in state.decision_history]
        evidence_first = probe_count > 1 or any(
            observation.expected is False for observation in state.observations
        )
        summary: dict[str, object] = {
            "project_id": state.project_id,
            "trajectory_class": "evidence-first-like" if evidence_first else "idea-first-like",
            "probe_count": probe_count,
            "selected_actions": selected_actions,
            "working_hypothesis_count": len(state.working_hypotheses),
            "observation_count": len(state.observations),
            "problem_id": state.active_problem_id,
            "candidate_idea_count": len(state.candidate_ideas),
            "primary_idea_id": state.active_idea_id,
            "final_stage": state.current_stage.value,
            "decision_log": str(logger.path),
            "latest_state": str(store.latest_path),
        }
        (root / "discovery_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary


def load_discovery_scenario(path: str | Path) -> DiscoveryScenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return DiscoveryScenario.model_validate(data)


def _active_hypothesis(state: ResearchState):
    return next(
        item
        for item in state.working_hypotheses
        if item.hypothesis_id == state.active_working_hypothesis_id
    )

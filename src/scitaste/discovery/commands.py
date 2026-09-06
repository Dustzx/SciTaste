"""Composable, evidence-bearing commands for the native Discovery Loop."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.discovery.hypothesis import HypothesisAgent
from scitaste.discovery.ideas import IdeaPortfolioBuilder, MatureIdeaGenerator
from scitaste.discovery.landscape import LiteratureLandscapeAgent
from scitaste.discovery.probe_agent import (
    DiagnosticProbeAgent,
    ProbeDisposition,
)
from scitaste.discovery.problem import ProblemFormationAgent
from scitaste.discovery.semantic_models import (
    DISCOVERY_HYPOTHESIS_NODE,
    DISCOVERY_IDEATION_NODE,
    DISCOVERY_REFORMULATION_NODE,
    DiscoveryHypothesisProposal,
    DiscoveryIdeationProposal,
    DiscoveryReformulationProposal,
    DiscoverySemanticReference,
)
from scitaste.executor.base import ExecutionResult, ResearchExecutor, require_execution_success
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore, canonical_json, snapshot_id
from scitaste.state.research_state import (
    ResearchStage,
    ResearchState,
    WorkingHypothesis,
    WorkingHypothesisStatus,
)
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController

_SemanticProposal = (
    DiscoveryHypothesisProposal | DiscoveryReformulationProposal | DiscoveryIdeationProposal
)

if TYPE_CHECKING:
    from scitaste.discovery.loop import DiscoveryScenario

_ContentDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_StateSnapshotId = Annotated[str, Field(pattern=r"^state-[0-9a-f]{64}$")]


class DiscoveryCommand(StrEnum):
    """Public, composable Phase 4 operations required by the project specification."""

    HYPOTHESIZE = "hypothesize"
    PROBE = "probe"
    REFORMULATE = "reformulate"
    IDEATE = "ideate"
    PORTFOLIO_SELECT = "portfolio-select"


class DiscoveryCommandPreview(BaseModel):
    """Mutation-free admission result for one discovery command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: DiscoveryCommand
    project_id: str
    input_state_id: _StateSnapshotId | None = None
    input_revision: int | None = None
    current_stage: ResearchStage | None = None
    planned_actions: list[MetaAction] = Field(min_length=1)
    signal_number: int | None = Field(default=None, ge=1)
    reformulation_number: int | None = Field(default=None, ge=1)


class DiscoveryCommandReport(BaseModel):
    """Content-bound receipt emitted only after a command completes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    status: Literal["completed"] = "completed"
    command: DiscoveryCommand
    project_id: str
    backend: str
    seed: int
    scenario_sha256: _ContentDigest
    input_state_id: _StateSnapshotId | None = None
    output_state_id: _StateSnapshotId
    output_revision: int = Field(ge=1)
    final_stage: ResearchStage
    selected_actions: list[MetaAction] = Field(min_length=1)
    decision_ids: list[str] = Field(min_length=1)
    executor_result_ids: list[str] = Field(min_length=1)
    active_working_hypothesis_id: str | None = None
    active_problem_id: str | None = None
    active_idea_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    semantic_proposal: DiscoverySemanticReference | None = None
    state: str
    decision_log: str
    decision_log_sha256: _ContentDigest
    report: str


@dataclass(frozen=True)
class _CommandOutcome:
    state: ResearchState
    decisions: list[ResearchDecision]
    results: list[ExecutionResult]
    details: dict[str, Any]


class DiscoveryCommandRunner:
    """Run one bounded discovery operation without mutating its input state.

    Every command accepts the same validated scenario. Commands after
    ``hypothesize`` consume a prior ``research_state.json`` and publish a new
    immutable output directory. The controller still chooses among candidates;
    invoking a command does not bypass scientific-taste or resource admission.
    """

    def __init__(
        self,
        *,
        controller: TasteController | None = None,
        executor: ResearchExecutor | None = None,
        seed: int = 0,
    ) -> None:
        self.seed = seed
        self.controller = controller or TasteController(seed=seed)
        self.executor = executor or MockExecutor(seed=seed)

    def preview(
        self,
        command: DiscoveryCommand,
        scenario: DiscoveryScenario,
        *,
        state: ResearchState | None = None,
        signal_number: int | None = None,
        reformulation_number: int | None = None,
    ) -> DiscoveryCommandPreview:
        """Validate command inputs and return the admitted action outline."""

        if command == DiscoveryCommand.HYPOTHESIZE:
            if state is not None:
                raise ValueError("hypothesize initializes a new state and does not accept --state")
            return DiscoveryCommandPreview(
                command=command,
                project_id=scenario.project_id,
                planned_actions=[
                    MetaAction.SEARCH,
                    MetaAction.FORM_INTUITION,
                    MetaAction.FORM_WORKING_HYPOTHESIS,
                ],
            )

        if state is None:
            raise ValueError(f"{command.value} requires --state PATH")
        self._require_scenario_match(scenario, state)

        planned_actions: list[MetaAction]
        resolved_signal: int | None = None
        resolved_reformulation: int | None = None
        if command == DiscoveryCommand.PROBE:
            self._require_stage(state, ResearchStage.DISCOVERY, command)
            self._active_hypothesis(state)
            resolved_signal = self._resolve_signal_number(
                scenario,
                state,
                signal_number,
            )
            planned_actions = [MetaAction.PROBE]
        elif command == DiscoveryCommand.REFORMULATE:
            self._require_stage(state, ResearchStage.DISCOVERY, command)
            hypothesis = self._active_hypothesis(state)
            if hypothesis.status != WorkingHypothesisStatus.CONTRADICTED:
                raise ValueError("reformulate requires a contradicted active working hypothesis")
            resolved_reformulation = self._resolve_reformulation_number(
                scenario,
                state,
                reformulation_number,
            )
            planned_actions = [MetaAction.REFORMULATE_HYPOTHESIS]
        elif command == DiscoveryCommand.IDEATE:
            if state.current_stage not in {
                ResearchStage.DISCOVERY,
                ResearchStage.PROBLEM_FORMULATION,
            }:
                raise ValueError("ideate requires DISCOVERY or PROBLEM_FORMULATION state")
            if state.candidate_ideas:
                raise ValueError("ideate refuses to replace existing candidate ideas")
            if not any(item.reproducible for item in state.observations):
                raise ValueError("ideate requires at least one reproducible observation")
            planned_actions = []
            if state.active_problem_id is None:
                planned_actions.append(MetaAction.FORMULATE_PROBLEM)
            planned_actions.append(MetaAction.IDEATE)
        elif command == DiscoveryCommand.PORTFOLIO_SELECT:
            self._require_stage(state, ResearchStage.IDEATION, command)
            if not state.candidate_ideas:
                raise ValueError("portfolio select requires candidate ideas")
            if state.idea_portfolio is not None or state.active_idea_id is not None:
                raise ValueError("portfolio select refuses to replace an existing selection")
            planned_actions = [MetaAction.SELECT_IDEA]
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"unsupported discovery command {command!r}")

        return DiscoveryCommandPreview(
            command=command,
            project_id=state.project_id,
            input_state_id=snapshot_id(state),
            input_revision=state.revision,
            current_stage=state.current_stage,
            planned_actions=planned_actions,
            signal_number=resolved_signal,
            reformulation_number=resolved_reformulation,
        )

    def run(
        self,
        command: DiscoveryCommand,
        scenario: DiscoveryScenario,
        *,
        output_dir: str | Path,
        state: ResearchState | None = None,
        signal_number: int | None = None,
        reformulation_number: int | None = None,
        receipt_paths: Literal["filesystem", "step-relative"] = "filesystem",
        semantic_proposal: _SemanticProposal | None = None,
        semantic_reference: DiscoverySemanticReference | None = None,
    ) -> DiscoveryCommandReport:
        """Execute and exclusively own a new discovery-step directory."""

        if receipt_paths not in {"filesystem", "step-relative"}:
            raise ValueError(f"unsupported discovery receipt path mode {receipt_paths!r}")
        root = Path(output_dir)
        if root.exists():
            raise FileExistsError(f"refusing to replace discovery command output: {root}")
        if (semantic_proposal is None) != (semantic_reference is None):
            raise ValueError("semantic proposal and reference must be supplied together")
        if semantic_proposal is not None:
            expected = {
                DiscoveryCommand.HYPOTHESIZE: (
                    DiscoveryHypothesisProposal,
                    DISCOVERY_HYPOTHESIS_NODE,
                ),
                DiscoveryCommand.REFORMULATE: (
                    DiscoveryReformulationProposal,
                    DISCOVERY_REFORMULATION_NODE,
                ),
                DiscoveryCommand.IDEATE: (
                    DiscoveryIdeationProposal,
                    DISCOVERY_IDEATION_NODE,
                ),
            }.get(command)
            if (
                expected is None
                or not isinstance(semantic_proposal, expected[0])
                or semantic_reference is None
                or semantic_reference.node_name != expected[1]
            ):
                raise ValueError("semantic proposal type does not match the discovery command")
        preview = self.preview(
            command,
            scenario,
            state=state,
            signal_number=signal_number,
            reformulation_number=reformulation_number,
        )
        input_state_id = snapshot_id(state) if state is not None else None
        if command == DiscoveryCommand.HYPOTHESIZE:
            outcome = self._hypothesize(
                scenario,
                semantic_proposal=semantic_proposal,
                semantic_reference=semantic_reference,
            )
        elif command == DiscoveryCommand.PROBE:
            assert state is not None and preview.signal_number is not None
            outcome = self._probe(scenario, state, signal_number=preview.signal_number)
        elif command == DiscoveryCommand.REFORMULATE:
            assert state is not None and preview.reformulation_number is not None
            outcome = self._reformulate(
                scenario,
                state,
                reformulation_number=preview.reformulation_number,
                semantic_proposal=(
                    semantic_proposal
                    if isinstance(semantic_proposal, DiscoveryReformulationProposal)
                    else None
                ),
                semantic_reference=semantic_reference,
            )
        elif command == DiscoveryCommand.IDEATE:
            assert state is not None
            outcome = self._ideate(
                scenario,
                state,
                semantic_proposal=(
                    semantic_proposal
                    if isinstance(semantic_proposal, DiscoveryIdeationProposal)
                    else None
                ),
                semantic_reference=semantic_reference,
            )
        else:
            assert command == DiscoveryCommand.PORTFOLIO_SELECT and state is not None
            outcome = self._select_portfolio(state)
        return self._publish(
            command,
            scenario,
            root=root,
            input_state_id=input_state_id,
            outcome=outcome,
            receipt_paths=receipt_paths,
            semantic_reference=semantic_reference,
        )

    def _hypothesize(
        self,
        scenario: DiscoveryScenario,
        *,
        semantic_proposal: DiscoveryHypothesisProposal | None = None,
        semantic_reference: DiscoverySemanticReference | None = None,
    ) -> _CommandOutcome:
        semantic_context = (
            semantic_reference.model_dump(mode="json") if semantic_reference is not None else None
        )
        executor_context: dict[str, Any] = {
            "discovery_command": {
                "schema_version": "1.0",
                "scenario_sha256": self._scenario_sha256(scenario),
            },
            "discovery_semantic": semantic_context,
        }
        if semantic_context is not None:
            executor_context["discovery_semantics"] = [semantic_context]
        state = ResearchState(
            project_id=scenario.project_id,
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            resource_budget=scenario.resource_budget,
            executor_context=executor_context,
        )
        if semantic_reference is not None:
            state.resource_usage.api_cost_usd = semantic_reference.cost_usd
        decisions: list[ResearchDecision] = []
        results: list[ExecutionResult] = []

        state, decision, result = self._act(
            state,
            [
                ResearchAction(
                    action_id="discovery-search",
                    type=MetaAction.SEARCH,
                    description="Build a source-linked structured literature landscape",
                    parameters={
                        "query": scenario.research_direction,
                        "domain_tags": [scenario.target_domain],
                        "limit": 5,
                    },
                    expected_cost={"wall_time_hours": 0.05},
                    expected_value={"information_gain": 0.8, "problem_validity": 0.5},
                )
            ],
        )
        decisions.append(decision)
        results.append(result)
        state.literature_landscape = LiteratureLandscapeAgent().build(scenario.landscape_findings)

        state, decision, result = self._act(
            state,
            [
                ResearchAction(
                    action_id="discovery-form-intuition",
                    type=MetaAction.FORM_INTUITION,
                    description="Form a lightweight direction without treating it as an idea",
                    expected_cost={"wall_time_hours": 0.01},
                    expected_value={"information_gain": 0.4},
                )
            ],
        )
        decisions.append(decision)
        results.append(result)
        context_ids = (
            list(semantic_proposal.intuition.supporting_source_ids)
            if semantic_proposal is not None
            else sorted(
                {source for finding in scenario.landscape_findings for source in finding.source_ids}
            )
        )
        hypothesis_agent = HypothesisAgent()
        intuition = hypothesis_agent.form_intuition(
            intuition_id="intuition-01",
            statement=(
                semantic_proposal.intuition.statement
                if semantic_proposal is not None
                else scenario.intuition.statement
            ),
            source=(
                "bounded-model-synthesis-of-registered-landscape"
                if semantic_proposal is not None
                else scenario.intuition.source
            ),
            supporting_context_ids=context_ids,
            confidence=(
                semantic_proposal.intuition.confidence
                if semantic_proposal is not None
                else scenario.intuition.confidence
            ),
        )
        state.research_intuitions.append(intuition)

        state, decision, result = self._act(
            state,
            [
                ResearchAction(
                    action_id="discovery-form-hypothesis",
                    type=MetaAction.FORM_WORKING_HYPOTHESIS,
                    description="Turn the intuition into a falsifiable provisional hypothesis",
                    expected_cost={"wall_time_hours": 0.01},
                    expected_value={"information_gain": 0.65, "problem_validity": 0.4},
                )
            ],
        )
        decisions.append(decision)
        results.append(result)
        hypothesis = hypothesis_agent.form_working_hypothesis(
            hypothesis_id="working-hypothesis-01",
            seed=(
                semantic_proposal.hypothesis
                if semantic_proposal is not None
                else scenario.initial_hypothesis
            ),
            intuition_ids=[intuition.intuition_id],
        )
        state.working_hypotheses.append(hypothesis)
        state.active_working_hypothesis_id = hypothesis.hypothesis_id
        return _CommandOutcome(
            state=state,
            decisions=decisions,
            results=results,
            details={
                "hypothesis_id": hypothesis.hypothesis_id,
                "content_origin": (
                    "bounded-semantic-proposal"
                    if semantic_proposal is not None
                    else "registered-scenario-seed"
                ),
                "alternative_explanations": (
                    list(semantic_proposal.alternative_explanations)
                    if semantic_proposal is not None
                    else []
                ),
                "uncertainty": (
                    semantic_proposal.uncertainty if semantic_proposal is not None else None
                ),
            },
        )

    def _probe(
        self,
        scenario: DiscoveryScenario,
        source_state: ResearchState,
        *,
        signal_number: int,
    ) -> _CommandOutcome:
        state = source_state.model_copy(deep=True)
        hypothesis = self._active_hypothesis(state)
        plan = DiagnosticProbeAgent().plan(
            hypothesis,
            probe_index=self._probe_count(state) + 1,
        )
        signal = scenario.probe_signals[signal_number - 1]
        uncertainty = 1.0 - hypothesis.confidence
        state, decision, result = self._act(
            state,
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
                    action_id=f"premature-formulation-{signal_number:02d}",
                    type=MetaAction.FORMULATE_PROBLEM,
                    description="Formulate a problem before the planned sanity check",
                    expected_cost={"wall_time_hours": 0.01},
                    expected_value={"problem_validity": hypothesis.confidence * 0.35},
                ),
            ],
            required_action=MetaAction.PROBE,
        )
        assessment = DiagnosticProbeAgent().assess(plan, result, signal)
        state.observations.append(assessment.observation)
        HypothesisAgent().incorporate_observation(
            self._active_hypothesis(state),
            assessment.observation,
        )
        decisions = [decision]
        results = [result]
        follow_up: MetaAction | None = None
        if assessment.disposition == ProbeDisposition.SUPPORT:
            follow_up = MetaAction.VALIDATE_HYPOTHESIS
            state, follow_decision, follow_result = self._act(
                state,
                [
                    ResearchAction(
                        action_id=f"validate-{signal_number:02d}",
                        type=follow_up,
                        description="Record reproducible support before problem formation",
                        expected_value={"problem_validity": 0.9},
                    )
                ],
            )
            decisions.append(follow_decision)
            results.append(follow_result)
        elif assessment.disposition == ProbeDisposition.INCONCLUSIVE:
            follow_up = MetaAction.RE_PROBE
            state, follow_decision, follow_result = self._act(
                state,
                [
                    ResearchAction(
                        action_id=f"re-probe-{signal_number:02d}",
                        type=follow_up,
                        description="Repeat or refine an unstable diagnostic",
                        expected_value={"information_gain": 0.85},
                    )
                ],
            )
            decisions.append(follow_decision)
            results.append(follow_result)
        return _CommandOutcome(
            state=state,
            decisions=decisions,
            results=results,
            details={
                "signal_number": signal_number,
                "probe_id": plan.probe_id,
                "observation_id": assessment.observation.observation_id,
                "disposition": assessment.disposition.value,
                "informative": assessment.informative,
                "follow_up": follow_up.value if follow_up is not None else None,
            },
        )

    def _reformulate(
        self,
        scenario: DiscoveryScenario,
        source_state: ResearchState,
        *,
        reformulation_number: int,
        semantic_proposal: DiscoveryReformulationProposal | None = None,
        semantic_reference: DiscoverySemanticReference | None = None,
    ) -> _CommandOutcome:
        state = source_state.model_copy(deep=True)
        if semantic_reference is not None:
            self._bind_semantic_reference(state, semantic_reference)
        parent = self._active_hypothesis(state)
        state, decision, result = self._act(
            state,
            [
                ResearchAction(
                    action_id=f"reformulate-{reformulation_number:02d}",
                    type=MetaAction.REFORMULATE_HYPOTHESIS,
                    description="Retain the contradiction and propose a new explanation",
                    expected_value={"information_gain": 0.95, "problem_validity": 0.8},
                ),
                ResearchAction(
                    action_id=f"discard-{reformulation_number:02d}",
                    type=MetaAction.DISCARD_HYPOTHESIS,
                    description="Discard the failed run and its observation",
                    expected_value={"information_gain": 0.05},
                ),
            ],
            required_action=MetaAction.REFORMULATE_HYPOTHESIS,
        )
        hypothesis_id = self._next_hypothesis_id(state)
        revised = HypothesisAgent().form_working_hypothesis(
            hypothesis_id=hypothesis_id,
            seed=(
                semantic_proposal.hypothesis
                if semantic_proposal is not None
                else scenario.reformulations[reformulation_number - 1]
            ),
            intuition_ids=parent.derived_from_intuition_ids,
            parent_hypothesis_ids=[parent.hypothesis_id],
        )
        state.working_hypotheses.append(revised)
        state.active_working_hypothesis_id = revised.hypothesis_id
        details: dict[str, Any] = {
            "reformulation_number": reformulation_number,
            "parent_hypothesis_id": parent.hypothesis_id,
            "hypothesis_id": revised.hypothesis_id,
        }
        if semantic_proposal is not None:
            details.update(
                {
                    "content_origin": "bounded-semantic-reformulation",
                    "supporting_observation_ids": list(
                        semantic_proposal.supporting_observation_ids
                    ),
                    "retained_constraints": list(semantic_proposal.retained_constraints),
                    "alternative_explanations": list(semantic_proposal.alternative_explanations),
                    "uncertainty": semantic_proposal.uncertainty,
                }
            )
        return _CommandOutcome(
            state=state,
            decisions=[decision],
            results=[result],
            details=details,
        )

    def _ideate(
        self,
        scenario: DiscoveryScenario,
        source_state: ResearchState,
        *,
        semantic_proposal: DiscoveryIdeationProposal | None = None,
        semantic_reference: DiscoverySemanticReference | None = None,
    ) -> _CommandOutcome:
        state = source_state.model_copy(deep=True)
        if semantic_reference is not None:
            self._bind_semantic_reference(state, semantic_reference)
        decisions: list[ResearchDecision] = []
        results: list[ExecutionResult] = []
        if state.active_problem_id is None:
            state, decision, result = self._act(
                state,
                [
                    ResearchAction(
                        action_id="discovery-formulate-problem",
                        type=MetaAction.FORMULATE_PROBLEM,
                        description="Convert stable observations into a bounded research problem",
                        expected_value={
                            "problem_validity": 0.95,
                            "scientific_importance": 0.8,
                        },
                    )
                ],
            )
            decisions.append(decision)
            results.append(result)
            problem = ProblemFormationAgent().form(
                problem_id=self._next_problem_id(state),
                observations=state.observations,
                seed=(
                    semantic_proposal.problem if semantic_proposal is not None else scenario.problem
                ),
            )
            state.problem_candidates.append(problem)
            state.active_problem_id = problem.problem_id
        else:
            if semantic_proposal is not None:
                raise ValueError("semantic ideation requires problem formation in the same command")
            problem = next(
                item
                for item in state.problem_candidates
                if item.problem_id == state.active_problem_id
            )

        state, decision, result = self._act(
            state,
            [
                ResearchAction(
                    action_id="discovery-generate-ideas",
                    type=MetaAction.IDEATE,
                    description="Generate divergent mechanisms, then normalize their presentation",
                    expected_value={"novelty": 0.8, "problem_validity": 0.95},
                )
            ],
        )
        decisions.append(decision)
        results.append(result)
        ideas = MatureIdeaGenerator().generate(
            problem=problem,
            observations=state.observations,
            seeds=(
                list(semantic_proposal.idea_seeds)
                if semantic_proposal is not None
                else scenario.idea_seeds
            ),
        )
        state.candidate_ideas.extend(ideas)
        details: dict[str, Any] = {
            "problem_id": problem.problem_id,
            "candidate_idea_ids": [item.idea_id for item in ideas],
        }
        if semantic_proposal is not None:
            details.update(
                {
                    "content_origin": "bounded-semantic-ideation",
                    "active_hypothesis_id": semantic_proposal.active_hypothesis_id,
                    "supporting_observation_ids": list(
                        semantic_proposal.supporting_observation_ids
                    ),
                    "alternative_problem_formulations": list(
                        semantic_proposal.alternative_problem_formulations
                    ),
                    "uncertainty": semantic_proposal.uncertainty,
                }
            )
        return _CommandOutcome(
            state=state,
            decisions=decisions,
            results=results,
            details=details,
        )

    def _select_portfolio(self, source_state: ResearchState) -> _CommandOutcome:
        state = source_state.model_copy(deep=True)
        actions = [
            ResearchAction(
                action_id=f"select-{idea.idea_id}",
                type=MetaAction.SELECT_IDEA,
                description=f"Select normalized idea: {idea.proposed_mechanism}",
                parameters={"idea_id": idea.idea_id},
                expected_cost=idea.expected_cost,
                expected_value=idea.expected_value,
            )
            for idea in state.candidate_ideas
        ]
        state, decision, result = self._act(state, actions)
        selected_id = str(decision.selected_action.parameters["idea_id"])
        state.active_idea_id = selected_id
        for idea in state.candidate_ideas:
            if idea.idea_id == selected_id:
                idea.status = "selected_for_pilot"
        state.idea_portfolio = IdeaPortfolioBuilder().build(
            state.candidate_ideas,
            primary_idea_id=selected_id,
        )
        return _CommandOutcome(
            state=state,
            decisions=[decision],
            results=[result],
            details={
                "primary_idea_id": selected_id,
                "portfolio": state.idea_portfolio.model_dump(mode="json"),
            },
        )

    def _act(
        self,
        state: ResearchState,
        candidates: list[ResearchAction],
        *,
        required_action: MetaAction | None = None,
    ) -> tuple[ResearchState, ResearchDecision, ExecutionResult]:
        decision = self.controller.decide(state=state, candidate_actions=candidates)
        if required_action is not None and decision.selected_action.type != required_action:
            raise ValueError(
                f"TasteController rejected {required_action.value} for the supplied state"
            )
        result = self.executor.execute(state, decision.selected_action)
        decision.executor_result_id = result.result_id
        decision.actual_outcome = result.model_dump(mode="json")
        require_execution_success(result)
        return apply_transition(state, decision), decision, result

    @staticmethod
    def _bind_semantic_reference(
        state: ResearchState,
        reference: DiscoverySemanticReference,
    ) -> None:
        raw_history = state.executor_context.get("discovery_semantics")
        if raw_history is None:
            legacy = state.executor_context.get("discovery_semantic")
            history = [] if legacy is None else [legacy]
        elif isinstance(raw_history, list) and all(isinstance(item, dict) for item in raw_history):
            history = list(raw_history)
        else:
            raise ValueError("discovery semantic history is malformed")
        if any(item.get("invocation_id") == reference.invocation_id for item in history):
            raise ValueError("discovery semantic invocation is already bound to state")
        history.append(reference.model_dump(mode="json"))
        state.executor_context["discovery_semantics"] = history
        state.resource_usage.api_cost_usd += reference.cost_usd

    def _publish(
        self,
        command: DiscoveryCommand,
        scenario: DiscoveryScenario,
        *,
        root: Path,
        input_state_id: str | None,
        outcome: _CommandOutcome,
        receipt_paths: Literal["filesystem", "step-relative"],
        semantic_reference: DiscoverySemanticReference | None,
    ) -> DiscoveryCommandReport:
        root.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
        try:
            store = StateStore(temporary)
            output_state_id = store.save(outcome.state)
            logger = DecisionLogger(temporary / "decisions.jsonl")
            for decision in outcome.decisions:
                logger.append(decision)
            decision_log_sha256 = hashlib.sha256(logger.path.read_bytes()).hexdigest()
            temporary_report = temporary / "discovery_command.json"
            if receipt_paths == "step-relative":
                state_locator = "research_state.json"
                decision_locator = "decisions.jsonl"
                report_locator = "discovery_command.json"
            else:
                state_locator = str(root / "research_state.json")
                decision_locator = str(root / "decisions.jsonl")
                report_locator = str(root / "discovery_command.json")
            report = DiscoveryCommandReport(
                command=command,
                project_id=outcome.state.project_id,
                backend=type(self.executor).__name__,
                seed=self.seed,
                scenario_sha256=self._scenario_sha256(scenario),
                input_state_id=input_state_id,
                output_state_id=output_state_id,
                output_revision=outcome.state.revision,
                final_stage=outcome.state.current_stage,
                selected_actions=[item.selected_action.type for item in outcome.decisions],
                decision_ids=[item.decision_id for item in outcome.decisions],
                executor_result_ids=[item.result_id for item in outcome.results],
                active_working_hypothesis_id=outcome.state.active_working_hypothesis_id,
                active_problem_id=outcome.state.active_problem_id,
                active_idea_id=outcome.state.active_idea_id,
                details=outcome.details,
                semantic_proposal=semantic_reference,
                state=state_locator,
                decision_log=decision_locator,
                decision_log_sha256=decision_log_sha256,
                report=report_locator,
            )
            temporary_report.write_text(
                json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, root)
            return report
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _require_scenario_match(
        scenario: DiscoveryScenario,
        state: ResearchState,
    ) -> None:
        expected = (
            scenario.project_id,
            scenario.research_direction,
            scenario.target_domain,
            scenario.target_venue,
        )
        actual = (
            state.project_id,
            state.research_direction,
            state.target_domain,
            state.target_venue,
        )
        if actual != expected:
            raise ValueError("state identity does not match the discovery scenario")
        context = state.executor_context.get("discovery_command")
        if not isinstance(context, dict) or context.get("scenario_sha256") != (
            DiscoveryCommandRunner._scenario_sha256(scenario)
        ):
            raise ValueError("state content is bound to a different discovery scenario")

    @staticmethod
    def _scenario_sha256(scenario: DiscoveryScenario) -> str:
        return hashlib.sha256(canonical_json(scenario).encode("utf-8")).hexdigest()

    @staticmethod
    def _require_stage(
        state: ResearchState,
        stage: ResearchStage,
        command: DiscoveryCommand,
    ) -> None:
        if state.current_stage != stage:
            raise ValueError(f"{command.value} requires {stage.value} state")

    @staticmethod
    def _active_hypothesis(state: ResearchState) -> WorkingHypothesis:
        if state.active_working_hypothesis_id is None:
            raise ValueError("an active working hypothesis is required")
        return next(
            item
            for item in state.working_hypotheses
            if item.hypothesis_id == state.active_working_hypothesis_id
        )

    @staticmethod
    def _probe_count(state: ResearchState) -> int:
        return sum(item.probe_type is not None for item in state.observations)

    def _resolve_signal_number(
        self,
        scenario: DiscoveryScenario,
        state: ResearchState,
        requested: int | None,
    ) -> int:
        number = requested if requested is not None else self._probe_count(state) + 1
        if number < 1 or number > len(scenario.probe_signals):
            raise ValueError(f"signal number must be between 1 and {len(scenario.probe_signals)}")
        return number

    @staticmethod
    def _resolve_reformulation_number(
        scenario: DiscoveryScenario,
        state: ResearchState,
        requested: int | None,
    ) -> int:
        number = requested if requested is not None else len(state.working_hypotheses)
        if number < 1 or number > len(scenario.reformulations):
            raise ValueError(
                f"reformulation number must be between 1 and {len(scenario.reformulations)}"
            )
        return number

    @staticmethod
    def _next_hypothesis_id(state: ResearchState) -> str:
        known = {item.hypothesis_id for item in state.working_hypotheses}
        index = len(known) + 1
        while f"working-hypothesis-{index:02d}" in known:
            index += 1
        return f"working-hypothesis-{index:02d}"

    @staticmethod
    def _next_problem_id(state: ResearchState) -> str:
        known = {item.problem_id for item in state.problem_candidates}
        index = len(known) + 1
        while f"research-problem-{index:02d}" in known:
            index += 1
        return f"research-problem-{index:02d}"

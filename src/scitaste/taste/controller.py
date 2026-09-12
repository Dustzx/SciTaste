"""Training-free Scientific Taste Controller skeleton."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import StrEnum

from scitaste.schema.actions import ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.state.resources import remaining_budget
from scitaste.taste.critics import StageTasteCriticSuite, TasteCriticFinding
from scitaste.taste.retriever import TasteQuery, TasteRetrievalPolicy, TasteRetriever
from scitaste.taste.utility import UtilityPolicy


class NoViableActionError(ValueError):
    """Raised when all candidate actions violate the current resource budget."""


class TasteMode(StrEnum):
    INTRINSIC = "intrinsic"
    AUGMENTED = "augmented"


class TasteController:
    """Rank candidate actions without executing or mutating research state."""

    def __init__(
        self,
        *,
        policy: UtilityPolicy | None = None,
        seed: int = 0,
        mode: TasteMode = TasteMode.INTRINSIC,
        retriever: TasteRetriever | None = None,
        retrieval_limit: int = 3,
        precedent_weight: float = 0.25,
        utility_enabled: bool = True,
        critics_enabled: bool = True,
        critic_suite: StageTasteCriticSuite | None = None,
    ) -> None:
        self.policy = policy or UtilityPolicy()
        self.seed = seed
        self.mode = mode
        self.retriever = retriever
        self.retrieval_limit = retrieval_limit
        self.precedent_weight = precedent_weight
        self.utility_enabled = utility_enabled
        self.critics_enabled = critics_enabled
        self.critic_suite = critic_suite or StageTasteCriticSuite()
        if mode == TasteMode.AUGMENTED and retriever is None:
            raise ValueError("augmented taste mode requires a TasteRetriever")
        if not critics_enabled and critic_suite is not None:
            raise ValueError("a custom critic suite requires critics_enabled")

    def decide(
        self,
        *,
        state: ResearchState,
        candidate_actions: Sequence[ResearchAction],
        budget: ResourceBudget | None = None,
    ) -> ResearchDecision:
        actions = list(candidate_actions)
        if not actions:
            raise ValueError("candidate_actions must not be empty")
        if len({action.action_id for action in actions}) != len(actions):
            raise ValueError("candidate action ids must be unique")

        active_budget = budget or remaining_budget(state.resource_budget, state.resource_usage)
        assessments = [self.policy.assess(action, active_budget) for action in actions]
        feasible = [item for item in assessments if item.feasible]
        if not feasible:
            details = "; ".join(reason for item in assessments for reason in item.reasons)
            raise NoViableActionError(f"all candidate actions exceed budget: {details}")

        retrieved = self._retrieve(state, actions)
        critic_findings = self.critic_suite.review(state, actions) if self.critics_enabled else ()
        critic_adjustments = {action.action_id: 0.0 for action in actions}
        for finding in critic_findings:
            critic_adjustments[finding.action_id] += finding.score_adjustment
        precedent_bonus = {action.action_id: 0.0 for action in actions}
        for result in retrieved:
            for action in actions:
                if result.case.preferred_action in {action.action_id, action.type.value}:
                    precedent_bonus[action.action_id] += (
                        self.precedent_weight * result.score * result.case.confidence
                    )
        adjusted_scores = {
            item.action_id: (
                (item.score if self.utility_enabled else 0.0)
                + precedent_bonus[item.action_id]
                + critic_adjustments[item.action_id]
            )
            for item in assessments
            if item.feasible
        }
        ranked = sorted(
            feasible,
            key=lambda item: (-adjusted_scores[item.action_id], self._tie_break(item.action_id)),
        )
        selected_assessment = ranked[0]
        selected = next(
            action for action in actions if action.action_id == selected_assessment.action_id
        )
        confidence = self._confidence([adjusted_scores[item.action_id] for item in ranked])
        score_text = ", ".join(
            f"{item.action_id}={adjusted_scores[item.action_id]:.3f}"
            if item.feasible
            else f"{item.action_id}=infeasible"
            for item in assessments
        )
        precedent_text = (
            f" Retrieved taste precedents: {', '.join(item.case.case_id for item in retrieved)}."
            if retrieved
            else ""
        )
        critic_text = _critic_rationale(critic_findings)
        utility_text = (
            "configurable scientific-value and resource-cost weights"
            if self.utility_enabled
            else "a utility-neutral control policy"
        )
        rationale = (
            f"Selected {selected.type.value} using {utility_text}. "
            f"Candidate scores: {score_text}. "
            + "; ".join(selected_assessment.reasons)
            + precedent_text
            + critic_text
        )
        return ResearchDecision(
            stage=state.current_stage.value,
            state_snapshot_id=snapshot_id(state),
            candidate_actions=actions,
            retrieved_taste_cases=[item.case.case_id for item in retrieved],
            selected_action=selected,
            rationale=rationale,
            confidence=confidence,
            expected_cost=dict(selected.expected_cost),
            expected_value=dict(selected.expected_value),
            candidate_scores={
                item.action_id: adjusted_scores[item.action_id] if item.feasible else None
                for item in assessments
            },
        )

    def _retrieve(self, state: ResearchState, actions: list[ResearchAction]):
        if self.mode == TasteMode.INTRINSIC:
            return []
        assert self.retriever is not None  # guarded by __init__
        query = TasteQuery(
            text=" ".join([state.research_direction, *(action.description for action in actions)]),
            policy=TasteRetrievalPolicy.STAGE_CONDITIONED,
            stage=state.current_stage.value,
            candidate_action_types=[action.type.value for action in actions],
            domain_tags=[state.target_domain],
            venue=state.target_venue,
        )
        return self.retriever.retrieve(query, limit=self.retrieval_limit)

    def _tie_break(self, action_id: str) -> str:
        value = f"{self.seed}:{action_id}".encode()
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _confidence(ranked_scores: list[float]) -> float:
        if len(ranked_scores) == 1:
            return 0.75
        margin = ranked_scores[0] - ranked_scores[1]
        scale = max(abs(ranked_scores[0]), abs(ranked_scores[1]), 1.0)
        return round(min(0.99, 0.5 + 0.49 * max(0.0, margin) / scale), 4)


def _critic_rationale(findings: tuple[TasteCriticFinding, ...]) -> str:
    if not findings:
        return ""
    rendered = ", ".join(
        f"{item.action_id}[{item.critic_id}:{item.code}={item.score_adjustment:.2f}]"
        for item in sorted(
            findings,
            key=lambda item: (item.action_id, item.critic_id, item.code),
        )
    )
    return f" Taste critics: {rendered}."

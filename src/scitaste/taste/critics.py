"""Stage-specific, deterministic critics for research-action selection.

These critics are advisory score modifiers. They never replace hard resource,
evidence-integrity, or execution-safety gates, which remain common to every
experimental condition.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchStage, ResearchState
from scitaste.state.transitions import TransitionError, next_stage


class TasteCriticDimension(StrEnum):
    WRONG_LEVEL = "wrong_level"
    READINESS = "readiness"
    DIAGNOSTICITY = "diagnosticity"
    CLAIM_DISCIPLINE = "claim_discipline"


class TasteCriticFinding(BaseModel):
    """One auditable critic contribution to an action score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    critic_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    action_id: str = Field(min_length=1)
    dimension: TasteCriticDimension
    score_adjustment: float = Field(le=0.0, ge=-10.0, allow_inf_nan=False)
    message: str = Field(min_length=1, max_length=1_000)


class TasteCritic(Protocol):
    critic_id: str

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]: ...


_REACHABLE_STAGES: dict[ResearchStage, frozenset[ResearchStage]] = {
    ResearchStage.DISCOVERY: frozenset(
        {ResearchStage.DISCOVERY, ResearchStage.PROBLEM_FORMULATION}
    ),
    ResearchStage.PROBLEM_FORMULATION: frozenset(
        {ResearchStage.PROBLEM_FORMULATION, ResearchStage.IDEATION}
    ),
    ResearchStage.IDEATION: frozenset({ResearchStage.IDEATION, ResearchStage.PILOT}),
    ResearchStage.PILOT: frozenset({ResearchStage.PILOT, ResearchStage.EVIDENCE}),
    ResearchStage.EVIDENCE: frozenset(
        {
            ResearchStage.EVIDENCE,
            ResearchStage.PROBLEM_FORMULATION,
            ResearchStage.COMMUNICATION,
        }
    ),
    ResearchStage.COMMUNICATION: frozenset(
        {ResearchStage.COMMUNICATION, ResearchStage.REVIEW, ResearchStage.EVIDENCE}
    ),
    ResearchStage.REVIEW: frozenset(
        {
            ResearchStage.REVIEW,
            ResearchStage.EVIDENCE,
            ResearchStage.COMMUNICATION,
            ResearchStage.PROBLEM_FORMULATION,
        }
    ),
    ResearchStage.COMPLETE: frozenset({ResearchStage.COMPLETE}),
}


class WrongLevelTasteCritic:
    """Penalize actions that jump outside the current research-stage neighborhood."""

    critic_id = "wrong-level"

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]:
        findings: list[TasteCriticFinding] = []
        reachable = _REACHABLE_STAGES[state.current_stage]
        for action in actions:
            try:
                destination = next_stage(action.type, from_stage=state.current_stage)
            except TransitionError:
                destination = None
            if destination is not None and destination in reachable:
                continue
            findings.append(
                TasteCriticFinding(
                    critic_id=self.critic_id,
                    code="stage-jump",
                    action_id=action.action_id,
                    dimension=TasteCriticDimension.WRONG_LEVEL,
                    score_adjustment=-2.0,
                    message=(
                        f"{action.type.value} does not address the current "
                        f"{state.current_stage.value} decision level"
                    ),
                )
            )
        return tuple(findings)


class ReadinessTasteCritic:
    """Penalize commitment actions whose state prerequisites are absent."""

    critic_id = "readiness"

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]:
        findings: list[TasteCriticFinding] = []
        for action in actions:
            missing = _missing_readiness(state, action.type)
            if missing is None:
                continue
            findings.append(
                TasteCriticFinding(
                    critic_id=self.critic_id,
                    code="missing-prerequisite",
                    action_id=action.action_id,
                    dimension=TasteCriticDimension.READINESS,
                    score_adjustment=-1.5,
                    message=missing,
                )
            )
        return tuple(findings)


class DiagnosticityTasteCritic:
    """Prefer uncertainty-reducing actions before irreversible commitment."""

    critic_id = "diagnosticity"
    _COMMITMENT = frozenset(
        {
            MetaAction.FORMULATE_PROBLEM,
            MetaAction.IDEATE,
            MetaAction.SELECT_IDEA,
            MetaAction.ADVANCE,
            MetaAction.BUILD_STORY,
            MetaAction.WRITE,
        }
    )
    _DIAGNOSTIC = frozenset(
        {
            MetaAction.PROBE,
            MetaAction.RE_PROBE,
            MetaAction.REPRODUCE,
            MetaAction.ADD_ANALYSIS,
            MetaAction.ADD_BASELINE,
        }
    )

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]:
        if not any(action.type in self._DIAGNOSTIC for action in actions):
            return ()
        if _decision_uncertainty_is_low(state):
            return ()
        return tuple(
            TasteCriticFinding(
                critic_id=self.critic_id,
                code="premature-commitment",
                action_id=action.action_id,
                dimension=TasteCriticDimension.DIAGNOSTICITY,
                score_adjustment=-1.0,
                message="a diagnostic alternative can reduce unresolved uncertainty first",
            )
            for action in actions
            if action.type in self._COMMITMENT
        )


class ClaimDisciplineTasteCritic:
    """Penalize communication commitment while material claims lack support."""

    critic_id = "claim-discipline"
    _COMMUNICATION_COMMITMENT = frozenset(
        {MetaAction.BUILD_STORY, MetaAction.WRITE, MetaAction.DESIGN_FIGURE}
    )

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]:
        unresolved = [
            claim.claim_id
            for claim in state.claims
            if claim.status not in {"supported", "partially_supported"}
        ]
        if not unresolved:
            return ()
        detail = ", ".join(sorted(unresolved)[:5])
        return tuple(
            TasteCriticFinding(
                critic_id=self.critic_id,
                code="unsupported-claim",
                action_id=action.action_id,
                dimension=TasteCriticDimension.CLAIM_DISCIPLINE,
                score_adjustment=-1.25,
                message=f"communication would commit before resolving claims: {detail}",
            )
            for action in actions
            if action.type in self._COMMUNICATION_COMMITMENT
        )


class StageTasteCriticSuite:
    """The fixed training-free critic family used by the v1 controller."""

    def __init__(self, critics: Sequence[TasteCritic] | None = None) -> None:
        self.critics: tuple[TasteCritic, ...] = tuple(
            critics
            or (
                WrongLevelTasteCritic(),
                ReadinessTasteCritic(),
                DiagnosticityTasteCritic(),
                ClaimDisciplineTasteCritic(),
            )
        )
        critic_ids = [critic.critic_id for critic in self.critics]
        if len(critic_ids) != len(set(critic_ids)):
            raise ValueError("taste critic IDs must be unique")

    def review(
        self,
        state: ResearchState,
        actions: Sequence[ResearchAction],
    ) -> tuple[TasteCriticFinding, ...]:
        findings = tuple(
            finding for critic in self.critics for finding in critic.review(state, actions)
        )
        known = {action.action_id for action in actions}
        if any(finding.action_id not in known for finding in findings):
            raise ValueError("taste critic returned a finding for an unknown action")
        return findings


def _missing_readiness(state: ResearchState, action: MetaAction) -> str | None:
    if action is MetaAction.FORMULATE_PROBLEM and not state.observations:
        return "problem formulation has no registered observation"
    if action is MetaAction.IDEATE and not state.problem_candidates:
        return "ideation has no registered research problem"
    if action is MetaAction.SELECT_IDEA and not state.candidate_ideas:
        return "idea selection has no candidate portfolio"
    if action in {MetaAction.PILOT, MetaAction.EXPERIMENT, MetaAction.ADVANCE} and not (
        state.active_idea_id or state.current_experiment_plan
    ):
        return "experimental commitment has no active idea or experiment plan"
    if action in {
        MetaAction.BUILD_STORY,
        MetaAction.WRITE,
        MetaAction.DESIGN_FIGURE,
        MetaAction.REVIEW,
    } and (not state.claims or not state.evidence_graph.items):
        return "communication has no registered claim-and-evidence pair"
    if (
        action
        in {
            MetaAction.RESPOND,
            MetaAction.REJECT_CONCERN_WITH_EVIDENCE,
            MetaAction.DEFER_FUTURE_WORK,
        }
        and not state.reviewer_concerns
    ):
        return "review response has no registered reviewer concern"
    return None


def _decision_uncertainty_is_low(state: ResearchState) -> bool:
    active = next(
        (
            item
            for item in state.working_hypotheses
            if item.hypothesis_id == state.active_working_hypothesis_id
        ),
        None,
    )
    if active is not None:
        return active.confidence >= 0.8 and not active.contradicting_evidence_ids
    reproducible = [item for item in state.observations if item.reproducible is True]
    return bool(reproducible) and all((item.stability or 0.0) >= 0.8 for item in reproducible)


__all__ = [
    "ClaimDisciplineTasteCritic",
    "DiagnosticityTasteCritic",
    "ReadinessTasteCritic",
    "StageTasteCriticSuite",
    "TasteCritic",
    "TasteCriticDimension",
    "TasteCriticFinding",
    "WrongLevelTasteCritic",
]

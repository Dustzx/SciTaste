"""Decision-driven, nonlinear state transitions."""

from __future__ import annotations

from scitaste.schema.actions import MetaAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import (
    ProjectStatus,
    ResearchStage,
    ResearchState,
    StateTransition,
)

ACTION_STAGE: dict[MetaAction, ResearchStage] = {
    MetaAction.SEARCH: ResearchStage.DISCOVERY,
    MetaAction.FORM_INTUITION: ResearchStage.DISCOVERY,
    MetaAction.FORM_WORKING_HYPOTHESIS: ResearchStage.DISCOVERY,
    MetaAction.PROBE: ResearchStage.DISCOVERY,
    MetaAction.VALIDATE_HYPOTHESIS: ResearchStage.DISCOVERY,
    MetaAction.REFORMULATE_HYPOTHESIS: ResearchStage.DISCOVERY,
    MetaAction.SPLIT_HYPOTHESIS: ResearchStage.DISCOVERY,
    MetaAction.DISCARD_HYPOTHESIS: ResearchStage.DISCOVERY,
    MetaAction.RE_PROBE: ResearchStage.DISCOVERY,
    MetaAction.REPRODUCE: ResearchStage.DISCOVERY,
    MetaAction.FORMULATE_PROBLEM: ResearchStage.PROBLEM_FORMULATION,
    MetaAction.PIVOT: ResearchStage.PROBLEM_FORMULATION,
    MetaAction.DROP: ResearchStage.DISCOVERY,
    MetaAction.IDEATE: ResearchStage.IDEATION,
    MetaAction.SELECT_IDEA: ResearchStage.PILOT,
    MetaAction.PILOT: ResearchStage.PILOT,
    MetaAction.ADVANCE: ResearchStage.PILOT,
    MetaAction.EXPERIMENT: ResearchStage.EVIDENCE,
    MetaAction.ANALYZE: ResearchStage.EVIDENCE,
    MetaAction.COLLECT_EVIDENCE: ResearchStage.EVIDENCE,
    MetaAction.REFINE: ResearchStage.EVIDENCE,
    MetaAction.ADD_EXPERIMENT: ResearchStage.EVIDENCE,
    MetaAction.ADD_BASELINE: ResearchStage.EVIDENCE,
    MetaAction.ADD_ANALYSIS: ResearchStage.EVIDENCE,
    MetaAction.REVISE_METHOD: ResearchStage.EVIDENCE,
    MetaAction.NARROW_CLAIM: ResearchStage.COMMUNICATION,
    MetaAction.BUILD_STORY: ResearchStage.COMMUNICATION,
    MetaAction.WRITE: ResearchStage.COMMUNICATION,
    MetaAction.DESIGN_FIGURE: ResearchStage.COMMUNICATION,
    MetaAction.REVIEW: ResearchStage.REVIEW,
    MetaAction.RESPOND: ResearchStage.REVIEW,
    MetaAction.STOP: ResearchStage.COMPLETE,
}


class TransitionError(ValueError):
    """Raised when a decision cannot be replayed against the supplied state."""


def next_stage(action: MetaAction) -> ResearchStage:
    try:
        return ACTION_STAGE[action]
    except KeyError as exc:  # pragma: no cover - enum/map completeness guard
        raise TransitionError(f"no transition registered for {action}") from exc


def apply_transition(state: ResearchState, decision: ResearchDecision) -> ResearchState:
    """Return the next state and append both decision and transition audit records."""

    if state.status == ProjectStatus.COMPLETED:
        raise TransitionError("a completed project cannot transition")
    if decision.stage != state.current_stage.value:
        raise TransitionError(
            f"decision stage {decision.stage!r} does not match state stage "
            f"{state.current_stage.value!r}"
        )
    if any(item.decision_id == decision.decision_id for item in state.decision_history):
        raise TransitionError(f"decision {decision.decision_id!r} was already applied")
    if decision.state_snapshot_id != snapshot_id(state):
        raise TransitionError("decision does not reference the current state snapshot")

    updated = state.model_copy(deep=True)
    destination = next_stage(decision.selected_action.type)
    revision = state.revision + 1
    updated.revision = revision
    updated.current_stage = destination
    if decision.selected_action.type == MetaAction.STOP:
        updated.status = ProjectStatus.COMPLETED

    updated.decision_history.append(decision.model_copy(deep=True))
    updated.transition_history.append(
        StateTransition(
            transition_id=f"trn-{revision:06d}-{decision.decision_id}",
            decision_id=decision.decision_id,
            action_type=decision.selected_action.type,
            from_stage=state.current_stage,
            to_stage=destination,
            state_revision=revision,
        )
    )
    return updated

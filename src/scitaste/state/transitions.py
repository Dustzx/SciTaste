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
    MetaAction.CLARIFY_EXISTING_TEXT: ResearchStage.COMMUNICATION,
    MetaAction.CITE_EXISTING_EVIDENCE: ResearchStage.COMMUNICATION,
    MetaAction.ACKNOWLEDGE_LIMITATION: ResearchStage.COMMUNICATION,
    MetaAction.CORRECT_ERROR: ResearchStage.COMMUNICATION,
    MetaAction.REJECT_CONCERN_WITH_EVIDENCE: ResearchStage.REVIEW,
    MetaAction.DEFER_FUTURE_WORK: ResearchStage.COMMUNICATION,
    MetaAction.BUILD_STORY: ResearchStage.COMMUNICATION,
    MetaAction.WRITE: ResearchStage.COMMUNICATION,
    MetaAction.DESIGN_FIGURE: ResearchStage.COMMUNICATION,
    MetaAction.REVIEW: ResearchStage.REVIEW,
    MetaAction.RESPOND: ResearchStage.REVIEW,
    MetaAction.STOP: ResearchStage.COMPLETE,
}


class TransitionError(ValueError):
    """Raised when a decision cannot be replayed against the supplied state."""


def next_stage(
    action: MetaAction,
    *,
    from_stage: ResearchStage | None = None,
) -> ResearchStage:
    if action == MetaAction.ADVANCE and from_stage == ResearchStage.PILOT:
        return ResearchStage.EVIDENCE
    if action == MetaAction.ADVANCE and from_stage == ResearchStage.EVIDENCE:
        return ResearchStage.COMMUNICATION
    if action == MetaAction.REPRODUCE and from_stage == ResearchStage.EVIDENCE:
        return ResearchStage.EVIDENCE
    try:
        return ACTION_STAGE[action]
    except KeyError as exc:  # pragma: no cover - enum/map completeness guard
        raise TransitionError(f"no transition registered for {action}") from exc


def apply_transition(state: ResearchState, decision: ResearchDecision) -> ResearchState:
    """Return the next state and append both decision and transition audit records."""

    if state.status in {ProjectStatus.COMPLETED, ProjectStatus.DROPPED}:
        raise TransitionError(f"a {state.status.value.lower()} project cannot transition")
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
    destination = next_stage(decision.selected_action.type, from_stage=state.current_stage)
    revision = state.revision + 1
    updated.revision = revision
    updated.current_stage = destination
    if decision.selected_action.type == MetaAction.STOP:
        updated.status = ProjectStatus.COMPLETED
    elif decision.selected_action.type == MetaAction.DROP:
        updated.status = ProjectStatus.DROPPED

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

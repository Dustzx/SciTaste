"""Route only experiment-allocation decisions to an explicit learned Taste head."""

from scitaste.schema.actions import MetaAction


class AllocationTasteToolController:
    """Development router; no general/full-Taste or task-transfer validity claim."""

    def __init__(self, *, base, allocation, idea_revision):
        self.base = base
        self.allocation = allocation
        self.idea_revision = idea_revision

    def decide(self, *, state, candidate_actions):
        actions = tuple(candidate_actions)
        allocation_choice = {action.type for action in actions} == {
            MetaAction.EXPERIMENT,
            MetaAction.STOP,
        } and all(
            action.parameters.get("tool") in {"Run Experiment", "Final Answer"}
            for action in actions
        )
        if allocation_choice:
            return self.allocation.decide(
                state=state,
                candidate_actions=actions,
                current_idea_revision=self.idea_revision,
            )
        return self.base.decide(state=state, candidate_actions=actions)

from types import SimpleNamespace

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.research_tool_policy import AllocationTasteToolController


def test_allocation_policy_cannot_claim_review_or_method_design_decisions():
    base_calls, policy_calls = [], []
    router = AllocationTasteToolController(
        base=SimpleNamespace(decide=lambda **kwargs: base_calls.append(kwargs) or "base"),
        allocation=SimpleNamespace(decide=lambda **kwargs: policy_calls.append(kwargs) or "taste"),
        idea_revision="bound-idea",
    )
    stop = ResearchAction(
        action_id="stop",
        type=MetaAction.STOP,
        description="Stop",
        parameters={"tool": "Final Answer"},
    )
    for kind, tool, expected in (
        (MetaAction.EXPERIMENT, "Run Experiment", "taste"),
        (MetaAction.REVIEW, "Review Implementation", "base"),
        (MetaAction.CORRECT_ERROR, "Write File", "base"),
        (MetaAction.SEARCH, "Read File", "base"),
        (MetaAction.EXPERIMENT, "Unsupported Tool", "base"),
    ):
        candidate = ResearchAction(
            action_id="candidate",
            type=kind,
            description="Candidate",
            parameters={"tool": tool},
        )
        assert router.decide(state="state", candidate_actions=(candidate, stop)) == expected
    assert len(policy_calls) == 1
    assert policy_calls[0]["current_idea_revision"] == "bound-idea"
    assert len(base_calls) == 4

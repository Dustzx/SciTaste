import copy
from types import SimpleNamespace

import pytest

from scitaste.evidence.research_reasoning import ResearchReasoningFrame
from scitaste.taste.inquiry_transfer import (
    InquiryTransfer,
    inquiry_context,
    inquiry_retrieval_query,
    validate_inquiry_transfer,
    validate_workspace_inquiry,
)


def packet():
    return {
        "version": "reviewed-conditional-v1",
        "execution_authorized": False,
        "applicability_established": False,
        "cases": [
            {
                "case_id": "selection",
                "complete_case_sha256": "a" * 64,
                "applicability_conditions": [
                    "validation is available",
                    "selection may change rankings",
                ],
                "failure_conditions": [
                    "test labels used for selection",
                    "no independent evaluation",
                ],
            }
        ],
    }


def frame():
    return ResearchReasoningFrame.model_validate(
        {
            "question": "Does selection change rankings?",
            "explanatory_gap": "Ranking effects are unknown",
            "scientific_importance": "Avoid unsupported benchmark claims",
            "explanations": [
                {
                    "hypothesis_id": name,
                    "mechanism": name,
                    "falsification": "Measure opposite ranking",
                    "applicability_boundary": "This dataset",
                }
                for name in ("selection-artifact", "stable-ranking")
            ],
            "probes": [
                {
                    "probe_id": "ranking-probe",
                    "intervention": "Compare predeclared selection rules",
                    "predictions": [
                        {"hypothesis_id": name, "observable_prediction": prediction}
                        for name, prediction in (
                            ("selection-artifact", "Rankings reverse"),
                            ("stable-ranking", "Rankings persist"),
                        )
                    ],
                    "controls_and_confounders": "Same model pool and data",
                    "cost_and_feasibility": "Reuse candidate predictions",
                    "decision_relevance": "Decides whether rankings support method choice",
                    "branches": [
                        {
                            "kind": kind,
                            "observed_pattern": kind,
                            "interpretation": "Unverified explanation",
                            "next_question": "Would an independent dataset resolve this?",
                            "next_action": "stop",
                            "action_rationale": "Stop if no discriminating evidence is feasible",
                        }
                        for kind in ("diagnostic", "inconclusive")
                    ],
                }
            ],
            "preferred_probe_id": "ranking-probe",
            "selection_reason": "Test a missing premise",
            "stopping_condition": "Probe is inconclusive",
            "revision_reason": "Initial design",
            "taste_transfer": "Question, not borrowed recipe",
        }
    )


def proposal():
    return InquiryTransfer.model_validate(
        {
            "case_id": "selection",
            "complete_case_sha256": "a" * 64,
            "premises": [
                {
                    "kind": kind,
                    "condition": text,
                    "status": "unknown",
                    "interpretation": "Current evidence does not establish this premise",
                }
                for kind, key in (
                    ("applicability", "applicability_conditions"),
                    ("failure", "failure_conditions"),
                )
                for text in packet()["cases"][0][key]
            ],
            "question": "Does selection change rankings?",
            "probe_id": "ranking-probe",
            "tested_conditions": ["selection may change rankings"],
        }
    )


def test_unknown_premise_supports_inquiry_but_never_recipe_or_execution():
    original = packet()
    before = copy.deepcopy(original)
    context = inquiry_context(original)
    assert original == before
    assert context["cases"] == original["cases"]
    accepted = validate_inquiry_transfer(proposal(), context=context, frame=frame(), sources={})
    assert not accepted.recipe_eligible and not accepted.execution_authorized
    with pytest.raises(ValueError, match="cannot establish recipe"):
        validate_inquiry_transfer(
            proposal().model_copy(update={"recipe_eligible": True}),
            context=context,
            frame=frame(),
            sources={},
        )


@pytest.mark.parametrize(
    "mutation,error",
    [
        ({"complete_case_sha256": "b" * 64}, "exact visible source"),
        ({"probe_id": "invented"}, "declared discriminating probe"),
        ({"tested_conditions": ("invented premise",)}, "visible source conditions"),
        ({"premises": proposal().premises[:-1]}, "every exact source premise"),
    ],
)
def test_closed_source_and_probe_bindings(mutation, error):
    with pytest.raises(ValueError, match=error):
        validate_inquiry_transfer(
            proposal().model_copy(update=mutation),
            context=inquiry_context(packet()),
            frame=frame(),
            sources={},
        )


def test_literature_or_invented_quote_is_not_current_evidence():
    value = proposal().model_dump()
    value["premises"][0]["status"] = "observed"
    value["premises"][0]["evidence"] = [{"source_id": "r1", "quote": "Validation is available"}]
    candidate = InquiryTransfer.model_validate(value)
    with pytest.raises(ValueError, match="quote is absent"):
        validate_inquiry_transfer(
            candidate, context=packet(), frame=frame(), sources={"r1": ("Training is available",)}
        )
    validate_inquiry_transfer(
        candidate,
        context=packet(),
        frame=frame(),
        sources={"r1": ("Validation is available in the supplied assets",)},
    )
    with pytest.raises(ValueError, match="Tool failure"):
        validate_inquiry_transfer(
            candidate,
            context=packet(),
            frame=frame(),
            sources={"r1": ("Validation is available in the supplied assets",)},
            failed_source_ids=frozenset({"r1"}),
        )


def test_inquiry_projection_retains_whole_boundaries_or_explicitly_omits_case():
    original = packet()
    original["cases"][0]["conditional_lesson"] = "Long source principle " * 1000
    value = inquiry_context(original, max_bytes=2000)
    assert value["cases"] == []
    assert value["omitted_case_ids"] == ["selection"]
    assert value["omitted_case_count"] == 1
    assert len(original["cases"]) == 1
    with pytest.raises(ValueError, match="interpretation boundary"):
        inquiry_context(original, max_bytes=50)


def test_workspace_inquiry_uses_committed_observations_and_failure_boundaries():
    state = SimpleNamespace(
        executor_context={"research_reasoning": {"frame": frame().model_dump()}}
    )
    value = proposal().model_dump()
    value["premises"][0].update(
        status="observed", evidence=[{"source_id": "r1", "quote": "Validation exists"}]
    )
    candidate = InquiryTransfer.model_validate(value)
    result = {"result_id": "r1", "status": "SUCCEEDED", "observations": ["Validation exists"]}
    validate_workspace_inquiry(
        candidate, context=packet(), state=state, history=[{"result": result}]
    )
    with pytest.raises(ValueError, match="Tool failure"):
        validate_workspace_inquiry(
            candidate,
            context=packet(),
            state=state,
            history=[{"result": {**result, "status": "FAILED"}}],
        )
    state.executor_context["research_reasoning"]["source_bindings"] = {"r1": "different"}
    with pytest.raises(ValueError, match="identity was reused"):
        validate_workspace_inquiry(
            candidate, context=packet(), state=state, history=[{"result": result}]
        )


def test_question_aware_retrieval_is_opt_in_and_keeps_whole_fields():
    state = SimpleNamespace(
        research_direction="Initial topic",
        executor_context={"research_reasoning": {"frame": frame().model_dump()}},
    )
    query = inquiry_retrieval_query(state)
    assert "Initial topic" in query and frame().question in query
    assert frame().explanatory_gap in query
    state.executor_context["research_reasoning"]["frame"]["question"] = "x" * 15000
    assert "x" not in inquiry_retrieval_query(state)

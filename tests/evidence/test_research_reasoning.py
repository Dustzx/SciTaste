"""The reasoning loop is grounded and usable, without conferring scientific truth."""

import json

import pytest

from scitaste.evidence.research_reasoning import (
    ResearchReasoningFrame,
    ResearchReasoningUpdateRejected,
    apply_research_reasoning,
    grounding_errors,
    seed_research_reasoning,
)
from scitaste.state.research_state import ResearchState


def frame(**updates):
    value = {
        "question": "Is a small-data gain regularization or a scale artifact?",
        "explanatory_gap": "Aggregate accuracy does not distinguish the mechanisms.",
        "scientific_importance": "Avoid scaling a method whose claimed mechanism is absent.",
        "explanations": [
            {
                "hypothesis_id": name,
                "mechanism": mechanism,
                "falsification": prediction,
                "applicability_boundary": "Same splits and selected hyperparameters only",
            }
            for name, mechanism, prediction in (
                ("h1", "Regularization", "Gain disappears under matched regularization"),
                ("h2", "Scale correction", "Gain disappears when input scales are matched"),
            )
        ],
        "probes": [
            {
                "probe_id": "p1",
                "intervention": "Match regularization, vary only input scaling",
                "predictions": [
                    {"hypothesis_id": "h1", "observable_prediction": "Gain persists"},
                    {"hypothesis_id": "h2", "observable_prediction": "Gain disappears"},
                ],
                "controls_and_confounders": "Paired splits, training-only transforms",
                "cost_and_feasibility": "Two CPU fits; no new assets",
                "decision_relevance": "Separates explanations before model scaling",
                "branches": [
                    {
                        "kind": "diagnostic",
                        "observed_pattern": "Gain disappears only after scale matching",
                        "interpretation": "Consistent with h2, subject to power and confounds",
                        "next_question": "Which scale ratios predict the effect?",
                        "next_action": "expand",
                        "action_rationale": "Measure an applicability boundary",
                    },
                    {
                        "kind": "inconclusive",
                        "observed_pattern": "Uncertainty includes both predictions",
                        "interpretation": "Neither explanation resolved",
                        "next_question": "Would more data change the decision?",
                        "next_action": "stop",
                        "action_rationale": "Stop if the added evidence exceeds the budget",
                    },
                ],
            }
        ],
        "preferred_probe_id": "p1",
        "selection_reason": "Discriminating evidence is more useful than another aggregate score",
        "stopping_condition": "No affordable experiment distinguishes remaining alternatives",
        "revision_reason": "Initial provisional design",
        "taste_transfer": "Use matched controls; no admitted Taste lesson is assumed",
    }
    value.update(updates)
    return ResearchReasoningFrame.model_validate(value)


def state():
    return ResearchState(project_id="p", research_direction="Research", target_domain="general")


def observation(status="SUCCEEDED"):
    return {
        "result": {
            "result_id": "r1",
            "status": status,
            "observations": ["Measured gap was zero in the matched scale condition."],
        }
    }


def revised(disposition="weaken"):
    return frame(
        evidence=[{"source_id": "r1", "quote": "Measured gap was zero"}],
        updates=[
            {
                "hypothesis_id": "h1",
                "evidence_ids": ["r1"],
                "disposition": disposition,
                "reasoning": "Condition-specific result questions the proposed mechanism",
                "remaining_uncertainty": "Replication and control validity unresolved",
            }
        ],
        question="Does scale ratio explain the boundary?",
        revision_reason="Measured boundary motivates a new question, not another score search",
    )


def test_grounded_revision_and_resume_preserve_model_only_authority():
    initial = apply_research_reasoning(state(), [], frame())
    updated = apply_research_reasoning(initial, [observation()], revised())
    record = updated.executor_context["research_reasoning"]
    assert record["frame"]["question"] == "Does scale ratio explain the boundary?"
    assert record["scientific_quality_established"] is False
    assert updated.claims == initial.claims == []
    assert updated.evidence_graph == initial.evidence_graph
    assert len(record["source_bindings"]["r1"]) == 64
    assert apply_research_reasoning(updated, [], revised()) is updated
    from scitaste.executor.state_handoff import inherit_state, scientific_context

    inherited = inherit_state(updated, {"state_id": "prior"}, updated.resource_budget)
    assert scientific_context(inherited)["research_reasoning"] == record


@pytest.mark.parametrize("fault", ["unknown-source", "wrong-quote", "identical-predictions"])
def test_rejects_ungrounded_or_non_discriminating_reasoning(fault):
    payload = revised().model_dump(mode="json")
    if fault == "unknown-source":
        assert grounding_errors(revised(), {})
        return
    if fault == "wrong-quote":
        payload["evidence"][0]["quote"] = "Invented positive result"
        with pytest.raises(ValueError, match="quote absent"):
            apply_research_reasoning(state(), [observation()], ResearchReasoningFrame(**payload))
    else:
        payload["probes"][0]["predictions"][1]["observable_prediction"] = "Gain persists"
        with pytest.raises(ValueError, match="different observable predictions"):
            ResearchReasoningFrame(**payload)


def test_failure_cannot_become_refutation_even_after_history_compaction():
    failed = apply_research_reasoning(state(), [observation("FAILED")], revised("unresolved"))
    with pytest.raises(ValueError, match="failure cannot establish"):
        apply_research_reasoning(failed, [], revised())


def test_same_id_cannot_silently_change_mechanism_or_discard_sources():
    previous = revised()
    assert "Reasoning cannot silently discard prior evidence anchors" in grounding_errors(
        frame(), {}, previous
    )
    payload = previous.model_dump(mode="json")
    payload["explanations"][0]["mechanism"] = "An entirely different mechanism"
    assert "Changed explanation requires a new identity" in grounding_errors(
        ResearchReasoningFrame(**payload), {"r1": ["Measured gap was zero"]}, previous
    )
    archived = frame(archived_evidence_ids=["r1"], revision_reason="Keep full source in trajectory")
    assert grounding_errors(archived, {}, previous) == []


def test_design_seed_is_bound_and_does_not_overwrite_evolved_state():
    seeded = seed_research_reasoning(
        state(), {"scientific_reasoning": revised().model_dump(mode="json")}, "a" * 64
    )
    record = seeded.executor_context["research_reasoning"]
    assert next(iter(record["source_bindings"])).startswith("design:" + "a" * 64)
    assert seed_research_reasoning(seeded, {}, "b" * 64) is seeded


def test_rejected_update_is_recoverable_without_mutating_canonical_state():
    initial = apply_research_reasoning(state(), [], frame())
    before = initial.model_dump_json()
    changed = frame().model_dump(mode="json")
    changed["explanations"][0]["mechanism"] = "A revised mechanism"
    with pytest.raises(ResearchReasoningUpdateRejected, match="new identity"):
        apply_research_reasoning(initial, [], ResearchReasoningFrame(**changed))
    assert initial.model_dump_json() == before
    assert apply_research_reasoning(initial, [], frame()) is initial


def test_source_identity_corruption_is_not_a_model_correction():
    initial = apply_research_reasoning(state(), [observation()], revised())
    corrupted = observation()
    corrupted["result"]["observations"] = ["Changed evidence"]
    updated = revised().model_copy(update={"revision_reason": "Attempt a new update"})
    with pytest.raises(ValueError, match="identity was reused") as caught:
        apply_research_reasoning(initial, [corrupted], updated)
    assert not isinstance(caught.value, ResearchReasoningUpdateRejected)


def test_new_scientific_design_requires_reasoning_but_legacy_design_remains_readable():
    from scitaste.model_nodes.research_design import (
        ResearchDesignInput,
        ResearchDesignNode,
        ResearchDesignProposal,
    )

    packet = ResearchDesignInput(
        idea_sha256="a" * 64,
        idea={},
        capabilities={},
        evidence={},
        objective="Find mechanism",
        scientific_reasoning_required=True,
    )
    proposal = ResearchDesignProposal.model_construct(
        idea_sha256="a" * 64,
        hypotheses=(),
        comparisons=(),
        studies=(),
        next_study_id="s",
        evidence_ids=(),
    )
    node = ResearchDesignNode()
    reasons = node._proposal_rejections(proposal, input_data=packet, context=None, policy=None)
    assert "Scientific planning requires competing explanations and outcome branches" in reasons
    legacy = packet.model_copy(update={"scientific_reasoning_required": False})
    assert node._proposal_rejections(proposal, input_data=legacy, context=None, policy=None) == [
        "Next study is absent from design"
    ]


def test_bound_study_transmits_reasoning_without_changing_legacy_instructions():
    from scitaste.executor.workspace_task import study_instructions
    from scitaste.model_nodes.research_design import (
        PlannedComparison,
        PlannedStudy,
        ResearchDesignProposal,
        StudyHypothesis,
    )

    # Other plan fields are irrelevant to this projection and tested by their own model.
    design = ResearchDesignProposal.model_construct(
        studies=(
            PlannedStudy.model_construct(
                study_id="s",
                hypothesis_ids=("h1", "h2"),
                comparison_ids=("c",),
                executor_id="scitaste-native-workspace",
            ),
        ),
        comparisons=(
            PlannedComparison.model_construct(
                comparison_id="c",
                treatment="Matched control",
                comparator="Original",
            ),
        ),
        hypotheses=tuple(
            StudyHypothesis(
                hypothesis_id=h.hypothesis_id,
                prediction=h.mechanism,
                falsification=h.falsification,
            )
            for h in frame().explanations
        ),
    )
    old = study_instructions(design, "s", "c", "treatment")
    assert "scientific_reasoning" not in old
    new = study_instructions(
        design.model_copy(update={"scientific_reasoning": frame()}), "s", "c", "treatment"
    )
    assert new.pop("scientific_reasoning") == frame().model_dump(mode="json")
    assert new == old


def test_reasoning_reaches_controller_and_only_selected_tool_executes(tmp_path):
    from scitaste.backends.base import PreferenceResponse
    from scitaste.executor.research_tools import ResearchToolEnvironment
    from scitaste.research_tool_loop import run_research_tool_loop
    from scitaste.taste.controller import TasteController

    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "model.py").write_text("x = 1\n")

    class Backend:
        name = "fixture"

        def rank(self, request):
            context = json.loads(request.decision_context)
            assert context["state"]["scientific_reasoning"]["preferred_probe_id"] == "p1"
            assert request.candidate_actions[0].parameters["scientific_probe_id"] == "p1"
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="tool-0-0",
                rationale="Inspect the control before modifying it",
                confidence=0.5,
                backend=self.name,
                model="fixture",
            )

    env = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Distinguish explanations",
        experiment=lambda _: pytest.fail("An unselected experiment must not execute"),
    )
    run_research_tool_loop(
        state=state(),
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        proposer=lambda *_: {
            "scientific_reasoning": frame().model_dump(mode="json"),
            "proposals": [
                {
                    "tool": "Read File",
                    "arguments": {"file_name": "model.py"},
                    "rationale": "Check matched control",
                    "scientific_probe_id": "p1",
                },
                {
                    "tool": "Write File",
                    "arguments": {"file_name": "model.py", "content": "x = 2\n"},
                    "rationale": "Revise the control",
                    "scientific_probe_id": "p1",
                },
            ],
        },
        environment=env,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=1,
        max_proposals=2,
    )
    assert (workspace / "model.py").read_text() == "x = 1\n"
    trajectory = json.loads((tmp_path / "loop/TRAJECTORY.jsonl").read_text())
    assert trajectory["proposal"]["scientific_reasoning"]["question"] == frame().question
    assert trajectory["selected"]["parameters"]["scientific_probe_id"] == "p1"

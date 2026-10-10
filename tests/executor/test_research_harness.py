import json
from typing import ClassVar

import pytest

from scitaste.backends.base import PreferenceResponse
from scitaste.executor.harness_tools import HarnessToolEnvironment
from scitaste.executor.research_harness import (
    NativeHarnessProfile,
    competitive_harness_binding,
    competitive_search_context,
    default_harness_binding,
    handoff_harness_binding,
    load_harness_binding,
)
from scitaste.research_tool_loop import ResearchToolProposal, run_research_tool_loop
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController


class Tool:
    description = "Test tool, not a scientific measurement"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["file_path"],
    }

    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def call(self, arguments, **kwargs):
        self.calls.append((self.name, arguments))
        return "raw observation"


def environment(path, *, authorized=True, isolated=True):
    path.mkdir(exist_ok=True)
    calls = []
    env = HarnessToolEnvironment(
        workspace=path,
        log_root=path / "tools",
        research_problem="Inspect research evidence",
        tool_map={name: Tool(name, calls) for name in ("Read", "Write", "Bash")},
        source_binding={"fixture": True},
        wall_seconds=60,
        research_harness_profile=NativeHarnessProfile(),
        project_id="p",
        execution_authorized=authorized,
        isolated_code=isolated,
    )
    return env, calls


def state():
    return ResearchState(project_id="p", research_direction="Research", target_domain="general")


def test_profile_binding_is_exact_and_legacy_is_not_upgraded():
    binding = default_harness_binding()
    assert load_harness_binding(binding).fingerprint == binding["sha256"]
    assert load_harness_binding(None) is None
    binding["profile"]["max_loaded_skills"] = 1
    with pytest.raises(ValueError, match="profile changed"):
        load_harness_binding(binding)


def test_competitive_search_is_explicit_and_does_not_upgrade_old_harness():
    new = competitive_harness_binding()
    profile = load_harness_binding(new)
    assert profile.schema_version == "4.0"
    assert competitive_search_context(profile)["max_refinement_panels"] == 1
    assert competitive_search_context(profile)["additional_model_calls"] == 0
    assert competitive_search_context(load_harness_binding(handoff_harness_binding())) is None
    assert competitive_search_context(load_harness_binding(default_harness_binding())) is None
    new["profile"]["max_public_refinement_panels"] = 2
    with pytest.raises(ValueError, match="profile changed"):
        load_harness_binding(new)


def test_model_advice_cannot_weaken_untrusted_code_boundary(tmp_path):
    env, calls = environment(tmp_path)
    proposal = ResearchToolProposal(
        tool="Bash",
        arguments={"file_path": "code.py"},
        rationale="Run the existing experiment",
        skill_id="controlled-experiment",
        verification_advice="direct_path",
    )
    action = env.research_harness.bind_action(proposal.action(env, 0), proposal.model_dump())
    binding = action.parameters["research_harness"]
    assert binding["verification"]["route"] == "full_preflight"
    assert binding["advice_rejected"]
    assert binding["execution_authority"] == "none"
    env.research_harness.isolated_code = False
    with pytest.raises(ValueError, match="isolated execution"):
        env.research_harness.guard_selected(state(), action)
    assert calls == []
    assert not list(env.research_harness.directory.glob("*.json"))


def test_unknown_optional_skill_is_rejected_without_losing_research_action(tmp_path):
    env, calls = environment(tmp_path)
    proposal = ResearchToolProposal(
        tool="Read",
        arguments={"file_path": "results.json"},
        rationale="Inspect retained results",
        skill_id="train-only-submission",
    )
    action = env.research_harness.bind_action(proposal.action(env, 0), proposal.model_dump())
    binding = action.parameters["research_harness"]
    assert binding["skill_id"] is None
    assert binding["skill_requested"] == "train-only-submission"
    assert binding["skill_rejected"] == "Unknown bound research skill"
    assert action.parameters["arguments"] == proposal.arguments
    env.research_harness.guard_selected(state(), action)
    assert calls == []  # Guard admission is not tool execution.
    env.research_harness.execution_authorized = False
    with pytest.raises(ValueError, match="authorization"):
        env.research_harness.guard_selected(state(), action)


@pytest.mark.parametrize("path", ["../outside.py", "data/inputs.py", "references/source.md"])
def test_inline_integrity_guards_remain_on_direct_path(tmp_path, path):
    env, calls = environment(tmp_path)
    proposal = ResearchToolProposal(
        tool="Write",
        arguments={"file_path": path, "content": "x = 1"},
        rationale="Propose an edit",
    )
    action = env.research_harness.bind_action(proposal.action(env, 0))
    assert action.parameters["research_harness"]["verification"]["route"] == "direct_path"
    with pytest.raises(ValueError):
        env.research_harness.guard_selected(state(), action)
    assert calls == []


def test_bound_skills_routes_and_single_proposal_use_real_controller(tmp_path):
    env, calls = environment(tmp_path)
    state = ResearchState(
        project_id="p", research_direction="Inspect results", target_domain="general"
    )

    class Backend:
        name = "fixture"

        def rank(self, request):
            assert len(request.candidate_actions) == 2  # A proposal and the real STOP alternative.
            assert (
                request.candidate_actions[0].parameters["research_harness"]["skill_id"]
                == "evidence-and-claims"
            )
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="tool-0-0",
                rationale="Read an existing terminal result",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    result = run_research_tool_loop(
        state=state,
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        proposer=lambda *_: {
            "proposals": [
                {
                    "tool": "Read",
                    "arguments": {"file_path": "results.json"},
                    "rationale": "Inspect existing evidence",
                    "skill_id": "evidence-and-claims",
                }
            ]
        },
        environment=env,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=1,
        max_proposals=2,
    )
    assert result["status"] == "turn-budget-exhausted"
    assert [name for name, _ in calls] == ["Read"]
    row = json.loads((tmp_path / "loop/TRAJECTORY.jsonl").read_text())
    assert row["result"]["data"]["tool_intelligence"]["credit_scope"] == "operational-only"
    assert row["result"]["data"]["scientific_efficacy_established"] is False
    summary = env.research_harness.summary()
    assert summary["routes"] == {"direct_path": 1}
    assert summary["additional_model_calls"] == summary["standalone_preflights"] == 0
    assert len(state.executor_context["research_harness"]["loaded_skills"]) == 2


def test_tampered_action_and_missing_owner_authority_are_rejected(tmp_path):
    env, _ = environment(tmp_path, authorized=False)
    proposal = ResearchToolProposal(
        tool="Read", arguments={"file_path": "results.json"}, rationale="Inspect"
    )
    action = env.research_harness.bind_action(proposal.action(env, 0))
    with pytest.raises(ValueError, match="authorization"):
        env.research_harness.guard_selected(state(), action)
    env.research_harness.execution_authorized = True
    changed = action.model_copy(
        update={"parameters": {**action.parameters, "arguments": {"file_path": "other.json"}}}
    )
    with pytest.raises(ValueError, match="verification binding"):
        env.research_harness.guard_selected(state(), changed)

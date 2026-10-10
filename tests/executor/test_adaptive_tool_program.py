"""Selected-action guards and failure-driven replanning, not scientific scores."""

import json
from typing import ClassVar

import pytest

from scitaste.executor.harness_tools import HarnessToolEnvironment
from scitaste.executor.research_harness import (
    AdaptiveHarnessProfile,
    NativeHarnessProfile,
    adaptive_harness_binding,
    default_harness_binding,
    load_harness_binding,
)
from scitaste.executor.research_tool_handler import ResearchToolActionHandler
from scitaste.research_tool_loop import ResearchToolProposal
from scitaste.state.research_state import ResearchState


class Tool:
    description = "Observable tool fixture"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["file_path"],
    }

    def __init__(self, name, calls, fail):
        self.name, self.calls, self.fail = name, calls, fail

    def call(self, args, **kwargs):
        self.calls.append(self.name)
        return "Tool error: observed failure" if self.name == self.fail else "observed result"


def env(root, fail=None, profile=None):
    calls = []
    e = HarnessToolEnvironment(
        workspace=root,
        log_root=root / "logs",
        research_problem="Scientific comparison",
        tool_map={n: Tool(n, calls, fail) for n in ("Write", "Bash", "Read")},
        source_binding={"test": True},
        wall_seconds=60,
        research_harness_profile=profile or AdaptiveHarnessProfile(),
        project_id="p",
        execution_authorized=True,
        isolated_code=True,
    )
    return e, calls


def program():
    return {
        "judgment": {
            "route": "compose",
            "scientific_interpretation_required_between_steps": False,
            "rationale": "Prepare, execute and inspect one predetermined comparison",
        },
        "steps": [
            {"tool": "Write", "arguments": {"file_path": "analysis.py", "content": "x=1"}},
            {"tool": "Bash", "arguments": {"file_path": "analysis.py"}},
            {"tool": "Read", "arguments": {"file_path": "results.json"}},
        ],
    }


def selected(e, arguments):
    p = ResearchToolProposal(
        tool="Execute Program",
        arguments=arguments,
        rationale="One controlled scientific comparison",
        skill_id="controlled-experiment",
    )
    return e.research_harness.bind_action(p.action(e, 0), p.model_dump())


def execute(e, action):
    state = ResearchState(project_id="p", research_direction="Research", target_domain="general")
    return ResearchToolActionHandler(project_id="p", environment=e)(state, action)


def test_preserves_legacy_profile_and_requires_explicit_successor(tmp_path):
    legacy = default_harness_binding()
    assert "tool_composition" not in legacy["profile"]
    assert load_harness_binding(legacy).model_dump(
        mode="json"
    ) == NativeHarnessProfile().model_dump(mode="json")
    assert load_harness_binding(adaptive_harness_binding()).profile_id.endswith("v2")
    e, _ = env(tmp_path, profile=NativeHarnessProfile())
    with pytest.raises(ValueError, match="not enabled"):
        selected(e, program())


def test_real_handler_executes_every_guard_without_extra_model_call(tmp_path):
    e, calls = env(tmp_path)
    result = execute(e, selected(e, program()))
    assert result.status == "SUCCEEDED"
    assert calls == ["Write", "Bash", "Read"]
    assert result.data["executed_atomic_tools"] == 3
    assert result.data["additional_model_calls"] == 0
    assert result.data["scientific_efficacy_established"] is False
    summary = e.research_harness.summary()
    assert summary["composed_programs"] == 1
    assert summary["atomic_actions_admitted"] == 3
    assert len(list((tmp_path / "logs/research_harness").glob("*.json"))) == 4
    assert all(
        json.loads(p.read_text())["selected_binding"]["execution_authority"] == "none"
        for p in (tmp_path / "logs/research_harness").glob("*.json")
    )


def test_failure_halts_dependents_and_returns_to_scientific_controller(tmp_path):
    e, calls = env(tmp_path, fail="Bash")
    result = execute(e, selected(e, program()))
    assert result.status == "FAILED"
    assert calls == ["Write", "Bash"]
    assert result.data["returned_to_controller"]
    assert result.data["steps"][1]["observations"] == ["Tool error: observed failure"]


@pytest.mark.parametrize("change", ["interpretation", "multiple-code", "remote"])
def test_no_blind_scientific_chain_or_permission_expansion(tmp_path, change):
    e, calls = env(tmp_path)
    args = program()
    if change == "interpretation":
        args["judgment"]["scientific_interpretation_required_between_steps"] = True
    elif change == "multiple-code":
        args["steps"].append(args["steps"][1])
    else:
        args["steps"][1]["tool"] = "Run Remote"
    with pytest.raises(ValueError):
        selected(e, args)
    assert not calls


def test_nested_protected_write_cannot_bypass_native_guard(tmp_path):
    e, calls = env(tmp_path)
    args = program()
    args["steps"][0]["arguments"]["file_path"] = "data/protected.py"
    result = execute(e, selected(e, args))
    assert result.status == "FAILED"
    assert "protected" in result.error
    assert not calls


def test_missing_evidence_artifact_is_not_successful_execution(tmp_path):
    e, calls = env(tmp_path)
    args = program()
    args["steps"][1]["required_artifacts"] = ["outputs/result.json"]
    result = execute(e, selected(e, args))
    assert result.status == "FAILED"
    assert "Missing required evidence" in result.error
    assert calls == ["Write", "Bash"]

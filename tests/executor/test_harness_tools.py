import json
from typing import ClassVar

from scitaste.backends.base import PreferenceResponse
from scitaste.executor.harness_tools import HarnessToolEnvironment
from scitaste.research_tool_loop import run_research_tool_loop
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController


def test_native_controller_selects_one_workspace_tool_and_records_state(tmp_path):
    calls = []

    class Tool:
        description = "Fixture workspace tool"
        parameters: ClassVar[dict] = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

        def __init__(self, name):
            self.name = name

        def call(self, arguments, **kwargs):
            calls.append((self.name, arguments, kwargs))
            return "retained observation"

    class Backend:
        name = "fixture"

        def rank(self, request):
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="tool-0-0",
                rationale="Inspect before revising",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    environment = HarnessToolEnvironment(
        workspace=tmp_path,
        log_root=tmp_path / "tools",
        research_problem="Inspect task",
        tool_map={name: Tool(name) for name in ("Read", "Write")},
        source_binding={"scope": "fixture-not-live-harness"},
        wall_seconds=60,
    )
    state = ResearchState(project_id="p", research_direction="Research", target_domain="general")
    result = run_research_tool_loop(
        state=state,
        controller=TasteController(
            utility_enabled=False,
            critics_enabled=False,
            preference_backend=Backend(),
        ),
        proposer=lambda *_: {
            "proposals": [
                {"tool": "Read", "arguments": {"path": "data.json"}, "rationale": "Inspect data"},
                {"tool": "Write", "arguments": {"path": "plan.md"}, "rationale": "Draft plan"},
            ]
        },
        environment=environment,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=1,
        max_proposals=2,
    )
    assert result["status"] == "turn-budget-exhausted"
    assert [row[0] for row in calls] == ["Read"]
    assert calls[0][2]["runtime_deadline"] > 1_000_000_000
    decision = json.loads((tmp_path / "loop/decision-000.json").read_text())
    assert len(decision["candidate_actions"]) == 3
    assert state.observations[-1].source_result_id
    assert state.resource_usage.experiments == 0
    assert environment.interface_descriptor["upstream_agent_loop_used"] is False

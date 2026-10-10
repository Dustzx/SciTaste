import json

import pytest

from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.project.session_recovery import planning_resume_stage


def test_session_planning_resume_keeps_binding_and_bounds(tmp_path):
    cycle, planning, exchange = (tmp_path / name for name in ("cycle", "plan", "exchange"))
    for path in (cycle, planning, exchange):
        path.mkdir()
    request = StructuredModelRequest(
        request_id="retained-plan",
        node_name="project-research-design",
        stage="EXPERIMENT_DESIGN",
        state_snapshot_id="idea-snapshot",
        expected_backend="assistant-session",
        expected_model="session-authored",
        policy_id="session-plan",
        policy_fingerprint="a" * 64,
        system_instruction="Select unfinished work from the supplied evidence.",
        input_payload={"evidence": "Completed experiment must not rerun."},
        output_schema={},
        prompt_version="v1",
    )
    request_path = exchange / (request.fingerprint + ".request.json")
    request_path.write_text(request.model_dump_json())
    command = [
        "python",
        "-m",
        "scitaste.project.research_planning",
        "--session-exchange",
        str(exchange),
    ]
    (cycle / "next-plan.started.json").write_text(json.dumps({"command": command}))
    (planning / "CONTRACT.json").write_text(json.dumps({"session_exchange": str(exchange)}))
    (planning / "SESSION_PENDING.json").write_text(
        json.dumps(
            {"status": "awaiting-session-response", "api_calls": 0, "request": str(request_path)}
        )
    )
    original = request_path.read_bytes()
    assert planning_resume_stage(cycle, planning, command) == "next-plan-session-resume-01"
    with pytest.raises(ValueError, match="exact original command"):
        planning_resume_stage(cycle, planning, [*command, "--allow-api"])
    for index in range(1, 4):
        stage = planning_resume_stage(cycle, planning, command)
        assert stage.endswith(f"{index:02d}")
        (cycle / f"{stage}.started.json").write_text("{}")
    with pytest.raises(ValueError, match="exhausted"):
        planning_resume_stage(cycle, planning, command)
    assert request_path.read_bytes() == original
    (planning / "RESULT.json").write_text('{"status":"accepted"}')
    with pytest.raises(ValueError, match="Only an explicit pending"):
        planning_resume_stage(cycle, planning, command)

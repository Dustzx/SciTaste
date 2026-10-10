import json

import pytest

from scitaste.executor.native_terminal_delivery import (
    close_for_report,
    verified_terminal_report_closure,
)
from scitaste.executor.workspace_continuation import restore_workspace
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.state.persistence import StateStore
from tests.executor.test_research_harness import state


def retained_source(tmp_path):
    parent = tmp_path / "native"
    (parent / "workspace/report").mkdir(parents=True)
    (parent / "workspace/report/report.md").write_text("# A retained report\nEvidence stays fixed.")
    exchange = parent / "exchange"
    exchange.mkdir()
    contract = {
        "controller_owner": "scitaste-native",
        "model_source": "assistant-session",
        "session_exchange": str(exchange),
        "plan_sha256": "fixed-plan",
        "max_turns": 3,
        "plan": {"resource_envelope": {"wall_seconds": 60, "max_requests": 3}},
    }
    terminal = {"status": "native-workspace-interrupted", "duration_seconds": 10}
    (parent / "CONTRACT.json").write_text(json.dumps(contract))
    (parent / "RESULT.json").write_text(json.dumps(terminal))
    (parent / "loop").mkdir()
    (parent / "loop/TRAJECTORY.jsonl").write_text("")
    StateStore(parent / "loop/state").save(state())
    request = StructuredModelRequest(
        request_id="pending",
        node_name="native-action-preference",
        stage="EVIDENCE",
        state_snapshot_id="fixed",
        expected_backend="assistant-session",
        expected_model="session-authored",
        policy_id="fixed",
        policy_fingerprint="0" * 64,
        system_instruction="Select one candidate.",
        input_payload={},
        output_schema={},
        prompt_version="v1",
    )
    (exchange / (request.fingerprint + ".request.json")).write_text(request.model_dump_json())
    return parent, contract, terminal


def test_report_disposition_cannot_authorize_research_or_fabricate_a_reply(tmp_path):
    parent, _, _ = retained_source(tmp_path)
    original = (parent / "RESULT.json").read_bytes()
    record = close_for_report(tmp_path, parent, reason="Stopped controller; deliver report only")
    assert len(record["unconsumed_requests"]) == 1
    assert record["responses_written"] == 0
    assert not list((parent / "exchange").glob("*.response.json"))
    child = tmp_path / "research-child"
    child.mkdir()
    with pytest.raises(ValueError, match="pending session"):
        restore_workspace(
            project=tmp_path,
            parent=parent,
            output=child,
            plan_sha256="fixed-plan",
            report_only=False,
        )
    delivery = tmp_path / "report-child"
    delivery.mkdir()
    _, _, lineage = restore_workspace(
        project=tmp_path,
        parent=parent,
        output=delivery,
        plan_sha256="fixed-plan",
        report_only=True,
    )
    assert lineage["inherited_session_requests"] == 1
    assert lineage["terminal_report_closure"]["research_execution_authorized"] is False
    assert lineage["unconsumed_requests"][0]["reply_consumed"] is False
    assert (parent / "RESULT.json").read_bytes() == original


def test_report_disposition_rejects_evidence_drift(tmp_path):
    parent, contract, terminal = retained_source(tmp_path)
    close_for_report(tmp_path, parent, reason="Report-only delivery")
    (parent / "workspace/report/report.md").write_text("# Changed evidence")
    with pytest.raises(ValueError, match="disposition changed"):
        verified_terminal_report_closure(parent, contract, terminal)

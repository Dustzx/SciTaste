from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

import scitaste.benchmark.manuscript as manuscript
import scitaste.full_workflow as full_workflow
from scitaste.cli import main
from scitaste.full_workflow import FullStageRecord, FullWorkflow, load_full_workflow_config
from scitaste.model_nodes.full_workflow_tool_intelligence import (
    FullWorkflowToolIntelligenceInputRecord,
    FullWorkflowToolIntelligenceRecord,
    load_full_workflow_tool_intelligence,
    verify_full_workflow_tool_intelligence,
)
from scitaste.model_nodes.runtime import ModelNodeRuntime
from scitaste.model_nodes.tool_execution_runtime import DurableToolExecutionRuntime
from scitaste.model_nodes.workflow_bridge import (
    load_full_workflow_model_advisory,
    verify_full_workflow_model_advisory,
)
from scitaste.project import ProjectRuntime

CONFIG = Path("configs/workflows/full_offline_tool_intelligence_v1.yaml")
ADVISORY = Path("configs/workflows/full_model_advisory_scripted_v1.yaml").resolve()


def _config(project_id: str, *, with_model_advisory: bool = False):
    config = load_full_workflow_config(CONFIG)
    payload = config.model_dump(mode="python")
    payload.update(
        project_id=project_id,
        paper_id=f"{project_id}-paper",
        paper_directory=f"{project_id}-fixture",
    )
    if with_model_advisory:
        payload["model_node_advisory"] = ADVISORY
    return type(config).model_validate(payload)


def test_full_workflow_automatically_runs_one_bounded_project_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline Tool Intelligence attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    outputs = tmp_path / "outputs"
    project_id = "full-tool-intelligence-project"
    run_id = "tool-intelligence-seed-07"
    config = _config(project_id)
    result = FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id=run_id)

    run_root = outputs / f"projects/{project_id}/runs/{run_id}"
    evidence_root = run_root / "stages/evidence"
    state_path = evidence_root / "research_state.json"
    input_record = FullWorkflowToolIntelligenceInputRecord.model_validate_json(
        (evidence_root / "tool_intelligence_input.json").read_bytes()
    )
    record = FullWorkflowToolIntelligenceRecord.model_validate_json(
        (evidence_root / "tool_intelligence.json").read_bytes()
    )
    stage = FullStageRecord.model_validate_json((evidence_root / "STAGE.json").read_bytes())
    runtime = ProjectRuntime(outputs)

    assert result["status"] == "complete"
    assert result["stages"]["evidence"]["tool_intelligence"] == {
        "hook_id": "evidence-grounding-tool-intelligence",
        "status": "resolved",
        "triggered": True,
        "decision": "accept-as-advice",
        "selected_tool_step": "inspect-supporting-evidence",
        "resolved": True,
        "recovered": False,
        "advisory_only": True,
        "canonical_evidence": False,
        "state_transition_authorized": False,
        "record": "stages/evidence/tool_intelligence.json",
    }
    assert input_record.triggered is True
    assert input_record.matched_claim_ids == ("claim-matched-performance",)
    assert record.input_state_sha256 == record.output_state_sha256
    assert record.output_state_sha256 == hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert record.decision is not None
    assert record.decision.tool_handler_invocation_count == 1
    assert record.decision.advice_payload is not None
    assert record.decision.advice_payload["items"][0]["evidence_id"] == (
        "evidence-result-support-claim-matched-performance"
    )
    assert set(stage.artifact_sha256) >= {
        "stages/evidence/tool_intelligence_binding.json",
        "stages/evidence/tool_intelligence_input.json",
        "stages/evidence/tool_intelligence.json",
    }
    assert (
        ModelNodeRuntime(runtime).verify(project_id=project_id, run_id=run_id).totals.entry_count
        == 1
    )
    tool_verification = DurableToolExecutionRuntime(
        runtime,
        executor_factory=lambda: (_ for _ in ()).throw(AssertionError("unreachable")),
    ).verify(project_id=project_id, run_id=run_id)
    assert tool_verification.decision_count == 1
    assert tool_verification.ledger_entry_count == 1


def test_model_advisory_remains_verifiable_after_tool_plan_appends_to_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    outputs = tmp_path / "outputs"
    project_id = "composed-model-tool-project"
    run_id = "composed-model-tool-seed-07"
    config = _config(project_id, with_model_advisory=True)

    result = FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id=run_id)

    run_root = outputs / f"projects/{project_id}/runs/{run_id}"
    runtime = ProjectRuntime(outputs)
    verification = ModelNodeRuntime(runtime).verify(project_id=project_id, run_id=run_id)
    advisory = verify_full_workflow_model_advisory(
        load_full_workflow_model_advisory(ADVISORY),
        project_runtime=runtime,
        project_id=project_id,
        run_id=run_id,
        state_path=run_root / "stages/evidence/research_state.json",
        record_path=run_root / "stages/evidence/model_advisory.json",
    )

    assert result["status"] == "complete"
    assert verification.totals.entry_count == 2
    assert advisory.receipt.totals.entry_count == 1
    assert verification.totals.chain_head_sha256 != advisory.receipt.totals.chain_head_sha256


def test_full_workflow_resume_reuses_tool_model_and_handler_ledgers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    original_run = full_workflow.FigureWorkflow.run
    calls = 0

    def fail_once(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("controlled post-tool failure")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_once)
    outputs = tmp_path / "outputs"
    project_id = "resumed-tool-intelligence-project"
    run_id = "resumed-tool-intelligence-seed-07"
    config = _config(project_id)
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="controlled post-tool failure"):
        workflow.run(config, outputs_root=outputs, run_id=run_id)

    runtime = ProjectRuntime(outputs)
    before_model = ModelNodeRuntime(runtime).verify(project_id=project_id, run_id=run_id)
    before_tool = DurableToolExecutionRuntime(
        runtime,
        executor_factory=lambda: (_ for _ in ()).throw(AssertionError("unreachable")),
    ).verify(project_id=project_id, run_id=run_id)
    result = workflow.run(config, outputs_root=outputs, run_id=run_id, resume=True)
    after_model = ModelNodeRuntime(runtime).verify(project_id=project_id, run_id=run_id)
    after_tool = DurableToolExecutionRuntime(
        runtime,
        executor_factory=lambda: (_ for _ in ()).throw(AssertionError("unreachable")),
    ).verify(project_id=project_id, run_id=run_id)

    assert result["status"] == "complete"
    assert result["reused_stages"] == ["discovery", "evidence", "communication"]
    assert before_model.totals == after_model.totals
    assert before_tool == after_tool


def test_tool_intelligence_dry_run_is_explicit_and_mutation_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = tmp_path / "outputs"

    assert (
        main(
            [
                "run",
                "full",
                "--config",
                str(CONFIG),
                "--project-id",
                "dry-tool-intelligence-project",
                "--output",
                str(outputs),
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["tool_intelligence"] == {
        "hook_id": "evidence-grounding-tool-intelligence",
        "trigger_claim_statuses": ["supported", "partially_supported"],
        "candidate_tools": ["evidence.inspect"],
        "backend_mode": "scripted",
        "live_configured": False,
        "caller_authorized": False,
        "would_contact_provider": False,
        "network_access": False,
        "automatic_trigger": "deterministic-claim-status-policy",
        "advisory_only": True,
        "canonical_evidence": False,
        "state_transition_authorized": False,
    }
    assert not outputs.exists()


def test_tool_intelligence_verification_rejects_bound_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    outputs = tmp_path / "outputs"
    project_id = "tampered-tool-intelligence-project"
    run_id = "tampered-tool-intelligence-seed-07"
    config = _config(project_id)
    FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id=run_id)
    run_root = outputs / f"projects/{project_id}/runs/{run_id}"
    evidence_root = run_root / "stages/evidence"
    source = evidence_root / "tool_intelligence_sources/evidence.jsonl"
    source.write_text(source.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="bound source is unsafe or oversized"):
        verify_full_workflow_tool_intelligence(
            load_full_workflow_tool_intelligence(config.tool_intelligence_advisory),
            project_runtime=ProjectRuntime(outputs),
            project_id=project_id,
            run_id=run_id,
            run_root=run_root,
            predecessor_state_path=run_root / "stages/discovery/research_state.json",
            state_path=evidence_root / "research_state.json",
            input_path=evidence_root / "tool_intelligence_input.json",
            record_path=evidence_root / "tool_intelligence.json",
        )

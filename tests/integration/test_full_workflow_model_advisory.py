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
from scitaste.model_nodes import (
    FullWorkflowModelAdvisoryInputRecord,
    FullWorkflowModelAdvisoryRecord,
    ModelNodeRuntime,
    ModelNodeRuntimeError,
)
from scitaste.model_nodes.nodes import InterpretationThreatNode
from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPResponse,
    StructuredOpenAICompatibleBackend,
)
from scitaste.model_nodes.runtime_config import LiveRuntimeBackend
from scitaste.project import ProjectRuntime

CONFIG = Path("configs/workflows/full_offline_model_advisory_v1.yaml")
LIVE_CONFIG = Path("configs/workflows/full_zhipu_model_advisory_probe_v1.yaml")


def _config(project_id: str):
    config = load_full_workflow_config(CONFIG)
    payload = config.model_dump(mode="python")
    payload.update(
        project_id=project_id,
        paper_id=f"{project_id}-paper",
        paper_directory=f"{project_id}-reviewed-draft",
    )
    return type(config).model_validate(payload)


def test_full_workflow_executes_offline_advice_without_state_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline full-workflow advisory attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    outputs = tmp_path / "outputs"
    result = FullWorkflow(seed=7).run(
        _config("full-advisory-project"),
        outputs_root=outputs,
        run_id="advisory-seed-07",
    )

    run_root = outputs / "projects/full-advisory-project/runs/advisory-seed-07"
    state = run_root / "stages/evidence/research_state.json"
    input_record_path = run_root / "stages/evidence/model_advisory_input.json"
    record_path = run_root / "stages/evidence/model_advisory.json"
    input_record = FullWorkflowModelAdvisoryInputRecord.model_validate_json(
        input_record_path.read_text(encoding="utf-8")
    )
    record = FullWorkflowModelAdvisoryRecord.model_validate_json(
        record_path.read_text(encoding="utf-8")
    )
    stage = FullStageRecord.model_validate_json(
        (run_root / "stages/evidence/STAGE.json").read_text(encoding="utf-8")
    )
    verification = ModelNodeRuntime(ProjectRuntime(outputs)).verify(
        project_id="full-advisory-project",
        run_id="advisory-seed-07",
    )

    assert result["stages"]["evidence"]["model_advisory"] == {
        "hook_id": "evidence-interpretation-threat",
        "node_name": "interpretation-threat",
        "outcome": "accepted",
        "proposal_available": True,
        "recovered_without_provider": False,
        "advisory_only": True,
        "executable": False,
        "record": "stages/evidence/model_advisory.json",
    }
    assert record.proposal is not None
    assert record.proposal["recommended_action_type"] == "REPRODUCE"
    assert record.state_mutated is False
    assert record.advisory_only is True
    assert record.executable is False
    assert record.input_state_sha256 == record.output_state_sha256
    assert record.output_state_sha256 == hashlib.sha256(state.read_bytes()).hexdigest()
    assert input_record.state_sha256 == record.input_state_sha256
    assert "stages/evidence/model_advisory_input.json" in stage.artifact_sha256
    assert "stages/evidence/model_advisory.json" in stage.artifact_sha256
    assert verification.verified is True
    assert verification.totals.entry_count == 1
    assert verification.totals.cost_usd == 0


def test_full_advisory_dry_run_is_explicit_and_mutation_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = tmp_path / "outputs"
    exit_code = main(
        [
            "run",
            "full",
            "--config",
            str(CONFIG),
            "--project-id",
            "dry-advisory-project",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["model_advisory"] == {
        "hook_id": "evidence-interpretation-threat",
        "node_name": "interpretation-threat",
        "backend_mode": "scripted",
        "live_configured": False,
        "caller_authorized": False,
        "would_contact_provider": False,
        "network_access": False,
        "advisory_only": True,
        "executable": False,
    }
    assert not outputs.exists()


def test_full_workflow_resume_reuses_verified_advisory_ledger(
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
            raise RuntimeError("controlled post-advisory failure")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_once)
    outputs = tmp_path / "outputs"
    config = _config("resumed-advisory-project")
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="controlled post-advisory failure"):
        workflow.run(config, outputs_root=outputs, run_id="resumed-advisory-seed-07")

    runtime = ProjectRuntime(outputs)
    before = ModelNodeRuntime(runtime).verify(
        project_id=config.project_id,
        run_id="resumed-advisory-seed-07",
    )
    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="resumed-advisory-seed-07",
        resume=True,
    )
    after = ModelNodeRuntime(runtime).verify(
        project_id=config.project_id,
        run_id="resumed-advisory-seed-07",
    )

    assert result["status"] == "complete"
    assert result["reused_stages"] == ["discovery", "evidence", "communication"]
    assert before.totals == after.totals
    assert after.totals.entry_count == 1


def test_full_workflow_resume_rejects_advisory_recording_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("tampered-advisory-project")

    def fail_figure(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("stop after advisory")

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_figure)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="stop after advisory"):
        workflow.run(config, outputs_root=outputs, run_id="tampered-advisory-seed-07")

    recording = next(
        (
            outputs / "projects/tampered-advisory-project/runs/tampered-advisory-seed-07/"
            "model_nodes/recordings"
        ).glob("*.jsonl")
    )
    recording.write_text(recording.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(ModelNodeRuntimeError, match="recording evidence drift"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="tampered-advisory-seed-07",
            resume=True,
        )


def test_full_workflow_resume_rejects_pre_call_checkpoint_artifact_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("tampered-advisory-input-project")
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)

    def stop_after_checkpoint(*_args: object, **_kwargs: object):
        raise SystemExit("stop after advisory input checkpoint")

    with monkeypatch.context() as patch:
        patch.setattr(
            full_workflow,
            "execute_full_workflow_model_advisory",
            stop_after_checkpoint,
        )
        with pytest.raises(SystemExit, match="input checkpoint"):
            workflow.run(
                config,
                outputs_root=outputs,
                run_id="tampered-input-seed-07",
            )

    run_root = outputs / "projects/tampered-advisory-input-project/runs/tampered-input-seed-07"
    summary_path = run_root / "stages/evidence/evidence_summary.json"
    summary_path.write_text(
        summary_path.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="input artifact hash drift"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="tampered-input-seed-07",
            resume=True,
        )

    assert (run_root / "stages/evidence/model_advisory_input.json").is_file()
    assert not (run_root / "failed_attempts/stages/evidence").exists()


def test_live_full_advisory_requires_opt_in_before_project_mutation(tmp_path: Path) -> None:
    config = load_full_workflow_config(LIVE_CONFIG)
    outputs = tmp_path / "outputs"

    with pytest.raises(ValueError, match="--allow-live-model-nodes"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="live-without-opt-in",
        )

    assert not outputs.exists()


def test_live_full_advisory_dry_run_reports_both_gates_without_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = tmp_path / "outputs"
    exit_code = main(
        [
            "run",
            "full",
            "--config",
            str(LIVE_CONFIG),
            "--run-id",
            "live-dry-plan",
            "--allow-live-model-nodes",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["model_advisory"]["backend_mode"] == "live"
    assert payload["model_advisory"]["live_configured"] is True
    assert payload["model_advisory"]["caller_authorized"] is True
    assert payload["model_advisory"]["would_contact_provider"] is True
    assert not outputs.exists()


def test_live_response_interruption_recovers_full_stage_without_provider_recall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    transport_calls = 0

    class FakeTransport:
        def post(self, *_args: object, **_kwargs: object) -> StructuredHTTPResponse:
            nonlocal transport_calls
            transport_calls += 1
            content = json.dumps(
                {
                    "threats": [
                        {
                            "threat_id": "bounded-generalization",
                            "kind": "benchmark_artifact",
                            "statement": "The measured result may be evaluation-specific.",
                            "evidence_ids": [],
                            "confidence": 0.7,
                        }
                    ],
                    "alternative_explanations": [
                        "The gain may depend on the configured evidence boundary."
                    ],
                    "recommended_action_type": "REPRODUCE",
                    "rationale": "A separately seeded run can test stability.",
                    "confidence": 0.75,
                }
            )
            raw = json.dumps(
                {
                    "model": "glm-5.3-flash",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 80},
                }
            )
            return StructuredHTTPResponse(data=json.loads(raw), raw_body=raw)

    def build_fake_backend(self: LiveRuntimeBackend, _request_id: str):
        return StructuredOpenAICompatibleBackend(self.config, transport=FakeTransport())

    monkeypatch.setattr(LiveRuntimeBackend, "build", build_fake_backend)
    original_run = InterpretationThreatNode.run

    def interrupt_after_durable_response(self, *args, **kwargs):
        original_run(self, *args, **kwargs)
        raise SystemExit("controlled post-response interruption")

    config = load_full_workflow_config(LIVE_CONFIG)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with monkeypatch.context() as patch:
        patch.setattr(InterpretationThreatNode, "run", interrupt_after_durable_response)
        with pytest.raises(SystemExit, match="post-response interruption"):
            workflow.run(
                config,
                outputs_root=outputs,
                run_id="live-recovery-seed-07",
                allow_live_model_nodes=True,
            )

    assert transport_calls == 1
    run_root = outputs / "projects/scitaste-glm53-full-advisory-probe/runs/live-recovery-seed-07"
    assert (run_root / "stages/evidence/model_advisory_input.json").is_file()
    assert not (run_root / "stages/evidence/model_advisory.json").exists()

    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="live-recovery-seed-07",
        resume=True,
        allow_live_model_nodes=True,
    )

    assert transport_calls == 1
    advice = result["stages"]["evidence"]["model_advisory"]
    assert advice["outcome"] == "rejected"
    assert advice["proposal_available"] is False
    assert advice["recovered_without_provider"] is True
    record = FullWorkflowModelAdvisoryRecord.model_validate_json(
        (run_root / "stages/evidence/model_advisory.json").read_text(encoding="utf-8")
    )
    assert record.receipt.telemetry is not None
    assert record.receipt.telemetry.total_tokens == 200
    assert record.receipt.telemetry.cost_usd is None
    assert record.receipt.totals.entry_count == 1
    assert record.receipt.totals.total_tokens == 200
    assert record.receipt.totals.unknown_cost_count == 1

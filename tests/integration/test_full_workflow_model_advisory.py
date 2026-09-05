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
    FullWorkflowModelAdvisoryRecord,
    ModelNodeRuntime,
    ModelNodeRuntimeError,
)
from scitaste.project import ProjectRuntime

CONFIG = Path("configs/workflows/full_offline_model_advisory_v1.yaml")


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
    record_path = run_root / "stages/evidence/model_advisory.json"
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

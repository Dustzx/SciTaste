from __future__ import annotations

import json
from pathlib import Path

import pytest

import scitaste.benchmark.manuscript as manuscript
import scitaste.full_workflow as full_workflow
from scitaste.cli import main
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.project import ProjectRuntime
from scitaste.state.persistence import StateStore


def test_full_cli_preserves_one_state_and_registers_a_project_paper(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_v1.yaml",
            "--project-id",
            "full-integration-test",
            "--run-id",
            "offline-seed-07",
            "--seed",
            "7",
            "--output",
            str(outputs),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "complete"
    assert payload["effectiveness_claim"] is False
    project = outputs / "projects/full-integration-test"
    run = project / "runs/offline-seed-07"
    final_state = StateStore(run / "stages/figure").load()
    assert final_state.project_id == "full-integration-test"
    assert final_state.working_hypotheses
    assert final_state.experiment_history
    assert final_state.writing_state is not None
    assert final_state.figure_state is not None
    assert len(final_state.decision_history) >= 15
    assert all((run / "stages" / stage / "STAGE.json").is_file() for stage in payload["stages"])

    paper = project / "papers/offline-full-reviewed-draft"
    assert (paper / "main.md").is_file()
    assert (paper / "main.tex").is_file()
    assert (paper / "build.json").is_file()
    assert (paper / "figures/figure.svg").is_file()
    assert (paper / "figures/figure.drawio").is_file()
    assert (paper / "MANIFEST.json").is_file()
    assert (project / "papers/current").resolve() == paper.resolve()
    assert Path(payload["snapshot_binding"]).is_file()


def test_full_cli_dry_run_is_mutation_free(tmp_path: Path, capsys) -> None:
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_v1.yaml",
            "--project-id",
            "dry-full-project",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["stages"] == ["discovery", "evidence", "communication", "figure"]
    assert not outputs.exists()


def test_full_workflow_retains_a_failed_run_for_audit(tmp_path: Path, monkeypatch) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    payload = config.model_dump(mode="python")
    payload["project_id"] = "failed-full-project"
    config = type(config).model_validate(payload)

    def fail_figure(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("controlled figure failure")

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_figure)
    outputs = tmp_path / "outputs"
    with pytest.raises(RuntimeError, match="controlled figure failure"):
        FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id="failed-seed-07")

    snapshot = ProjectRuntime(outputs).open("failed-full-project")
    run = snapshot.manifest.runs[0]
    assert run.status == "failed"
    assert run.model_extra == {
        "failure_type": "RuntimeError",
        "failure_message": "controlled figure failure",
    }
    assert (outputs / "projects/failed-full-project/runs/failed-seed-07/stages").is_dir()

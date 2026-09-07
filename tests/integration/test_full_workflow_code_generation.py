from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import scitaste.benchmark.manuscript as manuscript
import scitaste.full_workflow as full_workflow
from scitaste.cli import main
from scitaste.executor.native_code_generation import verify_native_code_generation_ledger
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.project import ProjectRuntime

CONFIG = Path("configs/workflows/full_offline_code_generation_v1.yaml")
LIVE_CONFIG = Path("configs/workflows/full_zhipu_glm53_flash_code_generation_probe_v1.yaml")


def _config(project_id: str):
    config = load_full_workflow_config(CONFIG)
    payload = config.model_dump(mode="python")
    payload.update(
        project_id=project_id,
        paper_id=f"{project_id}-paper",
        paper_directory=f"{project_id}-integration-fixture",
    )
    return type(config).model_validate(payload)


def test_full_workflow_runs_generated_code_only_after_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline native code generation attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    outputs = tmp_path / "outputs"
    config = _config("full-generated-code-project")
    result = FullWorkflow(seed=7).run(
        config,
        outputs_root=outputs,
        run_id="generated-code-seed-07",
    )

    run_root = outputs / "projects/full-generated-code-project/runs/generated-code-seed-07"
    generation = result["native_execution"]["code_generation"]
    assert generation["outcome"] == "accepted"
    assert generation["input_tokens"] == 900
    assert generation["output_tokens"] == 1250
    assert generation["cost_usd"] == 0
    assert result["native_execution"]["code_admission"]["decision"] == "accepted"
    assert result["stages"]["evidence"]["measured_metrics"]["correct_pivot_delta"] == pytest.approx(
        0.1
    )
    generated = run_root / "native_execution/context/code_generation/result/generated.py"
    proposed = run_root / "native_execution/context/code/proposed.py"
    admitted = run_root / "native_execution/context/code/admitted/experiment.py"
    assert generated.read_bytes() == proposed.read_bytes() == admitted.read_bytes()
    experiment_record = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_root / "native_execution/records").glob("*.json"))
        if "sandbox-measured-replicates" in path.read_text(encoding="utf-8")
    )
    assert list(experiment_record["input_sha256"]) == [
        "native_execution/context/code/admitted/experiment.py"
    ]
    paper = outputs / (
        "projects/full-generated-code-project/papers/"
        "full-generated-code-project-integration-fixture"
    )
    assert (paper / "main.md").is_file()
    assert (paper / "main.tex").is_file()
    assessment = json.loads((paper / "ASSESSMENT.json").read_text(encoding="utf-8"))
    assert assessment["paper_status"] == "integration-fixture"
    assert assessment["substantive_research_draft"] is False
    verification = verify_native_code_generation_ledger(
        ProjectRuntime(outputs),
        project_id=config.project_id,
        run_id="generated-code-seed-07",
    )
    assert verification.totals.entry_count == 1
    assert verification.totals.cost_usd == 0


def test_full_code_generation_dry_run_is_explicit_and_mutation_free(
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
            "generated-code-dry-run",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    generation = payload["native_execution"]["code_generation"]

    assert exit_code == 0
    assert generation["backend_mode"] == "scripted"
    assert generation["max_output_tokens"] == 8192
    assert generation["would_contact_provider"] is False
    assert generation["proposal_only"] is True
    assert generation["deterministic_admission_required"] is True
    assert payload["native_execution"]["experiment_configured"] is True
    assert payload["native_execution"]["isolation_required"] is True
    assert not outputs.exists()


def test_full_workflow_resume_does_not_generate_source_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    original_run = full_workflow.FigureWorkflow.run
    figure_calls = 0
    generation_calls = 0
    original_generate = full_workflow.generate_native_code_proposal

    def fail_once(*args, **kwargs):
        nonlocal figure_calls
        figure_calls += 1
        if figure_calls == 1:
            raise RuntimeError("controlled failure after generated experiment")
        return original_run(*args, **kwargs)

    def count_generation(*args, **kwargs):
        nonlocal generation_calls
        generated = original_generate(*args, **kwargs)
        if not kwargs.get("resume"):
            generation_calls += 1
        return generated

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_once)
    monkeypatch.setattr(full_workflow, "generate_native_code_proposal", count_generation)
    outputs = tmp_path / "outputs"
    config = _config("resumed-generated-code-project")
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="after generated experiment"):
        workflow.run(config, outputs_root=outputs, run_id="resume-codegen-seed-07")

    before = verify_native_code_generation_ledger(
        ProjectRuntime(outputs),
        project_id=config.project_id,
        run_id="resume-codegen-seed-07",
    )
    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="resume-codegen-seed-07",
        resume=True,
    )
    after = verify_native_code_generation_ledger(
        ProjectRuntime(outputs),
        project_id=config.project_id,
        run_id="resume-codegen-seed-07",
    )

    assert result["status"] == "complete"
    assert generation_calls == 1
    assert before.totals == after.totals
    assert after.totals.entry_count == 1


def test_live_code_generation_requires_explicit_caller_authority(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    config = load_full_workflow_config(LIVE_CONFIG)

    with pytest.raises(ValueError, match="--allow-live-model-nodes"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="unauthorized-live-codegen",
        )

    assert not outputs.exists()


def test_code_generation_rejects_an_unshared_advisory_ledger() -> None:
    config = load_full_workflow_config(CONFIG)
    payload = config.model_dump(mode="python")
    payload["model_node_advisory"] = Path(
        "configs/workflows/full_model_advisory_scripted_v1.yaml"
    ).resolve()

    with pytest.raises(ValueError, match="shared extension registry"):
        type(config).model_validate(payload)


def test_full_workflow_rechecks_generation_recording_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    original_run = full_workflow.FigureWorkflow.run
    outputs = tmp_path / "outputs"
    config = _config("tampered-generation-recording-project")

    def tamper_after_figure(*args, **kwargs):
        result = original_run(*args, **kwargs)
        recording = next(
            (
                outputs / "projects/tampered-generation-recording-project/runs/"
                "tampered-codegen-seed-07/model_nodes/recordings"
            ).glob("*.jsonl")
        )
        recording.write_text(recording.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
        return result

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", tamper_after_figure)
    with pytest.raises(ValueError, match="recording evidence drift"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="tampered-codegen-seed-07",
        )

    project = ProjectRuntime(outputs).open(config.project_id)
    run = next(item for item in project.manifest.runs if item.run_id == "tampered-codegen-seed-07")
    assert run.status == "failed"
    assert not (
        outputs / "projects/tampered-generation-recording-project/papers/"
        "tampered-generation-recording-project-draft"
    ).exists()

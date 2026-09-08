from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scitaste.benchmark.manuscript as manuscript
import scitaste.full_workflow as full_workflow
from scitaste.cli import main
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.project import ProjectRuntime
from scitaste.workflow_intake import (
    WorkflowLaunchPlan,
    inspect_workflow_intake,
    materialize_workflow_intake,
    verify_workflow_intake,
)


def _brief_payload(*, project_id: str = "intake-test") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "brief_id": "conflict-control-question-v1",
        "project_id": project_id,
        "question": (
            "Can explicit support and contradiction structure improve research pivot "
            "decisions under matched compute?"
        ),
        "objective": (
            "Determine whether conflict-aware control improves bounded research decisions "
            "without hiding negative evidence."
        ),
        "research_direction": "Test conflict-aware scientific control",
        "target_domain": "autonomous-research",
        "target_venue": "general-ml",
        "resource_budget": {
            "gpu_hours": 2.0,
            "max_experiments": 3,
            "max_wall_time_hours": 2.0,
            "max_api_cost_usd": 0.0,
        },
        "required_evidence_types": [
            "matched held-out benchmark",
            "controlled pilot",
            "matched baseline",
        ],
        "success_criteria": [
            "Report measured correct-pivot deltas with replicate-level provenance."
        ],
        "constraints": ["Use registered offline evidence only."],
        "prohibited_claims": ["Do not claim broad effectiveness from the integration run."],
    }


def _inspection(tmp_path: Path, payload: dict[str, object] | None = None):
    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text(
        yaml.safe_dump(payload or _brief_payload(), sort_keys=False), encoding="utf-8"
    )
    return inspect_workflow_intake(
        brief_path,
        project_id="intake-test",
        run_id="question-seed-07",
        research_direction="Test conflict-aware scientific control",
        target_domain="autonomous-research",
        target_venue="general-ml",
        workflow_config_sha256="a" * 64,
        scenario_paths={
            "discovery": Path("configs/experiments/discovery_strong.yaml"),
            "evidence": Path("configs/evidence/support_demo.yaml"),
            "communication": Path("configs/writing/reviewer_experiment_demo.yaml"),
            "figure": Path("configs/visual/mechanism_demo.yaml"),
        },
    )


def test_intake_materializes_hashed_project_owned_inputs(tmp_path: Path) -> None:
    inspection = _inspection(tmp_path)
    run_root = tmp_path / "outputs/projects/intake-test/runs/question-seed-07"

    prepared = materialize_workflow_intake(inspection, run_root=run_root)
    verified = verify_workflow_intake(inspection, run_root=run_root)

    assert prepared.plan.readiness == "ready"
    assert prepared.plan.model_authority == "proposal-only"
    assert prepared.plan.execution_authority == "deterministic-admission-required"
    assert prepared.scenario_paths["discovery"] == run_root / "intake/scenarios/discovery.yaml"
    assert verified.summary() == prepared.summary()
    assert (run_root / "intake/BRIEF.yaml").is_file()
    plan_path = run_root / "intake/PLAN.json"
    observed = WorkflowLaunchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    assert observed == inspection.plan
    assert observed.configured_evidence_types == (
        "controlled pilot",
        "matched baseline",
        "matched held-out benchmark",
    )

    (run_root / "intake/scenarios/discovery.yaml").write_text("tampered: true\n")
    with pytest.raises(ValueError, match="materialized workflow intake is invalid"):
        verify_workflow_intake(inspection, run_root=run_root)


def test_intake_rejects_budget_or_evidence_outside_the_brief(tmp_path: Path) -> None:
    budget_mismatch = _brief_payload()
    budget_mismatch["resource_budget"] = {
        "gpu_hours": 1.0,
        "max_experiments": 3,
        "max_wall_time_hours": 2.0,
        "max_api_cost_usd": 0.0,
    }
    with pytest.raises(ValueError, match="budget must match"):
        _inspection(tmp_path, budget_mismatch)

    evidence_mismatch = _brief_payload()
    evidence_mismatch["required_evidence_types"] = ["matched held-out benchmark"]
    with pytest.raises(ValueError, match="does not authorize configured evidence types"):
        _inspection(tmp_path, evidence_mismatch)


def test_intake_rejects_source_drift_after_inspection(tmp_path: Path) -> None:
    inspection = _inspection(tmp_path)
    brief_path = inspection.source_paths["research-brief"]
    brief_path.write_text(brief_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source changed after inspection"):
        materialize_workflow_intake(inspection, run_root=tmp_path / "run")


def test_intake_recovers_only_missing_files_and_rejects_symlinked_roots(
    tmp_path: Path,
) -> None:
    inspection = _inspection(tmp_path)
    run_root = tmp_path / "recoverable-run"
    materialize_workflow_intake(inspection, run_root=run_root)
    plan_path = run_root / "intake/PLAN.json"
    plan_path.unlink()

    recovered = materialize_workflow_intake(inspection, run_root=run_root)

    assert recovered.plan == inspection.plan
    assert plan_path.is_file()

    unsafe_root = tmp_path / "unsafe-run"
    unsafe_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (unsafe_root / "intake").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be symlinks"):
        materialize_workflow_intake(inspection, run_root=unsafe_root)


def test_open_question_dry_run_is_a_mutation_free_admission_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_open_question_offline_v1.yaml",
            "--run-id",
            "question-seed-07",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["research_intake"]["readiness"] == "ready"
    assert payload["research_intake"]["model_authority"] == "proposal-only"
    assert payload["research_intake"]["would_materialize_on_run"] is True
    assert len(payload["research_intake"]["input_bindings"]) == 5
    assert not outputs.exists()


def test_full_workflow_executes_only_run_owned_scenarios_and_verifies_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_open_question_offline_v1.yaml")
    outputs = tmp_path / "outputs"
    observed_discovery_paths: list[Path] = []
    load_discovery = full_workflow.load_discovery_scenario

    def capture_discovery(path: str | Path):
        observed_discovery_paths.append(Path(path))
        return load_discovery(path)

    monkeypatch.setattr(full_workflow, "load_discovery_scenario", capture_discovery)
    payload = FullWorkflow(seed=7).run(
        config,
        outputs_root=outputs,
        run_id="question-seed-07",
    )

    run_root = outputs / "projects/scitaste-open-question-offline/runs/question-seed-07"
    expected_discovery = run_root / "intake/scenarios/discovery.yaml"
    assert payload["status"] == "complete"
    assert payload["research_intake"]["readiness"] == "ready"
    assert observed_discovery_paths == [expected_discovery]
    assert (run_root / "intake/BRIEF.yaml").is_file()
    assert (run_root / "intake/PLAN.json").is_file()
    finalization = yaml.safe_load((run_root / "finalization/PLAN.json").read_text())
    assert {
        "intake/PLAN.json",
        "intake/BRIEF.yaml",
        "intake/scenarios/discovery.yaml",
        "intake/scenarios/evidence.yaml",
        "intake/scenarios/communication.yaml",
        "intake/scenarios/figure.yaml",
    }.issubset(finalization["input_sha256"])
    snapshot = ProjectRuntime(outputs).open(config.project_id)
    registered = snapshot.manifest.runs[0]
    assert registered.model_extra is not None
    assert registered.model_extra["research_brief_id"] == "conflict-control-open-question-v1"
    assert registered.model_extra["launch_plan_sha256"] == payload["research_intake"]["plan_sha256"]

    expected_discovery.write_text("tampered: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="materialized workflow intake is invalid"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="question-seed-07",
            resume=True,
        )

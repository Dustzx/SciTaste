from __future__ import annotations

import json
import sys

from scitaste.benchmark.study import load_study_protocol
from scitaste.benchmark.study_models import StudyResults
from scitaste.cli import main
from scitaste.project import ProjectManifest, ProjectRuntime


def test_study_plan_cli_writes_fixed_matrix(tmp_path) -> None:
    output = tmp_path / "plan"

    assert main(["study", "plan", "--output", str(output)]) == 0

    plan = json.loads((output / "study_plan.json").read_text(encoding="utf-8"))
    assert len(plan["cells"]) == 48
    assert set(plan["disabled_conditions"]) == {"sibyl", "ai_scientist_v2"}


def test_study_evaluate_cli_reports_incomplete_matrix(tmp_path) -> None:
    protocol = load_study_protocol("configs/experiments/matched_budget_study_v1.yaml")
    results_path = tmp_path / "incomplete-results.json"
    results_path.write_text(
        StudyResults(
            protocol_sha256=protocol.sha256,
            records=[],
            expert_reviews=[],
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "evaluation"

    assert (
        main(
            [
                "study",
                "evaluate",
                "--results",
                str(results_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )

    report = json.loads((output / "study_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "incomplete"
    assert report["headline_eligible"] is False
    assert report["completed_cells"] == 0
    assert "48 planned cells have no execution record" in report["blockers"]
    assert "48 planned cells have no execution record" in report["blockers"]


def test_study_status_cli_is_read_only_and_classifies_foreign_results(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"
    foreign = outputs / "projects/old/runs/one/study/study_results.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text(
        StudyResults(
            protocol_sha256="a" * 64,
            records=[],
            expert_reviews=[],
        ).model_dump_json(),
        encoding="utf-8",
    )
    before = {path.relative_to(outputs) for path in outputs.rglob("*")}

    assert main(["study", "status", "--outputs-root", str(outputs)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["planned_cells"] == payload["missing_cells"] == 48
    assert payload["integrity_verified_records"] == 0
    assert payload["compatible_sources"] == 0
    assert payload["foreign_sources"] == 1
    assert len(payload["next_execution_batch"]) == 4
    assert {path.relative_to(outputs) for path in outputs.rglob("*")} == before


def test_study_run_cli_dry_runs_four_local_pilot_conditions(tmp_path, capsys) -> None:
    output = tmp_path / "pilot"

    assert (
        main(
            [
                "study",
                "run",
                "--config",
                "configs/experiments/matched_budget_local_pilot_v1.yaml",
                "--launch-config",
                "configs/experiments/study_launchers.example.yaml",
                "--task",
                "diagnosis-friendly-v1",
                "--dry-run",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    summary = json.loads(capsys.readouterr().out)
    assert summary["selected_cells"] == 4
    assert {launch["condition"] for launch in summary["launches"]} == {
        "autoresearchclaw",
        "knowledge_rag",
        "taste_library",
        "full_scitaste",
    }
    assert not output.exists()


def test_local_qwen_study_launchers_are_fully_rendered(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_LOCAL_MODEL_PATH", "/models/qwen3-vl-4b")

    cases = [
        (
            "configs/experiments/matched_budget_local_pilot_v1.yaml",
            "configs/experiments/study_launchers_qwen3vl4b_local_v1.yaml",
            "2048",
        ),
        (
            "configs/experiments/matched_budget_local_preacceptance_v2.yaml",
            "configs/experiments/study_launchers_qwen3vl4b_local_v2.yaml",
            "8192",
        ),
    ]
    for index, (protocol, launch_config, output_ceiling) in enumerate(cases):
        assert (
            main(
                [
                    "study",
                    "run",
                    "--config",
                    protocol,
                    "--launch-config",
                    launch_config,
                    "--task",
                    "diagnosis-friendly-v1",
                    "--output",
                    str(tmp_path / f"local-qwen-plan-{index}"),
                    "--dry-run",
                ]
            )
            == 0
        )

        payload = json.loads(capsys.readouterr().out)
        assert payload["selected_cells"] == 4
        assert all(
            "scitaste.benchmark.local_study_adapter" in launch["command"]
            for launch in payload["launches"]
        )
        assert all(output_ceiling in launch["command"] for launch in payload["launches"])
        assert all(
            "replace-with" not in " ".join(launch["command"]) for launch in payload["launches"]
        )


def test_study_run_cli_executes_standard_result_contract(tmp_path) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        """
import json
import os
from pathlib import Path

cell_dir = Path(os.environ["SCITASTE_STUDY_CELL_DIR"])
(cell_dir / "paper.md").write_text("synthetic acceptance artifact", encoding="utf-8")
result = {
    "schema_version": "1.0",
    "status": "succeeded",
    "evidence_class": "synthetic",
    "usage": {
        "experiments": 1,
        "api_cost_usd": 0,
        "search_queries": 0,
        "llm_tokens": 100,
    },
    "outcome": {
        "useful_results": 1,
        "proposed_ideas": 1,
        "valid_ideas": 1,
        "pilots": 1,
        "discarded_ideas": 0,
        "unproductive_experiments": 0,
        "total_experiments": 1,
        "gpu_hours_before_useful_signal": 0,
        "pivots": 0,
        "correct_pivots": 0,
        "evidence_sufficiency": 0.5,
        "reviewer_concerns_opened": 0,
        "reviewer_concerns_closed": 0,
        "total_claims": 1,
        "unsupported_claims": 0,
    },
    "artifact_paths": ["paper.md"],
}
Path(os.environ["SCITASTE_STUDY_CELL_RESULT"]).write_text(
    json.dumps(result), encoding="utf-8"
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    launch_config = tmp_path / "launchers.yaml"
    launch_config.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "launchers:",
                "  autoresearchclaw:",
                "    command:",
                f"      - {sys.executable}",
                f"      - {adapter}",
                "    gpu_count: 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "run"

    assert (
        main(
            [
                "study",
                "run",
                "--config",
                "configs/experiments/matched_budget_local_pilot_v1.yaml",
                "--launch-config",
                str(launch_config),
                "--task",
                "diagnosis-friendly-v1",
                "--condition",
                "autoresearchclaw",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    results = json.loads((output / "study_results.json").read_text(encoding="utf-8"))
    assert len(results["records"]) == 1
    assert results["records"][0]["status"] == "succeeded"
    assert results["records"][0]["evidence_class"] == "synthetic"
    assert results["records"][0]["artifacts"][0]["path"].endswith("paper.md")


def test_study_project_run_cli_dry_run_does_not_register_run(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id="cli-study-project",
            title="CLI study",
            research_direction="Keep Phase 9 execution project-owned.",
            status="active",
            stage_semantics="matched-budget-study-cells",
        )
    )

    assert (
        main(
            [
                "study",
                "project-run",
                "--config",
                "configs/experiments/matched_budget_local_pilot_v1.yaml",
                "--launch-config",
                "configs/experiments/study_launchers.example.yaml",
                "--project-id",
                "cli-study-project",
                "--run-id",
                "cli-study-run",
                "--outputs-root",
                str(outputs),
                "--provider",
                "scripted",
                "--model",
                "deterministic-adapter",
                "--condition",
                "autoresearchclaw",
                "--max-cells",
                "1",
                "--dry-run",
            ]
        )
        == 0
    )

    summary = json.loads(capsys.readouterr().out)
    assert summary["run_status"] == "planned"
    assert summary["study"]["selected_cells"] == 1
    assert runtime.open("cli-study-project").manifest.runs == []


def test_study_project_run_cli_registers_partial_and_resumes(tmp_path, capsys) -> None:
    adapter = tmp_path / "project_adapter.py"
    adapter.write_text(
        """
import json
import os
from pathlib import Path

cell_dir = Path(os.environ["SCITASTE_STUDY_CELL_DIR"])
(cell_dir / "paper.md").write_text("project-owned synthetic artifact", encoding="utf-8")
result = {
    "schema_version": "1.0",
    "status": "succeeded",
    "evidence_class": "synthetic",
    "usage": {
        "experiments": 1,
        "api_cost_usd": 0,
        "search_queries": 0,
        "llm_tokens": 100,
    },
    "outcome": {
        "useful_results": 1,
        "proposed_ideas": 1,
        "valid_ideas": 1,
        "pilots": 1,
        "discarded_ideas": 0,
        "unproductive_experiments": 0,
        "total_experiments": 1,
        "gpu_hours_before_useful_signal": 0,
        "pivots": 0,
        "correct_pivots": 0,
        "evidence_sufficiency": 0.5,
        "reviewer_concerns_opened": 0,
        "reviewer_concerns_closed": 0,
        "total_claims": 1,
        "unsupported_claims": 0,
    },
    "artifact_paths": ["paper.md"],
}
Path(os.environ["SCITASTE_STUDY_CELL_RESULT"]).write_text(
    json.dumps(result), encoding="utf-8"
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    launch_config = tmp_path / "project_launchers.yaml"
    launch_config.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "launchers:",
                "  autoresearchclaw:",
                "    command:",
                f"      - {sys.executable}",
                f"      - {adapter}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs"
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id="cli-managed-study",
            title="Managed CLI study",
            research_direction="Resume only content-bound Phase 9 cells.",
            status="active",
            stage_semantics="matched-budget-study-cells",
        )
    )
    command = [
        "study",
        "project-run",
        "--config",
        "configs/experiments/matched_budget_local_pilot_v1.yaml",
        "--launch-config",
        str(launch_config),
        "--project-id",
        "cli-managed-study",
        "--run-id",
        "managed-study-run",
        "--outputs-root",
        str(outputs),
        "--provider",
        "scripted",
        "--model",
        "deterministic-adapter",
        "--condition",
        "autoresearchclaw",
        "--max-cells",
        "1",
    ]

    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["run_status"] == "partial"
    assert first["study"]["executed_cells"] == 1
    snapshot = runtime.open("cli-managed-study")
    assert snapshot.manifest.current_run == "managed-study-run"
    assert snapshot.manifest.runs[0].status == "partial"
    study_root = outputs / "projects/cli-managed-study/runs/managed-study-run/study"
    assert (study_root / "study_run_manifest.json").is_file()
    assert len(list(study_root.glob("cells/*/cell_checkpoint.json"))) == 1

    assert main([*command, "--resume"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["run_status"] == "partial"
    assert resumed["study"]["executed_cells"] == 0
    assert resumed["study"]["resumed_cells"] == 1
    assert runtime.open("cli-managed-study").manifest.runs[0].model_extra["resume_attempt"] == 1

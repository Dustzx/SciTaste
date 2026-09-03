from __future__ import annotations

import json
import sys

from scitaste.benchmark.study import load_study_protocol
from scitaste.benchmark.study_models import StudyResults
from scitaste.cli import main


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
    assert "base model revision is not frozen" in report["blockers"]
    assert "search snapshot is not materialized" in report["blockers"]
    assert "48 planned cells have no execution record" in report["blockers"]


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

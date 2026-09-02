from __future__ import annotations

import json

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

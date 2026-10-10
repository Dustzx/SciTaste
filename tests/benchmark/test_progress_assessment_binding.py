"""Progress reflects current closure while grades remain bound to exact papers."""

from scitaste.benchmark.open_research import digest
from scitaste.benchmark.open_research_results import merge_sealed_assessment


def test_matching_paper_grade_does_not_revert_current_lifecycle_status(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text("same manuscript")
    observed = {
        "rows": [
            {
                "arm": "native",
                "paper": "paper.md",
                "status": "paper-cycle-completed",
                "scores": {"Overall": None},
            }
        ]
    }
    assessed = {
        "rows": [
            {
                "arm": "native",
                "paper": "paper.md",
                "status": "paper-cycle-stopped",
                "scores": {"Overall": 4},
            }
        ]
    }
    result = merge_sealed_assessment(
        tmp_path, observed, assessed, [{"arm": "native", "paper_sha256": digest(paper)}]
    )
    assert result["rows"][0]["status"] == "paper-cycle-completed"
    assert result["rows"][0]["scores"] == {"Overall": 4}


def test_changed_paper_keeps_historical_grade_separate(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text("revised manuscript")
    observed = {
        "rows": [
            {
                "arm": "native",
                "paper": "paper.md",
                "status": "paper-cycle-completed",
                "scores": {"Overall": None},
            }
        ]
    }
    assessed = {"rows": [{"arm": "native", "paper": "paper.md", "scores": {"Overall": 4}}]}
    result = merge_sealed_assessment(
        tmp_path, observed, assessed, [{"arm": "native", "paper_sha256": "a" * 64}]
    )
    row = result["rows"][0]
    assert row["scores"] == {"Overall": None}
    assert row["historical_assessment"]["scores"] == {"Overall": 4}
    assert row["status"] == "paper-cycle-completed"

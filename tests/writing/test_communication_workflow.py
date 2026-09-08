from __future__ import annotations

import json

from scitaste.cli import main
from scitaste.state.persistence import StateStore


def test_review_triggers_evidence_and_returns_to_paper_revision(tmp_path) -> None:
    output = tmp_path / "communication"

    assert (
        main(
            [
                "write",
                "--config",
                "configs/writing/reviewer_experiment_demo.yaml",
                "--output",
                str(output),
                "--seed",
                "7",
            ]
        )
        == 0
    )

    summary = json.loads((output / "communication_summary.json").read_text())
    state = StateStore(output).load()
    obligation = state.open_research_obligations[0]
    assert summary["final_stage"] == "COMMUNICATION"
    assert summary["writing_revision"] == 2
    assert "ADD_BASELINE" in summary["selected_actions"]
    assert "COLLECT_EVIDENCE" in summary["selected_actions"]
    assert obligation.status == "closed"
    assert obligation.resolution_evidence_ids
    assert state.reviewer_concerns[0].status == "closed"
    assert state.evidence_graph.items[-1].evidence_type == "matched baseline"
    assert state.writing_state is not None
    assert state.writing_state.retrieved_taste_case_ids == [
        "taste-introduction-limitation",
        "taste-results-argument-not-log",
    ]
    assert (
        "Review resolution obligation-review-matched-baseline" in (output / "paper.md").read_text()
    )
    publication = (output / "paper.publication.md").read_text(encoding="utf-8")
    assert "Reviewer concern resolution:" in publication
    assert "[claim:" not in publication
    assert "[evidence:" not in publication
    assert "obligation-review" not in publication
    assert not [
        finding for finding in state.writing_state.critic_findings if finding.severity == "error"
    ]


def test_review_command_exposes_same_complete_loop(tmp_path) -> None:
    output = tmp_path / "review"

    assert main(["review", "--output", str(output), "--seed", "3"]) == 0

    summary = json.loads((output / "communication_summary.json").read_text())
    assert summary["closed_obligation_ids"] == ["obligation-review-matched-baseline"]

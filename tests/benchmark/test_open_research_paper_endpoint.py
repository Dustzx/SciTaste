import json

import pytest

from scitaste.benchmark.open_research import digest
from scitaste.benchmark.open_research_results import observe


def retain(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_official_topic_without_authored_assets(tmp_path):
    campaign = tmp_path / "evaluations/campaign/CAMPAIGN.json"
    brief = tmp_path / "evaluations/campaign/EXECUTION_BRIEF.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("Official open research topic")
    retain(
        campaign,
        {
            "arms": ["mlr-agent"],
            "benchmark": "MLR-Bench",
            "task_id": "official-topic",
            "execution_brief": {
                "locator": brief.relative_to(tmp_path).as_posix(),
                "sha256": digest(brief),
            },
        },
    )
    run = tmp_path / "evaluations/mlr"
    retain(
        run / "CONTRACT.json",
        {
            "framework": "mlr-agent",
            "source_commit": "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824",
            "source_tree_clean": True,
            "coding_cli_is_real": True,
            "task_sha256": digest(brief),
            "public_assets": {},
        },
    )
    retain(run / "RESULT.json", {"exit_code": 0, "wall_seconds": 10})
    retain(run / "workspace/UPSTREAM_FINISHED.json", {"native_pipeline_returned": True})
    (run / "workspace/results").mkdir()
    (run / "workspace/results/paper.md").write_text("First complete paper")
    row = observe(tmp_path, campaign, {"mlr-agent": "evaluations/mlr"})["rows"][0]
    assert row["terminal"]
    assert row["manuscript_timepoint"] == "first-native-complete-paper"
    contract = json.loads(campaign.read_text())
    contract["benchmark"] = "SciTasteBench"
    retain(campaign, contract)
    with pytest.raises(ValueError, match="requires its frozen public assets"):
        observe(tmp_path, campaign, {"mlr-agent": "evaluations/mlr"})


def test_first_paper_keeps_original_failure_separate_from_delivery_recovery(tmp_path):
    campaign = tmp_path / "evaluations/campaign/CAMPAIGN.json"
    retain(campaign, {"arms": ["scitaste-native"], "task_id": "research"})
    run = tmp_path / "evaluations/native"
    retain(
        run / "CONTRACT.json",
        {
            "plan": {
                "campaign": {
                    "locator": "evaluations/campaign/CAMPAIGN.json",
                    "sha256": digest(campaign),
                }
            }
        },
    )
    retain(run / "RESULT.json", {"status": "controller-finished", "duration_seconds": 2})
    lifecycle = tmp_path / "evaluations/lifecycle"
    retain(
        lifecycle / "CONTRACT.json",
        {
            "campaign_sha256": digest(campaign),
            "source_contract_sha256": digest(run / "CONTRACT.json"),
            "paper_prefix": "first-paper",
        },
    )
    original = {
        "status": "paper-cycle-stopped",
        "source_run": "evaluations/native",
        "elapsed_seconds_since_research_launch": 10,
        "paper_prefix": "first-paper",
        "observed_requests": 11,
    }
    retain(lifecycle / "RESULT.json", original)
    retain(
        lifecycle / "resumes/01.result.json",
        {
            **original,
            "status": "paper-cycle-completed",
            "elapsed_seconds_since_research_launch": 20,
            "observed_requests": 12,
            "original_failure_sha256": digest(lifecycle / "RESULT.json"),
        },
    )
    retain(lifecycle / "delivery/RESULT.json", {"status": "report-delivered"})
    paper = tmp_path / "papers/first-paper/main.md"
    paper.parent.mkdir(parents=True)
    paper.write_text("Initial paper")
    retain(
        paper.parent / "REPORT_IMPORT.json",
        {"task_result_sha256": digest(lifecycle / "delivery/RESULT.json")},
    )
    revised = tmp_path / "papers/first-paper-revised/main.md"
    revised.parent.mkdir()
    revised.write_text("Revised paper")
    assignment = {"run": "evaluations/native", "lifecycle": "evaluations/lifecycle"}
    current = observe(tmp_path, campaign, {"scitaste-native": assignment})["rows"][0]
    assert current["paper"] == "papers/first-paper-revised/main.md"
    assert current["original_lifecycle"]["status"] == "paper-cycle-stopped"
    assert current["retained_model_responses"] == 12
    initial = observe(
        tmp_path,
        campaign,
        {"scitaste-native": {**assignment, "manuscript_endpoint": "first-complete-paper"}},
    )["rows"][0]
    assert initial["paper"] == "papers/first-paper/main.md"
    assert initial["status"] == "paper-cycle-stopped"
    assert initial["elapsed_seconds"] == 10
    assert initial["retained_model_responses"] == 11
    assert not initial["paper_cycle_complete"]
    assert initial["manuscript_timepoint"] == "first-complete-paper"

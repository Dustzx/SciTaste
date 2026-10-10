"""Only assignment integrity and result-denominator checks, no model/GPU calls."""

import json

import pytest

from scitaste.benchmark.open_research import digest, load_plan, verified_asset
from scitaste.benchmark.open_research_results import observe, prepare_assessment


def test_retained_request_roundtrip_verifies_computed_fingerprint(tmp_path):
    from scitaste.model_nodes.models import StructuredModelRequest
    from scitaste.model_nodes.session_exchange import load_retained_request

    request = StructuredModelRequest(
        request_id="assessment",
        node_name="review",
        stage="EVIDENCE",
        state_snapshot_id="a" * 64,
        expected_backend="assistant-session",
        expected_model="session-authored",
        policy_id="test",
        policy_fingerprint="b" * 64,
        system_instruction="Assess",
        input_payload={},
        output_schema={},
        prompt_version="v1",
    )
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    assert load_retained_request(path) == request
    payload = json.loads(path.read_text())
    payload["system_instruction"] = "Changed instructions"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="fingerprint changed"):
        load_retained_request(path)


def test_asset_cannot_escape_or_change(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    asset = root / "brief.md"
    asset.write_text("original topic")
    row = {"locator": "brief.md", "sha256": digest(asset)}
    assert verified_asset(root, row) == asset
    asset.write_text("injected hypothesis")
    with pytest.raises(ValueError, match="changed"):
        verified_asset(root, row)
    outside = tmp_path / "private.json"
    outside.write_text("private scorer")
    with pytest.raises(ValueError):
        verified_asset(root, {"locator": "../private.json", "sha256": digest(outside)})


def test_missing_arms_remain_in_denominator(tmp_path):
    root = tmp_path / "project"
    (root / "evaluations").mkdir(parents=True)
    campaign = root / "campaign.json"
    campaign.write_text(
        json.dumps(
            {
                "arms": ["scitaste-native", "autoresearchclaw"],
                "task_id": "iclr2025_scsl",
            }
        )
    )
    assignments = {"scitaste-native": "evaluations/native", "autoresearchclaw": "evaluations/arc"}
    report = observe(root, campaign, assignments)
    assert report["assigned_systems"] == 2
    assert all(row["paper"] is None for row in report["rows"])
    assert all(value is None for row in report["rows"] for value in row["scores"].values())
    with pytest.raises(ValueError, match="Every frozen arm"):
        observe(root, campaign, {"scitaste-native": "evaluations/native"})
    with pytest.raises(ValueError, match="terminal receipts"):
        prepare_assessment(root, campaign, assignments, root / "assessment")
    assert not (root / "assessment").exists()


def test_native_project_segment_delivery_is_source_bound_not_recursive_completion(tmp_path):
    from scitaste.benchmark.open_research_results import _native_project_delivery

    root = tmp_path / "project"
    run = root / "evaluations/native"
    lifecycle = root / "evaluations/lifecycle"
    cycle = root / "evaluations/paper-cycle"
    report = root / "evaluations/delivery/RESULT.json"
    paper = root / "papers/paper-revised/main.md"
    for file in (run / "RESULT.json", run / "CONTRACT.json", cycle / "SUMMARY.json", report, paper):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}")
    plan = root / "plan.json"
    plan.write_text("{}")
    lifecycle.mkdir()
    contract = {
        "scope": "native-workspace-project-cycle",
        "project": root.name,
        "execution": "evaluations/native",
        "plan": "plan.json",
        "plan_sha256": digest(plan),
        "delivery": "evaluations/delivery",
        "paper_prefix": "paper",
    }
    (lifecycle / "CONTRACT.json").write_text(json.dumps(contract))
    delivery = {
        "contract_sha256": digest(lifecycle / "CONTRACT.json"),
        "execution_result_sha256": digest(run / "RESULT.json"),
        "delivery_result_sha256": digest(report),
        "paper_summary_sha256": digest(cycle / "SUMMARY.json"),
        "paper_directory": "paper-revised",
    }
    (lifecycle / "RESULT.json").write_text(json.dumps(delivery))
    launch = {"plan_sha256": digest(plan)}
    pending = _native_project_delivery(root, lifecycle, run, launch, delivery)
    assert not pending["terminal"]
    (lifecycle / "WORKFLOW_STATUS_CURRENT.json").write_text(
        json.dumps({"status": "lifecycle-segment-delivered", "paper_cycle_delivered": True})
    )
    observed = _native_project_delivery(root, lifecycle, run, launch, delivery)
    assert observed["terminal"] and observed["paper_cycle_complete"]
    assert observed["project_segment_delivered"] and not observed["lifecycle_complete"]
    assert not observed["whole_project_lifecycle_complete"]
    assert observed["paper"] == "papers/paper-revised/main.md"
    (cycle / "SUMMARY.json").write_text("changed")
    with pytest.raises(ValueError, match="sources changed"):
        _native_project_delivery(root, lifecycle, run, launch, delivery)


def test_project_delivery_display_does_not_mislabel_recursive_project_as_missing_paper():
    from scripts.publish_open_research_progress import display_status

    row = {
        "project_segment_delivered": True,
        "paper_cycle_complete": True,
        "lifecycle_complete": False,
        "scores": dict.fromkeys(("Clarity", "Novelty", "Soundness", "Significance", "Overall"), 4),
    }
    assert "修订链已交付" in display_status(row)
    assert "原生流程未完整结束" not in display_status(row)


def test_native_project_response_count_uses_actual_session_exchange(tmp_path):
    root = tmp_path / "project"
    run = root / "evaluations/native"
    exchange = run / "session-exchange"
    exchange.mkdir(parents=True)
    (exchange / "first.response.json").write_text("{}")
    campaign = root / "campaign.json"
    campaign.write_text(
        json.dumps({"arms": ["scitaste-native"], "task_id": "natural-reviewer-shift"})
    )
    (run / "CONTRACT.json").write_text(
        json.dumps({"plan": {"campaign": {"locator": "campaign.json", "sha256": digest(campaign)}}})
    )
    row = observe(root, campaign, {"scitaste-native": "evaluations/native"})["rows"][0]
    assert row["retained_model_responses"] == 1


def test_changed_budget_rejected_before_native_execution(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "source.md"
    source.write_text("source")
    bound = {"locator": "source.md", "sha256": digest(source)}
    campaign = root / "campaign.json"
    campaign.write_text(
        json.dumps(
            {
                **dict.fromkeys(
                    ("source_brief", "brief", "execution_brief", "rubric", "rubric_source"), bound
                ),
                "resource_envelope": {"wall_seconds": 14400, "max_requests": 80},
            }
        )
    )
    plan = {
        "project_id": "project",
        "executor_id": "scitaste-native-workspace",
        "controller_owner": "scitaste-native",
        "runtime_sources": {},
        "campaign": {"locator": "campaign.json", "sha256": digest(campaign)},
        "resource_envelope": {"wall_seconds": 14401, "max_requests": 80},
    }
    with pytest.raises(ValueError, match="budget differs"):
        load_plan(root, plan)


@pytest.mark.parametrize(
    ("text", "is_paper"),
    [
        ("# Paper Draft Blocked\n\nNo experiment metrics.\n", False),
        ("# Negative transfer result\n\nMeasured error did not improve.\n", True),
    ],
)
def test_upstream_failure_marker_is_not_a_manuscript(tmp_path, text, is_paper):
    root = tmp_path / "project"
    run = root / "evaluations/arc"
    draft = run / "work/upstream_run/stage-17/paper_draft.md"
    draft.parent.mkdir(parents=True)
    draft.write_text(text)
    (run / "SESSION_CLOSED.json").write_text(json.dumps({"return_code": 2, "wall_seconds": 10}))
    campaign = root / "campaign.json"
    campaign.write_text(json.dumps({"arms": ["autoresearchclaw"], "task_id": "molecular"}))
    row = observe(root, campaign, {"autoresearchclaw": "evaluations/arc"})["rows"][0]
    assert row["terminal"] and row["status"] == "stopped-incomplete"
    assert bool(row["paper"]) is is_paper
    assert all(value is None for value in row["scores"].values())
    if not is_paper:
        assert row["nonpaper_artifacts"][0]["sha256"] == digest(draft)
        assert row["paper_missing_reason"] == "upstream-draft-blocked-no-metrics"

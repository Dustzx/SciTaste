from __future__ import annotations

import json
import subprocess

from scitaste.executor.autoresearchclaw import (
    PINNED_COMMIT,
    AutoResearchClawExecutor,
)
from scitaste.executor.base import ExecutionStatus
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def test_pinned_substrate_baseline_dry_run(tmp_path) -> None:
    executor = AutoResearchClawExecutor(dry_run=True)

    verification = executor.verify_substrate()
    result = executor.baseline_run(topic="Smoke test", output_dir=tmp_path, to_stage="TOPIC_INIT")

    assert verification["actual_commit"] == PINNED_COMMIT
    assert result.status == ExecutionStatus.PLANNED
    assert result.data["command"][-2:] == ["--to-stage", "TOPIC_INIT"]


def test_stage_execution_imports_validated_artifacts_and_cost(tmp_path) -> None:
    run_dir = tmp_path / "arc-run"
    prior = run_dir / "stage-02"
    prior.mkdir(parents=True)
    (prior / "problem_tree.md").write_text("# Problems\n", encoding="utf-8")
    (run_dir / "checkpoint.json").write_text(
        json.dumps({"last_completed_stage": 2, "run_id": "upstream-before"}),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("test: true\n", encoding="utf-8")

    def successful_runner(command, **kwargs):
        stage = run_dir / "stage-03"
        stage.mkdir(parents=True)
        (stage / "search_plan.yaml").write_text("queries: []\n", encoding="utf-8")
        (stage / "sources.json").write_text("[]\n", encoding="utf-8")
        (stage / "queries.json").write_text("[]\n", encoding="utf-8")
        (run_dir / "checkpoint.json").write_text(
            json.dumps({"last_completed_name": "SEARCH_STRATEGY", "run_id": "upstream-after"}),
            encoding="utf-8",
        )
        (run_dir / "pipeline_summary.json").write_text(
            json.dumps({"final_status": "done", "final_stage": 3}), encoding="utf-8"
        )
        (run_dir / "cost_log.jsonl").write_text(
            json.dumps({"cost_usd": 0.0125}) + "\n", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="stage complete", stderr="")

    state = ResearchState(
        project_id="arc-test",
        research_direction="Scientific agent evaluation",
        target_domain="autonomous-research",
        executor_context={"autoresearchclaw_run_dir": str(run_dir)},
    )
    action = ResearchAction(
        action_id="search",
        type=MetaAction.SEARCH,
        description="Execute search strategy",
    )
    executor = AutoResearchClawExecutor(
        config_path=config,
        command_runner=successful_runner,
    )

    result = executor.search(state, action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert len(result.artifacts) == 3
    assert result.cost["api_cost_usd"] == 0.0125
    assert result.cost["wall_time_hours"] > 0
    assert result.data["checkpoint"]["last_completed_name"] == "SEARCH_STRATEGY"
    assert result.data["pipeline_summary"]["final_stage"] == 3
    assert result.data["session"]["upstream_run_id_changed"] is True
    assert result.data["session"]["session_id"].startswith("arc-session-")
    assert result.data["cost_accounting"]["api_cost_measured"] is True
    assert all(item["sha256"] for item in result.data["artifact_manifest"])


def test_stage_cost_is_incremental_when_upstream_log_is_cumulative(tmp_path) -> None:
    run_dir = tmp_path / "arc-run"
    prior = run_dir / "stage-02"
    prior.mkdir(parents=True)
    (prior / "problem_tree.md").write_text("# Problems\n", encoding="utf-8")
    (run_dir / "cost_log.jsonl").write_text(
        json.dumps({"cost_usd": 0.5}) + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("test: true\n", encoding="utf-8")

    def successful_runner(command, **kwargs):
        stage = run_dir / "stage-03"
        stage.mkdir(exist_ok=True)
        (stage / "search_plan.yaml").write_text("queries: []\n", encoding="utf-8")
        (stage / "sources.json").write_text("[]\n", encoding="utf-8")
        (stage / "queries.json").write_text("[]\n", encoding="utf-8")
        with (run_dir / "cost_log.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"cost_usd": 0.02}) + "\n")
        return subprocess.CompletedProcess(command, 0, stdout="stage complete", stderr="")

    state = ResearchState(
        project_id="arc-test",
        research_direction="Scientific agent evaluation",
        target_domain="autonomous-research",
        executor_context={"autoresearchclaw_run_dir": str(run_dir)},
    )
    action = ResearchAction(
        action_id="search",
        type=MetaAction.SEARCH,
        description="Execute search strategy",
    )
    result = AutoResearchClawExecutor(
        config_path=config,
        command_runner=successful_runner,
    ).execute(state, action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.cost["api_cost_usd"] == 0.02
    assert result.data["cost_accounting"] == {
        "wall_time_measured": True,
        "api_cost_measured": True,
        "api_cost_semantics": "incremental-stage-delta-v1",
        "prior_api_cost_usd": 0.5,
        "cumulative_api_cost_usd": 0.52,
    }


def test_stage_execution_rejects_missing_prerequisites(tmp_path) -> None:
    called = False

    def forbidden_runner(command, **kwargs):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    config = tmp_path / "config.yaml"
    config.write_text("test: true\n", encoding="utf-8")
    state = ResearchState(
        project_id="arc-test",
        research_direction="Scientific agent evaluation",
        target_domain="autonomous-research",
        executor_context={"autoresearchclaw_run_dir": str(tmp_path / "empty")},
    )
    action = ResearchAction(
        action_id="baseline",
        type=MetaAction.ADD_BASELINE,
        description="Design a matched baseline",
    )
    result = AutoResearchClawExecutor(
        config_path=config,
        command_runner=forbidden_runner,
    ).execute(state, action)

    assert result.status == ExecutionStatus.FAILED
    assert "hypotheses.md" in str(result.error)
    assert called is False


def test_success_exit_without_contract_artifacts_is_a_failure(tmp_path) -> None:
    run_dir = tmp_path / "arc-run"
    prior = run_dir / "stage-02"
    prior.mkdir(parents=True)
    (prior / "problem_tree.md").write_text("# Problems\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("test: true\n", encoding="utf-8")

    def incomplete_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    state = ResearchState(
        project_id="arc-test",
        research_direction="Scientific agent evaluation",
        target_domain="autonomous-research",
        executor_context={"autoresearchclaw_run_dir": str(run_dir)},
    )
    action = ResearchAction(
        action_id="search",
        type=MetaAction.SEARCH,
        description="Execute search strategy",
    )
    result = AutoResearchClawExecutor(
        config_path=config,
        command_runner=incomplete_runner,
    ).execute(state, action)

    assert result.status == ExecutionStatus.FAILED
    assert "omitted contract artifacts" in str(result.error)

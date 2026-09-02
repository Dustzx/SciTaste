from __future__ import annotations

import json

from scitaste.cli import main
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.mock import MockExecutor
from scitaste.executor.workflow import SubstrateActionWorkflow
from scitaste.schema.actions import MetaAction
from scitaste.state.persistence import DecisionLogger, StateStore


def test_successful_substrate_action_is_logged_and_applied(tmp_path) -> None:
    output = tmp_path / "substrate"

    summary = SubstrateActionWorkflow(executor=MockExecutor(seed=7), seed=7).run(
        action_type=MetaAction.SEARCH,
        run_dir=tmp_path / "arc-run",
        output_dir=output,
    )

    state = StateStore(output).load()
    decisions = DecisionLogger(output / "decisions.jsonl").read_all()
    assert summary["execution_status"] == "SUCCEEDED"
    assert summary["transition_applied"] is True
    assert state.revision == 1
    assert state.executor_context["autoresearchclaw_run_dir"].endswith("arc-run")
    assert decisions[0].executor_result_id
    assert decisions[0].actual_outcome["status"] == "SUCCEEDED"


def test_failed_substrate_action_does_not_advance_state(tmp_path) -> None:
    def fail(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="fixture",
            error="controlled failure",
        )

    summary = SubstrateActionWorkflow(
        executor=MockExecutor(handlers={MetaAction.SEARCH: fail})
    ).run(
        action_type=MetaAction.SEARCH,
        run_dir=tmp_path / "arc-run",
        output_dir=tmp_path / "failed",
    )

    state = StateStore(tmp_path / "failed").load()
    result = json.loads((tmp_path / "failed" / "executor_result.json").read_text())
    assert summary["transition_applied"] is False
    assert state.revision == 0
    assert result["error"] == "controlled failure"


def test_substrate_cli_dry_run_validates_pin_without_writing(tmp_path) -> None:
    output = tmp_path / "dry"
    assert (
        main(
            [
                "substrate",
                "execute",
                "--action",
                "SEARCH",
                "--run-dir",
                str(tmp_path / "arc-run"),
                "--config",
                "configs/executors/autoresearchclaw.bailian.example.yaml",
                "--output",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()

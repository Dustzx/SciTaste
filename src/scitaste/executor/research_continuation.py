"""Explicit terminal-run continuation without resetting consumed budgets."""

import hashlib
import json
import math
import shutil
from pathlib import Path

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.state.persistence import StateStore
from scitaste.state.research_state import ResearchObservation


def restore_terminal_research(parent: Path, output: Path, *, expected: dict, pending_observer=None):
    """Copy bounded execution inputs into a new run, never mutate or resume in place."""
    parent = parent.resolve(strict=True)
    output = output.resolve(strict=True)
    if parent == output or parent.is_relative_to(output) or output.is_relative_to(parent):
        raise ValueError("Continuation must use a separate sibling run")
    contract_bytes = (parent / "CONTRACT.json").read_bytes()
    contract = json.loads(contract_bytes)
    terminal = json.loads((parent / "RESULT.json").read_text())
    if terminal["status"] not in {"native-tool-loop-interrupted", "execution-unresolved"}:
        raise ValueError("Only explicitly interrupted Native runs may be continued")
    for key, value in expected.items():
        if contract.get(key) != value:
            raise ValueError(f"Continuation changes frozen setting: {key}")
    ledger = provider_ledger_accounting(parent / "logs/provider_calls")
    if ledger["unresolved_reservations"]:
        raise ValueError("Unresolved API requests must not be replayed")
    state = StateStore(parent / "loop/state").load()
    history = [
        json.loads(line) for line in (parent / "loop/TRAJECTORY.jsonl").read_text().splitlines()
    ]
    if len(history) != len(state.decision_history):
        raise ValueError("Checkpoint is not a complete post-action boundary")
    pending = None
    for index, (row, decision) in enumerate(zip(history, state.decision_history, strict=True)):
        if row["selected"] != decision.selected_action.model_dump(mode="json"):
            raise ValueError("History action differs from checkpoint")
        if row["result"]["status"] == "PLANNED":
            if (
                index != len(history) - 1
                or pending_observer is None
                or row["selected"]["parameters"]["tool"] != "Run Experiment"
                or decision.actual_outcome is not None
            ):
                raise ValueError("Only the final pending experiment may be observed for recovery")
            pending = row
        elif row["result"] != decision.actual_outcome:
            raise ValueError("History result differs or remains pending")
    attempts = sorted((parent / "tools/experiments").glob("attempt-*"))
    recovered = None
    reconciliation = None
    if pending is not None:
        if not attempts or (attempts[-1] / "RESULT.json").exists():
            raise ValueError("Pending history must bind the last unresolved experiment attempt")
        recovered = ExecutionResult.model_validate(pending_observer(attempts[-1].name))
        source_id = pending["result"].get("data", {}).get("source_execution_action_id")
        if recovered.action_id != source_id:
            raise ValueError("Observed remote execution does not match the pending action")
        if recovered.status == ExecutionStatus.PLANNED:
            raise ValueError("Original experiment remains unresolved; observe it, never relaunch")
        if recovered.data.get("cost_complete") is not True:
            raise ValueError(
                "Terminal experiment cost is unresolved; cannot spend remaining budget"
            )
        for field in ("experiments", "gpu_hours", "wall_time_hours"):
            cost = recovered.cost.get(field)
            if cost is None or not math.isfinite(cost) or cost < 0:
                raise ValueError("Recovered experiment needs complete finite costs")
        rebound = recovered.model_copy(
            update={
                "action_id": pending["selected"]["action_id"],
                "data": {
                    **recovered.data,
                    "source_execution_action_id": source_id,
                    "tool_interface_sha256": pending["selected"]["parameters"][
                        "tool_interface_sha256"
                    ],
                },
            }
        )
        reconciliation = {
            "original_pending_result": pending["result"],
            "observed_result": recovered.model_dump(mode="json"),
            "attempt": attempts[-1].name,
            "relaunch_performed": False,
        }
        for field in ("experiments", "gpu_hours", "wall_time_hours"):
            delta = rebound.cost[field] - pending["result"]["cost"].get(field, 0)
            if delta < 0:
                raise ValueError("Recovered cost cannot reduce already accounted resource use")
            setattr(state.resource_usage, field, getattr(state.resource_usage, field) + delta)
        pending["result"] = rebound.model_dump(mode="json")
        decision = state.decision_history[-1]
        decision.actual_outcome = pending["result"]
        decision.executor_result_id = rebound.result_id
        state.observations.append(
            ResearchObservation(
                observation_id="recovered-" + rebound.result_id,
                source_result_id=rebound.result_id,
                statement="Observation-only recovery of the original pending experiment: "
                + rebound.model_dump_json(),
            )
        )
        state.revision += 1
    seconds = 0.0
    for index, attempt in enumerate(attempts, 1):
        if attempt.name != f"attempt-{index:03d}":
            raise ValueError("Non-contiguous experiment ledger")
        result = (
            recovered.model_dump(mode="json")
            if recovered is not None and attempt == attempts[-1]
            else json.loads((attempt / "RESULT.json").read_text())
        )
        if result["status"] == "PLANNED" or result["data"].get("cost_complete") is not True:
            raise ValueError("Pending or unknown-cost experiments cannot be continued here")
        seconds += result["cost"]["wall_time_hours"] * 3600
    if (
        state.resource_usage.experiments != len(attempts)
        or abs(state.resource_usage.wall_time_hours * 3600 - seconds) > 0.01
    ):
        raise ValueError("Checkpoint experiment accounting differs")
    latest = {}
    for row in history:
        selected = row["selected"]["parameters"]
        if selected["tool"] == "Write File" and row["result"]["status"] == "SUCCEEDED":
            latest[selected["arguments"]["file_name"]] = selected["arguments"]["content"]
    for name, content in latest.items():
        path = (parent / "candidate" / name).resolve(strict=True)
        if not path.is_relative_to(parent / "candidate") or path.read_text() != content:
            raise ValueError("Current candidate differs from the last successful write")
    sources = ("candidate", "tools/experiments", "logs/provider_calls")
    for locator in sources:
        source = parent / locator
        if source.is_symlink() or any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("Continuation inputs cannot contain symbolic links")
        if (output / locator).exists():
            raise ValueError("Continuation destination is not fresh")
    lineage = {
        "parent_run": str(parent),
        "parent_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "parent_terminal_sha256": hashlib.sha256((parent / "RESULT.json").read_bytes()).hexdigest(),
        "inherited_turns": len(history),
        "inherited_experiments": len(attempts),
        "inherited_execution_seconds": seconds,
        "inherited_api_accounting": ledger,
        "new_independent_trial": False,
        "historical_prefix_not_new_execution": True,
        "pending_reconciliation": reconciliation,
    }
    # One child owns the remaining budget. A second child must not independently
    # spend the same remaining experiment/API allowance.
    claims = parent.parent / "continuation_claims"
    claims.mkdir(exist_ok=True)
    claim_key = hashlib.sha256(str(parent).encode()).hexdigest()
    with (claims / f"{claim_key}.json").open("x") as stream:
        json.dump({"parent_run": str(parent), "child_run": str(output)}, stream)
    for locator in sources:
        shutil.copytree(parent / locator, output / locator)
    if recovered is not None:
        with (output / "tools/experiments" / attempts[-1].name / "RESULT.json").open("x") as stream:
            stream.write(recovered.model_dump_json(indent=2))
    return state, history, lineage

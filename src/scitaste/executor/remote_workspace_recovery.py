"""Observe a checkpoint's last pending remote job in an isolated child snapshot."""

import json
import math
import shutil
import time

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.remote_workspace_tool import RemoteWorkspaceResource, RunRemoteWorkspace
from scitaste.state.research_state import ResearchObservation


def reconcile_pending_remote(*, parent, output, plan, state, history):
    row = history[-1]
    original = row["result"]
    if (
        row["selected"]["parameters"]["tool"] != "Run Remote"
        or original["status"] != "PLANNED"
        or state.decision_history[-1].actual_outcome is not None
    ):
        raise ValueError("Only the original final pending remote action can be reconciled")
    recovery = output / "remote-recovery"
    recovery.mkdir(exist_ok=False)
    for name in ("workspace", "remote_jobs"):
        source = parent / name
        if source.is_symlink() or any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("Remote recovery inputs cannot contain symbolic links")
        shutil.copytree(source, recovery / name)
    resource = RemoteWorkspaceResource.model_validate(plan["remote_workspace"]["resource"])
    tool = RunRemoteWorkspace(
        resource=resource,
        output=recovery / "remote_jobs",
        run_id=parent.name,
        resume=True,
        artifact_root=parent.parent.parent,
    )
    started = time.monotonic()
    raw = ExecutionResult.model_validate(
        tool.call(
            row["selected"]["parameters"]["arguments"],
            workspace_root=recovery / "workspace",
            runtime_deadline=time.time() + min(resource.wall_seconds + 30, 7200),
            observation_only=True,
        )
    )
    if raw.status == ExecutionStatus.PLANNED:
        raise ValueError(
            "Remote job remains unresolved; retained observation has not relaunched it"
        )
    if (
        raw.action_id != original["data"].get("source_execution_action_id")
        or raw.data.get("cost_complete") is not True
    ):
        raise ValueError("Remote identity or terminal cost is unresolved")
    for field in ("experiments", "gpu_hours", "wall_time_hours"):
        value = raw.cost.get(field)
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError("Recovery requires complete finite nonnegative execution costs")
        delta = value - original["cost"].get(field, 0)
        if delta < 0:
            raise ValueError("Recovery cannot erase already accounted resource use")
        setattr(state.resource_usage, field, getattr(state.resource_usage, field) + delta)
    rebound = raw.model_copy(
        update={
            "action_id": row["selected"]["action_id"],
            "data": {
                **raw.data,
                "source_execution_action_id": raw.action_id,
                "tool_interface_sha256": row["selected"]["parameters"]["tool_interface_sha256"],
            },
        }
    )
    row["result"] = rebound.model_dump(mode="json")
    decision = state.decision_history[-1]
    decision.actual_outcome = row["result"]
    decision.executor_result_id = rebound.result_id
    state.observations.append(
        ResearchObservation(
            observation_id="remote-recovery-" + rebound.result_id,
            source_result_id=rebound.result_id,
            statement="Observed original pending remote job: " + rebound.model_dump_json(),
        )
    )
    state.revision += 1
    receipt = {
        "original_pending_result": original,
        "observed_result": raw.model_dump(mode="json"),
        "relaunch_performed": False,
        "duration_seconds": time.monotonic() - started,
        "prospective_taste_capture_reconciled": False,
    }
    with (recovery / "RECONCILIATION.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
    return recovery, receipt

"""Convert a collected unlearning receipt into framework-neutral evidence.

Observation never launches or retries a job. A missing terminal receipt remains
PLANNED, not a failed experiment or a zero score.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from scitaste.executor.base import ExecutionResult, ExecutionStatus

METRICS = {
    "total_score",
    "forgetting_quality",
    "unlearn_retain_accuracy",
    "unlearn_test_accuracy",
    "unlearn_forget_accuracy",
    "retrain_retain_accuracy",
    "retrain_test_accuracy",
    "retrain_forget_accuracy",
}


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("Receipt must be a bounded regular file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Receipt must be an object")
    return value


def collect_unlearning_result(
    root: Path,
    *,
    action_id: str,
    contract_sha256: str,
    observation_only: bool = False,
) -> ExecutionResult:
    """Validate collected receipts against the controller's committed contract."""
    contract_path = root / "CONTRACT.json"
    contract = _read(contract_path)
    if hashlib.sha256(contract_path.read_bytes()).hexdigest() != contract_sha256:
        raise ValueError("Experiment contract differs from selected action")
    if (
        contract.get("task_id") != "mlrc-machine-unlearning-development"
        or contract.get("replicas") != 10
        or contract.get("formal_evidence") is not False
    ):
        raise ValueError("Unexpected unlearning protocol")
    data: dict[str, Any] = {
        "contract_sha256": contract_sha256,
        "primary_metric": "total_score",
        "primary_value": None,
        "formal_evidence_eligible": False,
        "observation_only": observation_only,
        "historical_import_not_native_execution": observation_only,
        "cost_complete": False,
    }
    status = ExecutionStatus.PLANNED
    cost: dict[str, float] = {}
    error = None
    terminal = root / "PROCESS_RESULT.json"
    if terminal.exists():
        process = _read(terminal)
        terminal_status = process.get("status")
        if terminal_status not in {"SUCCEEDED", "FAILED", "TIMED_OUT", "NOT_STARTED"}:
            raise ValueError("Unknown terminal process status")
        status = {
            "SUCCEEDED": ExecutionStatus.SUCCEEDED,
            "NOT_STARTED": ExecutionStatus.SKIPPED,
            "FAILED": ExecutionStatus.FAILED,
            "TIMED_OUT": ExecutionStatus.FAILED,
        }[terminal_status]
        if terminal_status == "NOT_STARTED":
            data["cost_complete"] = True
        else:
            elapsed = process.get("elapsed_seconds")
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
                raise ValueError("Terminal run lacks measured elapsed time")
            if not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("Invalid elapsed time")
            data["cost_complete"] = True
            data["gpu_cost_basis"] = "single-card wall-time reservation, not utilization"
            if not observation_only:
                cost = {
                    "experiments": 1.0,
                    "wall_time_hours": elapsed / 3600,
                    "gpu_hours": elapsed / 3600,
                }
        if status == ExecutionStatus.FAILED:
            error = f"Unlearning process {terminal_status}"
        if status == ExecutionStatus.SUCCEEDED:
            score = _read(root / "SCORE.json")
            if (
                process.get("exit_code") != 0
                or score.get("status") != "SUCCEEDED"
                or score.get("replicas") != 10
                or score.get("formal_evidence") is not False
            ):
                raise ValueError("Incomplete successful evaluation")
            for name in ("seed", "gpu_uuid", "protocol_amendment"):
                if score.get(name) != contract.get(name):
                    raise ValueError(f"Score identity mismatch: {name}")
            metrics = score.get("metrics", {})
            if set(metrics) != METRICS:
                raise ValueError("Missing component metrics")
            for name, value in metrics.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("Invalid numeric metric")
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Non-finite or negative metric")
                if name.endswith("accuracy") and value > 1:
                    raise ValueError("Invalid accuracy")
            rar, tar = metrics["retrain_retain_accuracy"], metrics["retrain_test_accuracy"]
            if rar <= 0 or tar <= 0:
                raise ValueError("Undefined reference ratios")
            composite = (
                metrics["forgetting_quality"]
                * metrics["unlearn_retain_accuracy"]
                / rar
                * metrics["unlearn_test_accuracy"]
                / tar
            )
            if not math.isclose(composite, metrics["total_score"], rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError("Composite score disagrees with components")
            for replica in range(10):
                receipt = _read(root / "exchange" / f"replica-{replica:02d}" / "RECEIPT.json")
                if (
                    receipt.get("replica") != replica
                    or receipt.get("seed") != contract["seed"] + replica
                    or receipt.get("candidate_python_imported_in_scorer") is not False
                ):
                    raise ValueError("Replica receipt differs from fixed protocol")
            data.update(primary_value=metrics["total_score"], metrics=metrics)
    return ExecutionResult(
        result_id=f"unlearning-{contract_sha256}",
        action_id=action_id,
        executor="scitaste-native-remote-unlearning",
        status=status,
        cost=cost,
        data=data,
        error=error,
        observations=[f"Unlearning development: {status}; score={data['primary_value']}"],
    )

import hashlib
import json

import pytest

from scitaste.executor.base import ExecutionStatus
from scitaste.executor.unlearning_result import collect_unlearning_result


def test_complete_and_unresolved_unlearning_receipts(tmp_path):
    contract = {
        "task_id": "mlrc-machine-unlearning-development",
        "replicas": 10,
        "formal_evidence": False,
        "seed": 42,
        "gpu_uuid": "GPU-fixture",
        "protocol_amendment": "isolated-per-replica-seeds-and-eval-mode-v1",
    }
    path = tmp_path / "CONTRACT.json"
    path.write_text(json.dumps(contract))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    kwargs = {"action_id": "fixture", "contract_sha256": digest}
    waiting = collect_unlearning_result(tmp_path, **kwargs)
    assert waiting.status == ExecutionStatus.PLANNED
    assert waiting.data["primary_value"] is None and not waiting.cost
    (tmp_path / "PROCESS_RESULT.json").write_text(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "exit_code": 0,
                "elapsed_seconds": 360,
            }
        )
    )
    metrics = {
        "total_score": 0.5,
        "forgetting_quality": 0.5,
        "unlearn_retain_accuracy": 0.8,
        "unlearn_test_accuracy": 0.7,
        "unlearn_forget_accuracy": 0.6,
        "retrain_retain_accuracy": 0.8,
        "retrain_test_accuracy": 0.7,
        "retrain_forget_accuracy": 0.5,
    }
    score = {**contract, "status": "SUCCEEDED", "metrics": metrics}
    (tmp_path / "SCORE.json").write_text(json.dumps(score))
    for replica in range(10):
        root = tmp_path / "exchange" / f"replica-{replica:02d}"
        root.mkdir(parents=True)
        (root / "RECEIPT.json").write_text(
            json.dumps(
                {
                    "replica": replica,
                    "seed": 42 + replica,
                    "candidate_python_imported_in_scorer": False,
                }
            )
        )
    result = collect_unlearning_result(tmp_path, **kwargs)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.cost["experiments"] == 1
    assert result.data["primary_value"] == 0.5
    assert not result.data["formal_evidence_eligible"]
    score["metrics"]["total_score"] = 0.9
    (tmp_path / "SCORE.json").write_text(json.dumps(score))
    with pytest.raises(ValueError, match="Composite"):
        collect_unlearning_result(tmp_path, **kwargs)

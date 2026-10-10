"""Integrity checks that prevent irreversible wrong-label/coverage scoring."""

import numpy as np
import pytest

from scitaste.benchmark.user_shift_task_data import reviewer_metrics, target_assets


def labels():
    return {
        "review_id": np.arange(4),
        "label": np.array([0, 0, 1, 1]),
        "user": np.array(["a", "a", "a", "b"]),
    }


def test_user_percentile_is_unweighted_and_ids_are_aligned():
    probabilities = np.eye(5)[[0, 0, 1, 0]][::-1]
    metrics = reviewer_metrics(labels(), np.arange(4)[::-1], probabilities)
    assert metrics["accuracy"] == 0.75
    assert metrics["accuracy_10th_percentile"] == pytest.approx(0.1)
    assert metrics["users"] == 2
    assert metrics["reviews"] == 4


@pytest.mark.parametrize("ids", [np.array([0, 1, 2, 2]), np.array([0, 1, 2, 5])])
def test_reject_duplicate_or_foreign_prediction_ids(ids):
    with pytest.raises(ValueError, match="exactly cover"):
        reviewer_metrics(labels(), ids, np.eye(5)[[0, 0, 1, 1]])


def test_reject_unormalized_predictions():
    with pytest.raises(ValueError, match="normalized"):
        reviewer_metrics(labels(), np.arange(4), np.ones((4, 5)))


def test_confirmation_protocol_is_explicit_and_legacy_contract_is_unchanged(tmp_path):
    import json

    (tmp_path / "PACK.json").write_text(
        json.dumps({"transfer_files": ["target/query.jsonl", "target/QUERY.json"]})
    )
    assert target_assets(tmp_path) == ["query.jsonl", "QUERY.json"]
    assert target_assets(tmp_path, public_metadata=("PROTOCOL.json",)) == [
        "query.jsonl",
        "QUERY.json",
        "PROTOCOL.json",
    ]
    with pytest.raises(ValueError, match="public protocol"):
        target_assets(tmp_path, public_metadata=("query-labels.npz",))

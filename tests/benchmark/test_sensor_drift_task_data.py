"""Protect the one-time scientific score boundary, not another repository gate."""

import numpy as np
import pytest

from scitaste.benchmark.sensor_drift_task_data import probability_metrics


def packet():
    labels = {"observation_id": np.array([10, 20, 30]), "target": np.array([0, 1, 0])}
    probabilities = np.eye(6)[[0, 1, 0]]
    prediction = {
        "observation_id": labels["observation_id"].copy(),
        "probabilities": probabilities,
        "valid": np.ones(3, dtype=bool),
        "seconds": np.zeros(3),
    }
    return labels, prediction


def test_proper_score_alignment_and_absent_classes():
    labels, prediction = packet()
    prediction = {key: value[::-1] for key, value in prediction.items()}
    metrics = probability_metrics(labels, prediction)
    assert metrics["multiclass_brier"] == 0
    assert metrics["accuracy"] == 1
    assert metrics["balanced_accuracy_present_classes"] == 1
    assert metrics["class_recall"] == [1, 1, None, None, None, None]


def test_declared_failure_is_missing_not_survivor_mean():
    labels, prediction = packet()
    prediction["valid"][1] = False
    metrics = probability_metrics(labels, prediction)
    assert metrics["multiclass_brier"] is None
    assert metrics["accuracy"] is None
    assert metrics["declared_failure_fraction"] == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    "corruption", ["duplicate", "nonfinite", "unnormalized", "complex", "negative_cost"]
)
def test_invalid_complete_outputs_fail_closed(corruption):
    labels, prediction = packet()
    if corruption == "duplicate":
        prediction["observation_id"][0] = 20
    elif corruption == "nonfinite":
        prediction["probabilities"][0, 0] = np.nan
    elif corruption == "unnormalized":
        prediction["probabilities"][0, 0] = 0.4
    elif corruption == "complex":
        prediction["probabilities"] = prediction["probabilities"].astype(complex)
    else:
        prediction["seconds"][0] = -1
    with pytest.raises(ValueError):
        probability_metrics(labels, prediction)


def test_zero_true_class_probability_has_explicit_log_loss_clip():
    labels, prediction = packet()
    prediction["probabilities"] = np.eye(6)[[2, 2, 2]]
    metrics = probability_metrics(labels, prediction)
    assert metrics["multiclass_brier"] == 2
    assert metrics["log_loss_clipped_fraction"] == 1
    assert metrics["log_loss"] == pytest.approx(-np.log(1e-15))

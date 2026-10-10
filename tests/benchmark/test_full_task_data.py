import pandas as pd
import pytest

from scitaste.benchmark.full_task_data import (
    prediction_metrics,
    recipe_groups,
    summarize_claim_judgments,
)


def test_recipe_groups_are_transitive_and_target_independent():
    frame = pd.DataFrame({"cement": [1.0, 1.4, 1.8, 5.0], "age": [1, 3, 28, 7]})
    groups, _ = recipe_groups(frame, ["cement"])
    assert groups[0] == groups[1] == groups[2]
    assert groups[3] != groups[0]


def test_prediction_denominator_and_group_weighting():
    labels = pd.DataFrame(
        {"row_id": ["a", "b", "c"], "group_id": ["g1", "g1", "g2"], "target": [0, 0, 0]}
    )
    predictions = pd.DataFrame({"row_id": ["c", "b", "a"], "prediction": [9, 0, 0]})
    scores = prediction_metrics(labels, predictions)
    assert scores["group_macro_mae"] == 4.5
    assert scores["row_mae"] == 3
    with pytest.raises(ValueError, match="exactly"):
        prediction_metrics(labels, predictions.iloc[:2])
    with pytest.raises(ValueError, match="Nonfinite"):
        prediction_metrics(labels, predictions.assign(prediction=float("nan")))


def test_empty_claim_list_cannot_score_as_grounded():
    protocol = {"claim_rubric": [{"claim_id": "main"}]}
    with pytest.raises(ValueError, match="exactly one"):
        summarize_claim_judgments(protocol, [])
    result = summarize_claim_judgments(
        protocol, [{"claim_id": "main", "status": "insufficient", "reason": "Omitted"}]
    )
    assert result["counts"]["insufficient"] == 1

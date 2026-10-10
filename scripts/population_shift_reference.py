"""Ordinary source-only probability controls; no national or causal claims."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

METHODS = ("constant", "logistic", "histogram_boosting")


def fit(train):
    weight = train["weight"] / np.mean(train["weight"])
    numeric = [0, 2, 7]
    categorical = [1, 3, 4, 5, 6, 8, 9]
    encoder = ColumnTransformer(
        [
            ("numeric", StandardScaler(), numeric),
            ("category", OneHotEncoder(handle_unknown="ignore"), categorical),
        ]
    )
    logistic = make_pipeline(encoder, LogisticRegression(max_iter=2000, C=1.0))
    logistic.fit(train["x"], train["target"], logisticregression__sample_weight=weight)
    # Tree splits use the declared raw codes; no ordinal causal meaning is implied.
    booster = HistGradientBoostingClassifier(
        max_iter=100,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=7,
    )
    booster.fit(train["x"], train["target"], sample_weight=weight)
    return {
        "constant": float(np.average(train["target"], weights=train["weight"])),
        "logistic": logistic,
        "histogram_boosting": booster,
    }


def probabilities(model, x):
    if isinstance(model, float):
        return np.tile([1.0 - model, model], (len(x), 1))
    return model.predict_proba(x)


def run(data, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with np.load(data / "train.npz", allow_pickle=False) as train:
        models = fit(train)
    fit_seconds = time.monotonic() - started
    if (data / "QUERY.json").is_file():
        contexts = json.loads((data / "QUERY.json").read_text())["contexts"]
    else:
        contexts = {"discovery": "discovery.npz", "validation": "validation.npz"}
    for context, filename in contexts.items():
        with np.load(data / filename, allow_pickle=False) as query:
            for method, model in models.items():
                start = time.monotonic()
                predicted = probabilities(model, query["x"])
                elapsed = time.monotonic() - start
                np.savez_compressed(
                    output / f"{context}--{method}.npz",
                    person_id=query["person_id"],
                    probabilities=predicted,
                    valid=np.ones(len(predicted), dtype=bool),
                    seconds=np.full(len(predicted), elapsed / len(predicted)),
                )
    (output / "RUN.json").write_text(
        json.dumps(
            {
                "fit_seconds": fit_seconds,
                "elapsed_seconds": time.monotonic() - started,
                "methods": list(models),
                "primary_is_not_private_selected": True,
                "role": "Ordinary feasibility controls, not an AutoResearch system or new method",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.data, args.output)

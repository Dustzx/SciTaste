"""Registered dataset-backed acceptance experiment for native execution."""

from __future__ import annotations

import json
from pathlib import Path

DATASET = Path("/datasets/conflict-pivot-cases")


def accuracy(truth: list[int], predictions: list[int]) -> float:
    if len(truth) != len(predictions):
        raise ValueError("truth and predictions must have equal length")
    return sum(truth[index] == predictions[index] for index in range(len(truth))) / len(truth)


cases = json.loads(DATASET.read_text(encoding="utf-8"))
measurements = []
for replicate_id, case in cases.items():
    baseline = accuracy(case["truth"], case["matched_baseline"])
    candidate = accuracy(case["truth"], case["conflict_aware"])
    measurements.append(
        {
            "replicate_id": replicate_id,
            "metrics": {
                "baseline_correct_pivot_rate": baseline,
                "conflict_aware_correct_pivot_rate": candidate,
                "correct_pivot_delta": candidate - baseline,
            },
        }
    )

print(
    "SCITASTE_MEASUREMENTS_JSON="
    + json.dumps(
        {"schema_version": "1.0", "measurements": measurements},
        sort_keys=True,
        separators=(",", ":"),
    )
)

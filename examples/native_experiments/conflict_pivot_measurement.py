"""Small deterministic CPU experiment used by the offline Full Workflow case."""

from __future__ import annotations

import json

CASES = {
    "seed-7": {
        "truth": [1, 0, 1, 1, 0, 1, 0, 0, 1, 0],
        "matched_baseline": [1, 0, 0, 1, 0, 1, 1, 0, 1, 1],
        "conflict_aware": [1, 0, 1, 1, 0, 1, 1, 0, 1, 1],
    },
    "seed-19": {
        "truth": [0, 1, 1, 0, 1, 0, 1, 0, 0, 1],
        "matched_baseline": [0, 1, 1, 1, 1, 0, 0, 0, 1, 1],
        "conflict_aware": [0, 1, 1, 0, 1, 0, 0, 0, 1, 1],
    },
    "seed-31": {
        "truth": [1, 1, 0, 0, 1, 0, 0, 1, 1, 0],
        "matched_baseline": [1, 0, 0, 0, 1, 1, 0, 1, 0, 0],
        "conflict_aware": [1, 1, 0, 0, 1, 1, 0, 1, 0, 0],
    },
}


def accuracy(truth: list[int], predictions: list[int]) -> float:
    if len(truth) != len(predictions):
        raise ValueError("truth and predictions must have equal length")
    return sum(truth[index] == predictions[index] for index in range(len(truth))) / len(truth)


measurements = []
for replicate_id, case in CASES.items():
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

"""Held-out inference-only entrypoint for MLRC Perception.

This module is mounted read-only into the candidate sandbox.  The mounted data
tree contains test features and a redacted manifest, but never scorer labels.
It deliberately emits a prediction identity instead of an objective score.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

_MARKER = "SCITASTE_BENCHMARK_PREDICTION_JSON="
_MAX_PREDICTION_BYTES = 536_870_912
_MAX_PREDICTIONS = 3_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="my_method")
    parser.add_argument("--result-task-id", required=True)
    args = parser.parse_args(argv)

    workspace = Path.cwd().resolve(strict=True)
    sys.path.insert(0, str(workspace))
    evaluation = importlib.import_module("evaluation")
    methods = importlib.import_module("methods")
    handlers = methods.all_method_handlers()
    if args.method not in handlers:
        raise ValueError(f"unknown perception method: {args.method}")
    method = handlers[args.method](args.method)
    evaluation.evaluate_model(method, "test")

    relative = Path("output") / f"{args.method}_test_results.json"
    prediction = (workspace / relative).resolve(strict=True)
    if not prediction.is_relative_to(workspace / "output") or prediction.is_symlink():
        raise ValueError("held-out prediction escaped the writable output directory")
    raw = prediction.read_bytes()
    if not raw or len(raw) > _MAX_PREDICTION_BYTES:
        raise ValueError("held-out prediction has an invalid size")
    count = _validate_predictions(json.loads(raw))
    payload = {
        "schema_version": "1.0",
        "task_id": args.result_task_id,
        "phase": "test-inference",
        "method": args.method,
        "prediction_locator": relative.as_posix(),
        "prediction_sha256": hashlib.sha256(raw).hexdigest(),
        "prediction_bytes": len(raw),
        "prediction_count": count,
        "objective_score_exposed": False,
        "heldout_labels_visible": False,
    }
    print(_MARKER + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _validate_predictions(payload: Any) -> int:
    if not isinstance(payload, dict) or len(payload) > 10_000:
        raise ValueError("held-out predictions must be a bounded video mapping")
    count = 0
    for video_id, value in payload.items():
        if not isinstance(video_id, str) or not video_id or not isinstance(value, dict):
            raise ValueError("held-out prediction video entry is invalid")
        if set(value) != {"action_localisation"}:
            raise ValueError("held-out prediction entry has unexpected fields")
        actions = value["action_localisation"]
        if not isinstance(actions, list):
            raise ValueError("held-out prediction actions must be a list")
        count += len(actions)
        if count > _MAX_PREDICTIONS:
            raise ValueError("held-out prediction count exceeds its bound")
        for action in actions:
            if not isinstance(action, dict) or set(action) != {"label", "score", "timestamps"}:
                raise ValueError("held-out prediction action has unexpected fields")
            label = _finite_number(action["label"])
            score = _finite_number(action["score"])
            timestamps = action["timestamps"]
            if label < 0 or not label.is_integer() or not 0 <= score <= 1:
                raise ValueError("held-out prediction label or score is invalid")
            if not isinstance(timestamps, list) or len(timestamps) != 2:
                raise ValueError("held-out prediction timestamps are invalid")
            start, end = (_finite_number(item) for item in timestamps)
            if start < 0 or end < start:
                raise ValueError("held-out prediction segment is invalid")
    return count


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a prediction number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("prediction number is invalid") from exc
    if not math.isfinite(result):
        raise ValueError("prediction number must be finite")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

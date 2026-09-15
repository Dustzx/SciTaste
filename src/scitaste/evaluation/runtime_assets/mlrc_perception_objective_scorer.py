"""Standalone, scorer-owned MLRC Perception temporal-detection metric.

The scorer receives exact ground-truth and prediction hashes.  It imports no
candidate/workspace module and reproduces the upstream interpolated mAP at
tIoU thresholds 0.1 through 0.5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

_OBJECTIVE_MARKER = "SCITASTE_BENCHMARK_OBJECTIVE_JSON="
_RECEIPT_MARKER = "SCITASTE_MLRC_SCORE_RECEIPT_JSON="
_THRESHOLDS = np.linspace(0.1, 0.5, 5)
_MAX_GROUND_TRUTH_BYTES = 67_108_864
_MAX_PREDICTION_BYTES = 536_870_912
_MAX_VIDEOS = 10_000
_MAX_PREDICTIONS = 3_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--ground-truth-sha256", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--predictions-sha256", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)

    started = perf_counter()
    ground_truth_raw = _bound_bytes(
        args.ground_truth,
        args.ground_truth_sha256,
        maximum_bytes=_MAX_GROUND_TRUTH_BYTES,
        label="ground truth",
    )
    prediction_raw = _bound_bytes(
        args.predictions,
        args.predictions_sha256,
        maximum_bytes=_MAX_PREDICTION_BYTES,
        label="predictions",
    )
    ground_truth, labels = _load_ground_truth(json.loads(ground_truth_raw))
    predictions, prediction_count = _load_predictions(json.loads(prediction_raw), labels)
    score, per_threshold = _mean_average_precision(ground_truth, predictions, labels)
    elapsed = max(0.0, perf_counter() - started)
    scorer_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt = {
        "schema_version": "1.0",
        "task_id": args.task_id,
        "method": args.method,
        "metric": "mean_average_precision",
        "metric_direction": "higher",
        "score": score,
        "tiou_thresholds": [float(item) for item in _THRESHOLDS],
        "per_threshold_map": per_threshold,
        "ground_truth_sha256": args.ground_truth_sha256,
        "prediction_sha256": args.predictions_sha256,
        "scorer_sha256": scorer_sha256,
        "ground_truth_instance_count": sum(len(items) for items in ground_truth.values()),
        "prediction_count": prediction_count,
        "label_count": len(labels),
        "heldout_labels_exposed_to_candidate": False,
        "model_invocations": 0,
        "secondary_llm_judge_invoked": False,
    }
    receipt["receipt_sha256"] = _content_sha256(receipt)
    if args.receipt is not None:
        _write_new_json(args.receipt, receipt)
    objective = {
        "schema_version": "1.0",
        "task_id": args.task_id,
        "phase": "test",
        "method": args.method,
        "score": score,
        "elapsed_seconds": elapsed,
        "secondary_llm_judge_invoked": False,
    }
    print(_RECEIPT_MARKER + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    print(_OBJECTIVE_MARKER + json.dumps(objective, sort_keys=True, separators=(",", ":")))
    return 0


def _bound_bytes(path: Path, expected_sha256: str, *, maximum_bytes: int, label: str) -> bytes:
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise ValueError(f"{label} SHA-256 is invalid")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    size = path.stat().st_size
    if not size or size > maximum_bytes:
        raise ValueError(f"{label} has an invalid size")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch")
    return raw


def _load_ground_truth(
    payload: Any,
) -> tuple[dict[int, list[tuple[str, float, float]]], tuple[int, ...]]:
    if not isinstance(payload, dict) or not payload or len(payload) > _MAX_VIDEOS:
        raise ValueError("ground truth must be a bounded non-empty video mapping")
    by_label: dict[int, list[tuple[str, float, float]]] = {}
    for video_id, value in payload.items():
        if not isinstance(video_id, str) or not video_id or not isinstance(value, dict):
            raise ValueError("ground-truth video entry is invalid")
        actions = value.get("action_localisation")
        metadata = value.get("metadata")
        if not isinstance(actions, list) or not isinstance(metadata, dict):
            raise ValueError("ground-truth video fields are invalid")
        if str(metadata.get("split", "")).casefold() != "test":
            raise ValueError("ground truth contains a non-test item")
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("ground-truth action is invalid")
            label = action.get("label_id")
            timestamps = action.get("timestamps")
            if isinstance(label, bool) or not isinstance(label, int) or label < 0:
                raise ValueError("ground-truth label is invalid")
            if not isinstance(timestamps, list) or len(timestamps) != 2:
                raise ValueError("ground-truth timestamps are invalid")
            start, end = (_finite_number(item) / 1_000_000.0 for item in timestamps)
            if start < 0 or end < start:
                raise ValueError("ground-truth segment is invalid")
            by_label.setdefault(label, []).append((video_id, start, end))
    labels = tuple(sorted(by_label))
    if not labels:
        raise ValueError("ground truth contains no labeled instances")
    return by_label, labels


def _load_predictions(
    payload: Any,
    labels: tuple[int, ...],
) -> tuple[dict[int, list[tuple[str, float, float, float]]], int]:
    if not isinstance(payload, dict) or len(payload) > _MAX_VIDEOS:
        raise ValueError("predictions must be a bounded video mapping")
    admitted = set(labels)
    by_label: dict[int, list[tuple[str, float, float, float]]] = {}
    count = 0
    for video_id, value in payload.items():
        if not isinstance(video_id, str) or not video_id or not isinstance(value, dict):
            raise ValueError("prediction video entry is invalid")
        if set(value) != {"action_localisation"}:
            raise ValueError("prediction video entry has unexpected fields")
        actions = value["action_localisation"]
        if not isinstance(actions, list):
            raise ValueError("prediction actions must be a list")
        count += len(actions)
        if count > _MAX_PREDICTIONS:
            raise ValueError("prediction count exceeds its bound")
        for action in actions:
            if not isinstance(action, dict) or set(action) != {"label", "score", "timestamps"}:
                raise ValueError("prediction action has unexpected fields")
            raw_label = _finite_number(action["label"])
            score = _finite_number(action["score"])
            timestamps = action["timestamps"]
            if not raw_label.is_integer() or int(raw_label) not in admitted:
                raise ValueError("prediction label is outside the scorer taxonomy")
            if not 0 <= score <= 1:
                raise ValueError("prediction score is outside [0, 1]")
            if not isinstance(timestamps, list) or len(timestamps) != 2:
                raise ValueError("prediction timestamps are invalid")
            start, end = (_finite_number(item) for item in timestamps)
            if start < 0 or end < start:
                raise ValueError("prediction segment is invalid")
            by_label.setdefault(int(raw_label), []).append((video_id, start, end, score))
    return by_label, count


def _mean_average_precision(
    ground_truth: dict[int, list[tuple[str, float, float]]],
    predictions: dict[int, list[tuple[str, float, float, float]]],
    labels: tuple[int, ...],
) -> tuple[float, list[float]]:
    ap = np.zeros((len(_THRESHOLDS), len(labels)), dtype=float)
    for column, label in enumerate(labels):
        gt = ground_truth[label]
        pred = predictions.get(label, [])
        if not pred:
            continue
        gt_by_video: dict[str, list[tuple[int, float, float]]] = {}
        for index, (video_id, start, end) in enumerate(gt):
            gt_by_video.setdefault(video_id, []).append((index, start, end))
        scores = np.asarray([item[3] for item in pred], dtype=float)
        order = scores.argsort()[::-1]
        true_positive = np.zeros((len(_THRESHOLDS), len(pred)), dtype=float)
        false_positive = np.zeros_like(true_positive)
        locks = np.full((len(_THRESHOLDS), len(gt)), -1, dtype=int)
        for rank, prediction_index in enumerate(order):
            video_id, start, end, _score = pred[int(prediction_index)]
            candidates = gt_by_video.get(video_id)
            if not candidates:
                false_positive[:, rank] = 1
                continue
            overlaps = np.asarray(
                [_segment_iou(start, end, gt_start, gt_end) for _, gt_start, gt_end in candidates]
            )
            sorted_candidates = overlaps.argsort()[::-1]
            for threshold_index, threshold in enumerate(_THRESHOLDS):
                for local_index in sorted_candidates:
                    overlap = overlaps[int(local_index)]
                    if overlap < threshold:
                        false_positive[threshold_index, rank] = 1
                        break
                    global_index = candidates[int(local_index)][0]
                    if locks[threshold_index, global_index] >= 0:
                        continue
                    true_positive[threshold_index, rank] = 1
                    locks[threshold_index, global_index] = rank
                    break
                if not true_positive[threshold_index, rank] and not false_positive[
                    threshold_index, rank
                ]:
                    false_positive[threshold_index, rank] = 1
        tp = np.cumsum(true_positive, axis=1)
        fp = np.cumsum(false_positive, axis=1)
        recall = tp / float(len(gt))
        precision = tp / (tp + fp)
        for threshold_index in range(len(_THRESHOLDS)):
            ap[threshold_index, column] = _interpolated_ap(
                precision[threshold_index], recall[threshold_index]
            )
    per_threshold = ap.mean(axis=1)
    return float(per_threshold.mean()), [float(item) for item in per_threshold]


def _segment_iou(start: float, end: float, gt_start: float, gt_end: float) -> float:
    intersection = max(0.0, min(end, gt_end) - max(start, gt_start))
    union = (end - start) + (gt_end - gt_start) - intersection
    return 0.0 if union <= 0 else intersection / union


def _interpolated_ap(precision: np.ndarray, recall: np.ndarray) -> float:
    padded_precision = np.hstack(([0.0], precision, [0.0]))
    padded_recall = np.hstack(([0.0], recall, [1.0]))
    for index in range(len(padded_precision) - 2, -1, -1):
        padded_precision[index] = max(padded_precision[index], padded_precision[index + 1])
    changed = np.where(padded_recall[1:] != padded_recall[:-1])[0] + 1
    return float(
        np.sum(
            (padded_recall[changed] - padded_recall[changed - 1])
            * padded_precision[changed]
        )
    )


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("numeric value is invalid") from exc
    if not math.isfinite(result):
        raise ValueError("numeric value must be finite")
    return result


def _content_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


if __name__ == "__main__":
    raise SystemExit(main())

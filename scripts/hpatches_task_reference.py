"""Ordinary CPU geometric estimators; not AutoResearch methods or novel policies."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


def corner_errors(expected, predicted, shape, valid):
    errors = np.full(len(expected), np.inf)
    for i in np.flatnonzero(valid):
        height, width = shape[i]
        corners = np.array(
            [[0, 0, 1], [width - 1, 0, 1], [width - 1, height - 1, 1], [0, height - 1, 1]]
        ).T
        truth, proposal = expected[i] @ corners, predicted[i] @ corners
        if (np.abs(truth[2]) < 1e-10).any() or (np.abs(proposal[2]) < 1e-10).any():
            continue
        distance = np.linalg.norm(truth[:2] / truth[2] - proposal[:2] / proposal[2], axis=0)
        if np.isfinite(distance).all():
            errors[i] = distance.mean()
    return errors


def auc(errors, threshold):
    # Conventional corner-error AUC: sorted recall, truncated at the threshold.
    errors = np.sort(np.asarray(errors, dtype=float))
    recall = np.arange(1, len(errors) + 1, dtype=float) / len(errors)
    errors, recall = np.r_[0.0, errors], np.r_[0.0, recall]
    end = np.searchsorted(errors, threshold, side="right")
    x, y = np.r_[errors[:end], threshold], np.r_[recall[:end], recall[end - 1]]
    return float(np.trapezoid(y, x) / threshold)


def predict(data, sampler, iterations):
    homographies = np.zeros((len(data["pair_id"]), 3, 3), dtype=float)
    valid = np.zeros(len(homographies), dtype=bool)
    seconds = np.zeros(len(homographies))
    for i, count in enumerate(data["n_matches"]):
        started = time.monotonic()
        if count >= 4:
            source, target = data["points1"][i, :count], data["points2"][i, :count]
            order = np.argsort(-data["confidence"][i, :count], kind="stable")
            params = cv2.UsacParams()
            params.maxIterations = iterations
            params.confidence = 0.999
            params.threshold = 3.0
            params.randomGeneratorState = int(data["pair_id"][i] % (2**31 - 1))
            params.isParallel = False
            params.sampler = cv2.SAMPLING_PROSAC if sampler == "prosac" else cv2.SAMPLING_UNIFORM
            params.score = cv2.SCORE_METHOD_MAGSAC if sampler == "magsac" else cv2.SCORE_METHOD_MSAC
            params.loMethod = (
                cv2.LOCAL_OPTIM_SIGMA if sampler == "magsac" else cv2.LOCAL_OPTIM_INNER_LO
            )
            params.loIterations = 10
            h, _ = cv2.findHomography(source[order], target[order], params)
            if h is not None and np.isfinite(h).all() and abs(np.linalg.det(h)) > 1e-14:
                homographies[i], valid[i] = h, True
        seconds[i] = time.monotonic() - started
    return {
        "pair_id": data["pair_id"],
        "homography": homographies,
        "valid": valid,
        "seconds": seconds,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    args.output.mkdir(parents=True, exist_ok=False)
    query = args.data / "QUERY.json"
    contexts = (
        json.loads(query.read_text())["contexts"]
        if query.exists()
        else {
            "illumination": "illumination-validation.npz",
            "viewpoint": "viewpoint-validation.npz",
        }
    )
    measurements = []
    for context, file in contexts.items():
        with np.load(args.data / file, allow_pickle=False) as source:
            data = {key: source[key] for key in source.files}
        for sampler in ("uniform", "prosac", "magsac"):
            for iterations in (64, 512):
                method = f"{sampler}_{iterations}"
                proposed = predict(data, sampler, iterations)
                np.savez_compressed(args.output / f"{context}--{method}.npz", **proposed)
                row = {
                    "context": context,
                    "method": method,
                    "seconds": float(proposed["seconds"].sum()),
                    "pairs": len(proposed["pair_id"]),
                }
                if "homography" in data:
                    errors = corner_errors(
                        data["homography"],
                        proposed["homography"],
                        data["shape1"],
                        proposed["valid"],
                    )
                    row.update(
                        auc_5px=auc(errors, 5.0),
                        auc_1px=auc(errors, 1.0),
                        failure_fraction=float(np.mean(~proposed["valid"])),
                    )
                measurements.append(row)
    (args.output / "RUN.json").write_text(
        json.dumps(
            {
                "measurements": measurements,
                "opencv_version": cv2.__version__,
                "scope": (
                    "ordinary controls; subject-estimation accuracy, "
                    "not autonomous research quality"
                ),
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

"""Fixed feasibility references; these are not autonomous research baselines."""

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import torch


def predict(cls, state, images):
    model = cls()
    model.load_state_dict(state)
    model.eval()
    result = []
    with torch.inference_mode():
        for start in range(0, len(images), 128):
            x = torch.from_numpy(images[start : start + 128]).float().div_(255)
            result.append(model(x).softmax(-1).numpy())
    return np.concatenate(result).astype(np.float64)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    torch.set_num_threads(2)
    data = args.data.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("research_cnn", data / "research_cnn.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with np.load(data / "calibration.npz", allow_pickle=False) as packet:
        calibration = {k: packet[k] for k in packet.files}
    with np.load(data / "development_query.npz", allow_pickle=False) as packet:
        query = {k: packet[k] for k in packet.files}
    contexts = json.loads((data / "DEVELOPMENT.json").read_text())["contexts"]
    began = time.monotonic()
    rows = []
    for context in contexts:
        clock = time.monotonic()
        states = [
            torch.load(data / path, weights_only=True, map_location="cpu")
            for path in context["checkpoints"]
        ]
        calib_preds = [
            predict(module.ResearchCNN, state, calibration["images"]) for state in states
        ]
        calib_acc = [float((p.argmax(1) == calibration["labels"]).mean()) for p in calib_preds]
        query_preds = [predict(module.ResearchCNN, state, query["images"]) for state in states]
        average = {k: torch.stack([s[k] for s in states]).mean(0) for k in states[0]}
        predictions = {
            "best_calibration": query_preds[int(np.argmax(calib_acc))],
            "uniform_weights": predict(module.ResearchCNN, average, query["images"]),
            "probability_ensemble": np.mean(query_preds, axis=0),
        }
        for method, probabilities in predictions.items():
            name = context["context_id"] + "--" + method + ".npz"
            np.savez_compressed(
                output / name, image_id=query["image_id"], probabilities=probabilities
            )
            row = {
                "context": context["context_id"],
                "training_block": context["training_block"],
                "method": method,
                "query_accuracy": float((probabilities.argmax(1) == query["labels"]).mean()),
                "query_nll": float(
                    -np.log(
                        np.maximum(
                            probabilities[np.arange(len(query["labels"])), query["labels"]], 1e-12
                        )
                    ).mean()
                ),
                "calibration_individual_accuracy": calib_acc,
                "query_images": len(query["labels"]),
                "fitting_query_labels_used": False,
                "inference_networks": 3 if method == "probability_ensemble" else 1,
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
        print(
            json.dumps(
                {"context_completed": context["context_id"], "seconds": time.monotonic() - clock}
            ),
            flush=True,
        )
    with (output / "RESULT.json").open("x") as stream:
        json.dump(
            {
                "status": "completed",
                "seconds": time.monotonic() - began,
                "rows": rows,
                "task_families": 1,
                "framework_runs": 0,
                "confirmation_labels_accessed": False,
                "formal_evidence_eligible": False,
            },
            stream,
            indent=2,
        )


if __name__ == "__main__":
    main()

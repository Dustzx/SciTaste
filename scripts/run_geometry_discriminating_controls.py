"""Run a declared ranking-information contrast on public geometry observations.

This is a development subject-control experiment, not a framework rerun, hidden
confirmation, full geometry-mechanism identification or a new independent task.
"""

import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import cv2
import numpy as np

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.open_research import digest
from scitaste.benchmark.scientific_design import (
    load_scientific_design,
    scientific_design_sha256,
)
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    pack = args.pack.resolve(strict=True)
    pack.relative_to(root / "evaluations")
    public = pack / "public/confidence-guided-geometry"
    output = args.output.resolve()
    output.relative_to(root / "evaluations")
    suite = load_scientific_design(args.design)
    design = next(d for d in suite.tasks if d.task_id == "confidence-guided-geometry")
    original = json.loads((pack / "PACK.json").read_bytes())
    reference = public / "reference.py"
    files = [reference, public / "PROTOCOL.json"] + [
        public / (context + "-validation.npz") for context in ("illumination", "viewpoint")
    ]
    for path in files:
        path.resolve(strict=True).relative_to(public.resolve(strict=True))
        if digest(path) != original["files"][path.relative_to(pack).as_posix()]:
            raise ValueError("Public task asset changed")
    output.mkdir(parents=True, exist_ok=False)
    methods = (
        ("prosac64_ranked", "prosac", 64, False),
        ("prosac64_permuted", "prosac", 64, True),
        ("uniform64_ranked", "uniform", 64, False),
        ("uniform64_permuted", "uniform", 64, True),
        ("magsac512_reference", "magsac", 512, False),
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "scope": "public development discriminating control",
            "design_id": design.design_id,
            "design_sha256": scientific_design_sha256(design),
            "design_source_sha256": digest(args.design),
            "script": binding(root.parent.parent.parent, Path(__file__).resolve()),
            "assets": [binding(root, p) for p in files],
            "methods": methods,
            "control_id": "confidence_rank_shuffle",
            "rank_permutation_seed": 20261008,
            "matching": (
                "Same correspondence identities, cardinality, confidence marginal, "
                "estimator/scoring/local optimization, threshold, nominal cap and pair seed. "
                "Only confidence assignment/order changes within each sampler pair."
            ),
            "strong_reference": "MAGSAC++/USAC on the same supplied SIFT correspondences",
            "limits": (
                "Uniform pairs also diagnose sensitivity to input order/random draws. "
                "Nominal caps do not equal actual solver work. One permutation per pair; "
                "no repeated-seed inference, coverage filtering or confidence-generation "
                "mechanism is identified. Existing exposed validation scenes only."
            ),
            "new_independent_tasks": 0,
            "private_data_access": False,
            "formal_evidence_eligible": False,
            "supplier_api_calls": 0,
            "gpu_calls": 0,
        },
    )
    spec = importlib.util.spec_from_file_location("frozen_geometry_reference", reference)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cv2.setNumThreads(2)
    started = time.monotonic()
    rows, pairs = [], []
    for context in ("illumination", "viewpoint"):
        with np.load(public / (context + "-validation.npz"), allow_pickle=False) as source:
            data = {key: source[key] for key in source.files}
        permuted = {**data, "confidence": data["confidence"].copy()}
        for i, count in enumerate(data["n_matches"]):
            seed = int.from_bytes(
                hashlib.sha256(f"20261008:{int(data['pair_id'][i])}".encode()).digest()[:8],
                "little",
            )
            permutation = np.random.default_rng(seed).permutation(int(count))
            permuted["confidence"][i, :count] = data["confidence"][i, :count][permutation]
        observed = {}
        for name, sampler, cap, shuffle in methods:
            proposal = module.predict(permuted if shuffle else data, sampler, cap)
            errors = module.corner_errors(
                data["homography"], proposal["homography"], data["shape1"], proposal["valid"]
            )
            prediction = output / f"{context}--{name}.npz"
            np.savez_compressed(prediction, **proposal)
            row = {
                "context": context,
                "method": name,
                "pairs": len(data["pair_id"]),
                "auc5": module.auc(errors, 5.0),
                "failures": int((~proposal["valid"]).sum()),
                "seconds": float(proposal["seconds"].sum()),
                "prediction": binding(root, prediction),
            }
            rows.append(row)
            observed[name] = row
            retain_json(output / f"{context}--{name}.json", row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        pairs.append(
            {
                "context": context,
                "pairs": len(data["pair_id"]),
                "prosac_rank_auc5_difference": (
                    observed["prosac64_ranked"]["auc5"] - observed["prosac64_permuted"]["auc5"]
                ),
                "uniform_order_auc5_difference": (
                    observed["uniform64_ranked"]["auc5"] - observed["uniform64_permuted"]["auc5"]
                ),
            }
        )
    result = {
        "contract_sha256": digest(output / "CONTRACT.json"),
        "measurements": rows,
        "ranking_contrasts": pairs,
        "elapsed_seconds": time.monotonic() - started,
        "opencv_version": cv2.__version__,
        "independent_scene_groups": {"illumination": 6, "viewpoint": 6},
        "pair_counts_are_not_research_task_counts": True,
        "new_independent_tasks": 0,
        "strong_reference_changes_score_and_local_optimization": True,
        "coverage_matched_control_complete": False,
        "scientific_validity_certified": False,
        "formal_evidence_eligible": False,
    }
    retain_json(output / "RESULTS.json", result)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Freeze two same-prefix MLRC Meta-Learning method branches without GPU use.

This prepares one *development qualification fork*, not a released benchmark
case or a measured utility. The official scorer and development data remain
outside the method branch directory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import stat
from pathlib import Path

EUCLIDEAN = "euclidean-prototypes"
NORMALIZED = "unit-normalized-prototypes"
DISTANCE_EXPR = (
    "distance_matrix = (torch.cdist(query_embeddings.unsqueeze(0), \n"
    "        prototypes.unsqueeze(0))**2).squeeze(0)"
)
NORMALIZED_EXPR = (
    "normalized_queries = torch.nn.functional.normalize(query_embeddings, p=2, dim=1)\n"
    "    normalized_prototypes = torch.nn.functional.normalize(prototypes, p=2, dim=1)\n"
    "    distance_matrix = (torch.cdist(normalized_queries.unsqueeze(0), \n"
    "        normalized_prototypes.unsqueeze(0))**2).squeeze(0)"
)


def normalized_helper(source: str) -> str:
    if source.count(DISTANCE_EXPR) != 1:
        raise ValueError("upstream prototype distance expression changed")
    result = source.replace(DISTANCE_EXPR, NORMALIZED_EXPR, 1)
    ast.parse(result)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("MLRC method tree must not contain symbolic links")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("MLRC method tree has a non-regular file")
            result[path.relative_to(root).as_posix()] = _sha256(path)
    if not result:
        raise ValueError("MLRC method tree is empty")
    return result


def prepare(source_method: Path, baseline_receipt: Path, output_root: Path) -> Path:
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError("visual fork output must be new")
    if not source_method.is_dir() or source_method.is_symlink():
        raise ValueError("source method must be a real directory")
    source_manifest = _tree_manifest(source_method)
    if not {"model.py", "helpers_protonet.py", "config.json"} <= set(source_manifest):
        raise ValueError("source method is missing required ProtoNet files")
    receipt = json.loads(baseline_receipt.read_text(encoding="utf-8"))
    if (
        receipt.get("task_id") != "meta-learning"
        or receipt.get("phase") != "dev"
        or receipt.get("heldout_opened") is not False
        or receipt.get("upstream_model_sha256") != source_manifest["model.py"]
    ):
        raise ValueError("source method differs from the qualified development baseline")
    source_helper = (source_method / "helpers_protonet.py").read_text(encoding="utf-8")
    normalized = normalized_helper(source_helper)
    ast.parse((source_method / "model.py").read_text(encoding="utf-8"))
    output_root.mkdir(parents=True)
    branches = output_root / "branches"
    branches.mkdir()
    for action in (EUCLIDEAN, NORMALIZED):
        shutil.copytree(source_method, branches / action, symlinks=False)
    (branches / NORMALIZED / "helpers_protonet.py").write_text(normalized, encoding="utf-8")
    euclidean_manifest = _tree_manifest(branches / EUCLIDEAN)
    normalized_manifest = _tree_manifest(branches / NORMALIZED)
    if euclidean_manifest != source_manifest:
        raise ValueError("unchanged branch differs from the official source method")
    changed = {
        name for name in source_manifest if normalized_manifest.get(name) != source_manifest[name]
    }
    if set(normalized_manifest) != set(source_manifest) or changed != {"helpers_protonet.py"}:
        raise ValueError("normalized branch changed more than the prototype geometry")
    manifest = {
        "schema_version": "1.0",
        "role": "visual-fork-development-qualification-prepared",
        "task_id": "mlrc-meta-learning",
        "phase": "development",
        "source_method": str(source_method),
        "baseline_receipt_sha256": _sha256(baseline_receipt),
        "development_data_manifest_sha256": receipt["development_data_manifest_sha256"],
        "shared_prefix_model_sha256": source_manifest["model.py"],
        "source_method_files": source_manifest,
        "actions": {
            EUCLIDEAN: {
                "meaning": (
                    "retain squared Euclidean distance between unnormalized "
                    "query and class prototypes"
                ),
                "method_files": euclidean_manifest,
            },
            NORMALIZED: {
                "meaning": (
                    "L2-normalize query and class prototypes before the same "
                    "squared Euclidean distance"
                ),
                "method_files": normalized_manifest,
            },
        },
        "shared_execution": {
            "official_development_datasets": 20,
            "official_development_prediction_tasks": 1000,
            "source_seed": 98,
            "train_tasks": 20,
            "validation_tasks": 10,
            "scorer": "unchanged upstream normalized balanced accuracy",
            "per_action_gpu_limit": "one remote RTX 3090, sequential runs",
        },
        "branch_scores": None,
        "formal_evidence_eligible": False,
        "remote_gpu_run_started": False,
    }
    (output_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-method", required=True, type=Path)
    parser.add_argument("--baseline-receipt", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.source_method, args.baseline_receipt, args.output_root))

#!/usr/bin/env python3
"""Freeze a pre-experiment development decision with actual image evidence.

No branch result or private scorer label is read. Four deterministic input
examples illustrate the domains; they do not establish a feature-norm diagnosis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import DecisionMethodRequest
from scitaste.project.models import content_sha256


def prepare(bundle: Path, data: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError("decision package must be new")
    manifest_bytes = (bundle / "MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("role") != "mlrc-meta-visual-fork-remote-execution-bundle":
        raise ValueError("expected frozen MLRC development execution bundle")
    split_bytes = (data / "info/meta_splits.txt").read_bytes()
    if hashlib.sha256(split_bytes).hexdigest() != manifest["development_split_sha256"]:
        raise ValueError("development split differs from execution bundle")
    splits = json.loads(split_bytes)
    selected = []
    for domain in sorted(splits["meta-train"])[:4]:
        images = sorted((data / domain / "images").glob("*"))
        images = [p for p in images if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        if not images:
            raise ValueError(f"no image examples in {domain}")
        selected.append((domain, images[0]))
    artifacts = []
    for domain, path in selected:
        if path.is_symlink() or not path.is_file():
            raise ValueError("image example must be a regular file")
        artifacts.append(
            {
                "artifact_id": f"development-example-{domain}",
                "relative_locator": f"{domain}/{path.name}",
                "media_type": "image/png" if path.suffix.lower() == ".png" else "image/jpeg",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "outcome_data": False,
            }
        )
    payload = {
        "schema_version": "1.0",
        "case_id": content_sha256(
            {
                "bundle": hashlib.sha256(manifest_bytes).hexdigest(),
                "prefix": "before-protonet-development-training",
            }
        ),
        "hypothesis_structure": "competing-candidates",
        "evidence_relation": "underdetermined",
        "bottleneck": "prototype-metric-selection",
        "identifiability": "low",
        "budget_pressure": "limited-training",
        "terminal_readiness": "not-ready",
        "decision_basis": (
            "Choose a prototype distance for cross-domain few-shot image classification. "
            "A randomly initialized ResNet-18 will train for 20 episodic tasks; validation "
            "uses 10 tasks every 5 training tasks. Compare unchanged squared Euclidean "
            "distance to L2-normalizing query embeddings and class prototypes before "
            "the same distance. The change affects both training and prediction logits. "
            "There is no temperature tuning, extra pretraining, or additional training. "
            "Four input examples illustrate development domains. No feature norms, "
            "candidate scores, or downstream errors have been measured for this decision. "
            "Infer expected usefulness cautiously; do not invent a norm-shift diagnosis."
        ),
        "evidence_anchors": [
            "Cross-domain few-shot image classification; normalized balanced accuracy.",
            "Training: 5-way, 10-shot, 20 query images per class; initialization seed 98.",
            "Only prototype geometry differs; both branches share data, seeds and budgets.",
            "Examples: first image of each of the first four sorted meta-train domains; "
            "no performance-based selection.",
            "Each branch has 1,000 development prediction episodes from one source research task.",
        ],
        "evidence_artifacts": artifacts,
        "available_actions": [
            {
                "action_id": "euclidean-prototypes",
                "semantic_role": "preserve-metric",
                "description": "Train and evaluate with unnormalized squared Euclidean distance.",
            },
            {
                "action_id": "unit-normalized-prototypes",
                "semantic_role": "change-metric",
                "description": "L2-normalize queries and prototypes in training and prediction; "
                "keep all other settings.",
            },
        ],
        "native_action_id": "euclidean-prototypes",
        "resource_limits": {"gpu_count": 1.0, "wall_seconds": 1200.0, "train_tasks": 20.0},
        "maximum_steps": 1,
        "timeout_seconds": 1200,
    }
    request = DecisionMethodRequest.model_validate(
        {**payload, "request_sha256": content_sha256(payload)}
    )
    output.mkdir(parents=True)
    for artifact, (_, source) in zip(artifacts, selected, strict=True):
        destination = output / "evidence" / artifact["relative_locator"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (output / "requests.jsonl").write_text(request.model_dump_json() + "\n", encoding="utf-8")
    (output / "MANIFEST.json").write_text(
        json.dumps(
            {
                "role": "mlrc-meta-pre-experiment-development-decision",
                "formal_evidence_eligible": False,
                "request_sha256": request.request_sha256,
                "execution_bundle_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "independent_tasks": 1,
                "images": len(artifacts),
                "branch_outcomes_read": False,
                "limitations": [
                    "single development task",
                    "illustrative input images only",
                    "no measured feature-norm evidence",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.bundle, args.data_root, args.output_root))

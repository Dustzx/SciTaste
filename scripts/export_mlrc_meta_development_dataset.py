#!/usr/bin/env python3
"""Export a completed image-bearing development fork through the common dataset API."""

from __future__ import annotations

import argparse
import json
import subprocess
from operator import itemgetter
from pathlib import Path

from scitaste.evaluation.decision_dataset import (
    build_development_dataset,
    evaluate_dataset,
    file_sha,
)
from scitaste.evaluation.decision_policy_baselines import DecisionPolicyRun

if __package__:
    from .score_mlrc_meta_decision import score
else:
    from score_mlrc_meta_decision import score


def export(
    *,
    decisions: Path,
    decision_bundle: Path,
    execution_bundle: Path,
    pair: Path,
    source_checkout: Path,
    output: Path,
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("development dataset export must be new")
    # Validate the complete official result and the pre-execution commitments
    # before creating an export. Partial jobs are never scoring-key sources.
    result = score(decisions, decision_bundle, execution_bundle, pair, None)
    manifest = json.loads((execution_bundle / "MANIFEST.json").read_text())
    scorer = source_checkout / (
        "MLAgentBench/benchmarks_base/meta-learning/env/cdmetadl/scoring/scoring.py"
    )
    if file_sha(scorer) != manifest["official_scorer_sha256"]:
        raise ValueError("source attribution does not match the executed official scorer")
    revision = subprocess.run(
        ["git", "-C", str(source_checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != "0d26417034811d2d4587646c4520cc305ea09dd6":
        raise ValueError("source checkout is not the admitted MLRC development revision")
    license_path = source_checkout / "LICENSE"
    output.mkdir(parents=True)
    preparation = output / "preparation"
    preparation.mkdir(mode=0o700)
    keys = preparation / "keys.jsonl"
    with keys.open("x") as stream:
        stream.write(json.dumps(result["private_scoring_key"], sort_keys=True) + "\n")
    keys.chmod(0o600)
    card = build_development_dataset(
        requests_path=decisions / "requests.jsonl",
        keys_path=keys,
        source={
            "benchmark_id": "MLRC-Bench/meta-learning",
            "title": "MLRC-Bench Meta-Learning development task",
            "repository": "https://github.com/yunx-z/MLRC-Bench",
            "revision": revision,
            "license": "MIT (benchmark code only)",
            "license_sha256": file_sha(license_path),
        },
        source_license=license_path,
        public_root=output / "participant",
        private_root=output / "scorer",
        evidence_root=decisions / "evidence",
        native_fallback_definition=(
            "Prespecified unchanged Euclidean ProtoNet action, not an observed "
            "complete Native-agent decision."
        ),
        limitations=(
            *result["limitations"],
            "Consumed development case, not a prospective held-out benchmark split.",
            "Four illustrative input images do not establish measured norm-shift evidence.",
            "The 1000 prediction episodes per action belong to one source research task.",
            "The original three provider calls lack raw response bodies; no exact replay claim.",
            "Benchmark code MIT license does not license MetaAlbum images; this package is "
            "internal-only, without public image redistribution authorization.",
            "The separately model-generated cosine-logit candidate was not executed and "
            "does not inherit the normalized-distance score.",
        ),
    )
    replayed = []
    submissions_root = output / "submissions"
    submissions_root.mkdir()
    for kind in ("direct", "planning"):
        recorded = DecisionPolicyRun.model_validate_json(
            (decisions / kind / "case-0000.json").read_text()
        )
        submissions = submissions_root / f"{kind}.jsonl"
        submissions.write_text(
            "".join(row.model_dump_json() + "\n" for row in recorded.submissions)
        )
        evaluation = evaluate_dataset(output / "participant", output / "scorer", submissions)
        replayed.extend(evaluation["methods"])
        (output / f"{kind}-score.json").write_text(json.dumps(evaluation, indent=2) + "\n")
    order = itemgetter("method_id")
    if sorted(replayed, key=order) != sorted(result["methods"], key=order):
        raise ValueError("exported dataset does not reproduce the official outcome join")
    receipt = {
        "role": "verified-visual-development-dataset-export",
        "formal_evidence_eligible": False,
        "source_pair_state_sha256": file_sha(pair / "STATE.json"),
        "execution_bundle_manifest_sha256": file_sha(execution_bundle / "MANIFEST.json"),
        "dataset_manifest_sha256": file_sha(output / "participant" / "MANIFEST.json"),
        "cases": card["cases"],
        "independent_source_tasks": card["independent_source_tasks"],
        "existing_method_scores_reproduced": True,
    }
    (output / "EXPORT_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "decisions",
        "decision-bundle",
        "execution-bundle",
        "pair",
        "source-checkout",
        "output",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    print(json.dumps(export(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

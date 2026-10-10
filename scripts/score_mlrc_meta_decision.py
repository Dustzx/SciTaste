#!/usr/bin/env python3
"""Join frozen image decisions to completed official development outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionScoringKey,
    score_decision_methods,
)
from scitaste.evaluation.decision_policy_baselines import DecisionPolicyRun
from scitaste.project.models import content_sha256

if __package__:
    from .mlrc_meta_visual_fork_runtime import ACTIONS, _official_score
else:
    from mlrc_meta_visual_fork_runtime import ACTIONS, _official_score


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(
    decisions: Path, original_bundle: Path, execution_bundle: Path, pair: Path, output: Path | None
) -> dict:
    if output is not None and output.exists():
        raise FileExistsError("decision evaluation must be new")
    state = json.loads((pair / "STATE.json").read_text())
    if state["status"] != "complete":
        raise ValueError("both official branch executions must complete before scoring")
    plan = json.loads((decisions / "MANIFEST.json").read_text())
    original = json.loads((original_bundle / "MANIFEST.json").read_text())
    executed = json.loads((execution_bundle / "MANIFEST.json").read_text())
    if plan["execution_bundle_sha256"] != sha(original_bundle / "MANIFEST.json"):
        raise ValueError("decision no longer matches its original execution bundle")
    if state["bundle_manifest_sha256"] != sha(execution_bundle / "MANIFEST.json"):
        raise ValueError("executed bundle differs from the pair receipt")
    # A launcher-only correction is allowed before execution. It cannot change
    # an action, official scorer, data, environment lock, or prediction count.
    for manifest in (original, executed):
        manifest["files"] = {k: v for k, v in manifest["files"].items() if k != "runner.py"}
    if original != executed:
        raise ValueError("experiment semantics changed after the policy decisions")
    bound = state["pre_execution_decision_sha256"]
    for relative in ("MANIFEST.json", "direct/case-0000.json", "planning/case-0000.json"):
        suffix = f"/{decisions.name}/{relative}"
        hashes = [value for name, value in bound.items() if name.endswith(suffix)]
        if hashes != [sha(decisions / relative)]:
            raise ValueError("decision bytes differ from the pre-execution commitment")
    request = DecisionMethodRequest.model_validate_json((decisions / "requests.jsonl").read_text())
    if request.request_sha256 != plan["request_sha256"]:
        raise ValueError("public request differs from the pre-experiment manifest")
    completed = {item["action"]: item for item in state["completed_actions"]}
    if len(state["completed_actions"]) != 2 or set(completed) != set(ACTIONS):
        raise ValueError("pair receipt must include each branch exactly once")
    outcomes = {}
    for action in ACTIONS:
        result = json.loads((pair / action / "RUN_RESULT.json").read_text())
        if result != completed[action] or result["status"] != "complete":
            raise ValueError("branch receipt differs from the completed pair")
        if (
            result["prediction_count"] != executed["prediction_count_per_action"]
            or result["bundle_manifest_sha256"] != state["bundle_manifest_sha256"]
        ):
            raise ValueError("branch execution population or identity differs")
        score_file = pair / action / "scoring_output/scores.txt"
        value = _official_score(score_file)
        if sha(score_file) != result["score_file_sha256"] or value != result["overall_score"]:
            raise ValueError("official score bytes differ from their execution receipt")
        outcomes[action] = value
    key = DecisionScoringKey(
        request_sha256=request.request_sha256,
        task_cluster_id="mlrc-meta-learning-development",
        action_utilities={action: (value + 1) / 2 for action, value in outcomes.items()},
        failure_utility=0.0,
        practical_equivalence_tolerance=0.0,
        execution_contract_sha256=state["bundle_manifest_sha256"],
        scorer_contract_sha256=content_sha256(
            {
                "official_scorer_sha256": executed["official_scorer_sha256"],
                "utility": "(official_normalized_accuracy + 1) / 2",
                "failure_utility": 0.0,
                "tie_tolerance": 0.0,
            }
        ),
    )
    submissions = tuple(
        item
        for kind in ("direct", "planning")
        for item in DecisionPolicyRun.model_validate_json(
            (decisions / kind / "case-0000.json").read_text()
        ).submissions
    )
    summary = score_decision_methods((request,), (key,), submissions)
    report = {
        "role": "single-task-multimodal-development-fork",
        "formal_evidence_eligible": False,
        "independent_research_tasks": 1,
        "prediction_episodes_per_action": 1000,
        "raw_official_scores": outcomes,
        "private_scoring_key": key.model_dump(mode="json"),
        "methods": [item.model_dump(mode="json") for item in summary],
        "utility_mapping": "(official_normalized_accuracy + 1) / 2; raw scores retained above",
        "execution_bundle_sha256": state["bundle_manifest_sha256"],
        "pre_execution_decision_sha256": bound,
        "limitations": [
            "one development task",
            "no Taste arm",
            "no whole-agent comparison",
            "unequal actual model inference costs",
            "no repeated-seed effect estimate",
        ],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--decision-bundle", type=Path, required=True)
    parser.add_argument("--execution-bundle", type=Path, required=True)
    parser.add_argument("--pair-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = score(
        args.decisions, args.decision_bundle, args.execution_bundle, args.pair_root, args.output
    )
    print(json.dumps({"scores": result["raw_official_scores"], "output": str(args.output)}))

"""Separate recovered science from first-attempt failure and charge every reply."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json


def summarize(project, study):
    root, study = project.resolve(strict=True), study.resolve(strict=True)
    spec = json.loads(study.read_text())
    continuation_path = study.parent / "HANDOFF_CONTINUATIONS.json"
    continuations = json.loads(continuation_path.read_text())
    rows, sources = [], [binding(root, study), binding(root, continuation_path)]
    for condition, allocation in spec["allocations"].items():
        original, current = root / allocation["run"], root / continuations[condition]["run"]
        terminal = current / "RESULT.json"
        if not terminal.is_file():
            raise ValueError("Actual delivery continuation is not terminal")
        old_result = json.loads((original / "RESULT.json").read_text())
        result = json.loads(terminal.read_text())
        feedback_path = current / "workspace/confirmation_feedback.json"
        feedback = json.loads(feedback_path.read_text())
        scored = feedback.get("result", {})
        old_manifest = original / "workspace/submission/SUBMISSION.json"
        manifest_path = current / "workspace/submission/SUBMISSION.json"
        if digest(old_manifest) != digest(manifest_path):
            raise ValueError("Delivery recovery changed the scientific manifest")
        handoff_path = current / "workspace/submission/HANDOFF.json"
        handoff = json.loads(handoff_path.read_text())
        for name, source in handoff["files"].items():
            if digest(current / "workspace/submission" / name) != digest(
                original / "workspace" / name
            ) or source["sha256"] != digest(original / "workspace" / name):
                raise ValueError("Original scientific source bytes changed")
        manifest = json.loads(manifest_path.read_text())
        if scored.get("primary_method") != manifest["primary_method"]:
            raise ValueError("Private outcomes reselected the primary method")
        primary = next(
            (s for s in scored.get("scores", []) if s["method"] == manifest["primary_method"]), {}
        )
        original_contract = json.loads((original / "CONTRACT.json").read_text())
        envelope = original_contract["plan"]["resource_envelope"]
        total_replies = (
            old_result["accounting"]["session_responses"]
            + result["accounting"]["session_responses"]
        )
        elapsed = terminal.stat().st_mtime - (original / "CONTRACT.json").stat().st_mtime
        rows.append(
            {
                "condition": condition,
                "original_confirmation": "failed-before-source-execution",
                "original_primary_outcome": None,
                "continuation_status": result["status"],
                "recovered_confirmation_status": feedback.get("status"),
                "executed_frozen_source": feedback.get("executed_frozen_source"),
                "source_and_manifest_bytes_unchanged": True,
                "primary_method": manifest["primary_method"],
                "complete_mean_condition_rmse": scored.get("primary_scores", {}).get(
                    "unseen_combinations"
                ),
                "confirmation_conditions": primary.get("metrics", {}).get("conditions"),
                "defined_primary_pearson_conditions": primary.get("metrics", {}).get(
                    "defined_pearson_delta_conditions"
                ),
                "mean_primary_pearson_delta": primary.get("metrics", {}).get("mean_pearson_delta"),
                "scored_procedures": len(scored.get("scores", [])),
                "original_model_responses": old_result["accounting"]["session_responses"],
                "continuation_model_responses": result["accounting"]["session_responses"],
                "total_model_responses": total_replies,
                "all_elapsed_seconds_including_repair_gap": elapsed,
                "within_original_reply_ceiling": total_replies <= envelope["max_requests"],
                "within_original_wall_ceiling": elapsed <= envelope["wall_seconds"],
                "independent_reproduction_verified": False,
                "tokens_and_session_cost": None,
                "continuation_figures_attached": False,
                "formal_evidence_eligible": False,
            }
        )
        for path in (
            terminal,
            current / "CONTRACT.json",
            current / "loop/TRAJECTORY.jsonl",
            feedback_path,
            handoff_path,
            manifest_path,
            current / "workspace/report/report.md",
            original / "RESULT.json",
            old_manifest,
        ):
            sources.append(binding(root, path))
    a, b = rows
    summary = {
        "scope": (
            "Two charged delivery continuations of ONE previously exposed research task; "
            "no additional task, no original failure overwritten"
        ),
        "rows": rows,
        "model_response_reduction_fraction": 1
        - b["total_model_responses"] / a["total_model_responses"],
        "original_assigned_workers": 2,
        "causal_taste_effect_established": False,
        "jev_called": False,
        "scientific_quality_independently_assessed": False,
        "source_bindings": sources,
        "interpretation": (
            "Identical recovered primary does not establish equal scientific quality, "
            "better hypotheses, novelty or universal efficiency. Protocol clarification "
            "and source-bound recovery are disclosed adaptations. Model response count "
            "is not dollar/token cost or number of atomic tools."
        ),
        "formal_evidence_eligible": False,
    }
    retain_json(study.parent / "DELIVERY_RESULTS.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.project, args.study), indent=2))


if __name__ == "__main__":
    main()

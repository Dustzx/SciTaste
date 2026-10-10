"""Seal frozen task outcomes, never replace a failed original assignment."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.confirmation_binding import confirmation_directory
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def collect(project, campaign, output, recovery_assignments=None, scoring_recovery_index=None):
    project, campaign = project.resolve(strict=True), campaign.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    output = output.resolve()
    output.relative_to(campaign.parent)
    frozen = json.loads(campaign.read_text())
    if frozen["task_id"] not in {
        "stable-physical-rollout",
        "cross-series-forecasting",
        "population-shift-calibration",
        "combinatorial-perturbation",
    }:
        raise ValueError("Not a recognized source-frozen complete research task")
    pack = json.loads(verified_asset(project, frozen["pack"]).read_text())
    assignments_path = campaign.parent / "ASSIGNMENTS.json"
    assignments = json.loads(assignments_path.read_text())

    def binding(path):
        return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}

    def measured_row(arm, assignment, *, recovery, scoring_directory=None):
        directory = confirmation_directory(project, campaign, arm, assignment)
        receipt = directory / "RESULT.json"
        collection_binding = None
        if scoring_directory is not None:
            scoring_directory.relative_to(campaign.parent / "scoring-recoveries")
            receipt = scoring_directory / "RESULT.json"
            collection_file = scoring_directory / "CONTRACT.json"
            collection = json.loads(collection_file.read_text())
            original_failure = json.loads((directory / "RESULT.json").read_text())
            if (
                original_failure.get("status") != "failed"
                or collection["campaign_sha256"] != digest(campaign)
                or collection["original_failure_sha256"] != digest(directory / "RESULT.json")
                or collection["inference_result_sha256"]
                != digest(directory / "INFERENCE_RESULT.json")
                or collection["original_execution_contract_sha256"]
                != digest(directory / "EXECUTION_CONTRACT.json")
                or collection["original_release_sha256"]
                != digest(directory / "release/RELEASE.json")
                or collection["new_inference_runs"] != 0
                or collection["new_model_calls"] != 0
                or collection["original_failure_replaced"]
            ):
                raise ValueError("Score-only recovery must retain its exact failed original")
            collection_binding = binding(collection_file)
        raw = json.loads(receipt.read_text())
        if (
            collection_binding
            and raw.get("explicit_scoring_collection_recovery_sha256")
            != collection_binding["sha256"]
        ):
            raise ValueError("Scoring result is not bound to the collection recovery")
        execution = directory / "EXECUTION_CONTRACT.json"
        inference = directory / "INFERENCE_RESULT.json"
        contract, ran = json.loads(execution.read_text()), json.loads(inference.read_text())
        release_path = directory / "release/RELEASE.json"
        release = json.loads(release_path.read_text())
        if (
            raw.get("status") != "completed"
            or not raw.get("executed_frozen_source")
            or raw["execution_contract_sha256"] != digest(execution)
            or raw["inference_result_sha256"] != digest(inference)
            or contract["campaign_sha256"] != digest(campaign)
            or contract["source_run"] != assignment["run"]
            or ran["release_sha256"] != digest(release_path)
            or ran["execution_contract_sha256"] != digest(execution)
            or ran["return_code"] != 0
            or not ran["before_private_scoring"]
            or release["pack_sha256"] != frozen["pack"]["sha256"]
        ):
            raise ValueError("Unbound frozen-program outcome")
        source = directory / "release/frozen_submission"
        for locator, sha in release["frozen_source"].items():
            asset = (source / locator).resolve(strict=True)
            asset.relative_to(source)
            if digest(asset) != sha:
                raise ValueError("Frozen scientific source changed")
        submission_file = source / "SUBMISSION.json"
        submission = json.loads(submission_file.read_text())
        primary = submission["primary_method"]
        methods = submission["methods"]
        contexts = set(pack["confirmation_contexts"])
        expected = {(context, method) for context in contexts for method in methods}
        scores = raw["result"]["scores"]
        if (
            primary not in methods
            or len(set(methods)) != len(methods)
            or len(scores) != len(expected)
            or {(row["context"], row["method"]) for row in scores} != expected
            or raw["result"]["primary_method"] != primary
        ):
            raise ValueError("Incomplete fixed method/context or unique-primary coverage")
        for row in scores:
            name = f"{row['context']}--{row['method']}.npz"
            if row.get("prediction_sha256") != ran["output_sha256"].get(name):
                raise ValueError("Scored prediction does not match the actual process receipt")
        return {
            "system": arm,
            "source_run": assignment["run"],
            "engineering_recovery": recovery,
            "score_collection_recovery": collection_binding,
            "primary_method": primary,
            "primary_endpoint": raw["result"].get("primary_endpoint"),
            "selection_rule": submission["selection_rule"],
            "primary_scores": raw["result"]["primary_scores"],
            "all_method_context_scores": scores,
            "confirmation": binding(receipt),
            "submission": binding(submission_file),
            "inference": binding(inference),
            "release": binding(release_path),
            "execution": binding(execution),
            "executed_frozen_source": True,
            "scorer_source_execution_verified": raw["result"]["source_execution_verified"],
            "formal_evidence_eligible": raw["formal_evidence_eligible"],
            "native_delivery_adapter": contract.get("native_delivery_adapter"),
        }

    original = []
    for arm, assignment in assignments.items():
        receipt = confirmation_directory(project, campaign, arm, assignment) / "RESULT.json"
        if receipt.is_file():
            raw = json.loads(receipt.read_text())
            if raw.get("status") == "failed":
                # The assignment remains missing even when a separately declared
                # recovery can score its original already-produced predictions.
                directory = receipt.parent
                inference = directory / "INFERENCE_RESULT.json"
                execution = directory / "EXECUTION_CONTRACT.json"
                ran = json.loads(inference.read_text()) if inference.is_file() else None
                if ran is not None and (
                    not execution.is_file()
                    or ran["execution_contract_sha256"] != digest(execution)
                    or json.loads(execution.read_text())["campaign_sha256"] != digest(campaign)
                    or json.loads(execution.read_text())["source_run"] != assignment["run"]
                ):
                    raise ValueError("Failed assignment's inference is unbound")
                original.append(
                    {
                        "system": arm,
                        "source_run": assignment["run"],
                        "status": "original-confirmation-failed",
                        "primary_scores": None,
                        "confirmation": binding(receipt),
                        "original_reported_executed_frozen_source": raw.get(
                            "executed_frozen_source"
                        ),
                        "inference_completed_before_scoring": bool(
                            ran and ran["return_code"] == 0 and ran["before_private_scoring"]
                        ),
                        "inference": binding(inference) if ran else None,
                        "error_type": raw.get("error_type"),
                        "error": raw.get("error"),
                        "missing_outcomes_imputed": False,
                    }
                )
            else:
                original.append(measured_row(arm, assignment, recovery=False))
        else:
            run = (project / assignment["run"]).resolve(strict=True)
            run.relative_to(project)
            terminal = run / "RESULT.json"
            if not terminal.is_file():
                raise ValueError("An original arm is neither confirmed nor terminal")
            original.append(
                {
                    "system": arm,
                    "source_run": assignment["run"],
                    "primary_scores": None,
                    "confirmation": None,
                    "original_terminal_receipt": binding(terminal),
                    "status": json.loads(terminal.read_text())["status"],
                    "missing_outcomes_imputed": False,
                }
            )
    recovered = []
    if recovery_assignments:
        recovery_assignments = recovery_assignments.resolve(strict=True)
        recovery_assignments.relative_to(campaign.parent)
        for arm, assignment in json.loads(recovery_assignments.read_text()).items():
            if arm not in assignments or assignment["run"] == assignments[arm]["run"]:
                raise ValueError("Recovery must be separately assigned to an original arm")
            recovered.append(measured_row(arm, assignment, recovery=True))
    score_only = []
    if scoring_recovery_index:
        scoring_recovery_index = scoring_recovery_index.resolve(strict=True)
        scoring_recovery_index.relative_to(campaign.parent)
        index = json.loads(scoring_recovery_index.read_text())
        if index["campaign_sha256"] != digest(campaign) or index["assignments_sha256"] != digest(
            assignments_path
        ):
            raise ValueError("Scoring recoveries belong to a different frozen cohort")
        for arm, result in index["results"].items():
            if arm not in assignments:
                raise ValueError("Scoring recovery cannot add an unassigned system")
            receipt = verified_asset(project, result)
            if receipt.name != "RESULT.json":
                raise ValueError("Scoring recovery must bind its sealed result")
            score_only.append(
                measured_row(arm, assignments[arm], recovery=True, scoring_directory=receipt.parent)
            )
    result = {
        "schema_version": "scitastebench.frozen-rollout-results.v1",
        "task_id": frozen["task_id"],
        "task_families": 1,
        "campaign": binding(campaign),
        "pack": frozen["pack"],
        "original_assignments": binding(assignments_path),
        "original_framework_assignment_count": len(assignments),
        "original_rows": original,
        "separate_recovery_rows": recovered,
        "separate_score_collection_recovery_rows": score_only,
        "score_collection_recovery_index": binding(scoring_recovery_index)
        if scoring_recovery_index
        else None,
        "recovery_assignments": binding(recovery_assignments) if recovery_assignments else None,
        "all_declared_procedures_failures_and_qualification_flags_retained": True,
        "primary_selected_after_private_scoring": False,
        "recovery_replaces_original_failure": False,
        "paper_or_workflow_completion_assessed": False,
        "taste_effect_established": False,
        "formal_evidence_eligible": False,
        "verified_model_identity_or_randomness_match": False,
        "human_judge_calibration": False,
        "top_venue_or_novelty_certified": False,
        "scope": "Actual frozen-program outcomes only; not the source leaderboard, "
        "a formal system ranking, a complete-paper assessment or a Taste treatment effect.",
    }
    verified_asset(project, frozen["pack"])
    retain_json(output, result)
    return {"output": str(output), "sha256": digest(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--recovery-assignments", type=Path)
    parser.add_argument("--scoring-recovery-index", type=Path)
    print(json.dumps(collect(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

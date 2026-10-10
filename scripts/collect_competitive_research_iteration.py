"""Collect all assigned successor outcomes without overwriting original comparisons."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def paired_primary_outcomes(family, baseline, successor):
    """Describe fixed selected procedures; units are not independent research tasks."""
    field, identifier, endpoint = (
        ("per_condition", "condition_id", "rmse")
        if family == "perturbation"
        else ("per_series", "series_id", "mase")
    )
    old = {
        row["context"]: row
        for row in baseline["all_method_context_scores"]
        if row["method"] == baseline["primary_method"]
    }
    new = {
        row["context"]: row
        for row in successor["all_method_context_scores"]
        if row["method"] == successor["primary_method"]
    }
    output = {}
    for context in old.keys() & new.keys():
        old_units = {item[identifier]: item for item in old[context]["metrics"][field]}
        new_units = {item[identifier]: item for item in new[context]["metrics"][field]}
        if not old_units or old_units.keys() != new_units.keys():
            raise ValueError("Selected procedures have different evaluation identities")
        if not all(item["valid"] for item in [*old_units.values(), *new_units.values()]):
            raise ValueError("Do not report a favorable survivor-only paired summary")
        differences = [new_units[key][endpoint] - item[endpoint] for key, item in old_units.items()]
        output[context] = {
            "units": len(differences),
            "improved": sum(value < 0 for value in differences),
            "unchanged": sum(value == 0 for value in differences),
            "worsened": sum(value > 0 for value in differences),
            "mean_difference_new_minus_original": sum(differences) / len(differences),
            "units_are_new_independent_research_tasks": False,
            "original_and_successor_public_selection_retained": True,
            "causal_taste_gain_established": False,
        }
    return output


def collect(project, study):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(project / "evaluations")
    protocol = json.loads((study / "STUDY.json").read_text())
    rows = {}
    for family, assignment in protocol["allocations"].items():
        campaign_path = verified_asset(project, assignment["campaign"])
        campaign = json.loads(campaign_path.read_text())
        source = project / assignment["run"]
        launch = json.loads((source / "CONTRACT.json").read_text())
        terminal = json.loads((source / "RESULT.json").read_text())
        if launch["plan"]["campaign"] != assignment["campaign"]:
            raise ValueError("Successor launch is not bound to its assigned campaign")
        old_campaign = verified_asset(project, campaign["source_system_campaign"])
        original = json.loads((old_campaign.parent / "SCIENTIFIC_RESULTS.json").read_text())
        for name, value in campaign["researcher_assets"].items():
            verified_asset(project, value)
            old = json.loads(old_campaign.read_text())["researcher_assets"][name]
            if old["sha256"] != value["sha256"]:
                raise ValueError("Public exposure changed between old and successor tasks")
        confirmation = campaign_path.parent / "confirmation/scitaste-native"
        feedback_path = confirmation / "RESULT.json"
        feedback = json.loads(feedback_path.read_text()) if feedback_path.is_file() else None
        row = {
            "campaign": assignment["campaign"],
            "source_run": assignment["run"],
            "terminal_sha256": digest(source / "RESULT.json"),
            "status": terminal["status"],
            "source_contract_sha256": digest(source / "CONTRACT.json"),
            "first_report_exists": terminal.get("report_exists", False),
            "first_report_sha256": None,
            "primary_method": None,
            "primary_endpoint": None,
            "primary_scores": None,
            "all_method_context_scores": [],
            "scientific_quality_established": False,
            "independent_task_generalization_established": False,
            "formal_evidence_eligible": False,
            "old_original_system_results": original["original_rows"],
            "old_results_sha256": digest(old_campaign.parent / "SCIENTIFIC_RESULTS.json"),
            "old_outcomes_replaced": False,
            "actual_requests": len(list((source / "exchange").glob("*.request.json"))),
            "actual_replies": len(list((source / "exchange").glob("*.reply.json"))),
            "actual_provider_model_seed_tokens_cost": None,
        }
        report = source / "workspace/report/report.md"
        if row["first_report_exists"]:
            row["first_report_sha256"] = digest(report)
        if feedback is not None:
            row["confirmation_feedback_sha256"] = digest(feedback_path)
            row["confirmation_status"] = feedback["status"]
            row["original_confirmation_primary_scores"] = (
                feedback["result"]["primary_scores"] if feedback["status"] == "completed" else None
            )
            recovery_path = campaign_path.parent / "scoring-recoveries/scitaste-native/RESULT.json"
            explicit_recovery = (
                campaign_path.parent / "scoring-recoveries/scitaste-native-v2/RESULT.json"
            )
            if family == "forecasting" and explicit_recovery.is_file():
                if recovery_path.is_file():
                    raise ValueError("Multiple successful recoveries; do not select by score")
                recovery_path = explicit_recovery
            scored = feedback
            row["score_collection_recovery"] = None
            if feedback["status"] == "failed" and recovery_path.is_file():
                recovered = json.loads(recovery_path.read_text())
                binding = json.loads((recovery_path.parent / "CONTRACT.json").read_text())
                if (
                    recovered["status"] != "completed"
                    or binding["original_failure_sha256"] != digest(feedback_path)
                    or binding["inference_result_sha256"]
                    != digest(confirmation / "INFERENCE_RESULT.json")
                    or binding["new_inference_runs"] != 0
                    or binding["original_failure_replaced"]
                ):
                    raise ValueError(
                        "Recovery must score exact old predictions without replacing failure"
                    )
                scored = recovered
                row["score_collection_recovery"] = {
                    "locator": recovery_path.relative_to(project).as_posix(),
                    "sha256": digest(recovery_path),
                    "contract_sha256": digest(recovery_path.parent / "CONTRACT.json"),
                    "source_inference_repeated": False,
                    "original_confirmation_failure_replaced": False,
                }
            if scored["status"] == "completed":
                measured = scored["result"]
                execution = json.loads((confirmation / "EXECUTION_CONTRACT.json").read_text())
                inference = json.loads((confirmation / "INFERENCE_RESULT.json").read_text())
                if execution["campaign_sha256"] != assignment["campaign"]["sha256"] or (
                    not inference["before_private_scoring"] or inference["return_code"] != 0
                ):
                    raise ValueError("Actual frozen execution/scoring provenance changed")
                row.update(
                    primary_method=measured["primary_method"],
                    primary_endpoint=measured["primary_endpoint"],
                    primary_scores=measured["primary_scores"],
                    all_method_context_scores=measured["scores"],
                    execution_contract_sha256=digest(confirmation / "EXECUTION_CONTRACT.json"),
                    inference_result_sha256=digest(confirmation / "INFERENCE_RESULT.json"),
                    frozen_source=json.loads((confirmation / "release/RELEASE.json").read_text())[
                        "frozen_source"
                    ],
                    score_origin="original-confirmation"
                    if row["score_collection_recovery"] is None
                    else "separate-exact-prediction-collection-recovery",
                )
        baseline = next(r for r in original["original_rows"] if r["system"] == "scitaste-native")
        row["new_minus_original_primary"] = {}
        row["relative_error_reduction"] = {}
        for context, old_value in (baseline.get("primary_scores") or {}).items():
            new = (row["primary_scores"] or {}).get(context)
            row["new_minus_original_primary"][context] = (
                None if new is None or old_value is None else new - old_value
            )
            row["relative_error_reduction"][context] = (
                None
                if new is None or old_value is None or old_value == 0
                else (old_value - new) / old_value
            )
        row["paired_primary_outcomes"] = (
            paired_primary_outcomes(family, baseline, row) if row["primary_scores"] else {}
        )
        rows[family] = row
    outer_path = study / "forecast-outer/RESULTS.json"
    result = {
        "schema_version": "1.0",
        "study_sha256": digest(study / "STUDY.json"),
        "assigned_research_questions": len(protocol["allocations"]),
        "outcomes": rows,
        "all_assignment_failures_retained": True,
        "outer_reserved_confirmation": None
        if not outer_path.is_file()
        else {"locator": outer_path.relative_to(project).as_posix(), "sha256": digest(outer_path)},
        "scope": "Task-exposed capability iteration under fixed task-native metrics and "
        "public-selected sources. Historical framework outcomes remain immutable. New "
        "allocation and combined intervention do not establish a causal Taste effect.",
        "causal_taste_gain_established": False,
        "matched_backbone_or_budget_established": False,
        "formal_evidence_eligible": False,
        "supplier_api_calls": 0,
        "gpu_enabled": False,
    }
    retain_json(study / "RESULTS.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "study"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.project, args.study)
    print(
        json.dumps(
            {
                family: {
                    key: row[key]
                    for key in ("status", "primary_scores", "relative_error_reduction")
                }
                for family, row in result["outcomes"].items()
            }
        )
    )

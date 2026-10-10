"""Read all original sensor assignments; never query labels or pick a private winner."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.writing.confirmation_evidence import native_confirmation_evidence


def summarize(project, study):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    frozen = json.loads((study / "STUDY.json").read_text())
    conditions = {}
    for name, assignment in frozen["allocations"].items():
        campaign = verified_asset(project, assignment["campaign"])
        run = project / assignment["run"]
        outcome = run / "RESULT.json"
        if not outcome.is_file():
            raise ValueError(f"Original assigned research remains nonterminal: {name}")
        terminal = json.loads(outcome.read_text())
        bound = native_confirmation_evidence(
            project, run, study / name / "CONFIRMATION_EVIDENCE.json"
        )
        feedback_path = campaign.parent / "confirmation/scitaste-native/RESULT.json"
        feedback = json.loads(feedback_path.read_text()) if feedback_path.is_file() else {}
        confirmation = feedback.get("result", {})
        reply_paths = sorted((run / "session-exchange").glob("*.reply.json"))
        authors, nodes = set(), {}
        for request in (run / "session-exchange").glob("*.request.json"):
            value = json.loads(request.read_text())
            node = value["node_name"]
            nodes[node] = nodes.get(node, 0) + 1
        for reply in reply_paths:
            authors.add(json.loads(reply.read_text())["author_reference"])
        source_observation = feedback.get("executed_frozen_source", False)
        if source_observation and not bound:
            raise ValueError("Confirmed output lacks its actual unchanged-execution binding")
        primary = confirmation.get("primary_scores", {})
        expected = [f"batch{i}" for i in range(6, 11)]
        if primary and set(primary) != set(expected):
            raise ValueError("Do not silently drop a confirmation batch")
        paper = run / "workspace/report/report.md"
        row = {
            "status": terminal["status"],
            "run": assignment["run"],
            "result_sha256": digest(outcome),
            "campaign_sha256": digest(campaign),
            "report_exists": paper.is_file(),
            "first_report_sha256": digest(paper) if paper.is_file() else None,
            "confirmation_status": feedback.get("status", "missing"),
            "executed_frozen_source": source_observation,
            "primary_method": confirmation.get("primary_method"),
            "primary_scores": {key: primary.get(key) for key in expected},
            "complete_selected_primary": bool(primary)
            and all(primary.get(key) is not None for key in expected),
            "all_predeclared_outcomes": confirmation.get("scores", []),
            "model_responses": len(reply_paths),
            "node_request_counts": nodes,
            "session_authors": sorted(authors),
            "research_elapsed_seconds": terminal["duration_seconds"],
            "actual_tokens": None,
            "session_cost_usd": None,
            "api_calls": 0,
            "actual_backbone_identity_verified": False,
            "tool_intelligence": terminal.get("tool_intelligence"),
            "lifecycle_report_review_revision_complete": False,
        }
        conditions[name] = row
    differences = {}
    for a, b in (("taste", "off"), ("taste", "raw"), ("raw", "off")):
        differences[f"{a}-minus-{b}"] = {
            key: conditions[a]["primary_scores"][key] - conditions[b]["primary_scores"][key]
            if conditions[a]["primary_scores"][key] is not None
            and conditions[b]["primary_scores"][key] is not None
            else None
            for key in expected
        }
    recoveries = {}
    registry = study / "off/RECOVERY_ASSIGNMENTS.json"
    if registry.is_file():
        recovery = json.loads(registry.read_text())["scitaste-native"]
        run = project / recovery["run"]
        outcome = run / "RESULT.json"
        if not outcome.is_file():
            raise ValueError("Assigned OFF continuation remains nonterminal")
        terminal = json.loads(outcome.read_text())
        bound = native_confirmation_evidence(
            project, run, study / "off/RECOVERY_CONFIRMATION_EVIDENCE.json"
        )
        receipt = project / recovery["confirmation"] / "RESULT.json"
        feedback = json.loads(receipt.read_text()) if receipt.is_file() else {}
        if feedback.get("executed_frozen_source") and not bound:
            raise ValueError("Recovery confirmation lacks unchanged execution binding")
        confirmation = feedback.get("result", {})
        primary = confirmation.get("primary_scores", {})
        if primary and set(primary) != set(expected):
            raise ValueError("Do not silently drop a recovery confirmation batch")
        launch = json.loads((run / "CONTRACT.json").read_text())
        parent = Path(launch["continuation"]["parent"]).resolve(strict=True)
        if parent != (project / frozen["allocations"]["off"]["run"]).resolve(strict=True):
            raise ValueError("Recovery lineage belongs to another condition")
        if launch["continuation"]["parent_result_sha256"] != conditions["off"]["result_sha256"]:
            raise ValueError("Recovery parent failure changed")
        replies = sorted((run / "session-exchange").glob("*.reply.json"))
        paper = run / "workspace/report/report.md"
        recoveries["off"] = {
            "run": recovery["run"],
            "status": terminal["status"],
            "result_sha256": digest(outcome),
            "assignment_sha256": digest(registry),
            "confirmation_status": feedback.get("status", "missing"),
            "executed_frozen_source": feedback.get("executed_frozen_source", False),
            "primary_method": confirmation.get("primary_method"),
            "primary_scores": {key: primary.get(key) for key in expected},
            "all_predeclared_outcomes": confirmation.get("scores", []),
            "report_exists": paper.is_file(),
            "first_report_sha256": digest(paper) if paper.is_file() else None,
            "new_model_responses": len(replies),
            "charged_model_responses": conditions["off"]["model_responses"] + len(replies),
            "continuation_duration_seconds": terminal["duration_seconds"],
            "active_research_elapsed_seconds": conditions["off"]["research_elapsed_seconds"]
            + terminal["duration_seconds"],
            "charged_research_elapsed_seconds": launch["continuation"]["inherited_duration_seconds"]
            + terminal["duration_seconds"],
            "original_failure_replaced": False,
            "original_contrast_repaired": False,
            "completed_experiments_repeated": False,
            "api_calls": 0,
            "actual_tokens": None,
            "session_cost_usd": None,
        }
    value = {
        "schema_version": "1.0",
        "study_sha256": digest(study / "STUDY.json"),
        "conditions": conditions,
        "separately_charged_recoveries": recoveries,
        "common_session_configuration": (
            "Fresh-context suppliers inherited the same parent configuration, with no "
            "model/reasoning overrides; actual provider ID and randomness "
            "not independently verified"
        ),
        "descriptive_paired_differences": differences,
        "difference_direction": (
            "negative favors first condition; not causal or significant-effect certification"
        ),
        "task_families": 1,
        "confirmation_contexts_within_task": 5,
        "assigned_denominator": 3,
        "formal_evidence_eligible": False,
        "repeated_for_positive_scores": False,
        "private_winner_substitution": False,
        "claim_scope": (
            "One prospectively selected source-aligned whole-task Native mechanism cohort; "
            "abstraction/inquiry/selection bundled; single trajectory per condition; "
            "actual provider identity and randomness not independently verified"
        ),
        "external_methods_not_in_this_table": True,
    }
    retain_json(study / "RESULTS.json", value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "study"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.project, args.study)
    print(
        json.dumps(
            {
                "conditions": {
                    k: {
                        "primary": v["primary_method"],
                        "scores": v["primary_scores"],
                        "responses": v["model_responses"],
                    }
                    for k, v in result["conditions"].items()
                }
            },
            ensure_ascii=False,
        )
    )

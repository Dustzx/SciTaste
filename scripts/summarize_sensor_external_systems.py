"""Seal real framework outcomes, preserving original failures and delivery recoveries."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json

CONTEXTS = tuple(f"batch{i}" for i in range(6, 11))


def read(path):
    return json.loads(path.read_text())


def binding(project, path):
    return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}


def confirmation(project, campaign, arm, run):
    directory = campaign.parent / "confirmation" / arm
    path = directory / "RESULT.json"
    if not path.is_file():
        return {"status": "missing", "primary_scores": dict.fromkeys(CONTEXTS)}
    receipt = read(path)
    result = receipt.get("result", {})
    primary = result.get("primary_scores", {})
    records = result.get("scores", [])
    if primary and set(primary) != set(CONTEXTS):
        raise ValueError("Incomplete context identity must not be silently filtered")
    if receipt.get("executed_frozen_source"):
        execution = directory / "EXECUTION_CONTRACT.json"
        inference = directory / "INFERENCE_RESULT.json"
        launch = run / ("EXECUTION_CONTRACT.json" if arm == "autoresearchclaw" else "CONTRACT.json")
        contract, observed = read(execution), read(inference)
        if (
            receipt["execution_contract_sha256"] != digest(execution)
            or receipt["inference_result_sha256"] != digest(inference)
            or observed["execution_contract_sha256"] != digest(execution)
            or contract["campaign_sha256"] != digest(campaign)
            or contract["source_contract_sha256"] != digest(launch)
            or contract["source_run"] != run.relative_to(project).as_posix()
            or observed["return_code"] != 0
            or not contract["frozen_source_readonly"]
            or contract["network_enabled"]
            or contract["gpu_enabled"]
        ):
            raise ValueError("Confirmation execution no longer binds the assigned framework")
    return {
        "status": receipt["status"],
        "receipt": binding(project, path),
        "executed_frozen_source": receipt.get("executed_frozen_source", False),
        "primary_method": result.get("primary_method"),
        "primary_endpoint": result.get("primary_endpoint"),
        "primary_scores": {key: primary.get(key) for key in CONTEXTS},
        "complete_selected_primary": bool(primary)
        and all(primary.get(key) is not None for key in CONTEXTS),
        "all_predeclared_outcomes": records,
        "method_context_records": len(records),
        "confirmation_execution_seconds": receipt.get("elapsed_seconds"),
        "independent_reproduction_certified": False,
    }


def provenance(run, directory):
    exchange = run / directory
    authors = set()
    for path in exchange.glob("*.reply.json"):
        author = read(path).get("author_reference")
        if author:
            authors.add(author)
    return {
        "retained_requests": len(list(exchange.glob("*.request.json"))),
        "retained_replies": len(list(exchange.glob("*.reply.json"))),
        "authors": sorted(authors),
        "api_calls": 0,
        "actual_backbone_identity_verified": False,
        "actual_tokens": None,
        "session_cost_usd": None,
    }


def summarize(project, study):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(project / "evaluations")
    directory = study / "external"
    campaign = directory / "CAMPAIGN.json"
    freeze = read(directory / "FREEZE.json")
    if freeze["external_campaign_sha256"] != digest(campaign):
        raise ValueError("The prospective external campaign changed")
    contract = read(campaign)
    assignments = read(directory / "ASSIGNMENTS.json")
    if set(assignments) != {"autoresearchclaw", "mlr-agent"}:
        raise ValueError("Do not change the assigned method denominator")
    rows = {}
    for arm, assignment in assignments.items():
        run = (project / assignment["run"]).resolve(strict=True)
        if arm == "autoresearchclaw":
            terminal_path = run / "SESSION_CLOSED.json"
            launch_path = run / "EXECUTION_CONTRACT.json"
            first_paper = run / "work/upstream_run/stage-17/paper_draft.md"
            native_path = run / "work/NATIVE_RESULTS.json"
        else:
            terminal_path, launch_path = run / "RESULT.json", run / "CONTRACT.json"
            first_paper = run / "workspace/results/paper.md"
            native_path = None
        if not terminal_path.is_file():
            raise ValueError(f"Original assigned framework remains active: {arm}")
        terminal, launch = read(terminal_path), read(launch_path)
        launch_campaign = launch.get("benchmark_campaign") or launch.get("campaign")
        if isinstance(launch_campaign, dict):
            if verified_asset(project, launch_campaign) != campaign.resolve():
                raise ValueError("Framework launch belongs to another campaign")
        elif arm == "mlr-agent":
            if launch["task_sha256"] != contract["execution_brief"]["sha256"] or any(
                launch["public_assets"].get(name) != asset["sha256"]
                for name, asset in contract["researcher_assets"].items()
            ):
                raise ValueError("Native MLR task/assets differ from the prospective campaign")
        elif launch.get("campaign_sha256") != digest(campaign):
            raise ValueError("Framework launch lacks the frozen campaign binding")
        native = read(native_path) if native_path and native_path.is_file() else {}
        complete = native.get("all_native_stages_done", False)
        status = terminal.get("status") or (
            "native-stages-complete"
            if terminal["return_code"] == 0 and complete
            else "failed-or-incomplete"
        )
        rows[arm] = {
            "run": assignment["run"],
            "status": status,
            "original_terminal": binding(project, terminal_path),
            "source_pin": launch.get("upstream_commit") or launch.get("source_commit"),
            "research_elapsed_seconds": terminal.get("wall_seconds"),
            "first_paper": binding(project, first_paper) if first_paper.is_file() else None,
            "native_stage_results": native,
            "all_native_stages_done": complete if arm == "autoresearchclaw" else None,
            "native_post_paper_review_revision_available": arm == "autoresearchclaw",
            "confirmation": confirmation(project, campaign, arm, run),
            "model_provenance": provenance(run, "exchange"),
        }
    native = read(study / "RESULTS.json")["conditions"]["taste"]
    original = read(study / "STUDY.json")["allocations"]["taste"]
    if verified_asset(project, contract["native_comparator"]["campaign"]) != verified_asset(
        project, original["campaign"]
    ):
        raise ValueError("Native comparator changed")
    rows["scitaste-native"] = {
        **native,
        "source": binding(project, study / "RESULTS.json"),
        "native_post_paper_review_revision_available": True,
    }
    recoveries = {}
    recovery = project / "evaluations" / (study.name + "-mlr-agent-delivery-continuation-v4")
    if (recovery / "RESULT.json").is_file():
        result, launch = read(recovery / "RESULT.json"), read(recovery / "CONTRACT.json")
        original_run = project / assignments["mlr-agent"]["run"]
        if Path(launch["original_run"]).resolve() != original_run.resolve():
            raise ValueError("Delivery continuation belongs to a different original run")
        for name, sha in launch["original_bindings"].items():
            if digest(original_run / name) != sha:
                raise ValueError("Continuation modified an original artifact")
        for name, sha in launch["original_submission"].items():
            if digest(recovery / "workspace/submission" / name) != sha:
                raise ValueError("Delivery changed frozen scientific source")
        paper = recovery / result["paper"] if result.get("paper") else None
        recoveries["mlr-agent"] = {
            "result": binding(project, recovery / "RESULT.json"),
            "contract": binding(project, recovery / "CONTRACT.json"),
            "status": result["status"],
            "paper": binding(project, paper) if paper and paper.is_file() else None,
            "new_model_requests": result["model_requests"],
            "charged_model_requests": launch["inherited_model_requests"] + result["model_requests"],
            "new_wall_seconds": result["wall_seconds"],
            "charged_wall_seconds": result["charged_wall_seconds"],
            "completed_experiments_repeated": False,
            "submission_unchanged": result["submission_unchanged"],
            "original_failure_replaced": False,
            "native_post_paper_review_revision_available": False,
            "original_confirmation": rows["mlr-agent"]["confirmation"]["receipt"],
        }
    value = {
        "schema_version": "1.0",
        "campaign": binding(project, campaign),
        "prospective_freeze": binding(project, directory / "FREEZE.json"),
        "original_methods": rows,
        "separately_charged_delivery_recoveries": recoveries,
        "assigned_system_denominator": 3,
        "task_families": 1,
        "within_task_confirmation_contexts": 5,
        "private_winner_substitution": False,
        "formal_evidence_eligible": False,
        "comparison_scope": contract["comparison_scope"],
        "limitations": [
            "Single trajectory per implementation, unknown provider identity and randomness; "
            "not a causal matched-backbone ranking.",
            "Common caps/assets do not equate native stage allocation, fitting "
            "or information consumption.",
            "Operator transport/input recoveries remain interventions, not framework "
            "scientific failures or unassisted completion.",
            "First papers, native review/revision, exports and separately charged recoveries "
            "are distinct endpoints.",
            "Five batches are dependent contexts within one task, not independent research tasks.",
        ],
    }
    retain_json(directory / "SCIENTIFIC_RESULTS.json", value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "study"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    results = summarize(args.project, args.study)
    print(
        json.dumps(
            {
                "original_systems": {
                    k: v["status"] for k, v in results["original_methods"].items()
                },
                "recoveries": list(results["separately_charged_delivery_recoveries"]),
            }
        )
    )

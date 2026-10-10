"""Synthesize sealed research episodes without silently promoting their evidence.

The unit is a frozen task assignment, not a prediction, manuscript paragraph,
recovery, or model response. This public-result reader never loads private labels.
"""

import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset


def binding(root: Path, path: Path) -> dict:
    path = path.resolve(strict=True)
    path.relative_to(root)
    return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}


def synthesize_research_evidence(project: Path, specification: dict) -> dict:
    """Bind original assignments, sealed reports and separately allocated recovery.

    A declared scope can restrict a source but cannot upgrade it to formal. No
    metric is picked by its value, no missing result is imputed, and uncalibrated
    manuscript judgments never become objective scientific outcomes.
    """
    root = project.resolve(strict=True)
    if specification.get("schema_version") != "1.0":
        raise ValueError("Unsupported evidence synthesis schema")
    inputs = specification.get("sources")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("Explicit frozen result sources required")
    seen_campaigns = set()
    tasks = []
    for item in inputs:
        campaign_path = verified_asset(root, item["campaign"])
        assignments_path = verified_asset(root, item["assignments"])
        result_path = verified_asset(root, item["result"])
        seal_path = verified_asset(root, item["submissions"])
        for path in (campaign_path, assignments_path, result_path, seal_path):
            path.relative_to(root / "evaluations")
        if campaign_path in seen_campaigns:
            raise ValueError("A recovery or second seal cannot add a task assignment")
        seen_campaigns.add(campaign_path)
        campaign, assignments, result, seal = (
            json.loads(p.read_bytes())
            for p in (campaign_path, assignments_path, result_path, seal_path)
        )
        arms = campaign["arms"]
        if len(arms) != len(set(arms)) or set(assignments) != set(arms):
            raise ValueError("Frozen arm denominator changed")
        rows = result["rows"]
        if len(rows) != len(arms) or {r["arm"] for r in rows} != set(arms):
            raise ValueError("Result omitted or duplicated an assigned system")
        for packet in (result, seal["observed"]):
            if (
                packet["campaign_sha256"] != digest(campaign_path)
                or packet["task_id"] != campaign["task_id"]
                or packet["assigned_systems"] != len(arms)
            ):
                raise ValueError("Result or manuscript seal belongs to another assignment")
        scope = item["scope"]
        if scope not in {"development", "formal"}:
            raise ValueError("Declare development or formal scope explicitly")
        if scope == "formal" and not (
            campaign.get("formal_evidence_eligible") is True
            and result.get("formal_evidence_eligible") is True
        ):
            raise ValueError("Synthesis cannot promote development results to formal evidence")
        sealed = {r["arm"]: r for r in seal["observed"]["rows"]}
        if len(sealed) != len(arms) or set(sealed) != set(arms):
            raise ValueError("Manuscript seal omitted an assigned system")
        hashes = {r["arm"]: r["paper_sha256"] for r in seal["assessments"]}
        summaries = []
        for row in rows:
            arm = row["arm"]
            assigned_run = assignments[arm]
            if isinstance(assigned_run, dict):
                assigned_run = assigned_run["run"]
            if row["run"] != assigned_run or not row["terminal"]:
                raise ValueError("Only the assigned terminal episode can enter synthesis")
            paper = row.get("paper")
            report_binding = None
            if paper:
                path = (root / paper).resolve(strict=True)
                path.relative_to(root)
                if sealed[arm].get("paper") != paper or hashes.get(arm) != digest(path):
                    raise ValueError("Assessed manuscript changed after its seal")
                report_binding = binding(root, path)
            confirmation = row.get("confirmation")
            claims = row.get("task_claims", [])
            counts = {
                name: sum(c["status"] == name for c in claims)
                for name in ("supported", "partial", "contradicted", "insufficient", "missing")
            }
            if sum(counts.values()) != len(claims):
                raise ValueError(
                    "Unknown scientific claim status cannot disappear from its denominator"
                )
            summaries.append(
                {
                    "arm": arm,
                    "run": assigned_run,
                    "status": row["status"],
                    "assessed_manuscript": report_binding,
                    "manuscript_timepoint": row.get("manuscript_timepoint", "not-recorded"),
                    "confirmation_status": confirmation["status"] if confirmation else "missing",
                    "executed_frozen_source": bool(
                        confirmation and confirmation.get("executed_frozen_source")
                    ),
                    "confirmation_metrics": confirmation.get("metrics", []) if confirmation else [],
                    "scientific_claims": {
                        "denominator": len(claims),
                        "counts": counts,
                        "judge_calibrated": row.get("task_claim_judge_calibrated", False),
                        "scope": "Retained AI judgments, not objective ground truth",
                    },
                    "manuscript_scores": row["scores"],
                    "elapsed_seconds": row.get("elapsed_seconds"),
                    "model_responses": row.get("retained_model_responses"),
                    "actual_tokens": row.get("actual_tokens"),
                    "actual_cost_usd": row.get("actual_cost_usd"),
                    "engineering_recovery": row.get("engineering_recovery", False),
                    "original_lifecycle": row.get("original_lifecycle"),
                    "paper_cycle_complete": row.get("paper_cycle_complete", False),
                    "whole_project_lifecycle_complete": row.get(
                        "whole_project_lifecycle_complete", False
                    ),
                }
            )
        recoveries = []
        if item.get("recovery_index"):
            index_path = verified_asset(root, item["recovery_index"])
            index_path.relative_to(root / "evaluations")
            index = json.loads(index_path.read_bytes())
            if (
                index["campaign_sha256"] != digest(campaign_path)
                or index["assignments_sha256"] != digest(assignments_path)
                or index["original_assignment_replaced"] is not False
            ):
                raise ValueError("Recovery must retain the exact original assignment")
            for recovery in index["recoveries"]:
                path = verified_asset(root, recovery["result"])
                path.relative_to(root / "evaluations")
                value = json.loads(path.read_bytes())
                if (
                    recovery["arm"] not in arms
                    or value.get("arm") != recovery["arm"]
                    or value.get("original_assignment_replaced") is not False
                ):
                    raise ValueError("Invalid independent recovery attribution")
                recoveries.append({"arm": recovery["arm"], "result": binding(root, path)})
        tasks.append(
            {
                "task_id": campaign["task_id"],
                "benchmark": campaign["benchmark"],
                "scope": scope,
                "campaign": binding(root, campaign_path),
                "assignments": binding(root, assignments_path),
                "sealed_result": binding(root, result_path),
                "manuscript_seal": binding(root, seal_path),
                "resource_envelope": campaign["resource_envelope"],
                "native_taste": campaign.get("native_taste"),
                "assigned_systems": len(arms),
                "rows": summaries,
                "separate_recoveries": recoveries,
            }
        )
    return {
        "schema_version": "1.0",
        "selection_rule": specification["selection_rule"],
        "task_assignments": len(tasks),
        "distinct_task_ids": len({t["task_id"] for t in tasks}),
        "assigned_episodes": sum(t["assigned_systems"] for t in tasks),
        "formal_task_assignments": sum(t["scope"] == "formal" for t in tasks),
        "tasks": tasks,
        "scope": (
            "Failure-inclusive sealed episode synthesis; neither method ranking, "
            "causal Taste efficacy, official benchmark score nor venue admission. "
            "Original and recovery outcomes remain separate; no best-metric selection."
        ),
    }

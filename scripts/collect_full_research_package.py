"""Freeze every ML research attempt and its scientific components for shared synthesis."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((args.package / "PLAN.json").read_text())
    rows, bindings, contracts = [], {}, []

    def bind(path):
        path.resolve(strict=True).relative_to(args.package.parent.resolve())
        bindings[path.relative_to(args.package.parent).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        return path.read_text() if path.suffix in {".py", ".md"} else json.loads(path.read_text())

    bind(args.package / "PLAN.json")
    runs = list(plan["runs"])
    amendment_path = args.package / "RUN_AMENDMENT.json"
    if amendment_path.exists():
        amendment = bind(amendment_path)
        runs.extend(amendment["additional_runs"])
    for relative in plan.get("context_artifacts", []):
        bind(args.package.parent / relative)
    runtime_observations = args.package / "RUNTIME_OBSERVATIONS.json"
    if runtime_observations.exists():
        bind(runtime_observations)
    if (args.package / "RESOURCE_DECISION.json").exists():
        bind(args.package / "RESOURCE_DECISION.json")
    if (args.package / "RECOVERY_DIAGNOSTIC.json").exists():
        bind(args.package / "RECOVERY_DIAGNOSTIC.json")

    advisory = args.package / "RUNTIME_ADVISORY.json"
    if advisory.exists():
        amendment = bind(advisory)
        for relative in amendment.get("evidence", []):
            bind(args.package / relative)

    for run in runs:
        root = args.package.parent / run["run_id"]
        contract = bind(root / "CONTRACT.json")
        contracts.append(contract)
        terminal = bind(root / "RESULT.json")
        if (root / "OPERATOR_CONTEXT.json").exists():
            bind(root / "OPERATOR_CONTEXT.json")
        iterative = (root / "ITERATIVE_SUMMARY.json").exists()
        summary = bind(
            root / ("ITERATIVE_SUMMARY.json" if iterative else "DEVELOPMENT_SUMMARY.json")
        )
        for decision in sorted((root / "loop").glob("decision-*.json")):
            bind(decision)
        trace = root / "tools/TOOL_TRACE.jsonl"
        if trace.exists():
            bindings[trace.relative_to(args.package.parent).as_posix()] = hashlib.sha256(
                trace.read_bytes()
            ).hexdigest()
        attempts = []
        for attempt in sorted((root / "tools/experiments").glob("attempt-*")):
            reservation = bind(attempt / "RESERVATION.json")
            for relative, expected in reservation["source_sha256"].items():
                source = attempt / "candidate" / relative
                source.resolve(strict=True).relative_to((attempt / "candidate").resolve())
                if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                    raise ValueError("Retained candidate differs from executed reservation")
                bind(source)
            collected = root / "executions" / attempt.name / "collected"
            for receipt in sorted(collected.rglob("*.json")):
                bind(receipt)
            result = bind(attempt / "RESULT.json") if (attempt / "RESULT.json").exists() else None
            attempts.append(
                {
                    "attempt": attempt.name,
                    "status": result["status"] if result else "unresolved",
                    "primary_value": result.get("data", {}).get("primary_value")
                    if result
                    else None,
                    "metrics": result.get("data", {}).get("metrics", {}) if result else {},
                    "replica_receipts": result.get("data", {}).get("collected_replica_receipts")
                    if result
                    else None,
                    "error": result.get("error") if result else None,
                    "execution_seconds": result.get("cost", {}).get("wall_time_hours", 0) * 3600
                    if result
                    else None,
                    "cost_complete": result.get("data", {}).get("cost_complete")
                    if result
                    else False,
                }
            )
        if not iterative:
            result_path = root / "EXECUTION_RESULT.json"
            if not result_path.exists():
                for relative in contract["task"]["required_files"]:
                    source = root / "candidate" / relative
                    source.resolve(strict=True).relative_to((root / "candidate").resolve())
                    bind(source)
            if result_path.exists():
                result = bind(result_path)
                binding = bind(root / "BINDING.json")
                manifest_path = root / "bundle/MANIFEST.json"
                if (
                    hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    != binding["bundle_manifest_sha256"]
                ):
                    raise ValueError("Executed bundle manifest changed")
                manifest = bind(manifest_path)
                for relative, expected in manifest["files"].items():
                    source = root / "bundle" / relative
                    source.resolve(strict=True).relative_to((root / "bundle").resolve())
                    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                        raise ValueError("Executed bundle source changed")
                    if relative.startswith("branches/agent-candidate/"):
                        bind(source)
                bind(root / "CANDIDATE_PROVENANCE.json")
                details = None
                if (root / "SCORE_DETAILS.json").exists():
                    details = bind(root / "SCORE_DETAILS.json")
                    if (
                        details["execution_result_sha256"]
                        != hashlib.sha256(result_path.read_bytes()).hexdigest()
                    ):
                        raise ValueError("Score details reference a different execution")
                    raw_score = details["raw_score_text"].encode()
                    if (
                        hashlib.sha256(raw_score).hexdigest()
                        != result["data"]["receipt"]["score_file_sha256"]
                    ):
                        raise ValueError("Official detailed score content changed")
                    parsed_scores = {
                        key: float(value)
                        for key, value in (
                            line.split(":", 1) for line in raw_score.decode().splitlines()
                        )
                    }
                    if parsed_scores != details["official_scores"]:
                        raise ValueError("Detailed metric values differ from source")
                attempts.append(
                    {
                        "attempt": "single-candidate",
                        "status": result["status"],
                        "primary_value": result.get("data", {}).get("primary_value"),
                        "metrics": details["official_scores"]
                        if details
                        else result.get("data", {}).get("metrics", {}),
                        "replica_receipts": None,
                        "error": result.get("error")
                        or result.get("data", {}).get("receipt", {}).get("failure_summary"),
                        "execution_seconds": result.get("cost", {}).get("wall_time_hours", 0)
                        * 3600,
                        "cost_complete": result.get("data", {}).get("cost_complete", False),
                    }
                )
        responses = list((root / "session-exchange").glob("*.response.json"))
        scored = [
            attempt
            for attempt in attempts
            if attempt["status"] == "SUCCEEDED" and attempt["primary_value"] is not None
        ]
        best_new = (
            sorted(
                scored,
                key=lambda attempt: attempt["primary_value"],
                reverse=contract["task"]["objective_direction"] == "maximize",
            )[0]
            if scored
            else None
        )
        if not iterative:
            baseline = contract["task"].get("baseline_score")
            best = best_new["primary_value"] if best_new else None
            better = best is not None and (
                baseline is None
                or (
                    best > baseline
                    if contract["task"]["objective_direction"] == "maximize"
                    else best < baseline
                )
            )
            summary = {
                **summary,
                "baseline_score": baseline,
                "best_observed_value": best if better else baseline,
                "best_observed_identity": "single-candidate"
                if better
                else "original-baseline"
                if baseline is not None
                else None,
            }
        rows.append(
            {
                "arm": run["arm"],
                "system": run["system"],
                "status": terminal["status"],
                "attempts": attempts,
                "new_scored_evaluations": len(scored),
                "best_new_candidate": best_new,
                "best_observed_identity": summary["best_observed_identity"],
                "best_observed_value": summary["best_observed_value"],
                "baseline_score": summary["baseline_score"],
                "baseline_semantics": "historical reference; not a new paired control"
                if summary["baseline_score"] is not None
                else "no supplied baseline score; new control is an explicit attempt",
                "grounded_deliberation": summary.get("grounded_deliberation"),
                "session_responses": len(responses),
                "actual_session_tokens": None,
                "actual_session_cost": None,
                "provider_api_calls": 0,
            }
        )
    if not contracts:
        raise ValueError("Research package has no runs")
    if len(contracts) == 1 and plan.get("package_type") != "single-system-scientific-followup":
        raise ValueError("A single run must explicitly declare follow-up rather than comparison")
    if any(contract["task"] != contracts[0]["task"] for contract in contracts[1:]):
        raise ValueError("Compared systems did not receive identical tasks and budgets")
    interfaces = [c.get("tool_interface_sha256") for c in contracts]
    # External adapter retains its exact shared-tool descriptor separately.
    for index, run in enumerate(runs):
        path = args.package.parent / run["run_id"] / "TOOL_INTERFACE.json"
        if path.exists():
            interfaces[index] = bind(path)["sha256"]
    if not all(interfaces) or any(interface != interfaces[0] for interface in interfaces[1:]):
        raise ValueError("Compared shared-tool interfaces differ")
    retain_json(
        args.package / "FINAL_REPORT.json",
        {
            "rows": rows,
            "result_sha256": bindings,
            "task": contracts[0]["task"],
            "shared_tool_interface_sha256": interfaces[0],
            "formal_evidence_eligible": False,
            "taste_effect_identified": False,
            "gpu_execution": True,
            "provider_api_calls": 0,
            "total_session_responses": sum(r["session_responses"] for r in rows),
            "scope": plan["scope"],
            "package_type": plan.get("package_type", "system-comparison"),
            "writing_semantics": (
                "common downstream report/review adapter, not upstream-native writing"
            ),
        },
    )
    print(json.dumps({"arms": len(rows), "attempts": sum(len(r["attempts"]) for r in rows)}))


if __name__ == "__main__":
    main()

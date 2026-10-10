"""Aggregate original and separately recovered outcomes without replacing failures."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--plan-name", default="PLAN.json")
    parser.add_argument("--report-name", default="FINAL_REPORT.json")
    args = parser.parse_args()
    if any(Path(name).name != name for name in (args.plan_name, args.report_name)):
        raise ValueError("Plan and report names must be package-local basenames")
    if args.plan_name == args.report_name:
        raise ValueError("A report cannot overwrite its plan")
    plan_bytes = (args.package / args.plan_name).read_bytes()
    plan = json.loads(plan_bytes)
    rows, hashes = [], {}
    for run in plan["runs"]:
        directory = args.package.parent / run["run_id"]
        result_path = directory / "RESULT.json"
        result = json.loads(result_path.read_text())
        controller_path = directory / "CONTROLLER_TERMINAL.json"
        controller = json.loads(controller_path.read_text()) if controller_path.exists() else result
        recovered = args.package / "terminal-recovery" / run["run_id"] / "RESULT.json"
        final = json.loads(recovered.read_text()) if recovered.exists() else {}
        for path in (
            result_path,
            recovered,
            controller_path,
            directory / "CONTRACT.json",
            directory / "tools/TOOL_TRACE.jsonl",
            directory / "FROZEN_SUBMISSION.json",
            directory / "TERMINAL_DELIVERY.json",
        ):
            if path.exists():
                hashes[str(path.relative_to(args.package.parent))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        records = list(directory.glob("**/provider_calls"))
        accounts = [provider_ledger_accounting(path) for path in records]
        responses = [
            json.loads(path.read_text()) for record in records for path in record.glob("*.response")
        ]
        session_responses = [
            json.loads(path.read_text())
            for exchange in ("session-exchange", "judge-exchange")
            for path in (directory / exchange).glob("*.response.json")
        ]
        session_run = result.get("accounting", {}).get("source") == "assistant-session"
        deliberations = [
            json.loads(path.read_text())
            for path in (directory / "taste_deliberation").glob("[0-9]*.json")
        ]
        accepted = [d for d in deliberations if d.get("reason") == "verified-deliberation"]
        consultations = [d for d in deliberations if d.get("runtime_receipt")]
        selections = sum(
            len((d["runtime_receipt"]["result"].get("proposal") or {}).get("selected_case_ids", []))
            for d in accepted
        )
        rows.append(
            {
                "task": run["task"],
                "arm": run["arm"],
                "original_status": controller["status"],
                "system_status": result["status"],
                "queries": result.get("queries_used"),
                "code_calls": result.get("code_calls_used", 0),
                "original_submission": controller.get("submission"),
                "final_submission": result.get("submission"),
                "system_metrics": result.get("objective", {}).get("metrics"),
                "common_terminal_used": (directory / "TERMINAL_DELIVERY.json").exists(),
                "terminal_recovery_status": final.get("status"),
                "terminal_recovery_metrics": final.get("objective", {}).get("metrics"),
                "provider_calls": sum(a["calls"] for a in accounts),
                "session_responses": len(session_responses),
                "session_tokens": None if session_run else 0,
                "session_cost_usd": None if session_run else 0,
                "execution_source": "assistant-session" if session_run else "provider-api",
                "provider_tokens": sum(
                    r.get("usage", {}).get("prompt_tokens", 0)
                    + r.get("usage", {}).get("completion_tokens", 0)
                    for r in responses
                ),
                "conservative_liability_usd": sum(a["liability_usd"] for a in accounts),
                "unresolved_reservations": sum(a["unresolved_reservations"] for a in accounts),
                "served_models": sorted({r.get("model", "unknown") for r in responses}),
                "taste_decision_records": len(deliberations),
                "taste_consultations": len(consultations),
                "skipped_deliberation_reasons": [
                    d.get("reason") for d in deliberations if not d.get("runtime_receipt")
                ],
                "accepted_deliberations": len(accepted),
                "selected_precedents": selections,
                "rejected_deliberation_reasons": [
                    d.get("runtime_receipt", {}).get("blockers")
                    for d in consultations
                    if d not in accepted
                ],
            }
        )
    report = {
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "scope": plan.get("scope", "development-results"),
        "rows": rows,
        "result_sha256": hashes,
        "original_valid_submissions": sum(r["original_submission"] is not None for r in rows),
        "system_scored": sum(r["system_status"] == "scored-development-run" for r in rows),
        "terminal_recovery_scored": sum(
            r["terminal_recovery_status"] == "scored-terminal-recovery" for r in rows
        ),
        "total_provider_calls": sum(r["provider_calls"] for r in rows),
        "total_session_responses": sum(r["session_responses"] for r in rows),
        "session_tokens_and_cost": "unknown"
        if any(r["execution_source"] == "assistant-session" for r in rows)
        else "not-used",
        "total_provider_tokens": sum(r["provider_tokens"] for r in rows),
        "total_conservative_liability_usd": sum(r["conservative_liability_usd"] for r in rows),
        "cost_semantics": "Conservative usage liability, not tariff or invoice",
        "formal_evidence_eligible": False,
        "taste_effect_identified": False,
        "gpu_execution": False,
    }
    retain_json(args.package / args.report_name, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "result_sha256"}}))


if __name__ == "__main__":
    main()

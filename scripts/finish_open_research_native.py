"""Continue a benchmark Native run into its actual paper cycle within remaining budget.

This does not write research content or replace any model node. Model requests are
served through the existing session exchange by isolated response authors.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project.models import validate_entry_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "source-run", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--resume-watch",
        action="store_true",
        help="Resume an interrupted observer only before any paper lifecycle was launched",
    )
    parser.add_argument(
        "--paper-prefix", help="New paper identity for an explicit delivery recovery"
    )
    parser.add_argument(
        "--report-appendix-heading", help="Keep the named appendix outside main prose"
    )
    parser.add_argument(
        "--report-delivery",
        type=Path,
        help="Explicit fresh report-only destination inside this failed-cycle recovery",
    )
    parser.add_argument(
        "--reuse-report-delivery",
        type=Path,
        help="Reuse an existing bound completed report; never regenerate retained evidence",
    )
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    source, campaign = args.source_run.resolve(strict=True), args.campaign.resolve(strict=True)
    output = args.output.resolve()
    for path in (source, campaign, output):
        path.relative_to(root)
    launch_path = source / "CONTRACT.json"
    launch = json.loads(launch_path.read_text())
    if verified_asset(root, launch["plan"]["campaign"]) != campaign:
        raise ValueError("Run/campaign mismatch")
    contract = json.loads(campaign.read_text())
    budget = contract["resource_envelope"]
    # Start from original launch, not this later delivery invocation.
    inherited = launch.get("continuation") or {}
    started_at = launch_path.stat().st_mtime - inherited.get("inherited_duration_seconds", 0)
    remaining_at_entry = max(0, started_at + budget["wall_seconds"] - time.time())
    deadline = time.monotonic() + remaining_at_entry
    if args.resume and args.resume_watch:
        raise ValueError("Choose failed-delivery recovery or interrupted-watch recovery")
    output.mkdir(parents=True, exist_ok=args.resume or args.resume_watch)
    if args.paper_prefix and not args.resume:
        raise ValueError("A paper identity override requires an explicit failed-cycle recovery")
    if args.report_delivery and args.reuse_report_delivery:
        raise ValueError("Choose a fresh report delivery OR an existing one, not both")
    selected_delivery = args.report_delivery or args.reuse_report_delivery
    delivery = selected_delivery.resolve() if selected_delivery else output / "delivery"
    delivery.relative_to(output)
    if args.report_delivery and (not args.resume or delivery.exists()):
        raise ValueError("Explicit report recovery needs a fresh destination and --resume")
    if args.reuse_report_delivery and (not args.resume or not (delivery / "RESULT.json").is_file()):
        raise ValueError("Report reuse requires an explicit recovery and existing receipt")
    prefix = args.paper_prefix or source.name + "-paper"
    validate_entry_id(prefix, field_name="paper prefix")
    exchange = output / "exchange"
    result_path = output / "RESULT.json"
    log_path = output / "lifecycle.log"
    if args.resume:
        previous = json.loads((output / "CONTRACT.json").read_text())
        failure = json.loads((output / "RESULT.json").read_text())
        if (
            previous["campaign_sha256"] != digest(campaign)
            or previous["source_contract_sha256"] != digest(launch_path)
            or failure["status"] != "paper-cycle-stopped"
        ):
            raise ValueError("Only a bound failed paper-cycle continuation is allowed")
        attempts = output / "resumes"
        attempts.mkdir(exist_ok=True)
        prior_results = sorted(attempts.glob("*.result.json"))
        legacy = output / "RESUMED_RESULT.json"
        if legacy.exists():
            prior_results.insert(0, legacy)
        if len(prior_results) >= 3 or any(
            json.loads(path.read_text())["status"] == "paper-cycle-completed"
            for path in prior_results
        ):
            raise ValueError("Paper recovery completed or three attempts exhausted")
        attempt = len(prior_results) + 1
        result_path = attempts / f"{attempt:02d}.result.json"
        log_path = attempts / f"{attempt:02d}.log"
    elif args.resume_watch:
        previous = json.loads((output / "CONTRACT.json").read_text())
        if (
            previous["campaign_sha256"] != digest(campaign)
            or previous["source_contract_sha256"] != digest(launch_path)
            or previous["paper_prefix"] != prefix
            or previous["max_requests"] != budget["max_requests"]
            or any(
                (output / name).exists()
                for name in ("RESULT.json", "COMMAND.json", "lifecycle.log", "delivery")
            )
        ):
            raise ValueError("Only an unchanged interrupted pre-launch observer can resume")
        for process in Path("/proc").iterdir():
            if not process.name.isdigit():
                continue
            try:
                argv = (process / "cmdline").read_bytes().decode().split("\0")
                cwd = (process / "cwd").resolve(strict=True)
            except (OSError, UnicodeError):
                continue
            if (
                int(process.name) == os.getpid()
                or argv[1:3] != ["-m", "scripts.finish_open_research_native"]
                or "--output" not in argv
            ):
                continue
            target = Path(argv[argv.index("--output") + 1])
            if (target if target.is_absolute() else cwd / target).resolve() == output:
                raise ValueError("An observer still owns this output")
        retain_json(
            output / "WATCH_RECOVERY.json",
            {
                "status": "observer-resumed-before-paper-launch",
                "source_contract_sha256": digest(launch_path),
                "original_watch_contract_sha256": digest(output / "CONTRACT.json"),
                "remaining_wall_seconds": remaining_at_entry,
                "budget_reset": False,
                "research_relaunched": False,
                "scientific_completion_inferred": False,
            },
        )
    else:
        previous = None
    retain_json(
        output / "CONTRACT.json",
        previous
        or {
            "campaign_sha256": digest(campaign),
            "source_contract_sha256": digest(launch_path),
            "source_run": source.relative_to(root).as_posix(),
            "paper_prefix": prefix,
            "max_requests": budget["max_requests"],
            "remaining_wall_seconds_at_entry": remaining_at_entry,
            "time_origin": "original research CONTRACT file timestamp, not a fresh delivery budget",
            "supplier_api_calls": 0,
            "recovery_excluded_from_original_run_score": bool(inherited),
            "inherited_session_requests": inherited.get("inherited_session_requests", 0),
        },
    )

    def count_requests():
        return (
            inherited.get("inherited_session_requests", 0)
            + len(list((source / "exchange").glob("*.request.json")))
            + len(list(exchange.rglob("*.request.json")))
        )

    def finish(status, **fields):
        result = {
            "status": status,
            "observed_requests": count_requests(),
            "elapsed_seconds_since_research_launch": time.time() - started_at,
            "source_run": source.relative_to(root).as_posix(),
            "paper_prefix": prefix,
            "formal_evidence_eligible": False,
            **fields,
        }
        if args.resume:
            result["original_failure_sha256"] = digest(output / "RESULT.json")
            result["engineering_recovery"] = True
        retain_json(result_path, result)
        print(json.dumps(result))

    while not (source / "RESULT.json").is_file():
        if time.monotonic() >= deadline:
            finish("research-did-not-close-within-lifecycle-budget")
            return 2
        time.sleep(5)
    if not (source / "workspace/report/report.md").is_file():
        finish("research-terminated-without-paper")
        return 2
    if count_requests() >= budget["max_requests"]:
        finish("no-response-budget-for-paper-cycle")
        return 2
    command = [
        sys.executable,
        "-m",
        "scripts.run_native_report_lifecycle",
        "--project",
        str(root),
        "--source-run",
        str(source),
        "--delivery",
        str(delivery),
        "--paper-prefix",
        prefix,
        "--session-exchange",
        str(exchange),
    ]
    if args.report_appendix_heading:
        command.extend(["--report-appendix-heading", args.report_appendix_heading])
    command_path = output / "COMMAND.json"
    if args.resume:
        command_path = attempts / f"{attempt:02d}.command.json"
        retain_json(
            attempts / f"{attempt:02d}.contract.json",
            {
                "original_contract_sha256": digest(output / "CONTRACT.json"),
                "original_failure_sha256": digest(output / "RESULT.json"),
                "paper_prefix": prefix,
                "report_appendix_heading": args.report_appendix_heading,
                "report_delivery": delivery.relative_to(root).as_posix(),
                "reused_existing_report": bool(args.reuse_report_delivery),
                "remaining_wall_seconds_at_entry": remaining_at_entry,
                "research_budget_reset": False,
                "research_source_edited": False,
                "recovery_excluded_from_original_run_score": True,
            },
        )
    retain_json(command_path, {"command": command})
    with log_path.open("x") as log:
        reason = None
        while True:
            process = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            while process.poll() is None:
                if time.monotonic() >= deadline or count_requests() > budget["max_requests"]:
                    reason = "lifecycle-budget-exhausted"
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                    break
                time.sleep(1)
            if reason or process.returncode != 75:
                break
            # A session coordinator's exit 75 is a retained model handoff, not
            # a failed paper cycle. Resume its exact bound input only after the
            # corresponding reply arrives; do not regenerate research/reports.
            pending = [
                path
                for path in exchange.rglob("*.request.json")
                if not path.with_name(path.name.replace(".request.json", ".response.json")).exists()
            ]
            if not pending:
                reason = "session-wait-without-retained-request"
                break
            log.write(json.dumps({"status": "session-model-wait", "pending": len(pending)}) + "\n")
            log.flush()
            while any(
                not path.with_name(path.name.replace(".request.json", ".reply.json")).is_file()
                for path in pending
            ):
                if time.monotonic() >= deadline or count_requests() > budget["max_requests"]:
                    reason = "lifecycle-budget-exhausted"
                    break
                time.sleep(5)
            if reason:
                break
    finish(
        reason or ("paper-cycle-completed" if process.returncode == 0 else "paper-cycle-stopped"),
        return_code=process.returncode,
        cycle_summary=str(
            (root / "evaluations" / (prefix + "-cycle/SUMMARY.json")).relative_to(root)
        ),
        review_closed=False,
    )
    return 0 if process.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

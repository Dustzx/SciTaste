"""Compose an idea-bound Native study, measured paper flow and experience disposition."""

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.executor.project_task import load_project_task
from scitaste.project.models import validate_entry_id
from scitaste.project.research_artifact import register_artifact


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_parser(parser):
    for key in ("project", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--plan", type=Path)
    selection.add_argument("--objective", help="Plan and provision a Native task before execution")
    for key in (
        "planning-prepared-task",
        "planning-workspace-resources",
        "planning-evidence",
        "planning-acquisition-option",
    ):
        parser.add_argument(f"--{key}", type=Path, action="append", default=[])
    parser.add_argument("--acquire-planning-resources", action="store_true")
    parser.add_argument("--planning-backend", type=Path)
    parser.add_argument(
        "--executor", choices=("unlearning", "native-workspace"), default="unlearning"
    )
    for key in ("brief", "baseline-run", "baseline-source", "execution-run", "report-delivery"):
        parser.add_argument(f"--{key}", type=Path)
    parser.add_argument("--paper-prefix")
    for key in (
        "task-context",
        "development-taste-library",
        "taste-deliberation-profile",
        "development-policy-refresh",
        "workflow-gaps",
        "paper-backend",
        "review-profile",
        "venue-taste-profile",
        "credentials",
        "session-exchange",
        "paper-flow",
        "figure-contract-repair",
        "research-state",
        "next-plan-format-recovery",
    ):
        parser.add_argument(f"--{key}", type=Path)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--next-workspace-resources", type=Path, action="append", default=[])
    parser.add_argument("--next-acquisition-option", type=Path, action="append", default=[])
    parser.add_argument("--acquire-next-resources", action="store_true")
    parser.add_argument("--allow-network-download", action="store_true")
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument(
        "--taste-decision-context",
        choices=("legacy-full", "bounded-research-source-v1"),
    )
    parser.add_argument(
        "--taste-proposal-context",
        choices=(
            "disabled",
            "reviewed-conditional-v1",
            "reviewed-inquiry-v1",
            "source-passages-v1",
        ),
    )
    parser.add_argument("--taste-action-selection", choices=("enabled", "disabled"))
    parser.add_argument("--max-execution-continuations", type=int, choices=range(4), default=0)
    parser.add_argument(
        "--next-planning-objective",
        help="After delivery, propose the next plan using this cycle; never auto-launch it",
    )
    return parser


def main(argv=None):
    parser = configure_parser(argparse.ArgumentParser(description=__doc__))
    args = parser.parse_args(argv)
    if args.research_state and args.executor != "native-workspace":
        parser.error("Canonical predecessor state currently requires Native workspace")
    if (args.planning_acquisition_option or args.acquire_planning_resources) and not args.objective:
        parser.error("Initial resource acquisition requires --objective")
    if args.session_exchange and (args.allow_api or args.executor != "native-workspace"):
        parser.error("Session exchange requires Native and cannot enable API calls")
    if args.executor == "native-workspace":
        if args.objective:
            from scitaste.project.cycle_planning import prepare_cycle_plan

            args.plan = prepare_cycle_plan(args)
            if args.plan is None:
                return
        from scitaste.project.native_workspace_cycle import run_cycle

        return run_cycle(args)
    if args.objective:
        parser.error("Objective-to-execution orchestration currently requires Native workspace")
    if not all((args.brief, args.baseline_run, args.baseline_source)):
        parser.error("unlearning requires --brief, --baseline-run and --baseline-source")
    if any(
        (
            args.execution_run,
            args.report_delivery,
            args.paper_prefix,
            args.paper_backend,
            args.review_profile,
            args.venue_taste_profile,
            args.credentials,
            args.next_workspace_resources,
            args.next_acquisition_option,
            args.acquire_next_resources,
            args.allow_network_download,
            args.max_execution_continuations,
        )
    ):
        parser.error("Native workspace delivery options require --executor native-workspace")
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    validate_entry_id(output.name, field_name="cycle identity")
    for path in (args.plan, args.brief, args.baseline_run, args.baseline_source):
        path.resolve(strict=True).relative_to(root)
    if bool(args.development_taste_library) != bool(args.taste_deliberation_profile):
        raise ValueError("Taste library and profile must be supplied together")
    if args.development_policy_refresh and args.development_taste_library:
        raise ValueError("This cycle supports either learned allocation or library deliberation")
    task, _, plan_binding = load_project_task(root, args.plan, adapter="unlearning", iterative=True)
    base = root / "evaluations"
    execution = base / (output.name + "-execution")
    delivery = execution.with_name(execution.name + "-delivery")
    paper = base / (output.name + "-paper")
    experience = base / (paper.name + "-experience-disposition")
    inputs = {
        "plan": sha(args.plan),
        "brief": sha(args.brief),
        "baseline_result": sha(args.baseline_run / "EXECUTION_RESULT.json"),
    }
    baseline_sources = {
        str(p.relative_to(args.baseline_source)): sha(p)
        for p in sorted(args.baseline_source.rglob("*.py"))
        if p.is_file()
    }
    if not baseline_sources:
        raise ValueError("Baseline source must contain frozen Python source")
    for key in ("task_context", "development_taste_library", "taste_deliberation_profile"):
        path = getattr(args, key)
        if path:
            inputs[key] = sha(path)
    if args.workflow_gaps:
        args.workflow_gaps.resolve(strict=True).relative_to(root)
        inputs["workflow_gaps"] = sha(args.workflow_gaps)
    if args.development_policy_refresh:
        from scitaste.project import ProjectRuntime
        from scitaste.taste.project_policy import load_project_taste_policy_refresh

        load_project_taste_policy_refresh(
            ProjectRuntime(root.parent.parent),
            project_id=root.name,
            directory=args.development_policy_refresh,
        )
        inputs["development_policy_refresh"] = sha(args.development_policy_refresh / "REFRESH.json")
    contract = {
        "scope": "prepared-idea-study-to-paper-and-experience",
        "project": root.name,
        "inputs": inputs,
        "project_plan": plan_binding,
        "baseline_sources": baseline_sources,
        "execution": execution.name,
        "paper_flow": paper.name,
        "max_api_liability_usd": 12,
        "max_experiments": task.max_experiments,
        "max_execution_seconds": task.total_wall_seconds,
        "autonomous_study_design": False,
        "formal_evidence_eligible": False,
    }
    if args.next_planning_objective:
        contract["continuation"] = {
            "objective": args.next_planning_objective,
            "max_additional_api_liability_usd": 3,
            "automatic_experiment_execution": False,
        }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract_path = output / "CONTRACT.json"
        if contract_path.exists():
            if json.loads(contract_path.read_text()) != contract:
                raise ValueError("Cycle input changed; do not resume under this identity")
        else:
            with contract_path.open("x") as stream:
                json.dump(contract, stream, indent=2)
        if not (execution / "RESULT.json").exists():
            marker = output / "execution.started.json"
            if execution.exists() or marker.exists():
                raise ValueError("Execution already started; observe/reconcile it, never relaunch")
            if not args.allow_api or not args.allow_execution:
                print(
                    json.dumps({"status": "prepared-not-executed", "contract": str(contract_path)})
                )
                return
            command = [
                sys.executable,
                "-m",
                "scripts.run_native_tools_development",
                "--project",
                str(root),
                "--project-plan",
                str(args.plan.resolve()),
                "--output",
                str(execution),
                "--task",
                "unlearning",
                "--iterative",
                "--capture-taste-trajectory",
                "--finish-at-experiment-limit",
                "--allow-api",
                "--allow-execution",
                "--delivery-baseline-run",
                str(args.baseline_run.resolve()),
                "--delivery-baseline-source",
                str(args.baseline_source.resolve()),
            ]
            for key in (
                "task_context",
                "development_taste_library",
                "taste_deliberation_profile",
                "development_policy_refresh",
            ):
                if getattr(args, key):
                    command.extend(
                        ["--" + key.replace("_", "-"), str(getattr(args, key).resolve())]
                    )
            with marker.open("x") as stream:
                json.dump({"command": command, "automatic_retry": False}, stream)
            print(
                "Starting idea-bound experiment loop; progress retained in execution.log",
                flush=True,
            )
            with (output / "execution.log").open("x") as log:
                run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            with (output / "execution.exit.json").open("x") as stream:
                json.dump({"returncode": run.returncode}, stream)
        if not (execution / "RESULT.json").exists():
            raise ValueError("No terminal execution receipt; retain run and inspect execution.log")
        executed_contract = json.loads((execution / "CONTRACT.json").read_text())
        if executed_contract.get("project_plan") != plan_binding:
            raise ValueError("Executed study differs from the bound project plan")
        if not (delivery / "SELECTION.json").exists():
            raise ValueError(
                "Measured delivery unavailable; inspect pending/failed execution, no restart"
            )
        command = [
            sys.executable,
            "-m",
            "scripts.run_measured_paper_lifecycle",
            "--project",
            str(root),
            "--delivery",
            str(delivery),
            "--brief",
            str(args.brief.resolve()),
            "--output",
            str(paper),
            "--evidence",
            str(execution / "CONTRACT.json"),
            "--sectioned-draft",
        ]
        if args.allow_api:
            command.append("--allow-api")
        print("Continuing measured paper and experience flow", flush=True)
        with (output / "paper.log").open("a") as log:
            run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        if run.returncode:
            raise ValueError("Paper flow stopped; inspect paper.log and retained checkpoints")
        disposition = json.loads((experience / "RESULT.json").read_text())
        result = {
            "status": "prepared-study-flow-complete"
            if disposition["status"] == "segment-complete"
            else "experience-disposition-pending",
            "contract_sha256": sha(contract_path),
            "execution_result_sha256": sha(execution / "RESULT.json"),
            "source_terminal_status": json.loads((execution / "RESULT.json").read_text())["status"],
            "paper_summary_sha256": sha(paper / "SUMMARY.json"),
            "experience_result_sha256": sha(experience / "RESULT.json"),
            "paper_directory": disposition["paper_directory"],
            "autonomous_study_design": False,
            "scientific_quality_established": False,
            "whole_project_lifecycle_complete": False,
        }
        result_path = output / "RESULT.json"
        if result_path.exists():
            if json.loads(result_path.read_text()) != result:
                raise ValueError("Completed cycle changed")
        else:
            with result_path.open("x") as stream:
                json.dump(result, stream, indent=2)
        register_artifact(
            project=root,
            artifact=result_path,
            provider="native-lifecycle",
            model="stage-bound",
            condition=contract["scope"],
            status=result["status"],
        )
        if args.next_planning_objective:
            next_plan = base / (output.name + "-next-plan")
            next_result = next_plan / "RESULT.json"
            marker = output / "next-plan.started.json"
            if not next_result.exists():
                if marker.exists() or next_plan.exists():
                    raise ValueError(
                        "Next planning already started; inspect it, no automatic retry"
                    )
                if not args.allow_api:
                    print(json.dumps({**result, "next_plan_status": "awaiting-api-enablement"}))
                    return
                command = [
                    sys.executable,
                    "-m",
                    "scripts.plan_project_research",
                    "--project",
                    str(root),
                    "--previous-cycle",
                    str(output),
                    "--previous-paper-flow",
                    str(paper),
                    "--output",
                    str(next_plan),
                    "--objective",
                    args.next_planning_objective,
                    "--allow-api",
                ]
                if args.workflow_gaps:
                    command.extend(["--workflow-gaps", str(args.workflow_gaps.resolve())])
                with marker.open("x") as stream:
                    json.dump({"command": command, "automatic_retry": False}, stream)
                with (output / "next-plan.log").open("x") as log:
                    planned = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
                with (output / "next-plan.exit.json").open("x") as stream:
                    json.dump({"returncode": planned.returncode}, stream)
                if not next_result.exists():
                    raise ValueError("Next planning stopped; completed cycle remains available")
            next_status = json.loads(next_result.read_text())["status"]
            continuation = {
                "cycle_result_sha256": sha(result_path),
                "next_plan_result": str(next_result.relative_to(root)),
                "next_plan_result_sha256": sha(next_result),
                "status": next_status,
                "scientific_adequacy_established": False,
                "execution_authorized": False,
            }
            receipt = output / "NEXT_PLAN.json"
            if receipt.exists():
                if json.loads(receipt.read_text()) != continuation:
                    raise ValueError("Existing continuation changed")
            else:
                with receipt.open("x") as stream:
                    json.dump(continuation, stream, indent=2)
            register_artifact(
                project=root,
                artifact=receipt,
                provider="lifecycle-continuation",
                model="stage-bound",
                condition="cycle-to-next-plan",
                status="next-plan-" + next_status,
                run_id=output.name + "-continuation",
            )
        print(json.dumps(result))


if __name__ == "__main__":
    main()

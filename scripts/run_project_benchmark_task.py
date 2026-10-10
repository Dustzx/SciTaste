"""Execute/resume delivery of a prepared project benchmark task without blind relaunch."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scitaste.executor.benchmark_task import load_benchmark_task
from scitaste.project.models import validate_entry_id
from scitaste.project.research_artifact import register_artifact
from scripts import run_mlrc_native_development_loop as shared
from scripts.import_benchmark_delivery import deliver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "plan", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--capture-decisions", action="store_true")
    parser.add_argument("--paper-brief", type=Path)
    parser.add_argument("--report-paper-prefix")
    parser.add_argument("--paper-evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    plan = load_benchmark_task(root, args.plan)
    config = shared.load_structured_openai_compatible_config(Path(plan["backend"]["path"]))
    if args.paper_brief:
        args.paper_brief.resolve(strict=True).relative_to(root)
    if args.paper_brief and args.report_paper_prefix:
        raise ValueError("Choose actual report continuation or a newly drafted case study")
    if args.report_paper_prefix:
        validate_entry_id(args.report_paper_prefix, field_name="report-paper-prefix")
    if args.paper_evidence and not args.report_paper_prefix:
        raise ValueError("Paper evidence requires an actual report continuation")
    for path in args.paper_evidence:
        path.resolve(strict=True).relative_to(root)
    run = output.with_name(output.name + "-execution")
    delivery = output.with_name(output.name + "-delivery")
    # Materialize terminal results separately; neither paper failure nor missing
    # score grants permission to repeat agent execution.
    contract = {
        "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        "executor_source_sha256": hashlib.sha256(
            Path("scripts/run_researchclawbench_system_arm.py").read_bytes()
        ).hexdigest(),
        "python": sys.executable,
        "scope": "prepared-benchmark-task-to-delivery",
    }
    if args.capture_decisions:
        contract["decision_capture"] = "prospective-tool-observations-v1"
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract_path = output / "CONTRACT.json"
        if contract_path.exists():
            retained = json.loads(contract_path.read_text())
            if {k: v for k, v in retained.items() if k != "executor_source_sha256"} != {
                k: v for k, v in contract.items() if k != "executor_source_sha256"
            }:
                raise ValueError("Bound task/executor changed; cannot resume")
            # Completed receipts retain their original executor provenance. New
            # source bytes matter only if this invocation would actually launch.
            retained_executor = retained["executor_source_sha256"]
        else:
            retained_executor = contract["executor_source_sha256"]
            with contract_path.open("x") as stream:
                json.dump(contract, stream, indent=2)
        receipt = run / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
        if not receipt.exists():
            marker = output / "execution.started.json"
            if marker.exists() or run.exists():
                raise ValueError("Existing execution requires observation/recovery, not relaunch")
            if not args.allow_api or not args.allow_execution:
                raise ValueError("Fresh task requires explicit API and execution enablement")
            if retained_executor != contract["executor_source_sha256"]:
                raise ValueError("Executor changed before launch; prepare a new execution identity")
            shared._bind_credential(
                Path("outputs/resources/access/credentials.env"), config.api_key_env
            )
            envelope = plan["resource_envelope"]
            command = [
                sys.executable,
                "-m",
                "scripts.run_researchclawbench_system_arm",
                "--benchmark-root",
                str(root / plan["benchmark"]),
                "--task-id",
                plan["task_id"],
                "--condition",
                plan["condition"],
                "--output",
                str(run),
                "--model",
                config.model,
                "--api-base",
                config.base_url,
                "--api-key-env",
                config.api_key_env,
                "--max-rounds",
                str(envelope["max_rounds"]),
                "--max-runtime-seconds",
                str(envelope["wall_seconds"]),
                "--max-output-tokens",
                str(envelope["max_output_tokens"]),
                "--extra-body-json",
                json.dumps(config.extra_body),
            ]
            env = dict(os.environ)
            if args.capture_decisions:
                command.append("--capture-decisions")
            env["PYTHONPATH"] = os.pathsep.join((str(Path.cwd()), str(root / plan["harness"])))
            env["CUDA_VISIBLE_DEVICES"] = ""
            env["OMP_NUM_THREADS"] = "4"
            with marker.open("x") as stream:
                json.dump({"command": command, "automatic_retry": False}, stream)
            with (output / "execution.log").open("x") as log:
                child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
                with (output / "execution.process.json").open("x") as stream:
                    json.dump({"pid": child.pid, "host": os.uname().nodename}, stream)
                returncode = child.wait()
            with (output / "execution.exit.json").open("x") as stream:
                json.dump({"returncode": returncode}, stream)
            if not receipt.is_file():
                raise ValueError("Execution ended without terminal receipt; inspect execution.log")
        delivered = deliver(project=root, runs=[run], output=delivery)
        terminal = json.loads(receipt.read_text())
        artifacts = {}
        for dirname in ("code", "outputs", "report"):
            for path in sorted((run / dirname).rglob("*")):
                if path.is_file():
                    path.resolve(strict=True).relative_to(run)
                    artifacts[path.relative_to(root).as_posix()] = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
        result = {
            "status": "benchmark-task-delivered",
            "plan_sha256": contract["plan_sha256"],
            "execution_status": terminal["status"],
            "duration_seconds": terminal["duration_seconds"],
            "receipt": receipt.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "delivery": delivery.relative_to(root).as_posix(),
            "delivery_sha256": hashlib.sha256(
                (delivery / "SELECTION.json").read_bytes()
            ).hexdigest(),
            "generated_artifacts": artifacts,
            "generated_metrics_independently_verified": False,
            "whole_project_lifecycle_complete": False,
            "scope": "prepared-task-execution-and-result-delivery",
        }
        if "decision_observations" in terminal:
            captured = terminal["decision_observations"]
            disposition = Path(captured["locator"]).resolve(strict=True)
            disposition.relative_to(root)
            if hashlib.sha256(disposition.read_bytes()).hexdigest() != captured["sha256"]:
                raise ValueError("Decision observation disposition changed")
            result["decision_observations"] = captured
            register_artifact(
                project=root,
                artifact=disposition,
                provider="execution-observer",
                model="source-bound-callback",
                condition="prospective-tool-observations",
                status="observed-not-admitted-as-taste",
            )
        result_path = output / "RESULT.json"
        if result_path.exists():
            if json.loads(result_path.read_text()) != result:
                raise ValueError("Terminal task delivery changed")
        else:
            with result_path.open("x") as stream:
                json.dump(result, stream, indent=2)
        register_artifact(
            project=root,
            artifact=result_path,
            provider=config.provider,
            model=config.model,
            condition="prepared-cpu-api-task",
            status=result["status"],
        )
        if args.report_paper_prefix:
            prefix = args.report_paper_prefix
            paper = root / "papers" / prefix
            if not (paper / "MANIFEST.json").exists():
                imported = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.import_benchmark_report",
                        "--project",
                        str(root),
                        "--task-run",
                        str(output),
                        "--paper-directory",
                        prefix,
                    ],
                    check=False,
                )
                if imported.returncode:
                    raise ValueError("Report import stopped; preserve the execution and build")
            imported_binding = json.loads((paper / "REPORT_IMPORT.json").read_text())
            if (
                imported_binding["task_result_sha256"]
                != hashlib.sha256(result_path.read_bytes()).hexdigest()
            ):
                raise ValueError("Existing paper belongs to another task result")
            base = root / "evaluations"
            paper_cycle = base / (prefix + "-cycle")
            command = [
                sys.executable,
                "-m",
                "scripts.run_candidate_paper_cycle",
                "--project",
                str(root),
                "--source-paper",
                prefix,
                "--revised-paper",
                prefix + "-revised",
                "--review-id",
                prefix + "-review",
                "--review-output",
                str(base / (prefix + "-review")),
                "--revision-output",
                str(base / (prefix + "-revision")),
                "--output",
                str(paper_cycle),
                "--evidence",
                str(result_path),
            ]
            for path in args.paper_evidence:
                command.extend(["--evidence", str(path.resolve())])
            if args.allow_api:
                command.append("--allow-api")
            with (output / "report-cycle.log").open("a") as log:
                continued = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if continued.returncode:
                raise ValueError("Report cycle stopped; recover that stage, not the experiment")
            register_artifact(
                project=root,
                artifact=paper_cycle / "SUMMARY.json",
                provider="project-report-cycle",
                model="stage-bound",
                condition="actual-experiment-report-review-revision",
                status="report-cycle-complete-review-open",
            )
        if args.paper_brief:
            command = [
                sys.executable,
                "-m",
                "scripts.run_measured_paper_lifecycle",
                "--project",
                str(root),
                "--delivery",
                str(delivery),
                "--brief",
                str(args.paper_brief.resolve()),
                "--output",
                str(output.with_name(output.name + "-paper")),
                "--sectioned-draft",
            ]
            if args.allow_api:
                command.append("--allow-api")
            with (output / "paper.log").open("a") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if completed.returncode:
                raise ValueError(
                    "Terminal execution retained; resume the paper lifecycle separately"
                )
        print(json.dumps(delivered))


if __name__ == "__main__":
    main()

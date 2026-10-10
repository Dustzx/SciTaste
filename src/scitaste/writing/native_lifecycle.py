"""Resume Native terminal execution into report, review, revision and PDF delivery."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.project.models import validate_entry_id
from scitaste.project.paper_feedback import load_paper_feedback
from scitaste.project.research_artifact import register_artifact


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "source-run", "delivery"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--paper-prefix", required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--session-exchange", type=Path)
    parser.add_argument("--paper-flow", type=Path, help="Reuse an existing verified paper flow")
    parser.add_argument("--figure-contract-repair", type=Path)
    parser.add_argument(
        "--report-appendix-heading", help="Explicit retained-report appendix boundary"
    )
    for key in ("backend", "review-profile", "credentials", "venue-taste-profile"):
        parser.add_argument("--" + key, type=Path)
    args = parser.parse_args()
    if args.session_exchange and args.allow_api:
        raise ValueError("Session mode cannot enable API calls")
    root = args.project.resolve(strict=True)
    source = args.source_run.resolve(strict=True)
    delivery = args.delivery.resolve()
    for path in (source, delivery):
        path.relative_to(root)
    prefix = args.paper_prefix
    validate_entry_id(prefix, field_name="paper prefix")

    def launch(module, *arguments, api=False):
        command = [sys.executable, "-m", module, "--project", str(root), *map(str, arguments)]
        if api and args.allow_api:
            command.append("--allow-api")
        if module == "scitaste.writing.native_report" and args.credentials:
            command.extend(["--credentials", str(args.credentials.resolve())])
        if module == "scitaste.writing.paper_cycle":
            if args.session_exchange:
                command.extend(["--session-exchange", str(args.session_exchange.resolve())])
            for key in ("backend", "review_profile", "credentials", "venue_taste_profile"):
                value = getattr(args, key)
                if value:
                    command.extend(["--" + key.replace("_", "-"), str(value.resolve())])
        completed = subprocess.run(command, check=False)
        if (
            completed.returncode == 75
            and args.session_exchange
            and module == "scitaste.writing.paper_cycle"
        ):
            # Preserve the child coordinator's explicit model wait, not an
            # ordinary subprocess error. No completed report is regenerated.
            raise SystemExit(75)
        completed.check_returncode()

    result_path = delivery / "RESULT.json"
    if not result_path.exists():
        if delivery.exists():
            raise ValueError("Existing report attempt needs recovery, not automatic regeneration")
        launch(
            "scitaste.writing.native_report",
            "--source-run",
            source,
            "--output",
            delivery,
            api=True,
        )
    result = json.loads(result_path.read_text())
    contract = json.loads((delivery / "CONTRACT.json").read_text())
    if (
        result["status"] != "native-workspace-report-delivered"
        or contract["source_run"] != source.relative_to(root).as_posix()
        or contract["continuation"]["parent_result_sha256"] != digest(source / "RESULT.json")
    ):
        raise ValueError("Report delivery is not bound to this terminal execution")
    receipt = (root / result["receipt"]).resolve(strict=True)
    receipt.relative_to(delivery)
    if digest(receipt) != result["receipt_sha256"]:
        raise ValueError("Report receipt changed")
    for locator, expected in result["generated_artifacts"].items():
        path = (root / locator).resolve(strict=True)
        path.relative_to(delivery)
        if digest(path) != expected:
            raise ValueError("Delivered artifact changed")
    if delivery.name == "delivery":
        # Different lifecycle folders share this basename. Register their
        # immutable retained deliveries under the owning lifecycle, including
        # recovery after report generation succeeded but registration failed.
        receipt_data = json.loads(receipt.read_text())
        register_artifact(
            project=root,
            artifact=result_path,
            provider=receipt_data.get("provider", contract["model_source"]),
            model=receipt_data["model"],
            condition="native-terminal-report",
            status=result["status"],
            run_id=delivery.parent.name + "-report",
        )
    from scitaste.visual.native_handoff import prepare_native_figure

    figure_output = root / "evaluations" / (prefix + "-figure")
    figure = prepare_native_figure(root, source, figure_output, repair=args.figure_contract_repair)
    figure_args = ["--figure-delivery", figure_output / "RESULT.json"] if figure else []
    paper = root / "papers" / prefix
    if not (paper / "MANIFEST.json").exists():
        appendix_args = (
            ["--appendix-heading", args.report_appendix_heading]
            if args.report_appendix_heading
            else []
        )
        launch(
            "scitaste.writing.report_import",
            "--task-run",
            delivery,
            "--paper-directory",
            prefix,
            *figure_args,
            *appendix_args,
        )
    binding = json.loads((paper / "REPORT_IMPORT.json").read_text())
    if binding["task_result_sha256"] != digest(result_path):
        raise ValueError("Existing paper belongs to a different delivery")
    if figure and binding.get("figure_delivery_sha256") != digest(figure_output / "RESULT.json"):
        raise ValueError(
            "Existing paper does not contain this figure delivery; use a new paper version"
        )
    base = root / "evaluations"
    cycle = args.paper_flow.resolve(strict=True) if args.paper_flow else base / (prefix + "-cycle")
    cycle.relative_to(root)
    if (cycle / "SUMMARY.json").exists():
        cycle_contract = json.loads((cycle / "CONTRACT.json").read_text())
        if cycle_contract["source_paper"] != prefix:
            raise ValueError("Existing paper flow belongs to another source paper")
        load_paper_feedback(root, cycle)
    elif args.paper_flow:
        raise ValueError("Explicit retained paper flow is not complete")
    else:
        cycle_contract = cycle / "CONTRACT.json"
        if cycle_contract.is_file():
            # Resume exactly the historical evidence set. New provenance support
            # must not mutate a sealed review or change a pending model request.
            retained = json.loads(cycle_contract.read_text())
            evidence = [root / name for name in retained["evidence"]]
            review_evidence = [root / name for name in retained.get("review_evidence", {})]
        else:
            from scitaste.writing.confirmation_evidence import native_confirmation_evidence

            confirmation = native_confirmation_evidence(
                root, source, cycle / "CONFIRMATION_EVIDENCE.json"
            )
            evidence = [result_path, source / "RESULT.json", *confirmation]
            # Public provenance only: no private pack, labels, other arms or
            # execution commands are sent to the manuscript reviewer.
            review_evidence = list(confirmation)
        evidence_args = [value for path in evidence for value in ("--evidence", path)]
        review_args = [value for path in review_evidence for value in ("--review-evidence", path)]
        launch(
            "scitaste.writing.paper_cycle",
            "--source-paper",
            prefix,
            "--revised-paper",
            prefix + "-revised",
            "--review-id",
            prefix + "-review",
            "--review-output",
            base / (prefix + "-review"),
            "--revision-output",
            base / (prefix + "-revision"),
            "--output",
            cycle,
            *evidence_args,
            *review_args,
            api=True,
        )
    register_artifact(
        project=root,
        artifact=cycle / "SUMMARY.json",
        provider="native-report-lifecycle",
        model="stage-bound",
        condition="native-experiment-report-review-revision",
        status="report-cycle-complete-review-open",
    )
    feedback = load_paper_feedback(root, cycle)
    feedback_path = cycle / "PAPER_FEEDBACK.json"
    if feedback_path.exists():
        if json.loads(feedback_path.read_text()) != feedback:
            raise ValueError("Retained review-to-planning feedback changed")
    else:
        with feedback_path.open("x") as stream:
            json.dump(feedback, stream, indent=2)
    print(
        json.dumps(
            {
                "status": "native-report-cycle-delivered",
                "planning_feedback": str(feedback_path),
                "review_closed": False,
                "whole_project_lifecycle_complete": False,
            }
        )
    )


if __name__ == "__main__":
    main()

"""Run the measured-delivery to revised-paper segment without launching experiments."""

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.project.models import validate_entry_id
from scripts.build_lifecycle_paper_candidate import build
from scripts.prepare_experiment_paper import prepare


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "delivery", "brief", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--sectioned-draft", action="store_true")
    parser.add_argument("--revision-recovery-output", type=Path)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    output = args.output.resolve()
    for path in (args.delivery, args.brief, output, *args.evidence):
        path.resolve().relative_to(project)
    identity = output.name
    validate_entry_id(identity, field_name="lifecycle identity")
    base = project / "evaluations"
    prepared = output / "paper-input"
    draft = base / (identity + "-draft")
    review = base / (identity + "-review")
    revision = base / (identity + "-revision")
    paper_id, revised_id = identity + "-draft", identity + "-revised"
    selection = args.delivery.resolve(strict=True) / "SELECTION.json"
    evidence = [selection, *[p.resolve(strict=True) for p in args.evidence]]
    if len(set(evidence)) != len(evidence):
        raise ValueError("Duplicate lifecycle evidence")
    contract = {
        "scope": "measured-delivery-to-revised-paper",
        "selection_sha256": sha(selection),
        "brief_sha256": sha(args.brief),
        "evidence": {str(p.relative_to(project)): sha(p) for p in evidence},
        "draft_run": draft.name,
        "review_run": review.name,
        "revision_run": revision.name,
        "source_paper": paper_id,
        "revised_paper": revised_id,
        "max_provider_calls": (
            len(json.loads(args.brief.read_text())["required_sections"]) + 3
            if args.sectioned_draft
            else 3
        ),
        "max_combined_api_liability_usd": 8,
        "experiment_execution_authorized": False,
    }
    if args.sectioned_draft:
        contract["draft_format"] = "section-prose-v1"
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract_path = output / "CONTRACT.json"
        if contract_path.exists():
            if json.loads(contract_path.read_text()) != contract:
                raise ValueError("Lifecycle input changed; cannot resume this identity")
        else:
            with contract_path.open("x") as stream:
                json.dump(contract, stream, indent=2)
        original_revision = revision
        cycle_output = output / "paper-cycle"
        if args.revision_recovery_output:
            replacement = args.revision_recovery_output.resolve()
            replacement.relative_to(project)
            if replacement == revision.resolve():
                raise ValueError("Recovery must preserve the original revision directory")
            failed_path = revision / "RESULT.json"
            failed = json.loads(failed_path.read_text())
            if failed.get("status") != "rejected":
                raise ValueError("Explicit revision recovery requires a terminal rejected result")
            recovery = {
                "original_result_sha256": sha(failed_path),
                "replacement": str(replacement.relative_to(project)),
                "additional_max_calls": 1,
                "additional_max_api_liability_usd": 3,
                "original_response_preserved": True,
            }
            recovery_path = output / "REVISION_RECOVERY.json"
            if recovery_path.exists():
                if json.loads(recovery_path.read_text()) != recovery:
                    raise ValueError("Revision recovery binding changed")
            else:
                with recovery_path.open("x") as stream:
                    json.dump(recovery, stream, indent=2)
            revision = replacement
            cycle_output = output / "paper-cycle-recovery"
        elif (output / "REVISION_RECOVERY.json").exists():
            raise ValueError("Resume with the recorded --revision-recovery-output")
        if not prepared.exists():
            prepare(delivery=args.delivery, project=project, brief=args.brief, output=prepared)
        binding = json.loads((prepared / "BINDING.json").read_text())
        if (
            binding["selection_sha256"] != contract["selection_sha256"]
            or binding["brief_sha256"] != contract["brief_sha256"]
            or binding["input_sha256"] != sha(prepared / "INPUT.json")
        ):
            raise ValueError("Prepared paper input no longer matches lifecycle")
        response = draft / "logs/provider_calls/00000.response"
        if args.sectioned_draft:
            from scripts.run_sectioned_paper_draft import draft as sectioned_draft

            sectioned_draft(
                project=project,
                input_directory=prepared,
                output=draft,
                paper_directory=paper_id,
                allow_api=args.allow_api,
            )
        if not args.sectioned_draft and not response.exists():
            marker = output / "draft.started.json"
            if marker.exists() or draft.exists():
                raise ValueError("Existing draft request requires observation/recovery, not retry")
            if not args.allow_api:
                raise ValueError("Draft is missing; --allow-api is required")
            command = [
                sys.executable,
                "-m",
                "scripts.run_experiment_paper_draft",
                "--project",
                str(project),
                "--input-directory",
                str(prepared),
                "--output",
                str(draft),
                "--allow-api",
            ]
            with marker.open("x") as stream:
                json.dump({"command": command, "automatic_retry": False}, stream)
            print("Draft generation started; retaining output in draft.log", flush=True)
            with (output / "draft.log").open("x") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            with (output / "draft.exit.json").open("x") as stream:
                json.dump({"returncode": result.returncode}, stream)
            # A schema-rejected response may still yield a reviewable candidate;
            # the builder preserves that status and never invents missing prose.
            if not response.exists():
                raise ValueError("No retained draft response; inspect archived stage failure")
        if not (draft / "RESULT.json").exists():
            raise ValueError("Draft runtime has not reached a recorded terminal state")
        if not args.sectioned_draft:
            print("Building independent candidate from retained model response", flush=True)
            build(
                project=project,
                input_path=prepared / "INPUT.json",
                response=response,
                output=output / "candidate-build",
                paper_directory=paper_id,
                source_run=draft.name,
            )
        command = [
            sys.executable,
            "-m",
            "scripts.run_candidate_paper_cycle",
            "--project",
            str(project),
            "--source-paper",
            paper_id,
            "--revised-paper",
            revised_id,
            "--review-id",
            review.name,
            "--review-output",
            str(review),
            "--revision-output",
            str(revision),
            "--output",
            str(cycle_output),
        ]
        for path in evidence:
            command.extend(["--evidence", str(path)])
        if args.allow_api:
            command.append("--allow-api")
        print("Continuing registered review, revision and PDF build", flush=True)
        with (output / "cycle.log").open("a") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise ValueError("Paper cycle stopped; inspect cycle.log; no automatic retry")
        cycle = json.loads((cycle_output / "SUMMARY.json").read_text())
        accounting = {
            p.name: provider_ledger_accounting(p / "logs/provider_calls")
            for p in (draft, review, revision)
        }
        if original_revision != revision:
            accounting[original_revision.name] = provider_ledger_accounting(
                original_revision / "logs/provider_calls"
            )
        summary = {
            "status": "measured-paper-segment-complete",
            "scope": contract["scope"],
            "input_selection_sha256": contract["selection_sha256"],
            "paper_cycle": cycle,
            "accounting": accounting,
            "whole_project_lifecycle_complete": False,
            "scientific_quality_established": False,
            "review_closed": False,
        }
        path = output / "SUMMARY.json"
        if path.exists():
            if json.loads(path.read_text()) != summary:
                raise ValueError("Completed lifecycle artifacts changed")
        else:
            with path.open("x") as stream:
                json.dump(summary, stream, indent=2)
        if (args.delivery / "experience/COLLECTION.json").is_file():
            from scripts.finalize_measured_research_cycle import finalize

            disposition = finalize(
                project=project,
                delivery=args.delivery,
                paper_flow=output,
                output=base / (identity + "-experience-disposition"),
            )
            print(json.dumps({"experience_disposition": disposition["status"]}), flush=True)
        print(json.dumps(summary))


if __name__ == "__main__":
    main()

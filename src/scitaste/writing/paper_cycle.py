"""Resume the registered candidate-paper review/revision/build artifact flow."""

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_entry_id
from scitaste.review.venue import (
    load_venue_review_packet,
    load_venue_review_reports,
    prepare_venue_review,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover_bounded_review(project, review_id, destination):
    """Reuse unchanged session advice, not stale execution authority or a new review."""
    receipt = destination / "RESULT.json"
    if not receipt.is_file():
        return False
    recorded = json.loads(receipt.read_text())
    if (
        recorded.get("outcome") != "rejected"
        or recorded.get("result", {}).get("node_name") != "venue-paper-review"
        or recorded.get("result", {}).get("request", {}).get("expected_backend")
        != "assistant-session"
        or recorded.get("blockers")
        not in (
            ["output token budget exceeded"],
            ["project revision changed while the model-node backend was running"],
        )
    ):
        return False
    from scitaste.review.recover_lifecycle import recover

    # Recovery rechecks every bound paper/packet byte and semantic obligation,
    # retains the rejected invocation, and grants no experimental authority.
    recover(project=project, review_id=review_id, output=destination)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-paper", required=True)
    parser.add_argument("--revised-paper", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--revision-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--review-evidence", type=Path, action="append", default=[])
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--session-exchange", type=Path)
    parser.add_argument("--session-wait-seconds", type=float, default=600)
    for key in ("backend", "review-profile", "credentials"):
        parser.add_argument("--" + key, type=Path)
    parser.add_argument("--draft-input", type=Path)
    parser.add_argument("--draft-response", type=Path)
    parser.add_argument("--draft-source-run")
    parser.add_argument(
        "--venue-taste-profile",
        type=Path,
        default=Path("configs/writing/venues/cvpr-2027/taste.yaml"),
    )
    args = parser.parse_args()
    if args.session_exchange and args.allow_api:
        raise ValueError("Session mode cannot enable API calls")
    root = args.project.resolve(strict=True)
    for value in (args.source_paper, args.revised_paper, args.review_id):
        validate_entry_id(value, field_name="cycle identity")
    output = args.output.resolve()
    for path in (
        output,
        args.review_output,
        args.revision_output,
        *args.evidence,
        *args.review_evidence,
    ):
        path.resolve().relative_to(root)
    runtime = ProjectRuntime(root.parent.parent)
    draft_values = (args.draft_input, args.draft_response, args.draft_source_run)
    if any(draft_values) and not all(draft_values):
        raise ValueError("Draft input, response and source run must be supplied together")
    if all(draft_values):
        from scripts.build_lifecycle_paper_candidate import build

        build(
            project=root,
            input_path=args.draft_input,
            response=args.draft_response,
            output=output / "candidate-build",
            paper_directory=args.source_paper,
            source_run=args.draft_source_run,
        )
    source = runtime.open_paper(root.name, args.source_paper)
    label = next(k for k in ("markdown", "source-markdown", "main.md") if k in source.files)
    paper_path = root / "papers" / args.source_paper / source.files[label]
    evidence = {str(p.resolve().relative_to(root)): digest(p) for p in args.evidence}
    contract = {
        "source_paper": args.source_paper,
        "source_sha256": digest(paper_path),
        "revised_paper": args.revised_paper,
        "review_id": args.review_id,
        "review_output": str(args.review_output.resolve().relative_to(root)),
        "revision_output": str(args.revision_output.resolve().relative_to(root)),
        "evidence": evidence,
        "venue_taste_sha256": digest(args.venue_taste_profile),
        "scope": "candidate-paper-review-revision-build",
        "review_closure_authorized": False,
    }
    if args.review_evidence:
        contract["review_evidence"] = {
            str(path.resolve().relative_to(root)): digest(path) for path in args.review_evidence
        }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract_path = output / "CONTRACT.json"
        if contract_path.exists():
            if json.loads(contract_path.read_text()) != contract:
                raise ValueError("Resume contract differs; use a new cycle identity")
        else:
            with contract_path.open("x") as stream:
                json.dump(contract, stream, indent=2)
        executed = []

        def launch(stage, destination, command):
            if stage == "review":
                for path in args.review_evidence:
                    command.extend(["--evidence", str(path)])
            if args.session_exchange:
                command.remove("--allow-api")
                exchange = args.session_exchange.resolve() / stage
                exchange.relative_to(root)
                command.extend(["--session-exchange", str(exchange)])
                command.extend(["--session-wait-seconds", str(args.session_wait_seconds)])
            for key in ("backend", "credentials"):
                value = getattr(args, key)
                if value:
                    command.extend(["--" + key, str(value.resolve())])
            if stage == "review" and args.review_profile:
                command.extend(["--profile", str(args.review_profile.resolve())])
            marker = output / f"{stage}.started.json"
            attempt = stage
            if marker.exists() or destination.exists():
                if args.session_exchange and (destination / "SESSION_PENDING.json").is_file():
                    from scitaste.project.session_recovery import pending_resume_stage

                    attempt = pending_resume_stage(output, destination, command, stage=stage)
                    marker = output / f"{attempt}.started.json"
                elif (
                    args.session_exchange
                    and stage in {"review", "revision"}
                    and not destination.exists()
                    and marker.is_file()
                    and json.loads(marker.read_text())["command"] == command
                    and (output / f"{stage}.exit.json").is_file()
                    and json.loads((output / f"{stage}.exit.json").read_text())["returncode"] == 1
                    and any(
                        message in (output / f"{stage}.log").read_text()
                        for message in (
                            "Evidence file exceeds bounded revision input",
                            "Review evidence exceeds bounded input",
                            "Oversized evidence is not a recognized microscopy confirmation",
                        )
                    )
                    and any(
                        not (output / f"{stage}-input-recovery-{index:02d}.started.json").exists()
                        for index in (1, 2)
                    )
                ):
                    # The original attempt failed before creating any model request.
                    # Reuse this source/review identity, not a second scientific review.
                    attempt = next(
                        f"{stage}-input-recovery-{index:02d}"
                        for index in (1, 2)
                        if not (
                            output / f"{stage}-input-recovery-{index:02d}.started.json"
                        ).exists()
                    )
                    marker = output / f"{attempt}.started.json"
                else:
                    raise ValueError(
                        f"{stage} requires recovery of existing work; no automatic retry"
                    )
            if not args.allow_api and not args.session_exchange:
                raise ValueError(f"{stage} is missing; --allow-api required for execution")
            with marker.open("x") as stream:
                json.dump({"command": command, "automatic_retry": False}, stream)
            with (output / f"{attempt}.log").open("x") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            with (output / f"{attempt}.exit.json").open("x") as stream:
                json.dump({"returncode": result.returncode}, stream)
            if result.returncode:
                if (
                    result.returncode == 75
                    and args.session_exchange
                    and (destination / "SESSION_PENDING.json").is_file()
                ):
                    pending = {
                        "status": "awaiting-session-response",
                        "stage": stage,
                        "pending": str(destination / "SESSION_PENDING.json"),
                        "api_calls": 0,
                    }
                    pointer = output / "WORKFLOW_STATUS_PENDING.json"
                    temporary = pointer.with_suffix(".tmp")
                    temporary.write_text(json.dumps(pending, indent=2))
                    temporary.replace(pointer)
                    print(json.dumps(pending))
                    raise SystemExit(75)
                receipt = destination / "RESULT.json"
                if (
                    stage == "review"
                    and args.session_exchange
                    and recover_bounded_review(root, args.review_id, destination)
                ):
                    executed.append("review-advisory-recovered")
                    return
                if stage == "revision" and receipt.is_file():
                    rejected = json.loads(receipt.read_text())
                    if rejected.get("status") == "rejected" and rejected.get(
                        "rejection_reasons"
                    ) == ["Revision paragraph targets are duplicated or unknown"]:
                        return
                raise ValueError(f"{stage} stopped; retain artifacts and inspect its log")
            executed.append(stage)

        if args.review_id not in runtime.open(root.name).review_locators:
            prepare_venue_review(
                runtime,
                project_id=root.name,
                paper_directory=args.source_paper,
                review_id=args.review_id,
                round_number=1,
                review_scope="development",
                venue_taste_profile=args.venue_taste_profile,
                expected_revision=runtime.open(root.name).revision,
            )
        packet = load_venue_review_packet(runtime, root.name, args.review_id)
        if (
            packet.paper_directory != args.source_paper
            or packet.paper_artifact_sha256[label] != contract["source_sha256"]
        ):
            raise ValueError("Existing review belongs to different paper bytes")
        reports = load_venue_review_reports(runtime, root.name, args.review_id)
        if not reports and (args.review_output / "RESULT.json").is_file():
            from scitaste.review.recover_lifecycle import recover

            recover(project=root, review_id=args.review_id, output=args.review_output)
            reports = load_venue_review_reports(runtime, root.name, args.review_id)
        if not reports:
            launch(
                "review",
                args.review_output,
                [
                    sys.executable,
                    "-m",
                    "scitaste.review.lifecycle_review",
                    "--project",
                    str(root),
                    "--review-id",
                    args.review_id,
                    "--output",
                    str(args.review_output),
                    "--allow-api",
                ],
            )
            reports = load_venue_review_reports(runtime, root.name, args.review_id)
        if not reports:
            raise ValueError("Review command produced no imported report")
        target = root / "papers" / args.revised_paper
        revision_output = args.revision_output
        retry_from = None
        for _ in range(2):
            first_result = args.revision_output / "RESULT.json"
            if first_result.is_file():
                first = json.loads(first_result.read_text())
                if (
                    not target.exists()
                    and first.get("status") == "rejected"
                    and first.get("rejection_reasons") == ["output token budget exceeded"]
                    and first.get("request", {}).get("expected_backend") == "assistant-session"
                ):
                    from scitaste.writing.recover_revision import recover

                    recover(
                        project=root,
                        output=args.revision_output,
                        paper_directory=args.revised_paper,
                    )
                if first.get("status") == "rejected" and first.get("rejection_reasons") == [
                    "Revision paragraph targets are duplicated or unknown"
                ]:
                    retry_from = args.revision_output
                    revision_output = args.revision_output.with_name(
                        args.revision_output.name + "-retry-01"
                    )
            if (target / "MANIFEST.json").exists():
                break
            command = [
                sys.executable,
                "-m",
                "scitaste.writing.lifecycle_revision",
                "--project",
                str(root),
                "--review-id",
                args.review_id,
                "--output",
                str(revision_output),
                "--paper-directory",
                args.revised_paper,
                "--allow-api",
            ]
            for path in args.evidence:
                command.extend(["--evidence", str(path)])
            if retry_from:
                command.extend(["--retry-from", str(retry_from)])
            launch("revision-retry-01" if retry_from else "revision", revision_output, command)
        runtime.open_paper(root.name, args.revised_paper)
        binding = json.loads((revision_output / "CONTRACT.json").read_text())
        trace = json.loads((target / "CANDIDATE_REVISION.json").read_text())
        if (
            binding["paper_sha256"] != contract["source_sha256"]
            or binding["report_sha256"] != {r.report_id: r.report_sha256 for r in reports}
            or {v["locator"]: v["sha256"] for v in binding["evidence"].values()} != evidence
            or trace["review_id"] != args.review_id
            or trace["source_paper"] != args.source_paper
            or trace["revised_sha256"] != digest(target / "main.md")
            or trace["revision_result"]
            != str((revision_output / "RESULT.json").resolve().relative_to(root))
        ):
            raise ValueError("Revised artifact does not match this cycle")
        build = json.loads((target / "build.json").read_text())
        if build["status"] != "succeeded" or not (target / "main.pdf").is_file():
            raise ValueError("Revised PDF is not built")
        summary = {
            "status": "artifact-flow-complete",
            "scope": contract["scope"],
            "source_sha256": contract["source_sha256"],
            "revised_sha256": trace["revised_sha256"],
            "pdf_sha256": digest(target / "main.pdf"),
            "review_closed": False,
            "whole_project_lifecycle_complete": False,
        }
        path = output / "SUMMARY.json"
        if path.exists():
            if json.loads(path.read_text()) != summary:
                raise ValueError("Completed cycle artifacts changed")
        else:
            with path.open("x") as stream:
                json.dump(summary, stream, indent=2)
        print(json.dumps({**summary, "executed_stages_this_invocation": executed}))


if __name__ == "__main__":
    main()

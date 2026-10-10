"""Deliver measured selection and frozen source, never the mutable last candidate."""

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.project.models import content_sha256


def resolve_unlearning_baseline(contract, baseline_run: Path, source: Path):
    """Resolve an explicit baseline receipt, not an unmeasured local source tree."""
    from scitaste.executor.unlearning_result import collect_unlearning_result

    root = baseline_run.resolve(strict=True)
    source = source.resolve(strict=True)
    saved = ExecutionResult.model_validate_json((root / "EXECUTION_RESULT.json").read_text())
    measured = collect_unlearning_result(
        root / "collected",
        action_id=saved.action_id,
        contract_sha256=saved.data["contract_sha256"],
    )
    baseline = json.loads((root / "collected/CONTRACT.json").read_text())
    if (
        measured.status != ExecutionStatus.SUCCEEDED
        or measured.data["primary_value"] != contract["task"]["baseline_score"]
        or contract["task"]["task_id"]
        not in {
            "mlrc-machine-unlearning-development",
            "mlrc-machine-unlearning-iterative-development",
        }
        or contract["task"]["source_group_id"] != "mlrc-machine-unlearning"
        or baseline["objective_direction"] != contract["task"]["objective_direction"]
        or baseline["candidate_sha256"].get("methods/MyMethod.py")
        != contract.get("baseline_identity_sha256")
    ):
        raise ValueError("Baseline measurement does not match the declared task/source")
    files = {}
    for name, digest in baseline["candidate_sha256"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("Invalid baseline source path")
        path = source / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError("Baseline source escapes root")
        if path.stat().st_size > 128_000:
            raise ValueError("Baseline source exceeds candidate bound")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Baseline source differs from measured source")
        files[name] = raw
    return files, {
        "source_run": str(root),
        "contract": baseline,
        "measured_result": measured.model_dump(mode="json"),
    }


def export_result(run: Path, output: Path, *, baseline_run=None, baseline_source=None):
    run = run.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(run) or run.is_relative_to(output):
        raise ValueError("Delivery must be separate from the immutable source run")
    contract = json.loads((run / "CONTRACT.json").read_text())
    terminal = json.loads((run / "RESULT.json").read_text())
    task = contract["task"]
    direction = task["objective_direction"]
    if direction not in {"maximize", "minimize"}:
        raise ValueError("Unknown objective direction")
    best_score = task.get("baseline_score")
    if best_score is not None and (
        type(best_score) not in (float, int) or not math.isfinite(best_score)
    ):
        raise ValueError("Invalid baseline score")
    best = None
    rows = []
    payloads = {}
    for index, attempt in enumerate(sorted((run / "tools/experiments").glob("attempt-*")), 1):
        if attempt.is_symlink() or attempt.name != f"attempt-{index:03d}":
            raise ValueError("Invalid attempt ledger")
        reservation = json.loads((attempt / "RESERVATION.json").read_text())
        result = ExecutionResult.model_validate_json((attempt / "RESULT.json").read_text())
        if result.status == ExecutionStatus.PLANNED:
            raise ValueError("Unresolved attempts cannot be delivered as completed")
        digests = reservation["source_sha256"]
        if content_sha256(digests) != reservation["candidate_identity"]:
            raise ValueError("Candidate identity mismatch")
        files = {}
        for name, digest in digests.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                raise ValueError("Invalid snapshot-relative path")
            path = attempt / "candidate" / name
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(attempt.resolve()):
                raise ValueError("Source escapes snapshot")
            if path.stat().st_size > 128_000:
                raise ValueError("Source exceeds candidate bound")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Frozen source changed")
            files[name] = raw
        payloads[attempt.name] = files
        value = result.data.get("primary_value")
        if result.status == ExecutionStatus.SUCCEEDED:
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("Successful attempt lacks finite measured objective")
            if best_score is None or (
                value > best_score if direction == "maximize" else value < best_score
            ):
                best, best_score = attempt.name, value
        rows.append(
            {
                "attempt": attempt.name,
                "candidate_identity": reservation["candidate_identity"],
                "source_sha256": digests,
                "result": result.model_dump(mode="json"),
                "reservation": reservation,
            }
        )
    if not rows:
        raise ValueError("No completed attempts to deliver")
    summary = json.loads((run / "ITERATIVE_SUMMARY.json").read_text())
    selected = best or "original-baseline"
    if (summary["best_observed_identity"], summary["best_observed_value"]) != (
        selected,
        best_score,
    ):
        raise ValueError("Run summary disagrees with measured selection")
    if (baseline_run is None) != (baseline_source is None):
        raise ValueError("Baseline source and measured run must be supplied together")
    selected_files = payloads[best] if best is not None else {}
    baseline_evidence = None
    if best is None and baseline_run is not None:
        selected_files, baseline_evidence = resolve_unlearning_baseline(
            contract,
            baseline_run,
            baseline_source,
        )
    manifest = {
        "schema_version": "1.0",
        "source_run": str(run),
        "source_contract_sha256": hashlib.sha256((run / "CONTRACT.json").read_bytes()).hexdigest(),
        "terminal_status": terminal["status"],
        "objective_direction": direction,
        "selected_identity": selected,
        "selected_score": best_score,
        "baseline_score": task.get("baseline_score"),
        "attempts": rows,
        "selection_scope": (
            "best observed development objective, baseline included; ties retain incumbent"
        ),
        "candidate_exported": bool(selected_files),
        "baseline_source_identity": contract.get("baseline_identity_sha256"),
        "baseline_source_requires_resolution": best is None and not selected_files,
        "baseline_evidence": baseline_evidence,
        "exported_source_sha256": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in selected_files.items()
        },
        "formal_evidence_eligible": False,
        "mechanism_verified": False,
        "taste_gain_established": False,
        "source_run_modified": False,
        "review_record_discovery": (
            "Review records are separate; this export is not semantic approval."
        ),
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in selected_files.items():
        path = output / "candidate" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    for name, data in {
        "SELECTION.json": manifest,
        "SOURCE_CONTRACT.json": contract,
        "SOURCE_SUMMARY.json": summary,
    }.items():
        with (output / name).open("x") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
    final = run / "tools/AGENT_FINAL.json"
    if final.is_file():
        with (output / "UNVERIFIED_AGENT_CLAIM.json").open("xb") as stream:
            stream.write(final.read_bytes())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--baseline-run", type=Path)
    parser.add_argument("--baseline-source", type=Path)
    args = parser.parse_args()
    result = export_result(
        args.run, args.output, baseline_run=args.baseline_run, baseline_source=args.baseline_source
    )
    if args.project is not None:
        from scripts.register_research_artifact import register_artifact

        register_artifact(
            project=args.project,
            artifact=args.output / "SELECTION.json",
            provider="deterministic",
            model="measured-result-selection",
            condition="frozen-candidate-delivery",
            status="exported-development-only",
        )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "selected_identity",
                    "selected_score",
                    "candidate_exported",
                    "mechanism_verified",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

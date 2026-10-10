"""Explicit delivery-marker recovery; never edit an already frozen scientific source."""

import argparse
import json
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scripts.serve_pde_confirmation import confirm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    campaign = args.campaign.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    contract = json.loads(campaign.read_text())
    assignment_path = campaign.parent / "ASSIGNMENTS.json"
    assignment = json.loads(assignment_path.read_text())["scitaste-native"]
    run = (project / assignment["run"]).resolve(strict=True)
    run.relative_to(project)
    launch_path = run / "CONTRACT.json"
    launch = json.loads(launch_path.read_text())
    if verified_asset(project, launch["plan"]["campaign"]) != campaign:
        raise ValueError("Native source belongs to another campaign")
    remaining = launch_path.stat().st_mtime + contract["resource_envelope"]["wall_seconds"]
    remaining -= time.time()
    if remaining <= 0:
        raise ValueError("Original whole-lifecycle deadline expired")
    workspace = run / "workspace"
    marker = workspace / "READY"
    source = workspace / "submission"
    if marker.is_symlink() or not marker.is_file() or (source / "READY").exists():
        raise ValueError("Only the observed mislocated initial READY marker is recoverable")
    source.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    files = list(source.rglob("*"))
    if any(p.is_symlink() for p in files):
        raise ValueError("Frozen delivery cannot contain symlinks")
    hashes = {p.relative_to(source).as_posix(): digest(p) for p in files if p.is_file()}
    if "SUBMISSION.json" not in hashes or any(
        p.stat().st_mtime_ns > marker.stat().st_mtime_ns for p in files if p.is_file()
    ):
        raise ValueError("Source is missing or was modified after the original READY")
    submission = json.loads((source / "SUBMISSION.json").read_text())
    if submission.get("primary_method") not in submission["methods"]:
        raise ValueError("Public-selected primary is missing")
    output = campaign.parent / "marker-handoff/scitaste-native"
    output.mkdir(parents=True, exist_ok=False)
    evidence = {
        "campaign_sha256": digest(campaign),
        "original_assignments_sha256": digest(assignment_path),
        "native_contract_sha256": digest(launch_path),
        "original_ready_sha256": digest(marker),
        "original_ready_mtime_ns": marker.stat().st_mtime_ns,
        "scientific_source_sha256": hashes,
        "primary_method": submission["primary_method"],
        "remaining_original_wall_seconds": remaining,
        "adapter_source_sha256": digest(Path(__file__)),
        "reason": "Shared brief does not name READY directory; root marker is retained",
        "scientific_source_edited": False,
        "primary_reselected": False,
        "new_freeze_marker_written": False,
        "original_marker_retained": True,
        "execution_budget_reset": False,
        "formal_evidence_eligible": False,
    }
    retain_json(output / "CONTRACT.json", evidence)
    status = confirm(
        project,
        campaign,
        "scitaste-native",
        workspace,
        run,
        assignment,
        submission=source,
        delivery={
            "policy": "explicit-root-ready-handoff.v1",
            "adapter_contract": (output / "CONTRACT.json").relative_to(project).as_posix(),
            "adapter_contract_sha256": digest(output / "CONTRACT.json"),
            "scientific_source_reconstructed_or_repaired": False,
        },
    )
    unchanged = hashes == {
        p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*") if p.is_file()
    }
    retain_json(output / "RESULT.json", {"status": status, "source_unchanged": unchanged})
    if not unchanged:
        raise ValueError("Scientific source changed during confirmation")
    print(json.dumps({"status": status, "source_unchanged": unchanged}))


if __name__ == "__main__":
    main()

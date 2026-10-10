"""Execute scientific source freezes unchanged for actual research systems."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scitaste.benchmark import (
    graph_task_data,
    hpatches_task_data,
    microscopy_task_data,
    molecular_task_data,
    qm9_task_data,
    user_shift_task_data,
    weightspace_task_data,
)
from scitaste.benchmark.confirmation_binding import confirmation_directory
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.executor.workspace_sandbox import command
from scitaste.model_nodes.session_exchange import retain_json


def confirm(project, campaign, arm, workspace, run, assignment):
    contract = json.loads(campaign.read_text())
    pack = verified_asset(project, contract["pack"]).parent
    if contract["task_id"] == graph_task_data.TASK_ID:
        endpoint = graph_task_data
        target_names = ["tolokers.npz"]
    elif contract["task_id"] == molecular_task_data.TASK_ID:
        endpoint = molecular_task_data
        target_names = ["aspirin-train.npz", "aspirin-calibration.npz", "aspirin-query.npz"]
    elif contract["task_id"] == microscopy_task_data.TASK_ID:
        endpoint = microscopy_task_data
        target_names = []
    elif contract["task_id"] == weightspace_task_data.TASK_ID:
        endpoint = weightspace_task_data
        target_names = endpoint.target_assets(pack)
    elif contract["task_id"] == qm9_task_data.TASK_ID:
        endpoint = qm9_task_data
        target_names = endpoint.target_assets(pack)
    elif contract["task_id"] == hpatches_task_data.TASK_ID:
        endpoint = hpatches_task_data
        target_names = endpoint.target_assets(pack)
    elif contract["task_id"] == user_shift_task_data.TASK_ID:
        endpoint = user_shift_task_data
        target_names = [
            *endpoint.target_assets(
                pack, public_metadata=tuple(contract.get("confirmation_public_metadata", {}))
            ),
            "train.jsonl",
            "id_val.jsonl",
            "ood_val.jsonl",
        ]
    else:
        raise ValueError("No confirmed execution route for the staged task")
    owned = confirmation_directory(project, campaign, arm, assignment)
    owned.mkdir(parents=True, exist_ok=False)
    feedback = {"arm": arm, "status": "failed", "formal_evidence_eligible": False}
    started = time.monotonic()
    try:
        repository = Path(__file__).resolve().parents[1]
        for name, binding in contract.get("confirmation_runtime_sources", {}).items():
            retained = verified_asset(project, binding)
            actual = (repository / name).resolve(strict=True)
            actual.relative_to(repository)
            if digest(actual) != digest(retained):
                raise ValueError("Confirmation runtime changed after prospective campaign freeze")
        # Private service directory is not mounted by either research framework.
        release = owned / "release"
        endpoint.export_stage(pack, release, submission=workspace / "submission")
        for name, binding in contract.get("confirmation_public_metadata", {}).items():
            if (
                endpoint is not user_shift_task_data
                or name != "PROTOCOL.json"
                or binding != contract["researcher_assets"].get(name)
                or digest(verified_asset(project, binding)) != digest(release / name)
            ):
                raise ValueError("Confirmation metadata must match the released public protocol")
        submission = json.loads((release / "frozen_submission/SUBMISSION.json").read_text())
        # Only declared target assets: query labels and the author pack stay private.
        execution = owned / "execution"
        output = execution / "predictions"
        microscopy = endpoint is microscopy_task_data
        if microscopy:
            # The trusted evaluator runs the already existing per-budget isolator;
            # no research process is ever mounted alongside the author pack.
            argv = [
                sys.executable,
                "-m",
                "scripts.scitastebench_microscopy_task",
                "confirm",
                "--pack",
                str(pack),
                "--release",
                str(release / "RELEASE.json"),
                "--output",
                str(execution),
            ]
        else:
            target = owned / "target"
            target.mkdir()
            import shutil

            for name in target_names:
                shutil.copy2(release / name, target / name)
            execution.mkdir()
            readonly = {release / "frozen_submission": "/submission", target: "/target"}
            argv = command(
                execution,
                [
                    sys.executable,
                    f"/submission/{submission['entrypoint']}",
                    "--data",
                    "/target",
                    "--output",
                    str(output),
                ],
                network=False,
                readonly=readonly,
            )
        origin = run / ("EXECUTION_CONTRACT.json" if arm == "autoresearchclaw" else "CONTRACT.json")
        inherited_seconds = (
            (json.loads(origin.read_text()).get("continuation") or {}).get(
                "inherited_duration_seconds", 0
            )
            if arm == "scitaste-native"
            else 0
        )
        remaining = max(
            0,
            origin.stat().st_mtime
            + contract["resource_envelope"]["wall_seconds"]
            - inherited_seconds
            - time.time(),
        )
        limit = min(contract["confirmation_execution_seconds"], remaining)
        if limit < 1:
            raise ValueError("No lifecycle time remains for confirmation")
        retain_json(
            owned / "EXECUTION_CONTRACT.json",
            {
                "campaign_sha256": digest(campaign),
                "source_run": run.relative_to(project).as_posix(),
                "source_contract_sha256": digest(origin),
                "release_sha256": digest(release / "RELEASE.json"),
                "command": argv,
                "timeout_seconds": limit,
                "network_enabled": False,
                "gpu_enabled": False,
                "frozen_source_readonly": True,
                "no_manual_program_repair": True,
                "budget_process_isolation": microscopy,
            },
        )
        with (owned / "execution.log").open("x") as log:
            inference_started = time.monotonic()
            process = subprocess.Popen(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError("Frozen confirmation exceeded its remaining budget") from None
        if code != 0:
            raise RuntimeError(f"Frozen program exit {code}; no evaluator repair")
        output_hashes = {}
        for path in sorted(output.rglob("*")):
            if path.is_symlink():
                raise ValueError("Confirmation outputs must be regular files")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("Confirmation outputs must be regular files")
            output_hashes[path.relative_to(output).as_posix()] = digest(path)
        inference_receipt = {
            "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
            "release_sha256": digest(release / "RELEASE.json"),
            "return_code": code,
            "elapsed_seconds": time.monotonic() - inference_started,
            "output_sha256": output_hashes,
            "before_private_scoring": True,
            "scientific_approval": False,
        }
        if microscopy:
            # The child scored once only after every predeclared budget finished.
            # Its aggregate receipt predates all private-reference access.
            joint = json.loads((execution / "INFERENCE_RESULT.json").read_text())
            if (
                joint["return_code"] != 0
                or not joint["before_private_scoring"]
                or not joint["budget_isolation_verified"]
                or joint["release_sha256"] != digest(release / "RELEASE.json")
                or joint["output_sha256"] != output_hashes
            ):
                raise ValueError("Microscopy joint inference is not bound to the frozen release")
            inference_receipt.update(
                before_private_scoring=False,
                pre_score_inference_sha256=digest(execution / "INFERENCE_RESULT.json"),
                budget_isolation_verified=True,
                scope="Copied post-score service receipt; linked joint inference predates scoring",
            )
            result = release / "confirmation/RESULT.json"
        else:
            retain_json(owned / "INFERENCE_RESULT.json", inference_receipt)
            result = endpoint.confirm_submission(pack, release / "RELEASE.json", output)
        if microscopy:
            retain_json(owned / "INFERENCE_RESULT.json", inference_receipt)
        feedback.update(
            status="completed", result=json.loads(result.read_text()), executed_frozen_source=True
        )
        # Make the provenance distinction explicit without altering underlying scores.
        feedback["execution_contract_sha256"] = digest(owned / "EXECUTION_CONTRACT.json")
        feedback["inference_result_sha256"] = digest(owned / "INFERENCE_RESULT.json")
    except Exception as exc:
        feedback.update(error_type=type(exc).__name__, error=str(exc), executed_frozen_source=False)
    feedback["elapsed_seconds"] = time.monotonic() - started
    retain_json(owned / "RESULT.json", feedback)
    retain_json(workspace / "confirmation_feedback.json", feedback)
    return feedback["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project, campaign = args.project.resolve(strict=True), args.campaign.resolve(strict=True)
    contract = json.loads(campaign.read_text())
    assignment_path = (args.assignments or campaign.parent / "ASSIGNMENTS.json").resolve(
        strict=True
    )
    assignment_path.relative_to(campaign.parent)
    assignments = json.loads(assignment_path.read_text())
    output = (args.output or campaign.parent / "CONFIRMATION_SERVICE.json").resolve()
    output.relative_to(campaign.parent)
    jobs, done = {}, {}
    deadline = time.monotonic() + contract["resource_envelope"]["wall_seconds"] + 180
    # Each frozen arm has its own two-thread execution allocation. Do not add
    # an unexplained shared queue delay when a prospective third arm is enabled.
    with ThreadPoolExecutor(max_workers=min(3, len(assignments))) as pool:
        while time.monotonic() < deadline and len(done) < len(assignments):
            for arm, assignment in assignments.items():
                if arm in done:
                    continue
                if arm in jobs:
                    if jobs[arm].done():
                        done[arm] = jobs[arm].result()
                    continue
                run = project / assignment["run"]
                workspace = run / ("work" if arm == "autoresearchclaw" else "workspace")
                if (workspace / "submission/READY").is_file():
                    jobs[arm] = pool.submit(
                        confirm, project, campaign, arm, workspace, run, assignment
                    )
                elif (
                    run / ("SESSION_CLOSED.json" if arm == "autoresearchclaw" else "RESULT.json")
                ).is_file():
                    done[arm] = "no-frozen-submission"
            if len(done) < len(assignments):
                time.sleep(5)
    retain_json(
        output,
        {"outcomes": done, "remaining": sorted(set(assignments) - set(done))},
    )
    print(json.dumps(done))


if __name__ == "__main__":
    main()

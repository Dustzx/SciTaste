"""One-time condition-held-out perturbation execution; older routes stay frozen."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scitaste.benchmark import perturbation_task_data as endpoint
from scitaste.benchmark.confirmation_binding import confirmation_directory
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.executor.workspace_sandbox import command
from scitaste.model_nodes.session_exchange import retain_json
from scripts.serve_pde_confirmation import submission_source


def confirm(project, campaign, arm, workspace, run, assignment, submission, delivery):
    contract = json.loads(campaign.read_text())
    if contract["task_id"] != endpoint.TASK_ID:
        raise ValueError("This runner only serves the frozen perturbation task")
    pack = verified_asset(project, contract["pack"]).parent
    owned = confirmation_directory(project, campaign, arm, assignment)
    # Exclusive creation prevents a second source execution or private query.
    owned.mkdir(parents=True, exist_ok=False)
    feedback = {"arm": arm, "status": "failed", "formal_evidence_eligible": False}
    started = time.monotonic()
    inference_finished = False
    try:
        repository = Path(__file__).resolve().parents[1]
        for name, binding in contract["confirmation_runtime_sources"].items():
            retained = verified_asset(project, binding)
            source = (repository / name).resolve(strict=True)
            source.relative_to(repository)
            if digest(source) != digest(retained):
                raise ValueError("Confirmation runtime changed after campaign freeze")
        release = owned / "release"
        endpoint.export_stage(pack, release, submission=submission)
        recipe = json.loads((release / "frozen_submission/SUBMISSION.json").read_text())
        target = owned / "target"
        target.mkdir()
        for name in endpoint.target_assets(pack):
            shutil.copy2(release / name, target / name)
        execution = owned / "execution"
        execution.mkdir()
        predictions = execution / "predictions"
        argv = command(
            execution,
            [
                sys.executable,
                f"/submission/{recipe['entrypoint']}",
                "--data",
                "/target",
                "--output",
                str(predictions),
            ],
            network=False,
            readonly={release / "frozen_submission": "/submission", target: "/target"},
        )
        origin = run / ("EXECUTION_CONTRACT.json" if arm == "autoresearchclaw" else "CONTRACT.json")
        launch = json.loads(origin.read_text())
        inherited = (launch.get("continuation") or {}).get("inherited_duration_seconds", 0)
        remaining = origin.stat().st_mtime + contract["resource_envelope"]["wall_seconds"]
        limit = min(contract["confirmation_execution_seconds"], remaining - inherited - time.time())
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
                "native_delivery_adapter": delivery,
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
                raise TimeoutError("Frozen confirmation exceeded remaining lifecycle") from None
        if code != 0:
            raise RuntimeError(f"Frozen program exit {code}; no evaluator source repair")
        hashes = {}
        for path in sorted(predictions.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Outputs must remain owned regular files")
            if path.is_file():
                hashes[path.relative_to(predictions).as_posix()] = digest(path)
        retain_json(
            owned / "INFERENCE_RESULT.json",
            {
                "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
                "release_sha256": digest(release / "RELEASE.json"),
                "return_code": code,
                "elapsed_seconds": time.monotonic() - inference_started,
                "output_sha256": hashes,
                "before_private_scoring": True,
                "scientific_approval": False,
            },
        )
        inference_finished = True
        result = endpoint.confirm_submission(pack, release / "RELEASE.json", predictions)
        feedback.update(
            status="completed",
            result=json.loads(result.read_text()),
            execution_contract_sha256=digest(owned / "EXECUTION_CONTRACT.json"),
            inference_result_sha256=digest(owned / "INFERENCE_RESULT.json"),
        )
    except Exception as exc:
        feedback.update(error_type=type(exc).__name__, error=str(exc))
    # Successful inference and successful scoring are separate observable facts.
    feedback["executed_frozen_source"] = inference_finished
    feedback["elapsed_seconds"] = time.monotonic() - started
    retain_json(owned / "RESULT.json", feedback)
    retain_json(workspace / "confirmation_feedback.json", feedback)
    return feedback["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "campaign"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project, campaign = args.project.resolve(strict=True), args.campaign.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    contract = json.loads(campaign.read_text())
    if contract["task_id"] != endpoint.TASK_ID:
        raise ValueError("Not a perturbation campaign")
    assignment_path = (args.assignments or campaign.parent / "ASSIGNMENTS.json").resolve(
        strict=True
    )
    assignment_path.relative_to(campaign.parent)
    assignments = json.loads(assignment_path.read_text())
    if not assignments or set(assignments) - {"scitaste-native", "autoresearchclaw", "mlr-agent"}:
        raise ValueError("Only genuine declared framework assignments are supported")
    output = (args.output or campaign.parent / "CONFIRMATION_SERVICE.json").resolve()
    output.relative_to(campaign.parent)
    deadline = time.monotonic() + contract["resource_envelope"]["wall_seconds"] + 180
    jobs, done = {}, {}
    with ThreadPoolExecutor(max_workers=min(3, len(assignments))) as pool:
        while time.monotonic() < deadline and len(done) < len(assignments):
            for arm, assignment in assignments.items():
                if arm in done:
                    continue
                if arm in jobs:
                    if jobs[arm].done():
                        done[arm] = jobs[arm].result()
                    continue
                run = (project / assignment["run"]).resolve()
                run.relative_to(project)
                workspace = run / ("work" if arm == "autoresearchclaw" else "workspace")
                source, delivery = submission_source(workspace, arm, contract)
                if source is not None:
                    jobs[arm] = pool.submit(
                        confirm,
                        project,
                        campaign,
                        arm,
                        workspace,
                        run,
                        assignment,
                        source,
                        delivery,
                    )
                elif (
                    run / ("SESSION_CLOSED.json" if arm == "autoresearchclaw" else "RESULT.json")
                ).is_file():
                    done[arm] = "no-frozen-submission"
            if len(done) < len(assignments):
                # Supervisor readiness checks do not fetch remote/model resources.
                time.sleep(5)
    retain_json(output, {"outcomes": done, "remaining": sorted(set(assignments) - set(done))})
    print(json.dumps(done))


if __name__ == "__main__":
    main()

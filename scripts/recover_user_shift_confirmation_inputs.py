"""Execute unchanged frozen source with the previously released public protocol.

This is a separately budgeted engineering confirmation, not a replacement for
either original assignment, a scientific source repair or a new formal score.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from scitaste.benchmark import user_shift_task_data
from scitaste.benchmark.confirmation_binding import confirmation_directory
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.executor.workspace_sandbox import command
from scitaste.model_nodes.session_exchange import retain_json


def recover(project, campaign, arm, output, *, seconds):
    root = project.resolve(strict=True)
    campaign = campaign.resolve(strict=True)
    campaign.relative_to(root / "evaluations")
    contract = json.loads(campaign.read_text())
    if contract["task_id"] != user_shift_task_data.TASK_ID or arm not in {
        "autoresearchclaw",
        "mlr-agent",
    }:
        raise ValueError("Only the retained external reviewer-shift metadata failures are eligible")
    if type(seconds) is not int or not 1 <= seconds <= 1800:
        raise ValueError("Explicit confirmation-only budget of at most 1800 seconds required")
    assignment_path = campaign.parent / "ASSIGNMENTS.json"
    assignment = json.loads(assignment_path.read_text())[arm]
    original = confirmation_directory(root, campaign, arm, assignment)
    failed = json.loads((original / "RESULT.json").read_text())
    log_path = original / "execution.log"
    log = log_path.read_text()
    if (
        failed["status"] != "failed"
        or failed.get("executed_frozen_source")
        or failed.get("error") != "Frozen program exit 1; no evaluator repair"
        or "FileNotFoundError" not in log
        or "'/target/PROTOCOL.json'" not in log
    ):
        raise ValueError("Recovery requires the exact retained public-protocol failure")
    old_execution = json.loads((original / "EXECUTION_CONTRACT.json").read_text())
    old_release = original / "release/RELEASE.json"
    release_data = json.loads(old_release.read_text())
    run = (root / assignment["run"]).resolve(strict=True)
    origin = run / ("EXECUTION_CONTRACT.json" if arm == "autoresearchclaw" else "CONTRACT.json")
    if (
        old_execution["campaign_sha256"] != digest(campaign)
        or old_execution["source_run"] != assignment["run"]
        or old_execution["source_contract_sha256"] != digest(origin)
        or old_execution["release_sha256"] != digest(old_release)
    ):
        raise ValueError("Original failed execution binding changed")
    protocol = verified_asset(root, contract["researcher_assets"]["PROTOCOL.json"])
    if digest(protocol) != release_data["assets"]["PROTOCOL.json"]:
        raise ValueError("Only the identical already released public protocol can be added")
    output = output.resolve()
    output.relative_to(campaign.parent / "input-recoveries")
    output.mkdir(parents=True, exist_ok=False)
    release = output / "release"
    release.mkdir()
    for name, expected in release_data["assets"].items():
        source = original / "release" / name
        source.resolve(strict=True).relative_to(original / "release")
        if Path(name).name != name or source.is_symlink() or digest(source) != expected:
            raise ValueError("Original public release changed")
        shutil.copy2(source, release / name)
    frozen = release / "frozen_submission"
    frozen.mkdir()
    for name, expected in release_data["frozen_source"].items():
        source = original / "release/frozen_submission" / name
        source.resolve(strict=True).relative_to(original / "release/frozen_submission")
        if source.is_symlink() or digest(source) != expected:
            raise ValueError("Original frozen scientific source changed")
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(old_release, release / "RELEASE.json")
    target = output / "target"
    target.mkdir()
    names = [
        "train.jsonl",
        "id_val.jsonl",
        "ood_val.jsonl",
        "query.jsonl",
        "QUERY.json",
        "PROTOCOL.json",
    ]
    for name in names:
        if name != "PROTOCOL.json" and digest(original / "target" / name) != digest(release / name):
            raise ValueError(
                "Original target input changed; metadata-only recovery is not applicable"
            )
        shutil.copy2(release / name, target / name)
    execution = output / "execution"
    execution.mkdir()
    predictions = execution / "predictions"
    submission = json.loads((frozen / "SUBMISSION.json").read_text())
    argv = command(
        execution,
        [
            sys.executable,
            f"/submission/{submission['entrypoint']}",
            "--data",
            "/target",
            "--output",
            str(predictions),
        ],
        network=False,
        readonly={frozen: "/submission", target: "/target"},
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "schema_version": "1.0",
            "arm": arm,
            "source_run": assignment["run"],
            "campaign_sha256": digest(campaign),
            "assignments_sha256": digest(assignment_path),
            "original_failure_sha256": digest(original / "RESULT.json"),
            "original_failure_log_sha256": digest(log_path),
            "original_execution_sha256": digest(original / "EXECUTION_CONTRACT.json"),
            "release_sha256": digest(release / "RELEASE.json"),
            "frozen_source_sha256": release_data["frozen_source"],
            "target_input_sha256": {name: digest(target / name) for name in names},
            "input_change": (
                "Identical discovery PROTOCOL.json added to target; "
                "all five original inputs unchanged"
            ),
            "timeout_seconds": seconds,
            "command": argv,
            "gpu_enabled": False,
            "network_enabled": False,
            "new_model_calls": 0,
            "scientific_source_changed": False,
            "original_assignment_replaced": False,
            "budget_scope": (
                "Separate confirmation-only engineering recovery, outside original lifecycle timing"
            ),
            "formal_evidence_eligible": False,
        },
    )
    started = time.monotonic()
    feedback = {
        "arm": arm,
        "status": "failed",
        "executed_frozen_source": False,
        "engineering_recovery": True,
        "formal_evidence_eligible": False,
        "original_assignment_replaced": False,
        "contract_sha256": digest(output / "CONTRACT.json"),
    }
    try:
        with (output / "execution.log").open("x") as log_file:
            process = subprocess.Popen(
                argv,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError(
                    "Frozen recovery exceeded its explicit confirmation budget"
                ) from None
        if code != 0:
            raise RuntimeError(f"Unchanged frozen program exit {code}; no source repair")
        hashes = {}
        for path in sorted(predictions.rglob("*")):
            if path.is_symlink():
                raise ValueError("Recovery predictions cannot be symlinks")
            if path.is_file():
                hashes[path.relative_to(predictions).as_posix()] = digest(path)
            elif not path.is_dir():
                raise ValueError("Recovery predictions must be regular files")
        retain_json(
            output / "INFERENCE_RESULT.json",
            {
                "return_code": code,
                "before_private_scoring": True,
                "contract_sha256": digest(output / "CONTRACT.json"),
                "release_sha256": digest(release / "RELEASE.json"),
                "output_sha256": hashes,
                "elapsed_seconds": time.monotonic() - started,
                "scientific_approval": False,
            },
        )
        result = user_shift_task_data.confirm_submission(
            verified_asset(root, contract["pack"]).parent, release / "RELEASE.json", predictions
        )
        feedback.update(
            status="completed",
            executed_frozen_source=True,
            result=json.loads(result.read_text()),
            inference_result_sha256=digest(output / "INFERENCE_RESULT.json"),
        )
    except Exception as exc:
        feedback.update(error_type=type(exc).__name__, error=str(exc))
    feedback["elapsed_seconds"] = time.monotonic() - started
    if (
        digest(original / "RESULT.json")
        != json.loads((output / "CONTRACT.json").read_text())["original_failure_sha256"]
    ):
        raise ValueError("Original failure changed during recovery")
    retain_json(output / "RESULT.json", feedback)
    return feedback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--arm", choices=("autoresearchclaw", "mlr-agent"), required=True)
    parser.add_argument("--seconds", type=int, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            recover(args.project, args.campaign, args.arm, args.output, seconds=args.seconds)
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Wait for an unused remote GPU, then run the two frozen development arms.

The queue has a finite waiting allowance and executes each arm at most once.
Only the standalone, content-bound execution bundle is imported on the host.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def free_devices() -> list[int]:
    devices = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    occupied = {line.strip() for line in processes.stdout.splitlines() if line.strip()}
    available = []
    for line in devices.stdout.splitlines():
        index, uuid, memory, utilization = [part.strip() for part in line.split(",")]
        if uuid not in occupied and int(memory) < 1024 and int(utilization) < 10:
            available.append(int(index))
    return available


def write_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_pair(
    bundle: Path,
    data: Path,
    output: Path,
    wait_seconds: int,
    wall_seconds: int,
    decision_records: tuple[Path, ...] = (),
) -> None:
    if wait_seconds < 0 or wall_seconds < 60:
        raise ValueError("invalid queue or branch time budget")
    bundle = bundle.resolve(strict=True)
    data = data.resolve(strict=True)
    output = output.resolve(strict=False)
    manifest_bytes = (bundle / "MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    runner_path = bundle / "runner.py"
    if hashlib.sha256(runner_path.read_bytes()).hexdigest() != manifest["files"]["runner.py"]:
        raise ValueError("frozen execution runner bytes changed")
    output.mkdir(parents=True, exist_ok=False)
    state = {
        "schema_version": "1.0",
        "role": "mlrc-meta-development-pair",
        "pid": os.getpid(),
        "status": "waiting-for-gpu",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "bundle_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "queue_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "wait_ceiling_seconds": wait_seconds,
        "wall_ceiling_per_arm_seconds": wall_seconds,
        "formal_evidence_eligible": False,
        "completed_actions": [],
        "pre_execution_decision_sha256": {
            str(path.resolve(strict=True)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in decision_records
        },
    }
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["MKL_NUM_THREADS"] = "4"
    state_path = output / "STATE.json"
    write_state(state_path, state)
    spec = importlib.util.spec_from_file_location("frozen_mlrc_runner", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    wait_remaining = float(wait_seconds)
    selected_gpu = None
    lock = None
    try:
        for action in runner.ACTIONS:
            wait_started = time.monotonic()
            while True:
                state["last_checked_at_utc"] = datetime.now(UTC).isoformat()
                available = free_devices()
                if selected_gpu is None:
                    for index in available:
                        candidate_lock = (output.parent / f".scitaste-gpu-{index}.lock").open("a")
                        try:
                            fcntl.flock(candidate_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            candidate_lock.close()
                            continue
                        selected_gpu, lock = index, candidate_lock
                        break
                if selected_gpu is not None and selected_gpu in available:
                    wait_remaining -= time.monotonic() - wait_started
                    break
                elapsed = time.monotonic() - wait_started
                state.update(
                    status="waiting-for-gpu",
                    next_action=action,
                    wait_remaining_seconds=max(0.0, wait_remaining - elapsed),
                )
                write_state(state_path, state)
                if elapsed >= wait_remaining:
                    state["status"] = "wait-expired"
                    write_state(state_path, state)
                    return
                time.sleep(min(30.0, wait_remaining - elapsed))
            state.update(status="running", active_action=action, gpu_index=selected_gpu)
            write_state(state_path, state)
            result_path = runner.run_branch(
                bundle=bundle,
                data_root=data,
                action=action,
                gpu_index=selected_gpu,
                output_root=output / action,
                wall_seconds=wall_seconds,
            )
            result = json.loads((result_path / "RUN_RESULT.json").read_text())
            state["completed_actions"].append(result)
            write_state(state_path, state)
        state["status"] = "complete"
    except Exception as exc:
        state.update(
            status="failed", failure_type=type(exc).__name__, failure_summary=str(exc)[:500]
        )
        raise
    finally:
        state["updated_at_utc"] = datetime.now(UTC).isoformat()
        write_state(state_path, state)
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-wait-seconds", type=int, default=3600)
    parser.add_argument("--wall-per-arm-seconds", type=int, default=1200)
    parser.add_argument("--decision-record", type=Path, action="append", default=[])
    args = parser.parse_args()
    run_pair(
        args.bundle,
        args.data_root,
        args.output_root,
        args.max_wait_seconds,
        args.wall_per_arm_seconds,
        tuple(args.decision_record),
    )

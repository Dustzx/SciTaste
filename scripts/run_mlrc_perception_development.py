#!/usr/bin/env python3
"""Execute one real MLRC Perception development objective on an owned workspace.

This is the narrow execution bridge between the already verified split/runtime
projection and the research loop.  It never opens held-out labels or scores and
does not call a language model.  A later Full/Base research arm supplies the
editable method tree; this command owns training, development scoring, logs,
resource telemetry, and the immutable receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scitaste.evaluation.mlrc_perception_runtime import (
    inspect_mlrc_perception_runtime,
    load_mlrc_perception_runtime_manifest,
)

_OBJECTIVE_MARKER = "SCITASTE_BENCHMARK_OBJECTIVE_JSON="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_manifest(root: Path) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        total_bytes += size
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "sha256": _sha256(path),
            }
        )
    return entries, total_bytes


def _hardlink_tree(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_symlink():
            raise ValueError(f"dataset view contains a symbolic link: {relative}")
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, destination)
        else:
            raise ValueError(f"dataset view contains a special entry: {relative}")


def _read_objective(stdout_path: Path) -> dict[str, Any]:
    matches = [
        line[len(_OBJECTIVE_MARKER) :]
        for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(_OBJECTIVE_MARKER)
    ]
    if len(matches) != 1:
        raise ValueError("MLRC run did not emit exactly one objective marker")
    payload = json.loads(matches[0])
    if (
        payload.get("phase") != "dev"
        or payload.get("task_id") != "perception-temporal-action-loc"
        or not isinstance(payload.get("score"), (float, int))
    ):
        raise ValueError("MLRC objective marker does not match the development task")
    return payload


def _gpu_snapshot() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    rows: list[dict[str, Any]] = []
    for raw in completed.stdout.splitlines():
        fields = [item.strip() for item in raw.split(",")]
        if len(fields) != 6:
            raise ValueError("unexpected nvidia-smi inventory row")
        rows.append(
            {
                "index": int(fields[0]),
                "uuid": fields[1],
                "name": fields[2],
                "memory_total_mb": int(fields[3]),
                "memory_free_mb": int(fields[4]),
                "utilization_percent": int(fields[5]),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("configs/evaluation/task_runtime/mlrc_perception_temporal_action_loc_v3.yaml"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--condition",
        required=True,
        choices=(
            "upstream-base",
            "native-base",
            "raw-context",
            "full",
            "taste-packet",
            "learned-policy-on",
            "learned-policy-off",
        ),
    )
    parser.add_argument("--cuda-device", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument(
        "--editable-source",
        type=Path,
        default=None,
        help="Optional prepared env tree for a research arm; defaults to the upstream source.",
    )
    parser.add_argument(
        "--checkpoint-source",
        type=Path,
        default=None,
        help=(
            "Checkpoint tree from a failed development run. Training is skipped and only "
            "objective scoring resumes; use only for a scoring-path-only repair."
        ),
    )
    parser.add_argument(
        "--checkpoint-receipt",
        type=Path,
        default=None,
        help="Failed development RESULT.json that owns --checkpoint-source.",
    )
    parser.add_argument("--allow-execution", action="store_true")
    args = parser.parse_args()
    if not args.allow_execution:
        raise ValueError("real MLRC development execution requires --allow-execution")
    if (args.checkpoint_source is None) != (args.checkpoint_receipt is None):
        raise ValueError("checkpoint resume requires both source and owning receipt")

    repository = Path.cwd().resolve(strict=True)
    output = args.output if args.output.is_absolute() else repository / args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)

    manifest_path = args.manifest.resolve(strict=True)
    manifest, manifest_sha256 = load_mlrc_perception_runtime_manifest(manifest_path)
    inspection = inspect_mlrc_perception_runtime(
        manifest,
        manifest_sha256=manifest_sha256,
        workspace_root=repository,
    )
    if not inspection.development_ready:
        raise ValueError(f"MLRC development runtime is not ready: {inspection.blocker_codes}")

    checkout = repository / manifest.source_checkout
    upstream_visible = checkout / manifest.visible_root
    editable_source = (
        args.editable_source.resolve(strict=True)
        if args.editable_source is not None
        else upstream_visible
    )
    if not editable_source.is_dir():
        raise ValueError("editable MLRC source must be a directory")
    development_data = repository / manifest.development_view
    python_executable = repository / manifest.python_executable
    package_root = repository / manifest.python_package_root
    entrypoint = repository / manifest.development_entrypoint.locator

    output.mkdir(parents=True)
    workspace = output / "workspace"
    shutil.copytree(editable_source, workspace, symlinks=False)
    _hardlink_tree(development_data, workspace / "data")
    checkpoint_source = (
        args.checkpoint_source.resolve(strict=True) if args.checkpoint_source is not None else None
    )
    checkpoint_source_bytes = 0
    checkpoint_source_manifest_sha256 = None
    checkpoint_receipt = None
    checkpoint_receipt_path = None
    if checkpoint_source is None:
        (workspace / "ckpt").mkdir()
    else:
        if not checkpoint_source.is_dir():
            raise ValueError("checkpoint source must be a directory")
        checkpoint_source_manifest, checkpoint_source_bytes = _tree_manifest(checkpoint_source)
        checkpoint_source_manifest_sha256 = hashlib.sha256(
            json.dumps(
                checkpoint_source_manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        assert args.checkpoint_receipt is not None
        checkpoint_receipt_path = args.checkpoint_receipt.resolve(strict=True)
        checkpoint_receipt = json.loads(checkpoint_receipt_path.read_bytes())
        if (
            checkpoint_receipt.get("status") != "failed"
            or checkpoint_receipt.get("condition") != args.condition
            or checkpoint_receipt.get("objective") is not None
            or checkpoint_receipt.get("formal_evidence_eligible") is not False
        ):
            raise ValueError("checkpoint receipt is not a failed matching development run")
        if checkpoint_receipt.get("checkpoint_manifest") != checkpoint_source_manifest:
            raise ValueError("checkpoint tree differs from its failed-run receipt")
        _hardlink_tree(checkpoint_source, workspace / "ckpt")
    (workspace / "output").mkdir()

    source_manifest, source_bytes = _tree_manifest(editable_source)
    source_manifest_sha256 = hashlib.sha256(
        json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    gpu_before = _gpu_snapshot()
    selected_gpu = next((item for item in gpu_before if item["index"] == args.cuda_device), None)
    if selected_gpu is None:
        raise ValueError(f"CUDA device is unavailable: {args.cuda_device}")
    if selected_gpu["memory_free_mb"] < 20_000:
        raise ValueError("MLRC development requires at least 20 GiB free GPU memory")

    stdout_path = output / "stdout.txt"
    stderr_path = output / "stderr.txt"
    command = [
        str(python_executable),
        str(entrypoint),
        "--task",
        "perception_temporal_action_loc",
        "--result-task-id",
        "perception-temporal-action-loc",
        "--method",
        "my_method",
        "--phase",
        "dev",
    ]
    if checkpoint_source is not None:
        command.append("--skip-training")
    environment = {
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "CUDA_VISIBLE_DEVICES": str(args.cuda_device),
        "HOME": str(output / "home"),
        "LANG": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(package_root), str(workspace))),
        "TZ": "UTC",
    }
    (output / "home").mkdir()
    started_at = datetime.now(UTC)
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
    finished_at = datetime.now(UTC)
    wall_seconds = time.monotonic() - started
    objective = None
    error = None
    if timed_out:
        error = "timeout"
    elif returncode != 0:
        error = "nonzero-exit"
    else:
        try:
            objective = _read_objective(stdout_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            error = f"objective-contract:{type(exc).__name__}"

    artifact_manifest, artifact_bytes = _tree_manifest(workspace / "output")
    checkpoint_manifest, checkpoint_bytes = _tree_manifest(workspace / "ckpt")
    receipt = {
        "schema_version": "1.0",
        "evidence_role": "consumed-development-only",
        "formal_evidence_eligible": False,
        "condition": args.condition,
        "manifest": args.manifest.as_posix(),
        "manifest_sha256": manifest_sha256,
        "runtime_fingerprint": manifest.fingerprint,
        "repository_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "source_root": str(editable_source),
        "source_file_count": len(source_manifest),
        "source_bytes": source_bytes,
        "source_manifest_sha256": source_manifest_sha256,
        "training_skipped": checkpoint_source is not None,
        "checkpoint_source": (
            checkpoint_source.as_posix() if checkpoint_source is not None else None
        ),
        "checkpoint_source_bytes": checkpoint_source_bytes,
        "checkpoint_source_manifest_sha256": checkpoint_source_manifest_sha256,
        "checkpoint_receipt": (
            checkpoint_receipt_path.as_posix() if checkpoint_receipt_path is not None else None
        ),
        "checkpoint_receipt_sha256": (
            _sha256(checkpoint_receipt_path) if checkpoint_receipt_path is not None else None
        ),
        "development_view_sha256": manifest.development_view_sha256,
        "heldout_opened": False,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "wall_seconds": wall_seconds,
        "timeout_seconds": args.timeout_seconds,
        "timed_out": timed_out,
        "returncode": returncode,
        "status": "succeeded" if error is None else "failed",
        "error": error,
        "objective": objective,
        "gpu_before": selected_gpu,
        "gpu_after": next(item for item in _gpu_snapshot() if item["index"] == args.cuda_device),
        "artifact_manifest": artifact_manifest,
        "artifact_bytes": artifact_bytes,
        "checkpoint_manifest": checkpoint_manifest,
        "checkpoint_bytes": checkpoint_bytes,
        "stdout_sha256": _sha256(stdout_path),
        "stderr_sha256": _sha256(stderr_path),
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (output / "RESULT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

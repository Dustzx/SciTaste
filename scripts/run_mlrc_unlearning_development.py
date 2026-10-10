#!/usr/bin/env python3
"""Remote-only, bounded MLRC unlearning development evaluation.

Requires the pinned source, verified public assets, Python 3.12 CUDA environment,
and bubblewrap. No API, Kaggle credentials, submission, or host fallback.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import random
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from mlrc_meta_visual_fork_runtime import candidate_sandbox_command

# Remote deployment copies these two trusted modules without importing the full
# controller package or its optional API integrations.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/scitaste/evaluation"))
from mlrc_unlearning import development_scorer_source, offline_loader_source
from unlearning_exchange import IsolatedUnlearningMethod, stage_candidate_data

ASSETS = {
    "weights_resnet18_cifar10.pth": (
        "bf54311698c98adb46c766cbe505ddf20a7cae5df9f8d51c7946f7d01f82a6d4"
    ),
    "retrain_weights_resnet18_cifar10.pth": (
        "ad9d42071b7aee490293b3cca0bc393397db7e317c6cac3ad99b3f753bc9b8de"
    ),
    "forget_idx.npy": "d9cece6f3d433e0d53438c709667f62f9f79b15260e3001c82adb5a9513a52cc",
}


def run_contract(args) -> dict:
    """Bind the actual executable inputs, not just a repository revision."""
    candidate_files = {}
    for path in sorted((args.candidate / "methods").glob("*.py")):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 150_000:
            raise ValueError("Invalid candidate source file")
        candidate_files[f"methods/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "methods/MyMethod.py" not in candidate_files:
        raise ValueError("Candidate method entrypoint missing")
    script_root = Path(__file__).resolve().parent
    module_root = script_root.parent / "src/scitaste/evaluation"
    runtime_files = [
        Path(__file__).resolve(),
        script_root / "mlrc_unlearning_worker.py",
        script_root / "mlrc_meta_visual_fork_runtime.py",
        module_root / "mlrc_unlearning.py",
        module_root / "unlearning_exchange.py",
    ]
    return {
        "task_id": "mlrc-machine-unlearning-development",
        "source_commit": "0d26417034811d2d4587646c4520cc305ea09dd6",
        "candidate_sha256": candidate_files,
        "runtime_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime_files
        },
        "replicas": 10,
        "seed": args.seed,
        "wall_seconds": args.wall_seconds,
        "gpu_index": args.gpu_index,
        "gpu_uuid": args.gpu_uuid,
        "formal_evidence": False,
        "whole_agent_comparison": False,
        "protocol_amendment": "isolated-per-replica-seeds-and-eval-mode-v1",
        "metric": "total_score",
        "objective_direction": "maximize",
    }


def write_json(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def evaluate(args) -> None:
    started = time.monotonic()
    output = args.output.resolve()
    trusted = output / "trusted"
    trusted.mkdir()
    # Validate the complete assets before loading any checkpoint or CIFAR pickle.
    for name, expected in ASSETS.items():
        source = args.assets / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Asset digest mismatch: {name}")
        shutil.copyfile(source, trusted / name)
    archive = args.assets / "cifar-10-python.tar.gz"
    if hashlib.md5(archive.read_bytes()).hexdigest() != "c58f30108f718f92721af3b95e74349a":
        raise ValueError("CIFAR archive is incomplete or has an unexpected digest")
    with tarfile.open(archive) as tar:
        tar.extractall(trusted / "data", filter="data")
    (trusted / "evaluation_dev.py").write_text(development_scorer_source(args.source))
    (trusted / "load_cifar_script.py").write_text(offline_loader_source(args.source))
    bundle = output / "candidate-bundle"
    runtime = bundle / "runtime"
    runtime.mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name("mlrc_unlearning_worker.py"), runtime / "worker.py")
    # Candidate source is copied as data; importing it happens only in bubblewrap.
    methods = runtime / "methods"
    methods.mkdir()
    for source in sorted((args.candidate / "methods").glob("*.py")):
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 150_000:
            raise ValueError("Candidate must contain bounded regular Python sources")
        shutil.copyfile(source, methods / source.name)
    if not (methods / "MyMethod.py").is_file():
        raise ValueError("Candidate lacks methods/MyMethod.py")
    if not (methods / "__init__.py").exists():
        (methods / "__init__.py").touch()

    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_uuid
    os.environ["OMP_NUM_THREADS"] = "4"
    import numpy as np
    import torch

    torch.set_num_threads(4)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if not torch.cuda.is_available():
        raise RuntimeError("Selected remote CUDA runtime is unavailable")
    os.chdir(trusted)
    loader = load_module("load_cifar_script", trusted / "load_cifar_script.py")
    scorer = load_module("evaluation_dev", trusted / "evaluation_dev.py")
    loaders = loader.get_cifar10_data()
    allowed = output / "allowed-data"
    stage_candidate_data(loaders, allowed)
    scorer.get_cifar10_data = lambda: loaders

    def launch(replica, seed, original, destination):
        remaining = int(args.wall_seconds - (time.monotonic() - started))
        if remaining <= 0:
            raise TimeoutError("Whole evaluation wall budget exhausted")
        # Only original weights are exposed alongside allowed candidate data.
        staged_original = allowed / f"original-{replica:02d}.npz"
        shutil.copyfile(original, staged_original)
        worker_output = output / f"worker-{replica:02d}"
        worker_output.mkdir()
        command = candidate_sandbox_command(
            [
                sys.executable,
                str(runtime / "worker.py"),
                "--candidate",
                str(runtime),
                "--data",
                str(allowed),
                "--original",
                str(staged_original),
                "--output",
                str(worker_output / "candidate.npz"),
                "--seed",
                str(seed),
            ],
            bundle=bundle,
            data_root=allowed,
            output_root=worker_output,
            gpu_index=args.gpu_index,
            gpu_uuid=args.gpu_uuid,
            wall_seconds=remaining,
        )
        with (output / f"worker-{replica:02d}.log").open("x") as log:
            subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=remaining
            )
        # The namespace has exited before transferring its sole result. The proxy
        # then rejects symlinks, nonregular files and invalid tensor archives.
        (worker_output / "candidate.npz").rename(destination)

    method = IsolatedUnlearningMethod(output / "exchange", launch, seed=args.seed)
    results = scorer._evaluate_dev(method)
    metrics = {name: float(value) for name, value in results.items()}
    if method.replica != 10 or not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("Incomplete or non-finite development score")
    write_json(
        output / "SCORE.json",
        {
            "status": "SUCCEEDED",
            "metrics": metrics,
            "replicas": method.replica,
            "elapsed_seconds": time.monotonic() - started,
            "formal_evidence": False,
            "benchmark_split": "development",
            "protocol_amendment": "isolated-per-replica-seeds-and-eval-mode-v1",
            "seed": args.seed,
            "gpu_uuid": args.gpu_uuid,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("source", "assets", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--gpu-index", type=int, required=True)
    parser.add_argument("--gpu-uuid", required=True)
    parser.add_argument("--wall-seconds", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--evaluate", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("source", "assets", "candidate", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if not 1 <= args.wall_seconds <= 7200:
        raise ValueError("Wall budget must be 1-7200 seconds")
    if args.evaluate:
        evaluate(args)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "CONTRACT.json", run_contract(args))
    # Advisory lock serializes this task's launches; the actual live observation
    # also protects already-running workloads that do not use this lock.
    gpu_lock = (args.output.parent / f".unlearning-gpu-{args.gpu_index}.lock").open("a")
    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    observation = subprocess.check_output(
        [
            "nvidia-smi",
            f"--id={args.gpu_index}",
            "--query-gpu=uuid,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=10,
    ).strip()
    uuid, memory, utilization = [part.strip() for part in observation.split(",")]
    if uuid != args.gpu_uuid or int(memory) > 256 or int(utilization) != 0:
        write_json(
            args.output / "PROCESS_RESULT.json",
            {
                "status": "NOT_STARTED",
                "reason": "selected-gpu-not-idle-or-identity-mismatch",
                "observation": observation,
            },
        )
        raise SystemExit(1)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--evaluate"]
    started = time.monotonic()
    with (args.output / "evaluation.log").open("x") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = process.wait(timeout=args.wall_seconds)
            status = (
                "SUCCEEDED" if code == 0 and (args.output / "SCORE.json").is_file() else "FAILED"
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
            status = "TIMED_OUT"
    write_json(
        args.output / "PROCESS_RESULT.json",
        {
            "status": status,
            "exit_code": code,
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    if status != "SUCCEEDED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

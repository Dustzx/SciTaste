"""Objective-only MLRC-Bench entrypoint for an isolated task environment.

This file intentionally imports no SciTaste package modules so a task-specific
Python runtime can execute it by absolute, read-only sandbox path.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter

_MARKER = "SCITASTE_BENCHMARK_OBJECTIVE_JSON="


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task",
        required=True,
        choices=("meta-learning", "perception_temporal_action_loc"),
    )
    parser.add_argument("--method", default="my_method")
    parser.add_argument("--result-task-id", required=True)
    parser.add_argument("--phase", required=True, choices=("dev", "test"))
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Resume development scoring from an existing checkpoint after a scoring-only failure.",
    )
    args = parser.parse_args(argv)
    if args.skip_training and (
        args.task != "perception_temporal_action_loc" or args.phase != "dev"
    ):
        raise ValueError("checkpoint resume is supported only for Perception development scoring")
    workspace = Path.cwd().resolve(strict=True)
    sys.path.insert(0, str(workspace))
    started = perf_counter()
    if args.task == "perception_temporal_action_loc":
        score = _perception_score(
            args.method,
            args.phase,
            skip_training=args.skip_training,
        )
    else:
        score = _meta_learning_score(workspace, args.method, args.phase)
    elapsed = max(0.0, perf_counter() - started)
    if not math.isfinite(score):
        raise ValueError("benchmark objective score is not finite")
    payload = {
        "schema_version": "1.0",
        "task_id": args.result_task_id,
        "phase": args.phase,
        "method": args.method,
        "score": score,
        "elapsed_seconds": elapsed,
        "secondary_llm_judge_invoked": False,
        "training_skipped": args.skip_training,
    }
    print(_MARKER + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _perception_score(method_name: str, phase: str, *, skip_training: bool = False) -> float:
    training = importlib.import_module("train")
    evaluation = importlib.import_module("evaluation")
    methods = importlib.import_module("methods")
    handlers = methods.all_method_handlers()
    if method_name not in handlers:
        raise ValueError(f"unknown perception method: {method_name}")
    method = handlers[method_name](method_name)
    if phase == "dev" and not skip_training:
        training.train_model(method)
    evaluation.evaluate_model(method, phase)
    return float(evaluation.get_score(method, phase))


def _meta_learning_score(workspace: Path, method_name: str, phase: str) -> float:
    methods = importlib.import_module("methods")
    handlers = methods.all_method_handlers()
    if method_name not in handlers:
        raise ValueError(f"unknown meta-learning method: {method_name}")
    handler = handlers[method_name]
    if (
        not isinstance(handler, str)
        or not handler
        or any(part in {"", ".", ".."} for part in Path(handler).parts)
    ):
        raise ValueError("meta-learning method handler is not a safe relative directory")
    method_directory = (workspace / "methods" / handler).resolve(strict=True)
    if not method_directory.is_dir() or not method_directory.is_relative_to(workspace / "methods"):
        raise ValueError("meta-learning method resolves outside the methods directory")
    ingestion = workspace / "ingestion_output"
    scoring = workspace / "scoring_output"
    _clear_directory(ingestion)
    _clear_directory(scoring)
    scoring_method_directory = method_directory
    temporary_method_root: Path | None = None
    if phase == "test":
        temporary_method_root = Path("/tmp") / "scitaste-heldout-method"
        if temporary_method_root.exists():
            shutil.rmtree(temporary_method_root)
        shutil.copytree(method_directory, temporary_method_root)
        scoring_method_directory = temporary_method_root
        config = scoring_method_directory / "config.json"
        payload = json.loads(config.read_bytes())
        validation = payload.get("validation_datasets")
        if isinstance(validation, bool) or not isinstance(validation, int):
            raise ValueError("meta-learning validation_datasets must be an integer")
        payload["validation_datasets"] = validation * 2
        config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    task_count = 100 if phase == "dev" else 600
    try:
        _run(
            (
                sys.executable,
                "-m",
                "cdmetadl.run_eval",
                f"--input_data_dir={workspace / 'data'}",
                f"--submission_dir={scoring_method_directory}",
                f"--output_dir_ingestion={ingestion}",
                "--verbose=False",
                "--overwrite_previous_results=True",
                f"--test_tasks_per_dataset={task_count}",
            )
        )
        _run(
            (
                sys.executable,
                "-m",
                "cdmetadl.run_scoring",
                f"--input_data_dir={workspace / 'data'}",
                f"--output_dir_ingestion={ingestion}",
                f"--output_dir_scoring={scoring}",
                "--verbose=False",
                "--overwrite_previous_results=True",
                f"--test_tasks_per_dataset={task_count}",
            )
        )
    finally:
        if temporary_method_root is not None:
            shutil.rmtree(temporary_method_root, ignore_errors=True)
    score_path = scoring / "scores.txt"
    first_line = score_path.read_text(encoding="utf-8").splitlines()[0]
    _, separator, raw_score = first_line.partition(":")
    if not separator:
        raise ValueError("meta-learning objective score is malformed")
    return float(raw_score.strip())


def _clear_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("benchmark output directory cannot be a symbolic link")
    path.mkdir(exist_ok=True)
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            raise ValueError("benchmark output directory contains a special entry")


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        check=False,
        env={
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "CUDA_VISIBLE_DEVICES",
                "HOME",
                "LANG",
                "LD_LIBRARY_PATH",
                "MKL_NUM_THREADS",
                "NVIDIA_VISIBLE_DEVICES",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "PATH",
                "PYTHONHASHSEED",
                "PYTHONNOUSERSITE",
                "PYTHONPATH",
                "TMPDIR",
                "TZ",
            }
        },
    )
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, command)


if __name__ == "__main__":
    raise SystemExit(main())

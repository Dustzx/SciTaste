#!/usr/bin/env python3
"""Resume the frozen ResearchClawBench SciTaste formal cohort.

The launcher materializes source-grounded Taste packets, executes paired system
arms in alternating order, and scores completed reports with the official
benchmark scorer. Existing immutable workspaces are never overwritten.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("protocol must be a YAML mapping")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _visible_hash(task_root: Path) -> str:
    digest = hashlib.sha256()
    visible = [task_root / "task_info.json"]
    for dirname in ("data", "related_work"):
        root = task_root / dirname
        if root.is_dir():
            visible.extend(sorted(path for path in root.rglob("*") if path.is_file()))
    for path in visible:
        relative = path.relative_to(task_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _run(command: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "output_tail": completed.stdout[-8_000:],
    }


def _registered_tasks(protocol: dict[str, Any], requested: set[str]) -> list[dict[str, Any]]:
    tasks = list(protocol["population"]["tasks"])
    if requested:
        unknown = requested - {item["task_id"] for item in tasks}
        if unknown:
            raise ValueError(f"unknown registered tasks: {sorted(unknown)}")
        tasks = [item for item in tasks if item["task_id"] in requested]
    return tasks


def _validate_population(
    benchmark_root: Path, protocol: dict[str, Any], tasks: list[dict[str, Any]]
) -> None:
    commit = subprocess.run(
        ["git", "-C", str(benchmark_root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if commit != protocol["benchmark"]["commit"]:
        raise ValueError(f"benchmark commit mismatch: {commit}")
    for item in tasks:
        task_root = (benchmark_root / "tasks" / item["task_id"]).resolve(strict=True)
        if benchmark_root not in task_root.parents:
            raise ValueError(f"task escapes benchmark root: {item['task_id']}")
        observed = _visible_hash(task_root)
        if observed != item["visible_sha256"]:
            raise ValueError(f"visible task hash mismatch: {item['task_id']}")


def _compile_overlay(
    *,
    task: dict[str, Any],
    protocol: dict[str, Any],
    benchmark_root: Path,
    study_root: Path,
    source_root: Path,
    backend: Path,
    python: str,
    env: dict[str, str],
) -> dict[str, Any]:
    output = study_root / task["task_id"] / "taste-overlay"
    receipt = output / "RECEIPT.json"
    if receipt.is_file():
        try:
            _validate_overlay(output, task["task_id"], protocol)
        except (OSError, ValueError) as exc:
            return {
                "task_id": task["task_id"],
                "phase": "overlay",
                "status": "failed",
                "reason": f"invalid reused overlay: {exc}",
            }
        return {"task_id": task["task_id"], "phase": "overlay", "status": "reused"}
    compiler = protocol.get("taste_control", {}).get(
        "compiler", "scripts/compile_researchclawbench_grounded_taste_overlay.py"
    )
    compiler_path = (source_root / str(compiler)).resolve(strict=True)
    if source_root not in compiler_path.parents:
        raise ValueError("Taste compiler escapes source root")
    result = _run(
        [
            python,
            str(compiler_path),
            "--task-root",
            str(benchmark_root / "tasks" / task["task_id"]),
            "--output",
            str(output),
            "--backend",
            str(backend),
            "--allow-api",
        ],
        env=env,
    )
    status = "completed" if result["returncode"] == 0 else "failed"
    reason = None
    if status == "completed":
        try:
            _validate_overlay(output, task["task_id"], protocol)
        except (OSError, ValueError) as exc:
            status = "failed"
            reason = f"compiled overlay failed protocol validation: {exc}"
    return {
        "task_id": task["task_id"],
        "phase": "overlay",
        "status": status,
        **({"reason": reason} if reason is not None else {}),
        **result,
    }


def _validate_overlay(output: Path, task_id: str, protocol: dict[str, Any]) -> None:
    overlay = output / "TASTE_CONTROL_OVERLAY.md"
    receipt_path = output / "RECEIPT.json"
    if not overlay.is_file() or not receipt_path.is_file():
        raise ValueError("overlay or receipt missing")
    requirements = protocol.get("taste_control", {}).get("receipt_requirements")
    if requirements is None:
        return
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    checks = {
        "task_id": task_id,
        "treatment": requirements["treatment"],
        "target_study_visible": False,
        "unconditional_recommended_action_present": False,
        "native_fallback_required_when_abstaining": True,
    }
    if "render_format" in requirements:
        checks["render_format"] = requirements["render_format"]
    mismatches = {
        key: {"expected": expected, "observed": receipt.get(key)}
        for key, expected in checks.items()
        if receipt.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"overlay receipt mismatch: {mismatches}")
    maximum_bytes = int(requirements["maximum_overlay_bytes"])
    observed_bytes = overlay.stat().st_size
    if observed_bytes > maximum_bytes or receipt.get("overlay_bytes") != observed_bytes:
        raise ValueError("overlay byte ceiling or receipt size mismatch")
    if receipt.get("overlay_file_sha256") != _sha256_file(overlay):
        raise ValueError("overlay file hash differs from receipt")
    count_limits = {
        "mechanism_claim_count": requirements.get("maximum_mechanism_claims"),
        "conditional_action_count": requirements.get("maximum_conditional_actions"),
    }
    for key, maximum in count_limits.items():
        if maximum is not None and (
            not isinstance(receipt.get(key), int) or receipt[key] > int(maximum)
        ):
            raise ValueError(f"overlay receipt violates {key} limit")


def _arm_command(
    *,
    task_id: str,
    condition: str,
    protocol: dict[str, Any],
    benchmark_root: Path,
    study_root: Path,
    source_root: Path,
    python: str,
) -> list[str]:
    execution = protocol["execution"]
    agent = protocol["agent"]
    judge = protocol["judge"]
    command = [
        python,
        str(source_root / "scripts" / "run_researchclawbench_system_arm.py"),
        "--benchmark-root",
        str(benchmark_root),
        "--task-id",
        task_id,
        "--condition",
        condition,
        "--output",
        str(study_root / task_id / condition),
        "--model",
        str(agent["model"]),
        "--api-base",
        str(agent["api_base"]),
        "--api-key-env",
        str(agent["api_key_env"]),
        "--max-rounds",
        str(execution["maximum_rounds_per_arm"]),
        "--max-runtime-seconds",
        str(execution["maximum_runtime_seconds_per_arm"]),
        "--max-input-tokens",
        str(execution["maximum_input_tokens_per_call"]),
        "--max-output-tokens",
        str(execution["maximum_output_tokens_per_call"]),
        "--compact-trigger-tokens",
        str(execution["compact_trigger_tokens"]),
        "--seed",
        str(execution["seed"]),
        "--extra-body-json",
        json.dumps(agent.get("extra_body", {}), sort_keys=True),
        "--score",
        "--judge-model",
        str(judge["model"]),
        "--judge-api-base",
        str(judge["api_base"]),
        "--judge-api-key-env",
        str(judge["api_key_env"]),
    ]
    if condition == "full-scitaste":
        command.extend(
            [
                "--taste-overlay",
                str(study_root / task_id / "taste-overlay" / "TASTE_CONTROL_OVERLAY.md"),
            ]
        )
    return command


def _run_pair(
    *,
    index: int,
    task: dict[str, Any],
    protocol: dict[str, Any],
    benchmark_root: Path,
    study_root: Path,
    source_root: Path,
    python: str,
    env: dict[str, str],
) -> list[dict[str, Any]]:
    task_id = task["task_id"]
    overlay = study_root / task_id / "taste-overlay" / "TASTE_CONTROL_OVERLAY.md"
    if not overlay.is_file():
        return [
            {
                "task_id": task_id,
                "phase": "arms",
                "status": "blocked",
                "reason": "Taste overlay missing",
            }
        ]
    try:
        _validate_overlay(overlay.parent, task_id, protocol)
    except (OSError, ValueError) as exc:
        return [
            {
                "task_id": task_id,
                "phase": "arms",
                "status": "blocked",
                "reason": f"Taste overlay is not protocol-admissible: {exc}",
            }
        ]
    order = ("native-base", "full-scitaste") if index % 2 == 0 else ("full-scitaste", "native-base")
    records = []
    for condition in order:
        workspace = study_root / task_id / condition
        receipt = workspace / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
        if receipt.is_file():
            records.append(
                {
                    "task_id": task_id,
                    "condition": condition,
                    "phase": "arm",
                    "status": "reused",
                }
            )
            continue
        result = _run(
            _arm_command(
                task_id=task_id,
                condition=condition,
                protocol=protocol,
                benchmark_root=benchmark_root,
                study_root=study_root,
                source_root=source_root,
                python=python,
            ),
            env=env,
        )
        records.append(
            {
                "task_id": task_id,
                "condition": condition,
                "phase": "arm",
                "status": "completed" if result["returncode"] == 0 else "failed",
                **result,
            }
        )
    return records


def _write_index(study_root: Path, protocol: Path, records: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": "1.0",
        "protocol": str(protocol),
        "protocol_sha256": _sha256_file(protocol),
        "updated_at_unix": time.time(),
        "records": records,
    }
    (study_root / "EXECUTION_INDEX.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--phase", choices=("overlays", "arms", "all"), default="all")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--max-workers", type=int)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("formal cohort execution requires --allow-api")

    protocol_path = args.protocol.resolve(strict=True)
    protocol = _read_yaml(protocol_path)
    benchmark_root = args.benchmark_root.resolve(strict=True)
    source_root = args.source_root.resolve(strict=True)
    backend = args.backend.resolve(strict=True)
    study_root = args.study_root.resolve()
    study_root.mkdir(parents=True, exist_ok=True)
    minimum_free_bytes = int(
        protocol.get("execution", {}).get("minimum_free_bytes_before_launch", 0)
    )
    if minimum_free_bytes < 0:
        raise ValueError("minimum_free_bytes_before_launch cannot be negative")
    observed_free_bytes = shutil.disk_usage(study_root).free
    if observed_free_bytes < minimum_free_bytes:
        raise ValueError(
            "insufficient free space for formal launch: "
            f"{observed_free_bytes} < {minimum_free_bytes}"
        )
    tasks = _registered_tasks(protocol, set(args.task))
    _validate_population(benchmark_root, protocol, tasks)

    required_env = {
        protocol["agent"]["api_key_env"],
        protocol["judge"]["api_key_env"],
    }
    if args.phase in {"overlays", "all"}:
        required_env.add(_read_yaml(backend).get("api_key_env", protocol["agent"]["api_key_env"]))
    missing = sorted(name for name in required_env if not os.environ.get(name, "").strip())
    if missing:
        raise ValueError(f"missing API credentials: {missing}")

    workers = args.max_workers or int(protocol["execution"]["maximum_concurrent_pairs"])
    if workers < 1:
        raise ValueError("--max-workers must be positive")
    env = os.environ.copy()
    records: list[dict[str, Any]] = []

    if args.phase in {"overlays", "all"}:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _compile_overlay,
                    task=task,
                    protocol=protocol,
                    benchmark_root=benchmark_root,
                    study_root=study_root,
                    source_root=source_root,
                    backend=backend,
                    python=args.python,
                    env=env,
                )
                for task in tasks
            ]
            for future in concurrent.futures.as_completed(futures):
                record = future.result()
                records.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)
        _write_index(study_root, protocol_path, records)

    if args.phase in {"arms", "all"}:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _run_pair,
                    index=index,
                    task=task,
                    protocol=protocol,
                    benchmark_root=benchmark_root,
                    study_root=study_root,
                    source_root=source_root,
                    python=args.python,
                    env=env,
                )
                for index, task in enumerate(tasks)
            ]
            for future in concurrent.futures.as_completed(futures):
                pair_records = future.result()
                records.extend(pair_records)
                for record in pair_records:
                    print(json.dumps(record, ensure_ascii=False), flush=True)
        _write_index(study_root, protocol_path, records)

    failures = [record for record in records if record["status"] in {"failed", "blocked"}]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

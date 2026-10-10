#!/usr/bin/env python3
"""Score immutable ResearchClawBench trajectories in a separate evidence layer.

ResearchClawBench's upstream scorer represents provider failures as zero-valued
rubric items. This adapter preserves the original agent workspace, materializes
only the files required by the unmodified scorer, and refuses to admit those
transport failures as scientific measurements.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
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


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_score(score: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if score.get("error"):
        errors.append(str(score["error"]))
    items = score.get("items")
    if not isinstance(items, list) or not items:
        return [*errors, "no rubric items returned"]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"rubric item {index} is not an object")
            continue
        value = item.get("score")
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            errors.append(f"rubric item {index} has an invalid score")
        reasoning = str(item.get("reasoning", "")).strip()
        if not reasoning or reasoning in {
            "Failed to parse scoring response.",
            "Scoring failed.",
        }:
            errors.append(f"rubric item {index} has no valid judge response")
    if not isinstance(score.get("total_score"), (int, float)):
        errors.append("total_score is missing or non-numeric")
    return errors


def _copy_scoring_inputs(source: Path, target: Path) -> None:
    if target.exists():
        if (target / "SCORING_RECEIPT.json").is_file():
            return
        raise FileExistsError(f"partial scoring workspace exists: {target}")
    target.mkdir(parents=True)
    for filename in ("_meta.json", "INSTRUCTIONS.md"):
        source_path = source / filename
        if not source_path.is_file():
            raise FileNotFoundError(f"missing scoring input: {source_path}")
        shutil.copy2(source_path, target / filename)
    for dirname in ("report", "outputs"):
        source_path = source / dirname
        if source_path.is_dir():
            shutil.copytree(source_path, target / dirname, copy_function=os.link)


def _score_arm(
    *,
    task_id: str,
    condition: str,
    study_root: Path,
    output_root: Path,
    judge: dict[str, Any],
    score_module: Any,
) -> dict[str, Any]:
    source = study_root / task_id / condition
    source_receipt_path = source / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
    if not source_receipt_path.is_file():
        return {
            "task_id": task_id,
            "condition": condition,
            "status": "blocked",
            "errors": ["source execution receipt is missing"],
        }
    source_receipt = _read_json(source_receipt_path)
    if source_receipt.get("status") != "completed":
        return {
            "task_id": task_id,
            "condition": condition,
            "status": "not-applicable-agent-failure",
            "errors": [],
        }
    report_path = source / "report" / "report.md"
    if not report_path.is_file():
        return {
            "task_id": task_id,
            "condition": condition,
            "status": "blocked",
            "errors": ["completed source execution has no report/report.md"],
        }

    target = output_root / task_id / condition
    receipt_path = target / "SCORING_RECEIPT.json"
    if receipt_path.is_file():
        receipt = _read_json(receipt_path)
        return {
            "task_id": task_id,
            "condition": condition,
            "status": "reused" if receipt.get("status") == "completed" else "failed",
            "errors": list(receipt.get("errors", [])),
        }

    started = time.time()
    _copy_scoring_inputs(source, target)
    score = score_module.score_workspace(target)
    errors = _validate_score(score)
    score_path = target / "_score.json"
    if not score_path.is_file():
        _write_json(score_path, score)
    receipt = {
        "schema_version": "1.0",
        "task_id": task_id,
        "condition": condition,
        "status": "completed" if not errors else "failed",
        "errors": errors,
        "duration_seconds": round(time.time() - started, 3),
        "source_workspace": str(source),
        "source_receipt_sha256": _sha256_file(source_receipt_path),
        "source_report_sha256": _sha256_file(report_path),
        "judge_provider": judge["provider"],
        "judge_model": judge["model"],
        "judge_model_revision": judge["model_revision"],
        "judge_api_base": judge["api_base"],
        "score_sha256": _sha256_file(score_path),
    }
    _write_json(receipt_path, receipt)
    return {
        "task_id": task_id,
        "condition": condition,
        "status": receipt["status"],
        "errors": errors,
        "total_score": score.get("total_score") if not errors else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("formal rescoring requires --allow-api")

    protocol_path = args.protocol.resolve(strict=True)
    protocol = _read_yaml(protocol_path)
    benchmark_root = args.benchmark_root.resolve(strict=True)
    study_root = args.study_root.resolve(strict=True)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    judge = protocol["judge"]
    credential = str(judge["api_key_env"])
    if not os.environ.get(credential, "").strip():
        raise ValueError(f"missing API credential: {credential}")

    sys.path.insert(0, str(benchmark_root))
    os.environ["JUDGE_API_KEY"] = os.environ[credential]
    os.environ["JUDGE_API_BASE"] = str(judge["api_base"])
    os.environ["JUDGE_MODEL_NAME"] = str(judge["model"])
    from evaluation import score as score_module

    score_module.JUDGE_MODEL_NAME = str(judge["model"])
    workers = args.max_workers or int(protocol.get("scoring", {}).get("maximum_concurrent_arms", 1))
    if workers < 1:
        raise ValueError("--max-workers must be positive")
    jobs = [
        (task["task_id"], condition)
        for task in protocol["population"]["tasks"]
        for condition in ("native-base", "full-scitaste")
    ]
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _score_arm,
                task_id=task_id,
                condition=condition,
                study_root=study_root,
                output_root=output_root,
                judge=judge,
                score_module=score_module,
            )
            for task_id, condition in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)

    index = {
        "schema_version": "1.0",
        "study_id": protocol["study_id"],
        "protocol": str(protocol_path),
        "protocol_sha256": _sha256_file(protocol_path),
        "execution_source_study": str(study_root),
        "records": sorted(records, key=lambda item: (item["task_id"], item["condition"])),
    }
    _write_json(output_root / "SCORING_INDEX.json", index)
    failures = [
        record
        for record in records
        if record["status"] not in {"completed", "reused", "not-applicable-agent-failure"}
    ]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

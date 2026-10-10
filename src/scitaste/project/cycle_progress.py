"""Source-bound operational progress, separate from scientific completion.

Events report the last observed boundary, never process liveness or execution
authority. Immutable observations survive updates to a cycle's current pointer.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scitaste.project.models import validate_entry_id


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(root: Path, path: Path) -> Path:
    relative = path.absolute().relative_to(root)
    cursor = root
    for part in relative.parts:
        if part in {".", ".."}:
            raise ValueError("Non-canonical progress path")
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("Progress paths cannot follow symlinks")
    cursor.resolve().relative_to(root)
    return cursor


def _read(path: Path) -> tuple[dict, str]:
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Progress source exceeds bounded read")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Progress source must be an object")
    return value, _digest(raw)


def publish_cycle_progress(
    project: Path, cycle: Path, source: Path, *, status: str, stage: str
) -> dict:
    """Append an observed boundary without touching scientific/run selections."""

    root = project.resolve(strict=True)
    cycle = _inside(root, cycle)
    validate_entry_id(cycle.name, field_name="cycle identity")
    validate_entry_id(status, field_name="progress status")
    validate_entry_id(stage, field_name="progress stage")
    contract_path = _inside(root, cycle / "CONTRACT.json")
    contract, contract_sha = _read(contract_path)
    if contract.get("scope") != "native-workspace-project-cycle":
        raise ValueError("Progress requires a Native cycle contract")
    if contract.get("project") != root.name:
        raise ValueError("Progress project identity mismatch")
    source = _inside(root, source)
    source.relative_to(cycle)
    data, source_sha = _read(source)
    # Do not copy command lines, credentials, prompts or arbitrary source fields.
    observed = {
        key: data[key]
        for key in (
            "execution_status",
            "paper_cycle_delivered",
            "experience_status",
            "next_plan_status",
            "resource_status",
            "next_plan_rejection_reasons",
        )
        if key in data
    }
    payload = {
        "schema_version": "1.0",
        "project_id": root.name,
        "cycle_id": cycle.name,
        "cycle_locator": cycle.relative_to(root).as_posix(),
        "contract_sha256": contract_sha,
        "source_locator": source.relative_to(root).as_posix(),
        "source_sha256": source_sha,
        "status": status,
        "stage": stage,
        "observed": observed,
        "process_liveness": "not-observed",
        "scientific_completion": "not-assessed",
        "execution_authorized": False,
    }
    directory = _inside(root, root / "progress" / "native-cycles" / cycle.name)
    directory.mkdir(parents=True, exist_ok=True)
    with _inside(root, directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _inside(root, directory / "CURRENT.json")
        previous = _read(current)[0] if current.exists() else None
        if previous:
            event, digest = _read(_inside(root, directory / previous["event_file"]))
            if digest != previous["sha256"]:
                raise ValueError("Previous progress event digest mismatch")
            if event["payload"]["cycle_locator"] != payload["cycle_locator"]:
                raise ValueError("Cycle identity is already bound to another directory")
            if event["payload"] == payload:
                return event
        event = {
            "payload": payload,
            "recorded_at": datetime.now(UTC).isoformat(),
            "previous_event_sha256": previous["sha256"] if previous else None,
        }
        raw = (json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        digest = _digest(raw)
        target = _inside(root, directory / f"{digest}.json")
        with target.open("xb") as stream:
            stream.write(raw)
        pointer = {"event_file": target.name, "sha256": digest}
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
            json.dump(pointer, stream)
            temporary = stream.name
        os.replace(temporary, current)
        return event


def inspect_cycle_progress(project: Path) -> dict:
    """Read indexed boundaries; corrupt/stale observations remain explicit."""

    root = project.resolve(strict=True)
    index = _inside(root, root / "progress" / "native-cycles")
    rows, issues = [], []
    for directory in sorted(index.iterdir()) if index.exists() else []:
        try:
            directory = _inside(root, directory)
            pointer, _ = _read(_inside(root, directory / "CURRENT.json"))
            event, digest = _read(_inside(root, directory / pointer["event_file"]))
            if digest != pointer["sha256"]:
                raise ValueError("Progress event digest mismatch")
            payload = event["payload"]
            if payload["project_id"] != root.name or payload["cycle_id"] != directory.name:
                raise ValueError("Progress identity mismatch")
            _, source_sha = _read(_inside(root, root / payload["source_locator"]))
            _, contract_sha = _read(
                _inside(root, root / payload["cycle_locator"] / "CONTRACT.json")
            )
            event["source_current"] = (
                source_sha == payload["source_sha256"]
                and contract_sha == payload["contract_sha256"]
            )
            rows.append(event)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append({"cycle_id": directory.name, "reason": type(exc).__name__})
    rows.sort(key=lambda item: item["recorded_at"], reverse=True)
    return {
        "schema_version": "1.0",
        "project_id": root.name,
        "cycles": rows,
        "issues": issues,
        "scientific_completion": "not-assessed",
    }

"""Resume only a known pre-tool session wait, never an ambiguous tool execution."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from scitaste.executor.state_handoff import local_decision_count
from scitaste.state.persistence import StateStore


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_hashes(root):
    files = {}
    for path in sorted((root / "workspace").rglob("*")):
        if path.is_symlink():
            raise ValueError("Session checkpoint cannot bind workspace symbolic links")
        if path.is_file():
            files[str(path.relative_to(root))] = digest(path)
    return files


def history(root):
    path = root / "loop/TRAJECTORY.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def save_wait(root, *, request, elapsed):
    state = StateStore(root / "loop/state").load()
    rows = history(root)
    if (
        len(rows) != local_decision_count(state)
        or (root / f"loop/decision-{len(rows):03d}.json").exists()
    ):
        raise ValueError("Cannot checkpoint an uncommitted tool action")
    request_path = Path(request).resolve(strict=True)
    request_path.relative_to(root)
    directory = root / "session_waits"
    directory.mkdir(exist_ok=True)
    checkpoint = {
        "status": "awaiting-session-response",
        "request": str(request_path),
        "api_calls": 0,
        "contract_sha256": digest(root / "CONTRACT.json"),
        "request_sha256": digest(request_path),
        "history": rows,
        "state": state.model_dump(mode="json"),
        "workspace_files": workspace_hashes(root),
        "elapsed_seconds": elapsed,
    }
    target = directory / f"{len(list(directory.glob('*.json'))):03d}.json"
    with target.open("x") as stream:
        json.dump(checkpoint, stream)
    with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as stream:
        json.dump(
            {
                "checkpoint": str(target.relative_to(root)),
                "sha256": digest(target),
                "status": "awaiting-session-response",
                "api_calls": 0,
                "request": str(request_path),
            },
            stream,
        )
        temporary = stream.name
    os.replace(temporary, root / "SESSION_PENDING.json")


def load_wait(root, *, plan_sha256, taste_binding, exchange):
    if (root / "RESULT.json").exists():
        raise ValueError("Terminal Native run cannot resume as a session wait")
    pointer = json.loads((root / "SESSION_PENDING.json").read_text())
    path = (root / pointer["checkpoint"]).resolve(strict=True)
    path.relative_to(root / "session_waits")
    if digest(path) != pointer["sha256"]:
        raise ValueError("Session checkpoint changed")
    checkpoint = json.loads(path.read_text())
    contract = json.loads((root / "CONTRACT.json").read_text())
    if (
        digest(root / "CONTRACT.json") != checkpoint["contract_sha256"]
        or contract["plan_sha256"] != plan_sha256
        or contract.get("development_taste") != taste_binding
        or contract.get("model_source") != "assistant-session"
        or contract.get("session_exchange") != str(exchange.resolve())
    ):
        raise ValueError("Session task, treatment or exchange changed")
    for name, expected in contract["source_sha256"].items():
        source = Path(__file__).resolve().parent.parent / name
        if digest(source) != expected:
            raise ValueError("Native source changed since the checkpoint")
    request = Path(checkpoint["request"]).resolve(strict=True)
    request.relative_to(exchange.resolve())
    if digest(request) != checkpoint["request_sha256"]:
        raise ValueError("Pending model request changed")
    state = StateStore(root / "loop/state").load()
    rows = history(root)
    if (
        rows != checkpoint["history"]
        or state.model_dump(mode="json") != checkpoint["state"]
        or len(rows) != local_decision_count(state)
        or (root / f"loop/decision-{len(rows):03d}.json").exists()
        or workspace_hashes(root) != checkpoint["workspace_files"]
    ):
        raise ValueError("Workspace/checkpoint drift or uncommitted tool execution")
    # Include inactive coordination/repair gaps. The contract is immutable and
    # its original timestamp is also the paper coordinator's budget origin.
    elapsed_since_launch = time.time() - (root / "CONTRACT.json").stat().st_mtime
    return state, rows, max(checkpoint["elapsed_seconds"], elapsed_since_launch)

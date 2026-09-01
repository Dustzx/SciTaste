"""Content-addressed, atomic persistence for states and decision logs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scitaste.schema.decisions import ResearchDecision
from scitaste.state.research_state import ResearchState


def canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_id(state: ResearchState) -> str:
    digest = hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()
    return f"state-{digest}"


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


class StateStore:
    """Store the latest state plus immutable content-addressed snapshots."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.latest_path = self.root / "research_state.json"
        self.snapshot_dir = self.root / "state_snapshots"

    def save(self, state: ResearchState) -> str:
        identifier = snapshot_id(state)
        rendered = state.model_dump_json(indent=2)
        snapshot_path = self.snapshot_dir / f"{identifier}.json"
        if not snapshot_path.exists():
            _atomic_write(snapshot_path, rendered)
        _atomic_write(self.latest_path, rendered)
        return identifier

    def load(self, identifier: str | None = None) -> ResearchState:
        path = self.latest_path if identifier is None else self.snapshot_dir / f"{identifier}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))

    def list_snapshots(self) -> list[str]:
        if not self.snapshot_dir.exists():
            return []
        return sorted(path.stem for path in self.snapshot_dir.glob("state-*.json"))


class DecisionLogger:
    """Append-only JSON Lines log suitable for replay and later taste mining."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, decision: ResearchDecision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = decision.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read_all(self) -> list[ResearchDecision]:
        if not self.path.exists():
            return []
        decisions: list[ResearchDecision] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                decisions.append(ResearchDecision.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"invalid decision log line {line_number}") from exc
        return decisions

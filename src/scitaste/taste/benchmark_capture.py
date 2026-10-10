"""Ordered tool choices/outcomes; these are not automatically Scientific Taste episodes."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class BenchmarkDecisionCapture:
    def __init__(self, directory: Path, *, source_binding: dict, mode: str = "prospective"):
        if mode not in {"prospective", "historical-replay"}:
            raise ValueError("Unknown observation mode")
        directory.mkdir(parents=True, exist_ok=False)
        self.directory, self.mode = directory, mode
        self.pending, self.completed = {}, []
        self.event_index = -1
        self.source_run = None
        self.closed = False
        self.contract = {
            "schema_version": "1.0",
            "mode": mode,
            "source_binding": source_binding,
            "created_at": datetime.now(UTC).isoformat(),
            "scope": "tool-selection-observations-not-scientific-credit",
            "policy_update_authorized": False,
        }
        self._write("CONTRACT.json", self.contract)
        self.chain = _digest(self.contract)

    def _write(self, name, payload):
        with (self.directory / name).open("x") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())

    def observe(self, event):
        if self.closed:
            raise ValueError("Capture is terminal")
        index = event["event_index"]
        if type(index) is not int or index <= self.event_index:
            raise ValueError("Capture events must preserve original order")
        if self.source_run is not None and self.source_run != event["run_id"]:
            raise ValueError("Cannot combine different agent sessions")
        self.source_run = event["run_id"]
        prior = self.chain
        event_hash = _digest(event)
        self.chain = _digest({"previous": prior, "event_sha256": event_hash})
        self.event_index = index
        role = event.get("role")
        ids, names = event.get("tool_call_ids", []), event.get("tool_names", [])
        arguments = event.get("tool_arguments", [])
        if role not in {"assistant", "tool"} or not ids:
            return
        if not (len(ids) == len(names) == len(arguments)) or len(set(ids)) != len(ids):
            raise ValueError("Malformed tool identity/argument correspondence")
        for call_id, name, args in zip(ids, names, arguments, strict=True):
            key = hashlib.sha256(str(call_id).encode()).hexdigest()
            if role == "assistant":
                if call_id in self.pending or any(
                    row["call_id"] == call_id for row in self.completed
                ):
                    raise ValueError("Duplicate selected tool call")
                observation = {
                    "call_id": call_id,
                    "tool": name,
                    "arguments": args,
                    "event_index": index,
                    "source_event_sha256": event_hash,
                    "prior_event_chain_sha256": prior,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "mode": self.mode,
                    "selection_explanation": event.get("text", ""),
                    "alternatives_observed": False,
                    "scientific_decision_classified": False,
                }
                self._write(key + ".selection.json", observation)
                self.pending[call_id] = (key, observation)
            else:
                if call_id not in self.pending:
                    raise ValueError("Outcome lacks its preceding selected action")
                key, selected = self.pending[call_id]
                if name != selected["tool"] or args != selected["arguments"]:
                    raise ValueError("Outcome tool differs from selected action")
                outcome = {
                    "call_id": call_id,
                    "selection_sha256": _digest(selected),
                    "event_index": index,
                    "source_event_sha256": event_hash,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "tool_observation": event.get("text", ""),
                    "scientific_success_inferred": False,
                }
                self._write(key + ".outcome.json", outcome)
                self.completed.append(
                    {
                        "call_id": call_id,
                        "selection": key + ".selection.json",
                        "outcome": key + ".outcome.json",
                        "disposition": "observation-only",
                        "taste_admission_authorized": False,
                        "reason": "missing-scientific-decision-context-and-reviewed-attribution",
                    }
                )
                del self.pending[call_id]

    def finish(self, *, terminal_status):
        if self.closed:
            raise ValueError("Capture already finalized")
        result = {
            "schema_version": "1.0",
            "mode": self.mode,
            "terminal_status": terminal_status,
            "contract_sha256": _digest(self.contract),
            "event_chain_sha256": self.chain,
            "source_session": self.source_run,
            "last_event_index": self.event_index,
            "completed_observations": self.completed,
            "unresolved_tool_call_ids": sorted(self.pending),
            "taste_admission_authorized": False,
            "policy_update_authorized": False,
            "historical_replay_proves_prospective_capture": False,
        }
        self._write("DISPOSITION.json", result)
        self.closed = True
        return result

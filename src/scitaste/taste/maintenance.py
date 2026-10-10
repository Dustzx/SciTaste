"""Bounded Tool Intelligence handoff for missing conditional experience.

Signals come from existing retained deliberations, not another model call.
Search/curation remains a candidate action under existing permissions/budgets.
No abstention automatically weakens applicability or mutates a frozen library.
"""

import fcntl
import hashlib
import json
from pathlib import Path


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class TasteMaintenance:
    def __init__(self, directory, *, library_sha256):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.library_sha256 = library_sha256

    def observe(self, state, *, decision_index, verified=None, failure_reason=None):
        if verified is None and failure_reason != "no-valid-grounded-transfer-pool":
            return
        if failure_reason not in {None, "no-valid-grounded-transfer-pool"}:
            return  # Transport/model failures are recovery, not a source coverage label.
        assessments = verified.proposal.assessments if verified is not None else ()
        if verified is not None and any(a.verdict.value == "applicable" for a in assessments):
            return  # Abstention alone cannot establish a coverage failure.
        kind = (
            "no-qualified-retrieval-pool"
            if verified is None
            else "retrieved-premises-unresolved"
            if any(a.verdict.value == "uncertain" for a in assessments)
            else "retrieved-experience-inapplicable"
        )
        frame = (state.executor_context.get("research_reasoning") or {}).get("frame") or {}
        question = frame.get("question") or state.research_direction
        identity = _hash({"question": question, "kind": kind, "library": self.library_sha256})
        event = {
            "decision_index": decision_index,
            "kind": kind,
            "ledger_locator": verified.ledger_locator if verified is not None else None,
            "ledger_sha256": verified.ledger_sha256 if verified is not None else None,
            "assessments": [
                {"case_id": a.case_id, "verdict": a.verdict.value} for a in assessments
            ],
        }
        path = self.directory / "STATE.json"
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            queue = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "schema_version": "1.0",
                    "items": [],
                    "evicted_item_count": 0,
                    "library_sha256": self.library_sha256,
                    "library_modified": False,
                    "new_model_calls": 0,
                    "execution_authorized": False,
                }
            )
            if queue["library_sha256"] != self.library_sha256:
                raise ValueError("Maintenance queue belongs to another frozen library")
            item = next((i for i in queue["items"] if i["gap_id"] == identity), None)
            if item is None:
                item = {
                    "gap_id": identity,
                    "question": question,
                    "kind": kind,
                    "status": "pending-budgeted-source-action",
                    "events": [],
                    "suggested_source_search_ceiling": 2,
                    "next_action": (
                        "Compare source-search/re-abstraction value with the active scientific "
                        "probe; use only permitted tools and remaining resources. Distinguish "
                        "a missing relevant source from missing current-task evidence. Qualify "
                        "content, abstract conditional experience, independently review, and "
                        "freeze a successor before activation. Never rewrite this assignment."
                    ),
                    "scientific_diagnosis_verified": False,
                }
                queue["items"].append(item)
            if not any(e["decision_index"] == decision_index for e in item["events"]):
                item["events"] = [*item["events"], event][-8:]
            if len(queue["items"]) > 8:
                queue["items"].pop(0)
                queue["evicted_item_count"] += 1
            # One bounded current queue; immutable deliberation ledgers retain history.
            temporary = self.directory / "STATE.pending.json"
            with temporary.open("w") as stream:
                json.dump(queue, stream, indent=2)
            temporary.replace(path)

    def proposal_context(self):
        path = self.directory / "STATE.json"
        if not path.exists():
            return None
        queue = json.loads(path.read_text())
        if queue["library_sha256"] != self.library_sha256:
            raise ValueError("Maintenance source binding changed")
        # Expose only the latest gap, not a growing stream of repetitive failures.
        return {
            "version": "taste-maintenance-v1",
            "library_modified": False,
            "execution_authorized": False,
            "current_gap": queue["items"][-1] if queue["items"] else None,
        }

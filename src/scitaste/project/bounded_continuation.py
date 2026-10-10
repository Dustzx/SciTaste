"""Authorize only bounded continuation of observed terminal Native executions."""

import hashlib
import json

from scitaste.backends.mlagentbench import provider_ledger_accounting


def continuation_decision(execution, *, plan_sha256, taste_binding, expected_child=None):
    contract = json.loads((execution / "CONTRACT.json").read_text())
    result = json.loads((execution / "RESULT.json").read_text())
    if (
        contract["plan_sha256"] != plan_sha256
        or contract["controller_owner"] != "scitaste-native"
        or result["controller_owner"] != "scitaste-native"
        or contract.get("development_taste") != taste_binding
    ):
        raise ValueError("Continuation cannot change execution ownership, task or treatment")
    eligible = (
        result["status"] == "native-workspace-interrupted"
        and result.get("error_type") in {"JSONDecodeError", "NativeProposalFormatError"}
    ) or (
        result["status"] == "execution-unresolved"
        and bool(contract["plan"].get("remote_workspace"))
    )
    decision = {
        "eligible": False,
        "reason": "terminal-status-not-auto-recoverable",
        "status": result["status"],
        "budget_extension": False,
        "positive_result_required": False,
    }
    if not eligible:
        return decision
    claim = (
        execution.parent
        / "continuation_claims"
        / (hashlib.sha256(str(execution.resolve()).encode()).hexdigest() + ".json")
    )
    if claim.exists():
        owner = json.loads(claim.read_text()).get("child")
        if expected_child is None or owner != str(expected_child.resolve()):
            return {**decision, "reason": "remaining-budget-already-claimed"}
    accounting = provider_ledger_accounting(execution / "logs/provider_calls")
    if accounting["unresolved_reservations"]:
        return {**decision, "reason": "provider-request-unresolved"}
    if accounting["liability_usd"] >= contract["execution_api_liability_usd"]:
        return {**decision, "reason": "execution-api-budget-exhausted"}
    elapsed = result["duration_seconds"] + (contract.get("continuation") or {}).get(
        "inherited_duration_seconds", 0
    )
    if elapsed >= contract["plan"]["resource_envelope"]["wall_seconds"]:
        return {**decision, "reason": "execution-time-exhausted"}
    history = execution / "loop/TRAJECTORY.jsonl"
    if not history.exists():
        return {**decision, "reason": "no-restorable-trajectory"}
    turns = len(history.read_text().splitlines())
    if turns >= contract["max_turns"]:
        return {**decision, "reason": "turn-budget-exhausted"}
    return {
        **decision,
        "eligible": True,
        "reason": "bounded-terminal-continuation",
        "inherited_turns": turns,
        "inherited_duration_seconds": elapsed,
        "inherited_api_accounting": accounting,
    }

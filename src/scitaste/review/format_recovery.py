"""Review formatting recovery using separate, fully ledgered runtime invocations."""

import json

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.model_nodes.format_recovery import format_recoverable


def execute_review_attempts(*, invoke, bridge, output):
    """Invoke the normal facade each time: never hide calls inside its backend."""
    feedback = []
    for index in range(2):
        invocation = "paper-review" if index == 0 else "paper-review-format-retry"
        receipt = invoke(invocation, feedback)
        serialized = receipt.model_dump(mode="json")
        with (output / f"{invocation}.receipt.json").open("x") as stream:
            json.dump(serialized, stream, indent=2)
        reasons = (serialized.get("result") or {}).get("rejection_reasons", [])
        accounting = provider_ledger_accounting(bridge.records)
        retry = (
            index == 0
            and receipt.outcome.value == "rejected"
            and format_recoverable(reasons)
            and all(any(b == r or b.endswith(r) for r in reasons) for b in receipt.blockers)
            and accounting["unresolved_reservations"] == 0
            and accounting["calls"] < bridge.max_calls
            and accounting["liability_usd"] < bridge.max_cost
        )
        with (output / f"{invocation}.recovery.json").open("x") as stream:
            json.dump(
                {
                    "retry": retry,
                    "accounting": accounting,
                    "next_invocation": "paper-review-format-retry" if retry else None,
                    "budget_extension": False,
                    "conclusion_based_retry": False,
                },
                stream,
                indent=2,
            )
        if not retry:
            return receipt, invocation
        feedback = reasons
    raise AssertionError("Unreachable review retry boundary")

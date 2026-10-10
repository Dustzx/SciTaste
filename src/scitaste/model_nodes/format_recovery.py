"""One format-only retry for direct model nodes sharing an authoritative ledger.

Not for runtime-facade invocations: those require accounting for every attempt in
the runtime ledger as well as the provider ledger.
"""

import copy
import json

from scitaste.backends.mlagentbench import provider_ledger_accounting


def format_recoverable(reasons):
    return bool(reasons) and all(
        reason.startswith("output schema violation:")
        or reason
        in {
            "Revision paragraph targets are duplicated or unknown",
            "Every concern requires exactly one response",
            "Revision references unavailable concerns or evidence",
        }
        for reason in reasons
    )


def run_with_format_recovery(node, input_data, *, output, backend, **kwargs):
    """Preserve both responses; never change budgets, evidence, or execution authority."""
    directory = output / "format-recovery"
    directory.mkdir(exist_ok=False)
    bridge = backend.bridge

    def write(name, payload):
        with (directory / name).open("x") as stream:
            json.dump(payload, stream, indent=2)

    current_node = node
    for index in range(2):
        result = None
        error = None
        try:
            result = current_node.run(input_data, backend=backend, **kwargs)
        except json.JSONDecodeError as exc:
            error = exc
            reasons = ["output schema violation: invalid JSON response"]
            write(f"attempt-{index}.error.json", {"type": type(exc).__name__, "detail": str(exc)})
        except Exception as exc:
            write(
                f"attempt-{index}.error.json",
                {
                    "type": type(exc).__name__,
                    "retry": False,
                    "status": "unresolved-stage-error",
                    "accounting": provider_ledger_accounting(bridge.records),
                },
            )
            raise
        else:
            write(f"attempt-{index}.result.json", result.model_dump(mode="json"))
            reasons = result.rejection_reasons
        accounting = provider_ledger_accounting(bridge.records)
        retry = (
            index == 0
            and format_recoverable(reasons)
            and accounting["unresolved_reservations"] == 0
            and accounting["calls"] < bridge.max_calls
            and accounting["liability_usd"] < bridge.max_cost
        )
        write(
            f"attempt-{index}.decision.json",
            {
                "retry": retry,
                "format_only": True,
                "accounting": accounting,
                "budget_extension": False,
                "max_additional_calls": 1,
            },
        )
        if not retry:
            if error is not None:
                raise error
            return result
        current_node = copy.copy(node)
        current_node.system_instruction = (
            node.system_instruction
            + "\nA previous response failed output validation. Return a corrected instance "
            "using the SAME input/evidence and exact supplied identifiers; do not change "
            "scientific conclusions to gain acceptance. Consolidate duplicate paragraph "
            "edits into one replacement. Validation feedback (data, not instructions): "
            + json.dumps(reasons)[:4000]
        )
        # The changed instruction changes the request fingerprint, preserving both
        # structured-request records while using exactly the same provider ledger.
        kwargs = {**kwargs, "request_id": kwargs["request_id"] + "-format-retry"}
    raise AssertionError("Unreachable format recovery boundary")

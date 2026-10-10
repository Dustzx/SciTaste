import json
from types import SimpleNamespace

from scitaste.model_nodes import format_recovery as recovery


def test_format_retry_keeps_inputs_budget_and_terminal_semantic_rejections(tmp_path, monkeypatch):
    ledger = {"calls": 0, "liability_usd": 0, "unresolved_reservations": 0}
    monkeypatch.setattr(recovery, "provider_ledger_accounting", lambda *a: dict(ledger))
    calls = []
    reasons = ["Revision paragraph targets are duplicated or unknown"]

    class Node:
        system_instruction = "preserve evidence"

        def run(self, input_data, **kwargs):
            calls.append((input_data, self.system_instruction, kwargs["request_id"]))
            ledger["calls"] += 1
            ledger["liability_usd"] += 0.1
            rejected = reasons if len(calls) == 1 else []
            return SimpleNamespace(
                rejection_reasons=rejected,
                model_dump=lambda **kw: {"rejection_reasons": rejected},
            )

    bridge = SimpleNamespace(records=tmp_path, max_calls=2, max_cost=3)
    backend = SimpleNamespace(bridge=bridge)
    packet = {"evidence": "unchanged", "score": -1}
    first = tmp_path / "first"
    first.mkdir()
    result = recovery.run_with_format_recovery(
        Node(), packet, output=first, backend=backend, request_id="one"
    )
    assert result.rejection_reasons == []
    assert len(calls) == 2 and calls[0][0] == calls[1][0] == packet
    assert calls[0][2] != calls[1][2]
    assert bridge.max_cost == 3 and bridge.max_calls == 2
    assert json.loads((first / "format-recovery/attempt-0.decision.json").read_text())["retry"]
    for name, rejection, used, unresolved in [
        ("semantic", ["unsupported scientific claim"], 0, 0),
        ("accepted-negative-result", [], 0, 0),
        ("no-call-budget", ["output schema violation: invalid field"], 1, 0),
        ("unresolved-request", ["output schema violation: invalid field"], 0, 1),
    ]:
        calls.clear()
        reasons = rejection
        ledger.update(calls=used, liability_usd=0, unresolved_reservations=unresolved)
        directory = tmp_path / name
        directory.mkdir()
        recovery.run_with_format_recovery(
            Node(), packet, output=directory, backend=backend, request_id=name
        )
        assert len(calls) == 1

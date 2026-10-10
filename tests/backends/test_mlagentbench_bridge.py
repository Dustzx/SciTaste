import json
from types import SimpleNamespace

import pytest

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, ProviderBudgetExhausted


def test_failed_provider_reservation_remains_in_shared_accounting(tmp_path):
    from scitaste.backends.mlagentbench import provider_ledger_accounting

    (tmp_path / "00000.json").write_text(json.dumps({"status": "reserved", "liability_usd": 0.5}))
    (tmp_path / "00000.completion").write_text(
        json.dumps({"status": "completed", "liability_usd": 0.1})
    )
    (tmp_path / "00001.json").write_text(json.dumps({"status": "reserved", "liability_usd": 0.3}))
    snapshot = provider_ledger_accounting(tmp_path)
    assert snapshot["calls"] == 2
    assert snapshot["unresolved_reservations"] == 1
    assert snapshot["liability_usd"] == pytest.approx(0.4)
    (tmp_path / "00001.json").write_text(json.dumps({"status": "reserved", "liability_usd": None}))
    with pytest.raises(ValueError, match="cannot be treated as zero"):
        provider_ledger_accounting(tmp_path)


def test_upstream_provider_bridge_records_identity_and_stops_at_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_TEST_KEY", "private-test-key")
    calls = []

    class Transport:
        def post(self, url, **kwargs):
            calls.append(kwargs["payload"])
            return {
                "model": "served-revision",
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                "choices": [{"message": {"content": "Action: Read File"}}],
            }

    bridge = MLAgentBenchProviderBridge(
        config=SimpleNamespace(
            model="bound-model",
            api_key_env="BRIDGE_TEST_KEY",
            base_url="https://example.invalid/v1",
            extra_body={},
        ),
        log_root=tmp_path,
        max_calls=1,
        max_output_tokens=32,
        transport=Transport(),
    )
    assert (
        bridge.complete_text("Plan", tmp_path / "agent.log", "bound-model") == "Action: Read File"
    )
    assert calls[0]["stop"] == ["Observation:"]
    record = json.loads((tmp_path / "provider_calls/00000.completion").read_text())
    assert record["served_model"] == "served-revision"
    reservation = json.loads((tmp_path / "provider_calls/00000.json").read_text())
    assert record["liability_usd"] == record["observed_usage_ceiling_usd"]
    assert record["liability_usd"] < reservation["liability_usd"]
    assert "private-test-key" not in (tmp_path / "provider_calls/00000.json").read_text()
    with pytest.raises(ProviderBudgetExhausted, match="budget exhausted") as failure:
        bridge.complete_text("Next", tmp_path / "agent.log", "bound-model")
    assert failure.value.details["request_sent"] is False
    assert failure.value.details["calls"] == 1
    assert failure.value.details["spent_liability_usd"] == record["liability_usd"]
    assert len(calls) == 1

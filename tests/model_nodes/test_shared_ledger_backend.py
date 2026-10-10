from types import SimpleNamespace

import pytest

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend


def test_structured_review_consumes_same_agent_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_TEST_KEY", "fixture")
    calls = []

    class Transport:
        def post(self, url, **kwargs):
            calls.append(kwargs["payload"])
            return {
                "model": "actual-revision",
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                "choices": [{"message": {"content": '{"findings": []}'}}],
            }

    bridge = MLAgentBenchProviderBridge(
        config=SimpleNamespace(
            provider="fixture",
            model="requested-model",
            api_key_env="LEDGER_TEST_KEY",
            base_url="https://example.invalid",
            extra_body={},
        ),
        log_root=tmp_path,
        max_calls=2,
        transport=Transport(),
    )
    bridge.complete_text("agent action", tmp_path / "agent.log", "requested-model")
    backend = SharedLedgerStructuredBackend(bridge)
    assert backend.config is bridge.config
    request = StructuredModelRequest(
        request_id="review",
        node_name="implementation-intent-review",
        stage="EVIDENCE",
        state_snapshot_id="fixture",
        expected_backend="fixture",
        expected_model="requested-model",
        policy_id="fixture",
        policy_fingerprint="0" * 64,
        system_instruction="Review source",
        input_payload={},
        output_schema={"type": "object"},
        prompt_version="v1",
        profile_id="shared-budget-profile",
        profile_fingerprint="1" * 64,
        generation_envelope={
            "max_request_bytes": 10000,
            "max_output_tokens": 512,
            "context_window_tokens": 20000,
            "structured_json": True,
        },
        admission_budget={
            "max_request_bytes": 10000,
            "max_input_tokens": 10000,
            "max_output_tokens": 512,
            "max_total_tokens": 10512,
            "max_latency_ms": 120000,
            "max_response_cost_usd": 1,
        },
        cumulative_project_budget={
            "max_invocations": 2,
            "max_total_tokens": 21024,
            "max_api_cost_usd": 2,
        },
    )
    response = backend.complete(request)
    assert response.model == "actual-revision"  # Let the node reject identity drift.
    assert response.usage.cost_usd == pytest.approx((12 * 12 + 4 * 36) / 1e6)
    assert response.output_payload == {"findings": []}
    assert calls[1]["stop"] is None
    assert calls[1]["max_tokens"] == 512
    with pytest.raises(RuntimeError, match="budget exhausted"):
        bridge.complete_text("next action", tmp_path / "agent.log", "requested-model")
    with pytest.raises(FileExistsError):
        backend.complete(request)
    assert len(calls) == 2

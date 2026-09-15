from __future__ import annotations

import json

import pytest

from scitaste.backends.local_transformers import LocalGeneration, LocalTransformersConfig
from scitaste.model_nodes import NodePolicy, StructuredModelRequest
from scitaste.model_nodes.local_transformers import StructuredLocalTransformersBackend
from scitaste.model_nodes.openai_compatible import StructuredBackendDisabledError


class StubStructuredRuntime:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration:
        self.calls.append(
            {
                "messages": messages,
                "seed": seed,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
            }
        )
        return LocalGeneration(
            text=self.responses[len(self.calls) - 1],
            input_tokens=31,
            output_tokens=13,
        )


def _config(*, enabled: bool = True, retries: int = 1) -> LocalTransformersConfig:
    return LocalTransformersConfig(
        model_path="/models/qwen3vl2b",
        model_id="Qwen/Qwen3-VL-2B-Instruct",
        model_revision="local-snapshot-47f9c0e0",
        max_new_tokens=256,
        max_context_tokens=4096,
        max_retries=retries,
        execution_enabled=enabled,
    )


def _request() -> StructuredModelRequest:
    policy = NodePolicy(
        policy_id="local-structured-policy",
        enabled=True,
        allowed_node_names=["reference-quality"],
        expected_backend="local-transformers",
        expected_model="Qwen/Qwen3-VL-2B-Instruct@local-snapshot-47f9c0e0",
    )
    return StructuredModelRequest(
        request_id="local-structured-one",
        node_name="reference-quality",
        stage="EXPERIMENT",
        state_snapshot_id="a" * 64,
        expected_backend=policy.expected_backend,
        expected_model=policy.expected_model,
        policy_id=policy.policy_id,
        policy_fingerprint=policy.fingerprint,
        system_instruction="Return one grounded quality proposal.",
        input_payload={"input": {"source_id": "source-one"}},
        output_schema={"type": "object"},
        seed=17,
        prompt_version="reference-quality-v1",
    )


def test_local_structured_backend_retains_identity_prompt_and_zero_api_cost() -> None:
    runtime = StubStructuredRuntime(['{"verdict":"reject"}'])

    response = StructuredLocalTransformersBackend(_config(), runtime=runtime).complete(_request())

    assert response.output_payload == {"verdict": "reject"}
    assert response.backend == "local-transformers"
    assert response.model == "Qwen/Qwen3-VL-2B-Instruct@local-snapshot-47f9c0e0"
    assert response.usage.input_tokens == 31
    assert response.usage.output_tokens == 13
    assert response.usage.cost_usd == 0.0
    call = runtime.calls[0]
    assert call["seed"] == 17
    assert call["temperature"] == 0.0
    assert call["messages"][0]["role"] == "system"
    user_payload = json.loads(call["messages"][1]["content"])
    assert "request_fingerprint" not in user_payload["request_identity"]
    assert "request_id" not in user_payload["request_identity"]


def test_local_structured_backend_retains_every_bounded_repair_attempt() -> None:
    runtime = StubStructuredRuntime(["not-json", '{"verdict":"qualify"}'])

    response = StructuredLocalTransformersBackend(_config(), runtime=runtime).complete(_request())
    evidence = json.loads(response.raw_response)

    assert response.output_payload == {"verdict": "qualify"}
    assert response.usage.input_tokens == 62
    assert response.usage.output_tokens == 26
    assert evidence["accepted_attempt"] == 1
    assert [item["text"] for item in evidence["attempts"]] == [
        "not-json",
        '{"verdict":"qualify"}',
    ]
    assert "not one valid JSON object" in runtime.calls[1]["messages"][-1]["content"]


def test_local_structured_backend_turns_invalid_generation_into_durable_rejection() -> None:
    runtime = StubStructuredRuntime(["bad", "still bad"])

    response = StructuredLocalTransformersBackend(_config(), runtime=runtime).complete(_request())
    evidence = json.loads(response.raw_response)

    assert response.output_payload == {}
    assert evidence["accepted_attempt"] is None
    assert all(not item["json_object_parsed"] for item in evidence["attempts"])


def test_local_structured_backend_requires_its_own_enable_gate() -> None:
    backend = StructuredLocalTransformersBackend(
        _config(enabled=False),
        runtime=StubStructuredRuntime(['{"verdict":"reject"}']),
    )

    with pytest.raises(StructuredBackendDisabledError, match="local structured"):
        backend.complete(_request())

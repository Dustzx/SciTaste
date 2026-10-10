from __future__ import annotations

import base64
import hashlib
import json

import pytest

from scitaste.evaluation.decision_image_backend import ImageEvidenceDecisionBackend
from scitaste.evaluation.decision_method_comparison import DecisionMethodRequest
from scitaste.evaluation.decision_policy_baselines import run_decision_policy
from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPResponse,
    StructuredOpenAICompatibleConfig,
)
from scitaste.project.models import content_sha256
from scripts.run_scitastebench_decision_baselines import RecordedDecisionBackend

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII="
)


class Transport:
    def __init__(self):
        self.payloads = []

    def post(self, url, *, headers, payload, timeout):
        self.payloads.append(payload)
        answer = (
            {"action_scores": {"A": 0.6, "B": 0.4}}
            if len(self.payloads) == 1
            else {"selected_action_id": "A"}
        )
        response = {
            "model": "image-model",
            "choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
        return StructuredHTTPResponse(data=response, raw_body=json.dumps(response))


def image_request(tmp_path, *, media_type="image/png"):
    (tmp_path / "image.png").write_bytes(PNG)
    payload = {
        "schema_version": "1.0",
        "case_id": "a" * 64,
        "hypothesis_structure": "competing-candidates",
        "evidence_relation": "underdetermined",
        "bottleneck": "metric-selection",
        "identifiability": "low",
        "budget_pressure": "medium",
        "terminal_readiness": "not-ready",
        "decision_basis": "Select from visible pre-decision evidence.",
        "evidence_anchors": ["Training image only; no action outcomes."],
        "evidence_artifacts": [
            {
                "artifact_id": "sample",
                "relative_locator": "image.png",
                "media_type": media_type,
                "sha256": hashlib.sha256(PNG).hexdigest(),
                "size_bytes": len(PNG),
                "outcome_data": False,
            }
        ],
        "available_actions": [
            {"action_id": k, "semantic_role": k, "description": k} for k in ("A", "B")
        ],
        "native_action_id": "A",
        "resource_limits": {"gpu_seconds": 1200.0},
        "maximum_steps": 1,
        "timeout_seconds": 1200,
    }
    return DecisionMethodRequest.model_validate(
        {**payload, "request_sha256": content_sha256(payload)}
    )


def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("SCITASTE_IMAGE_TEST_KEY", "test-value")
    transport = Transport()
    config = StructuredOpenAICompatibleConfig(
        provider="test",
        base_url="https://example.test/v1",
        model="image-model",
        api_key_env="SCITASTE_IMAGE_TEST_KEY",
        live_enabled=True,
        unpriced_engineering_probe=True,
    )
    return ImageEvidenceDecisionBackend(
        config, evidence_root=tmp_path, transport=transport
    ), transport


def test_both_planning_calls_receive_identical_bound_images(tmp_path, monkeypatch):
    request = image_request(tmp_path)
    model, transport = backend(tmp_path, monkeypatch)
    recording = tmp_path / "recordings.jsonl"
    model = RecordedDecisionBackend(model, recording)
    result = run_decision_policy(
        (request,),
        method_id="image-planning",
        policy_kind="planning",
        backend=model,
        backend_manifest_sha256="b" * 64,
    )
    assert result.submissions[0].selected_action_id == "A"
    assert len(transport.payloads) == 2
    records = [json.loads(line) for line in recording.read_text().splitlines()]
    assert records[0]["response"]["output_payload"]["action_scores"] == {"A": 0.6, "B": 0.4}
    assert records[1]["response"]["raw_response"]
    for payload in transport.payloads:
        parts = payload["messages"][-1]["content"]
        assert parts[0]["type"] == "text"
        assert request.request_sha256 in parts[0]["text"]
        assert base64.b64decode(parts[2]["image_url"]["url"].split(",", 1)[1]) == PNG
        assert "action_utilities" not in json.dumps(payload)
    assert (
        transport.payloads[0]["messages"][-1]["content"][1:]
        == (transport.payloads[1]["messages"][-1]["content"][1:])
    )


@pytest.mark.parametrize("damage", ["modified", "wrong-type", "unsupported-type"])
def test_invalid_images_never_reach_provider(tmp_path, monkeypatch, damage):
    media_type = {"wrong-type": "image/jpeg", "unsupported-type": "application/pdf"}.get(
        damage, "image/png"
    )
    request = image_request(tmp_path, media_type=media_type)
    if damage == "modified":
        (tmp_path / "image.png").write_bytes(PNG[:-1] + b"x")
    model, transport = backend(tmp_path, monkeypatch)
    result = run_decision_policy(
        (request,),
        method_id="image-direct",
        policy_kind="direct",
        backend=model,
        backend_manifest_sha256="b" * 64,
    )
    assert result.submissions[0].failure_code == "ValueError"
    assert transport.payloads == []

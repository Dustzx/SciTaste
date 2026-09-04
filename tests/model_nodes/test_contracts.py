from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResult,
    NodeResultStatus,
    ReviewSemanticOutput,
    StructuredModelRequest,
    StructuredModelResponse,
)
from scitaste.schema.actions import MetaAction


def request(**updates: object) -> StructuredModelRequest:
    values: dict[str, object] = {
        "request_id": "request-1",
        "node_name": "review-semantic",
        "stage": "COMMUNICATION",
        "state_snapshot_id": "snapshot-1",
        "expected_backend": "scripted",
        "expected_model": "scripted-v1",
        "policy_id": "policy-1",
        "policy_fingerprint": "1" * 64,
        "system_instruction": "Return a typed proposal only.",
        "input_payload": {"review": "Add a baseline."},
        "output_schema": {"type": "object"},
        "seed": 7,
        "prompt_version": "review-v1",
    }
    values.update(updates)
    return StructuredModelRequest.model_validate(values)


def test_request_fingerprint_covers_input_schema_and_pinned_identity() -> None:
    baseline = request()

    assert baseline.fingerprint == request().fingerprint
    assert (
        baseline.fingerprint != request(input_payload={"review": "Clarify the method."}).fingerprint
    )
    assert baseline.fingerprint != request(output_schema={"type": "array"}).fingerprint
    assert baseline.fingerprint != request(expected_model="other-model").fingerprint
    assert baseline.fingerprint != request(policy_fingerprint="2" * 64).fingerprint


def test_policy_fingerprint_normalizes_allowlist_order_and_covers_budget() -> None:
    first = NodePolicy(
        policy_id="policy",
        enabled=True,
        allowed_node_names=["review-semantic", "interpretation-threat"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        allowed_action_types=[MetaAction.REPRODUCE, MetaAction.ADD_ANALYSIS],
    )
    reordered = NodePolicy(
        policy_id="policy",
        enabled=True,
        allowed_node_names=["interpretation-threat", "review-semantic"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        allowed_action_types=[MetaAction.ADD_ANALYSIS, MetaAction.REPRODUCE],
    )

    assert first.fingerprint == reordered.fingerprint
    assert first.fingerprint != first.model_copy(update={"max_api_cost_usd": 0.01}).fingerprint


@pytest.mark.parametrize(
    "updates",
    [
        {"max_api_cost_usd": float("inf")},
        {"max_api_cost_usd": float("nan")},
        {"max_latency_ms": float("inf")},
        {"ambiguity_margin_max": float("inf")},
    ],
)
def test_policy_rejects_non_finite_float_limits(updates: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        NodePolicy(
            policy_id="policy",
            expected_backend="scripted",
            expected_model="scripted-v1",
            **updates,
        )


def test_cost_telemetry_cannot_be_disabled_for_a_bounded_node() -> None:
    with pytest.raises(ValidationError):
        NodePolicy(
            policy_id="policy",
            expected_backend="scripted",
            expected_model="scripted-v1",
            require_cost_telemetry=False,
        )


def test_response_rejects_a_raw_response_hash_mismatch() -> None:
    with pytest.raises(ValidationError, match="raw_response_sha256"):
        StructuredModelResponse(
            request_id="request-1",
            request_fingerprint=request().fingerprint,
            output_payload={},
            backend="scripted",
            model="scripted-v1",
            raw_response="actual bytes",
            raw_response_sha256="0" * 64,
            latency_ms=1,
            usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0),
        )


def test_context_and_policy_reject_duplicate_authority_references() -> None:
    with pytest.raises(ValidationError, match="context references must be unique"):
        NodeContext(
            project_id="project",
            stage="EVIDENCE",
            state_snapshot_id="snapshot",
            cumulative_api_cost_usd=0.0,
            claim_ids=["claim-1", "claim-1"],
        )
    with pytest.raises(ValidationError, match="policy allowlists"):
        NodePolicy(
            policy_id="policy",
            expected_backend="scripted",
            expected_model="scripted-v1",
            allowed_tool_names=["search", "search"],
        )


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_context_rejects_non_finite_cumulative_api_cost(value: float) -> None:
    with pytest.raises(ValidationError):
        NodeContext(
            project_id="project",
            stage="EVIDENCE",
            state_snapshot_id="snapshot",
            cumulative_api_cost_usd=value,
        )


def test_node_result_cannot_claim_execution_authority() -> None:
    raw = "{}"
    response = StructuredModelResponse(
        request_id="request-1",
        request_fingerprint=request().fingerprint,
        output_payload={},
        backend="scripted",
        model="scripted-v1",
        raw_response=raw,
        raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        latency_ms=1,
        usage=Usage(cost_usd=0),
    )

    with pytest.raises(ValidationError):
        NodeResult[ReviewSemanticOutput](
            node_name="review-semantic",
            policy_id="policy-1",
            status=NodeResultStatus.REJECTED,
            request=request(),
            response=response,
            rejection_reasons=["rejected"],
            advisory_only=False,
        )

    with pytest.raises(ValidationError, match="cannot expose a trusted proposal"):
        NodeResult[ReviewSemanticOutput](
            node_name="review-semantic",
            policy_id="policy-1",
            status=NodeResultStatus.REJECTED,
            request=request(),
            response=response,
            proposal={
                "concerns": [
                    {
                        "concern_id": "concern-1",
                        "category": "clarity",
                        "severity": "medium",
                        "text": "Clarify the method.",
                        "proposed_action_type": "CLARIFY_EXISTING_TEXT",
                    }
                ],
                "summary": "One concern.",
                "confidence": 0.5,
            },
            rejection_reasons=["rejected"],
        )

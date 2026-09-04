from __future__ import annotations

import hashlib
import json

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    RecordingStructuredBackend,
    ReplayStructuredBackend,
    ReviewSemanticInput,
    ReviewSemanticNode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    StructuredModelResponse,
    StructuredReplayMissError,
)
from scitaste.schema.actions import MetaAction


def payload() -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "medium",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "Clarify the intervention boundary.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.85,
    }


def context() -> NodeContext:
    return NodeContext(
        project_id="project-1",
        stage="COMMUNICATION",
        state_snapshot_id="snapshot-1",
        cumulative_api_cost_usd=0.0,
        claim_ids=["claim-1"],
        section_ids=["method"],
    )


def policy() -> NodePolicy:
    return NodePolicy(
        policy_id="policy-review",
        enabled=True,
        allowed_node_names=["review-semantic"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        allowed_action_types=[MetaAction.CLARIFY_EXISTING_TEXT],
    )


def test_structured_response_records_and_replays_exactly(tmp_path) -> None:
    recording = tmp_path / "structured.jsonl"
    scripted = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={"review-1": ScriptedStructuredReply(output_payload=payload())},
    )
    input_data = ReviewSemanticInput(review_text="Please clarify the method boundary.")
    first = ReviewSemanticNode().run(
        input_data,
        context=context(),
        backend=RecordingStructuredBackend(scripted, recording),
        policy=policy(),
        request_id="review-1",
        seed=7,
    )

    assert first.status == NodeResultStatus.ACCEPTED
    lines = recording.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["request"]["expected_model"] == "scripted-v1"
    assert stored["response"]["raw_response_sha256"]

    replayed = ReviewSemanticNode().run(
        input_data,
        context=context(),
        backend=ReplayStructuredBackend(recording),
        policy=policy(),
        request_id="review-1",
        seed=7,
    )
    assert replayed.status == NodeResultStatus.ACCEPTED
    assert replayed.response.cached is True
    assert replayed.proposal == first.proposal
    assert replayed.request.fingerprint == first.request.fingerprint


def test_replay_rejects_even_a_small_request_change(tmp_path) -> None:
    recording = tmp_path / "structured.jsonl"
    scripted = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={"review-1": ScriptedStructuredReply(output_payload=payload())},
    )
    ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Please clarify the method boundary."),
        context=context(),
        backend=RecordingStructuredBackend(scripted, recording),
        policy=policy(),
        request_id="review-1",
        seed=7,
    )
    replay = ReplayStructuredBackend(recording)

    with pytest.raises(StructuredReplayMissError, match="no exact structured replay"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Please clarify a different boundary."),
            context=context(),
            backend=replay,
            policy=policy(),
            request_id="review-1",
            seed=7,
        )


@pytest.mark.parametrize("mismatch", ["request_id", "request_fingerprint"])
def test_association_mismatch_is_recorded_and_replayed_as_a_rejection(
    tmp_path, mismatch: str
) -> None:
    class AssociationMismatchBackend:
        name = "scripted"
        model = "scripted-v1"

        def complete(self, request):  # type: ignore[no-untyped-def]
            raw = json.dumps(payload(), sort_keys=True, separators=(",", ":"))
            return StructuredModelResponse(
                request_id=(
                    "different-request" if mismatch == "request_id" else request.request_id
                ),
                request_fingerprint=(
                    "0" * 64 if mismatch == "request_fingerprint" else request.fingerprint
                ),
                output_payload=payload(),
                backend=self.name,
                model=self.model,
                raw_response=raw,
                raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                latency_ms=1,
                usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0),
            )

    recording = tmp_path / "mismatched.jsonl"
    kwargs = {
        "input_data": ReviewSemanticInput(review_text="Please clarify the method boundary."),
        "context": context(),
        "policy": policy(),
        "request_id": "review-mismatch",
        "seed": 7,
    }
    first = ReviewSemanticNode().run(
        kwargs.pop("input_data"),
        backend=RecordingStructuredBackend(AssociationMismatchBackend(), recording),
        **kwargs,
    )

    assert first.status == NodeResultStatus.REJECTED
    assert first.proposal is None
    assert first.untrusted_proposal is not None
    assert len(recording.read_text(encoding="utf-8").splitlines()) == 1

    replayed = ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Please clarify the method boundary."),
        context=context(),
        backend=ReplayStructuredBackend(recording),
        policy=policy(),
        request_id="review-mismatch",
        seed=7,
    )
    assert replayed.status == NodeResultStatus.REJECTED
    assert replayed.rejection_reasons == first.rejection_reasons
    assert replayed.response.cached is True

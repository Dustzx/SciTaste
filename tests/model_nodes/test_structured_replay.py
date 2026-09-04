from __future__ import annotations

import json

import pytest

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

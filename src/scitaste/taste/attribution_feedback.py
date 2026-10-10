"""Bind a retained AI critique to the exact candidate being revised."""

import hashlib
import json

from scitaste.model_nodes.experience_attribution import AttributionReviewFeedback
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.taste.ai_attribution import (
    AI_TASTE_ATTRIBUTION_REVIEW_NODE,
    AITasteAttributionReviewInput,
    AITasteAttributionReviewProposal,
)
from scitaste.taste.episodes import TasteEpisodeCandidate


def load_attribution_feedback(raw: bytes, candidate: TasteEpisodeCandidate):
    """Verify internal provenance, not provider identity or scientific truth."""
    payload = json.loads(raw)["result"]
    fingerprint = payload["request"].pop("fingerprint", None)
    result = NodeResult[AITasteAttributionReviewProposal].model_validate(payload)
    if (
        result.status != NodeResultStatus.ACCEPTED
        or result.node_name != AI_TASTE_ATTRIBUTION_REVIEW_NODE
        or result.request.node_name != AI_TASTE_ATTRIBUTION_REVIEW_NODE
        or (fingerprint is not None and fingerprint != result.request.fingerprint)
        or result.response.request_fingerprint != result.request.fingerprint
        or result.response.request_id != result.request.request_id
        or result.response.tool_calls
        or result.proposal is None
        or not result.response.raw_response
    ):
        raise ValueError("Expected a bound, retained attribution review")
    packet = AITasteAttributionReviewInput.model_validate(result.request.input_payload["input"])
    proposal = result.proposal
    if (
        packet.candidate_sha256 != candidate.candidate_sha256
        or packet.candidate_id != candidate.candidate_id
        or packet.credit_assignments != candidate.credit_assignments
        or proposal.review_packet_sha256 != packet.review_packet_sha256
    ):
        raise ValueError("Review does not bind the candidate being revised")
    response = json.loads(result.response.raw_response)
    recorded = json.loads(response["choices"][0]["message"]["content"])
    if (
        AITasteAttributionReviewProposal.model_validate(recorded) != proposal
        or AITasteAttributionReviewProposal.model_validate(result.response.output_payload)
        != proposal
    ):
        raise ValueError("Review critique differs from retained response")
    return AttributionReviewFeedback(
        candidate_sha256=candidate.candidate_sha256,
        review_result_sha256=hashlib.sha256(raw).hexdigest(),
        verdict=proposal.verdict.value,
        rationale=proposal.rationale,
        supported_credit_ids=proposal.supported_credit_ids,
    )

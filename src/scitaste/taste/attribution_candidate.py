"""Materialize proposed credit without changing measured observations or trust."""

import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.experience_attribution import (
    ExperienceAttributionDraft,
    ExperienceAttributionInput,
    ExperienceAttributionNode,
)
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.taste.episodes import TasteEpisodeCandidate


def candidate_from_attribution_draft(
    candidate: TasteEpisodeCandidate,
    result: NodeResult[ExperienceAttributionDraft],
    *,
    evidence_root: Path,
) -> TasteEpisodeCandidate | None:
    """Verify a saved node proposal; this is not independent provider verification."""
    node = ExperienceAttributionNode()
    if (
        result.status != NodeResultStatus.ACCEPTED
        or result.node_name != node.node_name
        or result.request.node_name != node.node_name
        or result.response.request_id != result.request.request_id
        or result.response.request_fingerprint != result.request.fingerprint
        or result.response.tool_calls
        or result.proposal is None
    ):
        raise ValueError("Expected a bound accepted attribution draft")
    packet = ExperienceAttributionInput.model_validate(result.request.input_payload["input"])
    if packet.candidate != candidate:
        raise ValueError("Attribution draft belongs to a different observation candidate")
    root = evidence_root.resolve(strict=True)
    for item in candidate.evidence:
        path = (root / item.locator).resolve(strict=True)
        path.relative_to(root)
        if path.stat().st_size > 256000:
            raise ValueError("Attribution evidence exceeds limit")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item.sha256:
            raise ValueError("Original observation evidence changed")
        if data.decode("utf-8") != packet.evidence[item.evidence_id]:
            raise ValueError("Attribution request differs from original evidence")
    proposal = result.proposal
    if proposal != ExperienceAttributionDraft.model_validate(result.response.output_payload):
        raise ValueError("Attribution proposal differs from recorded response")
    if result.response.raw_response is None:
        raise ValueError("Attribution draft requires retained raw provider response")
    raw = json.loads(result.response.raw_response)
    recorded = json.loads(raw["choices"][0]["message"]["content"])
    if ExperienceAttributionDraft.model_validate(recorded) != proposal:
        raise ValueError("Attribution proposal differs from raw response bytes")
    if node._proposal_rejections(proposal, input_data=packet, context=None, policy=None):
        raise ValueError("Attribution proposal cites unsupported outcomes or confounders")
    if proposal.abstained:
        return None
    fields = {
        name: getattr(candidate, name)
        for name in type(candidate).model_fields
        if name != "candidate_sha256"
    }
    fields.update(
        candidate_id="attribution-" + result.response.raw_response_sha256[:24],
        attribution_producer_role=candidate.producer_role,
        attribution_producer_id="model-attribution-draft",
        credit_assignments=proposal.credit_assignments,
        applicability_conditions=proposal.applicability_conditions,
        failure_conditions=proposal.failure_conditions,
    )
    return TasteEpisodeCandidate.create(**fields)

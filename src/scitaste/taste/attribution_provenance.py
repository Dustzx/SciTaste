"""Recover attribution-producer identity from the candidate's exact draft bytes."""

import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.experience_attribution import ExperienceAttributionDraft
from scitaste.model_nodes.models import NodeResult
from scitaste.taste.episodes import TasteEpisodeCandidate


def attribution_producer(candidate_path: Path, draft_path: Path) -> dict:
    candidate = TasteEpisodeCandidate.model_validate_json(candidate_path.read_bytes())
    binding = json.loads(candidate_path.with_name("BINDING.json").read_text())
    raw = draft_path.read_bytes()
    if (
        binding["draft_result_sha256"] != hashlib.sha256(raw).hexdigest()
        or binding["proposed_candidate_sha256"] != candidate.candidate_sha256
    ):
        raise ValueError("Producer draft does not bind this attribution candidate")
    payload = json.loads(raw)["result"]
    recorded = payload["request"].pop("fingerprint", None)
    result = NodeResult[ExperienceAttributionDraft].model_validate(payload)
    if (
        recorded != result.request.fingerprint
        or result.request.fingerprint != binding["draft_request_fingerprint"]
        or result.response.raw_response_sha256 != binding["raw_response_sha256"]
        or result.status.value != "accepted"
    ):
        raise ValueError("Attribution producer provenance changed or was not accepted")
    return {
        "producer_model_id": result.response.model,
        "producer_provider_id": result.response.backend,
        "producer_run_id": draft_path.resolve().parent.name,
        "draft_result_sha256": binding["draft_result_sha256"],
    }

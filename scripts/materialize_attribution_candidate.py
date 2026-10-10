"""Convert a retained attribution draft into a separately quarantined candidate."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.experience_attribution import ExperienceAttributionDraft
from scitaste.model_nodes.models import NodeResult
from scitaste.taste.attribution_candidate import candidate_from_attribution_draft
from scitaste.taste.episodes import TasteEpisodeCandidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--draft-result", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = TasteEpisodeCandidate.model_validate_json(args.candidate.read_bytes())
    draft_bytes = args.draft_result.read_bytes()
    payload = json.loads(draft_bytes)["result"]
    recorded_fingerprint = payload["request"].pop("fingerprint", None)
    result = NodeResult[ExperienceAttributionDraft].model_validate(payload)
    if recorded_fingerprint is not None and recorded_fingerprint != result.request.fingerprint:
        raise ValueError("Recorded attribution request fingerprint differs")
    proposed = candidate_from_attribution_draft(candidate, result, evidence_root=args.evidence_root)
    args.output.resolve().relative_to(Path("outputs/projects").resolve(strict=True))
    args.output.mkdir(parents=True, exist_ok=False)
    if proposed is not None:
        with (args.output / "CANDIDATE.json").open("x") as stream:
            stream.write(proposed.model_dump_json(indent=2))
    binding = {
        "original_candidate_sha256": candidate.candidate_sha256,
        "draft_result_sha256": hashlib.sha256(draft_bytes).hexdigest(),
        "draft_request_fingerprint": result.request.fingerprint,
        "raw_response_sha256": result.response.raw_response_sha256,
        "proposed_candidate_sha256": proposed.candidate_sha256 if proposed else None,
        "status": "quarantined-for-review" if proposed else "abstained",
        "review_completed": False,
        "policy_update_authorized": False,
        "provider_execution_independently_verified": False,
    }
    with (args.output / "BINDING.json").open("x") as stream:
        json.dump(binding, stream, indent=2)
    print(json.dumps(binding))


if __name__ == "__main__":
    main()

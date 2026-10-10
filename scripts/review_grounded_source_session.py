"""Prepare/import independent session Taste reviews without provider impersonation."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scitaste.evaluation.ai_taste_abstraction_review import (
    AIAbstractionAdjudicationResponse,
    AIAbstractionPrimaryRequest,
    AIAbstractionRawReviewResponse,
    LockedAIAbstractionPrimaryReviews,
    _bound_file,
    _canonical_sha256,
    compile_ai_taste_abstraction_review_requests,
    finalize_ai_taste_abstraction_reviews,
    import_codex_agent_abstraction_review,
    load_ai_abstraction_request_pack,
    lock_ai_taste_abstraction_primary_reviews,
)
from scitaste.model_nodes.session_exchange import retain_json


def owned(project, path, *, existing=True):
    target = path.resolve(strict=existing)
    target.relative_to(project / "evaluations")
    return target


def prepare(project, abstraction_receipt, output):
    root = Path.cwd().resolve(strict=True)
    project = project.resolve(strict=True)
    project.relative_to(root)
    receipt = owned(project, abstraction_receipt)
    output = owned(project, output, existing=False)
    template = root / "configs/evaluation/pilots"
    template /= "scitastebench_track_a_codex_agent_abstraction_review_v1.yaml"
    protocol = yaml.safe_load(template.read_text())
    protocol["protocol_id"] = output.name
    for identity in [*protocol["primary_reviewers"], protocol["adjudicator"]]:
        role = identity["role"]
        identity.update(
            reviewer_id=f"{output.name}-{role}",
            model_revision=f"{datetime.now(UTC).date()}-{role}-session-unverified",
        )
        identity["identity_sha256"] = _canonical_sha256(
            {key: identity[key] for key in ("provider", "model", "model_revision")}
        )
    output.mkdir(parents=True, exist_ok=False)
    retain_json(output / "PROTOCOL.json", protocol)
    pack = compile_ai_taste_abstraction_review_requests(
        evidence_root=root,
        runtime_receipt_paths=[receipt],
        protocol_path=output / "PROTOCOL.json",
        output_dir=output / "prepared",
        planned_source_count=1,
        eligible_source_count=1,
        runtime_rejected_source_count=0,
    )
    retain_json(output / "RESPONSE_SCHEMA.json", AIAbstractionRawReviewResponse.model_json_schema())
    # The importer binds the normalized request model, not the pretty-printed
    # request bytes. Expose the actual identities so session authors need not
    # guess a hash algorithm or fabricate a request binding.
    request_bindings = {}
    for role in ("primary-a", "primary-b"):
        request_path = output / f"prepared/requests/{role}.json"
        request = AIAbstractionPrimaryRequest.model_validate_json(request_path.read_text())
        request_bindings[role] = {
            "request_sha256": request.request_sha256,
            "reviewer_id": request.reviewer.reviewer_id,
            "reviewer_identity_sha256": request.reviewer.identity_sha256,
        }
    retain_json(output / "REQUEST_BINDINGS.json", request_bindings)
    retain_json(
        output / "ADJUDICATION_SCHEMA.json", AIAbstractionAdjudicationResponse.model_json_schema()
    )
    retain_json(
        output / "SESSION_BOUNDARY.json",
        {
            "provider_fields_name_role_slots_only": True,
            "provider_diversity_verified": False,
            "exact_model_identity_verified": False,
            "fresh_context_required": True,
            "source_extractor_may_not_review": True,
            "reviews_are_not_human_validation": True,
            "formal_evidence_eligible": False,
            "api_calls": 0,
            "library_admitted": False,
        },
    )
    return {"status": "awaiting-independent-session-reviews", "pack_sha256": pack.pack_sha256}


def finish(project, output, session_metadata):
    root = Path.cwd().resolve(strict=True)
    project = project.resolve(strict=True)
    project.relative_to(root)
    output = owned(project, output)
    metadata = json.loads(owned(project, session_metadata).read_text())
    roles = ("primary-a", "primary-b")
    if metadata[roles[0]]["session_id"] == metadata[roles[1]]["session_id"]:
        raise ValueError("Primary reviews require distinct observed sessions")
    pack = load_ai_abstraction_request_pack(output / "prepared")
    producers = set()
    for candidate in pack.candidates:
        receipt = json.loads(_bound_file(root, candidate.runtime_receipt).read_text())
        provenance = (receipt.get("result") or {}).get("response", {}).get(
            "session_provenance"
        ) or {}
        if provenance.get("author_reference"):
            producers.add(provenance["author_reference"])
    if any(metadata[role]["session_id"] in producers for role in metadata):
        raise ValueError("An abstraction producer cannot review its own candidate")

    def import_role(role, request):
        observed = metadata[role]
        receipt = output / f"{role}-execution.json"
        if receipt.exists():
            retained = json.loads(receipt.read_text())
            if retained["agent_session_id"] != observed["session_id"]:
                raise ValueError("Retained review belongs to a different session")
            return receipt
        import_codex_agent_abstraction_review(
            evidence_root=root,
            request_path=request,
            raw_response_path=response_path(role),
            agent_session_id=observed["session_id"],
            agent_runtime="Codex collaboration session; no API provider execution attestation",
            started_at=datetime.fromisoformat(observed["started_at"]),
            completed_at=datetime.fromisoformat(observed["completed_at"]),
            output_path=receipt,
        )
        return receipt

    def response_path(role):
        raw = output / f"{role}-response.json"
        if role == "adjudicator":
            return raw
        value = json.loads(raw.read_text())
        # Sorting a set-valued code list repairs serialization, not a verdict.
        # Retain both byte streams; never edit the independently supplied review.
        changed = False
        for item in value.get("responses", []):
            codes = item.get("issue_codes", [])
            if len(set(codes)) != len(codes):
                raise ValueError("Duplicate issue codes require a reviewer correction")
            if codes != sorted(codes):
                item["issue_codes"] = sorted(codes)
                changed = True
        AIAbstractionRawReviewResponse.model_validate(value)
        if not changed:
            return raw
        normalized = output / f"{role}-format-normalized.json"
        retain_json(normalized, value)
        import hashlib

        retain_json(
            output / f"{role}-format-recovery.json",
            {
                "operation": "sort-set-valued-issue-codes-only",
                "original_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest(),
                "scientific_assessment_modified": False,
                "new_model_responses": 0,
            },
        )
        return normalized

    receipts = tuple(import_role(role, output / f"prepared/requests/{role}.json") for role in roles)
    lock_path = output / "locked/LOCK.json"
    if lock_path.exists():
        locked = LockedAIAbstractionPrimaryReviews.model_validate_json(lock_path.read_text())
    else:
        locked = lock_ai_taste_abstraction_primary_reviews(
            evidence_root=root,
            request_pack_path_or_dir=output / "prepared",
            raw_response_paths=tuple(response_path(role) for role in roles),
            execution_receipt_paths=receipts,
            output_dir=output / "locked",
        )
    final_args = {}
    if locked.disputes:
        if "adjudicator" not in metadata:
            return {"status": "adjudication-required", "disputes": len(locked.disputes)}
        if metadata["adjudicator"]["session_id"] in {metadata[r]["session_id"] for r in roles}:
            raise ValueError("Adjudication requires a third observed session")
        request = (root / locked.adjudication_request.path).resolve(strict=True)
        request.relative_to(output)
        final_args = {
            "adjudication_response_path": output / "adjudicator-response.json",
            "adjudication_execution_receipt_path": import_role("adjudicator", request),
        }
    final = finalize_ai_taste_abstraction_reviews(
        evidence_root=root,
        locked_primary_reviews_path_or_dir=output / "locked",
        output_path=output / "FINAL.json",
        **final_args,
    )
    return {
        "status": "reviewed",
        "accepted": final.accepted_count,
        "rejected": final.rejected_count,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--abstraction-receipt", type=Path)
    parser.add_argument("--session-metadata", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.abstraction_receipt is None:
            parser.error("prepare requires --abstraction-receipt")
        result = prepare(args.project, args.abstraction_receipt, args.output)
    else:
        if args.session_metadata is None:
            parser.error("finish requires --session-metadata")
        result = finish(args.project, args.output, args.session_metadata)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

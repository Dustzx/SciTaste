"""Bind source-preserving revisions to actual locked AI review findings."""

import hashlib
from pathlib import Path

from scitaste.evaluation.ai_taste_abstraction_review import (
    AIAbstractionRawReviewResponse,
    AIAbstractionReviewExecutionReceipt,
    AIAcceptedTasteAbstractionSet,
    LockedAIAbstractionPrimaryReviews,
    _bound_file,
    _candidate_from_receipt,
    _load_primary_requests,
    _verify_pack_candidates,
    _verify_review_evidence,
    load_ai_abstraction_request_pack,
)
from scitaste.taste.reference_quality import ReferenceQualityInput
from scitaste.taste.semantic_models import GroundedTasteRevisionInput


def prepare_grounded_revision(
    *,
    evidence_root: Path,
    review_final: Path,
    source: ReferenceQualityInput,
) -> GroundedTasteRevisionInput:
    """Support agreed rejections; disputed/adjudicated cases require a separate route."""
    root = evidence_root.resolve(strict=True)
    final_path = review_final.resolve(strict=True)
    final_path.relative_to(root)
    raw = final_path.read_bytes()
    final = AIAcceptedTasteAbstractionSet.model_validate_json(raw)
    lock = LockedAIAbstractionPrimaryReviews.model_validate_json(
        _bound_file(root, final.locked_primary_reviews).read_bytes()
    )
    if lock.disputes or final.adjudication_response is not None:
        raise ValueError("This revision route requires primary agreement, not adjudication")
    if lock.review_set_sha256 != final.locked_primary_review_set_sha256:
        raise ValueError("Review lock differs from final decision")
    pack_path = _bound_file(root, final.request_pack)
    if pack_path != _bound_file(root, lock.request_pack):
        raise ValueError("Final and lock refer to different review packs")
    pack = load_ai_abstraction_request_pack(pack_path)
    _verify_pack_candidates(root, pack)
    if (
        pack.pack_sha256 != final.request_pack_sha256
        or pack.pack_sha256 != lock.request_pack_sha256
    ):
        raise ValueError("Review pack hash mismatch")
    candidates = [c for c in pack.candidates if c.source_id == source.source_id]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one reviewed candidate for the source")
    selected = candidates[0]
    decision = next(d for d in final.decisions if d.review_item_id == selected.review_item_id)
    if decision.disposition.value != "reject" or decision.resolution != "primary-agreement":
        raise ValueError("Only independently rejected candidates need this revision route")
    rows = [r for r in lock.normalized_rows if r.review_item_id == selected.review_item_id]
    if len(rows) != 2 or set(decision.deciding_row_sha256s) != {r.row_sha256 for r in rows}:
        raise ValueError("Final decision does not bind both actual review rows")
    requests = _load_primary_requests(root, pack)
    responses = {}
    for binding in lock.raw_responses:
        path = _bound_file(root, binding)
        response = AIAbstractionRawReviewResponse.model_validate_json(path.read_bytes())
        responses[response.reviewer_id] = (response, path)
    for binding in lock.execution_receipts:
        path = _bound_file(root, binding)
        receipt = AIAbstractionReviewExecutionReceipt.model_validate_json(path.read_bytes())
        response, response_path = responses[receipt.reviewer_id]
        _verify_review_evidence(
            root, requests[receipt.reviewer_id], response, response_path, receipt, path
        )
        row = next(r for r in rows if r.reviewer_id == receipt.reviewer_id)
        item = next(r for r in response.responses if r.review_item_id == selected.review_item_id)
        if (row.assessment, row.disposition, row.issue_codes, row.rationale) != (
            item.assessment,
            item.disposition,
            item.issue_codes,
            item.rationale,
        ) or row.disposition.value != "reject":
            raise ValueError("Locked finding differs from the original rejection")
    _, original, previous, _ = _candidate_from_receipt(
        root, _bound_file(root, selected.runtime_receipt)
    )
    if (
        original.source_id,
        original.source_projection_sha256,
        original.source_projection,
        original.stage,
        original.decision_role,
    ) != (
        source.source_id,
        source.source_projection_sha256,
        source.source_projection,
        source.decision_stage,
        source.decision_role,
    ):
        raise ValueError("Revision would change the screened and reviewed source")
    final_hash = hashlib.sha256(raw).hexdigest()
    return GroundedTasteRevisionInput(
        source_id=source.source_id,
        candidate_id=source.source_id + "-revision-" + final_hash[:12],
        case_id=original.case_id,
        stage=original.stage,
        decision_role=original.decision_role,
        source_projection=original.source_projection,
        source_projection_sha256=original.source_projection_sha256,
        domain_tags=original.domain_tags,
        outcome_information_availability=original.outcome_information_availability,
        previous_abstraction=previous,
        review_findings=tuple("; ".join(row.issue_codes) + ": " + row.rationale for row in rows),
        review_final_sha256=final_hash,
    )

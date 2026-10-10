"""Compile AI-reviewed precedents for explicitly development-only execution."""

import json
from pathlib import Path

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.evaluation.ai_taste_abstraction_review import (
    _bound_file,
    _candidate_from_receipt,
    _canonical_sha256,
    _verify_pack_candidates,
    load_ai_abstraction_request_pack,
)
from scitaste.evaluation.taste_mechanism_suite import (
    _load_accepted_set,
    _verify_accepted_review_chain,
)
from scitaste.model_nodes.runtime import RuntimeInvocationReceipt
from scitaste.taste.semantic import reference_quality_from_ledger


def reviewed_development_cases(
    *, evidence_root: Path, outputs_root: Path, accepted_set: Path, quality_result: Path
) -> list[TasteCase]:
    """Verify actual source quality and review chain; do not create formal authority.

    One quality result covers one source. No source is inferred from review prose,
    and revised candidates retain their original scientific stage and scope.
    """
    root = evidence_root.resolve(strict=True)
    outputs = outputs_root.resolve(strict=True)
    outputs.relative_to(root)
    final_path = accepted_set.resolve(strict=True)
    final_path.relative_to(root)
    quality_path = quality_result.resolve(strict=True)
    quality_path.relative_to(root)
    final = _load_accepted_set(final_path)
    pack = load_ai_abstraction_request_pack(_bound_file(root, final.request_pack))
    if pack.pack_sha256 != final.request_pack_sha256:
        raise ValueError("Accepted set binds a different review pack")
    _verify_pack_candidates(root, pack)
    _verify_accepted_review_chain(root, final, pack)
    receipt = RuntimeInvocationReceipt.model_validate(
        json.loads(quality_path.read_text())["receipt"]
    )
    ledger = (outputs / receipt.ledger_locator).resolve(strict=True)
    ledger.relative_to(outputs)
    entries = list(ledger.glob(f"*__{receipt.invocation_id}.json"))
    if len(entries) != 1:
        raise ValueError("Expected one source-quality ledger entry")
    quality = reference_quality_from_ledger(
        entries[0], evidence_root=outputs, allow_development_session=True
    )
    if quality.proposal.verdict.value != "qualify":
        raise ValueError("Source did not qualify")
    candidates = {item.review_item_id: item for item in pack.candidates}
    cases = []
    for accepted in final.accepted:
        candidate = candidates[accepted.review_item_id]
        for field in (
            "source_id",
            "candidate_id",
            "case_id",
            "runtime_receipt",
            "runtime_entry_sha256",
            "abstraction_sha256",
        ):
            if getattr(accepted, field) != getattr(candidate, field):
                raise ValueError("Accepted item differs from reviewed candidate")
        _, source, abstraction, _ = _candidate_from_receipt(
            root, _bound_file(root, candidate.runtime_receipt)
        )
        if (
            source.source_id != quality.input.source_id
            or source.source_projection_sha256 != quality.input.source_projection_sha256
            or source.source_projection != quality.input.source_projection
            or source.stage != quality.input.decision_stage
            or source.decision_role != quality.input.decision_role
        ):
            raise ValueError("Reviewed candidate differs from the qualified source")
        boundary = abstraction.transfer_boundary
        grounding_hash = _canonical_sha256(
            {
                "grounding": [item.model_dump(mode="json") for item in abstraction.grounding],
                "transfer_boundary": boundary.model_dump(mode="json"),
            }
        )
        fields = abstraction.model_dump(exclude={"grounding", "transfer_boundary"})
        cases.append(
            TasteCase(
                **fields,
                stage=source.stage,
                applicability_conditions=list(boundary.applies_when),
                failure_conditions=list(boundary.fails_when),
                counterfactual_probe=boundary.counterfactual_probe,
                taste_grounding_sha256=grounding_hash,
                domain_tags=list(source.domain_tags),
                label_basis="dual_ai_reviewed_external_source",
                human_verified=False,
                retrieval_eligible=True,
                extractor_version="reviewed-development-library-v1",
                provenance=[
                    ProvenanceRecord(
                        source_type="reviewed-development-reference",
                        locator=str(final_path.relative_to(root)),
                        content_hash=_canonical_sha256(final.model_dump(mode="json")),
                        accessed_at=final.finalized_at,
                        derivation_method="source-qualified-ai-reviewed-abstraction",
                        redistributable=False,
                        metadata={
                            "formal_evidence_eligible": False,
                            "provider_diversity_verified": False,
                            "source_projection_sha256": source.source_projection_sha256,
                            "source_id": source.source_id,
                            "quality_backend": quality.backend,
                            "quality_model": quality.model,
                            "quality_session_authored": quality.backend == "assistant-session",
                            "quality_result": str(quality_path.relative_to(root)),
                            "review_item_id": accepted.review_item_id,
                            "deliberately_discarded_details": list(
                                boundary.deliberately_discarded_details
                            ),
                        },
                    )
                ],
            )
        )
    if not cases:
        raise ValueError("No accepted precedents to compile")
    return cases

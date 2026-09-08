"""Writing-contract utilities and rhetorical-role taste retrieval."""

from __future__ import annotations

from scitaste.state.research_state import ParagraphContract, ResearchState
from scitaste.taste.retriever import TasteQuery, TasteRetrievalPolicy, TasteRetriever


def retrieve_contract_taste(
    state: ResearchState,
    contracts: list[ParagraphContract],
    retriever: TasteRetriever,
    *,
    limit_per_contract: int = 1,
) -> list[str]:
    identifiers: list[str] = []
    claims = {item.claim_id: item for item in state.claims}
    for contract in contracts:
        strengths = {
            claims[claim_id].strength for claim_id in contract.claim_ids if claim_id in claims
        }
        claim_strength = next(iter(strengths)) if len(strengths) == 1 else None
        results = retriever.retrieve(
            TasteQuery(
                text=(
                    f"{contract.section_name} {contract.rhetorical_role} "
                    f"{contract.input_context} {contract.intended_takeaway}"
                ),
                policy=TasteRetrievalPolicy.WRITING_DECISION,
                stage="COMMUNICATION",
                domain_tags=[state.target_domain],
                venue=state.target_venue,
                writing_level="paragraph",
                section_type=contract.section_name,
                rhetorical_role=contract.rhetorical_role,
                claim_strength=claim_strength,
                citation_density=_citation_density(len(contract.evidence_ids)),
                writing_taste_dimensions=_dimensions_for_role(contract.rhetorical_role),
            ),
            limit=limit_per_contract,
        )
        for result in results:
            if result.case.case_id not in identifiers:
                identifiers.append(result.case.case_id)
    return identifiers


def _citation_density(evidence_count: int) -> str:
    if evidence_count == 0:
        return "none"
    if evidence_count == 1:
        return "low"
    if evidence_count <= 3:
        return "medium"
    return "high"


def _dimensions_for_role(role: str) -> list[str]:
    normalized = role.casefold()
    if any(token in normalized for token in ("limit", "scope", "qualif")):
        return ["scientific_integrity", "claim_calibration", "precision_and_scope"]
    if any(token in normalized for token in ("result", "evidence", "experiment")):
        return ["argumentative_structure", "evidence_prioritization"]
    if any(token in normalized for token in ("contribution", "problem", "gap")):
        return ["scientific_positioning", "narrative_focus"]
    if any(token in normalized for token in ("conclusion", "synth", "takeaway")):
        return ["global_coherence", "reader_guidance", "anti_defensive_style"]
    return ["reader_guidance"]

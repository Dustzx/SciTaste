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
    for contract in contracts:
        results = retriever.retrieve(
            TasteQuery(
                text=f"{contract.input_context} {contract.intended_takeaway}",
                policy=TasteRetrievalPolicy.RHETORICAL_ROLE,
                stage="COMMUNICATION",
                domain_tags=[state.target_domain],
                venue=state.target_venue,
                rhetorical_role=contract.rhetorical_role,
            ),
            limit=limit_per_contract,
        )
        for result in results:
            if result.case.case_id not in identifiers:
                identifiers.append(result.case.case_id)
    return identifiers

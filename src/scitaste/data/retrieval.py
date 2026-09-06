"""Deterministic lexical retrieval for the factual Knowledge Library."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from scitaste.data.models import KnowledgeDocument
from scitaste.data.store import KnowledgeLibrary
from scitaste.taste.retriever import lexical_similarity


class RetrievedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: KnowledgeDocument
    score: float = Field(ge=0.0)


class KnowledgeRetriever:
    def __init__(self, library: KnowledgeLibrary) -> None:
        self.library = library

    def retrieve(
        self,
        text: str,
        *,
        domain_tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedKnowledge]:
        return rank_knowledge_documents(
            self.library.all(),
            text,
            domain_tags=domain_tags,
            limit=limit,
        )


def rank_knowledge_documents(
    documents: Iterable[KnowledgeDocument],
    text: str,
    *,
    domain_tags: list[str] | None = None,
    limit: int = 5,
) -> list[RetrievedKnowledge]:
    """Rank an already admitted document set with the library's exact policy."""

    if not text.strip():
        raise ValueError("knowledge retrieval text must not be blank")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("knowledge retrieval limit must be an integer from 1 to 20")
    if domain_tags is not None and (
        len(domain_tags) > 20
        or any(not isinstance(tag, str) or not tag.strip() for tag in domain_tags)
    ):
        raise ValueError("knowledge retrieval domain tags must be bounded non-empty strings")
    requested_tags = {tag.casefold() for tag in domain_tags or []}
    results: list[RetrievedKnowledge] = []
    for document in documents:
        searchable = " ".join(
            [document.title, document.abstract, document.content, *document.domain_tags]
        )
        score = lexical_similarity(text, searchable)
        document_tags = {tag.casefold() for tag in document.domain_tags}
        if requested_tags:
            score += 0.25 * len(requested_tags & document_tags) / len(requested_tags)
        if score > 0:
            results.append(RetrievedKnowledge(document=document, score=round(score, 6)))
    return sorted(results, key=lambda result: (-result.score, result.document.document_id))[:limit]


__all__ = ["KnowledgeRetriever", "RetrievedKnowledge", "rank_knowledge_documents"]

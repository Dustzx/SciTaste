"""Deterministic lexical retrieval for the factual Knowledge Library."""

from __future__ import annotations

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
        requested_tags = {tag.casefold() for tag in domain_tags or []}
        results: list[RetrievedKnowledge] = []
        for document in self.library.all():
            searchable = " ".join(
                [document.title, document.abstract, document.content, *document.domain_tags]
            )
            score = lexical_similarity(text, searchable)
            document_tags = {tag.casefold() for tag in document.domain_tags}
            if requested_tags:
                score += 0.25 * len(requested_tags & document_tags) / len(requested_tags)
            if score > 0:
                results.append(RetrievedKnowledge(document=document, score=round(score, 6)))
        return sorted(results, key=lambda result: (-result.score, result.document.document_id))[
            :limit
        ]

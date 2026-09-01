"""Stage- and role-aware retrieval over scientific decision precedents."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scitaste.data.models import TasteCase
from scitaste.data.store import TasteLibrary

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class TasteRetrievalPolicy(StrEnum):
    TOPICAL = "topical"
    DECISION_PATTERN = "decision_pattern"
    STAGE_CONDITIONED = "stage_conditioned"
    RHETORICAL_ROLE = "rhetorical_role"
    VISUAL_ROLE = "visual_role"


class TasteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    policy: TasteRetrievalPolicy = TasteRetrievalPolicy.STAGE_CONDITIONED
    stage: str | None = None
    candidate_action_types: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    venue: str | None = None
    rhetorical_role: str | None = None
    figure_role: str | None = None


class RetrievedTasteCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case: TasteCase
    score: float = Field(ge=0.0)
    matched_fields: list[str] = Field(default_factory=list)


class TasteRetriever:
    def __init__(self, library: TasteLibrary) -> None:
        self.library = library

    def retrieve(self, query: TasteQuery, *, limit: int = 5) -> list[RetrievedTasteCase]:
        results = [self._score(case, query) for case in self.library.all()]
        positive = [result for result in results if result.score > 0]
        return sorted(positive, key=lambda result: (-result.score, result.case.case_id))[:limit]

    def _score(self, case: TasteCase, query: TasteQuery) -> RetrievedTasteCase:
        matched: list[str] = []
        if query.policy == TasteRetrievalPolicy.TOPICAL:
            searchable = " ".join(
                filter(
                    None,
                    [case.context_summary, case.problem_pattern, *case.domain_tags],
                )
            )
        else:
            searchable = " ".join(
                filter(
                    None,
                    [
                        case.context_summary,
                        case.problem_pattern,
                        case.evidence_state,
                        case.decision_principle,
                        case.why_preferred,
                        case.preferred_action,
                        *case.candidate_actions,
                    ],
                )
            )
        score = lexical_similarity(query.text, searchable)
        if score > 0:
            matched.append("text")

        if query.stage and query.stage.casefold() == case.stage.casefold():
            score += 0.8 if query.policy == TasteRetrievalPolicy.STAGE_CONDITIONED else 0.2
            matched.append("stage")
        if query.candidate_action_types and case.preferred_action in query.candidate_action_types:
            score += 0.5
            matched.append("preferred_action")
        requested_domains = {item.casefold() for item in query.domain_tags}
        case_domains = {item.casefold() for item in case.domain_tags}
        if requested_domains & case_domains:
            score += 0.3
            matched.append("domain_tags")
        if query.venue and query.venue.casefold() in {item.casefold() for item in case.venue_tags}:
            score += 0.25
            matched.append("venue")
        if (
            query.policy == TasteRetrievalPolicy.RHETORICAL_ROLE
            and query.rhetorical_role
            and case.rhetorical_role
            and query.rhetorical_role.casefold() == case.rhetorical_role.casefold()
        ):
            score += 1.0
            matched.append("rhetorical_role")
        if (
            query.policy == TasteRetrievalPolicy.VISUAL_ROLE
            and query.figure_role
            and case.figure_role
            and query.figure_role.casefold() == case.figure_role.casefold()
        ):
            score += 1.0
            matched.append("figure_role")
        return RetrievedTasteCase(case=case, score=round(score, 6), matched_fields=matched)


def lexical_similarity(left: str, right: str) -> float:
    """Symmetric token overlap; deterministic fallback until embedding retrieval."""

    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]

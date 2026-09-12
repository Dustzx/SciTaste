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
    WRITING_DECISION = "writing_decision"
    VISUAL_ROLE = "visual_role"


class TasteDomainRelation(StrEnum):
    """Experimental corpus partition applied before any retrieval scoring."""

    ANY = "any"
    MATCHED = "matched"
    MISMATCHED = "mismatched"


class TasteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    policy: TasteRetrievalPolicy = TasteRetrievalPolicy.STAGE_CONDITIONED
    stage: str | None = None
    candidate_action_types: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    venue: str | None = None
    writing_level: str | None = None
    section_type: str | None = None
    rhetorical_role: str | None = None
    claim_strength: str | None = None
    citation_density: str | None = None
    writing_taste_dimensions: list[str] = Field(default_factory=list)
    figure_role: str | None = None


class RetrievedTasteCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case: TasteCase
    score: float = Field(ge=0.0)
    matched_fields: list[str] = Field(default_factory=list)
    selection_role: str | None = None
    applicability_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    selection_fact_ids: list[str] = Field(default_factory=list)
    deliberation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TasteRetriever:
    def __init__(
        self,
        library: TasteLibrary,
        *,
        domain_relation: TasteDomainRelation = TasteDomainRelation.ANY,
    ) -> None:
        self.library = library
        self.domain_relation = domain_relation

    def retrieve(self, query: TasteQuery, *, limit: int = 5) -> list[RetrievedTasteCase]:
        return retrieve_taste_cases(
            self.library.all(),
            query,
            domain_relation=self.domain_relation,
            limit=limit,
        )


def retrieve_taste_cases(
    cases: list[TasteCase],
    query: TasteQuery,
    *,
    domain_relation: TasteDomainRelation = TasteDomainRelation.ANY,
    limit: int = 5,
) -> list[RetrievedTasteCase]:
    """Run the production retrieval policy over an in-memory, immutable case set."""

    if limit < 1:
        raise ValueError("Taste retrieval limit must be positive")
    eligible = [case for case in cases if case.retrieval_eligible]
    selected = _filter_domain_relation(eligible, query, domain_relation=domain_relation)
    if query.policy == TasteRetrievalPolicy.RHETORICAL_ROLE and query.rhetorical_role:
        selected = [
            case
            for case in selected
            if case.rhetorical_role
            and case.rhetorical_role.casefold() == query.rhetorical_role.casefold()
        ]
    if query.policy == TasteRetrievalPolicy.WRITING_DECISION:
        selected = [case for case in selected if case.writing_level or case.rhetorical_role]
    if query.policy == TasteRetrievalPolicy.VISUAL_ROLE and query.figure_role:
        selected = [
            case
            for case in selected
            if case.figure_role and case.figure_role.casefold() == query.figure_role.casefold()
        ]
    results = [_score(case, query) for case in selected]
    positive = [result for result in results if result.score > 0]
    return sorted(positive, key=lambda result: (-result.score, result.case.case_id))[:limit]


def _filter_domain_relation(
    cases: list[TasteCase],
    query: TasteQuery,
    *,
    domain_relation: TasteDomainRelation,
) -> list[TasteCase]:
    if domain_relation is TasteDomainRelation.ANY:
        return cases
    requested = {item.casefold() for item in query.domain_tags if item.strip()}
    if not requested:
        raise ValueError("matched or mismatched Taste retrieval requires query domains")
    selected: list[TasteCase] = []
    for case in cases:
        observed = {item.casefold() for item in case.domain_tags if item.strip()}
        if not observed:
            continue
        overlaps = bool(requested & observed)
        if (domain_relation is TasteDomainRelation.MATCHED and overlaps) or (
            domain_relation is TasteDomainRelation.MISMATCHED and not overlaps
        ):
            selected.append(case)
    return selected


def _score(case: TasteCase, query: TasteQuery) -> RetrievedTasteCase:
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
                    case.writing_level,
                    case.section_type,
                    case.rhetorical_role,
                    case.transition_pattern,
                    case.claim_strength,
                    case.citation_density,
                    *case.writing_taste_dimensions,
                    *case.style_tags,
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
        query.writing_level
        and case.writing_level
        and query.writing_level.casefold() == case.writing_level.casefold()
    ):
        score += 0.4
        matched.append("writing_level")
    if (
        query.section_type
        and case.section_type
        and query.section_type.casefold() == case.section_type.casefold()
    ):
        score += 0.45
        matched.append("section_type")
    if (
        query.policy == TasteRetrievalPolicy.RHETORICAL_ROLE
        and query.rhetorical_role
        and case.rhetorical_role
        and query.rhetorical_role.casefold() == case.rhetorical_role.casefold()
    ):
        score += 1.0
        matched.append("rhetorical_role")
    if (
        query.policy == TasteRetrievalPolicy.WRITING_DECISION
        and query.rhetorical_role
        and case.rhetorical_role
        and query.rhetorical_role.casefold() == case.rhetorical_role.casefold()
    ):
        score += 1.0
        matched.append("rhetorical_role")
    if (
        query.claim_strength
        and case.claim_strength
        and query.claim_strength.casefold() == case.claim_strength.casefold()
    ):
        score += 0.3
        matched.append("claim_strength")
    if (
        query.citation_density
        and case.citation_density
        and query.citation_density.casefold() == case.citation_density.casefold()
    ):
        score += 0.2
        matched.append("citation_density")
    requested_dimensions = {item.casefold() for item in query.writing_taste_dimensions}
    case_dimensions = {item.casefold() for item in case.writing_taste_dimensions}
    if requested_dimensions & case_dimensions:
        score += 0.35
        matched.append("writing_taste_dimensions")
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

"""Decision-gap-driven discovery of candidate Scientific Taste references.

Discovery is intentionally weaker than source qualification.  This module can
plan broad searches and freeze a diverse metadata-only audit cohort, but it
cannot call a search service, read source bodies, or label any source as high
quality.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, model_validator

from scitaste.taste.intrinsic import TasteTask

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_MAX_RUN_BYTES = 8 * 1024 * 1024
_LEXICAL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "versus",
    "with",
}

REFERENCE_MINING_NODE = "reference-mining"


class ReferenceQueryFamily(StrEnum):
    """Complementary search directions needed before source-quality review."""

    DIRECT_DECISION = "direct-decision"
    ALTERNATIVE_OR_COMPARATOR = "alternative-or-comparator"
    NEGATIVE_OR_NULL = "negative-or-null"
    FAILURE_OR_LIMITATION = "failure-or-limitation"
    REPLICATION_OR_REAPPRAISAL = "replication-or-reappraisal"
    CROSS_DOMAIN_TRANSFER = "cross-domain-transfer"


class ReferenceDecisionPattern(StrEnum):
    """Scientific judgments a source may expose according to metadata."""

    PROBLEM_SIGNIFICANCE = "problem-significance"
    HYPOTHESIS_DISCRIMINATION = "hypothesis-discrimination"
    DIAGNOSTIC_EXPERIMENT = "diagnostic-experiment"
    CONFOUND_CONTROL = "confound-control"
    PIVOT_OR_STOP = "pivot-or-stop"
    CLAIM_CALIBRATION = "claim-calibration"


class ReferenceEvidenceRole(StrEnum):
    """Contrastive roles sought in a broad candidate pool."""

    SUPPORT = "support"
    CHALLENGE = "challenge"
    BOUNDARY = "boundary"
    ALTERNATIVE = "alternative"
    REPLICATION = "replication"


class ReferenceRightsStatus(StrEnum):
    COMPATIBLE_METADATA_ONLY = "compatible-metadata-only"
    REVIEW_REQUIRED = "review-required"
    BLOCKED = "blocked"


class ReferenceIsolationStatus(StrEnum):
    ELIGIBLE_CANDIDATE = "eligible-candidate"
    HELD_OUT = "held-out"
    SELF_DEVELOPMENT = "self-development"
    UNKNOWN = "unknown"


class ReferenceMiningStopReason(StrEnum):
    COVERAGE_AND_SATURATION = "coverage-and-saturation"
    BATCH_BUDGET_EXHAUSTED = "batch-budget-exhausted"
    SEARCH_INCOMPLETE = "search-incomplete"


class ReferenceMetadataIdentityStatus(StrEnum):
    """Whether independent indexes agree on the identity-bearing title metadata."""

    SINGLE_INDEX_UNVERIFIED = "single-index-unverified"
    CROSS_INDEX_CORROBORATED = "cross-index-corroborated"
    CROSS_INDEX_CONFLICT = "cross-index-conflict"


class ReferenceMetadataRelevanceStatus(StrEnum):
    """Deterministic metadata-only admission before source-quality review."""

    ELIGIBLE = "eligible"
    ADMINISTRATIVE_RECORD = "administrative-record"
    INSUFFICIENT_ANCHOR_EVIDENCE = "insufficient-anchor-evidence"


class ReferenceMiningNeed(BaseModel):
    """Closed scientific need from which a bounded search may be proposed."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    mining_id: str = Field(pattern=_ID)
    stage: TasteTask
    decision_question: str = Field(min_length=1, max_length=4_000)
    candidate_actions: tuple[str, ...] = Field(min_length=2, max_length=20)
    evidence_gap_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    required_decision_patterns: tuple[ReferenceDecisionPattern, ...] = Field(
        min_length=2,
        max_length=len(ReferenceDecisionPattern),
    )
    required_evidence_roles: tuple[ReferenceEvidenceRole, ...] = Field(
        min_length=3,
        max_length=len(ReferenceEvidenceRole),
    )
    required_domain_facets: tuple[str, ...] = Field(min_length=1, max_length=20)
    max_query_count: int = Field(ge=len(ReferenceQueryFamily), le=60)
    max_batches: int = Field(ge=3, le=30)
    saturation_window: int = Field(ge=2, le=5)
    min_distinct_source_groups: int = Field(ge=2, le=30)
    max_per_source_group: int = Field(ge=1, le=5)
    max_cohort_size: int = Field(ge=2, le=100)
    metadata_relevance_anchor_terms: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=100,
    )
    min_metadata_anchor_matches: int = Field(default=0, ge=0, le=20)
    max_query_terms: int = Field(default=60, ge=3, le=100)
    source_content_available: Literal[False] = False
    prestige_is_quality_signal: Literal[False] = False

    @model_validator(mode="after")
    def need_is_closed_and_contrastive(self) -> ReferenceMiningNeed:
        collections = (
            self.candidate_actions,
            self.evidence_gap_ids,
            self.required_decision_patterns,
            self.required_evidence_roles,
            self.required_domain_facets,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("reference-mining need fields must contain unique values")
        contrastive = {
            ReferenceEvidenceRole.CHALLENGE,
            ReferenceEvidenceRole.BOUNDARY,
            ReferenceEvidenceRole.ALTERNATIVE,
        }
        if not contrastive <= set(self.required_evidence_roles):
            raise ValueError(
                "reference mining must require challenge, boundary, and alternative roles"
            )
        if self.saturation_window >= self.max_batches:
            raise ValueError("reference-mining saturation window must be smaller than batch budget")
        if self.min_distinct_source_groups > self.max_cohort_size:
            raise ValueError("source-group floor cannot exceed the audit-cohort ceiling")
        normalized_anchors = [
            " ".join(term.casefold().split()) for term in self.metadata_relevance_anchor_terms
        ]
        if any(not term for term in normalized_anchors) or len(normalized_anchors) != len(
            set(normalized_anchors)
        ):
            raise ValueError("reference-mining metadata anchors must be nonempty and unique")
        if self.min_metadata_anchor_matches > len(normalized_anchors):
            raise ValueError("reference-mining metadata anchor floor exceeds its inventory")
        return self

    @property
    def need_sha256(self) -> str:
        if self.schema_version == "1.0":
            return _semantic_sha256(
                self,
                exclude={
                    "max_query_terms",
                    "metadata_relevance_anchor_terms",
                    "min_metadata_anchor_matches",
                    "need_sha256",
                },
            )
        return _semantic_sha256(self, exclude={"need_sha256"})


class ReferenceSearchQuery(BaseModel):
    """One unexecuted query with declared scientific coverage targets."""

    model_config = _CONFIG

    query_id: str = Field(pattern=_ID)
    family: ReferenceQueryFamily
    query_text: str = Field(min_length=3, max_length=2_000)
    targeted_decision_patterns: tuple[ReferenceDecisionPattern, ...] = Field(
        min_length=1,
        max_length=len(ReferenceDecisionPattern),
    )
    targeted_evidence_roles: tuple[ReferenceEvidenceRole, ...] = Field(
        min_length=1,
        max_length=len(ReferenceEvidenceRole),
    )
    targeted_domain_facets: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def query_targets_are_unique(self) -> ReferenceSearchQuery:
        targets = (
            self.targeted_decision_patterns,
            self.targeted_evidence_roles,
            self.targeted_domain_facets,
        )
        if any(len(values) != len(set(values)) for values in targets):
            raise ValueError("reference-search query targets must be unique")
        return self


class ReferenceMiningProposal(BaseModel):
    """Untrusted query plan; a deterministic controller retains execution authority."""

    model_config = _CONFIG

    mining_id: str = Field(pattern=_ID)
    queries: tuple[ReferenceSearchQuery, ...] = Field(
        min_length=len(ReferenceQueryFamily),
        max_length=60,
    )
    rationale: str = Field(min_length=1, max_length=4_000)
    requests_tool_execution: Literal[False] = False
    claims_source_quality: Literal[False] = False

    @model_validator(mode="after")
    def query_identities_are_unique(self) -> ReferenceMiningProposal:
        query_ids = [query.query_id for query in self.queries]
        normalized_text = [" ".join(query.query_text.casefold().split()) for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("reference-search query identities must be unique")
        if len(normalized_text) != len(set(normalized_text)):
            raise ValueError("reference-search query texts must be unique")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        return _semantic_sha256(self, exclude={"proposal_sha256"})


class VerifiedReferenceMining(BaseModel):
    """An accepted live query proposal bound to its immutable project ledger."""

    model_config = _CONFIG

    invocation_id: str = Field(pattern=_ID)
    backend: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    ledger_locator: str = Field(min_length=1, max_length=2_000)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input: ReferenceMiningNeed
    proposal: ReferenceMiningProposal

    @model_validator(mode="after")
    def proposal_matches_need(self) -> VerifiedReferenceMining:
        findings = validate_reference_mining_proposal(self.input, self.proposal)
        if findings:
            raise ValueError("; ".join(findings))
        return self


class ReferenceCandidateMetadata(BaseModel):
    """Metadata-only search result; all semantic labels remain hypotheses."""

    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    title: str = Field(min_length=1, max_length=1_000)
    locator: HttpUrl
    discovery_query_ids: tuple[str, ...] = Field(min_length=1, max_length=60)
    hypothesized_decision_patterns: tuple[ReferenceDecisionPattern, ...] = Field(
        min_length=1,
        max_length=len(ReferenceDecisionPattern),
    )
    hypothesized_evidence_roles: tuple[ReferenceEvidenceRole, ...] = Field(
        min_length=1,
        max_length=len(ReferenceEvidenceRole),
    )
    domain_facets: tuple[str, ...] = Field(min_length=1, max_length=20)
    rights_status: ReferenceRightsStatus
    isolation_status: ReferenceIsolationStatus
    venue: str | None = Field(default=None, max_length=300)
    citation_count: int | None = Field(default=None, ge=0)
    publication_year: int | None = Field(default=None, ge=1600, le=2200)
    metadata_provider_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    metadata_identity_status: ReferenceMetadataIdentityStatus = (
        ReferenceMetadataIdentityStatus.SINGLE_INDEX_UNVERIFIED
    )
    metadata_title_variants: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    metadata_relevance_status: ReferenceMetadataRelevanceStatus = (
        ReferenceMetadataRelevanceStatus.ELIGIBLE
    )
    metadata_relevance_anchor_matches: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=100,
    )
    metadata_grounded_domain_facets: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=20,
    )
    best_result_rank: int | None = Field(default=None, ge=1, le=10_000)
    retrieval_observation_count: int = Field(default=0, ge=0, le=10_000)
    source_body_read: Literal[False] = False
    quality_assessed: Literal[False] = False

    @model_validator(mode="after")
    def candidate_metadata_is_unique(self) -> ReferenceCandidateMetadata:
        values = (
            self.discovery_query_ids,
            self.hypothesized_decision_patterns,
            self.hypothesized_evidence_roles,
            self.domain_facets,
            self.metadata_provider_ids,
            self.metadata_title_variants,
            self.metadata_relevance_anchor_matches,
            self.metadata_grounded_domain_facets,
        )
        if any(len(items) != len(set(items)) for items in values):
            raise ValueError("reference candidate metadata sets must be unique")
        if (
            self.metadata_identity_status is ReferenceMetadataIdentityStatus.CROSS_INDEX_CONFLICT
            and len(self.metadata_provider_ids) < 2
        ):
            raise ValueError("cross-index metadata conflict requires at least two providers")
        if self.retrieval_observation_count and self.best_result_rank is None:
            raise ValueError("retrieval observations require a best result rank")
        return self


class ReferenceMiningBatch(BaseModel):
    """One completed metadata-only search batch in a fixed sequence."""

    model_config = _CONFIG

    batch_index: int = Field(ge=1, le=30)
    query_ids: tuple[str, ...] = Field(min_length=1, max_length=60)
    candidates: tuple[ReferenceCandidateMetadata, ...] = Field(
        default_factory=tuple, max_length=500
    )
    duplicate_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    search_completed: Literal[True] = True
    source_content_read: Literal[False] = False

    @model_validator(mode="after")
    def batch_sets_are_unique(self) -> ReferenceMiningBatch:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("new candidate identities must be unique within a batch")
        if len(self.query_ids) != len(set(self.query_ids)):
            raise ValueError("batch query identities must be unique")
        if len(self.duplicate_candidate_ids) != len(set(self.duplicate_candidate_ids)):
            raise ValueError("duplicate candidate identities must be unique")
        if set(candidate_ids) & set(self.duplicate_candidate_ids):
            raise ValueError("a candidate cannot be both new and duplicate in one batch")
        return self


class ReferenceMiningRun(BaseModel):
    """Closed no-read input used to freeze a downstream quality-audit cohort."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    need: ReferenceMiningNeed
    proposal: ReferenceMiningProposal
    batches: tuple[ReferenceMiningBatch, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def run_is_consistent(self) -> ReferenceMiningRun:
        findings = validate_reference_mining_proposal(self.need, self.proposal)
        if findings:
            raise ValueError("; ".join(findings))
        if len(self.batches) > self.need.max_batches:
            raise ValueError("reference search exceeded its batch budget")
        if [batch.batch_index for batch in self.batches] != list(range(1, len(self.batches) + 1)):
            raise ValueError("reference-search batch indices must be contiguous from one")
        query_ids = {query.query_id for query in self.proposal.queries}
        observed_candidates: dict[str, ReferenceCandidateMetadata] = {}
        observed_locators: set[str] = set()
        for batch in self.batches:
            if not set(batch.query_ids) <= query_ids:
                raise ValueError("reference-search batch names an unknown query")
            if not set(batch.duplicate_candidate_ids) <= set(observed_candidates):
                raise ValueError("duplicate candidates must have appeared in an earlier batch")
            for candidate in batch.candidates:
                if candidate.candidate_id in observed_candidates:
                    raise ValueError("candidate identity was reintroduced as a new result")
                if not set(candidate.discovery_query_ids) <= set(batch.query_ids):
                    raise ValueError("candidate discovery query is outside its batch")
                locator = str(candidate.locator)
                if locator in observed_locators:
                    raise ValueError("the same source locator has multiple candidate identities")
                observed_candidates[candidate.candidate_id] = candidate
                observed_locators.add(locator)
        return self

    @computed_field
    @property
    def run_sha256(self) -> str:
        if self.schema_version == "1.0":
            payload = self.model_dump(mode="json", exclude={"run_sha256"})
            for field in (
                "max_query_terms",
                "metadata_relevance_anchor_terms",
                "min_metadata_anchor_matches",
            ):
                payload["need"].pop(field, None)
            legacy_only_fields = {
                "best_result_rank",
                "metadata_identity_status",
                "metadata_provider_ids",
                "metadata_relevance_anchor_matches",
                "metadata_relevance_status",
                "metadata_title_variants",
                "retrieval_observation_count",
            }
            legacy_only_fields.add("metadata_grounded_domain_facets")
            for batch in payload["batches"]:
                for candidate in batch["candidates"]:
                    for field in legacy_only_fields:
                        candidate.pop(field, None)
            return _mapping_sha256(payload)
        if self.schema_version == "1.1":
            payload = self.model_dump(mode="json", exclude={"run_sha256"})
            for batch in payload["batches"]:
                for candidate in batch["candidates"]:
                    candidate.pop("metadata_grounded_domain_facets", None)
            return _mapping_sha256(payload)
        return _semantic_sha256(self, exclude={"run_sha256"})


class ReferenceMiningBatchProgress(BaseModel):
    model_config = _CONFIG

    batch_index: int
    new_candidate_count: int
    new_eligible_source_groups: tuple[str, ...]
    new_required_decision_patterns: tuple[ReferenceDecisionPattern, ...]
    new_required_evidence_roles: tuple[ReferenceEvidenceRole, ...]
    new_required_domain_facets: tuple[str, ...]
    adds_scientific_coverage: bool
    saturation_streak: int


class ReferenceMiningReport(BaseModel):
    """Content-free receipt for a metadata cohort awaiting quality screening."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    mining_id: str = Field(pattern=_ID)
    need_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stopping_reason: ReferenceMiningStopReason
    evaluated_batch_count: int = Field(ge=1, le=30)
    search_saturated: bool
    selected_candidate_ids: tuple[str, ...]
    selected_source_group_ids: tuple[str, ...]
    covered_decision_patterns: tuple[ReferenceDecisionPattern, ...]
    covered_evidence_roles: tuple[ReferenceEvidenceRole, ...]
    covered_domain_facets: tuple[str, ...]
    missing_decision_patterns: tuple[ReferenceDecisionPattern, ...]
    missing_evidence_roles: tuple[ReferenceEvidenceRole, ...]
    missing_domain_facets: tuple[str, ...]
    covered_query_families: tuple[ReferenceQueryFamily, ...] = Field(default_factory=tuple)
    missing_query_families: tuple[ReferenceQueryFamily, ...] = Field(default_factory=tuple)
    cohort_ready_for_reference_quality: bool
    batch_progress: tuple[ReferenceMiningBatchProgress, ...]
    selection_uses_prestige_signals: Literal[False] = False
    source_content_read: Literal[False] = False
    source_quality_assessed: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_content_access: Literal[False] = False
    authorizes_reference_quality: Literal[False] = False
    authorizes_model_or_gpu_use: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @computed_field
    @property
    def report_sha256(self) -> str:
        if self.schema_version == "1.0":
            return _semantic_sha256(
                self,
                exclude={
                    "covered_query_families",
                    "missing_query_families",
                    "report_sha256",
                },
            )
        return _semantic_sha256(self, exclude={"report_sha256"})


def validate_reference_mining_proposal(
    need: ReferenceMiningNeed,
    proposal: ReferenceMiningProposal,
) -> tuple[str, ...]:
    """Check coverage and reject plans that use prestige as a quality proxy."""

    findings: list[str] = []
    if proposal.mining_id != need.mining_id:
        findings.append("reference-mining proposal changed the mining identity")
    if len(proposal.queries) > need.max_query_count:
        findings.append("reference-mining proposal exceeds the query budget")
    families = {query.family for query in proposal.queries}
    if families != set(ReferenceQueryFamily):
        findings.append("reference-mining proposal must cover every query family")
    patterns = {item for query in proposal.queries for item in query.targeted_decision_patterns}
    roles = {item for query in proposal.queries for item in query.targeted_evidence_roles}
    domains = {item for query in proposal.queries for item in query.targeted_domain_facets}
    if not set(need.required_decision_patterns) <= patterns:
        findings.append("reference-mining proposal omits a required decision pattern")
    if not set(need.required_evidence_roles) <= roles:
        findings.append("reference-mining proposal omits a required evidence role")
    if not set(need.required_domain_facets) <= domains:
        findings.append("reference-mining proposal omits a required domain facet")
    allowed_patterns = set(need.required_decision_patterns)
    allowed_roles = set(need.required_evidence_roles)
    allowed_domains = set(need.required_domain_facets)
    for query in proposal.queries:
        if not set(query.targeted_decision_patterns) <= allowed_patterns:
            findings.append(f"query {query.query_id!r} invents a decision pattern")
        if not set(query.targeted_evidence_roles) <= allowed_roles:
            findings.append(f"query {query.query_id!r} invents an evidence role")
        if not set(query.targeted_domain_facets) <= allowed_domains:
            findings.append(f"query {query.query_id!r} invents a domain facet")
        lowered = " ".join(query.query_text.casefold().split())
        prestige_phrases = (
            "highly cited",
            "citation count",
            "h-index",
            "famous author",
            "top venue",
        )
        if any(phrase in lowered for phrase in prestige_phrases):
            findings.append(f"query {query.query_id!r} ranks by prestige")
        if len(re.findall(r"[a-z0-9]+", lowered)) > need.max_query_terms:
            findings.append(f"query {query.query_id!r} exceeds the executable term budget")
        anchor_matches = {
            anchor
            for anchor in need.metadata_relevance_anchor_terms
            if _normalized_phrase_present(anchor, lowered)
        }
        if len(anchor_matches) < need.min_metadata_anchor_matches:
            findings.append(f"query {query.query_id!r} lacks registered metadata anchors")
    return tuple(sorted(set(findings)))


def compile_reference_mining_report(run: ReferenceMiningRun) -> ReferenceMiningReport:
    """Freeze a diverse cohort by marginal decision coverage, then source identity."""

    required_patterns = set(run.need.required_decision_patterns)
    required_roles = set(run.need.required_evidence_roles)
    required_domains = set(run.need.required_domain_facets)
    available_patterns: set[ReferenceDecisionPattern] = set()
    available_roles: set[ReferenceEvidenceRole] = set()
    available_domains: set[str] = set()
    available_families: set[ReferenceQueryFamily] = set()
    eligible_groups: set[str] = set()
    eligible_candidates: list[ReferenceCandidateMetadata] = []
    query_families = {query.query_id: query.family for query in run.proposal.queries}
    required_families = set(ReferenceQueryFamily) if run.need.schema_version == "1.1" else set()
    progress: list[ReferenceMiningBatchProgress] = []
    saturation_streak = 0
    terminal_batch: int | None = None

    for batch in run.batches:
        old_groups = set(eligible_groups)
        old_patterns = set(available_patterns)
        old_roles = set(available_roles)
        old_domains = set(available_domains)
        old_families = set(available_families)
        for candidate in batch.candidates:
            if not _candidate_is_eligible(candidate):
                continue
            eligible_candidates.append(candidate)
            eligible_groups.add(candidate.source_group_id)
            available_patterns.update(
                set(candidate.hypothesized_decision_patterns) & required_patterns
            )
            available_roles.update(set(candidate.hypothesized_evidence_roles) & required_roles)
            available_domains.update(_candidate_domain_facets(candidate, run) & required_domains)
            available_families.update(
                query_families[query_id]
                for query_id in candidate.discovery_query_ids
                if query_id in query_families
            )
        new_groups = eligible_groups - old_groups
        new_patterns = available_patterns - old_patterns
        new_roles = available_roles - old_roles
        new_domains = available_domains - old_domains
        new_families = available_families - old_families
        # An open scholarly index can keep yielding valid new papers indefinitely.
        # The registered stopping target is therefore scientific coverage, not an
        # unprovable claim that the literature itself has been exhausted.  Source
        # diversity contributes only until the declared group floor is reached;
        # later batches must still run for the configured saturation window.
        adds_required_group_coverage = bool(new_groups) and (
            len(old_groups) < run.need.min_distinct_source_groups
        )
        adds_coverage = bool(
            adds_required_group_coverage or new_patterns or new_roles or new_domains or new_families
        )
        saturation_streak = 0 if adds_coverage else saturation_streak + 1
        progress.append(
            ReferenceMiningBatchProgress(
                batch_index=batch.batch_index,
                new_candidate_count=len(batch.candidates),
                new_eligible_source_groups=tuple(sorted(new_groups)),
                new_required_decision_patterns=_enum_order(new_patterns, ReferenceDecisionPattern),
                new_required_evidence_roles=_enum_order(new_roles, ReferenceEvidenceRole),
                new_required_domain_facets=tuple(sorted(new_domains)),
                adds_scientific_coverage=adds_coverage,
                saturation_streak=saturation_streak,
            )
        )
        coverage_available = (
            required_patterns <= available_patterns
            and required_roles <= available_roles
            and required_domains <= available_domains
            and len(eligible_groups) >= run.need.min_distinct_source_groups
            and required_families <= available_families
        )
        if coverage_available and saturation_streak >= run.need.saturation_window:
            terminal_batch = batch.batch_index
            break

    search_saturated = terminal_batch is not None
    if search_saturated:
        stopping_reason = ReferenceMiningStopReason.COVERAGE_AND_SATURATION
    elif len(run.batches) == run.need.max_batches:
        stopping_reason = ReferenceMiningStopReason.BATCH_BUDGET_EXHAUSTED
    else:
        stopping_reason = ReferenceMiningStopReason.SEARCH_INCOMPLETE

    selected = _select_coverage_cohort(
        eligible_candidates,
        run.need,
        run.proposal,
        use_grounded_domains=run.schema_version == "1.2",
    )
    covered_patterns = {
        item for candidate in selected for item in candidate.hypothesized_decision_patterns
    } & required_patterns
    covered_roles = {
        item for candidate in selected for item in candidate.hypothesized_evidence_roles
    } & required_roles
    covered_domains = {
        item for candidate in selected for item in _candidate_domain_facets(candidate, run)
    } & required_domains
    selected_groups = {candidate.source_group_id for candidate in selected}
    covered_families = {
        query_families[query_id]
        for candidate in selected
        for query_id in candidate.discovery_query_ids
        if query_id in query_families
    }
    ready = (
        search_saturated
        and required_patterns <= covered_patterns
        and required_roles <= covered_roles
        and required_domains <= covered_domains
        and len(selected_groups) >= run.need.min_distinct_source_groups
        and required_families <= covered_families
    )
    return ReferenceMiningReport(
        schema_version=run.schema_version,
        mining_id=run.need.mining_id,
        need_sha256=run.need.need_sha256,
        proposal_sha256=run.proposal.proposal_sha256,
        run_sha256=run.run_sha256,
        stopping_reason=stopping_reason,
        evaluated_batch_count=len(progress),
        search_saturated=search_saturated,
        selected_candidate_ids=tuple(candidate.candidate_id for candidate in selected),
        selected_source_group_ids=tuple(sorted(selected_groups)),
        covered_decision_patterns=_enum_order(covered_patterns, ReferenceDecisionPattern),
        covered_evidence_roles=_enum_order(covered_roles, ReferenceEvidenceRole),
        covered_domain_facets=tuple(sorted(covered_domains)),
        missing_decision_patterns=_enum_order(
            required_patterns - covered_patterns, ReferenceDecisionPattern
        ),
        missing_evidence_roles=_enum_order(required_roles - covered_roles, ReferenceEvidenceRole),
        missing_domain_facets=tuple(sorted(required_domains - covered_domains)),
        covered_query_families=_enum_order(covered_families, ReferenceQueryFamily),
        missing_query_families=_enum_order(
            required_families - covered_families,
            ReferenceQueryFamily,
        ),
        cohort_ready_for_reference_quality=ready,
        batch_progress=tuple(progress),
    )


def load_reference_mining_run(path: str | Path) -> ReferenceMiningRun:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("reference-mining run must not be a symlink")
    source = requested.resolve(strict=True)
    if not source.is_file() or not 1 <= source.stat().st_size <= _MAX_RUN_BYTES:
        raise ValueError("reference-mining run must be a bounded regular file")
    raw = source.read_bytes()
    try:
        if source.suffix.casefold() == ".json":
            value = json.loads(raw)
        else:
            value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("reference-mining run must be UTF-8 JSON or YAML") from exc
    if not isinstance(value, dict):
        raise ValueError("reference-mining run must contain a mapping")
    return ReferenceMiningRun.model_validate(value)


def save_reference_mining_report(report: ReferenceMiningReport, path: str | Path) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _candidate_is_eligible(candidate: ReferenceCandidateMetadata) -> bool:
    return (
        candidate.rights_status is ReferenceRightsStatus.COMPATIBLE_METADATA_ONLY
        and candidate.isolation_status is ReferenceIsolationStatus.ELIGIBLE_CANDIDATE
        and candidate.metadata_identity_status
        is not ReferenceMetadataIdentityStatus.CROSS_INDEX_CONFLICT
        and candidate.metadata_relevance_status is ReferenceMetadataRelevanceStatus.ELIGIBLE
    )


def _candidate_domain_facets(
    candidate: ReferenceCandidateMetadata,
    run: ReferenceMiningRun,
) -> set[str]:
    if run.schema_version == "1.2":
        return set(candidate.metadata_grounded_domain_facets)
    return set(candidate.domain_facets)


def _select_coverage_cohort(
    candidates: list[ReferenceCandidateMetadata],
    need: ReferenceMiningNeed,
    proposal: ReferenceMiningProposal,
    *,
    use_grounded_domains: bool,
) -> list[ReferenceCandidateMetadata]:
    remaining = list(candidates)
    selected: list[ReferenceCandidateMetadata] = []
    selected_title_fingerprints: set[str] = set()
    group_counts: dict[str, int] = {}
    patterns: set[ReferenceDecisionPattern] = set()
    roles: set[ReferenceEvidenceRole] = set()
    domains: set[str] = set()
    families: set[ReferenceQueryFamily] = set()
    required_patterns = set(need.required_decision_patterns)
    required_roles = set(need.required_evidence_roles)
    required_domains = set(need.required_domain_facets)
    queries = {query.query_id: query for query in proposal.queries}

    while remaining and len(selected) < need.max_cohort_size:
        admissible = [
            candidate
            for candidate in remaining
            if group_counts.get(candidate.source_group_id, 0) < need.max_per_source_group
            and _title_fingerprint(candidate.title) not in selected_title_fingerprints
        ]
        if not admissible:
            break

        def priority(
            candidate: ReferenceCandidateMetadata,
        ) -> tuple[int, int, int, int, int, int, int, int, str]:
            new_coverage = (
                len((set(candidate.hypothesized_decision_patterns) & required_patterns) - patterns)
                + len((set(candidate.hypothesized_evidence_roles) & required_roles) - roles)
                + len(
                    (
                        set(candidate.metadata_grounded_domain_facets)
                        if use_grounded_domains
                        else set(candidate.domain_facets)
                    )
                    & required_domains - domains
                )
            )
            new_group = int(candidate.source_group_id not in group_counts)
            candidate_families = {
                queries[query_id].family
                for query_id in candidate.discovery_query_ids
                if query_id in queries
            }
            new_family_coverage = (
                len(candidate_families - families) if need.schema_version == "1.1" else 0
            )
            matched_queries, best_overlap, total_overlap = _query_title_relevance(
                candidate,
                queries,
            )
            corroborated = int(
                candidate.metadata_identity_status
                is ReferenceMetadataIdentityStatus.CROSS_INDEX_CORROBORATED
            )
            rank = candidate.best_result_rank or 10_001
            stable = hashlib.sha256(candidate.candidate_id.encode()).hexdigest()
            return (
                -new_coverage,
                -new_group,
                -new_family_coverage,
                -corroborated,
                -matched_queries,
                -best_overlap,
                -total_overlap,
                rank,
                stable,
            )

        chosen = min(admissible, key=priority)
        selected.append(chosen)
        selected_title_fingerprints.add(_title_fingerprint(chosen.title))
        remaining.remove(chosen)
        group_counts[chosen.source_group_id] = group_counts.get(chosen.source_group_id, 0) + 1
        patterns.update(set(chosen.hypothesized_decision_patterns) & required_patterns)
        roles.update(set(chosen.hypothesized_evidence_roles) & required_roles)
        domains.update(
            (
                set(chosen.metadata_grounded_domain_facets)
                if use_grounded_domains
                else set(chosen.domain_facets)
            )
            & required_domains
        )
        families.update(
            queries[query_id].family
            for query_id in chosen.discovery_query_ids
            if query_id in queries
        )
    return selected


def _query_title_relevance(
    candidate: ReferenceCandidateMetadata,
    queries: dict[str, ReferenceSearchQuery],
) -> tuple[int, int, int]:
    """Rank metadata evidence without venue, citation, author, or outcome signals."""

    title_tokens = _lexical_tokens(candidate.title)
    overlaps = [
        len(title_tokens & _lexical_tokens(queries[query_id].query_text))
        for query_id in candidate.discovery_query_ids
        if query_id in queries
    ]
    return (
        sum(value > 0 for value in overlaps),
        max(overlaps, default=0),
        sum(overlaps),
    )


def _lexical_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3 and token not in _LEXICAL_STOPWORDS
    }


def _title_fingerprint(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _normalized_phrase_present(term: str, value: str) -> bool:
    normalized_term = " ".join(re.findall(r"[a-z0-9]+", term.casefold()))
    normalized_value = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
    return bool(normalized_term) and f" {normalized_term} " in f" {normalized_value} "


def _enum_order(values: set, enum_type: type[StrEnum]) -> tuple:
    return tuple(item for item in enum_type if item in values)


def _semantic_sha256(model: BaseModel, *, exclude: set[str]) -> str:
    payload = model.model_dump(mode="json", exclude=exclude)
    return _mapping_sha256(payload)


def _mapping_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "REFERENCE_MINING_NODE",
    "ReferenceCandidateMetadata",
    "ReferenceDecisionPattern",
    "ReferenceEvidenceRole",
    "ReferenceIsolationStatus",
    "ReferenceMetadataIdentityStatus",
    "ReferenceMetadataRelevanceStatus",
    "ReferenceMiningBatch",
    "ReferenceMiningBatchProgress",
    "ReferenceMiningNeed",
    "ReferenceMiningProposal",
    "ReferenceMiningReport",
    "ReferenceMiningRun",
    "ReferenceMiningStopReason",
    "ReferenceQueryFamily",
    "ReferenceRightsStatus",
    "ReferenceSearchQuery",
    "VerifiedReferenceMining",
    "compile_reference_mining_report",
    "load_reference_mining_run",
    "save_reference_mining_report",
    "validate_reference_mining_proposal",
]

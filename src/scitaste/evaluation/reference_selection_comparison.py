"""Freeze the H0 content-grounded versus prestige-only source-selection contrast."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.source_admission import (
    SourceAdmissionReport,
    SourceAdmissionVerdict,
)
from scitaste.taste.reference_mining import (
    ReferenceDecisionPattern,
    ReferenceEvidenceRole,
    ReferenceMiningReport,
    ReferenceMiningRun,
    compile_reference_mining_report,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 64 * 1_048_576
_ALGORITHM_ID = "content-gate-vs-age-normalized-citations-matched-v1"


class ReferenceSelectionFileBinding(BaseModel):
    """One project-relative upstream control artifact and its two identities."""

    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=1_000)
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> ReferenceSelectionFileBinding:
        _validate_relative_path(self.locator, "reference-selection evidence")
        return self


class ReferenceSelectionSourceLink(BaseModel):
    """Explicit identity link between one mined candidate and audited source."""

    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)


class ReferenceSelectionDownstreamEnvelope(BaseModel):
    """Shared treatment envelope; only the source-selection rule may differ."""

    model_config = _CONFIG

    held_out_decision_set_sha256: str = Field(pattern=_SHA256)
    representation_protocol_sha256: str = Field(pattern=_SHA256)
    execution_protocol_sha256: str = Field(pattern=_SHA256)
    sources_per_condition: int = Field(ge=2, le=100)
    per_source_context_token_ceiling: int = Field(ge=128, le=1_000_000)
    total_context_token_ceiling: int = Field(ge=256, le=10_000_000)
    same_representation_pipeline: Literal[True] = True
    same_model_prompt_tools_and_budget: Literal[True] = True
    same_held_out_decisions: Literal[True] = True
    condition_blinded_outcomes: Literal[True] = True

    @model_validator(mode="after")
    def token_budget_covers_exact_source_count(self) -> ReferenceSelectionDownstreamEnvelope:
        required = self.sources_per_condition * self.per_source_context_token_ceiling
        if self.total_context_token_ceiling != required:
            raise ValueError("H0 total context budget must equal the exact per-source budget")
        return self


class ReferenceSelectionCandidateRecord(BaseModel):
    """Content-free projection of one member of the complete frozen broad pool."""

    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    source_id: str | None = Field(default=None, pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    decision_patterns: tuple[ReferenceDecisionPattern, ...] = Field(min_length=1)
    evidence_roles: tuple[ReferenceEvidenceRole, ...] = Field(min_length=1)
    domain_facets: tuple[str, ...] = Field(min_length=1, max_length=20)
    balance_pattern: ReferenceDecisionPattern
    balance_role: ReferenceEvidenceRole
    balance_domain: str = Field(min_length=1, max_length=200)
    balance_stratum_id: str = Field(pattern=_ID)
    publication_year: int | None = Field(default=None, ge=1600, le=2200)
    citation_count: int | None = Field(default=None, ge=0)
    audit_binding_verified: bool
    rights_supported: bool
    source_isolation_supported: bool
    downstream_eligible: bool
    content_grounded_admitted: bool

    @model_validator(mode="after")
    def eligibility_is_evidence_derived(self) -> ReferenceSelectionCandidateRecord:
        expected = bool(
            self.source_id is not None
            and self.audit_binding_verified
            and self.rights_supported
            and self.source_isolation_supported
        )
        if self.downstream_eligible != expected:
            raise ValueError("reference-selection downstream eligibility differs from evidence")
        if self.content_grounded_admitted and not self.downstream_eligible:
            raise ValueError("content-grounded admission requires downstream eligibility")
        if self.balance_pattern not in self.decision_patterns:
            raise ValueError("reference-selection balance pattern is absent from the candidate")
        if self.balance_role not in self.evidence_roles:
            raise ValueError("reference-selection balance role is absent from the candidate")
        if self.balance_domain not in self.domain_facets:
            raise ValueError("reference-selection balance domain is absent from the candidate")
        expected_stratum = _stratum_id(
            self.balance_pattern,
            self.balance_role,
            self.balance_domain,
        )
        if self.balance_stratum_id != expected_stratum:
            raise ValueError("reference-selection balance stratum differs")
        return self


class ReferenceSelectionComparisonPlan(BaseModel):
    """Approved-before-selection H0 plan retaining the entire candidate pool."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    comparison_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    mining_id: str = Field(pattern=_ID)
    mining_run: ReferenceSelectionFileBinding
    mining_report: ReferenceSelectionFileBinding
    source_admission_report: ReferenceSelectionFileBinding
    report_output_locator: str = Field(min_length=1, max_length=1_000)
    implementation_sha256: str = Field(pattern=_SHA256)
    algorithm_id: Literal[_ALGORITHM_ID] = _ALGORITHM_ID
    created_at: datetime
    metadata_snapshot_year: int = Field(ge=1900, le=2200)
    minimum_observed_prestige_fraction: float = Field(ge=0.8, le=1.0)
    stable_tie_break_salt_sha256: str = Field(pattern=_SHA256)
    required_decision_patterns: tuple[ReferenceDecisionPattern, ...] = Field(min_length=2)
    required_evidence_roles: tuple[ReferenceEvidenceRole, ...] = Field(min_length=3)
    required_domain_facets: tuple[str, ...] = Field(min_length=1, max_length=20)
    target_source_count: int = Field(ge=2, le=100)
    downstream: ReferenceSelectionDownstreamEnvelope
    candidates: tuple[ReferenceSelectionCandidateRecord, ...] = Field(min_length=2, max_length=100)
    blocker_codes: tuple[str, ...] = ()
    ready_for_owner_approval: bool
    complete_broad_pool_preserved: Literal[True] = True
    quality_arm_prestige_blind: Literal[True] = True
    prestige_arm_quality_blind: Literal[True] = True
    natural_cross_arm_overlap_preserved: Literal[True] = True
    formal_outcomes_consulted: Literal[False] = False
    current_model_or_compute_inventory_consulted: Literal[False] = False
    raw_source_content_read: Literal[False] = False
    selection_performed: Literal[False] = False
    authorizes_selection: Literal[False] = False
    authorizes_source_content_access: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("reference-selection plan timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def pool_and_readiness_are_closed(self) -> ReferenceSelectionComparisonPlan:
        _validate_relative_path(self.report_output_locator, "reference-selection output")
        for values, label in (
            ([item.candidate_id for item in self.candidates], "candidate IDs"),
            (list(self.required_decision_patterns), "required decision patterns"),
            (list(self.required_evidence_roles), "required evidence roles"),
            (list(self.required_domain_facets), "required domain facets"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"reference-selection {label} must be unique")
        if self.target_source_count != self.downstream.sources_per_condition:
            raise ValueError("H0 source count differs from its downstream envelope")
        intrinsic_blockers: set[str] = set()
        content_groups = {
            item.source_group_id for item in self.candidates if item.content_grounded_admitted
        }
        downstream_groups = {
            item.source_group_id for item in self.candidates if item.downstream_eligible
        }
        if len(content_groups) < self.target_source_count:
            intrinsic_blockers.add("insufficient-content-grounded-source-groups")
        if len(downstream_groups) < self.target_source_count:
            intrinsic_blockers.add("insufficient-prestige-source-groups")
        eligible = [item for item in self.candidates if item.downstream_eligible]
        observed_fraction = (
            sum(
                item.citation_count is not None and item.publication_year is not None
                for item in eligible
            )
            / len(eligible)
            if eligible
            else 0.0
        )
        if observed_fraction < self.minimum_observed_prestige_fraction:
            intrinsic_blockers.add("insufficient-observed-prestige-signals")
        if self.created_at.year < self.metadata_snapshot_year:
            intrinsic_blockers.add("metadata-snapshot-year-after-plan")
        if any(
            item.publication_year is not None
            and item.publication_year > self.metadata_snapshot_year
            for item in self.candidates
        ):
            intrinsic_blockers.add("publication-after-metadata-snapshot")
        quality_ids = _select_quality(
            _quality_views(self.candidates),
            target_count=self.target_source_count,
            required_patterns=self.required_decision_patterns,
            required_roles=self.required_evidence_roles,
            required_domains=self.required_domain_facets,
            salt_sha256=self.stable_tie_break_salt_sha256,
        )
        if not _quality_coverage_complete(quality_ids, self):
            intrinsic_blockers.add("quality-arm-coverage-incomplete")
        if not _prestige_strata_feasible(self.candidates, quality_ids):
            intrinsic_blockers.add("prestige-arm-stratum-infeasible")
        if not intrinsic_blockers <= set(self.blocker_codes):
            raise ValueError("reference-selection plan omits an intrinsic blocker")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("reference-selection blockers must be sorted and unique")
        if self.ready_for_owner_approval != (not self.blocker_codes):
            raise ValueError("reference-selection readiness differs from its blockers")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class ReferenceSelectionPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: ReferenceSelectionComparisonPlan


class ReferenceSelectionComparisonApproval(BaseModel):
    """Owner authority for one exact deterministic H0 source selection only."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    comparison_id: str = Field(pattern=_ID)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["h0-deterministic-reference-selection-only"]
    authorizes_deterministic_selection: Literal[True] = True
    authorizes_source_content_access: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("reference-selection approval timestamp must include a timezone")
        return value

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class ReferenceSelectionApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: ReferenceSelectionComparisonApproval


class SelectedReferenceRecord(BaseModel):
    model_config = _CONFIG

    selection_rank: int = Field(gt=0, le=100)
    candidate_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    balance_stratum_id: str = Field(pattern=_ID)
    selection_basis: Literal["content-grounded-admission", "age-normalized-citation-prestige"]
    citation_count: int | None = Field(default=None, ge=0)
    publication_year: int | None = Field(default=None, ge=1600, le=2200)


class ReferenceSelectionStratumResult(BaseModel):
    model_config = _CONFIG

    balance_stratum_id: str = Field(pattern=_ID)
    balance_pattern: ReferenceDecisionPattern
    balance_role: ReferenceEvidenceRole
    balance_domain: str = Field(min_length=1, max_length=200)
    quality_count: int = Field(gt=0)
    prestige_count: int = Field(gt=0)

    @model_validator(mode="after")
    def counts_are_matched(self) -> ReferenceSelectionStratumResult:
        if self.quality_count != self.prestige_count:
            raise ValueError("H0 source-selection strata must be exactly matched")
        return self


class ReferenceSelectionComparisonReport(BaseModel):
    """Frozen H0 arms; downstream content, model, review, and experiment remain closed."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    comparison_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    plan_locator: str = Field(min_length=1, max_length=1_000)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_locator: str = Field(min_length=1, max_length=1_000)
    approval_file_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    implementation_sha256: str = Field(pattern=_SHA256)
    algorithm_id: Literal[_ALGORITHM_ID] = _ALGORITHM_ID
    frozen_at: datetime
    target_source_count: int = Field(ge=2, le=100)
    quality_selected: tuple[SelectedReferenceRecord, ...] = Field(min_length=2, max_length=100)
    prestige_selected: tuple[SelectedReferenceRecord, ...] = Field(min_length=2, max_length=100)
    cross_arm_overlap_candidate_ids: tuple[str, ...]
    quality_unselected_candidate_ids: tuple[str, ...]
    prestige_unselected_candidate_ids: tuple[str, ...]
    strata: tuple[ReferenceSelectionStratumResult, ...] = Field(min_length=1)
    observed_prestige_fraction: float = Field(ge=0, le=1)
    downstream_envelope_sha256: str = Field(pattern=_SHA256)
    exact_source_count_parity: Literal[True] = True
    exact_stratum_parity: Literal[True] = True
    quality_selection_consulted_prestige_signals: Literal[False] = False
    prestige_selection_consulted_content_quality: Literal[False] = False
    natural_cross_arm_overlap_preserved: Literal[True] = True
    complete_broad_pool_preserved: Literal[True] = True
    selection_performed: Literal[True] = True
    raw_source_content_read: Literal[False] = False
    formal_outcomes_consulted: Literal[False] = False
    ready_for_h0_materialization: Literal[True] = True
    source_content_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    human_recruitment_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_source_content_access: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("frozen_at")
    @classmethod
    def frozen_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("reference-selection freeze timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def frozen_arms_are_closed(self) -> ReferenceSelectionComparisonReport:
        for locator in (self.plan_locator, self.approval_locator):
            _validate_relative_path(locator, "reference-selection chain")
        quality_ids = tuple(item.candidate_id for item in self.quality_selected)
        prestige_ids = tuple(item.candidate_id for item in self.prestige_selected)
        if len(quality_ids) != self.target_source_count or len(set(quality_ids)) != len(
            quality_ids
        ):
            raise ValueError("H0 quality arm differs from its exact source count")
        if len(prestige_ids) != self.target_source_count or len(set(prestige_ids)) != len(
            prestige_ids
        ):
            raise ValueError("H0 prestige arm differs from its exact source count")
        expected_overlap = tuple(sorted(set(quality_ids) & set(prestige_ids)))
        if self.cross_arm_overlap_candidate_ids != expected_overlap:
            raise ValueError("H0 cross-arm overlap ledger differs")
        if tuple(item.selection_rank for item in self.quality_selected) != tuple(
            range(1, self.target_source_count + 1)
        ) or tuple(item.selection_rank for item in self.prestige_selected) != tuple(
            range(1, self.target_source_count + 1)
        ):
            raise ValueError("H0 selection ranks must be contiguous")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class ReferenceSelectionReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: ReferenceSelectionComparisonReport


class ReferenceSelectionChainInspection(BaseModel):
    model_config = _CONFIG

    report: ReferenceSelectionReportInspection
    plan: ReferenceSelectionPlanInspection
    approval: ReferenceSelectionApprovalInspection
    implementation_current: bool


def plan_reference_selection_comparison(
    mining_run: ReferenceMiningRun,
    mining_report: ReferenceMiningReport,
    source_admission: SourceAdmissionReport,
    *,
    mining_run_binding: ReferenceSelectionFileBinding,
    mining_report_binding: ReferenceSelectionFileBinding,
    source_admission_binding: ReferenceSelectionFileBinding,
    source_links: tuple[ReferenceSelectionSourceLink, ...],
    comparison_id: str,
    project_id: str,
    report_output_locator: str,
    metadata_snapshot_year: int,
    minimum_observed_prestige_fraction: float,
    stable_tie_break_salt_sha256: str,
    target_source_count: int,
    downstream: ReferenceSelectionDownstreamEnvelope,
    created_at: datetime,
) -> ReferenceSelectionComparisonPlan:
    """Build a complete-pool, outcome-blind H0 plan without selecting either arm."""

    blockers: list[str] = []
    replayed = compile_reference_mining_report(mining_run)
    if replayed != mining_report:
        blockers.append("mining-report-replay-mismatch")
    expected_bindings = (
        (mining_run_binding.semantic_sha256, mining_run.run_sha256, "mining-run-semantic-drift"),
        (
            mining_report_binding.semantic_sha256,
            mining_report.report_sha256,
            "mining-report-semantic-drift",
        ),
        (
            source_admission_binding.semantic_sha256,
            source_admission.report_sha256,
            "source-admission-semantic-drift",
        ),
    )
    blockers.extend(code for observed, expected, code in expected_bindings if observed != expected)
    if not mining_report.cohort_ready_for_reference_quality:
        blockers.append("mining-cohort-not-ready")
    if source_admission.blockers:
        blockers.append("source-admission-global-blockers")

    links = {item.candidate_id: item.source_id for item in source_links}
    if len(links) != len(source_links):
        raise ValueError("reference-selection candidate links must be unique")
    if len({item.source_id for item in source_links}) != len(source_links):
        raise ValueError("reference-selection source links must be one-to-one")
    if source_admission.project_id != project_id:
        blockers.append("source-admission-project-mismatch")
    selected_ids = tuple(mining_report.selected_candidate_ids)
    if set(links) != set(selected_ids):
        blockers.append("candidate-source-link-population-mismatch")
    candidates = {
        item.candidate_id: item
        for batch in mining_run.batches
        for item in batch.candidates
        if item.candidate_id in set(selected_ids)
    }
    if set(candidates) != set(selected_ids):
        blockers.append("mining-selected-population-missing")
    admission_items = {item.source_id: item for item in source_admission.items}
    required_patterns = tuple(mining_run.need.required_decision_patterns)
    required_roles = tuple(mining_run.need.required_evidence_roles)
    required_domains = tuple(mining_run.need.required_domain_facets)
    records: list[ReferenceSelectionCandidateRecord] = []
    for candidate_id in selected_ids:
        candidate = candidates.get(candidate_id)
        if candidate is None:
            continue
        source_id = links.get(candidate_id)
        admitted = admission_items.get(source_id) if source_id is not None else None
        candidate_domains = tuple(
            candidate.metadata_grounded_domain_facets
            if mining_run.schema_version == "1.2"
            else candidate.domain_facets
        )
        grounded_required_domains = tuple(
            item for item in required_domains if item in candidate_domains
        )
        required_candidate_patterns = tuple(
            item for item in required_patterns if item in candidate.hypothesized_decision_patterns
        )
        required_candidate_roles = tuple(
            item for item in required_roles if item in candidate.hypothesized_evidence_roles
        )
        if not required_candidate_patterns:
            blockers.append(f"candidate-unclassified-pattern:{candidate_id}")
        if not required_candidate_roles:
            blockers.append(f"candidate-unclassified-role:{candidate_id}")
        if not grounded_required_domains:
            blockers.append(f"candidate-unclassified-domain:{candidate_id}")
        balance_pattern = (
            required_candidate_patterns[0]
            if required_candidate_patterns
            else candidate.hypothesized_decision_patterns[0]
        )
        balance_role = (
            required_candidate_roles[0]
            if required_candidate_roles
            else candidate.hypothesized_evidence_roles[0]
        )
        balance_domain = (
            grounded_required_domains[0]
            if grounded_required_domains
            else (candidate_domains or candidate.domain_facets)[0]
        )
        if admitted is None:
            blockers.append(f"candidate-source-admission-missing:{candidate_id}")
        elif admitted.source_group_id != candidate.source_group_id:
            blockers.append(f"candidate-source-group-mismatch:{candidate_id}")
        records.append(
            ReferenceSelectionCandidateRecord(
                candidate_id=candidate_id,
                source_id=source_id,
                source_group_id=candidate.source_group_id,
                decision_patterns=candidate.hypothesized_decision_patterns,
                evidence_roles=candidate.hypothesized_evidence_roles,
                domain_facets=(candidate_domains or candidate.domain_facets),
                balance_pattern=balance_pattern,
                balance_role=balance_role,
                balance_domain=balance_domain,
                balance_stratum_id=_stratum_id(
                    balance_pattern,
                    balance_role,
                    balance_domain,
                ),
                publication_year=candidate.publication_year,
                citation_count=candidate.citation_count,
                audit_binding_verified=bool(admitted and admitted.audit_binding_verified),
                rights_supported=bool(admitted and admitted.rights_supported),
                source_isolation_supported=bool(admitted and admitted.source_isolation_supported),
                downstream_eligible=bool(
                    admitted
                    and admitted.audit_binding_verified
                    and admitted.rights_supported
                    and admitted.source_isolation_supported
                ),
                content_grounded_admitted=bool(
                    admitted and admitted.disposition is SourceAdmissionVerdict.ADMIT
                ),
            )
        )

    content_groups = {item.source_group_id for item in records if item.content_grounded_admitted}
    downstream_groups = {item.source_group_id for item in records if item.downstream_eligible}
    if len(content_groups) < target_source_count:
        blockers.append("insufficient-content-grounded-source-groups")
    if len(downstream_groups) < target_source_count:
        blockers.append("insufficient-prestige-source-groups")
    eligible = [item for item in records if item.downstream_eligible]
    observed_fraction = (
        sum(
            item.citation_count is not None and item.publication_year is not None
            for item in eligible
        )
        / len(eligible)
        if eligible
        else 0.0
    )
    if observed_fraction < minimum_observed_prestige_fraction:
        blockers.append("insufficient-observed-prestige-signals")
    if created_at.year < metadata_snapshot_year:
        blockers.append("metadata-snapshot-year-after-plan")
    if any(
        item.publication_year is not None and item.publication_year > metadata_snapshot_year
        for item in records
    ):
        blockers.append("publication-after-metadata-snapshot")

    quality_ids = _select_quality(
        _quality_views(tuple(records)),
        target_count=target_source_count,
        required_patterns=required_patterns,
        required_roles=required_roles,
        required_domains=required_domains,
        salt_sha256=stable_tie_break_salt_sha256,
    )
    if not _quality_coverage_complete_values(
        quality_ids,
        tuple(records),
        required_patterns,
        required_roles,
        required_domains,
        target_source_count,
    ):
        blockers.append("quality-arm-coverage-incomplete")
    if not _prestige_strata_feasible(tuple(records), quality_ids):
        blockers.append("prestige-arm-stratum-infeasible")

    return ReferenceSelectionComparisonPlan(
        comparison_id=comparison_id,
        project_id=project_id,
        mining_id=mining_report.mining_id,
        mining_run=mining_run_binding,
        mining_report=mining_report_binding,
        source_admission_report=source_admission_binding,
        report_output_locator=report_output_locator,
        implementation_sha256=reference_selection_implementation_sha256(),
        created_at=created_at,
        metadata_snapshot_year=metadata_snapshot_year,
        minimum_observed_prestige_fraction=minimum_observed_prestige_fraction,
        stable_tie_break_salt_sha256=stable_tie_break_salt_sha256,
        required_decision_patterns=required_patterns,
        required_evidence_roles=required_roles,
        required_domain_facets=required_domains,
        target_source_count=target_source_count,
        downstream=downstream,
        candidates=tuple(records),
        blocker_codes=tuple(sorted(set(blockers))),
        ready_for_owner_approval=not blockers,
    )


def plan_reference_selection_comparison_from_files(
    *,
    mining_run_path: str | Path,
    mining_report_path: str | Path,
    source_admission_report_path: str | Path,
    evidence_root: str | Path,
    source_links: tuple[ReferenceSelectionSourceLink, ...],
    comparison_id: str,
    project_id: str,
    report_output_locator: str,
    metadata_snapshot_year: int,
    minimum_observed_prestige_fraction: float,
    stable_tie_break_salt_sha256: str,
    target_source_count: int,
    downstream: ReferenceSelectionDownstreamEnvelope,
    created_at: datetime,
) -> ReferenceSelectionComparisonPlan:
    """Load, hash, and semantically verify the exact H0 control artifacts."""

    root = Path(evidence_root).resolve(strict=True)
    run_path, run_raw, run_payload = _load_json(mining_run_path, "reference-mining run")
    report_path, report_raw, report_payload = _load_json(
        mining_report_path, "reference-mining report"
    )
    admission_path, admission_raw, admission_payload = _load_json(
        source_admission_report_path, "source-admission report"
    )
    for path in (run_path, report_path, admission_path):
        _relative_to_root(path, root)

    recorded_run_sha256 = run_payload.pop("run_sha256", None)
    proposal_payload = run_payload.get("proposal")
    recorded_proposal_sha256 = (
        proposal_payload.pop("proposal_sha256", None)
        if isinstance(proposal_payload, dict)
        else None
    )
    mining_run = ReferenceMiningRun.model_validate(run_payload)
    if recorded_run_sha256 is not None and recorded_run_sha256 != mining_run.run_sha256:
        raise ValueError("reference-mining run hash mismatch")
    if (
        recorded_proposal_sha256 is not None
        and recorded_proposal_sha256 != mining_run.proposal.proposal_sha256
    ):
        raise ValueError("reference-mining proposal hash mismatch")
    recorded_report_sha256 = report_payload.pop("report_sha256", None)
    mining_report = ReferenceMiningReport.model_validate(report_payload)
    if recorded_report_sha256 is not None and recorded_report_sha256 != mining_report.report_sha256:
        raise ValueError("reference-mining report hash mismatch")
    recorded_admission_sha256 = admission_payload.pop("report_sha256", None)
    source_admission = SourceAdmissionReport.model_validate(admission_payload)
    if (
        recorded_admission_sha256 is not None
        and recorded_admission_sha256 != source_admission.report_sha256
    ):
        raise ValueError("source-admission report hash mismatch")

    return plan_reference_selection_comparison(
        mining_run,
        mining_report,
        source_admission,
        mining_run_binding=ReferenceSelectionFileBinding(
            locator=_relative_to_root(run_path, root),
            file_sha256=hashlib.sha256(run_raw).hexdigest(),
            semantic_sha256=mining_run.run_sha256,
        ),
        mining_report_binding=ReferenceSelectionFileBinding(
            locator=_relative_to_root(report_path, root),
            file_sha256=hashlib.sha256(report_raw).hexdigest(),
            semantic_sha256=mining_report.report_sha256,
        ),
        source_admission_binding=ReferenceSelectionFileBinding(
            locator=_relative_to_root(admission_path, root),
            file_sha256=hashlib.sha256(admission_raw).hexdigest(),
            semantic_sha256=source_admission.report_sha256,
        ),
        source_links=source_links,
        comparison_id=comparison_id,
        project_id=project_id,
        report_output_locator=report_output_locator,
        metadata_snapshot_year=metadata_snapshot_year,
        minimum_observed_prestige_fraction=minimum_observed_prestige_fraction,
        stable_tie_break_salt_sha256=stable_tie_break_salt_sha256,
        target_source_count=target_source_count,
        downstream=downstream,
        created_at=created_at,
    )


def approve_reference_selection_comparison(
    inspection: ReferenceSelectionPlanInspection,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> ReferenceSelectionComparisonApproval:
    """Approve deterministic H0 selection while retaining every external gate."""

    plan = inspection.plan
    if not plan.ready_for_owner_approval:
        raise ValueError("cannot approve a blocked reference-selection plan")
    if confirmed_plan_sha256 != plan.plan_sha256:
        raise ValueError("reference-selection plan confirmation hash differs")
    if plan.implementation_sha256 != reference_selection_implementation_sha256():
        raise ValueError("reference-selection implementation has drifted")
    return ReferenceSelectionComparisonApproval(
        approval_id=f"{plan.comparison_id}-approval",
        comparison_id=plan.comparison_id,
        plan_file_sha256=inspection.file_sha256,
        plan_sha256=plan.plan_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="h0-deterministic-reference-selection-only",
    )


def _replay_plan_from_upstreams(
    plan: ReferenceSelectionComparisonPlan,
    root: Path,
) -> ReferenceSelectionComparisonPlan:
    return plan_reference_selection_comparison_from_files(
        mining_run_path=root / plan.mining_run.locator,
        mining_report_path=root / plan.mining_report.locator,
        source_admission_report_path=root / plan.source_admission_report.locator,
        evidence_root=root,
        source_links=tuple(
            ReferenceSelectionSourceLink(
                candidate_id=item.candidate_id,
                source_id=item.source_id,
            )
            for item in plan.candidates
            if item.source_id is not None
        ),
        comparison_id=plan.comparison_id,
        project_id=plan.project_id,
        report_output_locator=plan.report_output_locator,
        metadata_snapshot_year=plan.metadata_snapshot_year,
        minimum_observed_prestige_fraction=plan.minimum_observed_prestige_fraction,
        stable_tie_break_salt_sha256=plan.stable_tie_break_salt_sha256,
        target_source_count=plan.target_source_count,
        downstream=plan.downstream,
        created_at=plan.created_at,
    )


def freeze_reference_selection_comparison(
    plan_inspection: ReferenceSelectionPlanInspection,
    approval_inspection: ReferenceSelectionApprovalInspection,
    *,
    workspace_root: str | Path,
) -> ReferenceSelectionComparisonReport:
    """Select both H0 arms deterministically without opening source content."""

    root = Path(workspace_root).resolve(strict=True)
    plan = plan_inspection.plan
    approval = approval_inspection.approval
    expected = (
        plan.comparison_id,
        plan_inspection.file_sha256,
        plan.plan_sha256,
    )
    observed = (
        approval.comparison_id,
        approval.plan_file_sha256,
        approval.plan_sha256,
    )
    if observed != expected:
        raise ValueError("reference-selection approval differs from its plan")
    if not plan.ready_for_owner_approval:
        raise ValueError("reference-selection plan is blocked")
    if plan.implementation_sha256 != reference_selection_implementation_sha256():
        raise ValueError("reference-selection implementation has drifted")
    replayed_plan = _replay_plan_from_upstreams(plan, root)
    if replayed_plan != plan:
        raise ValueError("reference-selection plan differs from its bound upstream artifacts")

    quality_ids = _select_quality(
        _quality_views(plan.candidates),
        target_count=plan.target_source_count,
        required_patterns=plan.required_decision_patterns,
        required_roles=plan.required_evidence_roles,
        required_domains=plan.required_domain_facets,
        salt_sha256=plan.stable_tie_break_salt_sha256,
    )
    if not _quality_coverage_complete(quality_ids, plan):
        raise ValueError("reference-selection quality arm lacks required scientific coverage")
    quality_records = {item.candidate_id: item for item in plan.candidates}
    quota = Counter(quality_records[item].balance_stratum_id for item in quality_ids)
    prestige_view = tuple(
        _PrestigeSelectionView(
            candidate_id=item.candidate_id,
            source_id=item.source_id,
            source_group_id=item.source_group_id,
            balance_stratum_id=item.balance_stratum_id,
            publication_year=item.publication_year,
            citation_count=item.citation_count,
            eligible=item.downstream_eligible,
        )
        for item in plan.candidates
        if item.source_id is not None
    )
    prestige_ids = _select_prestige(prestige_view, plan, quota)
    if (
        len(quality_ids) != plan.target_source_count
        or len(prestige_ids) != plan.target_source_count
    ):
        raise ValueError(
            "reference-selection algorithm could not satisfy the approved source count"
        )

    quality_selected = tuple(
        _selected_record(
            quality_records[candidate_id],
            rank=index,
            basis="content-grounded-admission",
        )
        for index, candidate_id in enumerate(quality_ids, start=1)
    )
    prestige_selected = tuple(
        _selected_record(
            quality_records[candidate_id],
            rank=index,
            basis="age-normalized-citation-prestige",
        )
        for index, candidate_id in enumerate(prestige_ids, start=1)
    )
    prestige_counts = Counter(item.balance_stratum_id for item in prestige_selected)
    strata: list[ReferenceSelectionStratumResult] = []
    for stratum_id in sorted(quota):
        exemplar = next(item for item in plan.candidates if item.balance_stratum_id == stratum_id)
        strata.append(
            ReferenceSelectionStratumResult(
                balance_stratum_id=stratum_id,
                balance_pattern=exemplar.balance_pattern,
                balance_role=exemplar.balance_role,
                balance_domain=exemplar.balance_domain,
                quality_count=quota[stratum_id],
                prestige_count=prestige_counts[stratum_id],
            )
        )
    all_ids = {item.candidate_id for item in plan.candidates}
    eligible = [item for item in plan.candidates if item.downstream_eligible]
    observed_fraction = sum(
        item.citation_count is not None and item.publication_year is not None for item in eligible
    ) / len(eligible)
    return ReferenceSelectionComparisonReport(
        comparison_id=plan.comparison_id,
        project_id=plan.project_id,
        plan_locator=_relative_to_root(plan_inspection.path, root),
        plan_file_sha256=plan_inspection.file_sha256,
        plan_sha256=plan.plan_sha256,
        approval_locator=_relative_to_root(approval_inspection.path, root),
        approval_file_sha256=approval_inspection.file_sha256,
        approval_sha256=approval.approval_sha256,
        implementation_sha256=plan.implementation_sha256,
        frozen_at=approval.approved_at,
        target_source_count=plan.target_source_count,
        quality_selected=quality_selected,
        prestige_selected=prestige_selected,
        cross_arm_overlap_candidate_ids=tuple(sorted(set(quality_ids) & set(prestige_ids))),
        quality_unselected_candidate_ids=tuple(sorted(all_ids - set(quality_ids))),
        prestige_unselected_candidate_ids=tuple(sorted(all_ids - set(prestige_ids))),
        strata=tuple(strata),
        observed_prestige_fraction=observed_fraction,
        downstream_envelope_sha256=_canonical_sha256(plan.downstream.model_dump(mode="json")),
    )


def inspect_reference_selection_comparison_chain(
    report_path: str | Path,
    *,
    workspace_root: str | Path,
) -> ReferenceSelectionChainInspection:
    """Replay plan, approval, and both selections from one frozen report."""

    root = Path(workspace_root).resolve(strict=True)
    report = load_reference_selection_report(report_path)
    plan = load_reference_selection_plan(root / report.report.plan_locator)
    approval = load_reference_selection_approval(root / report.report.approval_locator)
    if plan.file_sha256 != report.report.plan_file_sha256:
        raise ValueError("reference-selection report plan file hash differs")
    if approval.file_sha256 != report.report.approval_file_sha256:
        raise ValueError("reference-selection report approval file hash differs")
    if (
        report.report.plan_sha256 != plan.plan.plan_sha256
        or report.report.approval_sha256 != approval.approval.approval_sha256
        or approval.approval.comparison_id != plan.plan.comparison_id
        or approval.approval.plan_file_sha256 != plan.file_sha256
        or approval.approval.plan_sha256 != plan.plan.plan_sha256
    ):
        raise ValueError("reference-selection semantic chain differs")
    upstream_replay = _replay_plan_from_upstreams(plan.plan, root)
    normalized_replay = upstream_replay.model_copy(
        update={"implementation_sha256": plan.plan.implementation_sha256}
    )
    if normalized_replay != plan.plan:
        raise ValueError("reference-selection plan differs from its bound upstream artifacts")
    implementation_current = (
        plan.plan.implementation_sha256 == reference_selection_implementation_sha256()
    )
    if implementation_current:
        replayed = freeze_reference_selection_comparison(plan, approval, workspace_root=root)
        if replayed != report.report:
            raise ValueError("reference-selection report differs from deterministic replay")
    expected_output = root.joinpath(*PurePosixPath(plan.plan.report_output_locator).parts)
    if expected_output.resolve(strict=False) != report.path:
        raise ValueError("reference-selection report path differs from its approved output")
    return ReferenceSelectionChainInspection(
        report=report,
        plan=plan,
        approval=approval,
        implementation_current=implementation_current,
    )


def save_reference_selection_plan(plan: ReferenceSelectionComparisonPlan, path: str | Path) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def save_reference_selection_approval(
    approval: ReferenceSelectionComparisonApproval, path: str | Path
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def save_reference_selection_report(
    report: ReferenceSelectionComparisonReport, path: str | Path
) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def load_reference_selection_plan(path: str | Path) -> ReferenceSelectionPlanInspection:
    source, raw, payload = _load_json(path, "reference-selection plan")
    recorded = payload.pop("plan_sha256", None)
    plan = ReferenceSelectionComparisonPlan.model_validate(payload)
    if recorded is not None and recorded != plan.plan_sha256:
        raise ValueError("reference-selection plan hash mismatch")
    return ReferenceSelectionPlanInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def load_reference_selection_approval(path: str | Path) -> ReferenceSelectionApprovalInspection:
    source, raw, payload = _load_json(path, "reference-selection approval")
    recorded = payload.pop("approval_sha256", None)
    approval = ReferenceSelectionComparisonApproval.model_validate(payload)
    if recorded is not None and recorded != approval.approval_sha256:
        raise ValueError("reference-selection approval hash mismatch")
    return ReferenceSelectionApprovalInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def load_reference_selection_report(path: str | Path) -> ReferenceSelectionReportInspection:
    source, raw, payload = _load_json(path, "reference-selection report")
    recorded = payload.pop("report_sha256", None)
    report = ReferenceSelectionComparisonReport.model_validate(payload)
    if recorded is not None and recorded != report.report_sha256:
        raise ValueError("reference-selection report hash mismatch")
    return ReferenceSelectionReportInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


class _QualitySelectionView(BaseModel):
    model_config = _CONFIG

    candidate_id: str
    source_id: str
    source_group_id: str
    balance_stratum_id: str
    decision_patterns: tuple[ReferenceDecisionPattern, ...]
    evidence_roles: tuple[ReferenceEvidenceRole, ...]
    domain_facets: tuple[str, ...]
    admitted: bool


class _PrestigeSelectionView(BaseModel):
    model_config = _CONFIG

    candidate_id: str
    source_id: str
    source_group_id: str
    balance_stratum_id: str
    publication_year: int | None
    citation_count: int | None
    eligible: bool


def _select_quality(
    candidates: tuple[_QualitySelectionView, ...],
    *,
    target_count: int,
    required_patterns: tuple[ReferenceDecisionPattern, ...],
    required_roles: tuple[ReferenceEvidenceRole, ...],
    required_domains: tuple[str, ...],
    salt_sha256: str,
) -> tuple[str, ...]:
    """Coverage-aware content arm with no prestige field in its input type."""

    remaining = [item for item in candidates if item.admitted]
    selected: list[_QualitySelectionView] = []
    groups: set[str] = set()
    patterns: set[ReferenceDecisionPattern] = set()
    roles: set[ReferenceEvidenceRole] = set()
    domains: set[str] = set()
    while remaining and len(selected) < target_count:
        admissible = [item for item in remaining if item.source_group_id not in groups]
        if not admissible:
            break

        def priority(item: _QualitySelectionView) -> tuple[int, str]:
            gain = (
                len((set(item.decision_patterns) & set(required_patterns)) - patterns)
                + len((set(item.evidence_roles) & set(required_roles)) - roles)
                + len((set(item.domain_facets) & set(required_domains)) - domains)
            )
            return (-gain, _stable_priority(salt_sha256, item.candidate_id))

        chosen = min(admissible, key=priority)
        selected.append(chosen)
        remaining.remove(chosen)
        groups.add(chosen.source_group_id)
        patterns.update(set(chosen.decision_patterns) & set(required_patterns))
        roles.update(set(chosen.evidence_roles) & set(required_roles))
        domains.update(set(chosen.domain_facets) & set(required_domains))
    return tuple(item.candidate_id for item in selected)


def _quality_views(
    records: tuple[ReferenceSelectionCandidateRecord, ...],
) -> tuple[_QualitySelectionView, ...]:
    return tuple(
        _QualitySelectionView(
            candidate_id=item.candidate_id,
            source_id=item.source_id,
            source_group_id=item.source_group_id,
            balance_stratum_id=item.balance_stratum_id,
            decision_patterns=item.decision_patterns,
            evidence_roles=item.evidence_roles,
            domain_facets=item.domain_facets,
            admitted=item.content_grounded_admitted,
        )
        for item in records
        if item.source_id is not None
    )


def _quality_coverage_complete(
    selected_ids: tuple[str, ...],
    plan: ReferenceSelectionComparisonPlan,
) -> bool:
    return _quality_coverage_complete_values(
        selected_ids,
        plan.candidates,
        plan.required_decision_patterns,
        plan.required_evidence_roles,
        plan.required_domain_facets,
        plan.target_source_count,
    )


def _quality_coverage_complete_values(
    selected_ids: tuple[str, ...],
    records: tuple[ReferenceSelectionCandidateRecord, ...],
    required_patterns: tuple[ReferenceDecisionPattern, ...],
    required_roles: tuple[ReferenceEvidenceRole, ...],
    required_domains: tuple[str, ...],
    target_count: int,
) -> bool:
    selected = [item for item in records if item.candidate_id in set(selected_ids)]
    return bool(
        len(selected_ids) == target_count
        and set(required_patterns)
        <= {value for item in selected for value in item.decision_patterns}
        and set(required_roles) <= {value for item in selected for value in item.evidence_roles}
        and set(required_domains) <= {value for item in selected for value in item.domain_facets}
    )


def _prestige_strata_feasible(
    records: tuple[ReferenceSelectionCandidateRecord, ...],
    quality_ids: tuple[str, ...],
) -> bool:
    by_id = {item.candidate_id: item for item in records}
    quota = Counter(
        by_id[candidate_id].balance_stratum_id
        for candidate_id in quality_ids
        if candidate_id in by_id
    )
    if sum(quota.values()) != len(quality_ids):
        return False
    for stratum_id, required_count in quota.items():
        observed_groups = {
            item.source_group_id
            for item in records
            if item.downstream_eligible
            and item.balance_stratum_id == stratum_id
            and item.publication_year is not None
            and item.citation_count is not None
        }
        if len(observed_groups) < required_count:
            return False
    return bool(quota)


def _select_prestige(
    candidates: tuple[_PrestigeSelectionView, ...],
    plan: ReferenceSelectionComparisonPlan,
    quota: Counter[str],
) -> tuple[str, ...]:
    """Matched citation-rate arm with no content-quality field in its input type."""

    selected: list[_PrestigeSelectionView] = []
    groups: set[str] = set()
    for stratum_id in sorted(quota):
        available = [
            item
            for item in candidates
            if item.eligible
            and item.balance_stratum_id == stratum_id
            and item.publication_year is not None
            and item.citation_count is not None
        ]

        def priority(item: _PrestigeSelectionView) -> tuple[Fraction, int, str]:
            exposure = (
                max(1, plan.metadata_snapshot_year - item.publication_year + 1)
                if item.publication_year is not None
                else 1
            )
            citations = item.citation_count or 0
            return (
                -Fraction(citations, exposure),
                -citations,
                _stable_priority(plan.stable_tie_break_salt_sha256, item.candidate_id),
            )

        for item in sorted(available, key=priority):
            if item.source_group_id in groups:
                continue
            selected.append(item)
            groups.add(item.source_group_id)
            if (
                sum(record.balance_stratum_id == stratum_id for record in selected)
                == quota[stratum_id]
            ):
                break
        if sum(record.balance_stratum_id == stratum_id for record in selected) != quota[stratum_id]:
            raise ValueError(f"prestige arm cannot satisfy matched stratum {stratum_id}")
    return tuple(item.candidate_id for item in selected)


def _selected_record(
    candidate: ReferenceSelectionCandidateRecord,
    *,
    rank: int,
    basis: Literal["content-grounded-admission", "age-normalized-citation-prestige"],
) -> SelectedReferenceRecord:
    if candidate.source_id is None:
        raise ValueError("selected H0 reference lacks a source identity")
    return SelectedReferenceRecord(
        selection_rank=rank,
        candidate_id=candidate.candidate_id,
        source_id=candidate.source_id,
        source_group_id=candidate.source_group_id,
        balance_stratum_id=candidate.balance_stratum_id,
        selection_basis=basis,
        citation_count=candidate.citation_count,
        publication_year=candidate.publication_year,
    )


def _stratum_id(
    pattern: ReferenceDecisionPattern,
    role: ReferenceEvidenceRole,
    domain: str,
) -> str:
    digest = hashlib.sha256(f"{pattern.value}\0{role.value}\0{domain}".encode()).hexdigest()[:20]
    return f"stratum-{digest}"


def _stable_priority(salt_sha256: str, candidate_id: str) -> str:
    return hashlib.sha256(f"{salt_sha256}\0{candidate_id}".encode()).hexdigest()


def reference_selection_implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("reference-selection artifact escapes workspace root") from exc


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative path")


def _load_json(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    source = requested.resolve(strict=True)
    if not source.is_file() or not 1 <= source.stat().st_size <= _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return source, raw, payload


def _write_new_json(path: str | Path, text: str) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


__all__ = [
    "ReferenceSelectionApprovalInspection",
    "ReferenceSelectionCandidateRecord",
    "ReferenceSelectionChainInspection",
    "ReferenceSelectionComparisonApproval",
    "ReferenceSelectionComparisonPlan",
    "ReferenceSelectionComparisonReport",
    "ReferenceSelectionDownstreamEnvelope",
    "ReferenceSelectionFileBinding",
    "ReferenceSelectionPlanInspection",
    "ReferenceSelectionReportInspection",
    "ReferenceSelectionSourceLink",
    "ReferenceSelectionStratumResult",
    "SelectedReferenceRecord",
    "approve_reference_selection_comparison",
    "freeze_reference_selection_comparison",
    "inspect_reference_selection_comparison_chain",
    "load_reference_selection_approval",
    "load_reference_selection_plan",
    "load_reference_selection_report",
    "plan_reference_selection_comparison",
    "plan_reference_selection_comparison_from_files",
    "reference_selection_implementation_sha256",
    "save_reference_selection_approval",
    "save_reference_selection_plan",
    "save_reference_selection_report",
]

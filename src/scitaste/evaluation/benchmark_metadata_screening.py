"""Complete-population benchmark screening before allocation or task selection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.acquisition import load_dataset_acquisition_receipt
from scitaste.evaluation.benchmark_metadata_projection import (
    BenchmarkMetadataPopulationChainInspection,
    BenchmarkMetadataScopeInspection,
    ProjectedBenchmarkMetadataRecord,
    inspect_benchmark_metadata_population_chain,
    load_benchmark_metadata_scope,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_EVIDENCE_BYTES = 16 * 1_048_576
_POST_ELIGIBILITY_CODES = frozenset({"exceeds-declared-formal-capacity-after-scientific-screen"})


class BenchmarkScreenRuleRole(StrEnum):
    ELIGIBILITY = "scientific-eligibility"
    ALLOCATION = "post-eligibility-allocation"


class BenchmarkScreenEvidenceMode(StrEnum):
    PROJECTED_METADATA = "projected-metadata-only"
    PROJECTED_METADATA_AND_BOUND_EVIDENCE = "projected-metadata-plus-bound-evidence"


class BenchmarkScreenAssessmentAuthority(StrEnum):
    DETERMINISTIC_METADATA = "deterministic-metadata"
    EVIDENCE_BOUND_REVIEW = "evidence-bound-review"
    RIGHTS_REVIEW = "rights-review"
    RUNTIME_PREFLIGHT = "runtime-preflight"
    SANDBOX_PREFLIGHT = "sandbox-preflight"
    SEEDED_ALLOCATION = "seeded-allocation"


class BenchmarkScreenMissingDisposition(StrEnum):
    EXCLUDE = "exclude"
    CANNOT_ASSESS = "cannot-assess"


class BenchmarkScreenVerdict(StrEnum):
    PASS = "pass"
    EXCLUDE = "exclude"
    CANNOT_ASSESS = "cannot-assess"


class BenchmarkRecordScreenDisposition(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    BLOCKED = "blocked"


class BenchmarkMetadataScreenRule(BaseModel):
    """One pre-content rule; allocation rules cannot change scientific eligibility."""

    model_config = _CONFIG

    exclusion_code: str = Field(pattern=_ID)
    role: BenchmarkScreenRuleRole
    evidence_fields: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence_mode: BenchmarkScreenEvidenceMode
    assessment_authority: BenchmarkScreenAssessmentAuthority
    missing_evidence_disposition: BenchmarkScreenMissingDisposition
    decision_standard: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def rule_is_deterministic_and_closed(self) -> BenchmarkMetadataScreenRule:
        if self.evidence_fields != tuple(sorted(set(self.evidence_fields))):
            raise ValueError("benchmark screen evidence fields must be sorted and unique")
        if self.role is BenchmarkScreenRuleRole.ALLOCATION:
            if self.exclusion_code not in _POST_ELIGIBILITY_CODES:
                raise ValueError("only a declared post-screen capacity code may be allocation")
            if (
                self.assessment_authority
                is not BenchmarkScreenAssessmentAuthority.SEEDED_ALLOCATION
            ):
                raise ValueError("post-eligibility allocation requires seeded allocation authority")
        elif self.assessment_authority is BenchmarkScreenAssessmentAuthority.SEEDED_ALLOCATION:
            raise ValueError("scientific eligibility cannot use allocation authority")
        return self


class BenchmarkMetadataAllocationPolicy(BaseModel):
    """A deferred allocation contract over eligible records only."""

    model_config = _CONFIG

    population: Literal["eligible-records-only"] = "eligible-records-only"
    method: Literal["stratified-seeded-sampling"] = "stratified-seeded-sampling"
    strata_fields: tuple[str, ...] = Field(min_length=1, max_length=10)
    sample_size_source: Literal["future-clustered-power-analysis"] = (
        "future-clustered-power-analysis"
    )
    random_seed_source: Literal["future-precommitted-seed"] = "future-precommitted-seed"
    preserves_unsampled_records: Literal[True] = True
    allocation_deferred: Literal[True] = True

    @model_validator(mode="after")
    def fields_are_sorted_and_unique(self) -> BenchmarkMetadataAllocationPolicy:
        if self.strata_fields != tuple(sorted(set(self.strata_fields))):
            raise ValueError("benchmark allocation strata fields must be sorted and unique")
        return self


class BenchmarkMetadataScreenRulebook(BaseModel):
    """Scientific rules frozen before benchmark source content is opened."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    rulebook_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    scope_file_sha256: str = Field(pattern=_SHA256)
    frozen_at: datetime
    rules: tuple[BenchmarkMetadataScreenRule, ...] = Field(min_length=1, max_length=50)
    allocation_policy: BenchmarkMetadataAllocationPolicy
    frozen_before_source_content_read: Literal[True] = True
    formal_outcomes_available: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    current_host_inventory_consulted: Literal[False] = False
    model_may_decide_eligibility: Literal[False] = False
    selection_performed: Literal[False] = False
    authorizes_content_read: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("frozen_at")
    @classmethod
    def frozen_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark screen rulebook timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def rules_are_sorted_and_unique(self) -> BenchmarkMetadataScreenRulebook:
        codes = tuple(rule.exclusion_code for rule in self.rules)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("benchmark screen rules must be sorted and unique")
        return self

    @computed_field
    @property
    def rulebook_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"rulebook_sha256"}))


class BenchmarkMetadataScreenRulebookInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    rulebook: BenchmarkMetadataScreenRulebook


class BenchmarkMetadataScreenRulebookReport(BaseModel):
    """No-read proof that one rulebook exactly covers its frozen scope."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    rulebook_id: str = Field(pattern=_ID)
    rulebook_sha256: str = Field(pattern=_SHA256)
    scope_id: str = Field(pattern=_ID)
    scope_file_sha256: str = Field(pattern=_SHA256)
    eligibility_rule_count: int = Field(ge=1)
    allocation_rule_codes: tuple[str, ...]
    required_screen_fields: tuple[str, ...] = Field(min_length=1)
    ready_for_population_screening: Literal[True] = True
    source_content_read: Literal[False] = False
    selection_performed: Literal[False] = False
    authorizes_execution: Literal[False] = False


class BenchmarkScreenEvidenceBinding(BaseModel):
    """Bound assessment evidence; never a benchmark source-body locator."""

    model_config = _CONFIG

    evidence_id: str = Field(pattern=_ID)
    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        _validate_relative_path(value, "benchmark screen evidence")
        return value


class BenchmarkRecordRuleDecision(BaseModel):
    """One outcome/resource-blind decision for one record and eligibility rule."""

    model_config = _CONFIG

    record_id: str = Field(pattern=_ID)
    exclusion_code: str = Field(pattern=_ID)
    verdict: BenchmarkScreenVerdict
    evidence_fields: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence_bindings: tuple[BenchmarkScreenEvidenceBinding, ...] = Field(default=(), max_length=20)
    assessment_authority: BenchmarkScreenAssessmentAuthority
    assessor_id: str = Field(pattern=_ID)
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def evidence_is_sorted_and_unique(self) -> BenchmarkRecordRuleDecision:
        if self.evidence_fields != tuple(sorted(set(self.evidence_fields))):
            raise ValueError("benchmark decision evidence fields must be sorted and unique")
        evidence_ids = tuple(item.evidence_id for item in self.evidence_bindings)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("benchmark decision evidence bindings must be sorted and unique")
        evidence_paths = tuple(item.path for item in self.evidence_bindings)
        if len(evidence_paths) != len(set(evidence_paths)):
            raise ValueError("benchmark decision evidence paths must be unique")
        return self


class BenchmarkMetadataScreenDecisionPackage(BaseModel):
    """Complete proposed decisions; it cannot allocate or execute eligible records."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    population_file_sha256: str = Field(pattern=_SHA256)
    population_sha256: str = Field(pattern=_SHA256)
    rulebook_file_sha256: str = Field(pattern=_SHA256)
    rulebook_sha256: str = Field(pattern=_SHA256)
    frozen_at: datetime
    decisions: tuple[BenchmarkRecordRuleDecision, ...] = Field(min_length=1)
    complete_population_decisions_required: Literal[True] = True
    formal_outcomes_available: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    current_host_inventory_consulted: Literal[False] = False
    model_assistance_used: Literal[False] = False
    selection_performed: Literal[False] = False
    authorizes_allocation: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("frozen_at")
    @classmethod
    def frozen_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark screen decision timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def decision_pairs_are_sorted_and_unique(self) -> BenchmarkMetadataScreenDecisionPackage:
        pairs = tuple((item.record_id, item.exclusion_code) for item in self.decisions)
        if pairs != tuple(sorted(set(pairs))):
            raise ValueError("benchmark screen decision pairs must be sorted and unique")
        return self

    @computed_field
    @property
    def package_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"package_sha256"}))


class BenchmarkMetadataScreenDecisionPackageInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    package: BenchmarkMetadataScreenDecisionPackage


class BenchmarkMetadataScreenItemReport(BaseModel):
    model_config = _CONFIG

    record_id: str = Field(pattern=_ID)
    disposition: BenchmarkRecordScreenDisposition
    exclusion_codes: tuple[str, ...]
    unresolved_codes: tuple[str, ...]

    @model_validator(mode="after")
    def disposition_matches_codes(self) -> BenchmarkMetadataScreenItemReport:
        if self.exclusion_codes != tuple(sorted(set(self.exclusion_codes))):
            raise ValueError("benchmark screen exclusion codes must be sorted and unique")
        if self.unresolved_codes != tuple(sorted(set(self.unresolved_codes))):
            raise ValueError("benchmark screen unresolved codes must be sorted and unique")
        expected = (
            BenchmarkRecordScreenDisposition.EXCLUDED
            if self.exclusion_codes
            else BenchmarkRecordScreenDisposition.BLOCKED
            if self.unresolved_codes
            else BenchmarkRecordScreenDisposition.ELIGIBLE
        )
        if self.disposition is not expected:
            raise ValueError("benchmark record disposition differs from its rule decisions")
        return self


class BenchmarkMetadataScreeningReport(BaseModel):
    """Complete eligibility ledger; allocation and experimental execution remain closed."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    population_locator: str = Field(min_length=1, max_length=1_000)
    population_file_sha256: str = Field(pattern=_SHA256)
    population_sha256: str = Field(pattern=_SHA256)
    rulebook_locator: str = Field(min_length=1, max_length=1_000)
    rulebook_file_sha256: str = Field(pattern=_SHA256)
    rulebook_sha256: str = Field(pattern=_SHA256)
    decision_package_locator: str = Field(min_length=1, max_length=1_000)
    decision_package_file_sha256: str = Field(pattern=_SHA256)
    decision_package_sha256: str = Field(pattern=_SHA256)
    screening_implementation_sha256: str = Field(pattern=_SHA256)
    screened_at: datetime
    record_count: int = Field(ge=1)
    eligibility_rule_count: int = Field(ge=1)
    allocation_rule_codes: tuple[str, ...]
    eligible_record_ids: tuple[str, ...]
    excluded_record_ids: tuple[str, ...]
    blocked_record_ids: tuple[str, ...]
    items: tuple[BenchmarkMetadataScreenItemReport, ...] = Field(min_length=1)
    ready_for_allocation_proposal: bool
    complete_population_screened: Literal[True] = True
    projected_metadata_read: Literal[True] = True
    raw_source_content_read: Literal[False] = False
    bound_assessment_evidence_read: bool
    formal_outcomes_consulted: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    current_host_inventory_consulted: Literal[False] = False
    model_calls_performed: Literal[False] = False
    selection_performed: Literal[False] = False
    allocation_performed: Literal[False] = False
    asset_download_performed: Literal[False] = False
    ingestion_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_allocation: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("screened_at")
    @classmethod
    def screened_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark screening timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def population_partition_is_complete(self) -> BenchmarkMetadataScreeningReport:
        for value, label in (
            (self.eligible_record_ids, "eligible record IDs"),
            (self.excluded_record_ids, "excluded record IDs"),
            (self.blocked_record_ids, "blocked record IDs"),
            (self.allocation_rule_codes, "allocation rule codes"),
        ):
            if value != tuple(sorted(set(value))):
                raise ValueError(f"benchmark screening {label} must be sorted and unique")
        item_ids = tuple(item.record_id for item in self.items)
        if item_ids != tuple(sorted(set(item_ids))) or self.record_count != len(item_ids):
            raise ValueError("benchmark screening items must cover unique sorted records")
        partitions = (
            set(self.eligible_record_ids),
            set(self.excluded_record_ids),
            set(self.blocked_record_ids),
        )
        if any(partitions[left] & partitions[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("benchmark screening record partitions overlap")
        if set().union(*partitions) != set(item_ids):
            raise ValueError("benchmark screening record partitions are incomplete")
        expected_ready = bool(self.eligible_record_ids) and not self.blocked_record_ids
        if self.ready_for_allocation_proposal != expected_ready:
            raise ValueError("benchmark screening allocation readiness differs from evidence")
        for locator in (
            self.population_locator,
            self.rulebook_locator,
            self.decision_package_locator,
        ):
            _validate_relative_path(locator, "benchmark screening control locator")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class BenchmarkMetadataScreeningReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: BenchmarkMetadataScreeningReport


class BenchmarkMetadataScreeningChainInspection(BaseModel):
    model_config = _CONFIG

    report: BenchmarkMetadataScreeningReportInspection
    population: BenchmarkMetadataPopulationChainInspection
    rulebook: BenchmarkMetadataScreenRulebookInspection
    decisions: BenchmarkMetadataScreenDecisionPackageInspection
    screening_implementation_current: bool


def load_benchmark_metadata_screen_rulebook(
    path: str | Path,
) -> BenchmarkMetadataScreenRulebookInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata screen rulebook")
    recorded = payload.pop("rulebook_sha256", None)
    rulebook = BenchmarkMetadataScreenRulebook.model_validate(payload)
    if recorded is not None and recorded != rulebook.rulebook_sha256:
        raise ValueError("benchmark metadata screen rulebook hash mismatch")
    return BenchmarkMetadataScreenRulebookInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        rulebook=rulebook,
    )


def inspect_benchmark_metadata_screen_rulebook(
    rulebook: BenchmarkMetadataScreenRulebookInspection,
    scope: BenchmarkMetadataScopeInspection,
) -> BenchmarkMetadataScreenRulebookReport:
    """Prove rule coverage using only control files, before source content is opened."""

    policy = rulebook.rulebook
    frozen_scope = scope.scope
    if (
        policy.project_id != frozen_scope.project_id
        or policy.scope_id != frozen_scope.scope_id
        or policy.scope_file_sha256 != scope.file_sha256
    ):
        raise ValueError("benchmark screen rulebook differs from its frozen scope")
    codes = {rule.exclusion_code for rule in policy.rules}
    if codes != set(frozen_scope.exclusion_codes):
        raise ValueError("benchmark screen rulebook must cover every scope exclusion code")
    required_fields = set(frozen_scope.required_screen_fields)
    rule_fields = {field for rule in policy.rules for field in rule.evidence_fields}
    if not rule_fields.issubset(required_fields):
        raise ValueError("benchmark screen rulebook references a field outside the frozen scope")
    if rule_fields != required_fields:
        raise ValueError("benchmark screen rulebook must use every frozen screen field")
    if not set(policy.allocation_policy.strata_fields).issubset(required_fields):
        raise ValueError("benchmark allocation strata fields are outside the frozen scope")
    expected_allocation = codes & _POST_ELIGIBILITY_CODES
    observed_allocation = {
        rule.exclusion_code
        for rule in policy.rules
        if rule.role is BenchmarkScreenRuleRole.ALLOCATION
    }
    if observed_allocation != expected_allocation:
        raise ValueError("benchmark allocation rules differ from the frozen post-screen codes")
    eligibility_count = sum(
        rule.role is BenchmarkScreenRuleRole.ELIGIBILITY for rule in policy.rules
    )
    if eligibility_count < 1:
        raise ValueError("benchmark screen rulebook requires scientific eligibility rules")
    return BenchmarkMetadataScreenRulebookReport(
        rulebook_id=policy.rulebook_id,
        rulebook_sha256=policy.rulebook_sha256,
        scope_id=policy.scope_id,
        scope_file_sha256=scope.file_sha256,
        eligibility_rule_count=eligibility_count,
        allocation_rule_codes=tuple(sorted(observed_allocation)),
        required_screen_fields=tuple(sorted(required_fields)),
    )


def load_benchmark_metadata_screen_decisions(
    path: str | Path,
) -> BenchmarkMetadataScreenDecisionPackageInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata screen decisions")
    recorded = payload.pop("package_sha256", None)
    package = BenchmarkMetadataScreenDecisionPackage.model_validate(payload)
    if recorded is not None and recorded != package.package_sha256:
        raise ValueError("benchmark metadata screen decision-package hash mismatch")
    return BenchmarkMetadataScreenDecisionPackageInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        package=package,
    )


def save_benchmark_metadata_screen_decisions(
    package: BenchmarkMetadataScreenDecisionPackage,
    path: str | Path,
) -> Path:
    return _write_new_json(path, package.model_dump_json(indent=2) + "\n")


def screen_benchmark_metadata_population(
    population: BenchmarkMetadataPopulationChainInspection,
    rulebook: BenchmarkMetadataScreenRulebookInspection,
    decisions: BenchmarkMetadataScreenDecisionPackageInspection,
    *,
    workspace_root: str | Path,
    screened_at: datetime,
    allow_projected_metadata_read: bool,
) -> BenchmarkMetadataScreeningReport:
    """Compile every record/rule decision without opening raw benchmark sources."""

    if not allow_projected_metadata_read:
        raise ValueError("benchmark screening requires --allow-projected-metadata-read")
    root = Path(workspace_root).resolve(strict=True)
    projected = population.population.population
    policy = rulebook.rulebook
    package = decisions.package
    scope = load_benchmark_metadata_scope(
        _contained_locator(root, population.plan.plan.scope_locator, "benchmark metadata scope")
    )
    rulebook_report = inspect_benchmark_metadata_screen_rulebook(rulebook, scope)
    if (
        package.project_id != projected.project_id
        or package.scope_id != projected.scope_id
        or policy.project_id != projected.project_id
        or policy.scope_id != projected.scope_id
        or package.population_file_sha256 != population.population.file_sha256
        or package.population_sha256 != projected.population_sha256
        or package.rulebook_file_sha256 != rulebook.file_sha256
        or package.rulebook_sha256 != policy.rulebook_sha256
    ):
        raise ValueError("benchmark screen decision package differs from its controls")
    if screened_at.utcoffset() is None:
        raise ValueError("benchmark screening timestamp must include a timezone")
    if policy.frozen_at > population.audit.report.audited_at:
        raise ValueError("benchmark screen rulebook was not frozen before metadata content read")
    if package.frozen_at < projected.projected_at or screened_at < package.frozen_at:
        raise ValueError("benchmark screen decisions precede their projected population")

    eligibility_rules = {
        rule.exclusion_code: rule
        for rule in policy.rules
        if rule.role is BenchmarkScreenRuleRole.ELIGIBILITY
    }
    records = {record.record_id: record for record in projected.records}
    expected_pairs = {
        (record_id, exclusion_code) for record_id in records for exclusion_code in eligibility_rules
    }
    observed_pairs = {
        (decision.record_id, decision.exclusion_code) for decision in package.decisions
    }
    if observed_pairs != expected_pairs:
        raise ValueError("benchmark screen decisions must cover every record and eligibility rule")

    receipt = load_dataset_acquisition_receipt(
        _contained_locator(root, population.plan.plan.receipt_locator, "acquisition receipt")
    )
    raw_root = _resolve_beneath(root, receipt.receipt.destination_root)
    if raw_root is None:
        raise ValueError("benchmark metadata acquisition root escaped the workspace")
    forbidden_evidence_paths = {
        population.population.path,
        population.plan.path,
        population.approval.path,
        rulebook.path,
        decisions.path,
        *(
            _contained_locator(root, locator, "benchmark screening control")
            for locator in (
                population.plan.plan.scope_locator,
                population.plan.plan.request_locator,
                population.plan.plan.receipt_locator,
                population.plan.plan.audit_report_locator,
            )
        ),
    }
    evidence_cache: dict[tuple[str, str], bool] = {}
    by_record: dict[str, list[BenchmarkRecordRuleDecision]] = {
        record_id: [] for record_id in records
    }
    bound_evidence_read = False
    for decision in package.decisions:
        rule = eligibility_rules[decision.exclusion_code]
        record = records[decision.record_id]
        _validate_decision_semantics(decision, rule, record)
        for binding in decision.evidence_bindings:
            key = (binding.path, binding.sha256)
            if key not in evidence_cache:
                evidence_cache[key] = _binding_verified(
                    binding,
                    root,
                    forbidden_paths=forbidden_evidence_paths,
                    raw_root=raw_root,
                )
            if not evidence_cache[key]:
                raise ValueError("benchmark screen assessment evidence binding is invalid")
            bound_evidence_read = True
        by_record[decision.record_id].append(decision)

    item_reports: list[BenchmarkMetadataScreenItemReport] = []
    for record_id in sorted(records):
        record_decisions = by_record[record_id]
        exclusions = tuple(
            sorted(
                decision.exclusion_code
                for decision in record_decisions
                if decision.verdict is BenchmarkScreenVerdict.EXCLUDE
            )
        )
        unresolved = tuple(
            sorted(
                decision.exclusion_code
                for decision in record_decisions
                if decision.verdict is BenchmarkScreenVerdict.CANNOT_ASSESS
            )
        )
        disposition = (
            BenchmarkRecordScreenDisposition.EXCLUDED
            if exclusions
            else BenchmarkRecordScreenDisposition.BLOCKED
            if unresolved
            else BenchmarkRecordScreenDisposition.ELIGIBLE
        )
        item_reports.append(
            BenchmarkMetadataScreenItemReport(
                record_id=record_id,
                disposition=disposition,
                exclusion_codes=exclusions,
                unresolved_codes=unresolved,
            )
        )
    eligible = tuple(
        item.record_id
        for item in item_reports
        if item.disposition is BenchmarkRecordScreenDisposition.ELIGIBLE
    )
    excluded = tuple(
        item.record_id
        for item in item_reports
        if item.disposition is BenchmarkRecordScreenDisposition.EXCLUDED
    )
    blocked = tuple(
        item.record_id
        for item in item_reports
        if item.disposition is BenchmarkRecordScreenDisposition.BLOCKED
    )
    return BenchmarkMetadataScreeningReport(
        project_id=projected.project_id,
        scope_id=projected.scope_id,
        population_locator=_relative_locator(
            root, population.population.path, "benchmark metadata population"
        ),
        population_file_sha256=population.population.file_sha256,
        population_sha256=projected.population_sha256,
        rulebook_locator=_relative_locator(root, rulebook.path, "benchmark screen rulebook"),
        rulebook_file_sha256=rulebook.file_sha256,
        rulebook_sha256=policy.rulebook_sha256,
        decision_package_locator=_relative_locator(
            root, decisions.path, "benchmark screen decisions"
        ),
        decision_package_file_sha256=decisions.file_sha256,
        decision_package_sha256=package.package_sha256,
        screening_implementation_sha256=_module_sha256(),
        screened_at=screened_at,
        record_count=len(records),
        eligibility_rule_count=rulebook_report.eligibility_rule_count,
        allocation_rule_codes=rulebook_report.allocation_rule_codes,
        eligible_record_ids=eligible,
        excluded_record_ids=excluded,
        blocked_record_ids=blocked,
        items=tuple(item_reports),
        ready_for_allocation_proposal=bool(eligible) and not blocked,
        bound_assessment_evidence_read=bound_evidence_read,
    )


def save_benchmark_metadata_screening_report(
    report: BenchmarkMetadataScreeningReport,
    path: str | Path,
) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_screening_report(
    path: str | Path,
) -> BenchmarkMetadataScreeningReportInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata screening report")
    recorded = payload.pop("report_sha256", None)
    report = BenchmarkMetadataScreeningReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("benchmark metadata screening report hash mismatch")
    return BenchmarkMetadataScreeningReportInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


def inspect_benchmark_metadata_screening_chain(
    path: str | Path,
    *,
    workspace_root: str | Path,
) -> BenchmarkMetadataScreeningChainInspection:
    """Replay screening controls without reopening raw metadata or assessment evidence."""

    root = Path(workspace_root).resolve(strict=True)
    report = load_benchmark_metadata_screening_report(path)
    screened = report.report
    population = inspect_benchmark_metadata_population_chain(
        _contained_locator(root, screened.population_locator, "benchmark metadata population"),
        workspace_root=root,
    )
    rulebook = load_benchmark_metadata_screen_rulebook(
        _contained_locator(root, screened.rulebook_locator, "benchmark screen rulebook")
    )
    decisions = load_benchmark_metadata_screen_decisions(
        _contained_locator(root, screened.decision_package_locator, "benchmark screen decisions")
    )
    if (
        report.path
        != _contained_locator(
            root,
            _relative_locator(root, report.path, "benchmark metadata screening report"),
            "benchmark metadata screening report",
        )
        or population.population.file_sha256 != screened.population_file_sha256
        or population.population.population.population_sha256 != screened.population_sha256
        or rulebook.file_sha256 != screened.rulebook_file_sha256
        or rulebook.rulebook.rulebook_sha256 != screened.rulebook_sha256
        or decisions.file_sha256 != screened.decision_package_file_sha256
        or decisions.package.package_sha256 != screened.decision_package_sha256
        or decisions.package.population_file_sha256 != screened.population_file_sha256
        or decisions.package.population_sha256 != screened.population_sha256
        or decisions.package.rulebook_file_sha256 != screened.rulebook_file_sha256
        or decisions.package.rulebook_sha256 != screened.rulebook_sha256
        or screened.project_id != population.population.population.project_id
        or screened.scope_id != population.population.population.scope_id
        or decisions.package.project_id != screened.project_id
        or decisions.package.scope_id != screened.scope_id
    ):
        raise ValueError("benchmark metadata screening control chain differs")
    scope = load_benchmark_metadata_scope(
        _contained_locator(root, population.plan.plan.scope_locator, "benchmark metadata scope")
    )
    rulebook_report = inspect_benchmark_metadata_screen_rulebook(rulebook, scope)
    if (
        screened.record_count != population.population.population.record_count
        or screened.eligibility_rule_count != rulebook_report.eligibility_rule_count
        or screened.allocation_rule_codes != rulebook_report.allocation_rule_codes
    ):
        raise ValueError("benchmark metadata screening summary differs from its controls")
    audited_at = population.audit.report.audited_at
    projected_at = population.population.population.projected_at
    if (
        rulebook.rulebook.frozen_at > audited_at
        or decisions.package.frozen_at < projected_at
        or screened.screened_at < decisions.package.frozen_at
    ):
        raise ValueError("benchmark metadata screening chronology differs from its controls")
    eligibility_rules = {
        rule.exclusion_code: rule
        for rule in rulebook.rulebook.rules
        if rule.role is BenchmarkScreenRuleRole.ELIGIBILITY
    }
    expected_pairs = {
        (record.record_id, code)
        for record in population.population.population.records
        for code in eligibility_rules
    }
    if {
        (decision.record_id, decision.exclusion_code) for decision in decisions.package.decisions
    } != expected_pairs:
        raise ValueError("benchmark metadata screening decisions are incomplete")
    if any(
        decision.evidence_fields != eligibility_rules[decision.exclusion_code].evidence_fields
        or decision.assessment_authority
        is not eligibility_rules[decision.exclusion_code].assessment_authority
        for decision in decisions.package.decisions
    ):
        raise ValueError("benchmark metadata screening decisions differ from frozen rules")
    records = {record.record_id: record for record in population.population.population.records}
    for decision in decisions.package.decisions:
        _validate_decision_semantics(
            decision,
            eligibility_rules[decision.exclusion_code],
            records[decision.record_id],
        )
    decisions_by_record: dict[str, list[BenchmarkRecordRuleDecision]] = {
        record.record_id: [] for record in population.population.population.records
    }
    for decision in decisions.package.decisions:
        decisions_by_record[decision.record_id].append(decision)
    expected_items = tuple(
        _summarize_record_decisions(record_id, decisions_by_record[record_id])
        for record_id in sorted(decisions_by_record)
    )
    if screened.items != expected_items:
        raise ValueError("benchmark metadata screening report differs from frozen decisions")
    if screened.bound_assessment_evidence_read != any(
        decision.evidence_bindings for decision in decisions.package.decisions
    ):
        raise ValueError("benchmark metadata screening evidence-read summary differs")
    return BenchmarkMetadataScreeningChainInspection(
        report=report,
        population=population,
        rulebook=rulebook,
        decisions=decisions,
        screening_implementation_current=(
            screened.screening_implementation_sha256 == _module_sha256()
        ),
    )


def _projected_field_has_evidence(field: object) -> bool:
    present = getattr(field, "source_field_present", False)
    values = getattr(field, "values", ())
    return bool(
        present
        and any(
            value is not None and (not isinstance(value, str) or bool(value.strip()))
            for value in values
        )
    )


def _validate_decision_semantics(
    decision: BenchmarkRecordRuleDecision,
    rule: BenchmarkMetadataScreenRule,
    record: ProjectedBenchmarkMetadataRecord,
) -> None:
    if decision.evidence_fields != rule.evidence_fields:
        raise ValueError("benchmark screen decision fields differ from the frozen rule")
    if decision.assessment_authority is not rule.assessment_authority:
        raise ValueError("benchmark screen decision authority differs from the frozen rule")
    if (
        rule.evidence_mode is BenchmarkScreenEvidenceMode.PROJECTED_METADATA
        and decision.evidence_bindings
    ):
        raise ValueError("metadata-only benchmark decisions cannot add external evidence")
    fields = {field.semantic_field: field for field in record.fields}
    missing = tuple(
        field_name
        for field_name in rule.evidence_fields
        if not _projected_field_has_evidence(fields[field_name])
    )
    if missing and not decision.evidence_bindings:
        expected_missing_verdict = (
            BenchmarkScreenVerdict.EXCLUDE
            if rule.missing_evidence_disposition is BenchmarkScreenMissingDisposition.EXCLUDE
            else BenchmarkScreenVerdict.CANNOT_ASSESS
        )
        if decision.verdict is not expected_missing_verdict:
            raise ValueError("benchmark screen decision hides missing required evidence")
    elif (
        rule.evidence_mode is BenchmarkScreenEvidenceMode.PROJECTED_METADATA_AND_BOUND_EVIDENCE
        and not decision.evidence_bindings
        and decision.verdict is not BenchmarkScreenVerdict.CANNOT_ASSESS
    ):
        raise ValueError("benchmark screen conclusion lacks required bound evidence")


def _summarize_record_decisions(
    record_id: str,
    decisions: list[BenchmarkRecordRuleDecision],
) -> BenchmarkMetadataScreenItemReport:
    exclusions = tuple(
        sorted(
            decision.exclusion_code
            for decision in decisions
            if decision.verdict is BenchmarkScreenVerdict.EXCLUDE
        )
    )
    unresolved = tuple(
        sorted(
            decision.exclusion_code
            for decision in decisions
            if decision.verdict is BenchmarkScreenVerdict.CANNOT_ASSESS
        )
    )
    disposition = (
        BenchmarkRecordScreenDisposition.EXCLUDED
        if exclusions
        else BenchmarkRecordScreenDisposition.BLOCKED
        if unresolved
        else BenchmarkRecordScreenDisposition.ELIGIBLE
    )
    return BenchmarkMetadataScreenItemReport(
        record_id=record_id,
        disposition=disposition,
        exclusion_codes=exclusions,
        unresolved_codes=unresolved,
    )


def _binding_verified(
    binding: BenchmarkScreenEvidenceBinding,
    root: Path,
    *,
    forbidden_paths: set[Path],
    raw_root: Path,
) -> bool:
    path = _resolve_beneath(root, binding.path)
    if (
        path is None
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > _MAX_EVIDENCE_BYTES
        or path in forbidden_paths
        or path.is_relative_to(raw_root)
    ):
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == binding.sha256


def _relative_locator(root: Path, path: Path, label: str) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must be inside the workspace")
    return resolved.relative_to(root).as_posix()


def _contained_locator(root: Path, locator: str, label: str) -> Path:
    resolved = _resolve_beneath(root, locator)
    if resolved is None or resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} is unavailable or escaped the workspace")
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be normalized and relative")


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    try:
        _validate_relative_path(locator, "workspace locator")
    except ValueError:
        return None
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            return None
    resolved = current.resolve(strict=False)
    return resolved if resolved.is_relative_to(root) else None


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


class DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _write_new_json(path: str | Path, text: str) -> Path:
    target = Path(path)
    if target.is_symlink() or target.exists():
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
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _module_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


__all__ = [
    "BenchmarkMetadataAllocationPolicy",
    "BenchmarkMetadataScreenDecisionPackage",
    "BenchmarkMetadataScreenDecisionPackageInspection",
    "BenchmarkMetadataScreenItemReport",
    "BenchmarkMetadataScreenRule",
    "BenchmarkMetadataScreenRulebook",
    "BenchmarkMetadataScreenRulebookInspection",
    "BenchmarkMetadataScreenRulebookReport",
    "BenchmarkMetadataScreeningChainInspection",
    "BenchmarkMetadataScreeningReport",
    "BenchmarkMetadataScreeningReportInspection",
    "BenchmarkRecordRuleDecision",
    "BenchmarkRecordScreenDisposition",
    "BenchmarkScreenAssessmentAuthority",
    "BenchmarkScreenEvidenceBinding",
    "BenchmarkScreenEvidenceMode",
    "BenchmarkScreenMissingDisposition",
    "BenchmarkScreenRuleRole",
    "BenchmarkScreenVerdict",
    "inspect_benchmark_metadata_screen_rulebook",
    "inspect_benchmark_metadata_screening_chain",
    "load_benchmark_metadata_screen_decisions",
    "load_benchmark_metadata_screen_rulebook",
    "load_benchmark_metadata_screening_report",
    "save_benchmark_metadata_screen_decisions",
    "save_benchmark_metadata_screening_report",
    "screen_benchmark_metadata_population",
]

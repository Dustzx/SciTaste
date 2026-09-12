"""Powered allocation from a complete benchmark screen to a frozen task set."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.benchmark_metadata_projection import ProjectedBenchmarkMetadataRecord
from scitaste.evaluation.benchmark_metadata_screening import (
    BenchmarkMetadataScreeningChainInspection,
    inspect_benchmark_metadata_screening_chain,
)
from scitaste.evaluation.clustered_power import (
    ClusteredPowerReportInspection,
    ClusteredPowerRequestInspection,
    PowerAnalysisFamily,
    PowerIndependentUnit,
    load_clustered_power_report,
    load_clustered_power_request,
    plan_clustered_power,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 64 * 1_048_576
_ALGORITHM_ID = "cluster-distinct-stratified-sha256-v1"


class BenchmarkAllocationStratumInventory(BaseModel):
    """Population counts only; an allocation plan contains no selected record IDs."""

    model_config = _CONFIG

    stratum_id: str = Field(pattern=_ID)
    values: dict[str, str] = Field(min_length=1, max_length=10)
    eligible_record_count: int = Field(gt=0)
    independent_unit_count: int = Field(gt=0)

    @model_validator(mode="after")
    def values_are_ordered(self) -> BenchmarkAllocationStratumInventory:
        if tuple(self.values) != tuple(sorted(self.values)):
            raise ValueError("benchmark allocation stratum fields must be sorted")
        if self.independent_unit_count > self.eligible_record_count:
            raise ValueError("benchmark allocation stratum units exceed its records")
        return self


class BenchmarkMetadataAllocationPlan(BaseModel):
    """Outcome-blind powered allocation plan; no task identity is selected yet."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    screening_report_locator: str = Field(min_length=1, max_length=1_000)
    screening_report_file_sha256: str = Field(pattern=_SHA256)
    screening_report_sha256: str = Field(pattern=_SHA256)
    population_sha256: str = Field(pattern=_SHA256)
    rulebook_sha256: str = Field(pattern=_SHA256)
    decision_package_sha256: str = Field(pattern=_SHA256)
    power_report_locator: str = Field(min_length=1, max_length=1_000)
    power_report_file_sha256: str = Field(pattern=_SHA256)
    power_report_sha256: str = Field(pattern=_SHA256)
    power_request_locator: str = Field(min_length=1, max_length=1_000)
    power_request_file_sha256: str = Field(pattern=_SHA256)
    power_request_sha256: str = Field(pattern=_SHA256)
    formal_study_id: str = Field(pattern=_ID)
    allocation_output_locator: str = Field(min_length=1, max_length=1_000)
    allocation_implementation_sha256: str = Field(pattern=_SHA256)
    algorithm_id: Literal[_ALGORITHM_ID] = _ALGORITHM_ID
    created_at: datetime
    random_seed: int = Field(ge=0, le=2**63 - 1)
    random_seed_source: Literal["owner-reviewed-allocation-plan"] = "owner-reviewed-allocation-plan"
    cluster_field: str = Field(pattern=_ID)
    strata_fields: tuple[str, ...] = Field(min_length=2, max_length=10)
    balance_fields: tuple[str, ...] = Field(min_length=1, max_length=9)
    eligible_record_count: int = Field(ge=0)
    allocatable_record_count: int = Field(ge=0)
    excluded_record_count: int = Field(ge=0)
    blocked_record_count: int = Field(ge=0)
    available_independent_units: int = Field(ge=0)
    powered_independent_units: int = Field(gt=0)
    minimum_per_nonempty_stratum: Literal[1] = 1
    strata: tuple[BenchmarkAllocationStratumInventory, ...] = ()
    blocker_codes: tuple[str, ...] = ()
    ready_for_owner_approval: bool
    complete_screen_required: Literal[True] = True
    source_group_distinct_allocation_required: Literal[True] = True
    allocation_without_replacement: Literal[True] = True
    unsampled_eligible_records_must_be_preserved: Literal[True] = True
    pilot_power_report_consulted: Literal[True] = True
    formal_outcomes_consulted: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    current_host_inventory_consulted: Literal[False] = False
    model_calls_performed: Literal[False] = False
    allocation_performed: Literal[False] = False
    task_selection_performed: Literal[False] = False
    authorizes_allocation: Literal[False] = False
    authorizes_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def created_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark allocation plan timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def controls_and_readiness_are_consistent(self) -> BenchmarkMetadataAllocationPlan:
        for locator in (
            self.screening_report_locator,
            self.power_report_locator,
            self.power_request_locator,
            self.allocation_output_locator,
        ):
            _validate_relative_path(locator, "benchmark allocation control locator")
        if self.strata_fields != tuple(sorted(set(self.strata_fields))):
            raise ValueError("benchmark allocation strata fields must be sorted and unique")
        if self.balance_fields != tuple(sorted(set(self.balance_fields))):
            raise ValueError("benchmark allocation balance fields must be sorted and unique")
        if self.cluster_field not in self.strata_fields:
            raise ValueError("benchmark allocation cluster field is outside its strata")
        if set(self.balance_fields) != set(self.strata_fields) - {self.cluster_field}:
            raise ValueError("benchmark allocation balance fields differ from its strata")
        stratum_ids = tuple(item.stratum_id for item in self.strata)
        if stratum_ids != tuple(sorted(set(stratum_ids))):
            raise ValueError("benchmark allocation strata must be sorted and unique")
        if self.allocatable_record_count > self.eligible_record_count:
            raise ValueError("benchmark allocatable records exceed screened eligibility")
        if sum(item.eligible_record_count for item in self.strata) != (
            self.allocatable_record_count
        ):
            raise ValueError("benchmark allocation stratum records differ from usable evidence")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("benchmark allocation blockers must be sorted and unique")
        if self.ready_for_owner_approval != (not self.blocker_codes):
            raise ValueError("benchmark allocation readiness differs from its blockers")
        if self.ready_for_owner_approval and (
            self.allocatable_record_count != self.eligible_record_count
            or sum(item.independent_unit_count for item in self.strata)
            != self.available_independent_units
        ):
            raise ValueError("ready benchmark allocation does not cover all eligible evidence")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class BenchmarkMetadataAllocationPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: BenchmarkMetadataAllocationPlan


class BenchmarkMetadataAllocationPlanChainInspection(BaseModel):
    """Replayable controls for an allocation plan that has not selected tasks."""

    model_config = _CONFIG

    plan: BenchmarkMetadataAllocationPlanInspection
    screening: BenchmarkMetadataScreeningChainInspection
    power_report: ClusteredPowerReportInspection
    power_request: ClusteredPowerRequestInspection
    allocation_implementation_current: bool


class BenchmarkMetadataAllocationApproval(BaseModel):
    """Owner authority for one exact, powered, deterministic task allocation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    plan_id: str = Field(pattern=_ID)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["powered-screened-benchmark-allocation-only"]
    authorizes_deterministic_allocation: Literal[True] = True
    authorizes_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark allocation approval timestamp must include a timezone")
        return value

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class BenchmarkMetadataAllocationApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: BenchmarkMetadataAllocationApproval


class AllocatedBenchmarkRecord(BaseModel):
    model_config = _CONFIG

    record_id: str = Field(pattern=_ID)
    source_group: str = Field(min_length=1, max_length=200)
    stratum_id: str = Field(pattern=_ID)
    stratum_values: dict[str, str] = Field(min_length=1, max_length=9)
    selection_priority_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def stratum_values_are_ordered(self) -> AllocatedBenchmarkRecord:
        if tuple(self.stratum_values) != tuple(sorted(self.stratum_values)):
            raise ValueError("allocated benchmark stratum fields must be sorted")
        return self


class BenchmarkAllocationStratumResult(BaseModel):
    model_config = _CONFIG

    stratum_id: str = Field(pattern=_ID)
    stratum_values: dict[str, str] = Field(min_length=1, max_length=9)
    available_independent_units: int = Field(gt=0)
    selected_independent_units: int = Field(gt=0)
    unsampled_independent_units: int = Field(ge=0)

    @model_validator(mode="after")
    def stratum_partition_is_complete(self) -> BenchmarkAllocationStratumResult:
        if tuple(self.stratum_values) != tuple(sorted(self.stratum_values)):
            raise ValueError("allocated benchmark stratum fields must be sorted")
        if self.available_independent_units != (
            self.selected_independent_units + self.unsampled_independent_units
        ):
            raise ValueError("benchmark allocation stratum partition differs")
        return self


class BenchmarkMetadataAllocationReport(BaseModel):
    """Frozen task identities with the complete screened population still visible."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    plan_locator: str = Field(min_length=1, max_length=1_000)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_locator: str = Field(min_length=1, max_length=1_000)
    approval_file_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    screening_report_sha256: str = Field(pattern=_SHA256)
    population_sha256: str = Field(pattern=_SHA256)
    power_report_sha256: str = Field(pattern=_SHA256)
    allocation_implementation_sha256: str = Field(pattern=_SHA256)
    algorithm_id: Literal[_ALGORITHM_ID] = _ALGORITHM_ID
    allocated_at: datetime
    random_seed: int = Field(ge=0, le=2**63 - 1)
    cluster_field: str = Field(pattern=_ID)
    balance_fields: tuple[str, ...] = Field(min_length=1, max_length=9)
    screened_record_count: int = Field(gt=0)
    powered_independent_units: int = Field(gt=0)
    available_independent_units: int = Field(gt=0)
    selected_records: tuple[AllocatedBenchmarkRecord, ...] = Field(min_length=1)
    unsampled_eligible_record_ids: tuple[str, ...]
    excluded_record_ids: tuple[str, ...]
    blocked_record_ids: tuple[str, ...]
    strata: tuple[BenchmarkAllocationStratumResult, ...] = Field(min_length=1)
    formal_task_set_sha256: str = Field(pattern=_SHA256)
    complete_screen_preserved: Literal[True] = True
    source_groups_unique: Literal[True] = True
    allocation_without_replacement: Literal[True] = True
    powered_sample_size_satisfied: Literal[True] = True
    pilot_power_report_consulted: Literal[True] = True
    formal_outcomes_consulted: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    current_host_inventory_consulted: Literal[False] = False
    model_calls_performed: Literal[False] = False
    allocation_performed: Literal[True] = True
    task_selection_frozen: Literal[True] = True
    asset_download_performed: Literal[False] = False
    ingestion_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("allocated_at")
    @classmethod
    def allocated_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("benchmark allocation timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def allocation_is_complete_and_powered(self) -> BenchmarkMetadataAllocationReport:
        _validate_relative_path(self.plan_locator, "benchmark allocation plan")
        _validate_relative_path(self.approval_locator, "benchmark allocation approval")
        record_ids = tuple(item.record_id for item in self.selected_records)
        if record_ids != tuple(sorted(set(record_ids))):
            raise ValueError("allocated benchmark records must be sorted and unique")
        source_groups = tuple(item.source_group for item in self.selected_records)
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("allocated benchmark source groups must be unique")
        if len(record_ids) != self.powered_independent_units:
            raise ValueError("benchmark allocation differs from powered sample size")
        for values, label in (
            (self.unsampled_eligible_record_ids, "unsampled eligible records"),
            (self.excluded_record_ids, "excluded records"),
            (self.blocked_record_ids, "blocked records"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"benchmark allocation {label} must be sorted and unique")
        partitions = (
            set(record_ids),
            set(self.unsampled_eligible_record_ids),
            set(self.excluded_record_ids),
            set(self.blocked_record_ids),
        )
        if any(
            partitions[left] & partitions[right]
            for left in range(len(partitions))
            for right in range(left + 1, len(partitions))
        ):
            raise ValueError("benchmark allocation population partitions overlap")
        if len(set().union(*partitions)) != self.screened_record_count:
            raise ValueError("benchmark allocation does not preserve the screened population")
        stratum_ids = tuple(item.stratum_id for item in self.strata)
        if stratum_ids != tuple(sorted(set(stratum_ids))):
            raise ValueError("benchmark allocation stratum results must be sorted and unique")
        if sum(item.available_independent_units for item in self.strata) != (
            self.available_independent_units
        ):
            raise ValueError("benchmark allocation available units differ from strata")
        if sum(item.selected_independent_units for item in self.strata) != len(record_ids):
            raise ValueError("benchmark allocation selected units differ from strata")
        expected_task_set = _canonical_sha256(
            {
                "algorithm_id": self.algorithm_id,
                "plan_sha256": self.plan_sha256,
                "population_sha256": self.population_sha256,
                "power_report_sha256": self.power_report_sha256,
                "random_seed": self.random_seed,
                "selected_records": [
                    item.model_dump(mode="json") for item in self.selected_records
                ],
            }
        )
        if self.formal_task_set_sha256 != expected_task_set:
            raise ValueError("benchmark formal task-set hash differs")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class BenchmarkMetadataAllocationReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: BenchmarkMetadataAllocationReport


class BenchmarkMetadataAllocationChainInspection(BaseModel):
    model_config = _CONFIG

    report: BenchmarkMetadataAllocationReportInspection
    plan: BenchmarkMetadataAllocationPlanInspection
    approval: BenchmarkMetadataAllocationApprovalInspection
    screening: BenchmarkMetadataScreeningChainInspection
    power_report: ClusteredPowerReportInspection
    power_request: ClusteredPowerRequestInspection
    allocation_implementation_current: bool


def plan_benchmark_metadata_allocation(
    screening: BenchmarkMetadataScreeningChainInspection,
    power_report: ClusteredPowerReportInspection,
    power_request: ClusteredPowerRequestInspection,
    *,
    workspace_root: str | Path,
    plan_id: str,
    random_seed: int,
    cluster_field: str,
    allocation_output_locator: str,
    created_at: datetime,
    allow_projected_metadata_read: bool,
) -> BenchmarkMetadataAllocationPlan:
    """Create a powered plan with population counts but no selected record identities."""

    if not allow_projected_metadata_read:
        raise ValueError("benchmark allocation planning requires --allow-projected-metadata-read")
    root = Path(workspace_root).resolve(strict=True)
    _verify_power_chain(power_report, power_request, root)
    screened = screening.report.report
    if created_at.utcoffset() is None or created_at < screened.screened_at:
        raise ValueError("benchmark allocation plan cannot precede its complete screen")
    rulebook = screening.rulebook.rulebook
    power = power_report.report
    population = screening.population.population.population
    blockers: set[str] = set()
    if not screened.ready_for_allocation_proposal or screened.blocked_record_ids:
        blockers.add("screening-not-allocation-ready")
    if not screening.screening_implementation_current:
        blockers.add("screening-implementation-drift")
    if not screening.population.projection_implementation_current:
        blockers.add("projection-implementation-drift")
    if power.family is not PowerAnalysisFamily.OBJECTIVE_H3:
        blockers.add("wrong-power-family")
    if power.independent_unit is not PowerIndependentUnit.HELD_OUT_TASK:
        blockers.add("wrong-independent-unit")
    if not power.ready_for_formal_sample_size_freeze:
        blockers.add("power-not-formal-freeze-ready")
    policy = rulebook.allocation_policy
    strata_fields = policy.strata_fields
    if cluster_field not in strata_fields:
        raise ValueError("benchmark allocation cluster field is outside the frozen policy")
    balance_fields = tuple(field for field in strata_fields if field != cluster_field)
    if not balance_fields:
        raise ValueError("benchmark allocation requires a non-cluster balance field")

    records = {record.record_id: record for record in population.records}
    stratum_records: dict[tuple[tuple[str, str], ...], list[str]] = {}
    stratum_clusters: dict[tuple[tuple[str, str], ...], set[str]] = {}
    cluster_strata: dict[str, set[tuple[tuple[str, str], ...]]] = {}
    for record_id in screened.eligible_record_ids:
        values = _allocation_values(records[record_id], strata_fields)
        if values is None:
            blockers.add("missing-allocation-field-evidence")
            continue
        cluster = values[cluster_field]
        stratum = tuple((field, values[field]) for field in balance_fields)
        stratum_records.setdefault(stratum, []).append(record_id)
        stratum_clusters.setdefault(stratum, set()).add(cluster)
        cluster_strata.setdefault(cluster, set()).add(stratum)
    if any(len(values) != 1 for values in cluster_strata.values()):
        blockers.add("cluster-spans-strata")
    available_units = len(cluster_strata)
    powered_units = power.recommended_independent_units
    if available_units < powered_units:
        blockers.add("too-few-independent-units")
    if stratum_records and powered_units < len(stratum_records):
        blockers.add("sample-too-small-for-strata")
    strata = tuple(
        BenchmarkAllocationStratumInventory(
            stratum_id=_stratum_id(stratum),
            values=dict(stratum),
            eligible_record_count=len(stratum_records[stratum]),
            independent_unit_count=len(stratum_clusters[stratum]),
        )
        for stratum in sorted(stratum_records)
    )
    return BenchmarkMetadataAllocationPlan(
        plan_id=plan_id,
        project_id=screened.project_id,
        scope_id=screened.scope_id,
        screening_report_locator=_relative_locator(
            root, screening.report.path, "benchmark screening report"
        ),
        screening_report_file_sha256=screening.report.file_sha256,
        screening_report_sha256=screened.report_sha256,
        population_sha256=screened.population_sha256,
        rulebook_sha256=screened.rulebook_sha256,
        decision_package_sha256=screened.decision_package_sha256,
        power_report_locator=_relative_locator(root, power_report.path, "clustered power report"),
        power_report_file_sha256=power_report.file_sha256,
        power_report_sha256=power.report_sha256,
        power_request_locator=_relative_locator(
            root, power_request.path, "clustered power request"
        ),
        power_request_file_sha256=power_request.file_sha256,
        power_request_sha256=power_request.request.request_sha256,
        formal_study_id=power.formal_study_id,
        allocation_output_locator=allocation_output_locator,
        allocation_implementation_sha256=_module_sha256(),
        created_at=created_at,
        random_seed=random_seed,
        cluster_field=cluster_field,
        strata_fields=strata_fields,
        balance_fields=balance_fields,
        eligible_record_count=len(screened.eligible_record_ids),
        allocatable_record_count=sum(len(records) for records in stratum_records.values()),
        excluded_record_count=len(screened.excluded_record_ids),
        blocked_record_count=len(screened.blocked_record_ids),
        available_independent_units=available_units,
        powered_independent_units=powered_units,
        strata=strata,
        blocker_codes=tuple(sorted(blockers)),
        ready_for_owner_approval=not blockers,
    )


def approve_benchmark_metadata_allocation(
    plan: BenchmarkMetadataAllocationPlanInspection,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> BenchmarkMetadataAllocationApproval:
    if confirmed_plan_sha256 != plan.plan.plan_sha256:
        raise ValueError("confirmed benchmark allocation plan hash differs")
    if plan.plan.allocation_implementation_sha256 != _module_sha256():
        raise ValueError("benchmark allocation plan implementation has drifted")
    if not plan.plan.ready_for_owner_approval:
        raise ValueError("blocked benchmark allocation plan cannot be approved")
    if approved_at.utcoffset() is None or approved_at < plan.plan.created_at:
        raise ValueError("benchmark allocation approval cannot precede its plan")
    return BenchmarkMetadataAllocationApproval(
        approval_id=f"{plan.plan.plan_id}-approval",
        plan_id=plan.plan.plan_id,
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="powered-screened-benchmark-allocation-only",
    )


def allocate_benchmark_metadata_population(
    screening: BenchmarkMetadataScreeningChainInspection,
    power_report: ClusteredPowerReportInspection,
    power_request: ClusteredPowerRequestInspection,
    plan: BenchmarkMetadataAllocationPlanInspection,
    approval: BenchmarkMetadataAllocationApprovalInspection,
    *,
    workspace_root: str | Path,
    allocated_at: datetime,
    allow_projected_metadata_read: bool,
    _inspection_replay: bool = False,
) -> BenchmarkMetadataAllocationReport:
    """Freeze a powered, source-group-distinct task set after exact owner approval."""

    root = Path(workspace_root).resolve(strict=True)
    rebuilt = plan_benchmark_metadata_allocation(
        screening,
        power_report,
        power_request,
        workspace_root=root,
        plan_id=plan.plan.plan_id,
        random_seed=plan.plan.random_seed,
        cluster_field=plan.plan.cluster_field,
        allocation_output_locator=plan.plan.allocation_output_locator,
        created_at=plan.plan.created_at,
        allow_projected_metadata_read=allow_projected_metadata_read,
    )
    rebuilt_at_recorded_implementation = rebuilt.model_copy(
        update={
            "allocation_implementation_sha256": plan.plan.allocation_implementation_sha256,
        }
    )
    if rebuilt != plan.plan and (
        not _inspection_replay or rebuilt_at_recorded_implementation != plan.plan
    ):
        raise ValueError("benchmark allocation plan differs from current controls")
    authority = approval.approval
    if (
        authority.plan_id != plan.plan.plan_id
        or authority.plan_file_sha256 != plan.file_sha256
        or authority.plan_sha256 != plan.plan.plan_sha256
    ):
        raise ValueError("benchmark allocation approval differs from its plan")
    if allocated_at.utcoffset() is None or allocated_at < authority.approved_at:
        raise ValueError("benchmark allocation cannot precede its approval")

    screened = screening.report.report
    population = screening.population.population.population
    records = {record.record_id: record for record in population.records}
    candidates: dict[tuple[tuple[str, str], ...], dict[str, list[str]]] = {}
    for record_id in screened.eligible_record_ids:
        values = _require_allocation_values(records[record_id], plan.plan.strata_fields)
        cluster = values[plan.plan.cluster_field]
        stratum = tuple((field, values[field]) for field in plan.plan.balance_fields)
        candidates.setdefault(stratum, {}).setdefault(cluster, []).append(record_id)
    representatives: dict[tuple[tuple[str, str], ...], list[tuple[str, str, str]]] = {}
    for stratum, clusters in candidates.items():
        rows: list[tuple[str, str, str]] = []
        for cluster, record_ids in clusters.items():
            ranked = sorted(
                (
                    _priority(
                        plan.plan, "representative", _stratum_id(stratum), cluster, record_id
                    ),
                    record_id,
                )
                for record_id in record_ids
            )
            priority, record_id = ranked[0]
            rows.append((priority, record_id, cluster))
        representatives[stratum] = sorted(rows)
    quotas = _stratified_quotas(
        {stratum: len(rows) for stratum, rows in representatives.items()},
        plan.plan.powered_independent_units,
        plan.plan,
    )
    selected: list[AllocatedBenchmarkRecord] = []
    stratum_results: list[BenchmarkAllocationStratumResult] = []
    for stratum in sorted(representatives):
        rows = representatives[stratum]
        quota = quotas[stratum]
        values = dict(stratum)
        stratum_id = _stratum_id(stratum)
        for priority, record_id, cluster in rows[:quota]:
            selected.append(
                AllocatedBenchmarkRecord(
                    record_id=record_id,
                    source_group=cluster,
                    stratum_id=stratum_id,
                    stratum_values=values,
                    selection_priority_sha256=priority,
                )
            )
        stratum_results.append(
            BenchmarkAllocationStratumResult(
                stratum_id=stratum_id,
                stratum_values=values,
                available_independent_units=len(rows),
                selected_independent_units=quota,
                unsampled_independent_units=len(rows) - quota,
            )
        )
    selected_records = tuple(sorted(selected, key=lambda item: item.record_id))
    selected_ids = {item.record_id for item in selected_records}
    task_set_sha256 = _canonical_sha256(
        {
            "algorithm_id": plan.plan.algorithm_id,
            "plan_sha256": plan.plan.plan_sha256,
            "population_sha256": plan.plan.population_sha256,
            "power_report_sha256": plan.plan.power_report_sha256,
            "random_seed": plan.plan.random_seed,
            "selected_records": [item.model_dump(mode="json") for item in selected_records],
        }
    )
    return BenchmarkMetadataAllocationReport(
        project_id=plan.plan.project_id,
        scope_id=plan.plan.scope_id,
        plan_locator=_relative_locator(root, plan.path, "benchmark allocation plan"),
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        approval_locator=_relative_locator(root, approval.path, "benchmark allocation approval"),
        approval_file_sha256=approval.file_sha256,
        approval_sha256=authority.approval_sha256,
        screening_report_sha256=plan.plan.screening_report_sha256,
        population_sha256=plan.plan.population_sha256,
        power_report_sha256=plan.plan.power_report_sha256,
        allocation_implementation_sha256=_module_sha256(),
        allocated_at=allocated_at,
        random_seed=plan.plan.random_seed,
        cluster_field=plan.plan.cluster_field,
        balance_fields=plan.plan.balance_fields,
        screened_record_count=population.record_count,
        powered_independent_units=plan.plan.powered_independent_units,
        available_independent_units=plan.plan.available_independent_units,
        selected_records=selected_records,
        unsampled_eligible_record_ids=tuple(
            sorted(set(screened.eligible_record_ids) - selected_ids)
        ),
        excluded_record_ids=screened.excluded_record_ids,
        blocked_record_ids=screened.blocked_record_ids,
        strata=tuple(sorted(stratum_results, key=lambda item: item.stratum_id)),
        formal_task_set_sha256=task_set_sha256,
    )


def inspect_benchmark_metadata_allocation_chain(
    path: str | Path,
    *,
    workspace_root: str | Path,
) -> BenchmarkMetadataAllocationChainInspection:
    """Replay screening, power, approval and allocation without raw-source access."""

    root = Path(workspace_root).resolve(strict=True)
    report = load_benchmark_metadata_allocation_report(path)
    allocated = report.report
    plan = load_benchmark_metadata_allocation_plan(
        _contained_locator(root, allocated.plan_locator, "benchmark allocation plan")
    )
    approval = load_benchmark_metadata_allocation_approval(
        _contained_locator(root, allocated.approval_locator, "benchmark allocation approval")
    )
    screening = inspect_benchmark_metadata_screening_chain(
        _contained_locator(
            root,
            plan.plan.screening_report_locator,
            "benchmark screening report",
        ),
        workspace_root=root,
    )
    power_report = load_clustered_power_report(
        _contained_locator(root, plan.plan.power_report_locator, "clustered power report")
    )
    power_request = load_clustered_power_request(
        _contained_locator(root, plan.plan.power_request_locator, "clustered power request")
    )
    rebuilt = allocate_benchmark_metadata_population(
        screening,
        power_report,
        power_request,
        plan,
        approval,
        workspace_root=root,
        allocated_at=allocated.allocated_at,
        allow_projected_metadata_read=True,
        _inspection_replay=True,
    )
    rebuilt_at_recorded_implementation = rebuilt.model_copy(
        update={
            "allocation_implementation_sha256": allocated.allocation_implementation_sha256,
        }
    )
    if rebuilt_at_recorded_implementation != allocated:
        raise ValueError("benchmark allocation report differs from its control chain")
    expected_path = _contained_locator(
        root,
        plan.plan.allocation_output_locator,
        "benchmark allocation report",
    )
    if report.path != expected_path:
        raise ValueError("benchmark allocation report is outside its approved destination")
    return BenchmarkMetadataAllocationChainInspection(
        report=report,
        plan=plan,
        approval=approval,
        screening=screening,
        power_report=power_report,
        power_request=power_request,
        allocation_implementation_current=(
            allocated.allocation_implementation_sha256 == _module_sha256()
        ),
    )


def inspect_benchmark_metadata_allocation_plan_chain(
    path: str | Path,
    *,
    workspace_root: str | Path,
) -> BenchmarkMetadataAllocationPlanChainInspection:
    """Replay a no-selection allocation plan from its complete scientific controls."""

    root = Path(workspace_root).resolve(strict=True)
    plan = load_benchmark_metadata_allocation_plan(path)
    screening = inspect_benchmark_metadata_screening_chain(
        _contained_locator(
            root,
            plan.plan.screening_report_locator,
            "benchmark screening report",
        ),
        workspace_root=root,
    )
    power_report = load_clustered_power_report(
        _contained_locator(root, plan.plan.power_report_locator, "clustered power report")
    )
    power_request = load_clustered_power_request(
        _contained_locator(root, plan.plan.power_request_locator, "clustered power request")
    )
    rebuilt = plan_benchmark_metadata_allocation(
        screening,
        power_report,
        power_request,
        workspace_root=root,
        plan_id=plan.plan.plan_id,
        random_seed=plan.plan.random_seed,
        cluster_field=plan.plan.cluster_field,
        allocation_output_locator=plan.plan.allocation_output_locator,
        created_at=plan.plan.created_at,
        allow_projected_metadata_read=True,
    )
    rebuilt_at_recorded_implementation = rebuilt.model_copy(
        update={
            "allocation_implementation_sha256": plan.plan.allocation_implementation_sha256,
        }
    )
    if rebuilt_at_recorded_implementation != plan.plan:
        raise ValueError("benchmark allocation plan control chain has drifted")
    return BenchmarkMetadataAllocationPlanChainInspection(
        plan=plan,
        screening=screening,
        power_report=power_report,
        power_request=power_request,
        allocation_implementation_current=(
            plan.plan.allocation_implementation_sha256 == _module_sha256()
        ),
    )


def load_benchmark_metadata_allocation_plan(
    path: str | Path,
) -> BenchmarkMetadataAllocationPlanInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata allocation plan")
    recorded = payload.pop("plan_sha256", None)
    plan = BenchmarkMetadataAllocationPlan.model_validate(payload)
    if recorded != plan.plan_sha256:
        raise ValueError("benchmark metadata allocation plan hash mismatch")
    return BenchmarkMetadataAllocationPlanInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def save_benchmark_metadata_allocation_plan(
    plan: BenchmarkMetadataAllocationPlan,
    path: str | Path,
) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_allocation_approval(
    path: str | Path,
) -> BenchmarkMetadataAllocationApprovalInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata allocation approval")
    recorded = payload.pop("approval_sha256", None)
    approval = BenchmarkMetadataAllocationApproval.model_validate(payload)
    if recorded != approval.approval_sha256:
        raise ValueError("benchmark metadata allocation approval hash mismatch")
    return BenchmarkMetadataAllocationApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def save_benchmark_metadata_allocation_approval(
    approval: BenchmarkMetadataAllocationApproval,
    path: str | Path,
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_allocation_report(
    path: str | Path,
) -> BenchmarkMetadataAllocationReportInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata allocation report")
    recorded = payload.pop("report_sha256", None)
    report = BenchmarkMetadataAllocationReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("benchmark metadata allocation report hash mismatch")
    return BenchmarkMetadataAllocationReportInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


def save_benchmark_metadata_allocation_report(
    report: BenchmarkMetadataAllocationReport,
    path: str | Path,
) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def _verify_power_chain(
    report: ClusteredPowerReportInspection,
    request: ClusteredPowerRequestInspection,
    root: Path,
) -> None:
    powered = report.report
    if (
        powered.request_file_sha256 != request.file_sha256
        or powered.request_sha256 != request.request.request_sha256
    ):
        raise ValueError("clustered power report differs from its request")
    rebuilt = plan_clustered_power(request, evidence_root=root)
    if rebuilt != powered:
        raise ValueError("clustered power report differs from its pilot evidence")


def _allocation_values(
    record: ProjectedBenchmarkMetadataRecord,
    fields: tuple[str, ...],
) -> dict[str, str] | None:
    projected = {field.semantic_field: field for field in record.fields}
    values: dict[str, str] = {}
    for field_name in fields:
        field = projected.get(field_name)
        if field is None:
            return None
        if not field.source_field_present or len(field.values) != 1:
            return None
        value = field.values[0]
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
            return None
        values[field_name] = value.strip()
    return dict(sorted(values.items()))


def _require_allocation_values(
    record: ProjectedBenchmarkMetadataRecord,
    fields: tuple[str, ...],
) -> dict[str, str]:
    values = _allocation_values(record, fields)
    if values is None:
        raise ValueError("approved benchmark allocation lost required stratum evidence")
    return values


def _stratum_id(stratum: tuple[tuple[str, str], ...]) -> str:
    return f"stratum-{_canonical_sha256(dict(stratum))[:24]}"


def _priority(
    plan: BenchmarkMetadataAllocationPlan,
    *parts: str,
) -> str:
    value = "\x1f".join(
        (
            plan.algorithm_id,
            str(plan.random_seed),
            plan.screening_report_sha256,
            plan.power_report_sha256,
            *parts,
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _stratified_quotas(
    capacities: dict[tuple[tuple[str, str], ...], int],
    sample_size: int,
    plan: BenchmarkMetadataAllocationPlan,
) -> dict[tuple[tuple[str, str], ...], int]:
    if not capacities or sample_size < len(capacities) or sample_size > sum(capacities.values()):
        raise ValueError("approved benchmark allocation cannot satisfy its strata and sample size")
    quotas = {stratum: 1 for stratum in capacities}
    remaining = sample_size - len(capacities)
    residual_capacity = {stratum: capacity - 1 for stratum, capacity in capacities.items()}
    total_residual = sum(residual_capacity.values())
    if remaining == 0:
        return quotas
    if total_residual < remaining:
        raise ValueError("approved benchmark allocation exceeds residual stratum capacity")
    exact = {
        stratum: remaining * residual / total_residual
        for stratum, residual in residual_capacity.items()
    }
    for stratum, value in exact.items():
        quotas[stratum] += math.floor(value)
    leftover = sample_size - sum(quotas.values())
    ranked = sorted(
        capacities,
        key=lambda stratum: (
            -(exact[stratum] - math.floor(exact[stratum])),
            _priority(plan, "quota", _stratum_id(stratum)),
        ),
    )
    for stratum in ranked:
        if leftover == 0:
            break
        if quotas[stratum] < capacities[stratum]:
            quotas[stratum] += 1
            leftover -= 1
    if leftover:
        raise ValueError("benchmark allocation quota rounding did not reach sample size")
    return quotas


def _relative_locator(root: Path, path: Path, label: str) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must be inside the workspace")
    return resolved.relative_to(root).as_posix()


def _contained_locator(root: Path, locator: str, label: str) -> Path:
    _validate_relative_path(locator, label)
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"{label} is unavailable or escaped the workspace")
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if (
        "\\" in value
        or pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative path")


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link")
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
    "AllocatedBenchmarkRecord",
    "BenchmarkAllocationStratumInventory",
    "BenchmarkAllocationStratumResult",
    "BenchmarkMetadataAllocationApproval",
    "BenchmarkMetadataAllocationApprovalInspection",
    "BenchmarkMetadataAllocationChainInspection",
    "BenchmarkMetadataAllocationPlan",
    "BenchmarkMetadataAllocationPlanChainInspection",
    "BenchmarkMetadataAllocationPlanInspection",
    "BenchmarkMetadataAllocationReport",
    "BenchmarkMetadataAllocationReportInspection",
    "allocate_benchmark_metadata_population",
    "approve_benchmark_metadata_allocation",
    "inspect_benchmark_metadata_allocation_chain",
    "inspect_benchmark_metadata_allocation_plan_chain",
    "load_benchmark_metadata_allocation_approval",
    "load_benchmark_metadata_allocation_plan",
    "load_benchmark_metadata_allocation_report",
    "plan_benchmark_metadata_allocation",
    "save_benchmark_metadata_allocation_approval",
    "save_benchmark_metadata_allocation_plan",
    "save_benchmark_metadata_allocation_report",
]

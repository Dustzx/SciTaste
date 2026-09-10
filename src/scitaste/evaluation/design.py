"""Contracts and deterministic gates for rigorous AutoResearch evaluation designs."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationTrack(StrEnum):
    DECISION_MECHANISM = "decision_mechanism"
    FULL_LIFECYCLE = "full_lifecycle"
    EXPERIMENT_INTEGRITY = "experiment_integrity"
    FRONTIER_PROGRESS = "frontier_progress"
    SELF_DEVELOPMENT = "self_development"


class EvidenceRole(StrEnum):
    HEADLINE = "headline"
    MECHANISM = "mechanism"
    INTEGRITY = "integrity"
    STRETCH = "stretch"
    PROCESS_ONLY = "process_only"


class FrameworkRole(StrEnum):
    SCITASTE = "scitaste"
    EXTERNAL = "external"
    CONTROL = "control"


class FrameworkSpec(FrozenModel):
    system_id: str = Field(min_length=1)
    role: FrameworkRole
    implementation_ref: str = Field(min_length=1)
    resource_id: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    independent_from_scitaste: bool
    real_implementation: bool
    core_modified: bool = False
    task_semantics_compatible: bool
    resource_telemetry_complete: bool

    @model_validator(mode="after")
    def role_matches_independence(self) -> FrameworkSpec:
        if self.role == FrameworkRole.SCITASTE and self.independent_from_scitaste:
            raise ValueError("SciTaste cannot be marked independent from itself")
        if self.role == FrameworkRole.EXTERNAL and not self.independent_from_scitaste:
            raise ValueError("external systems must be independent from SciTaste")
        if self.role == FrameworkRole.EXTERNAL and self.resource_id is None:
            raise ValueError("external systems require an evaluation resource ID")
        return self


class EvaluationTask(FrozenModel):
    task_id: str = Field(min_length=1)
    track: EvaluationTrack
    benchmark_id: str = Field(min_length=1)
    benchmark_resource_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    source_group_id: str = Field(min_length=1)
    asset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    held_out: bool
    self_referential: bool = False
    overlaps_parent_evidence: bool = False
    public_or_retrievable_assets: bool
    executable_success_signal: bool
    paper_required: bool = False


class ComparisonBlock(FrozenModel):
    block_id: str = Field(min_length=1)
    track: EvaluationTrack
    evidence_role: EvidenceRole
    system_ids: list[str] = Field(min_length=2)
    task_ids: list[str] = Field(min_length=1)
    seeds: list[int] = Field(min_length=1)
    budget_ref: str = Field(min_length=1)
    matched_backbone: bool
    matched_starting_information: bool
    matched_tool_permissions: bool
    matched_repair_policy: bool

    @model_validator(mode="after")
    def members_are_unique(self) -> ComparisonBlock:
        if len(set(self.system_ids)) != len(self.system_ids):
            raise ValueError("comparison block system_ids must be unique")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("comparison block task_ids must be unique")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("comparison block seeds must be unique")
        return self


class StatisticalDesign(FrozenModel):
    track: EvaluationTrack
    experimental_unit: str = Field(min_length=1)
    primary_endpoint: str = Field(min_length=1)
    estimand: str = Field(min_length=1)
    power_analysis_ref: str | None = None
    failure_policy: str = Field(min_length=1)
    condition_blinded: bool
    min_reviewers_per_artifact: int = Field(ge=0)
    judge_validation_ref: str | None = None


class RecursiveProjectContract(FrozenModel):
    product_id: str = Field(min_length=1)
    self_development_project_id: str = Field(min_length=1)
    formal_project_prefix: str = Field(min_length=1)
    feedback_creates_new_protocol: bool
    self_case_excluded_from_headline: bool
    paper_uses_admitted_evidence_only: bool


class ApprovalRecord(FrozenModel):
    approved: bool = False
    approved_design_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approved_by: str | None = None
    approved_at: str | None = None

    @model_validator(mode="after")
    def approval_is_attributable(self) -> ApprovalRecord:
        fields = (self.approved_design_sha256, self.approved_by, self.approved_at)
        if self.approved and not all(fields):
            raise ValueError("approved designs require hash, approver, and timestamp")
        if not self.approved and any(fields):
            raise ValueError("unapproved designs cannot carry approval metadata")
        return self


class ExperimentDesignState(FrozenModel):
    schema_version: Literal["1.1"] = "1.1"
    design_id: str = Field(min_length=1)
    design_version: str = Field(min_length=1)
    protocol_id: str = Field(min_length=1)
    paper_claim: str = Field(min_length=1)
    resource_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frameworks: list[FrameworkSpec] = Field(min_length=1)
    tasks: list[EvaluationTask] = Field(min_length=1)
    comparison_blocks: list[ComparisonBlock] = Field(min_length=1)
    statistical_designs: list[StatisticalDesign] = Field(min_length=1)
    recursion: RecursiveProjectContract
    approval: ApprovalRecord = Field(default_factory=ApprovalRecord)

    @model_validator(mode="after")
    def references_are_closed(self) -> ExperimentDesignState:
        framework_ids = [framework.system_id for framework in self.frameworks]
        task_ids = [task.task_id for task in self.tasks]
        block_ids = [block.block_id for block in self.comparison_blocks]
        statistical_tracks = [design.track for design in self.statistical_designs]
        for values, label in (
            (framework_ids, "framework"),
            (task_ids, "task"),
            (block_ids, "comparison block"),
            (statistical_tracks, "statistical track"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} identifiers must be unique")

        known_frameworks = set(framework_ids)
        known_tasks = set(task_ids)
        task_by_id = {task.task_id: task for task in self.tasks}
        for block in self.comparison_blocks:
            unknown_frameworks = set(block.system_ids) - known_frameworks
            if unknown_frameworks:
                raise ValueError(f"unknown framework ids: {sorted(unknown_frameworks)}")
            unknown_tasks = set(block.task_ids) - known_tasks
            if unknown_tasks:
                raise ValueError(f"unknown task ids: {sorted(unknown_tasks)}")
            wrong_track = [
                task_id for task_id in block.task_ids if task_by_id[task_id].track != block.track
            ]
            if wrong_track:
                raise ValueError(f"tasks do not match comparison block track: {wrong_track}")
        return self

    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"approval"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class DesignGatePolicy(FrozenModel):
    min_independent_external_systems: int = Field(default=2, ge=1)
    require_full_lifecycle_headline: bool = True
    require_power_analysis: bool = True
    require_human_judge_validation: bool = True
    require_resource_admission: bool = True
    min_human_reviewers: int = Field(default=2, ge=1)


class DesignBlocker(FrozenModel):
    code: str
    message: str


class DesignGateReport(FrozenModel):
    schema_version: str = "1.0"
    design_id: str
    design_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    design_complete: bool
    ready_for_human_approval: bool
    execution_authorized: bool
    blockers: list[DesignBlocker]
    authorization_blockers: list[DesignBlocker]


class ExperimentDesignGate:
    """Check scientific completeness separately from explicit launch approval."""

    def __init__(self, policy: DesignGatePolicy | None = None) -> None:
        self.policy = policy or DesignGatePolicy()

    def evaluate(
        self,
        design: ExperimentDesignState,
        *,
        resource_corpus: ExternalResourceCorpus | None = None,
    ) -> DesignGateReport:
        blockers: list[DesignBlocker] = []
        frameworks = {framework.system_id: framework for framework in design.frameworks}
        tasks = {task.task_id: task for task in design.tasks}
        statistics = {item.track: item for item in design.statistical_designs}
        headline_blocks = [
            block
            for block in design.comparison_blocks
            if block.evidence_role == EvidenceRole.HEADLINE
        ]
        lifecycle_blocks = [
            block for block in headline_blocks if block.track == EvaluationTrack.FULL_LIFECYCLE
        ]

        if self.policy.require_full_lifecycle_headline and not lifecycle_blocks:
            blockers.append(
                DesignBlocker(
                    code="missing_full_lifecycle_headline",
                    message="a full-lifecycle headline comparison block is required",
                )
            )

        for block in lifecycle_blocks:
            block_frameworks = [frameworks[system_id] for system_id in block.system_ids]
            if not any(item.role == FrameworkRole.SCITASTE for item in block_frameworks):
                blockers.append(
                    DesignBlocker(
                        code="missing_scitaste_headline",
                        message=f"{block.block_id} does not include SciTaste",
                    )
                )
            external_count = sum(
                item.role == FrameworkRole.EXTERNAL and item.independent_from_scitaste
                for item in block_frameworks
            )
            if external_count < self.policy.min_independent_external_systems:
                blockers.append(
                    DesignBlocker(
                        code="insufficient_external_systems",
                        message=(
                            f"{block.block_id} requires at least "
                            f"{self.policy.min_independent_external_systems} "
                            "independent external systems"
                        ),
                    )
                )

        headline_system_ids = {
            system_id for block in headline_blocks for system_id in block.system_ids
        }

        if self.policy.require_resource_admission:
            blockers.extend(
                self._resource_blockers(
                    design,
                    headline_blocks=headline_blocks,
                    frameworks=frameworks,
                    tasks=tasks,
                    resource_corpus=resource_corpus,
                )
            )

        for system_id in sorted(headline_system_ids):
            framework = frameworks[system_id]
            if not framework.real_implementation:
                blockers.append(
                    DesignBlocker(
                        code="pseudo_implementation",
                        message=f"{system_id} is not a real implementation",
                    )
                )
            if framework.role == FrameworkRole.EXTERNAL and framework.core_modified:
                blockers.append(
                    DesignBlocker(
                        code="external_core_modified",
                        message=f"{system_id} modifies the external framework core",
                    )
                )
            if not framework.task_semantics_compatible:
                blockers.append(
                    DesignBlocker(
                        code="incompatible_task_semantics",
                        message=f"{system_id} cannot preserve the registered task semantics",
                    )
                )
            if not framework.resource_telemetry_complete:
                blockers.append(
                    DesignBlocker(
                        code="incomplete_resource_telemetry",
                        message=f"{system_id} lacks matched resource telemetry",
                    )
                )

        for block in headline_blocks:
            for task_id in block.task_ids:
                task = tasks[task_id]
                if not task.held_out or task.self_referential or task.overlaps_parent_evidence:
                    blockers.append(
                        DesignBlocker(
                            code="headline_task_not_independent",
                            message=f"{task_id} is not independent from self-development evidence",
                        )
                    )
                if not task.public_or_retrievable_assets:
                    blockers.append(
                        DesignBlocker(
                            code="task_assets_unavailable",
                            message=f"{task_id} lacks public or precisely retrievable assets",
                        )
                    )
                if not task.executable_success_signal:
                    blockers.append(
                        DesignBlocker(
                            code="task_not_executable",
                            message=f"{task_id} lacks an executable success signal",
                        )
                    )
                if block.track == EvaluationTrack.FULL_LIFECYCLE and not task.paper_required:
                    blockers.append(
                        DesignBlocker(
                            code="full_lifecycle_without_paper",
                            message=f"{task_id} does not require a final paper artifact",
                        )
                    )
            fairness = (
                block.matched_backbone,
                block.matched_starting_information,
                block.matched_tool_permissions,
                block.matched_repair_policy,
            )
            if not all(fairness):
                blockers.append(
                    DesignBlocker(
                        code="unmatched_headline_block",
                        message=f"{block.block_id} does not satisfy every matched-comparison gate",
                    )
                )

        headline_tracks = {block.track for block in headline_blocks}
        for track in sorted(headline_tracks):
            statistical = statistics.get(track)
            if statistical is None:
                blockers.append(
                    DesignBlocker(
                        code="missing_statistical_design",
                        message=f"{track.value} lacks a statistical design",
                    )
                )
                continue
            if self.policy.require_power_analysis and not statistical.power_analysis_ref:
                blockers.append(
                    DesignBlocker(
                        code="missing_power_analysis",
                        message=f"{track.value} lacks a frozen power-analysis reference",
                    )
                )
            if not statistical.condition_blinded:
                blockers.append(
                    DesignBlocker(
                        code="review_not_blinded",
                        message=f"{track.value} review is not condition blinded",
                    )
                )
            if statistical.min_reviewers_per_artifact < self.policy.min_human_reviewers:
                blockers.append(
                    DesignBlocker(
                        code="insufficient_human_reviewers",
                        message=f"{track.value} has too few reviewers per artifact",
                    )
                )
            if self.policy.require_human_judge_validation and not statistical.judge_validation_ref:
                blockers.append(
                    DesignBlocker(
                        code="judge_not_validated",
                        message=f"{track.value} lacks a human judge-validation reference",
                    )
                )

        recursion = design.recursion
        if not recursion.feedback_creates_new_protocol:
            blockers.append(
                DesignBlocker(
                    code="mutable_formal_protocol",
                    message="self-iteration feedback must create a new formal protocol",
                )
            )
        if not recursion.self_case_excluded_from_headline:
            blockers.append(
                DesignBlocker(
                    code="self_case_in_headline",
                    message="self-development must be excluded from headline estimates",
                )
            )
        if not recursion.paper_uses_admitted_evidence_only:
            blockers.append(
                DesignBlocker(
                    code="paper_not_evidence_bound",
                    message="paper generation must use admitted evidence only",
                )
            )

        blockers = _deduplicate_blockers(blockers)
        design_complete = not blockers
        authorization_blockers: list[DesignBlocker] = []
        if not design.approval.approved:
            authorization_blockers.append(
                DesignBlocker(
                    code="human_approval_required",
                    message="the frozen design has not received explicit human launch approval",
                )
            )
        elif design.approval.approved_design_sha256 != design.proposal_sha256:
            authorization_blockers.append(
                DesignBlocker(
                    code="approval_hash_mismatch",
                    message="approval does not bind the current design bytes",
                )
            )
        return DesignGateReport(
            design_id=design.design_id,
            design_sha256=design.proposal_sha256,
            design_complete=design_complete,
            ready_for_human_approval=design_complete,
            execution_authorized=design_complete and not authorization_blockers,
            blockers=blockers,
            authorization_blockers=authorization_blockers,
        )

    @staticmethod
    def _resource_blockers(
        design: ExperimentDesignState,
        *,
        headline_blocks: list[ComparisonBlock],
        frameworks: dict[str, FrameworkSpec],
        tasks: dict[str, EvaluationTask],
        resource_corpus: ExternalResourceCorpus | None,
    ) -> list[DesignBlocker]:
        if resource_corpus is None:
            return [
                DesignBlocker(
                    code="missing_resource_corpus",
                    message="the design gate requires its content-bound evaluation resource corpus",
                )
            ]
        if resource_corpus.semantic_sha256 != design.resource_corpus_sha256:
            return [
                DesignBlocker(
                    code="resource_corpus_hash_mismatch",
                    message="the supplied resource corpus does not match the frozen design hash",
                )
            ]

        blockers: list[DesignBlocker] = []
        headline_system_ids = {
            system_id for block in headline_blocks for system_id in block.system_ids
        }
        for system_id in sorted(headline_system_ids):
            framework = frameworks[system_id]
            if framework.role is not FrameworkRole.EXTERNAL:
                continue
            if framework.resource_id is None:
                blockers.append(
                    DesignBlocker(
                        code="missing_framework_resource",
                        message=f"{system_id} has no external resource binding",
                    )
                )
                continue
            try:
                report = evaluate_resource_feasibility(
                    resource_corpus,
                    framework.resource_id,
                    ResourceUse.COMPARISON_SYSTEM,
                )
            except ValueError:
                blockers.append(
                    DesignBlocker(
                        code="unknown_framework_resource",
                        message=(
                            f"{system_id} references unknown evaluation resource "
                            f"{framework.resource_id}"
                        ),
                    )
                )
                continue
            if report.repository_commit not in framework.implementation_ref:
                blockers.append(
                    DesignBlocker(
                        code="framework_pin_mismatch",
                        message=(
                            f"{system_id} implementation_ref does not bind admitted commit "
                            f"{report.repository_commit}"
                        ),
                    )
                )
            if not report.eligible:
                blockers.append(
                    DesignBlocker(
                        code="external_resource_not_admitted",
                        message=(
                            f"{system_id} is blocked for comparison_system: "
                            f"{', '.join(report.blocker_codes)}"
                        ),
                    )
                )

        headline_task_ids = {task_id for block in headline_blocks for task_id in block.task_ids}
        for task_id in sorted(headline_task_ids):
            task = tasks[task_id]
            if task.benchmark_resource_id is None:
                blockers.append(
                    DesignBlocker(
                        code="missing_task_resource",
                        message=f"{task_id} has no benchmark resource binding",
                    )
                )
                continue
            try:
                report = evaluate_resource_feasibility(
                    resource_corpus,
                    task.benchmark_resource_id,
                    ResourceUse.TASK_SOURCE,
                )
            except ValueError:
                blockers.append(
                    DesignBlocker(
                        code="unknown_task_resource",
                        message=(
                            f"{task_id} references unknown evaluation resource "
                            f"{task.benchmark_resource_id}"
                        ),
                    )
                )
                continue
            if not report.eligible:
                blockers.append(
                    DesignBlocker(
                        code="task_resource_not_admitted",
                        message=(
                            f"{task_id} is blocked for task_source: "
                            f"{', '.join(report.blocker_codes)}"
                        ),
                    )
                )
        return blockers


class FailureAttribution(StrEnum):
    MODEL_LIMIT_CANDIDATE = "model_limit_candidate"
    FRAMEWORK_LIMIT = "framework_limit"
    FRAMEWORK_INDUCED_REGRESSION = "framework_induced_regression"
    CONTEXT_TOOLING_GAP = "context_tooling_gap"
    RESOURCE_ENVIRONMENT_FAILURE = "resource_environment_failure"
    UNRESOLVED = "unresolved"


class FailureObservation(FrozenModel):
    primary_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparator_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    primary_model_succeeded: bool
    comparator_model_succeeded: bool
    native_base_succeeded: bool
    full_scitaste_succeeded: bool
    proposed_plan_sound: bool
    representable_by_framework: bool
    executable_by_framework: bool
    context_complete: bool
    resource_or_environment_failure: bool


def attribute_failure(observation: FailureObservation) -> FailureAttribution:
    """Return a bounded attribution; ambiguous failures remain unresolved."""

    if observation.resource_or_environment_failure:
        return FailureAttribution.RESOURCE_ENVIRONMENT_FAILURE
    if not observation.context_complete:
        return FailureAttribution.CONTEXT_TOOLING_GAP
    if observation.native_base_succeeded and not observation.full_scitaste_succeeded:
        return FailureAttribution.FRAMEWORK_INDUCED_REGRESSION
    if observation.proposed_plan_sound and (
        not observation.representable_by_framework or not observation.executable_by_framework
    ):
        return FailureAttribution.FRAMEWORK_LIMIT
    same_state = observation.primary_state_sha256 == observation.comparator_state_sha256
    if (
        same_state
        and not observation.primary_model_succeeded
        and observation.comparator_model_succeeded
    ):
        return FailureAttribution.MODEL_LIMIT_CANDIDATE
    return FailureAttribution.UNRESOLVED


def _deduplicate_blockers(blockers: list[DesignBlocker]) -> list[DesignBlocker]:
    seen: set[tuple[str, str]] = set()
    unique: list[DesignBlocker] = []
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            unique.append(blocker)
    return unique

"""Deterministic, evidence-bound critics for experiment prelaunch proposals."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.prelaunch import (
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    PrelaunchGateReport,
    ReadinessStatus,
    ScientificLaneRole,
    SystemRole,
)
from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvaluationCriticDomain(StrEnum):
    BENCHMARK_FIT = "benchmark_fit"
    BASELINE_APPLICABILITY = "baseline_applicability"
    STATISTICS = "statistics"
    INTEGRITY = "integrity"
    RESOURCES = "resources"


class EvaluationCriticVerdict(StrEnum):
    PASS = "pass"
    ADVISORY = "advisory"
    BLOCK = "block"


class EvaluationCriticFinding(BaseModel):
    model_config = _CONFIG

    domain: EvaluationCriticDomain
    criterion: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    verdict: EvaluationCriticVerdict
    message: str = Field(min_length=1, max_length=4_000)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=50)
    proposed_action: str | None = Field(default=None, max_length=4_000)


class EvaluationCriticReport(BaseModel):
    """A review artifact. It can never authorize execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    ready_for_author_review: bool
    authorizes_execution: Literal[False] = False
    blocking_codes: tuple[str, ...]
    findings: tuple[EvaluationCriticFinding, ...]
    no_execution_performed: Literal[True] = True


class EvaluationCriticSuite:
    """Review scientific sufficiency without providers, datasets, GPUs, or mutation."""

    def review(
        self,
        manifest: ExperimentPrelaunchManifest,
        resource_corpus: ExternalResourceCorpus,
        gate_report: PrelaunchGateReport,
    ) -> EvaluationCriticReport:
        if gate_report.proposal_sha256 != manifest.proposal_sha256:
            raise ValueError("gate report does not bind the supplied prelaunch proposal")

        findings = (
            *self._benchmark_fit(manifest, resource_corpus),
            *self._baseline_applicability(manifest, resource_corpus),
            *self._statistics(manifest),
            *self._integrity(manifest, gate_report),
            *self._resources(manifest, gate_report),
        )
        blocking_codes = tuple(
            f"{finding.domain.value}:{finding.criterion}"
            for finding in findings
            if finding.verdict is EvaluationCriticVerdict.BLOCK
        )
        return EvaluationCriticReport(
            manifest_id=manifest.manifest_id,
            proposal_sha256=manifest.proposal_sha256,
            resource_corpus_sha256=resource_corpus.semantic_sha256,
            observed_source_commit=gate_report.observed_source_commit,
            ready_for_author_review=(gate_report.ready_for_author_approval and not blocking_codes),
            blocking_codes=blocking_codes,
            findings=findings,
        )

    @staticmethod
    def _benchmark_fit(
        manifest: ExperimentPrelaunchManifest,
        resource_corpus: ExternalResourceCorpus,
    ) -> tuple[EvaluationCriticFinding, ...]:
        refs = tuple(f"manifest://tasks/{task.task_id}" for task in manifest.tasks)
        unready = [
            task.task_id
            for task in manifest.tasks
            if task.license_status is not ReadinessStatus.VERIFIED
            or task.asset_status is not ReadinessStatus.VERIFIED
            or not task.held_out
            or not task.source_group_disjoint
            or task.selected_asset_manifest is None
            or task.asset_manifest_sha256 is None
        ]
        resource_blockers: list[str] = []
        for task in manifest.tasks:
            try:
                report = evaluate_resource_feasibility(
                    resource_corpus,
                    task.benchmark_resource_id,
                    ResourceUse.TASK_SOURCE,
                )
            except ValueError:
                resource_blockers.append(f"{task.task_id}:unknown_resource")
                continue
            resource_blockers.extend(f"{task.task_id}:{code}" for code in report.blocker_codes)
        if unready or resource_blockers:
            details = sorted((*unready, *resource_blockers))
            return (
                _finding(
                    EvaluationCriticDomain.BENCHMARK_FIT,
                    "frozen_independent_tasks",
                    EvaluationCriticVerdict.BLOCK,
                    "The selected task population is not yet a fully admitted, source-disjoint, "
                    f"content-addressed benchmark subset: {', '.join(details)}.",
                    refs,
                    "Freeze exact task assets, licenses, source groups, and executable signals.",
                ),
            )
        return (
            _finding(
                EvaluationCriticDomain.BENCHMARK_FIT,
                "frozen_independent_tasks",
                EvaluationCriticVerdict.PASS,
                "Every selected task is held out, source-group disjoint, content-addressed, and "
                "admitted for task-source use.",
                refs,
            ),
        )

    @staticmethod
    def _baseline_applicability(
        manifest: ExperimentPrelaunchManifest,
        resource_corpus: ExternalResourceCorpus,
    ) -> tuple[EvaluationCriticFinding, ...]:
        systems = {system.system_id: system for system in manifest.systems}
        problems: list[str] = []
        for lane in manifest.lanes:
            selected = [systems[system_id] for system_id in lane.system_ids]
            if lane.scientific_role is ScientificLaneRole.MATCHED_BACKBONE:
                counts = {
                    role: sum(item.role is role for item in selected)
                    for role in (
                        SystemRole.SCITASTE,
                        SystemRole.CONTROL,
                        SystemRole.METHOD_COMPARATOR,
                    )
                }
                if counts[SystemRole.SCITASTE] < 1:
                    problems.append(f"{lane.lane_id}:missing_scitaste")
                if counts[SystemRole.CONTROL] < 1:
                    problems.append(f"{lane.lane_id}:missing_direct_control")
                if counts[SystemRole.METHOD_COMPARATOR] < 2:
                    problems.append(f"{lane.lane_id}:fewer_than_two_method_comparators")
            for system in selected:
                if (
                    system.availability is not ReadinessStatus.VERIFIED
                    or not system.real_implementation
                    or system.implementation_ref is None
                ):
                    problems.append(f"{lane.lane_id}:{system.system_id}:implementation_unverified")
                if system.role in {SystemRole.METHOD_COMPARATOR, SystemRole.CONTROL} and (
                    system.adapter_preflight_ref is None or system.adapter_preflight_sha256 is None
                ):
                    problems.append(f"{lane.lane_id}:{system.system_id}:adapter_preflight_unbound")
                if system.external_resource_id is not None:
                    try:
                        report = evaluate_resource_feasibility(
                            resource_corpus,
                            system.external_resource_id,
                            ResourceUse.COMPARISON_SYSTEM,
                        )
                    except ValueError:
                        problems.append(f"{lane.lane_id}:{system.system_id}:unknown_resource")
                    else:
                        problems.extend(
                            f"{lane.lane_id}:{system.system_id}:{code}"
                            for code in report.blocker_codes
                        )
        refs = tuple(f"manifest://systems/{item.system_id}" for item in manifest.systems)
        if problems:
            return (
                _finding(
                    EvaluationCriticDomain.BASELINE_APPLICABILITY,
                    "real_matched_comparators",
                    EvaluationCriticVerdict.BLOCK,
                    "The comparison set lacks fully admitted real implementations or "
                    f"content-bound adapter preflights: {', '.join(sorted(set(problems)))}.",
                    refs,
                    "Complete unchanged-core adapter preflights; keep unavailable systems "
                    "explicitly unavailable rather than substituting pseudo-implementations.",
                ),
            )
        return (
            _finding(
                EvaluationCriticDomain.BASELINE_APPLICABILITY,
                "real_matched_comparators",
                EvaluationCriticVerdict.PASS,
                "The planned lanes contain real, admitted comparators with bound adapter "
                "preflight evidence.",
                refs,
            ),
        )

    @staticmethod
    def _statistics(
        manifest: ExperimentPrelaunchManifest,
    ) -> tuple[EvaluationCriticFinding, ...]:
        refs = (f"manifest://proposal/{manifest.proposal_sha256}",)
        findings: list[EvaluationCriticFinding] = []
        if manifest.analysis is None:
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "content_bound_analysis",
                    EvaluationCriticVerdict.BLOCK,
                    "No structured primary outcome, estimand, analysis unit, aggregation, or "
                    "uncertainty method is bound to this proposal.",
                    refs,
                    "Attach a content-bound analysis contract before author review.",
                )
            )
        elif manifest.study_scope == "formal" and manifest.analysis.power_analysis_ref is None:
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "content_bound_analysis",
                    EvaluationCriticVerdict.BLOCK,
                    "The formal study has no content-addressed power analysis.",
                    refs,
                    "Freeze a pilot-informed power analysis without inspecting formal outcomes.",
                )
            )
        else:
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "content_bound_analysis",
                    EvaluationCriticVerdict.PASS,
                    "The proposal binds its outcome, estimand, analysis unit, aggregation, and "
                    "uncertainty method.",
                    refs,
                )
            )

        sparse_lanes = [
            lane.lane_id for lane in manifest.lanes if len(lane.task_ids) < 2 or len(lane.seeds) < 2
        ]
        if sparse_lanes:
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "independent_replication",
                    EvaluationCriticVerdict.BLOCK,
                    "The following lanes cannot estimate task and seed variability because they "
                    f"contain fewer than two tasks or seeds: {', '.join(sparse_lanes)}.",
                    tuple(f"manifest://lanes/{lane_id}" for lane_id in sparse_lanes),
                    "Use the adapter smoke test only for debugging, then freeze a multi-task, "
                    "multi-seed pilot before estimating comparative effects.",
                )
            )
        else:
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "independent_replication",
                    EvaluationCriticVerdict.PASS,
                    "Every lane contains at least two tasks and two seeds for pilot variance "
                    "estimation.",
                    tuple(f"manifest://lanes/{lane.lane_id}" for lane in manifest.lanes),
                )
            )
        return tuple(findings)

    @staticmethod
    def _integrity(
        manifest: ExperimentPrelaunchManifest,
        gate_report: PrelaunchGateReport,
    ) -> tuple[EvaluationCriticFinding, ...]:
        refs = (f"manifest://proposal/{manifest.proposal_sha256}",)
        problems: list[str] = []
        if manifest.integrity is None:
            problems.append("integrity_contract_missing")
        elif manifest.human_review.required and manifest.integrity.judge_protocol_ref is None:
            problems.append("judge_protocol_unbound")
        if gate_report.observed_source_commit != manifest.source_commit:
            problems.append("executable_commit_unmatched")
        if gate_report.source_tree_clean is not True:
            problems.append("executable_tree_not_clean")
        if any(lane.kind is ExecutionLaneKind.API_ONLY for lane in manifest.lanes) and (
            not manifest.retention.retain_raw_provider_responses
        ):
            problems.append("raw_provider_responses_not_retained")
        if problems:
            return (
                _finding(
                    EvaluationCriticDomain.INTEGRITY,
                    "frozen_temporal_integrity",
                    EvaluationCriticVerdict.BLOCK,
                    "The proposal cannot yet preserve preregistration, task freeze, failure, "
                    "repair, leakage, judge, and executable-source integrity: "
                    f"{', '.join(problems)}.",
                    refs,
                    "Bind the integrity artifacts and inspect an exact clean executable commit.",
                ),
            )
        return (
            _finding(
                EvaluationCriticDomain.INTEGRITY,
                "frozen_temporal_integrity",
                EvaluationCriticVerdict.PASS,
                "The proposal binds temporal-integrity policies and an exact clean executable "
                "source state while preserving failed and raw API outcomes.",
                refs,
            ),
        )

    @staticmethod
    def _resources(
        manifest: ExperimentPrelaunchManifest,
        gate_report: PrelaunchGateReport,
    ) -> tuple[EvaluationCriticFinding, ...]:
        prefixes = (
            "api_",
            "gpu_",
            "human_review_",
            "system_",
            "task_assets_",
            "task_license_",
            "resource_corpus_",
        )
        resource_blockers = sorted(
            blocker.code for blocker in gate_report.blockers if blocker.code.startswith(prefixes)
        )
        refs = tuple(f"manifest://lanes/{lane.lane_id}" for lane in manifest.lanes)
        if resource_blockers:
            return (
                _finding(
                    EvaluationCriticDomain.RESOURCES,
                    "bounded_ready_resources",
                    EvaluationCriticVerdict.BLOCK,
                    "One or more implementation, task, provider, GPU, or reviewer resources are "
                    f"not verified: {', '.join(resource_blockers)}.",
                    refs,
                    "Resolve and re-hash the exact resource proposal; do not launch a partial "
                    "lane.",
                ),
            )
        return (
            _finding(
                EvaluationCriticDomain.RESOURCES,
                "bounded_ready_resources",
                EvaluationCriticVerdict.PASS,
                "All declared implementation, task, provider/GPU, retention, and reviewer resource "
                "gates pass within explicit ceilings.",
                refs,
            ),
        )


def _finding(
    domain: EvaluationCriticDomain,
    criterion: str,
    verdict: EvaluationCriticVerdict,
    message: str,
    evidence_refs: tuple[str, ...],
    proposed_action: str | None = None,
) -> EvaluationCriticFinding:
    return EvaluationCriticFinding(
        domain=domain,
        criterion=criterion,
        verdict=verdict,
        message=message,
        evidence_refs=evidence_refs,
        proposed_action=proposed_action,
    )


__all__ = [
    "EvaluationCriticDomain",
    "EvaluationCriticFinding",
    "EvaluationCriticReport",
    "EvaluationCriticSuite",
    "EvaluationCriticVerdict",
]

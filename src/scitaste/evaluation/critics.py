"""Deterministic, evidence-bound critics for experiment prelaunch proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.benchmark_metadata_allocation import (
    inspect_benchmark_metadata_allocation_chain,
)
from scitaste.evaluation.gpu_inventory import (
    compare_gpu_inventory,
    load_gpu_host_inventory,
)
from scitaste.evaluation.prelaunch import (
    ConfirmatoryEstimandKind,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    PrelaunchGateReport,
    ReadinessStatus,
    ScientificEndpointKind,
    ScientificLaneRole,
    SystemRole,
    TaskFreezeSemantics,
)
from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


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
    evidence_root_observed: bool
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
        *,
        evidence_root: str | Path | None = None,
    ) -> EvaluationCriticReport:
        if gate_report.proposal_sha256 != manifest.proposal_sha256:
            raise ValueError("gate report does not bind the supplied prelaunch proposal")

        findings = (
            *self._benchmark_fit(manifest, resource_corpus, evidence_root),
            *self._baseline_applicability(manifest, resource_corpus, evidence_root),
            *self._statistics(manifest, evidence_root),
            *self._integrity(manifest, gate_report, evidence_root),
            *self._resources(manifest, gate_report, evidence_root),
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
            evidence_root_observed=evidence_root is not None,
            ready_for_author_review=(gate_report.ready_for_author_approval and not blocking_codes),
            blocking_codes=blocking_codes,
            findings=findings,
        )

    @staticmethod
    def _benchmark_fit(
        manifest: ExperimentPrelaunchManifest,
        resource_corpus: ExternalResourceCorpus,
        evidence_root: str | Path | None,
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
        artifact_problems = _artifact_problems(
            evidence_root,
            ((task.selected_asset_manifest, task.asset_manifest_sha256) for task in manifest.tasks),
        )
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
        if unready or resource_blockers or artifact_problems:
            details = sorted((*unready, *resource_blockers, *artifact_problems))
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
        evidence_root: str | Path | None,
    ) -> tuple[EvaluationCriticFinding, ...]:
        systems = {system.system_id: system for system in manifest.systems}
        claim = manifest.analysis.claim_admission if manifest.analysis is not None else None
        problems: list[str] = []
        for lane in manifest.lanes:
            selected = [systems[system_id] for system_id in lane.system_ids]
            if lane.scientific_role in {
                ScientificLaneRole.MATCHED_BACKBONE,
                ScientificLaneRole.BEST_NATIVE_SYSTEM,
            }:
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
                lane_claim = claim if claim is not None and claim.lane_id == lane.lane_id else None
                if lane_claim is None:
                    if counts[SystemRole.CONTROL] < 1:
                        problems.append(f"{lane.lane_id}:missing_direct_control")
                    if counts[SystemRole.METHOD_COMPARATOR] < 2:
                        problems.append(f"{lane.lane_id}:fewer_than_two_method_comparators")
                elif lane_claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL:
                    if not any(item.role is SystemRole.ABLATION for item in selected):
                        problems.append(f"{lane.lane_id}:missing_native_ablation")
                elif counts[SystemRole.METHOD_COMPARATOR] < 2:
                    problems.append(f"{lane.lane_id}:fewer_than_two_method_comparators")
            for system in selected:
                if (
                    system.availability is not ReadinessStatus.VERIFIED
                    or not system.real_implementation
                    or system.implementation_ref is None
                ):
                    problems.append(f"{lane.lane_id}:{system.system_id}:implementation_unverified")
                requires_preflight = system.role in {
                    SystemRole.METHOD_COMPARATOR,
                    SystemRole.CONTROL,
                } or (
                    manifest.schema_version == "1.4"
                    and lane_claim is not None
                    and lane_claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
                )
                if requires_preflight and (
                    system.adapter_preflight_ref is None or system.adapter_preflight_sha256 is None
                ):
                    problems.append(f"{lane.lane_id}:{system.system_id}:adapter_preflight_unbound")
                elif requires_preflight:
                    problems.extend(
                        f"{lane.lane_id}:{system.system_id}:{problem}"
                        for problem in _artifact_problems(
                            evidence_root,
                            (
                                (
                                    system.adapter_preflight_ref,
                                    system.adapter_preflight_sha256,
                                ),
                            ),
                        )
                    )
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
        evidence_root: str | Path | None,
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
        elif _artifact_problems(
            evidence_root,
            (
                (
                    manifest.analysis.power_analysis_ref,
                    manifest.analysis.power_analysis_sha256,
                ),
            ),
        ):
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "content_bound_analysis",
                    EvaluationCriticVerdict.BLOCK,
                    "The referenced power analysis was not verified against its declared hash.",
                    refs,
                    "Make the content-addressed power analysis available in the evidence root.",
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
            verdict = (
                EvaluationCriticVerdict.BLOCK
                if manifest.study_scope == "formal"
                else EvaluationCriticVerdict.ADVISORY
            )
            findings.append(
                _finding(
                    EvaluationCriticDomain.STATISTICS,
                    "independent_replication",
                    verdict,
                    "The following lanes cannot estimate both task and seed variability because "
                    f"they contain fewer than two tasks or seeds: {', '.join(sparse_lanes)}.",
                    tuple(f"manifest://lanes/{lane_id}" for lane_id in sparse_lanes),
                    "Treat this pilot as feasibility evidence only, then freeze a multi-task, "
                    "multi-seed formal design before estimating confirmatory effects.",
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
        evidence_root: str | Path | None,
    ) -> tuple[EvaluationCriticFinding, ...]:
        refs = (f"manifest://proposal/{manifest.proposal_sha256}",)
        problems: list[str] = []
        if manifest.integrity is None:
            problems.append("integrity_contract_missing")
        else:
            if manifest.human_review.required and manifest.integrity.judge_protocol_ref is None:
                problems.append("judge_protocol_unbound")
            problems.extend(
                _artifact_problems(
                    evidence_root,
                    (
                        (
                            manifest.integrity.preregistration_ref,
                            manifest.integrity.preregistration_sha256,
                        ),
                        (
                            manifest.integrity.task_freeze_ref,
                            manifest.integrity.task_freeze_sha256,
                        ),
                        (
                            manifest.integrity.failure_policy_ref,
                            manifest.integrity.failure_policy_sha256,
                        ),
                        (
                            manifest.integrity.repair_policy_ref,
                            manifest.integrity.repair_policy_sha256,
                        ),
                        (
                            manifest.integrity.leakage_audit_ref,
                            manifest.integrity.leakage_audit_sha256,
                        ),
                        (
                            manifest.integrity.judge_protocol_ref,
                            manifest.integrity.judge_protocol_sha256,
                        ),
                    ),
                )
            )
            if (
                manifest.study_scope == "formal"
                and manifest.primary_endpoint is ScientificEndpointKind.OBJECTIVE_PROGRESS
            ):
                if (
                    manifest.integrity.task_freeze_semantics
                    is not TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
                ):
                    problems.append("formal_task_allocation_unbound")
                else:
                    problems.extend(_benchmark_allocation_freeze_problems(manifest, evidence_root))
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
        evidence_root: str | Path | None,
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
        resource_blockers.extend(_gpu_inventory_problems(manifest, evidence_root))
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


def _gpu_inventory_problems(
    manifest: ExperimentPrelaunchManifest,
    evidence_root: str | Path | None,
) -> list[str]:
    problems: list[str] = []
    for lane in manifest.lanes:
        resource = lane.gpu_resource
        if resource is None:
            continue
        bindings: list[tuple[str | None, str | None]] = []
        if resource.remote_inventory_status is ReadinessStatus.VERIFIED:
            bindings.append((resource.remote_inventory_ref, resource.remote_inventory_sha256))
        if resource.remote_checkpoint_status is ReadinessStatus.VERIFIED:
            bindings.append(
                (
                    resource.remote_checkpoint_attestation_ref,
                    resource.remote_checkpoint_attestation_sha256,
                )
            )
        artifact_problems = _artifact_problems(evidence_root, bindings)
        problems.extend(f"{lane.lane_id}:{problem}" for problem in artifact_problems)
        if (
            resource.remote_inventory_status is not ReadinessStatus.VERIFIED
            or artifact_problems
            or evidence_root is None
            or resource.remote_inventory_ref is None
        ):
            continue
        try:
            root = Path(evidence_root).resolve(strict=True)
            inventory_path = root.joinpath(*PurePosixPath(resource.remote_inventory_ref).parts)
            inspection = load_gpu_host_inventory(inventory_path)
        except (OSError, ValueError) as exc:
            problems.append(f"{lane.lane_id}:gpu_inventory_invalid:{type(exc).__name__}")
            continue
        mismatches = compare_gpu_inventory(
            inspection.inventory,
            host_alias=resource.host_alias,
            device_count=resource.device_count,
            device_name=resource.device_name,
            minimum_memory_mb_per_device=resource.minimum_memory_mb_per_device,
            checkpoint_id=resource.checkpoint_id,
            checkpoint_sha256=resource.checkpoint_sha256,
            checkpoint_bytes=resource.checkpoint_bytes,
            compare_checkpoint=(resource.remote_checkpoint_status is ReadinessStatus.VERIFIED),
        )
        problems.extend(f"{lane.lane_id}:gpu_inventory_{code}" for code in mismatches)
        if (
            resource.remote_checkpoint_status is ReadinessStatus.VERIFIED
            and resource.remote_checkpoint_attestation_ref is not None
        ):
            try:
                attestation_path = root.joinpath(
                    *PurePosixPath(resource.remote_checkpoint_attestation_ref).parts
                )
                attestation = load_gpu_host_inventory(attestation_path).inventory
            except (OSError, ValueError) as exc:
                problems.append(
                    f"{lane.lane_id}:remote_checkpoint_attestation_invalid:{type(exc).__name__}"
                )
                continue
            problems.extend(
                f"{lane.lane_id}:checkpoint_attestation_{code}"
                for code in compare_gpu_inventory(
                    attestation,
                    host_alias=resource.host_alias,
                    device_count=resource.device_count,
                    device_name=resource.device_name,
                    minimum_memory_mb_per_device=resource.minimum_memory_mb_per_device,
                    checkpoint_id=resource.checkpoint_id,
                    checkpoint_sha256=resource.checkpoint_sha256,
                    checkpoint_bytes=resource.checkpoint_bytes,
                )
            )
            checkpoint = attestation.checkpoint
            if not checkpoint.destination_present:
                problems.append(f"{lane.lane_id}:remote_checkpoint_absent")
            elif checkpoint.observed_sha256 != resource.checkpoint_sha256:
                problems.append(f"{lane.lane_id}:remote_checkpoint_hash_mismatch")
    return problems


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


def _artifact_problems(
    evidence_root: str | Path | None,
    bindings: Iterable[tuple[str | None, str | None]],
) -> list[str]:
    pairs = tuple(bindings)
    required = [(locator, digest) for locator, digest in pairs if locator or digest]
    if not required:
        return []
    if evidence_root is None:
        return [f"artifact_unobserved:{locator}" for locator, _ in required]
    try:
        root = Path(evidence_root).resolve(strict=True)
    except (OSError, ValueError):
        return ["evidence_root_unavailable"]
    if not root.is_dir():
        return ["evidence_root_not_directory"]

    problems: list[str] = []
    for locator, expected in required:
        if locator is None or expected is None:
            problems.append(f"artifact_binding_incomplete:{locator or 'missing_locator'}")
            continue
        pure = PurePosixPath(locator)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            problems.append(f"artifact_path_unsafe:{locator}")
            continue
        candidate = root.joinpath(*pure.parts)
        if any(path.is_symlink() for path in (root, *candidate.parents, candidate)):
            problems.append(f"artifact_symlink_forbidden:{locator}")
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            size = resolved.stat().st_size
        except (OSError, ValueError):
            problems.append(f"artifact_missing_or_escaped:{locator}")
            continue
        if not resolved.is_file() or size > _MAX_EVIDENCE_BYTES:
            problems.append(f"artifact_not_bounded_file:{locator}")
            continue
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected:
            problems.append(f"artifact_hash_mismatch:{locator}")
    return problems


def _benchmark_allocation_freeze_problems(
    manifest: ExperimentPrelaunchManifest,
    evidence_root: str | Path | None,
) -> list[str]:
    """Require one replayed allocation to be the exact formal prelaunch task set."""

    integrity = manifest.integrity
    if integrity is None or evidence_root is None:
        return ["benchmark_allocation_chain_unobserved"]
    try:
        root = Path(evidence_root).resolve(strict=True)
        pure = PurePosixPath(integrity.task_freeze_ref)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            return ["benchmark_allocation_path_unsafe"]
        candidate = root.joinpath(*pure.parts)
        inspection = inspect_benchmark_metadata_allocation_chain(
            candidate,
            workspace_root=root,
        )
    except (OSError, ValueError):
        return ["benchmark_allocation_chain_invalid"]

    problems: list[str] = []
    allocation = inspection.report.report
    plan = inspection.plan.plan
    if inspection.report.file_sha256 != integrity.task_freeze_sha256:
        problems.append("benchmark_allocation_file_hash_mismatch")
    if allocation.formal_task_set_sha256 != integrity.formal_task_set_sha256:
        problems.append("benchmark_allocation_task_set_hash_mismatch")
    if plan.formal_study_id != manifest.protocol_id:
        problems.append("benchmark_allocation_formal_study_mismatch")
    if not inspection.allocation_implementation_current:
        problems.append("benchmark_allocation_implementation_drift")

    allocated_records = tuple(allocation.selected_records)
    allocated_task_ids = tuple(item.record_id for item in allocated_records)
    manifest_task_ids = tuple(item.task_id for item in manifest.tasks)
    if manifest_task_ids != allocated_task_ids:
        problems.append("benchmark_allocation_task_identity_mismatch")
    allocated_source_groups = {item.record_id: item.source_group for item in allocated_records}
    if any(
        task.source_group != allocated_source_groups.get(task.task_id) for task in manifest.tasks
    ):
        problems.append("benchmark_allocation_source_group_mismatch")
    if any(tuple(lane.task_ids) != allocated_task_ids for lane in manifest.lanes):
        problems.append("benchmark_allocation_lane_population_mismatch")
    return problems


__all__ = [
    "EvaluationCriticDomain",
    "EvaluationCriticFinding",
    "EvaluationCriticReport",
    "EvaluationCriticSuite",
    "EvaluationCriticVerdict",
]

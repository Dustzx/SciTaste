"""Diagnostic attribution of model-specific and SciTaste-system limits."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scitaste.benchmark.models import (
    BenchmarkCondition,
    BenchmarkReport,
    CapabilityBoundaryReport,
    ConditionReport,
    CrossModelCapabilityComparison,
)


def build_capability_boundary(
    reports: dict[BenchmarkCondition, ConditionReport],
    *,
    excluded_case_ids: list[str],
) -> CapabilityBoundaryReport | None:
    """Classify paired Base/Full outcomes without overclaiming causal attribution."""

    if BenchmarkCondition.FULL_SCITASTE not in reports:
        return None
    excluded = set(excluded_case_ids)
    base = {
        result.case_id: result.correct
        for result in reports[BenchmarkCondition.BASE].results
        if result.case_id not in excluded
    }
    full = {
        result.case_id: result.correct
        for result in reports[BenchmarkCondition.FULL_SCITASTE].results
        if result.case_id not in excluded
    }
    if set(base) != set(full):
        raise ValueError("Base and Full conditions must cover the same headline cases")

    no_limit = sorted(case_id for case_id in base if base[case_id] and full[case_id])
    recoveries = sorted(case_id for case_id in base if not base[case_id] and full[case_id])
    regressions = sorted(case_id for case_id in base if base[case_id] and not full[case_id])
    shared = sorted(case_id for case_id in base if not base[case_id] and not full[case_id])

    if shared:
        model_conclusion = (
            "inconclusive: Base and Full both failed; use a same-suite comparator model "
            "before assigning these cases to model capability"
        )
    elif recoveries:
        model_conclusion = (
            "base-model misses were observed but recovered by SciTaste context; this does "
            "not establish a hard model ceiling"
        )
    else:
        model_conclusion = (
            "no model failure was observed on the paired headline cases; ceiling effects "
            "may make the suite non-discriminating"
        )

    if regressions:
        system_conclusion = "system-induced regressions observed: Base succeeded where Full failed"
    elif recoveries:
        system_conclusion = "system recoveries observed with no paired regressions"
    elif shared:
        system_conclusion = (
            "no differential system effect on shared failures; attribution remains unresolved"
        )
    else:
        system_conclusion = "no system limit observed; paired results are ceiling-limited"

    return CapabilityBoundaryReport(
        no_observed_limit_case_ids=no_limit,
        system_recovery_case_ids=recoveries,
        system_regression_case_ids=regressions,
        shared_failure_case_ids=shared,
        model_capability_conclusion=model_conclusion,
        system_conclusion=system_conclusion,
    )


def compare_model_boundaries(
    primary: BenchmarkReport,
    comparator: BenchmarkReport,
) -> CrossModelCapabilityComparison:
    """Use same-suite Base outcomes to identify model-specific limit candidates."""

    if primary.suite_sha256 != comparator.suite_sha256:
        raise ValueError("cross-model attribution requires the same benchmark suite hash")
    if primary.seed != comparator.seed:
        raise ValueError("cross-model attribution requires the same benchmark seed")
    if primary.capability_boundary is None or comparator.capability_boundary is None:
        raise ValueError("cross-model attribution requires paired Base and Full conditions")

    primary_base = _headline_correctness(primary, BenchmarkCondition.BASE)
    comparator_base = _headline_correctness(comparator, BenchmarkCondition.BASE)
    if set(primary_base) != set(comparator_base):
        raise ValueError("cross-model attribution requires identical headline case ids")

    both_correct = sorted(
        case_id for case_id in primary_base if primary_base[case_id] and comparator_base[case_id]
    )
    primary_limit = sorted(
        case_id
        for case_id in primary_base
        if not primary_base[case_id] and comparator_base[case_id]
    )
    comparator_limit = sorted(
        case_id
        for case_id in primary_base
        if primary_base[case_id] and not comparator_base[case_id]
    )
    shared = sorted(
        case_id
        for case_id in primary_base
        if not primary_base[case_id] and not comparator_base[case_id]
    )
    return CrossModelCapabilityComparison(
        suite_id=primary.suite_id,
        suite_sha256=primary.suite_sha256,
        seed=primary.seed,
        primary_backend=primary.backend,
        primary_model=primary.model,
        comparator_backend=comparator.backend,
        comparator_model=comparator.model,
        both_base_correct_case_ids=both_correct,
        primary_model_limit_candidate_case_ids=primary_limit,
        comparator_model_limit_candidate_case_ids=comparator_limit,
        shared_base_failure_case_ids=shared,
        primary_system_regression_case_ids=(primary.capability_boundary.system_regression_case_ids),
        comparator_system_regression_case_ids=(
            comparator.capability_boundary.system_regression_case_ids
        ),
        attribution_rule=(
            "A Base failure is model-specific evidence only when the comparator succeeds on "
            "the identical case and seed. Shared failures remain unassigned; a Base success "
            "followed by a Full failure is attributed to the SciTaste augmentation path."
        ),
    )


def load_benchmark_report(path: str | Path) -> BenchmarkReport:
    report = BenchmarkReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if report.capability_boundary is None:
        boundary = build_capability_boundary(
            report.conditions,
            excluded_case_ids=report.excluded_headline_case_ids,
        )
        report = report.model_copy(update={"capability_boundary": boundary})
    return report


def save_boundary_comparison(
    comparison: CrossModelCapabilityComparison,
    output_dir: str | Path,
) -> dict[str, str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / "capability_boundary_report.json"
    content = json.dumps(comparison.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    report_path.write_text(content, encoding="utf-8")
    manifest_path = target / "capability_boundary_manifest.json"
    manifest = {
        "schema_version": comparison.schema_version,
        "method": comparison.method,
        "report": report_path.name,
        "report_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "suite_sha256": comparison.suite_sha256,
        "primary_model": comparison.primary_model,
        "comparator_model": comparison.comparator_model,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"report": str(report_path), "manifest": str(manifest_path)}


def _headline_correctness(
    report: BenchmarkReport,
    condition: BenchmarkCondition,
) -> dict[str, bool]:
    excluded = set(report.excluded_headline_case_ids)
    try:
        results = report.conditions[condition].results
    except KeyError as exc:
        raise ValueError(f"benchmark report lacks {condition.value} condition") from exc
    return {result.case_id: result.correct for result in results if result.case_id not in excluded}

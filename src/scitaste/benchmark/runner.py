"""Condition-isolated SciTasteBench runner and deterministic report persistence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import yaml

from scitaste.backends.base import PreferenceBackend
from scitaste.benchmark.attribution import build_capability_boundary
from scitaste.benchmark.models import (
    BenchmarkCase,
    BenchmarkCondition,
    BenchmarkMetrics,
    BenchmarkReport,
    BenchmarkResult,
    BenchmarkSuite,
    CandidateOrder,
    ConditionComparison,
    ConditionReport,
    TransferAxis,
)
from scitaste.taste.intrinsic import BackendProtocolError, TasteTask


class SciTasteBenchRunner:
    """Measure intrinsic and externally augmented taste on fixed candidate pairs."""

    def __init__(
        self,
        backend: PreferenceBackend,
        *,
        seed: int = 0,
        candidate_order: CandidateOrder = CandidateOrder.DECLARED,
    ) -> None:
        self.backend = backend
        self.seed = seed
        self.candidate_order = candidate_order

    def evaluate(
        self,
        suite: BenchmarkSuite,
        *,
        conditions: list[BenchmarkCondition] | None = None,
    ) -> BenchmarkReport:
        selected_conditions = conditions or suite.conditions
        if len(set(selected_conditions)) != len(selected_conditions):
            raise ValueError("selected benchmark conditions must be unique")
        unknown = set(selected_conditions) - set(suite.conditions)
        if unknown:
            raise ValueError(f"conditions are not declared by suite: {sorted(unknown)}")
        if BenchmarkCondition.BASE not in selected_conditions:
            raise ValueError("base condition is required for controlled comparisons")

        condition_reports = {
            condition: self._evaluate_condition(suite, condition)
            for condition in selected_conditions
        }
        all_results = [result for report in condition_reports.values() for result in report.results]
        models = {result.model for result in all_results}
        backends = {result.backend for result in all_results}
        if len(models) != 1 or len(backends) != 1:
            raise BackendProtocolError("one benchmark report cannot mix backends or models")
        base = condition_reports[BenchmarkCondition.BASE]
        comparisons = {
            condition: _compare(base, report, suite)
            for condition, report in condition_reports.items()
            if condition != BenchmarkCondition.BASE
        }
        excluded_headline_case_ids = [
            case.case_id for case in suite.cases if not case.headline_eligible
        ]
        return BenchmarkReport(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            suite_sha256=suite.sha256,
            backend=next(iter(backends)),
            model=next(iter(models)),
            seed=self.seed,
            candidate_order=self.candidate_order,
            conditions=condition_reports,
            comparisons_to_base=comparisons,
            excluded_headline_case_ids=excluded_headline_case_ids,
            unavailable_metrics={
                "ranking_correlation": (
                    "v1 uses fixed candidate pairs; the backend contract does not return "
                    "full rankings"
                ),
                "system_level_metrics": (
                    "research-yield and matched-budget outcome metrics belong to Phase 9"
                ),
            },
            capability_boundary=build_capability_boundary(
                condition_reports,
                excluded_case_ids=excluded_headline_case_ids,
            ),
        )

    def _evaluate_condition(
        self, suite: BenchmarkSuite, condition: BenchmarkCondition
    ) -> ConditionReport:
        results: list[BenchmarkResult] = []
        case_by_id = {case.case_id: case for case in suite.cases}
        for case in suite.cases:
            request = case.to_request(
                condition,
                seed=self.seed,
                candidate_order=self.candidate_order,
            )
            response = self.backend.rank(request)
            candidate_ids = set(case.action_roles)
            if response.request_id != request.request_id:
                raise BackendProtocolError(
                    "backend response request_id does not match benchmark case"
                )
            if response.request_fingerprint != request.fingerprint:
                raise BackendProtocolError(
                    "backend response fingerprint does not match benchmark request"
                )
            if response.selected_action_id not in candidate_ids:
                raise BackendProtocolError(
                    f"backend selected unknown action {response.selected_action_id!r}"
                )
            results.append(
                BenchmarkResult(
                    case_id=case.case_id,
                    condition=condition,
                    candidate_order=self.candidate_order,
                    task=case.task,
                    selected_action_id=response.selected_action_id,
                    selected_role=case.action_roles[response.selected_action_id],
                    preferred_action_id=case.preferred_action_id,
                    correct=response.selected_action_id == case.preferred_action_id,
                    wrong_level=response.selected_action_id in case.wrong_level_action_ids,
                    confidence=response.confidence,
                    expert_agreement=case.expert_distribution[response.selected_action_id],
                    rationale=response.rationale,
                    backend=response.backend,
                    model=response.model,
                    request_fingerprint=request.fingerprint,
                    cached=response.cached,
                    usage=response.usage,
                )
            )
        headline = [result for result in results if case_by_id[result.case_id].headline_eligible]
        return ConditionReport(
            condition=condition,
            overall=_metrics(results),
            headline=_metrics(headline),
            by_task={
                task: _metrics([result for result in headline if result.task == task])
                for task in TasteTask
                if any(result.task == task for result in headline)
            },
            transfer={
                axis: _metrics(
                    [
                        result
                        for result in headline
                        if axis in case_by_id[result.case_id].transfer_axes
                    ]
                )
                for axis in TransferAxis
                if any(axis in case_by_id[result.case_id].transfer_axes for result in headline)
            },
            style_invariance=_consistency(results, suite.cases, "style_group"),
            paraphrase_consistency=_consistency(results, suite.cases, "paraphrase_group"),
            results=results,
        )


def load_benchmark_suite(path: str | Path) -> BenchmarkSuite:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BenchmarkSuite.model_validate(data)


def scripted_selections(
    suite: BenchmarkSuite,
    conditions: list[BenchmarkCondition] | None = None,
    *,
    candidate_order: CandidateOrder = CandidateOrder.DECLARED,
) -> dict[str, str]:
    selected_conditions = conditions or suite.conditions
    selections: dict[str, str] = {}
    for case in suite.cases:
        for condition in selected_conditions:
            try:
                selections[case.request_id(condition, candidate_order)] = (
                    case.scripted_selections[condition]
                )
            except KeyError as exc:
                raise ValueError(
                    f"scripted selection missing for {case.case_id!r} / {condition.value!r}"
                ) from exc
    return selections


def save_benchmark_report(report: BenchmarkReport, output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / "benchmark_report.json"
    content = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    report_path.write_text(content, encoding="utf-8")
    manifest: dict[str, object] = {
        "schema_version": report.schema_version,
        "suite_id": report.suite_id,
        "suite_version": report.suite_version,
        "suite_sha256": report.suite_sha256,
        "backend": report.backend,
        "model": report.model,
        "seed": report.seed,
        "candidate_order": report.candidate_order.value,
        "report": report_path.name,
        "report_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "headline_case_count": report.conditions[BenchmarkCondition.BASE].headline.count,
        "excluded_headline_case_ids": report.excluded_headline_case_ids,
    }
    manifest_path = target / "benchmark_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {**manifest, "report": str(report_path), "manifest": str(manifest_path)}


def _metrics(results: list[BenchmarkResult]) -> BenchmarkMetrics:
    if not results:
        return BenchmarkMetrics(
            count=0,
            pairwise_accuracy=0,
            expert_agreement=0,
            mean_confidence=0,
            brier_score=0,
            expected_calibration_error=0,
            wrong_level_decision_rate=0,
        )
    count = len(results)
    return BenchmarkMetrics(
        count=count,
        pairwise_accuracy=_round(sum(result.correct for result in results) / count),
        expert_agreement=_round(sum(result.expert_agreement for result in results) / count),
        mean_confidence=_round(sum(result.confidence for result in results) / count),
        brier_score=_round(
            sum((result.confidence - float(result.correct)) ** 2 for result in results) / count
        ),
        expected_calibration_error=_round(_ece(results)),
        wrong_level_decision_rate=_round(sum(result.wrong_level for result in results) / count),
    )


def _ece(results: list[BenchmarkResult], bins: int = 5) -> float:
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            result
            for result in results
            if lower <= result.confidence <= upper
            and (index == bins - 1 or result.confidence < upper)
        ]
        if members:
            accuracy = sum(result.correct for result in members) / len(members)
            confidence = sum(result.confidence for result in members) / len(members)
            error += len(members) / len(results) * abs(accuracy - confidence)
    return error


def _consistency(
    results: list[BenchmarkResult], cases: list[BenchmarkCase], attribute: str
) -> float | None:
    roles = {result.case_id: result.selected_role for result in results}
    groups: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        if not case.headline_eligible:
            continue
        group = getattr(case, attribute)
        if group:
            groups[group].append(case.case_id)
    comparable = [case_ids for case_ids in groups.values() if len(case_ids) >= 2]
    if not comparable:
        return None
    consistent = sum(len({roles[case_id] for case_id in case_ids}) == 1 for case_ids in comparable)
    return _round(consistent / len(comparable))


def _compare(
    base: ConditionReport, augmented: ConditionReport, suite: BenchmarkSuite
) -> ConditionComparison:
    eligible = {case.case_id for case in suite.cases if case.headline_eligible}
    base_results = {result.case_id: result for result in base.results if result.case_id in eligible}
    augmented_results = {
        result.case_id: result for result in augmented.results if result.case_id in eligible
    }
    shared = sorted(base_results.keys() & augmented_results.keys())
    improvements = sum(
        not base_results[case_id].correct and augmented_results[case_id].correct
        for case_id in shared
    )
    regressions = sum(
        base_results[case_id].correct and not augmented_results[case_id].correct
        for case_id in shared
    )
    return ConditionComparison(
        condition=augmented.condition,
        eligible_case_count=len(shared),
        accuracy_delta=_round(
            augmented.headline.pairwise_accuracy - base.headline.pairwise_accuracy
        ),
        expert_agreement_delta=_round(
            augmented.headline.expert_agreement - base.headline.expert_agreement
        ),
        wrong_level_rate_delta=_round(
            augmented.headline.wrong_level_decision_rate - base.headline.wrong_level_decision_rate
        ),
        paired_improvements=improvements,
        paired_regressions=regressions,
        paired_unchanged=len(shared) - improvements - regressions,
    )


def _round(value: float) -> float:
    return round(value, 6)

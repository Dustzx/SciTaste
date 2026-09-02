"""Deterministic planning and auditing for matched-budget system studies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from scitaste.benchmark.study_models import (
    CellAudit,
    CellStatus,
    EvidenceClass,
    ExpertPanelReview,
    MatchedStudyProtocol,
    MatchedStudyReport,
    ReviewSource,
    StudyCell,
    StudyExecutionRecord,
    StudyPlan,
    StudyResults,
    StudyStatus,
    SystemComparison,
    SystemCondition,
    SystemMetrics,
)


def load_study_protocol(
    path: str | Path, *, asset_root: str | Path | None = None
) -> MatchedStudyProtocol:
    source = Path(path)
    protocol = MatchedStudyProtocol.model_validate(
        yaml.safe_load(source.read_text(encoding="utf-8"))
    )
    root = Path(asset_root) if asset_root is not None else Path.cwd()
    for task in protocol.tasks:
        asset = root / task.asset_path
        if not asset.is_file():
            raise FileNotFoundError(asset)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        if digest != task.asset_sha256:
            raise ValueError(
                f"task asset hash mismatch for {task.task_id!r}: "
                f"expected {task.asset_sha256}, got {digest}"
            )
    return protocol


def load_study_results(path: str | Path) -> StudyResults:
    return StudyResults.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class MatchedStudyPlanner:
    def plan(self, protocol: MatchedStudyProtocol) -> StudyPlan:
        cells: list[StudyCell] = []
        enabled = [condition for condition in protocol.conditions if condition.enabled]
        for task in protocol.tasks:
            for condition in enabled:
                for seed in protocol.seeds:
                    for repetition in range(protocol.repetitions_per_seed):
                        identity = (
                            f"{protocol.sha256}|{task.task_id}|{condition.condition.value}|"
                            f"{seed}|{repetition}"
                        )
                        cells.append(
                            StudyCell(
                                cell_id="cell-"
                                + hashlib.sha256(identity.encode()).hexdigest()[:20],
                                blind_id="blind-"
                                + hashlib.sha256(("blind|" + identity).encode()).hexdigest()[:20],
                                protocol_sha256=protocol.sha256,
                                task_id=task.task_id,
                                condition=condition.condition,
                                seed=seed,
                                repetition=repetition,
                                budget=protocol.budget,
                            )
                        )
        return StudyPlan(
            study_id=protocol.study_id,
            study_version=protocol.version,
            protocol_sha256=protocol.sha256,
            cells=cells,
            disabled_conditions={
                condition.condition: str(condition.unavailable_reason)
                for condition in protocol.conditions
                if not condition.enabled
            },
            readiness_blockers=_readiness_blockers(protocol),
        )


class MatchedStudyEvaluator:
    def evaluate(self, protocol: MatchedStudyProtocol, results: StudyResults) -> MatchedStudyReport:
        if results.protocol_sha256 != protocol.sha256:
            raise ValueError("study results do not match the protocol fingerprint")
        plan = MatchedStudyPlanner().plan(protocol)
        cells = {cell.cell_id: cell for cell in plan.cells}
        records = _unique_by(results.records, "cell_id", "execution record")
        unknown = sorted(set(records) - set(cells))
        if unknown:
            raise ValueError(f"results contain unknown study cells: {', '.join(unknown)}")
        reviews = _unique_by(results.expert_reviews, "blind_id", "expert review")

        missing = sorted(set(cells) - set(records))
        audits: list[CellAudit] = []
        blockers: list[str] = list(plan.readiness_blockers)
        accepted_records: list[StudyExecutionRecord] = []
        review_by_cell: dict[str, ExpertPanelReview] = {}
        for cell_id, record in records.items():
            cell = cells[cell_id]
            review = reviews.get(cell.blind_id)
            audit = _audit_cell(cell, record, review, protocol)
            audits.append(audit)
            if record.status != CellStatus.SUCCEEDED:
                blockers.append(f"{cell_id}: execution did not succeed")
            if not audit.telemetry_complete:
                blockers.append(f"{cell_id}: incomplete resource telemetry")
            if not audit.budget_compliant:
                blockers.append(f"{cell_id}: resource budget exceeded")
            if review is None:
                blockers.append(f"{cell_id}: expert panel review missing")
            elif not audit.expert_review_valid:
                blockers.append(f"{cell_id}: expert panel review violates protocol")
            if not audit.outcome_consistent:
                blockers.append(f"{cell_id}: result counts violate execution telemetry")
            if (
                record.status == CellStatus.SUCCEEDED
                and audit.telemetry_complete
                and audit.budget_compliant
                and audit.outcome_consistent
            ):
                accepted_records.append(record)
                if review is not None and audit.expert_review_valid:
                    review_by_cell[cell_id] = review
        if missing:
            blockers.append(f"{len(missing)} planned cells have no execution record")

        synthetic = any(
            record.evidence_class == EvidenceClass.SYNTHETIC for record in records.values()
        ) or any(review.source == ReviewSource.SYNTHETIC for review in reviews.values())
        internal_review = any(review.source == ReviewSource.INTERNAL for review in reviews.values())
        if internal_review:
            blockers.append("internal reviews cannot satisfy external expert evaluation")

        if blockers:
            status = StudyStatus.INCOMPLETE
        elif synthetic:
            status = StudyStatus.ACCEPTANCE_ONLY
        else:
            status = StudyStatus.ELIGIBLE

        by_condition = {
            condition: _system_metrics(
                [
                    (record, review_by_cell.get(record.cell_id))
                    for record in accepted_records
                    if cells[record.cell_id].condition == condition
                ]
            )
            for condition in {cell.condition for cell in plan.cells}
        }
        baseline = by_condition[SystemCondition.AUTORESEARCHCLAW]
        comparisons = {
            condition: _compare_system_metrics(baseline, metrics, condition)
            for condition, metrics in by_condition.items()
            if condition != SystemCondition.AUTORESEARCHCLAW
        }
        return MatchedStudyReport(
            study_id=protocol.study_id,
            protocol_sha256=protocol.sha256,
            plan_sha256=plan.sha256,
            status=status,
            headline_eligible=status == StudyStatus.ELIGIBLE,
            planned_cells=len(plan.cells),
            completed_cells=len(records),
            missing_cell_ids=missing,
            blockers=blockers,
            audits=sorted(audits, key=lambda audit: audit.cell_id),
            by_condition=by_condition,
            comparisons_to_autoresearchclaw=comparisons,
            disabled_conditions=plan.disabled_conditions,
        )


def save_study_plan(plan: StudyPlan, output_dir: str | Path) -> Path:
    target = Path(output_dir) / "study_plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def save_study_report(report: MatchedStudyReport, output_dir: str | Path) -> Path:
    target = Path(output_dir) / "study_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def _unique_by(items, attribute: str, label: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        key = str(getattr(item, attribute))
        if key in indexed:
            raise ValueError(f"duplicate {label} for {key!r}")
        indexed[key] = item
    return indexed


def _readiness_blockers(protocol: MatchedStudyProtocol) -> list[str]:
    blockers: list[str] = []
    revision = protocol.base_model_revision.casefold()
    if "pending" in revision or "required" in revision:
        blockers.append("base model revision is not frozen")
    snapshot = protocol.search_access.frozen_snapshot.casefold()
    if "pending" in snapshot or "required" in snapshot:
        blockers.append("search snapshot is not materialized")
    return blockers


def _audit_cell(cell, record, review, protocol) -> CellAudit:
    limits = {
        "gpu_hours": cell.budget.gpu_hours,
        "experiments": cell.budget.max_experiments,
        "wall_time_hours": cell.budget.max_wall_time_hours,
        "api_cost_usd": cell.budget.max_api_cost_usd,
        "search_queries": cell.budget.max_search_queries,
        "llm_tokens": cell.budget.max_llm_tokens,
    }
    usage = record.usage.model_dump()
    missing = [name for name in limits if usage[name] is None]
    violations = [
        name for name, limit in limits.items() if usage[name] is not None and usage[name] > limit
    ]
    review_violations: list[str] = []
    if review is not None:
        if len(review.reviewer_identity_hashes) < protocol.expert_panel.min_reviewers_per_cell:
            review_violations.append("reviewer_count")
        if review.rubric_version != protocol.expert_panel.rubric_version:
            review_violations.append("rubric_version")
    integrity_violations: list[str] = []
    if record.outcome is None:
        integrity_violations.append("outcome_missing")
    elif (
        record.usage.experiments is not None
        and record.usage.experiments != record.outcome.total_experiments
    ):
        integrity_violations.append("experiment_count_mismatch")
    return CellAudit(
        cell_id=cell.cell_id,
        telemetry_complete=not missing,
        missing_telemetry=missing,
        budget_compliant=not violations,
        budget_violations=violations,
        expert_review_present=review is not None,
        expert_review_valid=review is not None and not review_violations,
        review_violations=review_violations,
        outcome_consistent=not integrity_violations,
        integrity_violations=integrity_violations,
    )


def _system_metrics(items) -> SystemMetrics:
    records = [record for record, _ in items]
    reviews = [review for _, review in items if review is not None]
    outcomes = [record.outcome for record in records if record.outcome is not None]
    gpu = sum(float(record.usage.gpu_hours or 0) for record in records)
    proposed = sum(outcome.proposed_ideas for outcome in outcomes)
    valid = sum(outcome.valid_ideas for outcome in outcomes)
    experiments = sum(outcome.total_experiments for outcome in outcomes)
    concerns = sum(outcome.reviewer_concerns_opened for outcome in outcomes)
    claims = sum(outcome.total_claims for outcome in outcomes)
    pivots = sum(outcome.pivots for outcome in outcomes)
    signal_costs = [
        outcome.gpu_hours_before_useful_signal
        for outcome in outcomes
        if outcome.gpu_hours_before_useful_signal is not None
    ]
    count = len(records)
    return SystemMetrics(
        cell_count=count,
        research_yield_per_gpu_hour=_ratio(
            sum(outcome.useful_results for outcome in outcomes), gpu
        ),
        idea_yield=_ratio(valid, proposed),
        invalid_idea_rate=_ratio(proposed - valid, proposed),
        mean_pilots=_mean([float(outcome.pilots) for outcome in outcomes]),
        mean_discarded_ideas=_mean([float(outcome.discarded_ideas) for outcome in outcomes]),
        unproductive_experiment_rate=_ratio(
            sum(outcome.unproductive_experiments for outcome in outcomes), experiments
        ),
        mean_gpu_hours_before_useful_signal=_mean(signal_costs),
        mean_pivots=_mean([float(outcome.pivots) for outcome in outcomes]),
        evidence_sufficiency=_mean([outcome.evidence_sufficiency for outcome in outcomes]),
        reviewer_concern_closure_rate=_ratio(
            sum(outcome.reviewer_concerns_closed for outcome in outcomes), concerns
        ),
        unsupported_claim_rate=_ratio(
            sum(outcome.unsupported_claims for outcome in outcomes), claims
        ),
        correct_pivot_rate=_ratio(sum(outcome.correct_pivots for outcome in outcomes), pivots),
        problem_quality=_review_mean(reviews, "problem_quality"),
        idea_quality=_review_mean(reviews, "idea_quality"),
        evidence_quality=_review_mean(reviews, "evidence_quality"),
        story_quality=_review_mean(reviews, "story_quality"),
        writing_quality=_review_mean(reviews, "writing_quality"),
        figure_quality=_review_mean(reviews, "figure_quality"),
        final_expert_preference=_review_mean(reviews, "final_preference_score"),
    )


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _review_mean(reviews: list[ExpertPanelReview], attribute: str) -> float | None:
    return _mean([float(getattr(review, attribute)) for review in reviews])


def _compare_system_metrics(
    baseline: SystemMetrics,
    augmented: SystemMetrics,
    condition: SystemCondition,
) -> SystemComparison:
    return SystemComparison(
        condition=condition,
        comparable_cell_count=min(baseline.cell_count, augmented.cell_count),
        research_yield_delta=_delta(
            augmented.research_yield_per_gpu_hour,
            baseline.research_yield_per_gpu_hour,
        ),
        idea_yield_delta=_delta(augmented.idea_yield, baseline.idea_yield),
        unproductive_experiment_rate_delta=_delta(
            augmented.unproductive_experiment_rate,
            baseline.unproductive_experiment_rate,
        ),
        evidence_sufficiency_delta=_delta(
            augmented.evidence_sufficiency,
            baseline.evidence_sufficiency,
        ),
        unsupported_claim_rate_delta=_delta(
            augmented.unsupported_claim_rate,
            baseline.unsupported_claim_rate,
        ),
        correct_pivot_rate_delta=_delta(
            augmented.correct_pivot_rate,
            baseline.correct_pivot_rate,
        ),
        final_expert_preference_delta=_delta(
            augmented.final_expert_preference,
            baseline.final_expert_preference,
        ),
    )


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return round(value - baseline, 6)

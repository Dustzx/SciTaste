"""Offline-first execution and acceptance evaluation for the bounded pilot."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, TypeAlias

import yaml
from pydantic import BaseModel

from scitaste.model_nodes.backends import (
    ScriptedStructuredBackend,
    StructuredModelBackend,
)
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.nodes import (
    AmbiguousActionNode,
    InterpretationThreatNode,
    NodeNotApplicableError,
    NodePolicyViolationError,
    ReviewSemanticNode,
)
from scitaste.model_nodes.openai_compatible import StructuredOpenAICompatibleBackend
from scitaste.model_nodes.pilot_models import (
    AcceptanceMetric,
    AcceptanceStatus,
    ExpectedApplicability,
    IndependentOutcomeReview,
    ManualMeasurementRole,
    PilotAcceptance,
    PilotCase,
    PilotCaseResult,
    PilotCondition,
    PilotNodeType,
    PilotOutcome,
    PilotProtocol,
    PilotReport,
    PilotStatistics,
    ReplayEvidenceRole,
    ReviewDecision,
    canonical_sha256,
)
from scitaste.model_nodes.replay import RecordingStructuredBackend, ReplayStructuredBackend

BackendFactory: TypeAlias = Callable[[], StructuredModelBackend]
BackendBinding: TypeAlias = StructuredModelBackend | BackendFactory


class PilotConfigurationError(ValueError):
    """Raised when a condition is bound to an unsafe or misleading backend."""


_NODES = {
    PilotNodeType.REVIEW_SEMANTIC: ReviewSemanticNode,
    PilotNodeType.INTERPRETATION_THREAT: InterpretationThreatNode,
    PilotNodeType.AMBIGUOUS_ACTION: AmbiguousActionNode,
}

_UNSUPPORTED_MARKERS = (
    "unknown claim",
    "unknown evidence",
    "unknown section",
    "unpermitted evidence",
    "action type",
    "ranked action ids",
)


class BoundedPilotRunner:
    """Run a versioned protocol without provider fallback or hidden live calls."""

    def __init__(self, *, backends: Mapping[str, BackendBinding] | None = None) -> None:
        self._bindings = dict(backends or {})
        self._resolved: dict[str, StructuredModelBackend] = {}

    def run(
        self,
        protocol: PilotProtocol,
        *,
        report_id: str,
        generated_at: datetime,
        independent_outcome_review: IndependentOutcomeReview | None = None,
    ) -> PilotReport:
        """Execute cases in declared order and return a hash-verified report."""

        protocol = _strict_copy(PilotProtocol, protocol)
        self._resolved = {}
        case_results = tuple(self._run_case(case) for case in protocol.cases)
        statistics = _statistics(protocol, case_results)
        acceptance = evaluate_acceptance(
            protocol,
            case_results,
            statistics,
            independent_outcome_review,
        )
        return PilotReport.create(
            schema_version="1.0",
            report_id=report_id,
            generated_at=generated_at,
            protocol_id=protocol.protocol_id,
            protocol_version=protocol.protocol_version,
            protocol_sha256=protocol.fingerprint,
            self_dogfooding_only=True,
            retrieval_eligible=False,
            effectiveness_claim=False,
            case_results=case_results,
            statistics=statistics,
            independent_outcome_review=independent_outcome_review,
            acceptance=acceptance,
        )

    def _run_case(self, case: PilotCase) -> PilotCaseResult:
        if case.condition is PilotCondition.DETERMINISTIC_ONLY:
            baseline = {
                "case_id": case.case_id,
                "condition": case.condition.value,
                "node_type": case.node_type.value,
                "input": case.node_input.model_dump(mode="json"),
                "context": case.context.model_dump(mode="json"),
                "policy": case.policy.model_dump(mode="json"),
                "manual_intervention": case.manual_intervention.model_dump(mode="json"),
            }
            return _case_result(
                case,
                outcome=PilotOutcome.BASELINE,
                invoked=False,
                schema_valid=None,
                baseline_fingerprint=canonical_sha256(baseline),
            )

        if case.condition is PilotCondition.LIVE_STRUCTURED_NODE and (
            case.backend_key not in self._bindings
        ):
            return _case_result(
                case,
                outcome=PilotOutcome.PLANNED,
                invoked=False,
                schema_valid=None,
            )

        backend = self._backend_for(case)
        node = _NODES[case.node_type]()
        try:
            result = node.run(
                case.validated_node_input(),
                context=case.context.value,
                backend=backend,
                policy=case.policy.value,
                request_id=case.request_id,
                seed=case.seed,
            )
        except NodeNotApplicableError as exc:
            return _case_result(
                case,
                outcome=PilotOutcome.NOT_APPLICABLE,
                invoked=False,
                schema_valid=None,
                backend_id=backend.name,
                model_id=backend.model,
                rejection_reasons=(str(exc),),
            )
        except NodePolicyViolationError as exc:
            return _case_result(
                case,
                outcome=PilotOutcome.REJECTED,
                invoked=False,
                schema_valid=None,
                backend_id=backend.name,
                model_id=backend.model,
                rejection_reasons=(str(exc),),
            )
        return _node_case_result(case, result, backend=backend)

    def _backend_for(self, case: PilotCase) -> StructuredModelBackend:
        assert case.backend_key is not None
        if case.backend_key not in self._bindings:
            raise PilotConfigurationError(
                f"case {case.case_id!r} has no backend binding {case.backend_key!r}"
            )
        if case.backend_key not in self._resolved:
            binding = self._bindings[case.backend_key]
            backend = binding() if callable(binding) else binding
            if not isinstance(backend, StructuredModelBackend):
                raise PilotConfigurationError(
                    f"backend binding {case.backend_key!r} does not implement the protocol"
                )
            self._resolved[case.backend_key] = backend
        backend = self._resolved[case.backend_key]

        if case.condition is PilotCondition.SCRIPTED_NODE:
            valid_scripted = isinstance(backend, ScriptedStructuredBackend) or (
                isinstance(backend, RecordingStructuredBackend)
                and isinstance(backend.delegate, ScriptedStructuredBackend)
            )
            if not valid_scripted:
                raise PilotConfigurationError(
                    "scripted_node requires ScriptedStructuredBackend or its recording wrapper"
                )
        elif case.condition is PilotCondition.REPLAY_NODE:
            if not isinstance(backend, ReplayStructuredBackend):
                raise PilotConfigurationError(
                    "replay_node requires the exact ReplayStructuredBackend"
                )
        elif case.condition is PilotCondition.LIVE_STRUCTURED_NODE:
            if not isinstance(backend, StructuredOpenAICompatibleBackend):
                raise PilotConfigurationError(
                    "live_structured_node requires StructuredOpenAICompatibleBackend"
                )
            if not backend.config.live_enabled:
                raise PilotConfigurationError(
                    "live_structured_node backend is explicitly bound but live_enabled is false"
                )
        return backend


def _node_case_result(
    case: PilotCase,
    result: NodeResult[Any],
    *,
    backend: StructuredModelBackend,
) -> PilotCaseResult:
    response = result.response
    reasons = tuple(result.rejection_reasons)
    schema_valid = not any(reason.startswith("output schema violation:") for reason in reasons)
    outcome = (
        PilotOutcome.ACCEPTED
        if result.status is NodeResultStatus.ACCEPTED
        else PilotOutcome.REJECTED
    )
    response_payload = response.model_dump(mode="json")
    response_payload.pop("cached", None)
    tool_count = len(response.tool_calls)
    return _case_result(
        case,
        outcome=outcome,
        invoked=True,
        schema_valid=schema_valid,
        backend_id=response.backend,
        model_id=response.model,
        request_fingerprint=result.request.fingerprint,
        response_fingerprint=canonical_sha256(response_payload),
        result_fingerprint=canonical_sha256(result),
        recorded=isinstance(backend, RecordingStructuredBackend),
        cached=response.cached,
        rejection_reasons=reasons,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        cost_usd=response.usage.cost_usd,
        latency_ms=response.latency_ms,
        tool_call_proposal_count=tool_count,
        unbounded_tool_call_count=max(
            0,
            tool_count - case.budget.max_tool_call_proposals,
        ),
        unsupported_claim_reference_action_count=sum(
            any(marker in reason.casefold() for marker in _UNSUPPORTED_MARKERS)
            for reason in reasons
        ),
    )


def _case_result(case: PilotCase, **values: Any) -> PilotCaseResult:
    payload = {
        "schema_version": "1.0",
        "case_id": case.case_id,
        "condition": case.condition,
        "node_type": case.node_type,
        "expected_outcome": values["outcome"] in case.allowed_outcomes,
        "replay_pair_id": case.replay_pair_id,
        "replay_role": case.replay_role,
        "manual_intervention": case.manual_intervention,
        **values,
    }
    evidence_payload = {
        key: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        for key, value in payload.items()
    }
    evidence_payload = _jsonable(evidence_payload)
    return PilotCaseResult(
        **payload,
        evidence_fingerprint=canonical_sha256(evidence_payload),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _statistics(
    protocol: PilotProtocol,
    results: tuple[PilotCaseResult, ...],
) -> PilotStatistics:
    baselines = [
        result.manual_intervention.count
        for result in results
        if result.manual_intervention
        and result.manual_intervention.role is ManualMeasurementRole.BASELINE
    ]
    observed = [
        result.manual_intervention.count
        for result in results
        if result.manual_intervention
        and result.manual_intervention.role is ManualMeasurementRole.OBSERVED
    ]
    manual_baseline = sum(baselines) if baselines else None
    manual_observed = sum(observed) if observed else None
    manual_reduction = (
        (manual_baseline - manual_observed) / manual_baseline
        if manual_baseline is not None and manual_baseline > 0 and manual_observed is not None
        else None
    )

    pair_ids = sorted({case.replay_pair_id for case in protocol.cases if case.replay_pair_id})
    covered_pairs = 0
    for pair_id in pair_ids:
        pair_results = [result for result in results if result.replay_pair_id == pair_id]
        by_role = {result.replay_role: result for result in pair_results}
        recording = by_role.get(ReplayEvidenceRole.RECORDING)
        replay = by_role.get(ReplayEvidenceRole.REPLAY)
        if (
            recording is not None
            and replay is not None
            and recording.outcome is PilotOutcome.ACCEPTED
            and replay.outcome is PilotOutcome.ACCEPTED
            and recording.invoked
            and replay.invoked
            and recording.recorded
            and not recording.cached
            and replay.cached
            and recording.request_fingerprint == replay.request_fingerprint
            and recording.response_fingerprint == replay.response_fingerprint
        ):
            covered_pairs += 1
    replay_coverage = covered_pairs / len(pair_ids) if pair_ids else None

    gate_bypasses = sum(
        (
            result.outcome is PilotOutcome.ACCEPTED
            and (
                case.gate_probe
                or PilotOutcome.ACCEPTED not in case.allowed_outcomes
                or case.expected_applicability is ExpectedApplicability.NOT_APPLICABLE
            )
        )
        or (
            case.expected_applicability is ExpectedApplicability.NOT_APPLICABLE
            and result.outcome not in {PilotOutcome.NOT_APPLICABLE, PilotOutcome.PLANNED}
        )
        for case, result in zip(protocol.cases, results, strict=True)
    )

    costs = [result.cost_usd for result in results if result.invoked]
    cost_complete = all(cost is not None for cost in costs)
    aggregate_cost = (
        sum(
            result.cost_usd
            for result in results
            if result.invoked and not result.cached and result.cost_usd is not None
        )
        if cost_complete
        else None
    )
    project_costs = {case.context.value.project_id: 0.0 for case in protocol.cases}
    for case, result in zip(protocol.cases, results, strict=True):
        if result.invoked and not result.cached and result.cost_usd is not None:
            project_costs[case.context.value.project_id] += result.cost_usd

    return PilotStatistics(
        case_count=len(results),
        planned_count=sum(result.outcome is PilotOutcome.PLANNED for result in results),
        invoked_count=sum(result.invoked for result in results),
        not_applicable_count=sum(
            result.outcome is PilotOutcome.NOT_APPLICABLE for result in results
        ),
        accepted_count=sum(result.outcome is PilotOutcome.ACCEPTED for result in results),
        rejected_count=sum(result.outcome is PilotOutcome.REJECTED for result in results),
        successful_count=sum(result.outcome is PilotOutcome.ACCEPTED for result in results),
        schema_valid_count=sum(result.schema_valid is True for result in results),
        schema_invalid_count=sum(result.schema_valid is False for result in results),
        gate_bypass_count=gate_bypasses,
        unsupported_claim_reference_action_count=sum(
            result.unsupported_claim_reference_action_count for result in results
        ),
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
        total_tokens=sum(result.total_tokens for result in results),
        cost_usd=aggregate_cost,
        cost_telemetry_complete=cost_complete,
        additional_api_cost_by_project_usd=project_costs,
        latency_ms=sum(result.latency_ms for result in results),
        manual_intervention_baseline=manual_baseline,
        manual_intervention_observed=manual_observed,
        manual_intervention_reduction=manual_reduction,
        exact_replay_pair_count=len(pair_ids),
        exact_replay_covered_count=covered_pairs,
        exact_replay_coverage=replay_coverage,
        unbounded_tool_call_count=sum(result.unbounded_tool_call_count for result in results),
    )


def evaluate_acceptance(
    protocol: PilotProtocol,
    results: tuple[PilotCaseResult, ...],
    statistics: PilotStatistics,
    review: IndependentOutcomeReview | None,
) -> PilotAcceptance:
    """Evaluate every fixed threshold, blocking rather than imputing missing data."""

    thresholds = protocol.acceptance_thresholds
    metrics: list[AcceptanceMetric] = []

    schema_rate = (
        statistics.schema_valid_count / statistics.invoked_count
        if statistics.invoked_count
        else None
    )
    metrics.append(
        _minimum_metric(
            "schema_valid_rate",
            schema_rate,
            thresholds.minimum_schema_valid_rate,
            "No invoked cases provide a schema-validity denominator.",
        )
    )
    metrics.append(
        _maximum_metric(
            "gate_bypass_count",
            statistics.gate_bypass_count,
            thresholds.maximum_gate_bypass_count,
        )
    )
    metrics.append(_planned_case_metric(statistics.planned_count))
    metrics.append(
        _minimum_metric(
            "exact_replay_coverage",
            statistics.exact_replay_coverage,
            thresholds.minimum_exact_replay_coverage,
            "No complete recording/replay pair evidence is available.",
        )
    )
    metrics.append(
        _minimum_metric(
            "manual_intervention_reduction",
            statistics.manual_intervention_reduction,
            thresholds.minimum_manual_intervention_reduction,
            "A positive manual baseline and observed intervention count are required.",
        )
    )

    unsupported_baseline = thresholds.unsupported_claim_reference_action_baseline
    if unsupported_baseline is None:
        metrics.append(
            AcceptanceMetric(
                metric_id="unsupported_claim_reference_action_increase",
                status=AcceptanceStatus.BLOCKED,
                observed=None,
                threshold=thresholds.maximum_unsupported_claim_reference_action_increase,
                detail="Unsupported-claim/reference/action baseline is missing.",
            )
        )
    else:
        increase = statistics.unsupported_claim_reference_action_count - unsupported_baseline
        metrics.append(
            _maximum_metric(
                "unsupported_claim_reference_action_increase",
                increase,
                thresholds.maximum_unsupported_claim_reference_action_increase,
            )
        )

    metrics.append(
        _maximum_metric(
            "unbounded_tool_call_count",
            statistics.unbounded_tool_call_count,
            thresholds.maximum_unbounded_tool_call_count,
        )
    )

    max_project_cost = (
        max(statistics.additional_api_cost_by_project_usd.values(), default=0.0)
        if statistics.cost_telemetry_complete
        else None
    )
    metrics.append(
        _maximum_metric(
            "additional_api_cost_per_project_usd",
            max_project_cost,
            thresholds.maximum_additional_api_cost_per_project_usd,
            missing_detail="Complete cost telemetry is required for every invoked case.",
        )
    )

    unexpected = sum(not result.expected_outcome for result in results)
    metrics.append(_maximum_metric("protocol_outcome_mismatch_count", unexpected, 0))
    metrics.append(_review_metric(review))

    statuses = {metric.status for metric in metrics}
    overall = (
        AcceptanceStatus.BLOCKED
        if AcceptanceStatus.BLOCKED in statuses
        else AcceptanceStatus.FAIL
        if AcceptanceStatus.FAIL in statuses
        else AcceptanceStatus.PASS
    )
    return PilotAcceptance(
        overall_status=overall,
        eligible=overall is AcceptanceStatus.PASS,
        metrics=tuple(metrics),
    )


def _minimum_metric(
    metric_id: str,
    observed: float | None,
    threshold: float,
    missing_detail: str,
) -> AcceptanceMetric:
    if observed is None:
        return AcceptanceMetric(
            metric_id=metric_id,
            status=AcceptanceStatus.BLOCKED,
            observed=None,
            threshold=threshold,
            detail=missing_detail,
        )
    passed = observed >= threshold
    return AcceptanceMetric(
        metric_id=metric_id,
        status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        observed=observed,
        threshold=threshold,
        detail="Observed value meets the minimum."
        if passed
        else "Observed value is below the minimum.",
    )


def _maximum_metric(
    metric_id: str,
    observed: int | float | None,
    threshold: int | float,
    *,
    missing_detail: str = "Required observations are missing.",
) -> AcceptanceMetric:
    if observed is None:
        return AcceptanceMetric(
            metric_id=metric_id,
            status=AcceptanceStatus.BLOCKED,
            observed=None,
            threshold=threshold,
            detail=missing_detail,
        )
    passed = observed <= threshold
    return AcceptanceMetric(
        metric_id=metric_id,
        status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        observed=observed,
        threshold=threshold,
        detail="Observed value meets the maximum."
        if passed
        else "Observed value exceeds the maximum.",
    )


def _review_metric(review: IndependentOutcomeReview | None) -> AcceptanceMetric:
    if review is None:
        return AcceptanceMetric(
            metric_id="independent_outcome_review",
            status=AcceptanceStatus.BLOCKED,
            observed=None,
            threshold=ReviewDecision.APPROVED.value,
            detail="Independent outcome review evidence is missing.",
        )
    if not review.independent:
        status = AcceptanceStatus.FAIL
        detail = "The submitted reviewer is not independent."
    elif review.decision is ReviewDecision.INCONCLUSIVE:
        status = AcceptanceStatus.BLOCKED
        detail = "Independent review is inconclusive."
    elif review.decision is ReviewDecision.REJECTED:
        status = AcceptanceStatus.FAIL
        detail = "Independent review rejected the outcomes."
    else:
        status = AcceptanceStatus.PASS
        detail = "Independent review approved the outcomes."
    return AcceptanceMetric(
        metric_id="independent_outcome_review",
        status=status,
        observed=review.decision.value,
        threshold=ReviewDecision.APPROVED.value,
        detail=detail,
    )


def _planned_case_metric(planned_count: int) -> AcceptanceMetric:
    if planned_count:
        return AcceptanceMetric(
            metric_id="planned_case_count",
            status=AcceptanceStatus.BLOCKED,
            observed=planned_count,
            threshold=0,
            detail="Planned live cases have no invocation evidence.",
        )
    return AcceptanceMetric(
        metric_id="planned_case_count",
        status=AcceptanceStatus.PASS,
        observed=0,
        threshold=0,
        detail="Every planned case has invocation evidence.",
    )


def load_pilot_protocol(path: str | Path) -> PilotProtocol:
    """Load a strict YAML protocol without accepting undeclared keys."""

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PilotProtocol.model_validate_json(
        json.dumps(data, ensure_ascii=False, allow_nan=False),
        strict=True,
    )


def save_pilot_report(
    report: PilotReport,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically persist a verified canonical report, refusing overwrite by default."""

    report = _strict_copy(PilotReport, report)
    if not report.verify_sha256():
        raise ValueError("refusing to persist a report with an invalid canonical hash")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            report.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(f"pilot report already exists: {target}") from exc
            temporary.unlink()
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_pilot_report(path: str | Path) -> PilotReport:
    """Load and verify a strict pilot report."""

    return PilotReport.model_validate_json(Path(path).read_text(encoding="utf-8"), strict=True)


def _strict_copy(model_type: type[BaseModel], value: BaseModel) -> Any:
    return model_type.model_validate_json(
        value.model_dump_json(exclude_computed_fields=True),
        strict=True,
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

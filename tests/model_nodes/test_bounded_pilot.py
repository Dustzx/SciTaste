from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.evidence.interpretation import ClaimRelation, InterpretationContext, ResultRecord
from scitaste.model_nodes.backends import ScriptedStructuredBackend, ScriptedStructuredReply
from scitaste.model_nodes.models import (
    ModelCostProvenance,
    NodeContext,
    NodePolicy,
    ToolCallProposal,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPResponse,
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
)
from scitaste.model_nodes.pilot_models import (
    AcceptanceStatus,
    ExpectedApplicability,
    IndependentOutcomeReview,
    ManualInterventionMeasurement,
    ManualInterventionRequirement,
    ManualMeasurementRole,
    PilotAcceptanceThresholds,
    PilotBudget,
    PilotCase,
    PilotCondition,
    PilotNodeType,
    PilotOutcome,
    PilotProtocol,
    ReplayEvidenceRole,
    ReviewDecision,
    VersionedNodeContext,
    VersionedNodeInput,
    VersionedNodePolicy,
)
from scitaste.model_nodes.pilot_runner import (
    BoundedPilotRunner,
    PilotConfigurationError,
    load_pilot_protocol,
    load_pilot_report,
    save_pilot_report,
)
from scitaste.model_nodes.replay import RecordingStructuredBackend, ReplayStructuredBackend
from scitaste.model_nodes.schemas import (
    AmbiguousActionInput,
    InterpretationThreatInput,
    ReviewSemanticInput,
)
from scitaste.schema.actions import MetaAction, ResearchAction

NOW = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)


def _actions() -> list[ResearchAction]:
    return [
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe."),
        ResearchAction(
            action_id="reproduce",
            type=MetaAction.REPRODUCE,
            description="Reproduce.",
        ),
    ]


def _context(*, actions: list[ResearchAction] | None = None) -> NodeContext:
    return NodeContext(
        project_id="scitaste-self-development",
        stage="COMMUNICATION",
        state_snapshot_id="snapshot-1",
        cumulative_api_cost_usd=0.0,
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
        section_ids=["method"],
        candidate_actions=actions or [],
    )


def _policy(
    node_type: PilotNodeType,
    *,
    enabled: bool = True,
    backend: str = "scripted",
    model: str = "scripted-v1",
) -> NodePolicy:
    action_types: list[MetaAction]
    if node_type is PilotNodeType.REVIEW_SEMANTIC:
        action_types = [MetaAction.ADD_BASELINE]
    elif node_type is PilotNodeType.INTERPRETATION_THREAT:
        action_types = [MetaAction.REPRODUCE]
    else:
        action_types = [MetaAction.PROBE, MetaAction.REPRODUCE]
    return NodePolicy(
        policy_id=f"pilot-{node_type.value}",
        enabled=enabled,
        allowed_node_names=[node_type.value] if enabled else [],
        expected_backend=backend,
        expected_model=model,
        allowed_action_types=action_types,
        max_request_bytes=100_000,
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens=200,
        max_api_cost_usd=0.15,
        max_latency_ms=1_000,
        ambiguity_margin_max=0.05,
    )


def _budget() -> PilotBudget:
    return PilotBudget(
        max_input_tokens=100,
        max_output_tokens=100,
        max_request_bytes=100_000,
        max_latency_ms=1_000,
        max_api_cost_usd=0.15,
        max_project_api_cost_usd=0.15,
        max_tool_call_proposals=0,
    )


def _review_input() -> ReviewSemanticInput:
    return ReviewSemanticInput(
        review_text="The claim needs a matched baseline.",
        permitted_evidence_types=["matched baseline"],
    )


def _interpretation_input() -> InterpretationThreatInput:
    return InterpretationThreatInput(
        result=ResultRecord(
            result_id="result-1",
            experiment_id="experiment-1",
            summary="Accuracy increased.",
            metrics={"accuracy": 0.85},
        ),
        interpretation_context=InterpretationContext(
            claim_id="claim-1",
            evidence_type="held-out benchmark",
            expected="Accuracy should increase.",
            observed="Accuracy increased.",
            relation=ClaimRelation.SUPPORTS,
            reproducible=True,
            stability=0.8,
        ),
    )


def _ambiguous_input(*, clear: bool = False) -> AmbiguousActionInput:
    return AmbiguousActionInput(
        decision_context="Choose between two feasible actions.",
        candidate_actions=_actions(),
        deterministic_scores=(
            {"probe": 0.9, "reproduce": 0.5} if clear else {"probe": 0.51, "reproduce": 0.50}
        ),
    )


def _case(
    case_id: str,
    *,
    condition: PilotCondition,
    node_type: PilotNodeType,
    node_input: ReviewSemanticInput | InterpretationThreatInput | AmbiguousActionInput,
    context: NodeContext,
    allowed_outcomes: tuple[PilotOutcome, ...],
    applicability: ExpectedApplicability = ExpectedApplicability.APPLICABLE,
    backend_key: str | None,
    policy: NodePolicy | None = None,
    request_id: str | None = None,
    replay_pair_id: str | None = None,
    replay_role: ReplayEvidenceRole | None = None,
    manual_requirement: ManualInterventionRequirement | None = None,
) -> PilotCase:
    if policy is None:
        policy = _policy(node_type, enabled=condition is not PilotCondition.DETERMINISTIC_ONLY)
    return PilotCase(
        case_id=case_id,
        case_version="1.0",
        condition=condition,
        node_type=node_type,
        seed=7,
        request_id=request_id or case_id,
        backend_key=backend_key,
        expected_backend_id=policy.expected_backend,
        expected_model_id=policy.expected_model,
        budget=_budget(),
        node_input=VersionedNodeInput(payload=node_input.model_dump(mode="json")),
        context=VersionedNodeContext(value=context),
        policy=VersionedNodePolicy(value=policy),
        expected_applicability=applicability,
        allowed_outcomes=allowed_outcomes,
        replay_pair_id=replay_pair_id,
        replay_role=replay_role,
        manual_intervention_requirement=manual_requirement,
    )


def _protocol() -> PilotProtocol:
    ambiguous = _ambiguous_input()
    cases = (
        _case(
            "manual-review-baseline",
            condition=PilotCondition.DETERMINISTIC_ONLY,
            node_type=PilotNodeType.REVIEW_SEMANTIC,
            node_input=_review_input(),
            context=_context(),
            allowed_outcomes=(PilotOutcome.BASELINE,),
            backend_key=None,
            policy=_policy(PilotNodeType.REVIEW_SEMANTIC, enabled=False),
            manual_requirement=ManualInterventionRequirement(
                role=ManualMeasurementRole.BASELINE,
                requires_handleable_without_model=True,
            ),
        ),
        _case(
            "review-scripted",
            condition=PilotCondition.SCRIPTED_NODE,
            node_type=PilotNodeType.REVIEW_SEMANTIC,
            node_input=_review_input(),
            context=_context(),
            allowed_outcomes=(PilotOutcome.ACCEPTED,),
            backend_key="review",
            manual_requirement=ManualInterventionRequirement(
                role=ManualMeasurementRole.OBSERVED,
            ),
        ),
        _case(
            "interpretation-scripted",
            condition=PilotCondition.SCRIPTED_NODE,
            node_type=PilotNodeType.INTERPRETATION_THREAT,
            node_input=_interpretation_input(),
            context=_context(),
            allowed_outcomes=(PilotOutcome.ACCEPTED,),
            backend_key="interpretation",
        ),
        _case(
            "ambiguous-recording",
            condition=PilotCondition.SCRIPTED_NODE,
            node_type=PilotNodeType.AMBIGUOUS_ACTION,
            node_input=ambiguous,
            context=_context(actions=ambiguous.candidate_actions),
            allowed_outcomes=(PilotOutcome.ACCEPTED,),
            backend_key="recording",
            request_id="ambiguous-paired-request",
            replay_pair_id="ambiguous-pair",
            replay_role=ReplayEvidenceRole.RECORDING,
        ),
        _case(
            "ambiguous-replay",
            condition=PilotCondition.REPLAY_NODE,
            node_type=PilotNodeType.AMBIGUOUS_ACTION,
            node_input=ambiguous,
            context=_context(actions=ambiguous.candidate_actions),
            allowed_outcomes=(PilotOutcome.ACCEPTED,),
            backend_key="replay",
            request_id="ambiguous-paired-request",
            replay_pair_id="ambiguous-pair",
            replay_role=ReplayEvidenceRole.REPLAY,
        ),
        _case(
            "ambiguous-clear-margin",
            condition=PilotCondition.SCRIPTED_NODE,
            node_type=PilotNodeType.AMBIGUOUS_ACTION,
            node_input=_ambiguous_input(clear=True),
            context=_context(actions=_actions()),
            allowed_outcomes=(PilotOutcome.NOT_APPLICABLE,),
            applicability=ExpectedApplicability.NOT_APPLICABLE,
            backend_key="clear",
        ),
        _case(
            "interpretation-live-plan",
            condition=PilotCondition.LIVE_STRUCTURED_NODE,
            node_type=PilotNodeType.INTERPRETATION_THREAT,
            node_input=_interpretation_input(),
            context=_context(),
            allowed_outcomes=(
                PilotOutcome.PLANNED,
                PilotOutcome.ACCEPTED,
                PilotOutcome.REJECTED,
            ),
            backend_key="live",
            policy=_policy(
                PilotNodeType.INTERPRETATION_THREAT,
                backend="zhipu-direct",
                model="glm-5.3-flash",
            ),
        ),
    )
    return PilotProtocol(
        protocol_id="bounded-model-node-self-development",
        protocol_version="1.0.0",
        created_at=NOW,
        cases=cases,
        acceptance_thresholds=PilotAcceptanceThresholds(
            minimum_schema_valid_rate=0.98,
            maximum_gate_bypass_count=0,
            minimum_exact_replay_coverage=1.0,
            minimum_manual_intervention_reduction=0.30,
            unsupported_claim_reference_action_baseline=0,
            maximum_unsupported_claim_reference_action_increase=0,
            maximum_unbounded_tool_call_count=0,
            maximum_additional_api_cost_per_project_usd=0.15,
            independent_outcome_review_required=True,
        ),
    )


def _review_payload(*, claim_id: str = "claim-1") -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "missing_baseline",
                "severity": "high",
                "target_claim_ids": [claim_id],
                "target_section": "method",
                "text": "The claim needs a matched baseline.",
                "requires_new_evidence": True,
                "requires_new_experiment": True,
                "required_evidence_types": ["matched baseline"],
                "proposed_action_type": "ADD_BASELINE",
            }
        ],
        "summary": "One concern.",
        "confidence": 0.9,
    }


def _interpretation_payload() -> dict[str, object]:
    return {
        "threats": [
            {
                "threat_id": "threat-1",
                "kind": "benchmark_artifact",
                "statement": "The gain may be benchmark-specific.",
                "evidence_ids": ["evidence-1"],
                "confidence": 0.7,
            }
        ],
        "alternative_explanations": ["Template overlap"],
        "recommended_action_type": "REPRODUCE",
        "rationale": "Reproduction separates the explanations.",
        "confidence": 0.8,
    }


def _ambiguous_payload() -> dict[str, object]:
    return {
        "ranked_action_ids": ["reproduce", "probe"],
        "preferred_action_id": "reproduce",
        "rationale": "Reproduction addresses the larger uncertainty.",
        "confidence": 0.6,
    }


def _scripted(
    request_id: str,
    payload: object,
    *,
    usage: Usage | None = None,
    tool_calls: list[ToolCallProposal] | None = None,
) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            request_id: ScriptedStructuredReply(
                output_payload=payload,
                usage=usage or Usage(cost_usd=0.0),
                latency_ms=4,
                tool_calls=tool_calls or [],
            )
        },
    )


class _LiveFakeTransport:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout: float,
    ) -> StructuredHTTPResponse:
        del url, headers, payload, timeout
        response = {
            "choices": [
                {
                    "message": {"content": json.dumps(_interpretation_payload())},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            "model": "glm-5.3-flash",
        }
        raw = json.dumps(response, sort_keys=True, separators=(",", ":"))
        return StructuredHTTPResponse(data=response, raw_body=raw)


def _live_backend() -> StructuredOpenAICompatibleBackend:
    return StructuredOpenAICompatibleBackend(
        StructuredOpenAICompatibleConfig(
            provider="zhipu-direct",
            base_url="http://localhost:9999/v1",
            model="glm-5.3-flash",
            api_key_env="SCITASTE_PILOT_TEST_KEY",
            live_enabled=True,
            max_retries=0,
            max_output_tokens=100,
            pricing_confirmed=True,
            pricing=ModelCostProvenance(
                input_usd_per_million_tokens=100.0,
                output_usd_per_million_tokens=100.0,
                captured_at=NOW,
                source="fixed offline test pricing",
            ),
        ),
        transport=_LiveFakeTransport(),
    )


def _bindings(
    replay_path: Path,
    *,
    review_payload: object | None = None,
    include_live: bool = False,
) -> dict[str, object]:
    recording = RecordingStructuredBackend(
        _scripted("ambiguous-paired-request", _ambiguous_payload()),
        replay_path,
    )
    bindings: dict[str, object] = {
        "review": _scripted(
            "review-scripted",
            review_payload if review_payload is not None else _review_payload(),
            usage=Usage(input_tokens=11, output_tokens=7, cost_usd=0.01),
        ),
        "interpretation": _scripted(
            "interpretation-scripted",
            _interpretation_payload(),
            usage=Usage(input_tokens=13, output_tokens=8, cost_usd=0.02),
        ),
        "recording": recording,
        "replay": lambda: ReplayStructuredBackend(replay_path),
        "clear": ScriptedStructuredBackend(
            name="scripted",
            model="scripted-v1",
            replies={},
        ),
    }
    if include_live:
        bindings["live"] = _live_backend()
    return bindings


def _committed_protocol_bindings(replay_path: Path) -> dict[str, object]:
    bindings = _bindings(replay_path)
    return {
        "review-scripted": bindings["review"],
        "interpretation-scripted": bindings["interpretation"],
        "ambiguous-recording": bindings["recording"],
        "ambiguous-replay": bindings["replay"],
        "ambiguous-clear-margin": bindings["clear"],
    }


def _review() -> IndependentOutcomeReview:
    return IndependentOutcomeReview(
        review_id="synthetic-pytest-review",
        reviewer_id="synthetic-independent-test-reviewer",
        reviewed_at=NOW,
        independent=True,
        decision=ReviewDecision.APPROVED,
        evidence_sha256=hashlib.sha256(b"synthetic pytest outcome review").hexdigest(),
    )


def _synthetic_measurements() -> dict[str, ManualInterventionMeasurement]:
    """Test-only measurements; these are not evidence for the committed pilot."""

    return {
        "manual-review-baseline": ManualInterventionMeasurement(
            case_id="manual-review-baseline",
            role=ManualMeasurementRole.BASELINE,
            count=10,
            source="synthetic pytest baseline fixture",
            evidence_sha256=hashlib.sha256(b"synthetic pytest baseline").hexdigest(),
            handleable_without_model=True,
        ),
        "review-scripted": ManualInterventionMeasurement(
            case_id="review-scripted",
            role=ManualMeasurementRole.OBSERVED,
            count=6,
            source="synthetic pytest observed fixture",
            evidence_sha256=hashlib.sha256(b"synthetic pytest observed").hexdigest(),
        ),
    }


def _run(tmp_path: Path, **updates: object):
    return BoundedPilotRunner(backends=_bindings(tmp_path / "exact-replay.jsonl", **updates)).run(
        _protocol(),
        report_id="pilot-report-1",
        generated_at=NOW,
        manual_interventions=_synthetic_measurements(),
        independent_outcome_review=_review(),
    )


def test_full_offline_pilot_with_fake_live_transport_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITASTE_PILOT_TEST_KEY", "offline-placeholder")
    report = _run(tmp_path, include_live=True)

    assert report.verify_sha256()
    assert report.acceptance.overall_status is AcceptanceStatus.PASS
    assert report.statistics.case_count == 7
    assert report.statistics.planned_count == 0
    assert report.statistics.invoked_count == 5
    assert report.statistics.accepted_count == 5
    assert report.statistics.successful_count == 5
    assert report.statistics.rejected_count == 0
    assert report.statistics.not_applicable_count == 1
    assert report.statistics.total_tokens == 48
    assert report.statistics.cost_usd == pytest.approx(0.0309)
    assert report.statistics.additional_api_cost_by_project_usd == {
        "scitaste-self-development": pytest.approx(0.0309)
    }
    assert report.statistics.latency_ms >= 16
    assert all(result.evidence_fingerprint for result in report.case_results)
    assert report.retrieval_eligible is False
    assert report.effectiveness_claim is False


def test_exact_replay_requires_paired_recording_evidence(tmp_path: Path) -> None:
    report = _run(tmp_path)
    recording, replay = [
        result for result in report.case_results if result.replay_pair_id == "ambiguous-pair"
    ]

    assert recording.recorded is True
    assert recording.cached is False
    assert replay.cached is True
    assert recording.request_fingerprint == replay.request_fingerprint
    assert recording.response_fingerprint == replay.response_fingerprint
    assert report.statistics.exact_replay_coverage == 1.0


def test_clear_margin_is_not_applicable_and_does_not_call_backend(tmp_path: Path) -> None:
    bindings = _bindings(tmp_path / "exact-replay.jsonl")
    report = BoundedPilotRunner(backends=bindings).run(
        _protocol(),
        report_id="clear-margin-report",
        generated_at=NOW,
        manual_interventions=_synthetic_measurements(),
        independent_outcome_review=_review(),
    )
    clear_result = next(
        result for result in report.case_results if result.case_id == "ambiguous-clear-margin"
    )

    assert clear_result.outcome is PilotOutcome.NOT_APPLICABLE
    assert clear_result.invoked is False
    assert bindings["clear"].calls == []
    assert report.statistics.successful_count == report.statistics.accepted_count


def test_schema_and_reference_gates_reject_without_counting_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITASTE_PILOT_TEST_KEY", "offline-placeholder")
    invalid_schema = _run(
        tmp_path / "schema",
        review_payload={"concerns": [], "summary": "invalid", "confidence": "high"},
        include_live=True,
    )
    schema_result = next(
        result for result in invalid_schema.case_results if result.case_id == "review-scripted"
    )
    assert schema_result.outcome is PilotOutcome.REJECTED
    assert schema_result.schema_valid is False
    assert invalid_schema.statistics.schema_invalid_count == 1
    assert invalid_schema.acceptance.overall_status is AcceptanceStatus.FAIL

    rejected_reference = _run(
        tmp_path / "reference",
        review_payload=_review_payload(claim_id="invented-claim"),
        include_live=True,
    )
    reference_result = next(
        result for result in rejected_reference.case_results if result.case_id == "review-scripted"
    )
    assert reference_result.outcome is PilotOutcome.REJECTED
    assert reference_result.schema_valid is True
    assert reference_result.unsupported_claim_reference_action_count == 1
    assert rejected_reference.statistics.successful_count == 4
    assert rejected_reference.acceptance.overall_status is AcceptanceStatus.FAIL


def test_gate_probe_acceptance_is_counted_as_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITASTE_PILOT_TEST_KEY", "offline-placeholder")
    protocol = _protocol()
    review_case = protocol.cases[1].model_copy(
        update={
            "gate_probe": True,
            "allowed_outcomes": (PilotOutcome.REJECTED,),
        }
    )
    protocol = protocol.model_copy(
        update={"cases": (protocol.cases[0], review_case, *protocol.cases[2:])}
    )
    report = BoundedPilotRunner(
        backends=_bindings(tmp_path / "exact-replay.jsonl", include_live=True)
    ).run(
        protocol,
        report_id="bypass-report",
        generated_at=NOW,
        manual_interventions=_synthetic_measurements(),
        independent_outcome_review=_review(),
    )

    assert report.statistics.gate_bypass_count == 1
    assert report.acceptance.overall_status is AcceptanceStatus.FAIL


def test_live_case_without_injected_backend_remains_planned(tmp_path: Path) -> None:
    report = _run(tmp_path)
    live = next(
        result
        for result in report.case_results
        if result.condition is PilotCondition.LIVE_STRUCTURED_NODE
    )
    assert live.outcome is PilotOutcome.PLANNED
    assert live.invoked is False
    assert live.backend_id is None
    assert report.statistics.case_count == 7
    assert report.statistics.planned_count == 1
    planned_metric = next(
        metric for metric in report.acceptance.metrics if metric.metric_id == "planned_case_count"
    )
    assert planned_metric.status is AcceptanceStatus.BLOCKED
    assert report.acceptance.overall_status is AcceptanceStatus.BLOCKED


def test_scripted_and_replay_conditions_cannot_masquerade(tmp_path: Path) -> None:
    bindings = _bindings(tmp_path / "exact-replay.jsonl")
    bindings["replay"] = _scripted(
        "ambiguous-paired-request",
        _ambiguous_payload(),
    )
    with pytest.raises(PilotConfigurationError, match="replay_node requires"):
        BoundedPilotRunner(backends=bindings).run(
            _protocol(),
            report_id="wrong-scripted-binding",
            generated_at=NOW,
        )

    live_bindings = _bindings(tmp_path / "live-masquerade.jsonl")
    live_bindings["live"] = live_bindings["interpretation"]
    with pytest.raises(PilotConfigurationError, match="live_structured_node requires"):
        BoundedPilotRunner(backends=live_bindings).run(
            _protocol(),
            report_id="scripted-cannot-be-live",
            generated_at=NOW,
        )


def test_budget_and_tool_telemetry_feed_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITASTE_PILOT_TEST_KEY", "offline-placeholder")
    bindings = _bindings(tmp_path / "exact-replay.jsonl", include_live=True)
    bindings["review"] = _scripted(
        "review-scripted",
        _review_payload(),
        usage=Usage(input_tokens=101, output_tokens=7, cost_usd=0.16),
        tool_calls=[ToolCallProposal(name="unbounded", arguments={})],
    )
    report = BoundedPilotRunner(backends=bindings).run(
        _protocol(),
        report_id="budget-report",
        generated_at=NOW,
        manual_interventions=_synthetic_measurements(),
        independent_outcome_review=_review(),
    )

    review = next(result for result in report.case_results if result.case_id == "review-scripted")
    assert review.outcome is PilotOutcome.REJECTED
    assert review.input_tokens == 101
    assert review.total_tokens == 108
    assert review.unbounded_tool_call_count == 1
    assert report.statistics.unbounded_tool_call_count == 1
    assert report.statistics.additional_api_cost_by_project_usd["scitaste-self-development"] > 0.15
    assert report.acceptance.overall_status is AcceptanceStatus.FAIL


def test_missing_independent_review_is_a_blocker(tmp_path: Path) -> None:
    report = BoundedPilotRunner(backends=_bindings(tmp_path / "exact-replay.jsonl")).run(
        _protocol(),
        report_id="no-review-report",
        generated_at=NOW,
        manual_interventions=_synthetic_measurements(),
    )
    metric = next(
        item for item in report.acceptance.metrics if item.metric_id == "independent_outcome_review"
    )
    assert metric.status is AcceptanceStatus.BLOCKED
    assert report.acceptance.overall_status is AcceptanceStatus.BLOCKED
    assert report.acceptance.eligible is False


def test_missing_external_manual_measurements_block_without_aborting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITASTE_PILOT_TEST_KEY", "offline-placeholder")
    measurements = _synthetic_measurements()
    measurements.pop("review-scripted")
    report = BoundedPilotRunner(
        backends=_bindings(tmp_path / "exact-replay.jsonl", include_live=True)
    ).run(
        _protocol(),
        report_id="missing-manual-evidence",
        generated_at=NOW,
        manual_interventions=measurements,
        independent_outcome_review=_review(),
    )

    assert report.verify_sha256()
    assert report.statistics.missing_manual_measurement_case_ids == ("review-scripted",)
    assert report.statistics.manual_intervention_baseline == 10
    assert report.statistics.manual_intervention_observed is None
    assert report.statistics.manual_intervention_reduction is None
    manual_metric = next(
        metric
        for metric in report.acceptance.metrics
        if metric.metric_id == "manual_intervention_reduction"
    )
    assert manual_metric.status is AcceptanceStatus.BLOCKED
    assert report.acceptance.overall_status is AcceptanceStatus.BLOCKED


def test_report_hash_is_stable_and_tampering_is_rejected(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")
    assert first.report_sha256 == second.report_sha256

    path = save_pilot_report(first, tmp_path / "report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["report_id"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="report_sha256"):
        load_pilot_report(path)


def test_report_write_refuses_overwrite_by_default(tmp_path: Path) -> None:
    report = _run(tmp_path / "run")
    target = save_pilot_report(report, tmp_path / "report.json")
    original = target.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        save_pilot_report(report, target)
    assert target.read_bytes() == original


def test_committed_protocol_without_external_evidence_is_honestly_blocked(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    protocol = load_pilot_protocol(
        root / "configs/model_nodes/bounded_self_development_pilot_v1.yaml"
    )
    assert protocol.self_dogfooding_only is True
    assert protocol.retrieval_eligible is False
    assert protocol.effectiveness_claim is False
    assert {case.node_type for case in protocol.cases} == set(PilotNodeType)
    assert {case.condition for case in protocol.cases} == set(PilotCondition)
    live = next(
        case for case in protocol.cases if case.condition is PilotCondition.LIVE_STRUCTURED_NODE
    )
    assert (live.expected_backend_id, live.expected_model_id) == (
        "zhipu-direct",
        "glm-5.3-flash",
    )
    assert {case.context.value.project_id for case in protocol.cases} == {
        "scitaste-self-development"
    }

    report = BoundedPilotRunner(
        backends=_committed_protocol_bindings(tmp_path / "committed-replay.jsonl")
    ).run(
        protocol,
        report_id="committed-protocol-without-external-evidence",
        generated_at=NOW,
    )
    assert report.statistics.planned_count == 1
    assert report.statistics.missing_manual_measurement_case_ids == (
        "manual-review-baseline",
        "review-scripted",
    )
    assert report.independent_outcome_review is None
    assert report.acceptance.overall_status is AcceptanceStatus.BLOCKED
    assert report.acceptance.eligible is False


def test_protocol_rejects_unknown_fields_and_input_type_coercion() -> None:
    payload = _protocol().model_dump(mode="json", exclude_computed_fields=True)
    payload["cases"][0]["unexpected_authority"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PilotProtocol.model_validate(payload)

    payload = _protocol().model_dump(mode="json", exclude_computed_fields=True)
    payload["cases"][0]["node_input"]["payload"]["review_text"] = 7
    with pytest.raises(ValidationError, match="invalid strict ReviewSemanticInput"):
        PilotProtocol.model_validate(payload)

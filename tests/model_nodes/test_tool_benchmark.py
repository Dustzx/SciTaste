from __future__ import annotations

import pytest

from scitaste.model_nodes import (
    ToolBenchmarkCondition,
    ToolBenchmarkTrial,
    evaluate_tool_intelligence_benchmark,
)


def _trial(
    scenario_id: str,
    condition: ToolBenchmarkCondition,
    *,
    resolved: bool,
    manual_steps: int,
    model_invocations: int = 1,
    tool_invocations: int = 1,
    runtime_ms: float = 1.0,
    **values: object,
) -> ToolBenchmarkTrial:
    return ToolBenchmarkTrial(
        scenario_id=scenario_id,
        condition=condition,
        evidence_test=f"tests/model_nodes::{scenario_id}::{condition.value}",
        hotspot_resolved=resolved,
        manual_controller_steps=manual_steps,
        model_invocations=model_invocations,
        tool_handler_invocations=tool_invocations,
        input_tokens=12 * model_invocations,
        output_tokens=8 * model_invocations,
        known_cost_usd=0.01 * model_invocations,
        model_latency_ms=5 * model_invocations,
        tool_latency_ms=1 * tool_invocations,
        runtime_ms=runtime_ms,
        **values,
    )


def test_paired_benchmark_reports_directional_v2_v3_improvements() -> None:
    v2 = ToolBenchmarkCondition.V2
    v3 = ToolBenchmarkCondition.V3
    trials = (
        _trial("normal", v2, resolved=True, manual_steps=3),
        _trial("normal", v3, resolved=True, manual_steps=1, runtime_ms=1.4),
        _trial(
            "restart",
            v2,
            resolved=True,
            manual_steps=3,
            tool_invocations=2,
            restart_duplicate_execution_count=1,
        ),
        _trial(
            "restart",
            v3,
            resolved=True,
            manual_steps=1,
            runtime_ms=1.4,
            restart_duplicate_execution_count=0,
        ),
        _trial(
            "crash-result",
            v2,
            resolved=True,
            manual_steps=4,
            tool_invocations=2,
            crash_recovery_success=False,
        ),
        _trial(
            "crash-result",
            v3,
            resolved=True,
            manual_steps=1,
            runtime_ms=1.4,
            crash_recovery_success=True,
        ),
        _trial(
            "ambiguous-custom",
            v2,
            resolved=False,
            manual_steps=4,
            tool_invocations=2,
            ambiguous_call_failed_closed=False,
        ),
        _trial(
            "ambiguous-custom",
            v3,
            resolved=False,
            manual_steps=2,
            runtime_ms=1.4,
            ambiguous_call_failed_closed=True,
        ),
        _trial(
            "concurrent-state",
            v2,
            resolved=False,
            manual_steps=3,
            stale_or_concurrent_result_accepted=False,
        ),
        _trial(
            "concurrent-state",
            v3,
            resolved=False,
            manual_steps=1,
            runtime_ms=1.4,
            stale_or_concurrent_result_accepted=False,
        ),
        _trial(
            "locator-symlink",
            v2,
            resolved=False,
            manual_steps=3,
            locator_attack_rejected=False,
        ),
        _trial(
            "locator-symlink",
            v3,
            resolved=False,
            manual_steps=1,
            model_invocations=0,
            tool_invocations=0,
            runtime_ms=1.4,
            locator_attack_rejected=True,
        ),
    )

    report = evaluate_tool_intelligence_benchmark(trials)

    assert report.v2.successful_hotspot_resolution_rate == 0.5
    assert report.v3.successful_hotspot_resolution_rate == 0.5
    assert report.delta.hotspot_resolution_rate_gain == 0
    assert report.delta.restart_duplicate_execution_rate_reduction == 1
    assert report.delta.crash_recovery_success_rate_gain == 1
    assert report.delta.ambiguous_call_fail_closed_rate_gain == 1
    assert report.delta.stale_result_acceptance_rate_reduction == 0
    assert report.delta.locator_attack_rejection_rate_gain == 1
    assert report.v2.manual_controller_steps_per_resolved_hotspot == pytest.approx(10 / 3)
    assert report.v3.manual_controller_steps_per_resolved_hotspot == 1
    assert report.delta.manual_controller_step_reduction_rate == pytest.approx(0.7)
    assert report.delta.tool_invocation_reduction_rate == pytest.approx(4 / 9)
    assert report.delta.model_invocation_reduction_rate == pytest.approx(1 / 6)
    assert report.delta.token_reduction_rate == pytest.approx(1 / 6)
    assert report.delta.known_cost_reduction_rate == pytest.approx(1 / 6)
    assert report.delta.mean_runtime_overhead_ms == pytest.approx(0.4)
    assert report.scientific_effectiveness_claim is False
    assert len(report.fingerprint) == 64


def test_benchmark_rejects_unpaired_or_duplicate_condition_trials() -> None:
    trial = _trial("normal", ToolBenchmarkCondition.V2, resolved=True, manual_steps=3)
    with pytest.raises(ValueError, match="exactly paired"):
        evaluate_tool_intelligence_benchmark((trial,))

    candidate = _trial("normal", ToolBenchmarkCondition.V3, resolved=True, manual_steps=1)
    with pytest.raises(ValueError, match="duplicate condition"):
        evaluate_tool_intelligence_benchmark((trial, trial, candidate))

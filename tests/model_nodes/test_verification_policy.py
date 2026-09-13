from __future__ import annotations

import pytest

from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    VerificationAdvisory,
    VerificationDecisionInput,
    VerificationRoute,
    apply_verification_advisory,
    decide_verification_route,
)


def _action(**updates: object) -> VerificationDecisionInput:
    values: dict[str, object] = {
        "action_id": "local-reversible-edit",
        "reversibility": "reversible",
        "effects": ["read_only_local"],
        "evidence_state": "current",
        "semantic_uncertainty": "low",
        "failure_probability": 0.05,
        "failure_impact_units": 5.0,
        "targeted_check_cost_units": 1.0,
        "targeted_detection_probability": 0.8,
        "full_preflight_cost_units": 5.0,
        "full_preflight_detection_probability": 0.95,
    }
    values.update(updates)
    return VerificationDecisionInput.model_validate(values)


def test_low_cost_reversible_action_skips_wasteful_prechecks() -> None:
    decision = decide_verification_route(_action())

    assert decision.route is VerificationRoute.DIRECT_PATH
    assert decision.owner_approval_required is False
    assert decision.execution_authority == "none"
    assert decision.reason_codes == ("verification-cost-exceeds-avoidable-loss",)


def test_positive_expected_value_selects_only_the_targeted_check() -> None:
    decision = decide_verification_route(
        _action(failure_probability=0.4, failure_impact_units=20.0)
    )

    assert decision.route is VerificationRoute.TARGETED_CHECK
    assert decision.targeted_net_gain_units > 0
    assert decision.full_preflight_net_gain_units < decision.targeted_net_gain_units


@pytest.mark.parametrize(
    ("updates", "route"),
    [
        (
            {"reversibility": "irreversible", "effects": ["external_mutation"]},
            VerificationRoute.OWNER_APPROVAL,
        ),
        (
            {"effects": [ActionEffect.UNTRUSTED_CODE]},
            VerificationRoute.FULL_PREFLIGHT,
        ),
    ],
)
def test_hard_safety_boundaries_cannot_be_optimized_away(
    updates: dict[str, object],
    route: VerificationRoute,
) -> None:
    decision = decide_verification_route(_action(**updates))

    assert decision.route is route
    assert decision.owner_approval_required is True
    assert decision.model_advisory_eligible is False


def test_model_can_resolve_only_a_declared_semantic_gray_zone() -> None:
    action = _action(
        semantic_uncertainty="high",
        failure_probability=0.25,
        failure_impact_units=10.0,
        targeted_check_cost_units=1.5,
        targeted_detection_probability=0.8,
    )
    decision = decide_verification_route(action)
    assert decision.model_advisory_eligible is True
    advisory = VerificationAdvisory(
        input_fingerprint=action.fingerprint,
        recommended_route="direct_path",
        rationale="The current content hash already resolves the only semantic uncertainty.",
    )

    resolved = apply_verification_advisory(decision, advisory)

    assert resolved.route is VerificationRoute.DIRECT_PATH
    assert resolved.decision_source == "model_assisted"
    assert resolved.execution_authority == "none"

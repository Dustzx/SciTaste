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


def test_small_incremental_gain_does_not_expand_a_sufficient_targeted_check() -> None:
    decision = decide_verification_route(
        _action(
            failure_probability=0.5,
            failure_impact_units=20.0,
            targeted_check_cost_units=2.0,
            targeted_detection_probability=0.7,
            full_preflight_cost_units=3.4,
            full_preflight_detection_probability=0.85,
        )
    )

    assert decision.targeted_net_gain_units >= 1
    assert decision.full_preflight_net_gain_units > decision.targeted_net_gain_units
    assert decision.route is VerificationRoute.TARGETED_CHECK
    assert decision.reason_codes == ("targeted-check-is-cheapest-sufficient-verification",)


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
        (
            {"effects": [ActionEffect.DECLARED_OWNER_BOUNDARY]},
            VerificationRoute.OWNER_APPROVAL,
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


def test_model_cannot_add_a_negative_value_check_in_a_gray_zone() -> None:
    action = _action(
        semantic_uncertainty="high",
        failure_probability=0.25,
        failure_impact_units=10.0,
        targeted_check_cost_units=1.5,
        targeted_detection_probability=0.8,
        full_preflight_cost_units=5.0,
        full_preflight_detection_probability=0.95,
    )
    decision = decide_verification_route(action)
    advisory = VerificationAdvisory(
        input_fingerprint=action.fingerprint,
        recommended_route="full_preflight",
        rationale="Request a broad check despite its negative expected value.",
    )

    with pytest.raises(ValueError, match="negative-value verification"):
        apply_verification_advisory(decision, advisory)


def test_model_cannot_expand_to_a_lower_value_full_preflight() -> None:
    action = _action(
        effects=(ActionEffect.READ_ONLY_LOCAL,),
        semantic_uncertainty="high",
        failure_probability=0.2,
        failure_impact_units=20.0,
        targeted_check_cost_units=1.0,
        targeted_detection_probability=0.8,
        full_preflight_cost_units=3.5,
        full_preflight_detection_probability=0.95,
    )
    decision = decide_verification_route(action)
    assert decision.route is VerificationRoute.TARGETED_CHECK
    assert decision.model_advisory_eligible is True
    advisory = VerificationAdvisory(
        input_fingerprint=action.fingerprint,
        recommended_route="full_preflight",
        rationale="Request a broader check despite its lower declared net value.",
    )

    with pytest.raises(ValueError, match="lower-value verification step"):
        apply_verification_advisory(decision, advisory)


def test_model_may_choose_only_the_best_positive_check_or_direct_path() -> None:
    action = _action(
        effects=(ActionEffect.READ_ONLY_LOCAL,),
        semantic_uncertainty="high",
        failure_probability=0.2,
        failure_impact_units=20.0,
        targeted_check_cost_units=2.3,
        targeted_detection_probability=0.75,
        full_preflight_cost_units=2.5,
        full_preflight_detection_probability=0.95,
    )
    decision = decide_verification_route(action)
    assert decision.model_advisory_eligible is True
    assert decision.full_preflight_net_gain_units > decision.targeted_net_gain_units

    admitted = apply_verification_advisory(
        decision,
        VerificationAdvisory(
            input_fingerprint=action.fingerprint,
            recommended_route="full_preflight",
            rationale="The deeper check has the highest positive declared net value.",
        ),
    )
    assert admitted.route is VerificationRoute.FULL_PREFLIGHT

    skipped = apply_verification_advisory(
        decision,
        VerificationAdvisory(
            input_fingerprint=action.fingerprint,
            recommended_route="direct_path",
            rationale="The semantic concern does not apply to this exact action.",
        ),
    )
    assert skipped.route is VerificationRoute.DIRECT_PATH

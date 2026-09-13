from __future__ import annotations

from pathlib import Path

import pytest

from scitaste.evaluation import (
    EffectiveProgramActionRoute,
    ExperimentProgramControl,
    compile_effective_experiment_program,
    inspect_experiment_decision_dossier,
    load_experiment_decision_dossier,
    route_effective_program_action,
)

_DOSSIER = Path("configs/evaluation/campaigns/iclr2027_self_development_v1.yaml")


def _report():
    dossier = load_experiment_decision_dossier(_DOSSIER).dossier
    return inspect_experiment_decision_dossier(dossier, evidence_root=".")


def _effective(report, stage_id: str | None = None):
    control = None
    if stage_id is not None:
        order = (stage_id, *(item for item in report.next_stage_ids if item != stage_id))
        control = ExperimentProgramControl.create(
            project_id="scitaste-self-development",
            source_publication_id="program-action-test",
            source_publication_sha256="a" * 64,
            source_dossier_id=report.dossier_id,
            source_dossier_sha256=report.dossier_sha256,
            change_kind="reprioritize_next_gates",
            target_stage_id=stage_id,
            proposed_next_stage_order=order,
            summary="Use this eligible gate as the current project decision.",
            rationale="The exact user-published order remains non-executing.",
        )
    return compile_effective_experiment_program(
        report,
        project_id="scitaste-self-development",
        control=control,
    )


def test_current_gpu_gate_retains_owner_boundary_without_execution() -> None:
    report = _report()

    route = route_effective_program_action(report, _effective(report))

    assert route.stage_id == "qualify-scientific-taste-source-pilot"
    assert route.verification.route == "owner_approval"
    assert route.verification.owner_approval_required is True
    assert route.verification.reason_codes == (
        "declared-owner-boundary-requires-owner",
        "external-authority-requires-owner",
    )
    assert route.next_action_kind == "request_owner_decision"
    assert route.verification.action_id == "route-qualify-scientific-taste-source-pilot"
    assert route.verification.input_fingerprint == route.verification_input.fingerprint
    assert route.authorizes_external_action is False
    assert route.authorizes_execution is False
    assert route.no_external_action_performed is True


def test_costly_check_is_used_only_when_expected_gain_is_positive() -> None:
    report = _report()

    targeted = route_effective_program_action(
        report,
        _effective(report, "qualify-held-out-task-bytes"),
    )
    direct = route_effective_program_action(
        report,
        _effective(report, "attest-native-condition-implementations"),
    )

    assert targeted.verification.route == "targeted_check"
    assert targeted.verification.targeted_net_gain_units > 0
    assert targeted.next_action_kind == "run_targeted_check"
    assert direct.verification.route == "direct_path"
    assert direct.verification.reason_codes == (
        "verification-cost-exceeds-avoidable-loss",
        "semantic-gray-zone-allows-model-advice",
    )
    assert direct.verification.model_advisory_eligible is True
    assert direct.next_action_kind == "resolve_registered_blockers"


def test_action_route_is_bound_to_the_effective_program() -> None:
    report = _report()
    effective = _effective(report)

    route = route_effective_program_action(report, effective)

    assert route.project_id == effective.project_id
    assert route.dossier_report_sha256 == effective.dossier_report_sha256
    assert route.effective_program_sha256 == effective.program_sha256
    assert route.route_sha256
    assert EffectiveProgramActionRoute.model_validate_json(route.model_dump_json()) == route

    changed = {
        name: getattr(route, name)
        for name in EffectiveProgramActionRoute.model_fields
        if name != "route_sha256"
    }
    changed["verification_input"] = route.verification_input.model_copy(
        update={"failure_probability": 0.01}
    )
    with pytest.raises(ValueError, match="verification decision belongs"):
        EffectiveProgramActionRoute.create(**changed)

from __future__ import annotations

from pathlib import Path

import pytest

from scitaste.evaluation import (
    ExperimentProgramControl,
    compile_effective_experiment_program,
    inspect_experiment_decision_dossier,
    load_experiment_decision_dossier,
)

_DOSSIER = Path("configs/evaluation/campaigns/iclr2027_self_development_v1.yaml")


def _report():
    dossier = load_experiment_decision_dossier(_DOSSIER).dossier
    return inspect_experiment_decision_dossier(dossier, evidence_root=".")


def _control(report, *, change_kind: str, **updates: object) -> ExperimentProgramControl:
    values: dict[str, object] = {
        "project_id": "scitaste-self-development",
        "source_publication_id": "program-directive-test",
        "source_publication_sha256": "a" * 64,
        "source_dossier_id": report.dossier_id,
        "source_dossier_sha256": report.dossier_sha256,
        "change_kind": change_kind,
        "target_stage_id": report.next_stage_ids[0],
        "summary": "Use the published project planning preference.",
        "rationale": "The user reviewed and published this exact non-executing plan.",
        "required_evidence": ("Retain the bound dossier evidence.",),
    }
    values.update(updates)
    return ExperimentProgramControl.create(**values)


def test_published_reprioritization_changes_core_next_stage_without_execution() -> None:
    report = _report()
    order = (report.next_stage_ids[1], report.next_stage_ids[0], *report.next_stage_ids[2:])
    control = _control(
        report,
        change_kind="reprioritize_next_gates",
        target_stage_id=order[0],
        proposed_next_stage_order=order,
    )

    program = compile_effective_experiment_program(
        report,
        project_id=control.project_id,
        control=control,
    )

    assert program.planning_authority == "user_published_control"
    assert program.control_effect == "stage_order"
    assert program.baseline_next_stage_ids == report.next_stage_ids
    assert program.effective_next_stage_ids == order
    assert program.effective_current_stage_id == order[0]
    assert program.control_sha256 == control.control_sha256
    assert program.controller_consumed is True
    assert program.verification_route == "direct_path"
    assert program.verification_reason_codes == (
        "verification-cost-exceeds-avoidable-loss",
    )
    assert program.authorizes_external_action is False
    assert program.authorizes_execution is False
    assert program.execution_authority == "none"


def test_decision_guidance_is_consumed_without_rewriting_dossier_order() -> None:
    report = _report()
    control = _control(report, change_kind="clarify_stage_decision")

    program = compile_effective_experiment_program(
        report,
        project_id=control.project_id,
        control=control,
    )

    assert program.control_effect == "decision_guidance"
    assert program.effective_next_stage_ids == report.next_stage_ids
    assert program.published_guidance == control.summary
    assert program.guidance_rationale == control.rationale
    assert program.required_evidence == control.required_evidence
    assert program.dossier_sha256 == report.dossier_sha256
    assert program.authorizes_execution is False


def test_control_cannot_cross_project_or_dossier_identity() -> None:
    report = _report()
    control = _control(report, change_kind="add_risk_note")

    with pytest.raises(ValueError, match="another project"):
        compile_effective_experiment_program(
            report,
            project_id="another-project",
            control=control,
        )
    changed = ExperimentProgramControl.create(
        **{
            **control.model_dump(exclude={"control_sha256"}),
            "source_dossier_sha256": "f" * 64,
        }
    )
    with pytest.raises(ValueError, match="another dossier"):
        compile_effective_experiment_program(
            report,
            project_id=control.project_id,
            control=changed,
        )


def test_reprioritization_cannot_target_an_unrelated_incomplete_stage() -> None:
    report = _report()
    unrelated_stage = next(
        item.stage_id
        for item in report.stages
        if item.state != "complete" and item.stage_id not in report.next_stage_ids
    )
    control = _control(
        report,
        change_kind="reprioritize_next_gates",
        target_stage_id=unrelated_stage,
        proposed_next_stage_order=report.next_stage_ids,
    )

    with pytest.raises(ValueError, match="must target a current next gate"):
        compile_effective_experiment_program(
            report,
            project_id=control.project_id,
            control=control,
        )

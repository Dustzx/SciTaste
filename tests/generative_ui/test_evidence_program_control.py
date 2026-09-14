from __future__ import annotations

from pathlib import Path

from scitaste.evaluation import (
    ExperimentProgramControl,
    compile_effective_experiment_program,
    inspect_experiment_decision_dossier,
    load_experiment_decision_dossier,
    route_program_stage_action,
)
from scitaste.generative_ui.evidence_program import project_iclr_evidence_program
from scitaste.model_nodes import VerificationAdvisory
from scitaste.project import ProjectRun


def test_effective_core_order_controls_the_primary_generation_as_content_phase() -> None:
    repository = Path(__file__).resolve().parents[2]
    dossier = load_experiment_decision_dossier(
        repository / "configs/evaluation/campaigns/iclr2027_self_development_v1.yaml"
    ).dossier
    report = inspect_experiment_decision_dossier(dossier, evidence_root=repository)
    order = (report.next_stage_ids[1], report.next_stage_ids[0], *report.next_stage_ids[2:])
    control = ExperimentProgramControl.create(
        project_id="scitaste-self-development",
        source_publication_id="program-directive-ui-test",
        source_publication_sha256="a" * 64,
        source_dossier_id=report.dossier_id,
        source_dossier_sha256=report.dossier_sha256,
        change_kind="reprioritize_next_gates",
        target_stage_id=order[0],
        proposed_next_stage_order=order,
        summary="Prioritize the qualified task-byte gate.",
        rationale="The user published this exact order after reviewing the evidence plan.",
    )
    effective = compile_effective_experiment_program(
        report,
        project_id=control.project_id,
        control=control,
    )

    projected = project_iclr_evidence_program(
        report,
        effective_program=effective,
        run=ProjectRun(
            run_id="program-run",
            provider="scitaste-native",
            model="deterministic",
            condition="test",
            seed=0,
            status="complete",
            evidence_scope="test-only",
        ),
        project_ref_id="project-record",
        run_ref_id="program-run-record",
        artifact_ref_id="program-artifact",
    )

    assert projected.planning_authority == "user_published_control"
    assert projected.control_effect == "stage_order"
    assert projected.source_publication_id == control.source_publication_id
    assert projected.source_publication_sha256 == control.source_publication_sha256
    assert projected.current_stage_id == "qualify-held-out-task-bytes"
    assert projected.current_phase_id == "method-readiness"
    assert projected.effective_next_stage_ids == order
    assert projected.effective_program_sha256 == effective.program_sha256
    assert projected.gate_action_route.verification_route == "targeted_check"
    assert projected.gate_action_route.next_action_kind == "run_targeted_check"
    assert projected.gate_action_route.authorizes_execution is False
    assert projected.no_external_action_performed is True


def test_lifecycle_program_uses_the_same_seven_user_facing_phases() -> None:
    repository = Path(__file__).resolve().parents[2]
    dossier = load_experiment_decision_dossier(
        repository
        / "configs/evaluation/campaigns/iclr2027_self_development_lifecycle_v2.yaml"
    ).dossier
    report = inspect_experiment_decision_dossier(dossier, evidence_root=repository)
    effective = compile_effective_experiment_program(
        report,
        project_id="scitaste-self-development",
    )

    projected = project_iclr_evidence_program(
        report,
        effective_program=effective,
        run=ProjectRun(
            run_id="lifecycle-program-run",
            provider="scitaste-native",
            model="deterministic",
            condition="test",
            seed=0,
            status="complete",
            evidence_scope="test-only",
        ),
        project_ref_id="project-record",
        run_ref_id="program-run-record",
        artifact_ref_id="program-artifact",
    )

    assert projected.current_stage_id == "admit-natural-lifecycle-episodes"
    assert projected.current_phase_id == "taste-instrument"
    assert tuple(item.phase_id for item in projected.phases) == (
        "research-basis",
        "taste-instrument",
        "method-readiness",
        "independent-review",
        "prepilot-evidence",
        "formal-evidence",
        "paper-review-loop",
    )
    assert projected.exact_cell_count == 0
    assert projected.no_external_action_performed is True


def test_published_gray_zone_advice_is_visible_in_the_core_route() -> None:
    repository = Path(__file__).resolve().parents[2]
    dossier = load_experiment_decision_dossier(
        repository / "configs/evaluation/campaigns/iclr2027_self_development_v1.yaml"
    ).dossier
    report = inspect_experiment_decision_dossier(dossier, evidence_root=repository)
    stage_id = "attest-native-condition-implementations"
    order = (stage_id, *(item for item in report.next_stage_ids if item != stage_id))
    control = ExperimentProgramControl.create(
        project_id="scitaste-self-development",
        source_publication_id="program-advisory-ui-test",
        source_publication_sha256="b" * 64,
        source_dossier_id=report.dossier_id,
        source_dossier_sha256=report.dossier_sha256,
        change_kind="reprioritize_next_gates",
        target_stage_id=stage_id,
        proposed_next_stage_order=order,
        summary="Continue directly through the already bounded implementation attestation.",
        rationale="The feedback model and project controller share this exact route identity.",
    )
    effective = compile_effective_experiment_program(
        report,
        project_id=control.project_id,
        control=control,
    )
    baseline = route_program_stage_action(report, effective, stage_id=stage_id)
    advisory = VerificationAdvisory(
        input_fingerprint=baseline.verification_input.fingerprint,
        recommended_route="direct_path",
        rationale="Avoid a duplicate preflight around reversible local attestation work.",
    )

    projected = project_iclr_evidence_program(
        report,
        effective_program=effective,
        run=ProjectRun(
            run_id="program-advisory-run",
            provider="scitaste-native",
            model="deterministic",
            condition="test",
            seed=0,
            status="complete",
            evidence_scope="test-only",
        ),
        project_ref_id="project-record",
        run_ref_id="program-run-record",
        artifact_ref_id="program-artifact",
        verification_advisory=advisory,
        verification_advisory_stage_id=stage_id,
    )

    assert projected.gate_action_route.stage_id == stage_id
    assert projected.gate_action_route.decision_source == "model_assisted"
    assert projected.gate_action_route.advisory_fingerprint == advisory.fingerprint
    assert projected.gate_action_route.verification_route == "direct_path"
    assert projected.gate_action_route.authorizes_execution is False

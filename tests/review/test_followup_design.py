from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import load_evidence_program
from scitaste.review import (
    ProjectReviewFollowupActivation,
    ProjectReviewFollowupDesign,
    ProjectReviewIterationPlan,
    ReviewIterationStep,
    ReviewIterationWorkKind,
    compile_review_followup_activation,
    compile_review_followup_design,
    load_review_followup_activation_manifest,
    load_review_followup_mapping,
)

_ROOT = Path(__file__).resolve().parents[2]
_PROGRAM = _ROOT / "configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml"
_MAPPING = _ROOT / "configs/evaluation/review_followups/iclr2027_v6_internal_r2.yaml"
_ACTIVATION = _ROOT / "configs/evaluation/activation/iclr2027_review_followup_v3.yaml"
_SHA = "a" * 64
_COMMIT = "b" * 40
_PROJECT = "scitaste-self-development"
_ITERATION_RUN = "2026-09-12__scitaste-native__review-iteration-plan-v1__seed-00"
_CONCERNS = (
    "missing-effectiveness-evidence",
    "missing-external-baseline",
    "overclaim-title-improvement",
    "single-task-generalization",
)


def _step(
    step_id: str,
    kind: ReviewIterationWorkKind,
    *,
    concern_id: str | None = None,
    depends_on: tuple[str, ...] = (),
    approval: bool = False,
) -> ReviewIterationStep:
    return ReviewIterationStep(
        step_id=step_id,
        kind=kind,
        stage=(
            "writing"
            if kind
            in {
                ReviewIterationWorkKind.CLAIM_REVISION,
                ReviewIterationWorkKind.PAPER_REVISION,
            }
            else "review"
            if kind
            in {
                ReviewIterationWorkKind.AUTHOR_RESPONSE,
                ReviewIterationWorkKind.REVIEWER_VERIFICATION,
            }
            else "evidence"
        ),
        objective=f"Complete {step_id}.",
        concern_ids=(() if concern_id is None else (concern_id,)),
        obligation_ids=(() if concern_id is None else (f"obligation-{concern_id}",)),
        depends_on=depends_on,
        completion_artifacts=(f"artifact-{step_id}",),
        project_interface="project.paper.review.test",
        execution_class=(
            "approval_gated_external_or_compute"
            if approval
            else "independent_human_review"
            if kind is ReviewIterationWorkKind.REVIEWER_VERIFICATION
            else "deterministic_no_run"
        ),
        requires_owner_approval=approval,
    )


def _iteration() -> ProjectReviewIterationPlan:
    experiment_concerns = (
        "missing-effectiveness-evidence",
        "missing-external-baseline",
        "single-task-generalization",
    )
    steps: list[ReviewIterationStep] = []
    terminals: list[str] = []
    for concern_id in experiment_concerns[:2]:
        design_id = f"design-experiment-{concern_id}"
        execute_id = f"execute-experiment-{concern_id}"
        steps.extend(
            (
                _step(design_id, ReviewIterationWorkKind.EXPERIMENT_DESIGN, concern_id=concern_id),
                _step(
                    execute_id,
                    ReviewIterationWorkKind.EXPERIMENT_EXECUTION,
                    concern_id=concern_id,
                    depends_on=(design_id,),
                    approval=True,
                ),
            )
        )
        terminals.append(execute_id)
    claim_id = "revise-text-overclaim-title-improvement"
    steps.append(
        _step(
            claim_id,
            ReviewIterationWorkKind.CLAIM_REVISION,
            concern_id="overclaim-title-improvement",
        )
    )
    terminals.append(claim_id)
    last_concern = experiment_concerns[-1]
    last_design = f"design-experiment-{last_concern}"
    last_execute = f"execute-experiment-{last_concern}"
    steps.extend(
        (
            _step(
                last_design,
                ReviewIterationWorkKind.EXPERIMENT_DESIGN,
                concern_id=last_concern,
            ),
            _step(
                last_execute,
                ReviewIterationWorkKind.EXPERIMENT_EXECUTION,
                concern_id=last_concern,
                depends_on=(last_design,),
                approval=True,
            ),
        )
    )
    terminals.append(last_execute)
    steps.extend(
        (
            _step(
                "compile-review-revision-input",
                ReviewIterationWorkKind.REVISION_INPUT,
                depends_on=tuple(terminals),
            ).model_copy(
                update={
                    "concern_ids": _CONCERNS,
                    "obligation_ids": tuple(f"obligation-{item}" for item in _CONCERNS),
                }
            ),
            _step(
                "build-reviewed-paper-revision",
                ReviewIterationWorkKind.PAPER_REVISION,
                depends_on=("compile-review-revision-input",),
            ).model_copy(
                update={
                    "concern_ids": _CONCERNS,
                    "obligation_ids": tuple(f"obligation-{item}" for item in _CONCERNS),
                }
            ),
            _step(
                "submit-review-response",
                ReviewIterationWorkKind.AUTHOR_RESPONSE,
                depends_on=("build-reviewed-paper-revision",),
            ).model_copy(
                update={
                    "concern_ids": _CONCERNS,
                    "obligation_ids": tuple(f"obligation-{item}" for item in _CONCERNS),
                }
            ),
            _step(
                "verify-review-response",
                ReviewIterationWorkKind.REVIEWER_VERIFICATION,
                depends_on=("submit-review-response",),
            ).model_copy(
                update={
                    "concern_ids": _CONCERNS,
                    "obligation_ids": tuple(f"obligation-{item}" for item in _CONCERNS),
                }
            ),
        )
    )
    return ProjectReviewIterationPlan.create(
        project_id=_PROJECT,
        run_id=_ITERATION_RUN,
        review_id="iclr2027-v6-internal-r2",
        source_commit=_COMMIT,
        review_round_sha256=_SHA,
        routing_run_ids=("routing-v1",),
        routing_bundle_sha256={"routing-v1": _SHA},
        report_sha256={"report-v1": _SHA},
        routed_state_sha256=_SHA,
        concern_ids=_CONCERNS,
        obligation_ids=tuple(f"obligation-{item}" for item in _CONCERNS),
        steps=tuple(steps),
        next_step_ids=tuple(item.step_id for item in steps if not item.depends_on),
        owner_approval_step_ids=tuple(
            item.step_id for item in steps if item.requires_owner_approval
        ),
        execution_approval_required=True,
    )


def test_review_followup_design_binds_exact_studies_without_duplicate_execution() -> None:
    design = compile_review_followup_design(
        project_id=_PROJECT,
        run_id="followup-design-v1",
        source_commit=_COMMIT,
        review_iteration=_iteration(),
        mapping=load_review_followup_mapping(_MAPPING),
        evidence_program=load_evidence_program(_PROGRAM),
    )

    assert [item.hypothesis.value for item in design.studies] == [
        "H0_reference_quality",
        "H1_taste_abstraction",
        "H2_taste_specificity",
        "H2b_taste_selection",
        "H3_native_effect",
        "E1_ecological_comparison",
        "D1_integrity_diagnostic",
    ]
    assert len(design.studies) == 7
    assert design.studies[0].reused_by_concern_ids == (
        "missing-effectiveness-evidence",
        "overclaim-title-improvement",
        "single-task-generalization",
    )
    assert [item.system_id for item in design.system_requirements] == [
        "agent-laboratory",
        "ai-researcher",
        "deep-scientist",
    ]
    assert design.excluded_process_study_ids == ("longitudinal-self-development-case",)
    assert design.primary_model_id is None
    assert design.fixed_formal_sample_size is None
    assert design.fixed_repetitions is None
    assert design.title_claim_status == "submission_blocked_pending_title_critical_evidence"
    assert design.authorizes_execution is False
    assert design.no_execution_performed is True


def test_review_followup_design_rejects_scientifically_incomplete_mapping(tmp_path: Path) -> None:
    raw = _MAPPING.read_text(encoding="utf-8")
    invalid = raw.replace("      - native-objective-progress\n", "", 1)
    path = tmp_path / "mapping.yaml"
    path.write_text(invalid, encoding="utf-8")

    with pytest.raises(ValueError, match="exact registered studies"):
        compile_review_followup_design(
            project_id=_PROJECT,
            run_id="followup-design-v1",
            source_commit=_COMMIT,
            review_iteration=_iteration(),
            mapping=load_review_followup_mapping(path),
            evidence_program=load_evidence_program(_PROGRAM),
        )


def test_review_followup_design_is_self_hashed() -> None:
    design = compile_review_followup_design(
        project_id=_PROJECT,
        run_id="followup-design-v1",
        source_commit=_COMMIT,
        review_iteration=_iteration(),
        mapping=load_review_followup_mapping(_MAPPING),
        evidence_program=load_evidence_program(_PROGRAM),
    )
    payload = design.model_dump(mode="json")
    payload["title_claim_status"] = "submission_blocked_pending_title_critical_evidence"
    payload["paper_title"] = "A rewritten title"

    with pytest.raises(ValidationError, match="design hash mismatch"):
        ProjectReviewFollowupDesign.model_validate(payload)


def test_review_activation_closes_seven_studies_without_selecting_available_resources() -> None:
    design = compile_review_followup_design(
        project_id=_PROJECT,
        run_id="followup-design-v1",
        source_commit=_COMMIT,
        review_iteration=_iteration(),
        mapping=load_review_followup_mapping(_MAPPING),
        evidence_program=load_evidence_program(_PROGRAM),
    )

    activation = compile_review_followup_activation(
        design=design,
        manifest_inspection=load_review_followup_activation_manifest(_ACTIVATION),
        workspace_root=_ROOT,
        run_id="followup-activation-v1",
        source_commit=_COMMIT,
    )

    assert [item.hypothesis for item in activation.studies] == [
        "H0_reference_quality",
        "H1_taste_abstraction",
        "H2_taste_specificity",
        "H2b_taste_selection",
        "H3_native_effect",
        "E1_ecological_comparison",
        "D1_integrity_diagnostic",
    ]
    assert activation.next_owner_decision.source_ids == (
        "innovatorbench-objective-tasks",
        "expbench-integrity",
    )
    assert activation.next_owner_decision.requested_item_count == 21
    assert activation.next_owner_decision.maximum_requested_bytes == 8 * 1024 * 1024
    assert activation.primary_model_id is None
    assert activation.ready_for_model_conformance_pilot is False
    assert activation.ready_for_adapter_preflight is False
    assert activation.ready_for_human_recruitment is False
    assert activation.ready_for_experiment is False
    assert all(not item.selected for item in activation.primary_model_candidates)
    assert all(not item.paper_backbone_selected for item in activation.diagnostic_checkpoints)
    assert activation.schema_version == "1.1"
    assert activation.model_identity_protocol_id == "iclr2027-api-identity-v1"
    assert activation.ready_for_model_pilot_proposal is False
    candidates = {item.resource_id: item for item in activation.primary_model_candidates}
    assert candidates["deepseek-v4-flash"].declared_revision == "DeepSeek-V4-Flash-0731"
    assert candidates["deepseek-v4-flash"].pilot_proposal_ready is True
    assert candidates["deepseek-v4-flash"].blocker_codes == (
        "authenticated_identity_attestation_not_observed",
        "formal_identity_window_not_open",
    )
    assert candidates["zhipu-glm53-flash"].pilot_proposal_ready is False
    assert candidates["zhipu-glm53-flash"].blocker_codes == (
        "authenticated_identity_attestation_not_observed",
        "pricing_ceiling_not_verified",
        "formal_identity_window_not_open",
    )
    assert activation.historical_campaign_superseded_for_launch is True
    assert activation.authorizes_download is False
    assert activation.authorizes_api_calls is False
    assert activation.authorizes_gpu_work is False
    assert activation.authorizes_human_recruitment is False
    assert activation.authorizes_execution is False
    assert activation.no_external_action_performed is True


def test_review_activation_rejects_design_and_resource_drift() -> None:
    design = compile_review_followup_design(
        project_id=_PROJECT,
        run_id="followup-design-v1",
        source_commit=_COMMIT,
        review_iteration=_iteration(),
        mapping=load_review_followup_mapping(_MAPPING),
        evidence_program=load_evidence_program(_PROGRAM),
    )
    manifest = load_review_followup_activation_manifest(_ACTIVATION)

    with pytest.raises(ValueError, match="evidence program differs"):
        compile_review_followup_activation(
            design=design.model_copy(update={"evidence_program_sha256": "0" * 64}),
            manifest_inspection=manifest,
            workspace_root=_ROOT,
            run_id="followup-activation-v1",
            source_commit=_COMMIT,
        )

    wrong_candidates = manifest.manifest.model_copy(
        update={
            "primary_api_candidate_ids": (
                "qwen3-vl-2b-local-47f9c0e0",
                "zhipu-glm53-flash",
            )
        }
    )
    with pytest.raises(ValueError, match="API identity candidates differ"):
        compile_review_followup_activation(
            design=design,
            manifest_inspection=manifest.model_copy(update={"manifest": wrong_candidates}),
            workspace_root=_ROOT,
            run_id="followup-activation-v1",
            source_commit=_COMMIT,
        )


def test_review_activation_is_self_hashed() -> None:
    design = compile_review_followup_design(
        project_id=_PROJECT,
        run_id="followup-design-v1",
        source_commit=_COMMIT,
        review_iteration=_iteration(),
        mapping=load_review_followup_mapping(_MAPPING),
        evidence_program=load_evidence_program(_PROGRAM),
    )
    activation = compile_review_followup_activation(
        design=design,
        manifest_inspection=load_review_followup_activation_manifest(_ACTIVATION),
        workspace_root=_ROOT,
        run_id="followup-activation-v1",
        source_commit=_COMMIT,
    )
    payload = activation.model_dump(mode="json")
    payload["paper_title"] = "A drifted activation title"

    with pytest.raises(ValidationError, match="review activation hash mismatch"):
        ProjectReviewFollowupActivation.model_validate(payload)

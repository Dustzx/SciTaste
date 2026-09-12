from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import load_evidence_program
from scitaste.review import (
    ProjectReviewFollowupDesign,
    ProjectReviewIterationPlan,
    ReviewIterationStep,
    ReviewIterationWorkKind,
    compile_review_followup_design,
    load_review_followup_mapping,
)

_ROOT = Path(__file__).resolve().parents[2]
_PROGRAM = _ROOT / "configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml"
_MAPPING = _ROOT / "configs/evaluation/review_followups/iclr2027_v6_internal_r2.yaml"
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
        "H1_taste_abstraction",
        "H2_taste_specificity",
        "H3_native_effect",
        "E1_ecological_comparison",
        "D1_integrity_diagnostic",
    ]
    assert len(design.studies) == 5
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

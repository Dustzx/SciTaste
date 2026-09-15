from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.evaluation.model_role_conformance import (
    ConformanceCase,
    ConformanceCaseManifest,
    ConformanceCaseResult,
    ConformanceCaseResults,
    ConformanceExecutorReceipt,
    ConformanceMeasurements,
    EvidenceArtifact,
    EvidenceKind,
    EvidenceValidator,
    ExactModelIdentity,
    ExecutionKind,
    IdentityScope,
    ModelRole,
    ModelRoleConformancePlan,
    ModelRoleConformanceRunResult,
    SelectionStatus,
    compile_model_role_selection,
    inspect_model_role_conformance,
    load_model_role_plan,
    load_model_role_selection,
    plan_model_role_conformance,
    save_model_role_document,
)

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "configs/evaluation/model_roles/scitaste_b0_model_role_conformance_v1.yaml"


def _write_receipts(
    tmp_path: Path,
    *,
    judge_candidate: str = "judge-zhipu-glm53-flash",
) -> tuple[ModelRoleConformancePlan, list[Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan = plan_model_role_conformance(SUITE, repository_root=ROOT)
    plan = plan.model_copy(
        update={
            "exclusions": plan.exclusions.model_copy(
                update={
                    "conformance_task_bytes_bound": True,
                    "conformance_tasks_are_planning_labels_only": False,
                    "conformance_case_input_sha256": {
                        task_id: "6" * 64 for task_id in plan.exclusions.conformance_task_ids
                    },
                    "conformance_source_group_by_task": {
                        task_id: "b0-synthetic-contract-cases"
                        for task_id in plan.exclusions.conformance_task_ids
                    },
                }
            )
        }
    )
    candidate_ids = (
        "research-deepseek-v4-flash",
        "code-deepseek-v4-flash",
        judge_candidate,
        "embedding-minilm-local",
        "training-qwen3vl-4b-local",
        "training-sam21-tiny-local",
    )
    planned_by_id = {item.candidate.candidate_id: item for item in plan.candidates}
    receipt_paths: list[Path] = []
    for candidate_id in candidate_ids:
        planned = planned_by_id[candidate_id]
        expected = planned.candidate.identity
        for repetition in (1, 2):
            run_id = f"unit-{candidate_id}-{repetition}"
            started_at = datetime(2026, 9, 15, 12, 0, repetition, tzinfo=UTC)
            executor = ConformanceExecutorReceipt.create(
                runner_id="unit-conformance-runner",
                runner_version="1.0.0",
                candidate_id=candidate_id,
                role=planned.candidate.role,
                selection_scope_id=planned.candidate.selection_scope_id,
                provider=expected.provider,
                model_id=expected.model_id,
                revision=expected.revision,
                profile_sha256=planned.profile.profile_sha256,
                budget_sha256=planned.budget.budget_sha256,
                started_at_utc=started_at,
                completed_at_utc=started_at + timedelta(seconds=1),
                actual_execution=True,
                request_sha256="4" * 64,
                response_sha256="5" * 64,
            )
            executor_path = tmp_path / f"{run_id}.executor.json"
            executor_path.write_text(executor.model_dump_json(indent=2) + "\n", encoding="utf-8")
            executor_sha256 = hashlib.sha256(executor_path.read_bytes()).hexdigest()
            if expected.execution_kind is ExecutionKind.API:
                identity = ExactModelIdentity(
                    execution_kind=ExecutionKind.API,
                    provider=expected.provider,
                    model_id=expected.model_id,
                    revision=expected.revision,
                    route="openai-compatible-chat-completions",
                    scope=IdentityScope.HOSTED_TEMPORAL_WINDOW,
                    temporal_window_id=f"unit-window-{candidate_id}",
                    identity_evidence_sha256=executor_sha256,
                )
            else:
                identity = ExactModelIdentity(
                    execution_kind=ExecutionKind.LOCAL,
                    provider=expected.provider,
                    model_id=expected.model_id,
                    revision=expected.revision,
                    route="local-transformers",
                    scope=IdentityScope.IMMUTABLE_CHECKPOINT,
                    artifact_sha256="2" * 64,
                    identity_evidence_sha256=executor_sha256,
                )
            case_id = f"case-{candidate_id}-{repetition}"
            case_manifest = ConformanceCaseManifest.create(
                manifest_id=f"manifest-{candidate_id}-{repetition}",
                cases=(
                    ConformanceCase(
                        case_id=case_id,
                        task_id="b0-conformance-structured-decision",
                        source_group_id="b0-synthetic-contract-cases",
                        input_sha256="6" * 64,
                    ),
                ),
                formal_or_heldout_content_present=False,
            )
            manifest_path = tmp_path / f"{run_id}.cases.json"
            manifest_path.write_text(
                case_manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            manifest_file_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            case_results = ConformanceCaseResults.create(
                case_manifest_sha256=case_manifest.manifest_sha256,
                executor_receipt_file_sha256=executor_sha256,
                cases=(
                    ConformanceCaseResult(
                        case_id=case_id,
                        succeeded=True,
                        output_sha256="7" * 64,
                    ),
                ),
            )
            results_path = tmp_path / f"{run_id}.case-results.json"
            results_path.write_text(
                case_results.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            results_file_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()
            receipt = ModelRoleConformanceRunResult(
                suite_id=plan.suite_id,
                plan_sha256=plan.plan_sha256,
                run_id=run_id,
                candidate_id=candidate_id,
                role=planned.candidate.role,
                selection_scope_id=planned.candidate.selection_scope_id,
                exact_identity=identity,
                profile_sha256=planned.profile.profile_sha256,
                budget_sha256=planned.budget.budget_sha256,
                task_ids=("b0-conformance-structured-decision",),
                source_group_ids=("b0-synthetic-contract-cases",),
                measurements=ConformanceMeasurements(
                    schema_adherence=0.98,
                    tool_adherence=0.97,
                    success=0.96,
                    context=0.95,
                    latency_cost=0.94,
                    reproducibility=0.93,
                    task_fit=0.92,
                    successful_cases=1,
                    total_cases=1,
                    latency_p95_ms=100,
                    cost_usd=0.01 if expected.execution_kind is ExecutionKind.API else 0.0,
                ),
                evidence_artifacts=(
                    EvidenceArtifact(
                        kind=EvidenceKind.EXECUTOR_RECEIPT,
                        validator=EvidenceValidator.CONFORMANCE_EXECUTION_V1,
                        locator=executor_path.name,
                        sha256=executor_sha256,
                    ),
                    EvidenceArtifact(
                        kind=EvidenceKind.CASE_MANIFEST,
                        validator=EvidenceValidator.CASE_MANIFEST_V1,
                        locator=manifest_path.name,
                        sha256=manifest_file_sha256,
                    ),
                    EvidenceArtifact(
                        kind=EvidenceKind.CASE_RESULTS,
                        validator=EvidenceValidator.CASE_RESULTS_V1,
                        locator=results_path.name,
                        sha256=results_file_sha256,
                    ),
                ),
                actual_execution=True,
                inventory_presence_was_not_used_as_result=True,
                formal_or_heldout_content_used=False,
            )
            path = tmp_path / f"{receipt.run_id}.json"
            path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
            receipt_paths.append(path)
    return plan, receipt_paths


def test_b0_plan_is_multirole_and_empty_receipts_do_not_select(tmp_path: Path) -> None:
    plan = plan_model_role_conformance(SUITE, repository_root=ROOT)

    assert {item.candidate.role for item in plan.candidates} == set(ModelRole)
    assert any("qwen3vl-8b" in item.candidate.candidate_id for item in plan.candidates)
    assert any("qwen35-4b" in item.candidate.candidate_id for item in plan.candidates)
    assert not any("2b" in item.candidate.candidate_id for item in plan.candidates)

    manifest = compile_model_role_selection(plan, [], evidence_root=tmp_path)
    assert manifest.status is SelectionStatus.INCOMPLETE
    assert manifest.missing_roles == tuple(ModelRole)
    assert manifest.selections == ()
    status = inspect_model_role_conformance(plan, [], evidence_root=tmp_path)
    assert status.executable_for_conformance is False
    assert "freeze conformance case bytes" in status.next_action

    _, receipts = _write_receipts(tmp_path / "bounded-fixture")
    with pytest.raises(ValueError, match="planning labels only"):
        compile_model_role_selection(plan, receipts, evidence_root=tmp_path / "bounded-fixture")


def test_selection_binds_exact_identity_profile_budget_and_independent_judge(
    tmp_path: Path,
) -> None:
    plan, receipts = _write_receipts(tmp_path)
    manifest = compile_model_role_selection(plan, receipts, evidence_root=tmp_path)

    assert manifest.status is SelectionStatus.COMPLETE
    assert manifest.headline_eligible is True
    judge = next(item for item in manifest.selections if item.role is ModelRole.JUDGE)
    research = next(item for item in manifest.selections if item.role is ModelRole.RESEARCH_AGENT)
    assert judge.exact_identity.independence_key != research.exact_identity.independence_key
    assert judge.profile.profile_sha256
    assert judge.budget.budget_sha256
    assert judge.evidence_sha256

    selection_path = save_model_role_document(manifest, tmp_path / "selection.json")
    plan_path = save_model_role_document(plan, tmp_path / "plan.json")
    reloaded = load_model_role_selection(selection_path)
    status = inspect_model_role_conformance(
        load_model_role_plan(plan_path),
        receipts,
        evidence_root=tmp_path,
        selection=reloaded,
    )
    assert status.selection_status is SelectionStatus.COMPLETE
    assert status.selected_roles == tuple(ModelRole)


def test_same_identity_judge_is_marked_nonheadline(tmp_path: Path) -> None:
    plan, receipts = _write_receipts(tmp_path, judge_candidate="judge-deepseek-v4-flash")
    manifest = compile_model_role_selection(plan, receipts, evidence_root=tmp_path)

    assert manifest.status is SelectionStatus.NON_HEADLINE
    assert manifest.headline_eligible is False
    assert manifest.judge_generator_conflicts == ("judge-deepseek-v4-flash",)
    judge = next(item for item in manifest.selections if item.role is ModelRole.JUDGE)
    assert judge.headline_independent is False


def test_receipt_cannot_cross_into_formal_partition(tmp_path: Path) -> None:
    plan, receipts = _write_receipts(tmp_path)
    receipt_path = receipts[0]
    receipt = ModelRoleConformanceRunResult.model_validate_json(receipt_path.read_text())
    contaminated = receipt.model_copy(update={"task_ids": ("scitastebench-formal-partition",)})
    receipt_path.write_text(contaminated.model_dump_json(indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the frozen conformance partition"):
        compile_model_role_selection(plan, receipts, evidence_root=tmp_path)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.taste.episodes import (
    TasteEpisodeEvidenceRole,
    TasteEpisodePartition,
    TasteEpisodeSourceRelationship,
)
from scitaste.taste.trajectory_reconstruction import (
    TasteProcessEvidenceBinding,
    TasteTrajectoryAssignmentTiming,
    TasteTrajectorySamplingPlan,
    attach_prospective_taste_outcome,
    lock_prospective_taste_decision,
)


def _foundation(tmp_path: Path, research_state):
    runtime = ProjectRuntime(tmp_path / "outputs")
    project = runtime.create(
        ProjectManifest(
            project_id="prospective-v2-project",
            title="Prospective v2 smoke",
            research_direction="Verify temporal separation.",
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    idea = ProjectIdeaRevisionBinding.create(
        project_id="prospective-v2-project",
        observed_project_revision=0,
        observed_project_snapshot_sha256="1" * 64,
        revision_id="prospective-v2-idea",
        status="candidate",
        record_locator="runs/idea/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=False,
        paper_claim_authority=False,
    )
    frozen_at = datetime(2026, 9, 15, 1, tzinfo=UTC)
    plan = TasteTrajectorySamplingPlan.create(
        plan_id="prospective-v2-plan",
        project_id="prospective-v2-project",
        observed_project_revision=project.revision,
        observed_project_snapshot_sha256=project.snapshot_sha256,
        idea_revision=idea,
        source_project_id="prospective-v2-project",
        source_run_id="prospective-v2-run",
        source_relationship=TasteEpisodeSourceRelationship.SELF_PROJECT,
        source_group_id="prospective-v2-run",
        dataset_partition=TasteEpisodePartition.DEVELOPMENT,
        assignment_timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE,
        decision_log_locator="stage/decisions.jsonl",
        state_snapshot_root_locator="stage",
        frozen_at=frozen_at,
        source_absent_when_frozen=True,
    )
    project = runtime.begin_run(
        "prospective-v2-project",
        ProjectRun(
            run_id="prospective-v2-run",
            provider="scitaste-native",
            model="deterministic-controller",
            condition="synthetic-no-call-smoke",
            seed=0,
            status="running",
            evidence_scope="synthetic-test-only",
            stage_path="stage",
        ),
        expected_revision=project.revision,
    )
    state = research_state.model_copy(update={"project_id": "prospective-v2-project"})
    actions = [
        ResearchAction(
            action_id="repair-contract",
            type=MetaAction.REFINE,
            description="Repair the prospective evidence contract.",
        ),
        ResearchAction(
            action_id="launch-experiment",
            type=MetaAction.ADVANCE,
            description="Launch the objective experiment immediately.",
        ),
    ]
    decision = ResearchDecision(
        decision_id="prospective-v2-decision",
        timestamp=frozen_at + timedelta(minutes=1),
        stage=state.current_stage.value,
        state_snapshot_id=snapshot_id(state),
        candidate_actions=actions,
        selected_action=actions[0],
        rationale="Repair temporal validity before consuming experiment resources.",
        confidence=0.9,
    )
    return runtime, project, idea, plan, state, decision


def test_two_phase_capture_orders_outcome_and_detects_predecision_tampering(
    tmp_path: Path,
    research_state,
) -> None:
    runtime, project, idea, plan, state, decision = _foundation(tmp_path, research_state)
    lock = lock_prospective_taste_decision(
        plan,
        runtime=runtime,
        state=state,
        decision=decision,
        current_idea_revision=idea,
        expected_project_revision=project.revision,
        output=tmp_path / "LOCK.json",
        captured_at=decision.timestamp + timedelta(minutes=1),
    )
    assert lock.executor_result_id is None
    assert lock.actual_outcome is None

    run_root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    outcome_path = run_root / "stage" / "outcome.json"
    outcome_path.write_text('{"status":"SUCCEEDED"}\n', encoding="utf-8")
    evidence = (
        TasteProcessEvidenceBinding(
            evidence_id="executor-outcome",
            role=TasteEpisodeEvidenceRole.OUTCOME,
            locator="stage/outcome.json",
        ),
    )
    with pytest.raises(ValueError, match="strictly later"):
        attach_prospective_taste_outcome(
            plan,
            lock,
            source_root=run_root,
            executor_result_id="result-01",
            observed_at=lock.captured_at,
            actual_outcome={"status": "SUCCEEDED"},
            evidence=evidence,
            output=tmp_path / "EARLY.json",
            projection_output=tmp_path / "EARLY_PROJECTION.json",
        )

    immutable = run_root / lock.immutable_decision_locator
    original = immutable.read_bytes()
    immutable.write_bytes(original.replace(b"Repair temporal", b"Change temporal", 1))
    with pytest.raises(ValueError, match="immutable predecision record drifted"):
        attach_prospective_taste_outcome(
            plan,
            lock,
            source_root=run_root,
            executor_result_id="result-01",
            observed_at=lock.captured_at + timedelta(minutes=1),
            actual_outcome={"status": "SUCCEEDED"},
            evidence=evidence,
            output=tmp_path / "TAMPERED.json",
            projection_output=tmp_path / "TAMPERED_PROJECTION.json",
            attached_at=lock.captured_at + timedelta(minutes=2),
        )
    immutable.write_bytes(original)

    attachment, projection = attach_prospective_taste_outcome(
        plan,
        lock,
        source_root=run_root,
        executor_result_id="result-01",
        observed_at=lock.captured_at + timedelta(minutes=1),
        actual_outcome={"status": "SUCCEEDED"},
        evidence=evidence,
        output=tmp_path / "ATTACHMENT.json",
        projection_output=tmp_path / "PROJECTION.json",
        attached_at=lock.captured_at + timedelta(minutes=2),
    )
    assert attachment.predecision_sha256 == lock.decision_sha256
    assert projection.completed_decision.executor_result_id == "result-01"
    assert projection.completed_decision.actual_outcome == {"status": "SUCCEEDED"}
    assert immutable.read_bytes() == original

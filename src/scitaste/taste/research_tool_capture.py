"""Prospective Taste evidence capture for the selected-action tool loop."""

from datetime import UTC, datetime

from scitaste.project import inspect_current_idea_revision
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
    save_taste_trajectory_sampling_plan,
)


class ResearchToolTasteCapture:
    def __init__(self, *, runtime, plan):
        self.runtime = runtime
        self.plan = plan
        self.root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id

    @classmethod
    def prepare(cls, *, runtime, project_id, run_id, output):
        # Concurrent research runs may register between two reads. The Idea
        # binding and captured project digest must describe the SAME revision.
        for _ in range(8):
            idea = inspect_current_idea_revision(runtime, project_id).current_binding
            snapshot = runtime.open(project_id)
            if idea is None or (
                idea.observed_project_revision == snapshot.revision
                and idea.observed_project_snapshot_sha256 == snapshot.snapshot_sha256
            ):
                break
        else:
            raise ValueError("Project changed repeatedly while freezing the Idea binding")
        if any(item.run_id == run_id for item in snapshot.manifest.runs):
            raise ValueError("Prospective plan must precede source-run registration")
        if idea is None:
            raise ValueError("Prospective capture requires a current Idea binding")
        plan = TasteTrajectorySamplingPlan.create(
            plan_id=run_id + "-capture",
            project_id=project_id,
            observed_project_revision=snapshot.revision,
            observed_project_snapshot_sha256=snapshot.snapshot_sha256,
            idea_revision=idea,
            source_project_id=project_id,
            source_run_id=run_id,
            source_relationship=TasteEpisodeSourceRelationship.SELF_PROJECT,
            source_group_id=run_id,
            dataset_partition=TasteEpisodePartition.DEVELOPMENT,
            assignment_timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE,
            decision_log_locator="taste_capture/predecisions.jsonl",
            state_snapshot_root_locator="taste_capture/state",
            frozen_at=datetime.now(UTC),
            source_absent_when_frozen=True,
        )
        save_taste_trajectory_sampling_plan(plan, output)
        return cls(runtime=runtime, plan=plan)

    def before_execution(self, state, decision, turn):
        idea = inspect_current_idea_revision(self.runtime, self.plan.project_id).current_binding
        if idea is None:
            raise ValueError("Current Idea binding unavailable before execution")
        directory = self.root / "taste_capture" / f"decision-{turn:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        return lock_prospective_taste_decision(
            self.plan,
            runtime=self.runtime,
            state=state,
            decision=decision,
            current_idea_revision=idea,
            expected_project_revision=self.runtime.open(self.plan.project_id).revision,
            output=directory / "LOCK.json",
        )

    def after_execution(self, lock, result, turn):
        directory = self.root / "taste_capture" / f"decision-{turn:03d}"
        path = directory / "EXECUTION_RESULT.json"
        with path.open("x") as stream:
            stream.write(result.model_dump_json(indent=2))
        return attach_prospective_taste_outcome(
            self.plan,
            lock,
            source_root=self.root,
            executor_result_id=result.result_id,
            observed_at=datetime.now(UTC),
            actual_outcome=result.model_dump(mode="json"),
            evidence=(
                TasteProcessEvidenceBinding(
                    evidence_id=f"tool-result-{turn}",
                    role=TasteEpisodeEvidenceRole.OUTCOME,
                    locator=path.relative_to(self.root).as_posix(),
                ),
            ),
            output=directory / "OUTCOME.json",
            projection_output=directory / "COMPLETED.json",
        )

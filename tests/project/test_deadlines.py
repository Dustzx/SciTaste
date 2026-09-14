from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from scitaste.project import (
    ProjectDeadlineUrgency,
    ProjectManifest,
    ProjectRuntime,
    ProjectVenueSchedule,
    assign_project_venue_schedule,
    complete_project_venue_milestone,
    inspect_project_deadline,
)


def _schedule(*, venue_name: str = "ICLR 2027") -> ProjectVenueSchedule:
    return ProjectVenueSchedule.create(
        schedule_id="iclr-2027-test-v1",
        venue_id="iclr-2027",
        venue_name=venue_name,
        deadline_timezone="Anywhere on Earth (UTC-12)",
        sources=(
            {
                "source_id": "iclr-author-guide",
                "role": "authoritative",
                "url": "https://iclr.cc/Conferences/2027/AuthorGuidelines",
                "checked_at": "2026-09-15T00:00:00+08:00",
            },
        ),
        milestones=(
            {
                "milestone_id": "abstract-registration",
                "kind": "abstract-registration",
                "deadline_at": "2026-09-18T23:59:00-12:00",
                "hard_deadline": True,
                "source_id": "iclr-author-guide",
                "required_outcomes": ("Register a genuine abstract.",),
            },
            {
                "milestone_id": "paper-submission",
                "kind": "paper-submission",
                "deadline_at": "2026-09-25T23:59:00-12:00",
                "hard_deadline": True,
                "source_id": "iclr-author-guide",
                "required_outcomes": ("Submit an anonymous paper.",),
            },
        ),
    )


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="deadline-project",
            title="Deadline project",
            research_direction="Close one submission honestly.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    return runtime


def test_deadline_status_exposes_submission_pressure(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    snapshot = assign_project_venue_schedule(
        runtime,
        project_id="deadline-project",
        schedule=_schedule(),
        expected_revision=0,
    )

    status = inspect_project_deadline(
        snapshot,
        observed_at=datetime.fromisoformat("2026-09-15T00:00:00+08:00"),
    )

    assert snapshot.revision == 1
    assert status.next_milestone_id == "abstract-registration"
    assert status.hours_to_next_deadline == pytest.approx(115.983, abs=0.001)
    assert status.urgency is ProjectDeadlineUrgency.CRITICAL
    assert status.defer_noncritical_work is True
    assert status.recommended_outcomes == ("Register a genuine abstract.",)


def test_completion_requires_owned_evidence_and_advances_the_clock(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    snapshot = assign_project_venue_schedule(
        runtime,
        project_id="deadline-project",
        schedule=_schedule(),
        expected_revision=0,
    )
    evidence = runtime.projects_root / "deadline-project/submission/abstract-receipt.json"
    evidence.parent.mkdir()
    evidence.write_text('{"submission":"registered"}\n', encoding="utf-8")

    snapshot = complete_project_venue_milestone(
        runtime,
        project_id="deadline-project",
        milestone_id="abstract-registration",
        expected_revision=snapshot.revision,
        completed_at=datetime.fromisoformat("2026-09-18T12:00:00+08:00"),
        evidence_locator="submission/abstract-receipt.json",
    )
    status = inspect_project_deadline(
        snapshot,
        observed_at=datetime.fromisoformat("2026-09-18T12:00:00+08:00"),
        project_root=runtime.projects_root / "deadline-project",
    )

    assert snapshot.revision == 2
    assert status.completed_milestone_ids == ("abstract-registration",)
    assert status.next_milestone_id == "paper-submission"
    assert status.urgency is ProjectDeadlineUrgency.URGENT
    assert status.defer_noncritical_work is True
    completion = snapshot.manifest.model_extra["venue_milestone_completions"][0]
    assert completion["evidence_locator"] == "submission/abstract-receipt.json"
    assert len(completion["evidence_sha256"]) == 64

    evidence.write_text('{"submission":"tampered"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="evidence hash mismatch"):
        inspect_project_deadline(
            snapshot,
            project_root=runtime.projects_root / "deadline-project",
        )


def test_assignment_rejects_a_different_target_venue(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    with pytest.raises(ValueError, match="target venue differs"):
        assign_project_venue_schedule(
            runtime,
            project_id="deadline-project",
            schedule=_schedule(venue_name="NeurIPS 2027"),
            expected_revision=0,
        )

    assert runtime.open("deadline-project").revision == 0

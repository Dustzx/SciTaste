from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scitaste.project.models import ProjectManifest
from scitaste.project.runtime import ProjectRuntime
from scitaste.project.submission_plan import (
    SubmissionPlanDraft,
    read_submission_plan,
    save_submission_plan,
    submission_plan_status,
)


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    for project_id in ("paper-a", "paper-b"):
        runtime.create(
            ProjectManifest(
                project_id=project_id,
                title=project_id,
                research_direction="research",
                target_venue="CVPR 2027",
                status="active",
            )
        )
    return runtime


def _draft(**changes) -> SubmissionPlanDraft:
    fields = dict(
        plan_id="submission-v1",
        project_id="paper-a",
        venue_name="CVPR 2027",
        objective="Deliver evidence-grounded paper",
        internal_deadline_at="2026-10-11T23:59:00+08:00",
        deadline_basis="user-internal-target",
        deadline_note="An internal goal, not the official deadline.",
        work_items=[
            dict(
                work_id="experiment",
                title="Collect evidence",
                kind="experiment",
                phase="experiments",
                owner="researcher",
                due_at="2026-10-05T23:59:00+08:00",
                acceptance=["Actual outputs"],
                claim_critical=True,
                estimated_hours=20,
                expected_evidence_gain=90,
            ),
            dict(
                work_id="paper",
                title="Write paper",
                kind="manuscript",
                phase="writing",
                owner="writer",
                due_at="2026-10-10T23:59:00+08:00",
                acceptance=["Grounded manuscript"],
                prerequisite_ids=["experiment"],
                submission_blocking=True,
                estimated_hours=10,
                expected_evidence_gain=40,
            ),
            dict(
                work_id="polish",
                title="Optional UI polish",
                kind="interface",
                phase="project",
                owner="UI",
                due_at="2026-10-10T23:59:00+08:00",
                acceptance=["Usability"],
                estimated_hours=3,
                expected_evidence_gain=0,
            ),
        ],
    )
    fields.update(changes)
    return SubmissionPlanDraft.model_validate(fields)


def test_plan_is_project_owned_and_defers_optional_work(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    save_submission_plan(
        runtime, _draft(), expected_revision=0, author="owner", reason="Ten-day delivery"
    )
    status = submission_plan_status(
        runtime, "paper-a", observed_at=datetime.fromisoformat("2026-10-02T00:00+08:00")
    )
    assert status["ready_work_ids"] == ["experiment"]
    assert status["scheduling_policy"] == "as-soon-as-prerequisites-ready"
    assert status["due_date_semantics"] == "latest-completion"
    assert status["work_items"][1]["effective_state"] == "waiting"
    assert status["work_items"][2]["effective_state"] == "deadline-deferred"
    assert status["execution_authorized"] is False
    assert not submission_plan_status(runtime, "paper-b")["configured"]
    assert (runtime.projects_root / "paper-a/docs/project/SUBMISSION_PLAN.md").is_file()
    with pytest.raises(ValueError, match=r"stale|revision"):
        save_submission_plan(
            runtime, _draft(), expected_revision=0, author="owner", reason="Stale write"
        )
    assert read_submission_plan(runtime.open("paper-a")).plan_revision == 1


def test_completion_is_bound_and_history_is_bounded_to_one_container(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    save_submission_plan(runtime, _draft(), expected_revision=0, author="owner", reason="Initial")
    project = runtime.projects_root / "paper-a"
    evidence = project / "experiments.json"
    evidence.write_text('{"result":1}\n')
    payload = _draft().model_dump(mode="json")
    payload["work_items"][0].update(
        state="complete",
        evidence=[
            {
                "locator": "experiments.json",
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }
        ],
    )
    save_submission_plan(
        runtime,
        SubmissionPlanDraft.model_validate(payload),
        expected_revision=1,
        author="owner",
        reason="Measured evidence collected",
    )
    status = submission_plan_status(
        runtime, "paper-a", observed_at=datetime.fromisoformat("2026-10-02T00:00+08:00")
    )
    assert status["ready_work_ids"] == ["paper"]
    assert status["completed_deliverables"] == 1
    history = project / "docs/project/archive/submission-plans.jsonl"
    assert json.loads(history.read_text())["plan_revision"] == 1
    evidence.write_text('{"result":2}\n')
    status = submission_plan_status(runtime, "paper-a")
    assert status["completed_deliverables"] == 0
    assert status["work_items"][0]["effective_state"] == "evidence-invalid"
    assert status["work_items"][1]["effective_state"] == "waiting"


def test_invalid_delivery_graph_or_unsupported_completion_is_rejected() -> None:
    payload = _draft().model_dump(mode="json")
    payload["work_items"][0]["prerequisite_ids"] = ["paper"]
    with pytest.raises(ValueError, match=r"cycle|cyclic"):
        SubmissionPlanDraft.model_validate(payload)
    payload = _draft().model_dump(mode="json")
    payload["work_items"][0]["state"] = "complete"
    with pytest.raises(ValueError, match="requires project-owned evidence"):
        SubmissionPlanDraft.model_validate(payload)
    with pytest.raises(ValueError, match="timezone"):
        _draft(internal_deadline_at="2026-10-11T23:59:00")


def test_official_deadline_is_preserved_and_completion_cannot_escape_project(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    official = {
        "milestones": [{"kind": "paper-submission", "deadline_at": "2026-11-16T23:59:00-12:00"}]
    }
    runtime.update("paper-a", expected_revision=0, venue_schedule=official)
    save_submission_plan(
        runtime, _draft(), expected_revision=1, author="owner", reason="Internal target"
    )
    assert runtime.open("paper-a").manifest.model_extra["venue_schedule"] == official
    with pytest.raises(ValueError, match="after official"):
        save_submission_plan(
            runtime,
            _draft(internal_deadline_at="2026-12-01T00:00:00+08:00"),
            expected_revision=2,
            author="owner",
            reason="Too late",
        )
    external = tmp_path / "secret.json"
    external.write_text("private")
    (runtime.projects_root / "paper-a/leak.json").symlink_to(external)
    payload = _draft().model_dump(mode="json")
    payload["work_items"][0].update(
        state="complete",
        evidence=[
            {
                "locator": "leak.json",
                "sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
            }
        ],
    )
    with pytest.raises(ValueError):
        save_submission_plan(
            runtime,
            SubmissionPlanDraft.model_validate(payload),
            expected_revision=2,
            author="owner",
            reason="Invalid foreign evidence",
        )
    assert runtime.open("paper-a").revision == 2

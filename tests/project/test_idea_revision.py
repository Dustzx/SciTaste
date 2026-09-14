from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.cli import main
from scitaste.project import (
    ProjectIdeaRevisionArtifact,
    ProjectIdeaRevisionEntry,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
    inspect_current_idea_revision,
    register_project_idea_revision,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialize_revision(runtime: ProjectRuntime) -> tuple[ProjectIdeaRevisionEntry, int]:
    snapshot = runtime.create(
        ProjectManifest(
            project_id="idea-project",
            title="Idea project",
            research_direction="Learn a bounded lifecycle policy.",
            status="active",
        )
    )
    run_id = "2026-09-14__scitaste-native__idea-revision__seed-00"
    snapshot = runtime.begin_run(
        "idea-project",
        ProjectRun(
            run_id=run_id,
            provider="scitaste-native",
            model="deterministic-controller",
            condition="idea-revision",
            seed=0,
            status="complete-candidate-revision",
            evidence_scope="candidate-only",
            stage_path="idea_refinement",
        ),
        expected_revision=snapshot.revision,
    )
    stage = runtime.projects_root / "idea-project/runs" / run_id / "idea_refinement"
    narrative = stage / "IDEA_REVISION.md"
    intervention = stage / "INTERVENTIONS.jsonl"
    narrative.write_text("# Lifecycle Taste\n", encoding="utf-8")
    intervention.write_text('{"operation":"challenge-attribution"}\n', encoding="utf-8")
    artifact = ProjectIdeaRevisionArtifact(
        project_id="idea-project",
        revision_id="lifecycle-taste-candidate-01",
        status="candidate",
        paper_claim_authority=False,
        novelty_review_complete=False,
        scientific_effectiveness_established=False,
        title="Grounded Scientific Taste",
        research_question="Can trajectory outcomes improve later research decisions?",
        single_thesis="Learn Scientific Taste as a lifecycle policy.",
        scientific_problem="Long-horizon credit assignment over research trajectories.",
        policy_object="pi_T(a_t | s_t, A_t, M_t)",
        decision_families=("experiment-design", "claim-calibration"),
        supervision_channels=("internal-outcome", "human-intervention"),
        subordinate_mechanisms={
            "tool_intelligence": "proposes process episodes",
            "generation_as_content": "records human interventions",
        },
        rejected_framings=("software tests establish scientific effectiveness",),
        falsifiable_hypotheses=("Outcome updates improve held-out decisions.",),
        evidence_inputs=(
            {
                "role": "human-intervention",
                "locator": intervention.relative_to(
                    runtime.projects_root / "idea-project"
                ).as_posix(),
                "sha256": _sha(intervention),
            },
        ),
        related_work_gap={"status": "targeted-screen-only"},
        next_gates=("independent novelty challenge",),
        narrative_locator=narrative.relative_to(runtime.projects_root / "idea-project").as_posix(),
        narrative_sha256=_sha(narrative),
    )
    record = stage / "REVISION.json"
    record.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return (
        ProjectIdeaRevisionEntry(
            revision_id=artifact.revision_id,
            status=artifact.status,
            run_id=run_id,
            record_locator=record.relative_to(runtime.projects_root / "idea-project").as_posix(),
            record_sha256=_sha(record),
            supersedes_concepts=("static-controller",),
            selected_for_paper=False,
        ),
        snapshot.revision,
    )


def test_candidate_idea_revision_is_verified_but_cannot_freeze_experiments(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    entry, revision = _materialize_revision(runtime)

    snapshot = register_project_idea_revision(
        runtime,
        "idea-project",
        entry,
        expected_revision=revision,
    )
    report = inspect_current_idea_revision(runtime, "idea-project")

    assert snapshot.revision == revision + 1
    assert report.artifact_verified is True
    assert report.input_evidence_verified is True
    assert report.method_development_binding_available is True
    assert report.experiment_freeze_eligible is False
    assert report.paper_claim_authority is False
    assert report.current_binding is not None
    assert {finding.code for finding in report.findings} == {
        "current-revision-is-candidate",
        "novelty-review-incomplete",
    }


def test_tampered_idea_input_invalidates_downstream_binding(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    entry, revision = _materialize_revision(runtime)
    register_project_idea_revision(
        runtime,
        "idea-project",
        entry,
        expected_revision=revision,
    )
    intervention = (
        runtime.projects_root
        / "idea-project/runs/2026-09-14__scitaste-native__idea-revision__seed-00"
        / "idea_refinement/INTERVENTIONS.jsonl"
    )
    intervention.write_text(json.dumps({"operation": "accept"}) + "\n", encoding="utf-8")

    report = inspect_current_idea_revision(runtime, "idea-project")

    assert report.artifact_verified is False
    assert report.current_binding is None
    assert {finding.code for finding in report.findings} == {"input-evidence-hash-mismatch"}


def test_idea_registration_rejects_stale_project_revision(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    entry, revision = _materialize_revision(runtime)

    with pytest.raises(ValueError, match="expected project revision"):
        register_project_idea_revision(
            runtime,
            "idea-project",
            entry,
            expected_revision=revision - 1,
        )


def test_project_idea_status_cli_exposes_scientific_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    entry, revision = _materialize_revision(runtime)
    register_project_idea_revision(
        runtime,
        "idea-project",
        entry,
        expected_revision=revision,
    )

    assert (
        main(
            [
                "project",
                "idea",
                "status",
                "--project-id",
                "idea-project",
                "--outputs-root",
                str(tmp_path / "outputs"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["artifact_verified"] is True
    assert payload["method_development_binding_available"] is True
    assert payload["experiment_freeze_eligible"] is False

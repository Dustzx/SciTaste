from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scitaste.lifecycle import assess_project_lifecycle
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.models import content_sha256
from scitaste.writing.venue import VenueSubmissionAssessment


def _write_stage(run_root: Path, stage: str) -> str:
    stage_root = run_root / "stages" / stage
    stage_root.mkdir(parents=True)
    state = stage_root / "research_state.json"
    decisions = stage_root / "decisions.jsonl"
    summary = stage_root / f"{stage}_summary.json"
    state.write_text('{"revision":1}\n', encoding="utf-8")
    decisions.write_text('{"decision":"bounded"}\n', encoding="utf-8")
    summary.write_text('{"status":"complete"}\n', encoding="utf-8")
    payload = {
        "schema_version": "1.1",
        "stage": stage,
        "status": "complete",
        "purpose": f"Complete the {stage} phase.",
        "summary": {"status": "complete"},
        "input_state_sha256": None,
        "output_state_locator": f"stages/{stage}/research_state.json",
        "output_state_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
        "decision_log_locator": f"stages/{stage}/decisions.jsonl",
        "decision_log_sha256": hashlib.sha256(decisions.read_bytes()).hexdigest(),
        "artifact_sha256": {
            f"stages/{stage}/{stage}_summary.json": hashlib.sha256(
                summary.read_bytes()
            ).hexdigest()
        },
    }
    payload["record_sha256"] = content_sha256(payload)
    record = stage_root / "STAGE.json"
    record.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return f"runs/native-run/stages/{stage}/STAGE.json"


def _submission_assessment(markdown: str) -> VenueSubmissionAssessment:
    return VenueSubmissionAssessment.create(
        venue_id="iclr-2027",
        venue_name="ICLR 2027",
        submission_mode="anonymous",
        template_fingerprint="1" * 64,
        manuscript_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        bibliography_sha256=hashlib.sha256(b"").hexdigest(),
        title="Scientific Taste for Autonomous Research",
        title_present=True,
        word_count=1_000,
        abstract_paragraph_count=1,
        citation_keys=(),
        bibliography_keys=(),
        duplicate_bibliography_keys=(),
        missing_citation_keys=(),
        required_statements=("AI Use Statement",),
        missing_required_statements=(),
        recommended_statements=(),
        missing_recommended_statements=(),
        statement_order_valid=True,
        statement_page_limits={},
        statement_pages={},
        statement_page_limit_violations=(),
        identity_markers=(),
        internal_markers=(),
        compiled=True,
        main_text_pages=8,
        max_main_pages=9,
        page_limit_satisfied=True,
        eligible_for_submission=True,
    )


def test_lifecycle_requires_verified_native_stages_and_review_closure(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="lifecycle-project",
            title="Lifecycle project",
            research_direction="Verify idea-to-paper-to-review continuity.",
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    snapshot = runtime.begin_run(
        "lifecycle-project",
        ProjectRun(
            run_id="native-run",
            provider="scitaste-native",
            model="deterministic-controller",
            condition="full-scitaste",
            seed=0,
            status="running",
            evidence_scope="test-only",
            stage_path="stages",
        ),
        expected_revision=snapshot.revision,
    )
    run_root = runtime.projects_root / "lifecycle-project/runs/native-run"
    stage_records = {
        stage: _write_stage(run_root, stage) for stage in ("discovery", "evidence")
    }
    snapshot = runtime.update_run(
        "lifecycle-project",
        "native-run",
        expected_revision=snapshot.revision,
        status="complete",
        stage_records=stage_records,
    )
    paper_root = runtime.projects_root / "lifecycle-project/papers/paper-v1"
    paper_root.mkdir(parents=True)
    markdown = "# Scientific Taste for Autonomous Research\n"
    (paper_root / "main.md").write_text(markdown, encoding="utf-8")
    assessment = _submission_assessment(markdown)
    (paper_root / "SUBMISSION_ASSESSMENT.json").write_text(
        assessment.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    snapshot = runtime.register_paper(
        "lifecycle-project",
        PaperManifest(
            paper_id="paper-v1",
            project_id="lifecycle-project",
            title="Scientific Taste for Autonomous Research",
            date="2026-09-11",
            provider="scitaste-native",
            model="deterministic-writer",
            condition="venue-draft",
            task="held-out-task",
            seed=0,
            stage=17,
            status="venue-submission-draft",
            evidence_scope="test-only",
            source_run="native-run",
            files={
                "source-markdown": "main.md",
                "submission-assessment": "SUBMISSION_ASSESSMENT.json",
            },
            venue_id="iclr-2027",
            eligible_for_submission=True,
            submission_assessment_sha256=assessment.record_sha256,
        ),
        directory_name="paper-v1",
        expected_revision=snapshot.revision,
    )
    runtime.select_paper(
        "lifecycle-project",
        "paper-v1",
        expected_revision=snapshot.revision,
        global_latest=False,
    )

    lifecycle = assess_project_lifecycle(runtime, "lifecycle-project")

    assert lifecycle.state == "paper"
    assert lifecycle.idea_to_paper_complete is True
    assert lifecycle.internal_review_cycle_complete is False
    assert lifecycle.independent_pre_submission_review_complete is False
    assert [item.state for item in lifecycle.gates[:5]] == [
        "satisfied",
        "satisfied",
        "satisfied",
        "satisfied",
        "satisfied",
    ]
    assert lifecycle.gates[5].reason_code == "no-review-round"
    assert lifecycle.official_decision_authority is False

    (run_root / "stages/evidence/evidence_summary.json").write_text(
        "tampered\n", encoding="utf-8"
    )
    drifted = assess_project_lifecycle(runtime, "lifecycle-project")
    assert drifted.idea_to_paper_complete is False
    assert drifted.gates[1].reason_code == "native-evidence-unverified"
    assert drifted.gates[2].reason_code == "paper-source-run-lacks-complete-native-lineage"

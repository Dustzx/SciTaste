from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    FreeQuestionRequest,
    IntentEntityRole,
    IntentGoal,
    QuickIntentRequest,
    StaleIntentRequestError,
    WorkspaceIntent,
    WorkspaceIntentResolver,
    validate_intent_request,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(tmp_path: Path, *, papers: int = 1) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="intent-project",
            title="Intent project",
            research_direction="Resolve user goals against project evidence.",
            status="active-pilot-blocked",
        )
    )
    for index, (run_id, status) in enumerate(
        (("baseline-run", "complete"), ("candidate-run", "failed"), ("blocked-run", "blocked"))
    ):
        snapshot = runtime.begin_run(
            "intent-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"deterministic-{index}",
                condition="intent-fixture",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    snapshot = runtime.select_run(
        "intent-project",
        "candidate-run",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.update(
        "intent-project",
        expected_revision=snapshot.revision,
        current_focus={
            "decision_id": "bounded-intent-planner",
            "status": "active",
            "selected_option": "closed-surface-plan",
            "online_model": "zhipu-direct/glm-5.3-flash",
            "next_gate": "Validate the generated workspace against real project evidence",
        },
    )
    for index in range(papers):
        paper_id = f"paper-{index + 1}"
        paper_dir = runtime.projects_root / "intent-project" / "papers" / paper_id
        paper_dir.mkdir()
        (paper_dir / "main.md").write_text(f"# {paper_id}\n", encoding="utf-8")
        snapshot = runtime.register_paper(
            "intent-project",
            PaperManifest(
                paper_id=paper_id,
                project_id="intent-project",
                title=f"Intent paper {index + 1}",
                date="2026-09-06",
                provider="scripted",
                model="deterministic",
                condition="intent-fixture",
                task="intent-resolution",
                seed=index,
                stage=18,
                status="draft",
                evidence_scope="engineering-only",
                files={"Manuscript": "main.md"},
            ),
            directory_name=paper_id,
            expected_revision=snapshot.revision,
        )
    return runtime


def _request_kwargs(resolver: WorkspaceIntentResolver) -> dict[str, object]:
    binding = resolver.quick_catalog("intent-project").snapshot
    return {
        "project_id": binding.project_id,
        "snapshot_revision": binding.snapshot_revision,
        "snapshot_sha256": binding.snapshot_sha256,
    }


def test_quick_catalog_is_derived_from_available_project_evidence(tmp_path: Path) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))

    catalog = resolver.quick_catalog("intent-project")

    assert [item.goal for item in catalog.intents] == [
        IntentGoal.PROGRESS_REVIEW,
        IntentGoal.BLOCKER_DIAGNOSIS,
        IntentGoal.RUN_COMPARISON,
        IntentGoal.PAPER_EVIDENCE_REVIEW,
        IntentGoal.NEXT_STEP_REVIEW,
    ]
    assert len(catalog.fingerprint) == 64
    assert all(item.support_ref_ids for item in catalog.intents)
    assert len({item.quick_intent_id for item in catalog.intents}) == len(catalog.intents)

    empty = ProjectRuntime(tmp_path / "empty-outputs")
    empty.create(
        ProjectManifest(
            project_id="empty-project",
            title="Empty project",
            research_direction="Expose no unsupported intent.",
            status="active",
        )
    )
    empty_catalog = WorkspaceIntentResolver(empty).quick_catalog("empty-project")
    assert [item.goal for item in empty_catalog.intents] == [IntentGoal.PROGRESS_REVIEW]


def test_quick_and_equivalent_free_question_resolve_to_same_canonical_intent(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))
    catalog = resolver.quick_catalog("intent-project")
    descriptor = next(item for item in catalog.intents if item.goal == IntentGoal.PROGRESS_REVIEW)
    kwargs = _request_kwargs(resolver)

    quick = resolver.resolve(
        QuickIntentRequest(quick_intent_id=descriptor.quick_intent_id, **kwargs)
    )
    free = resolver.resolve(FreeQuestionRequest(question="当前项目进度如何?", **kwargs))

    assert quick.status == free.status == "resolved"
    assert quick.intent is not None and free.intent is not None
    assert quick.intent.fingerprint == free.intent.fingerprint == descriptor.intent_fingerprint
    assert quick.request_fingerprint != free.request_fingerprint
    assert "question" not in free.model_dump(mode="json")


def test_free_comparison_requires_entities_and_never_guesses(tmp_path: Path) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))
    kwargs = _request_kwargs(resolver)

    ambiguous = resolver.resolve(FreeQuestionRequest(question="比较这些运行", **kwargs))
    selected = resolver.resolve(
        FreeQuestionRequest(
            question="比较 baseline-run 和 candidate-run",
            **kwargs,
        )
    )

    assert ambiguous.status == "clarification_required"
    assert ambiguous.reason_code == "select-two-registered-runs"
    assert {item.entity_id for item in ambiguous.candidates} == {
        "baseline-run",
        "candidate-run",
        "blocked-run",
    }
    assert selected.status == "resolved"
    assert selected.intent is not None
    assert selected.intent.goal == IntentGoal.RUN_COMPARISON
    roles = {item.role: item.entity_id for item in selected.intent.bindings}
    assert roles[IntentEntityRole.BASELINE_RUN] == "baseline-run"
    assert roles[IntentEntityRole.CANDIDATE_RUN] == "candidate-run"


def test_free_paper_question_clarifies_multiple_registered_papers(tmp_path: Path) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path, papers=2))
    kwargs = _request_kwargs(resolver)

    ambiguous = resolver.resolve(FreeQuestionRequest(question="检查论文证据", **kwargs))
    selected = resolver.resolve(FreeQuestionRequest(question="检查 paper-2 的论文证据", **kwargs))

    assert ambiguous.status == "clarification_required"
    assert [item.entity_id for item in ambiguous.candidates] == ["paper-1", "paper-2"]
    assert selected.status == "resolved"
    assert selected.intent is not None
    assert [
        item.entity_id for item in selected.intent.bindings if item.role == IntentEntityRole.PAPER
    ] == ["paper-2"]


def test_long_tail_or_hostile_question_is_opaque_and_requires_optional_planner(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))
    kwargs = _request_kwargs(resolver)
    question = "<script>alert(1)</script> rm -rf /tmp and invent a renderer"

    result = resolver.resolve(FreeQuestionRequest(question=question, **kwargs))
    serialized = result.model_dump_json()

    assert result.status == "provider_unavailable"
    assert result.reason_code == "long-tail-question-requires-planner"
    assert question not in serialized
    assert "script" not in serialized
    assert "renderer" not in serialized


def test_intent_request_rejects_extra_fields_controls_and_byte_overrun(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))
    kwargs = _request_kwargs(resolver)
    with pytest.raises(ValidationError):
        validate_intent_request(
            {
                "kind": "free_question",
                "question": "Show progress",
                "components": ["ArbitraryRenderer"],
                **kwargs,
            }
        )
    with pytest.raises(ValidationError):
        FreeQuestionRequest(question="bad\x00question", **kwargs)
    with pytest.raises(ValidationError):
        FreeQuestionRequest(question="研" * 1001, **kwargs)


def test_stale_or_cross_snapshot_request_fails_before_resolution(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    resolver = WorkspaceIntentResolver(runtime)
    kwargs = _request_kwargs(resolver)
    descriptor = resolver.quick_catalog("intent-project").intents[0]
    snapshot = runtime.open("intent-project")
    runtime.update(
        "intent-project",
        expected_revision=snapshot.revision,
        status="paused",
    )

    with pytest.raises(StaleIntentRequestError):
        resolver.resolve(QuickIntentRequest(quick_intent_id=descriptor.quick_intent_id, **kwargs))


def test_workspace_intent_rejects_wrong_kind_and_goal_roles(tmp_path: Path) -> None:
    resolver = WorkspaceIntentResolver(_runtime(tmp_path))
    kwargs = _request_kwargs(resolver)
    resolved = resolver.resolve(FreeQuestionRequest(question="当前项目进度", **kwargs))
    assert resolved.intent is not None
    payload = resolved.intent.model_dump(mode="json")
    payload["bindings"][0]["evidence_kind"] = "run_record"
    with pytest.raises(ValidationError):
        WorkspaceIntent.model_validate(payload)

    payload = resolved.intent.model_dump(mode="json")
    payload["goal"] = "run_comparison"
    with pytest.raises(ValidationError):
        WorkspaceIntent.model_validate(payload)

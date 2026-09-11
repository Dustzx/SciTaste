from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    FreeQuestionRequest,
    IntentGoal,
    PlanGroup,
    QuickIntentRequest,
    StaleSurfacePlanError,
    SurfaceCandidateCatalog,
    SurfaceCandidateFactory,
    SurfacePlan,
    SurfacePlanEntry,
    TrustedComponent,
    WorkspaceIntentResolver,
    materialize_surface_plan,
    validate_surface_plan,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="planning-project",
            title="Planning project",
            research_direction="Select only server-owned component candidates.",
            status="active",
        )
    )
    for index, (run_id, status) in enumerate(
        (("baseline-run", "complete"), ("candidate-run", "failed"))
    ):
        snapshot = runtime.begin_run(
            "planning-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"deterministic-{index}",
                condition="planning-fixture",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    paper_dir = runtime.projects_root / "planning-project" / "papers" / "paper-one"
    paper_dir.mkdir()
    (paper_dir / "main.md").write_text("# Planned evidence\n", encoding="utf-8")
    runtime.register_paper(
        "planning-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="planning-project",
            title="Planned evidence paper",
            date="2026-09-06",
            provider="scripted",
            model="deterministic",
            condition="planning-fixture",
            task="surface-planning",
            seed=0,
            stage=18,
            status="draft",
            evidence_scope="engineering-only",
            files={"Manuscript": "main.md"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    return runtime


def _catalog(runtime: ProjectRuntime) -> SurfaceCandidateCatalog:
    resolver = WorkspaceIntentResolver(runtime)
    quick = resolver.quick_catalog("planning-project")
    resolution = resolver.resolve(
        FreeQuestionRequest(
            project_id="planning-project",
            snapshot_revision=quick.snapshot.snapshot_revision,
            snapshot_sha256=quick.snapshot.snapshot_sha256,
            question="比较 baseline-run 和 candidate-run",
        )
    )
    assert resolution.intent is not None
    return SurfaceCandidateFactory(runtime).build(resolution.intent)


def _plan(catalog: SurfaceCandidateCatalog, candidate_ids: list[str]) -> SurfacePlan:
    by_id = {item.candidate_id: item for item in catalog.candidates}
    return SurfacePlan(
        project_id=catalog.intent.snapshot.project_id,
        snapshot_revision=catalog.intent.snapshot.snapshot_revision,
        snapshot_sha256=catalog.intent.snapshot.snapshot_sha256,
        intent_fingerprint=catalog.intent.fingerprint,
        catalog_fingerprint=catalog.fingerprint,
        entries=[
            SurfacePlanEntry(
                candidate_id=candidate_id,
                group=by_id[candidate_id].allowed_groups[0],
            )
            for candidate_id in candidate_ids
        ],
    )


def test_candidate_catalog_is_stable_and_provider_descriptors_are_data_free(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    first = _catalog(runtime)
    repeated = _catalog(runtime)

    assert first.fingerprint == repeated.fingerprint
    assert first == repeated
    assert any(item.component.component.value == "RunComparisonPanel" for item in first.candidates)
    for descriptor in first.descriptors():
        payload = descriptor.model_dump(mode="json")
        assert "data" not in payload
        assert "title" not in payload
        assert "actions" not in payload
        assert "proposal" not in payload
        assert descriptor.evidence_ref_ids


def test_large_project_candidate_catalog_is_bounded_without_losing_summaries(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    snapshot = runtime.open("planning-project")
    for paper_index in range(2, 22):
        directory_name = f"paper-{paper_index:02d}"
        paper_dir = runtime.projects_root / "planning-project/papers" / directory_name
        paper_dir.mkdir()
        files: dict[str, str] = {}
        for artifact_index in range(4):
            name = f"artifact-{artifact_index}.md"
            (paper_dir / name).write_text("# Bounded artifact\n", encoding="utf-8")
            files[f"Artifact {artifact_index}"] = name
        snapshot = runtime.register_paper(
            "planning-project",
            PaperManifest(
                paper_id=directory_name,
                project_id="planning-project",
                title=f"Bounded paper {paper_index}",
                date="2026-09-11",
                provider="scripted",
                model="deterministic",
                condition="candidate-bound",
                task="surface-planning",
                seed=paper_index,
                stage=18,
                status="draft",
                evidence_scope="engineering-only",
                files=files,
            ),
            directory_name=directory_name,
            expected_revision=snapshot.revision,
        )
    resolver = WorkspaceIntentResolver(runtime)
    quick = resolver.quick_catalog("planning-project")
    descriptor = next(item for item in quick.intents if item.goal is IntentGoal.PROGRESS_REVIEW)
    resolution = resolver.resolve(
        QuickIntentRequest(
            project_id="planning-project",
            snapshot_revision=quick.snapshot.snapshot_revision,
            snapshot_sha256=quick.snapshot.snapshot_sha256,
            quick_intent_id=descriptor.quick_intent_id,
        )
    )
    assert resolution.intent is not None

    catalog = SurfaceCandidateFactory(runtime).build(resolution.intent)

    assert len(catalog.candidates) == 64
    components = {item.component.component for item in catalog.candidates}
    assert TrustedComponent.PROJECT_PROGRESS_BOARD in components
    assert TrustedComponent.EVIDENCE_GRAPH in components
    assert TrustedComponent.PROJECT_SUMMARY_CARD in components
    assert TrustedComponent.RUN_STAGE_EXPLORER in components


def test_materialization_reorders_but_does_not_rewrite_trusted_components(
    tmp_path: Path,
) -> None:
    catalog = _catalog(_runtime(tmp_path))
    comparison = next(
        item
        for item in catalog.candidates
        if item.component.component.value == "RunComparisonPanel"
    )
    progress = next(
        item
        for item in catalog.candidates
        if item.component.component.value == "ProjectProgressBoard"
    )
    plan = _plan(catalog, [comparison.candidate_id, progress.candidate_id])

    materialized = materialize_surface_plan(catalog, plan)

    assert materialized.plan.fingerprint == plan.fingerprint
    assert materialized.surface.purpose == "generated_workspace"
    assert [item.component for item in materialized.surface.components] == [
        comparison.component.component,
        progress.component.component,
    ]
    assert materialized.surface.components[0] == comparison.component
    assert materialized.surface.components[1] == progress.component
    assert materialized.surface.project_id == catalog.intent.snapshot.project_id


def test_plan_round_trip_and_fingerprint_are_stable(tmp_path: Path) -> None:
    catalog = _catalog(_runtime(tmp_path))
    candidate = catalog.candidates[-1]
    plan = _plan(catalog, [candidate.candidate_id])

    restored = validate_surface_plan(plan.model_dump(mode="json"))

    assert restored == plan
    assert restored.fingerprint == plan.fingerprint


def test_plan_rejects_unknown_duplicate_or_cross_candidate_selection(tmp_path: Path) -> None:
    catalog = _catalog(_runtime(tmp_path))
    first = next(item for item in catalog.candidates if len(item.component.evidence_ref_ids) == 1)
    second = next(
        item
        for item in catalog.candidates
        if set(item.component.evidence_ref_ids) - set(first.component.evidence_ref_ids)
    )
    plan = _plan(catalog, [first.candidate_id])

    payload = plan.model_dump(mode="json")
    payload["entries"][0]["candidate_id"] = "candidate-does-not-exist"
    with pytest.raises(StaleSurfacePlanError):
        materialize_surface_plan(catalog, payload)

    payload = plan.model_dump(mode="json")
    payload["entries"].append(payload["entries"][0])
    with pytest.raises(ValidationError):
        validate_surface_plan(payload)

    foreign_ref = next(
        ref_id
        for ref_id in second.component.evidence_ref_ids
        if ref_id not in first.component.evidence_ref_ids
    )
    payload = plan.model_dump(mode="json")
    payload["entries"][0]["focus_ref_ids"] = [foreign_ref]
    with pytest.raises(ValueError, match="outside its candidate"):
        materialize_surface_plan(catalog, payload)


@pytest.mark.parametrize("field", ["html", "url", "command", "component", "data", "actions"])
def test_plan_schema_rejects_content_or_execution_fields(tmp_path: Path, field: str) -> None:
    catalog = _catalog(_runtime(tmp_path))
    plan = _plan(catalog, [catalog.candidates[0].candidate_id])
    payload = plan.model_dump(mode="json")
    payload["entries"][0][field] = "untrusted"

    with pytest.raises(ValidationError):
        validate_surface_plan(payload)


def test_plan_binding_rejects_catalog_or_snapshot_drift(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    catalog = _catalog(runtime)
    plan = _plan(catalog, [catalog.candidates[0].candidate_id])
    payload = plan.model_dump(mode="json")
    payload["catalog_fingerprint"] = "0" * 64
    with pytest.raises(StaleSurfacePlanError):
        materialize_surface_plan(catalog, payload)

    snapshot = runtime.open("planning-project")
    runtime.update(
        "planning-project",
        expected_revision=snapshot.revision,
        status="paused",
    )
    with pytest.raises(StaleSurfacePlanError):
        SurfaceCandidateFactory(runtime).build(catalog.intent)


def test_candidate_group_is_closed_per_server_policy(tmp_path: Path) -> None:
    catalog = _catalog(_runtime(tmp_path))
    evidence_candidate = next(
        item
        for item in catalog.candidates
        if item.component.component.value == "ProjectProgressBoard"
    )
    assert PlanGroup.ATTENTION not in evidence_candidate.allowed_groups
    plan = _plan(catalog, [evidence_candidate.candidate_id])
    payload = plan.model_dump(mode="json")
    payload["entries"][0]["group"] = "attention"

    with pytest.raises(ValueError, match="group is not allowed"):
        materialize_surface_plan(catalog, payload)

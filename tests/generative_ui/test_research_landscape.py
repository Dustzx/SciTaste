from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    FreeQuestionRequest,
    IntentGoal,
    QuickIntentRequest,
    ResearchLandscapeArtifact,
    ResearchLandscapeQuery,
    TrustedComponent,
    WorkspaceGenerationRequest,
    WorkspaceGenerationService,
    WorkspaceIntentResolver,
    WorkspaceSurfaceFactory,
    load_research_landscape_source,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "docs/research/data/autoresearch_evaluation_landscape_v1.yaml"
)


def _runtime(tmp_path: Path, *, projection: bool = True) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="landscape-project",
            title="Research landscape project",
            research_direction="Understand comparisons before fixing experiments.",
            status="active",
        )
    )
    if not projection:
        return runtime
    run_id = "research-landscape-v1"
    artifact = f"runs/{run_id}/synthesis/RESULT.json"
    snapshot = runtime.begin_run(
        "landscape-project",
        ProjectRun(
            run_id=run_id,
            provider="scitaste-native",
            model="deterministic-synthesis",
            condition="literature-map",
            seed=0,
            status="complete",
            evidence_scope="literature-and-protocol-design-only",
            artifact=artifact,
            generative_ui_projection="autoresearch-evaluation-landscape-v1",
        ),
        expected_revision=snapshot.revision,
    )
    path = runtime.projects_root / "landscape-project" / artifact
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(load_research_landscape_source(_SOURCE).model_dump(mode="json")),
        encoding="utf-8",
    )
    return runtime


def test_landscape_source_is_strict_closed_and_not_an_experiment_result() -> None:
    artifact = load_research_landscape_source(_SOURCE)

    assert artifact.synthesis_scope == "literature-and-protocol-design-only"
    assert artifact.freeze_decision == "hold"
    assert len(artifact.works) == 11
    assert {item.role for item in artifact.works} == {"primary", "anchor", "context"}
    assert not any(item.readiness == "formal" for item in artifact.comparison_candidates)

    payload = artifact.model_dump(mode="json")
    payload["works"][0]["stage_ids"].append("invented-stage")
    with pytest.raises(ValidationError, match="unknown lifecycle stage"):
        ResearchLandscapeArtifact.model_validate(payload)


def test_registered_landscape_builds_one_content_bound_trusted_map(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    document = WorkspaceSurfaceFactory(runtime).build(
        ResearchLandscapeQuery(project_id="landscape-project")
    )

    assert document.renderer.catalog_version == "scitaste-trusted-components-v3"
    assert [item.renderer for item in document.renderer.components] == [
        TrustedComponent.RESEARCH_LANDSCAPE_MAP
    ]
    component = document.renderer.components[0]
    assert component.data["freeze_decision"] == "hold"
    assert len(component.data["support_ref_ids"]) == 2
    assert {item.kind for item in document.renderer.snapshot.evidence_refs} >= {
        "project_manifest",
        "run_record",
    }


def test_absent_landscape_is_explicit_and_not_offered_as_an_intent(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, projection=False)

    document = WorkspaceSurfaceFactory(runtime).build(
        ResearchLandscapeQuery(project_id="landscape-project")
    )
    catalog = WorkspaceIntentResolver(runtime).quick_catalog("landscape-project")

    assert document.renderer.components[0].renderer == TrustedComponent.AVAILABILITY_NOTICE
    assert document.renderer.components[0].data["subject"] == "research_landscape"
    assert IntentGoal.RESEARCH_LANDSCAPE_REVIEW not in {item.goal for item in catalog.intents}


def test_landscape_quick_and_free_intents_resolve_to_registered_map(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    resolver = WorkspaceIntentResolver(runtime)
    catalog = resolver.quick_catalog("landscape-project")
    descriptor = next(
        item for item in catalog.intents if item.goal == IntentGoal.RESEARCH_LANDSCAPE_REVIEW
    )

    resolution = resolver.resolve(
        FreeQuestionRequest(
            project_id="landscape-project",
            snapshot_revision=catalog.snapshot.snapshot_revision,
            snapshot_sha256=catalog.snapshot.snapshot_sha256,
            question="领域相关工作的实验如何对比?",
        )
    )

    assert descriptor.quick_intent_id == "review-research-evaluation-landscape"
    assert resolution.status == "resolved"
    assert resolution.intent is not None
    assert resolution.intent.goal == IntentGoal.RESEARCH_LANDSCAPE_REVIEW

    generated = WorkspaceGenerationService(runtime).generate(
        WorkspaceGenerationRequest(
            quick_catalog_fingerprint=catalog.fingerprint,
            intent_request=QuickIntentRequest(
                project_id="landscape-project",
                snapshot_revision=catalog.snapshot.snapshot_revision,
                snapshot_sha256=catalog.snapshot.snapshot_sha256,
                quick_intent_id=descriptor.quick_intent_id,
            ),
        )
    )
    assert generated.status == "generated"
    assert generated.renderer is not None
    assert generated.renderer.components[0].renderer == TrustedComponent.RESEARCH_LANDSCAPE_MAP


def test_landscape_artifact_must_remain_inside_declaring_run(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, projection=False)
    snapshot = runtime.open("landscape-project")
    runtime.begin_run(
        "landscape-project",
        ProjectRun(
            run_id="escaping-landscape",
            provider="scripted",
            model="deterministic",
            condition="invalid",
            seed=0,
            status="complete",
            evidence_scope="engineering-only",
            artifact="PROJECT.json",
            generative_ui_projection="autoresearch-evaluation-landscape-v1",
        ),
        expected_revision=snapshot.revision,
    )

    with pytest.raises(ValueError, match="escaped its run"):
        WorkspaceSurfaceFactory(runtime).build(
            ResearchLandscapeQuery(project_id="landscape-project")
        )

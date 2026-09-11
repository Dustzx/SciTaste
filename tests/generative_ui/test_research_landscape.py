from __future__ import annotations

import json
import shutil
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
    / "docs/research/data/autoresearch_evaluation_landscape_v6.yaml"
)
_V5_SOURCE = _SOURCE.with_name("autoresearch_evaluation_landscape_v5.yaml")
_LEGACY_SOURCE = _SOURCE.with_name("autoresearch_evaluation_landscape_v1.yaml")


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
            generative_ui_projection="autoresearch-evaluation-landscape-v6",
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
    assert artifact.schema_version == "1.5"
    assert artifact.corpus_scope == (
        "accepted-method-census-fourth-screen-and-targeted-evaluation-resources"
    )
    assert artifact.prevalence_inference == "not-estimable"
    assert len(artifact.works) == 45
    assert {item.role for item in artifact.works} == {"primary", "anchor", "context"}
    assert {item.contribution_type for item in artifact.works} == {
        "method",
        "benchmark",
        "hybrid",
    }
    assert sum(item.contribution_type == "method" for item in artifact.works) == 16
    assert sum(item.contribution_type == "hybrid" for item in artifact.works) == 6
    assert sum(item.contribution_type == "benchmark" for item in artifact.works) == 23
    assert {item.publication_status for item in artifact.works} == {"accepted-archival"}
    assert not any(item.readiness == "formal" for item in artifact.comparison_candidates)
    assert {"agent-laboratory", "dolphin", "code-scientist", "ai-researcher"}.issubset(
        {item.candidate_id for item in artifact.comparison_candidates}
    )
    headline = {
        item.candidate_id
        for item in artifact.comparison_candidates
        if item.evaluation_track == "headline-system"
    }
    assert headline == {
        "scitaste-native",
        "direct-agent",
        "mlr-agent",
        "agent-laboratory",
        "ai-researcher",
        "tiny-scientist",
    }
    assert {
        item.candidate_id
        for item in artifact.comparison_candidates
        if item.publication_status == "preprint-only"
    } == {"ai-scientist-v2", "autoresearchclaw"}
    census = next(item for item in artifact.planning_gates if item.gate_id == "census")
    assert census.state == "candidate"

    system_sources = {
        item.work_id
        for item in artifact.works
        if item.contribution_type in {"method", "hybrid"} and "system" in item.bundled_artifacts
    }
    evaluation_sources = {
        item.work_id
        for item in artifact.works
        if item.contribution_type == "benchmark"
        or (
            item.contribution_type == "hybrid"
            and {"benchmark", "judge", "dataset"} & set(item.bundled_artifacts)
        )
    }
    assert len(system_sources) == 22
    assert len(evaluation_sources) == 29
    assert system_sources & evaluation_sources == {
        "ai-researcher",
        "empirical-outcome-prediction",
        "moose-chem",
        "research-town",
        "mm-agent",
        "safe-scientist",
    }

    payload = artifact.model_dump(mode="json")
    payload["works"][0]["stage_ids"].append("invented-stage")
    with pytest.raises(ValidationError, match="unknown lifecycle stage"):
        ResearchLandscapeArtifact.model_validate(payload)

    payload = artifact.model_dump(mode="json")
    payload["works"][0]["contribution_type"] = "unclassified"
    with pytest.raises(ValidationError, match="explicit contribution type"):
        ResearchLandscapeArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("work_id", "update", "message"),
    [
        (
            "mlr-bench",
            {"experiment_role": "system-comparator"},
            "only a method or hybrid system can be a system comparator",
        ),
        (
            "cycle-researcher",
            {"experiment_role": "task-source"},
            "only a benchmark or hybrid benchmark can be a task source",
        ),
        (
            "cycle-researcher",
            {"bundled_artifacts": ["dataset"]},
            "a method contribution must bundle a system",
        ),
        (
            "ai-researcher",
            {"bundled_artifacts": ["system"]},
            "a hybrid contribution must bundle a system and evaluation infrastructure",
        ),
    ],
)
def test_contribution_type_cannot_impersonate_an_experiment_role(
    work_id: str,
    update: dict[str, object],
    message: str,
) -> None:
    payload = load_research_landscape_source(_SOURCE).model_dump(mode="json")
    work = next(item for item in payload["works"] if item["work_id"] == work_id)
    work.update(update)

    with pytest.raises(ValidationError, match=message):
        ResearchLandscapeArtifact.model_validate(payload)


def test_ready_landscape_requires_both_formal_experiment_tracks() -> None:
    payload = load_research_landscape_source(_SOURCE).model_dump(mode="json")
    payload["freeze_decision"] = "ready"
    for gate in payload["planning_gates"]:
        gate["state"] = "ready"

    with pytest.raises(ValidationError, match="formal system and evaluation tracks"):
        ResearchLandscapeArtifact.model_validate(payload)


def test_preprint_system_cannot_enter_the_headline_track() -> None:
    payload = load_research_landscape_source(_SOURCE).model_dump(mode="json")
    candidate = next(
        item
        for item in payload["comparison_candidates"]
        if item["candidate_id"] == "ai-scientist-v2"
    )
    candidate["evaluation_track"] = "headline-system"

    with pytest.raises(ValidationError, match="headline system must be accepted"):
        ResearchLandscapeArtifact.model_validate(payload)


def test_v6_requires_two_accepted_external_headline_candidates() -> None:
    payload = load_research_landscape_source(_SOURCE).model_dump(mode="json")
    for candidate in payload["comparison_candidates"]:
        if (
            candidate["evaluation_track"] == "headline-system"
            and candidate["publication_status"] == "accepted-archival"
        ):
            candidate["evaluation_track"] = "sensitivity-system"

    with pytest.raises(ValidationError, match="two accepted external headline"):
        ResearchLandscapeArtifact.model_validate(payload)


def test_legacy_landscape_remains_readable_but_explicitly_unclassified() -> None:
    artifact = load_research_landscape_source(_LEGACY_SOURCE)

    assert artifact.schema_version == "1.0"
    assert artifact.artifact_kind == "autoresearch-evaluation-landscape-v1"
    assert {item.contribution_type for item in artifact.works} == {"unclassified"}


def test_v6_overlay_is_bound_to_the_exact_v5_base(tmp_path: Path) -> None:
    overlay = tmp_path / _SOURCE.name
    base = tmp_path / _V5_SOURCE.name
    shutil.copyfile(_SOURCE, overlay)
    shutil.copyfile(_V5_SOURCE, base)
    base.write_text(base.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="base hash has drifted"):
        load_research_landscape_source(overlay)


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
    assert [item.renderer for item in generated.renderer.components] == [
        TrustedComponent.RESEARCH_LANDSCAPE_MAP
    ]


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
            generative_ui_projection="autoresearch-evaluation-landscape-v6",
        ),
        expected_revision=snapshot.revision,
    )

    with pytest.raises(ValueError, match="escaped its run"):
        WorkspaceSurfaceFactory(runtime).build(
            ResearchLandscapeQuery(project_id="landscape-project")
        )

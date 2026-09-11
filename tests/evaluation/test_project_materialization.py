from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.cli import main
from scitaste.evaluation import (
    prepare_project_evaluation,
    publish_project_evaluation,
)
from scitaste.generative_ui import (
    EvidenceKind,
    ProjectProgressQuery,
    TrustedComponent,
    WorkspaceSurfaceFactory,
)
from scitaste.project import ProjectManifest, ProjectRuntime

CORPUS = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")
PROPOSALS = {
    "deepseek-v41-prepilot": (
        Path("configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml"),
        50,
    ),
    "zhipu-glm53-prepilot": (
        Path("configs/evaluation/prelaunch/zhipu_glm53flash_pilot_v1.yaml"),
        5,
    ),
    "qwen3vl2b-robustness": (
        Path("configs/evaluation/prelaunch/qwen3vl2b_8x3090_robustness_v1.yaml"),
        6,
    ),
}


def _runtime(tmp_path: Path) -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="evaluation-project",
            title="Evaluation project",
            research_direction="Own exact experiment resources before execution.",
            status="active",
        )
    )
    return runtime, snapshot


def _prepare(evaluation_id: str):
    manifest, _ = PROPOSALS[evaluation_id]
    return prepare_project_evaluation(
        project_id="evaluation-project",
        evaluation_id=evaluation_id,
        manifest_path=manifest,
        resource_corpus_path=CORPUS,
        source_root=Path("."),
        evidence_root=Path("."),
    )


def test_api_and_gpu_proposals_prepare_exact_no_run_resources() -> None:
    prepared = {evaluation_id: _prepare(evaluation_id) for evaluation_id in PROPOSALS}

    for evaluation_id, (_, cells) in PROPOSALS.items():
        bundle = prepared[evaluation_id].bundle
        assert bundle.planned_cells == cells
        assert bundle.status == "blocked"
        assert bundle.ready_for_author_review is False
        assert bundle.execution_authorized is False
        assert bundle.no_execution_performed is True
        assert set(bundle.files) == {
            "prelaunch_manifest",
            "resource_corpus",
            "gate_report",
            "critic_report",
            "cell_plan",
        }

    assert prepared["deepseek-v41-prepilot"].bundle.api_resources == (
        "deepseek/deepseek-flash@DeepSeek-V4.1-Flash",
    )
    assert prepared["zhipu-glm53-prepilot"].bundle.api_resources == (
        "zhipu/glm-5.3-flash@GLM-5.3-Flash",
    )
    gpu = prepared["qwen3vl2b-robustness"].bundle.gpu_resources
    assert len(gpu) == 1
    assert gpu[0].startswith("3090-2/8xNVIDIA GeForce RTX 3090/qwen3-vl-2b-instruct")


def test_project_publication_is_atomic_content_bound_and_visible_on_home(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _runtime(tmp_path)
    prepared = _prepare("deepseek-v41-prepilot")

    snapshot = publish_project_evaluation(
        runtime,
        prepared,
        expected_revision=snapshot.revision,
        select=True,
    )

    assert snapshot.revision == 2
    assert snapshot.manifest.current_evaluation == "deepseek-v41-prepilot"
    assert snapshot.manifest.evaluations[0].planned_cells == 50
    assert snapshot.manifest.evaluations[0].execution_authorized is False
    assert snapshot.current_evaluation_locator == (
        "projects/evaluation-project/evaluations/deepseek-v41-prepilot"
    )
    assert snapshot.warnings == []
    evaluation_dir = runtime.projects_root / "evaluation-project/evaluations/deepseek-v41-prepilot"
    assert {item.name for item in evaluation_dir.iterdir()} == {
        "PRELAUNCH.yaml",
        "RESOURCE_CORPUS.yaml",
        "GATE_REPORT.json",
        "CRITIC_REPORT.json",
        "CELL_PLAN.json",
        "EVALUATION.json",
    }

    surface = WorkspaceSurfaceFactory(runtime).build(
        ProjectProgressQuery(project_id="evaluation-project")
    )
    progress = next(
        item
        for item in surface.renderer.components
        if item.renderer == TrustedComponent.PROJECT_PROGRESS_BOARD
    ).data
    assert progress["counts"]["evaluations_registered"] == 1
    assert progress["evaluations"][0]["planned_cells"] == 50
    assert progress["evaluations"][0]["no_execution_performed"] is True
    reference = next(
        item
        for item in surface.renderer.snapshot.evidence_refs
        if item.evidence_id == progress["evaluations"][0]["evaluation_ref_id"]
    )
    assert reference.kind == EvidenceKind.EVALUATION

    (evaluation_dir / "GATE_REPORT.json").write_text("{}\n", encoding="utf-8")
    drifted = runtime.open("evaluation-project")
    assert drifted.warnings == [
        "registered evaluation is missing or invalid: deepseek-v41-prepilot"
    ]
    with pytest.raises(ValueError, match="failed integrity validation"):
        WorkspaceSurfaceFactory(runtime).build(
            ProjectProgressQuery(project_id="evaluation-project")
        )
    with pytest.raises(ValueError, match="mismatch"):
        runtime.select_evaluation(
            "evaluation-project",
            "deepseek-v41-prepilot",
            expected_revision=drifted.revision,
        )


def test_tampered_payload_is_rejected_without_publishing_directory(tmp_path: Path) -> None:
    runtime, snapshot = _runtime(tmp_path)
    prepared = _prepare("qwen3vl2b-robustness")
    tampered = dict(prepared.artifact_payloads)
    tampered["CELL_PLAN.json"] += b"tamper"

    with pytest.raises(ValueError, match="size mismatch"):
        runtime.publish_evaluation(
            "evaluation-project",
            prepared.bundle,
            artifact_payloads=tampered,
            expected_revision=snapshot.revision,
        )
    assert not (
        runtime.projects_root / "evaluation-project/evaluations/qwen3vl2b-robustness"
    ).exists()
    assert runtime.open("evaluation-project").revision == 0


def test_project_evaluation_cli_dry_run_then_registers_without_execution(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id="evaluation-project",
            title="Evaluation project",
            research_direction="Freeze exact resources.",
            status="active",
        )
    )
    arguments = [
        "project",
        "evaluation",
        "register-prelaunch",
        "--project-id",
        "evaluation-project",
        "--evaluation-id",
        "zhipu-glm53-prepilot",
        "--manifest",
        str(PROPOSALS["zhipu-glm53-prepilot"][0]),
        "--resource-corpus",
        str(CORPUS),
        "--source-root",
        ".",
        "--evidence-root",
        ".",
        "--expected-revision",
        "0",
        "--outputs-root",
        str(outputs),
    ]

    assert main([*arguments, "--dry-run"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["bundle"]["planned_cells"] == 5
    assert dry_run["no_execution_performed"] is True
    assert runtime.open("evaluation-project").manifest.evaluations == []

    assert main([*arguments, "--select"]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["project_revision"] == 2
    assert registered["execution_authorized"] is False
    assert registered["selected"] is True
    assert runtime.open("evaluation-project").manifest.current_evaluation == (
        "zhipu-glm53-prepilot"
    )

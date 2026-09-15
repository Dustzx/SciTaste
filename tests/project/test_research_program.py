from __future__ import annotations

from pathlib import Path

import pytest

import scitaste.project.research_program as research_program_module
from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.project.research_program import (
    ResearchProgramRunStatus,
    ResearchProgramRuntime,
    ResearchProgramTransitionDisposition,
)

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = (
    ROOT / "configs/evaluation/programs/iclr2027_scitaste_complete_autoresearch_program_v3.yaml"
)
CAPABILITY_PROGRAM = (
    ROOT
    / "configs/evaluation/programs/"
    / "iclr2027_scitaste_capability_driven_autoresearch_program_v4.yaml"
)
MODEL_INVENTORY = ROOT / "configs/resources/assets/model_role_inventory_v1.yaml"


def _runtime(tmp_path: Path, project_id: str = "program-project") -> ResearchProgramRuntime:
    outputs = tmp_path / "outputs"
    ProjectRuntime(outputs).create(
        ProjectManifest(
            project_id=project_id,
            title="Complete research program",
            research_direction="Exercise a complete idea-to-reviewed-paper lifecycle.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    return ResearchProgramRuntime(outputs)


def _initialize(runtime: ResearchProgramRuntime, project_id: str = "program-project"):
    return runtime.initialize(
        project_id=project_id,
        program_path=PROGRAM,
        model_inventory_path=MODEL_INVENTORY,
        expected_revision=0,
    )


def _artifacts(runtime: ResearchProgramRuntime, status) -> dict[str, str]:
    project_root = runtime.project_runtime.projects_root / status.state.project_id
    locators: dict[str, str] = {}
    for artifact_id in status.required_artifact_ids:
        locator = (
            f"program-evidence/{status.state.sequence:03d}-"
            f"{status.state.current_phase_id}/{artifact_id}.json"
        )
        path = project_root / locator
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"completed":true}\n', encoding="utf-8")
        locators[artifact_id] = locator
    return locators


def _complete_current(runtime: ResearchProgramRuntime, status, **review_options):
    return runtime.advance(
        project_id=status.state.project_id,
        program_id=status.state.program_id,
        artifact_locators=_artifacts(runtime, status),
        attest_artifacts_complete=True,
        **review_options,
    )


def test_initialize_binds_v3_and_records_block_resume_without_execution(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    initialized = _initialize(runtime)

    assert initialized.state.current_phase_id == "task-acquisition-proposed"
    assert initialized.contract.model_selection_gate == "task-excluded-conformance"
    assert initialized.contract.planning_is_scientific_result is False
    assert initialized.contract.blocked_external_system_ids == (
        "mlr-agent",
        "agent-laboratory",
        "deep-scientist",
    )
    project = runtime.project_runtime.open("program-project")
    run = next(
        item for item in project.manifest.runs if item.run_id == initialized.state.program_id
    )
    assert run.artifact == "program/STATE.json"
    assert run.status == "running"

    blocked = runtime.advance(
        project_id="program-project",
        program_id=initialized.state.program_id,
        artifact_locators={},
        disposition=ResearchProgramTransitionDisposition.BLOCKED,
        reason="license evidence is not yet available",
    )
    assert blocked.state.status is ResearchProgramRunStatus.BLOCKED
    assert blocked.required_action == "resolve-blocker-then-resume"
    assert blocked.state.current_phase_id == "task-acquisition-proposed"

    resumed = runtime.resume(
        project_id="program-project",
        program_id=blocked.state.program_id,
    )
    advanced = _complete_current(runtime, resumed)
    assert advanced.state.current_phase_id == "acquired-quarantined"
    assert advanced.state.sequence == 3
    transition_path = (
        runtime.project_runtime.projects_root
        / "program-project/runs"
        / advanced.state.program_id
        / "program"
        / advanced.state.transition_locators[-1]
    )
    transition = transition_path.read_text(encoding="utf-8")
    assert '"controller_launched_api": false' in transition
    assert '"controller_launched_gpu": false' in transition
    assert '"controller_launched_download": false' in transition


def test_initialize_binds_capability_driven_v4_without_selecting_qwen2b(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, "capability-program")
    initialized = runtime.initialize(
        project_id="capability-program",
        program_path=CAPABILITY_PROGRAM,
        model_inventory_path=MODEL_INVENTORY,
        expected_revision=0,
    )

    assert initialized.contract.source_program_schema_version == "4.0"
    assert initialized.contract.model_selection_gate == "task-excluded-conformance"
    project = runtime.project_runtime.open("capability-program")
    run = next(
        item for item in project.manifest.runs if item.run_id == initialized.state.program_id
    )
    assert run.condition == "complete-autoresearch-program-v4"
    assert run.model == "task-excluded-selection-pending"


def test_review_disagreement_adjudicates_and_revision_can_return_to_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        research_program_module,
        "_validate_phase_artifacts",
        lambda *_args, **kwargs: research_program_module._PHASE_SEMANTIC_VALIDATORS[
            kwargs["phase_id"]
        ][:1],
    )
    runtime = _runtime(tmp_path)
    status = _initialize(runtime)

    while status.state.current_phase_id != "dual-ai-review":
        status = _complete_current(runtime, status)
    status = _complete_current(runtime, status, review_outcome="disagreement")
    assert status.state.current_phase_id == "ai-adjudication"
    status = _complete_current(runtime, status)
    assert status.state.current_phase_id == "review-driven-revision"
    status = _complete_current(runtime, status)
    assert status.state.current_phase_id == "final-ai-review-and-package-freeze"

    status = _complete_current(
        runtime,
        status,
        review_outcome="revision_required",
        revision_target="development-execution",
    )
    assert status.state.current_phase_id == "development-execution"
    assert status.state.final_review_accepted is False

    while status.state.current_phase_id != "dual-ai-review":
        status = _complete_current(runtime, status)
    status = _complete_current(runtime, status, review_outcome="agreement")
    status = _complete_current(runtime, status)
    status = _complete_current(runtime, status, review_outcome="accepted")
    assert status.state.current_phase_id == "complete"
    assert status.state.status is ResearchProgramRunStatus.ACTIVE
    assert status.state.final_review_accepted is True

    status = _complete_current(runtime, status)
    assert status.state.status is ResearchProgramRunStatus.COMPLETE
    assert status.state.next_actionable_phase_id is None
    assert status.required_action == "none"
    assert status.history_verified is True


def test_bound_artifact_drift_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    initialized = _initialize(runtime)
    artifacts = _artifacts(runtime, initialized)
    status = runtime.advance(
        project_id="program-project",
        program_id=initialized.state.program_id,
        artifact_locators=artifacts,
        attest_artifacts_complete=True,
    )
    first = (
        runtime.project_runtime.projects_root / "program-project" / next(iter(artifacts.values()))
    )
    first.write_text('{"completed":false}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="artifact drifted"):
        runtime.status(project_id="program-project", program_id=status.state.program_id)


@pytest.mark.parametrize(
    "target_phase",
    ["models-and-systems-frozen", "hidden-scoring", "dual-ai-review"],
)
def test_title_critical_phases_reject_untyped_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_phase: str,
) -> None:
    validate = research_program_module._validate_phase_artifacts

    def validate_target_only(*args, **kwargs):
        phase_id = kwargs["phase_id"]
        if phase_id == target_phase:
            return validate(*args, **kwargs)
        return research_program_module._PHASE_SEMANTIC_VALIDATORS[phase_id][:1]

    monkeypatch.setattr(
        research_program_module,
        "_validate_phase_artifacts",
        validate_target_only,
    )
    runtime = _runtime(tmp_path)
    status = _initialize(runtime)
    while status.state.current_phase_id != target_phase:
        status = _complete_current(runtime, status)

    options = {"review_outcome": "agreement"} if target_phase == "dual-ai-review" else {}
    blocked = _complete_current(runtime, status, **options)
    assert blocked.state.status is ResearchProgramRunStatus.BLOCKED
    transition_path = (
        runtime.project_runtime.projects_root
        / "program-project/runs"
        / blocked.state.program_id
        / "program"
        / blocked.state.transition_locators[-1]
    )
    assert f"unsupported_validator:{target_phase}" in transition_path.read_text()

    unchanged = runtime.status(
        project_id="program-project",
        program_id=status.state.program_id,
    )
    assert unchanged.state.sequence == status.state.sequence + 1
    assert unchanged.state.current_phase_id == target_phase

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scitaste.benchmark.manuscript as manuscript
from scitaste.cli import main
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.state.persistence import StateStore


def test_full_workflow_applies_one_condition_across_every_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    base = load_full_workflow_config("configs/workflows/full_offline_native_conditions_v1.yaml")
    config = base.model_copy(
        update={
            "project_id": "native-condition-full-test",
            "paper_id": "native-condition-full-paper",
            "paper_directory": "native-condition-full-paper",
        }
    )

    result = FullWorkflow(seed=7).run(
        config,
        outputs_root=tmp_path / "outputs",
        run_id="full-seed-07",
    )

    condition = result["native_condition"]
    assert condition is not None
    assert condition["condition_id"] == "full-scitaste"
    assert condition["components"] == {
        "utility_policy_enabled": True,
        "knowledge_retrieval_enabled": True,
        "taste_retrieval": "matched",
        "taste_critics_enabled": True,
        "integrity_gates_enabled": True,
    }
    assert condition["integrity_gates_invariant"] is True
    run_root = tmp_path / "outputs/projects/native-condition-full-test/runs/full-seed-07"
    state = StateStore(run_root / "stages/figure").load()
    assert any(decision.retrieved_taste_cases for decision in state.decision_history)
    search = next(
        decision
        for decision in state.decision_history
        if decision.selected_action.action_id == "discovery-search"
    )
    assert search.actual_outcome is not None
    assert search.actual_outcome["data"]["result_basis"] == "knowledge-library-retrieval"
    assert result["stages"]["communication"]["retrieved_taste_case_ids"] == []
    assert result["stages"]["figure"]["final_blocking_findings"] == 0


@pytest.mark.parametrize(
    ("condition_id", "knowledge_enabled", "taste_context_enabled"),
    [
        ("native-base", False, False),
        ("native-knowledge", True, False),
        ("native-taste", False, True),
        ("native-critics", False, False),
        ("mismatched-taste-placebo", True, True),
    ],
)
def test_native_component_conditions_execute_without_disabling_integrity(
    tmp_path: Path,
    monkeypatch,
    condition_id: str,
    knowledge_enabled: bool,
    taste_context_enabled: bool,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    base = load_full_workflow_config("configs/workflows/full_offline_native_conditions_v1.yaml")
    safe_id = condition_id.replace("-", "_")
    config = base.model_copy(
        update={
            "project_id": f"native-condition-{condition_id}-test",
            "condition": condition_id,
            "paper_id": f"native-condition-{condition_id}-paper",
            "paper_directory": f"native-condition-{condition_id}-paper",
        }
    )
    result = FullWorkflow(seed=7).run(
        config,
        outputs_root=tmp_path / "outputs",
        run_id=f"{safe_id}-seed-07",
    )

    condition = result["native_condition"]
    assert condition is not None
    assert condition["condition_id"] == condition_id
    assert condition["taste_context_enabled"] is taste_context_enabled
    assert condition["knowledge_retrieval_enabled"] is knowledge_enabled
    assert condition["components"]["integrity_gates_enabled"] is True
    run_root = (
        tmp_path
        / "outputs"
        / "projects"
        / f"native-condition-{condition_id}-test"
        / "runs"
        / f"{safe_id}-seed-07"
    )
    state = StateStore(run_root / "stages/figure").load()
    search = next(
        decision
        for decision in state.decision_history
        if decision.selected_action.action_id == "discovery-search"
    )
    assert search.actual_outcome is not None
    if knowledge_enabled:
        assert search.actual_outcome["data"]["result_basis"] == "knowledge-library-retrieval"
        assert search.actual_outcome["data"]["retrieved_document_ids"]
    else:
        assert search.actual_outcome["data"]["result_basis"] == "workflow-component-receipt"
        assert "retrieved_document_ids" not in search.actual_outcome["data"]
    if not taste_context_enabled:
        assert result["stages"]["communication"]["retrieved_taste_case_ids"] == []
        assert result["stages"]["figure"]["retrieved_taste_case_ids"] == []
    assert result["stages"]["figure"]["final_blocking_findings"] == 0


def test_native_condition_dry_run_exposes_the_exact_component_contract(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_native_conditions_v1.yaml",
            "--project-id",
            "native-condition-dry-run",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    condition = payload["native_execution"]["condition"]
    assert condition["condition_id"] == "full-scitaste"
    assert condition["components"]["taste_retrieval"] == "matched"
    assert condition["integrity_gates_invariant"] is True
    assert not outputs.exists()


def test_native_condition_requires_its_library_before_project_mutation(tmp_path: Path) -> None:
    base = load_full_workflow_config("configs/workflows/full_offline_native_conditions_v1.yaml")
    config = base.model_copy(
        update={
            "project_id": "native-condition-missing-library",
            "native_knowledge_config": None,
            "paper_id": "native-condition-missing-library-paper",
            "paper_directory": "native-condition-missing-library-paper",
        }
    )
    outputs = tmp_path / "outputs"

    with pytest.raises(ValueError, match="full-scitaste requires native_knowledge_config"):
        FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id="missing-library")

    assert not outputs.exists()


def test_native_condition_rejects_unknown_condition_before_project_mutation(
    tmp_path: Path,
) -> None:
    base = load_full_workflow_config("configs/workflows/full_offline_native_conditions_v1.yaml")
    config = base.model_copy(
        update={
            "project_id": "native-condition-unknown",
            "condition": "invented-condition",
            "paper_id": "native-condition-unknown-paper",
            "paper_directory": "native-condition-unknown-paper",
        }
    )
    outputs = tmp_path / "outputs"

    with pytest.raises(ValueError, match="invented-condition"):
        FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id="unknown-condition")

    assert not outputs.exists()

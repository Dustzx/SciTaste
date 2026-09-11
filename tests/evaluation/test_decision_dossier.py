from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    CampaignArtifactBinding,
    CampaignStageState,
    CampaignTrackState,
    ExperimentDecisionDossier,
    inspect_experiment_decision_dossier,
    load_experiment_decision_dossier,
)

DOSSIER_PATH = Path("configs/evaluation/campaigns/iclr2027_self_development_v1.yaml")


def test_repository_dossier_separates_exact_api_cells_from_design_only_gpu_data() -> None:
    inspection = load_experiment_decision_dossier(DOSSIER_PATH)
    dossier = inspection.dossier

    assert dossier.paper_title == (
        "SciTaste: Improving Autonomous Research through Scientific Taste"
    )
    assert {track.track_id for track in dossier.tracks} == {
        "scientific-taste-mechanism",
        "external-idea-to-paper",
    }
    mechanism = dossier.tracks[0]
    external = dossier.tracks[1]
    assert mechanism.state is CampaignTrackState.DESIGN_ONLY
    assert mechanism.model.model_id == "Qwen3-VL-2B-Instruct"
    assert mechanism.model.device_count == 8
    assert mechanism.data.population_floor == 120
    assert mechanism.matrix.planned_cells is None
    assert mechanism.matrix.planned_model_calls == 1_440
    assert mechanism.budget.allocated_gpu_hours == 16.0
    assert external.state is CampaignTrackState.BLOCKED
    assert external.model.model_id == "deepseek-flash"
    assert external.model.model_revision == "DeepSeek-V4.1-Flash"
    assert external.matrix.planned_cells == 100
    assert external.budget.api_requests == 1_500
    assert external.budget.total_tokens == 15_000_000
    assert external.budget.api_cost_usd == 100.0
    assert all(
        not value
        for value in (
            dossier.authorizes_download,
            dossier.authorizes_api_calls,
            dossier.authorizes_gpu_work,
            dossier.authorizes_human_recruitment,
        )
    )


def test_repository_dossier_verifies_every_bound_artifact_without_external_action() -> None:
    dossier = load_experiment_decision_dossier(DOSSIER_PATH).dossier

    report = inspect_experiment_decision_dossier(dossier, evidence_root=".")

    assert report.artifact_bindings_verified is True
    assert report.artifact_findings == ()
    assert report.exact_cell_count == 100
    assert report.design_only_track_ids == ("scientific-taste-mechanism",)
    assert report.next_stage_ids == ("freeze-headline-comparison-design",)
    assert report.stages[0].state is CampaignStageState.COMPLETE
    assert report.stages[1].state is CampaignStageState.READY_FOR_DECISION
    assert report.no_external_action_performed is True
    assert report.authorizes_download is False
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False


def test_artifact_drift_is_visible_and_never_changes_authority(tmp_path: Path) -> None:
    dossier = load_experiment_decision_dossier(DOSSIER_PATH).dossier
    artifact = tmp_path / "contract.txt"
    artifact.write_text("drifted\n", encoding="utf-8")
    binding = CampaignArtifactBinding(
        artifact_id="iclr-evaluation-contract",
        path="contract.txt",
        sha256="a" * 64,
    )
    changed = dossier.model_copy(update={"artifacts": (binding, *dossier.artifacts[1:])})

    report = inspect_experiment_decision_dossier(changed, evidence_root=tmp_path)

    assert report.artifact_bindings_verified is False
    assert any(item.code == "hash_mismatch" for item in report.artifact_findings)
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False


def test_dossier_rejects_unsafe_artifact_paths_and_false_cell_arithmetic() -> None:
    dossier = load_experiment_decision_dossier(DOSSIER_PATH).dossier
    payload = dossier.model_dump(mode="json", exclude={"dossier_sha256"})
    payload["artifacts"][0]["path"] = "../outside.md"
    with pytest.raises(ValidationError, match="normalized relative path"):
        ExperimentDecisionDossier.model_validate(payload)

    payload = dossier.model_dump(mode="json", exclude={"dossier_sha256"})
    payload["tracks"][1]["matrix"]["planned_cells"] = 99
    with pytest.raises(ValidationError, match=r"closed matrix \(100\)"):
        ExperimentDecisionDossier.model_validate(payload)


def test_decision_dossier_cli_is_read_only_and_can_save_a_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "REPORT.json"

    assert (
        main(
            [
                "evaluation",
                "decision-dossier",
                "--manifest",
                str(DOSSIER_PATH),
                "--evidence-root",
                ".",
                "--require-artifacts",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert payload["paper_title"] == (
        "SciTaste: Improving Autonomous Research through Scientific Taste"
    )
    assert payload["exact_cell_count"] == 100
    assert payload["report"] == str(output)
    assert saved["artifact_bindings_verified"] is True
    assert saved["tracks"][0]["model"]["model_id"] == "Qwen3-VL-2B-Instruct"
    assert saved["tracks"][1]["matrix"]["planned_cells"] == 100
    assert saved["no_external_action_performed"] is True

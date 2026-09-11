from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    inspect_executable_candidate,
    load_executable_candidate_manifest,
    load_executable_candidate_report,
    load_external_resource_corpus,
    save_executable_candidate_report,
)

MANIFEST = Path("configs/evaluation/candidates/mlrc_3090_objective_progress_v1.yaml")
CORPUS = Path("docs/research/data/autoresearch_evaluation_resources_v7.yaml")
COMPUTE = Path("configs/resources/compute_catalog_v2.yaml")


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    target = tmp_path / "candidate.yaml"
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def _report(path: Path = MANIFEST):
    return inspect_executable_candidate(
        load_executable_candidate_manifest(path),
        resource_corpus_path=CORPUS,
        compute_catalog_path=COMPUTE,
    )


def test_tracked_candidate_freezes_exact_mlrc_scope_without_execution() -> None:
    inspection = load_executable_candidate_manifest(MANIFEST)
    report = _report()
    corpus = load_external_resource_corpus(CORPUS).corpus

    assert corpus.schema_version == "2.4"
    assert {item.resource_id for item in corpus.resources} >= {"mlrc-bench", "mlrc-bench-code"}
    assert report.metadata_review_ready is True
    assert report.accepted_task_count == 7
    assert report.selected_task_count == 4
    assert report.excluded_task_count == 3
    assert report.planned_cells == 4 * 3 * 3 == 36
    assert report.planned_gpu_hours == 180.0
    assert report.formal_gpu_hour_cap == 192.0
    assert report.first_preflight_candidate_ids == (
        "perception_temporal_action_loc",
        "meta-learning",
    )
    assert report.requires_additional_48gb_single_device_resource is True
    assert report.local_preflight_ready is False
    assert report.experiment_ready is False
    assert report.authorizes_download is False
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False
    assert report.authorizes_execution is False
    assert report.external_action_performed is False
    assert (
        inspection.file_sha256
        in next(item for item in corpus.resources if item.resource_id == "mlrc-bench-code")
        .gates["selected_task_manifest"]
        .evidence
    )


def test_selected_48gb_task_is_rejected_on_24gb_per_device(tmp_path: Path) -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    payload["selected_tasks"][0]["paper_gpu_memory_mb"] = 48_000
    candidate = _write_manifest(tmp_path, payload)

    report = _report(candidate)

    assert report.metadata_review_ready is False
    assert {item.code for item in report.integrity_blockers} >= {
        "selected-task-exceeds-device-memory",
        "candidate-file-hash-not-bound-by-resource",
    }


def test_task_cannot_keep_blockers_after_all_evidence_is_ready(tmp_path: Path) -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    task = payload["selected_tasks"][0]
    for key in (
        "input_license_status",
        "task_assets_status",
        "environment_status",
        "held_out_evaluation_status",
    ):
        task[key] = "verified"
    task["authentication_status"] = "not_required"

    with pytest.raises(ValidationError, match="blockers must match evidence status"):
        load_executable_candidate_manifest(_write_manifest(tmp_path, payload))


def test_compute_or_benchmark_identity_drift_is_fail_closed(tmp_path: Path) -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    payload["binding"]["repository_commit"] = "0" * 40
    payload["binding"]["compute_catalog_semantic_sha256"] = "0" * 64
    report = _report(_write_manifest(tmp_path, payload))

    assert report.metadata_review_ready is False
    assert {item.code for item in report.integrity_blockers} >= {
        "benchmark-repository-pin-mismatch",
        "compute-catalog-semantic-mismatch",
    }


def test_candidate_loader_rejects_symlinks_and_oversized_input(tmp_path: Path) -> None:
    link = tmp_path / "candidate-link.yaml"
    link.symlink_to(MANIFEST.resolve())
    with pytest.raises(ValueError, match="must not be a symlink"):
        load_executable_candidate_manifest(link)

    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(ValueError, match="bounded regular file"):
        load_executable_candidate_manifest(oversized)


def test_candidate_report_is_self_hashed_and_tamper_evident(tmp_path: Path) -> None:
    target = save_executable_candidate_report(_report(), tmp_path / "REPORT.json")
    loaded = load_executable_candidate_report(target)
    assert loaded.report_sha256 == _report().report_sha256

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["planned_gpu_hours"] = 1.0
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_executable_candidate_report(target)


def test_executable_candidate_cli_separates_review_from_launch(capsys) -> None:
    common = [
        "evaluation",
        "executable-candidate",
        "--manifest",
        str(MANIFEST),
        "--resource-corpus",
        str(CORPUS),
        "--compute-catalog",
        str(COMPUTE),
    ]
    assert main([*common, "--require-metadata-review-ready"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metadata_review_ready"] is True
    assert payload["experiment_ready"] is False

    assert main([*common, "--require-experiment-ready"]) == 1
    capsys.readouterr()

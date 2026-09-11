from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.benchmark import (
    load_source_candidate_manifest,
    source_candidate_status,
)
from scitaste.cli import main
from scitaste.taste.intrinsic import TasteTask

MANIFEST = Path("docs/research/data/scitastebench_v2_source_candidates_v1.yaml")


def test_committed_source_screen_separates_tracks_and_authorizes_nothing() -> None:
    inspection = load_source_candidate_manifest(MANIFEST)
    report = source_candidate_status(inspection.manifest)

    assert set(report.covered_decision_families) == set(TasteTask)
    assert report.track_a_source_ids == (
        "aaar-1.0",
        "aries",
        "openreview-public-comments",
    )
    assert report.track_b_source_ids == ("mlr-bench-tasks",)
    assert report.blocker_count == 21
    assert report.acquisition_authorized is False
    assert report.api_execution_authorized is False
    assert report.gpu_execution_authorized is False
    assert all(
        item.acquisition_status == "not-acquired"
        for item in inspection.manifest.sources
    )


def test_track_b_source_cannot_be_used_as_track_a_label(tmp_path: Path) -> None:
    value = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    value["sources"][-1]["candidate_families"] = ["idea"]
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValidationError, match="Track B task sources"):
        load_source_candidate_manifest(path)


def test_source_status_cli_is_offline_and_content_bound(capsys) -> None:
    assert main(["benchmark", "source-status", "--manifest", str(MANIFEST)]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "hold"
    assert result["source_count"] == 4
    assert result["file_sha256"]
    assert result["manifest_sha256"]
    assert result["no_download_performed"] is True
    assert result["no_model_call_performed"] is True
    assert result["no_gpu_work_performed"] is True

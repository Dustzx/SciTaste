from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation.native_condition_preflight import (
    NativeConditionPreflightManifest,
    NativePathRequirement,
    inspect_native_condition_preflight,
    load_native_condition_preflight_manifest,
)

MANIFEST = Path(
    "configs/evaluation/preflight/qwen3vl2b_native_condition_path_v1.yaml"
)


def test_tracked_preflight_proves_static_selection_but_blocks_experiment() -> None:
    inspection = load_native_condition_preflight_manifest(MANIFEST)
    report = inspect_native_condition_preflight(inspection, source_root=".")

    assert report.source_commit_available is True
    assert report.source_commit_is_ancestor is True
    assert report.static_action_path_verified is True
    assert report.model_candidate_generation_verified is False
    assert report.corpus_pair_verified is False
    assert report.checkpoint_execution_verified is False
    assert report.ready_for_experiment is False
    assert report.authorizes_execution is False
    assert set(report.verified_requirements) == {
        NativePathRequirement.CONDITION_RUNTIME,
        NativePathRequirement.FIXED_CANDIDATE_SELECTION,
        NativePathRequirement.BACKEND_IDENTITY,
        NativePathRequirement.DECISION_TELEMETRY,
    }
    assert set(report.blocked_requirements) == {
        NativePathRequirement.MODEL_CANDIDATE_GENERATION,
        NativePathRequirement.MATCHED_PLACEBO_CORPORA,
    }
    assert report.pending_requirements == (NativePathRequirement.CHECKPOINT_EXECUTION,)
    assert len(report.proposal_sha256) == 64
    assert report.no_external_action_performed is True


def test_git_object_drift_blocks_static_action_path() -> None:
    inspection = load_native_condition_preflight_manifest(MANIFEST)
    drifted_manifest = inspection.manifest.model_copy(
        update={"workflow_config_sha256": "0" * 64}
    )
    drifted = inspection.model_copy(update={"manifest": drifted_manifest})

    report = inspect_native_condition_preflight(drifted, source_root=".")

    assert report.static_action_path_verified is False
    assert "conflicting_evidence_hash" in {item.code for item in report.blockers}


def test_manifest_rejects_incomplete_corpus_parity_matrix() -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    del payload["corpus_pair"]["dimensions"]["context_token_budget"]

    with pytest.raises(ValidationError, match="parity dimension matrix must be complete"):
        NativeConditionPreflightManifest.model_validate(payload)


def test_native_condition_preflight_cli_is_no_run_and_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "evaluation",
            "native-condition-preflight",
            "--manifest",
            str(MANIFEST),
            "--source-root",
            ".",
            "--require-experiment-ready",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["static_action_path_verified"] is True
    assert payload["ready_for_experiment"] is False
    assert payload["authorizes_execution"] is False
    assert payload["no_external_action_performed"] is True

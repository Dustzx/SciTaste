from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import scitaste.benchmark.manuscript as manuscript
from scitaste.cli import main
from scitaste.evaluation.native_condition_preflight import (
    NativeConditionPreflightManifest,
    NativePathRequirement,
    attest_native_condition_implementations,
    inspect_native_condition_preflight,
    load_native_condition_preflight_manifest,
)
from scitaste.taste.conditions import NativeTasteCondition

MANIFEST = Path("configs/evaluation/preflight/qwen3vl2b_native_condition_path_v1.yaml")
V2_MANIFEST = Path("configs/evaluation/preflight/qwen3vl2b_native_condition_path_v2.yaml")
V3_MANIFEST = Path("configs/evaluation/preflight/qwen3vl2b_native_condition_path_v3.yaml")
V4_MANIFEST = Path("configs/evaluation/preflight/qwen3vl2b_native_condition_path_v4.yaml")
FIXTURE_WORKFLOW = Path("configs/workflows/full_offline_native_conditions_v1.yaml")


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


def test_v2_proves_bounded_candidate_generation_but_keeps_external_gates_closed() -> None:
    inspection = load_native_condition_preflight_manifest(V2_MANIFEST)
    report = inspect_native_condition_preflight(inspection, source_root=".")

    assert report.source_commit_available is True
    assert report.source_commit_is_ancestor is True
    assert report.static_action_path_verified is True
    assert report.model_candidate_generation_verified is True
    assert report.corpus_pair_verified is False
    assert report.checkpoint_execution_verified is False
    assert report.ready_for_experiment is False
    assert set(report.blocked_requirements) == {
        NativePathRequirement.MATCHED_PLACEBO_CORPORA,
    }
    assert report.pending_requirements == (NativePathRequirement.CHECKPOINT_EXECUTION,)
    assert "candidate_generation_claim_inconsistent" not in {item.code for item in report.blockers}
    assert report.authorizes_execution is False
    assert report.no_external_action_performed is True


def test_v3_proves_curation_runtime_without_claiming_a_formal_corpus() -> None:
    inspection = load_native_condition_preflight_manifest(V3_MANIFEST)
    report = inspect_native_condition_preflight(inspection, source_root=".")

    assert report.source_commit_available is True
    assert report.source_commit_is_ancestor is True
    assert report.static_action_path_verified is True
    assert report.model_candidate_generation_verified is True
    assert report.corpus_curation_runtime_verified is True
    assert report.corpus_pair_verified is False
    assert report.checkpoint_execution_verified is False
    assert report.ready_for_experiment is False
    assert set(report.blocked_requirements) == {
        NativePathRequirement.MATCHED_PLACEBO_CORPORA,
    }
    assert report.pending_requirements == (NativePathRequirement.CHECKPOINT_EXECUTION,)
    assert report.authorizes_execution is False
    assert report.no_external_action_performed is True


def test_git_object_drift_blocks_static_action_path() -> None:
    inspection = load_native_condition_preflight_manifest(MANIFEST)
    drifted_manifest = inspection.manifest.model_copy(update={"workflow_config_sha256": "0" * 64})
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


def test_v4_behaviorally_attests_all_six_native_conditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    inspection = load_native_condition_preflight_manifest(V4_MANIFEST)

    report = attest_native_condition_implementations(
        inspection,
        fixture_workflow=FIXTURE_WORKFLOW,
        source_root=".",
        workspace_root=tmp_path,
        seed=7,
        allow_local_fixture_execution=True,
    )

    assert report.implementation_qualified is True
    assert report.findings == ()
    assert report.exact_condition_population_verified is True
    assert report.workflow_component_routes_verified is True
    assert report.full_placebo_single_factor_verified is True
    assert {item.condition_id for item in report.condition_probes} == set(NativeTasteCondition)
    assert all(item.condition_contract_verified for item in report.condition_probes)
    assert report.taste_routing_probe is not None
    assert report.taste_routing_probe.verified is True
    assert report.critic_routing_probe is not None
    assert report.critic_routing_probe.verified is True
    assert report.local_fixture_execution_performed is True
    assert report.real_task_or_experiment_execution_performed is False
    assert report.model_calls == report.api_calls == report.gpu_jobs == 0
    assert list(tmp_path.iterdir()) == []


def test_behavioral_attestation_requires_explicit_local_execution_switch(
    tmp_path: Path,
) -> None:
    inspection = load_native_condition_preflight_manifest(V4_MANIFEST)

    with pytest.raises(ValueError, match="allow-local-fixture-execution"):
        attest_native_condition_implementations(
            inspection,
            fixture_workflow=FIXTURE_WORKFLOW,
            source_root=".",
            workspace_root=tmp_path,
        )

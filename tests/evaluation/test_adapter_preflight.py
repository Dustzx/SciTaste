from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    AdapterRequirement,
    AdapterRequirementEvidence,
    ExternalAdapterPreflightManifest,
    ReadinessStatus,
    inspect_adapter_preflight,
    load_adapter_contract_manifest,
    load_adapter_preflight_manifest,
    load_external_resource_corpus,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v2.yaml"
ARC_PREFLIGHT = ROOT / "configs/evaluation/adapters/autoresearchclaw_mlr_v1.yaml"
AGENT_LAB_CONTRACT = (
    ROOT / "configs/evaluation/adapters/agent_laboratory_best_native_contract_v1.yaml"
)
V9_CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v9.yaml"


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _fixture(tmp_path: Path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _run_git(upstream, "init", "-q")
    _run_git(upstream, "config", "user.email", "test@example.invalid")
    _run_git(upstream, "config", "user.name", "SciTaste Test")
    (upstream / "README.md").write_text("pinned upstream\n", encoding="utf-8")
    _run_git(upstream, "add", "README.md")
    _run_git(upstream, "commit", "-q", "-m", "fixture")
    commit = _run_git(upstream, "rev-parse", "HEAD")

    artifact = b"verified adapter evidence\n"
    digest = hashlib.sha256(artifact).hexdigest()
    for relative in ("adapter.py", "evidence.md"):
        (tmp_path / relative).write_bytes(artifact)

    corpus = load_external_resource_corpus(CORPUS).corpus
    resources = tuple(
        resource.model_copy(update={"repository_commit": commit})
        if resource.resource_id == "autoresearchclaw"
        else resource
        for resource in corpus.resources
    )
    corpus = corpus.model_copy(update={"resources": resources})
    requirements = {
        requirement: AdapterRequirementEvidence(
            status=ReadinessStatus.VERIFIED,
            summary=f"Verified {requirement.value} fixture.",
            evidence_ref="evidence.md",
            evidence_sha256=digest,
        )
        for requirement in AdapterRequirement
    }
    manifest = ExternalAdapterPreflightManifest(
        preflight_id="adapter-fixture-v1",
        authorization_scope="static-inspection-only",
        external_resource_id="autoresearchclaw",
        expected_upstream_commit=commit,
        upstream_checkout="upstream",
        adapter_entrypoint="adapter.py",
        adapter_entrypoint_sha256=digest,
        requirements=requirements,
    )
    return manifest, corpus


def test_complete_static_preflight_is_ready_but_never_authorizes_execution(
    tmp_path: Path,
) -> None:
    manifest, corpus = _fixture(tmp_path)

    report = inspect_adapter_preflight(manifest, corpus, source_root=tmp_path)

    assert report.observed_upstream_commit == manifest.expected_upstream_commit
    assert report.upstream_tree_clean is True
    assert report.ready_for_corpus_revision_review is True
    assert report.ready_for_matched_adapter is True
    assert report.pending_requirements == ()
    assert set(report.corpus_revision_candidates) == set(AdapterRequirement)
    assert report.authorizes_execution is False
    assert report.no_execution_performed is True


def test_pending_requirement_and_hash_drift_fail_closed(tmp_path: Path) -> None:
    manifest, corpus = _fixture(tmp_path)
    pending = manifest.requirements[AdapterRequirement.MODEL_MAPPING].model_copy(
        update={
            "status": ReadinessStatus.PENDING,
            "evidence_ref": None,
            "evidence_sha256": None,
        }
    )
    requirements = dict(manifest.requirements)
    requirements[AdapterRequirement.MODEL_MAPPING] = pending
    pending_manifest = manifest.model_copy(update={"requirements": requirements})

    pending_report = inspect_adapter_preflight(
        pending_manifest,
        corpus,
        source_root=tmp_path,
    )
    assert pending_report.ready_for_corpus_revision_review is True
    assert pending_report.ready_for_matched_adapter is False
    assert pending_report.pending_requirements == (AdapterRequirement.MODEL_MAPPING,)

    (tmp_path / "evidence.md").write_text("drift\n", encoding="utf-8")
    drift_report = inspect_adapter_preflight(manifest, corpus, source_root=tmp_path)
    assert drift_report.ready_for_corpus_revision_review is False
    assert any("hash_mismatch" in finding.code for finding in drift_report.blockers)


def test_repository_arc_preflight_is_static_and_incomplete() -> None:
    manifest = load_adapter_preflight_manifest(ARC_PREFLIGHT).manifest

    assert manifest.external_resource_id == "autoresearchclaw"
    assert manifest.no_external_download is True
    assert manifest.no_execution_performed is True
    assert {
        requirement
        for requirement, evidence in manifest.requirements.items()
        if evidence.status is ReadinessStatus.PENDING
    } == {
        AdapterRequirement.TASK_MAPPING,
        AdapterRequirement.MODEL_MAPPING,
        AdapterRequirement.SANDBOX,
        AdapterRequirement.TELEMETRY,
    }


def test_v11_preflight_requires_and_replays_exact_adapter_contract() -> None:
    contract = load_adapter_contract_manifest(AGENT_LAB_CONTRACT)
    corpus = load_external_resource_corpus(V9_CORPUS).corpus
    adapter = ROOT / "src/scitaste/evaluation/adapter_contract.py"
    requirements = {
        requirement: AdapterRequirementEvidence(
            status=ReadinessStatus.PENDING,
            summary=f"Pending observed {requirement.value} evidence.",
        )
        for requirement in AdapterRequirement
    }
    manifest = ExternalAdapterPreflightManifest(
        schema_version="1.1",
        preflight_id="agent-laboratory-preflight-v2",
        authorization_scope="static-inspection-only",
        external_resource_id="agent-laboratory",
        expected_upstream_commit=contract.manifest.expected_upstream_commit,
        upstream_checkout="third_party/agent-laboratory",
        adapter_entrypoint="src/scitaste/evaluation/adapter_contract.py",
        adapter_entrypoint_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
        adapter_contract_ref=(
            "configs/evaluation/adapters/agent_laboratory_best_native_contract_v1.yaml"
        ),
        adapter_contract_file_sha256=contract.file_sha256,
        adapter_contract_proposal_sha256=contract.manifest.proposal_sha256,
        requirements=requirements,
    )

    report = inspect_adapter_preflight(manifest, corpus, source_root=ROOT)

    assert report.adapter_contract_proposal_sha256 == contract.manifest.proposal_sha256
    assert report.ready_for_corpus_revision_review is False
    assert report.ready_for_matched_adapter is False
    assert "adapter_contract:not_implementation_ready" in {
        finding.code for finding in report.blockers
    }


def test_v11_preflight_cannot_omit_contract_identity(tmp_path: Path) -> None:
    manifest, _ = _fixture(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["schema_version"] = "1.1"

    with pytest.raises(ValidationError, match="requires an exact adapter contract"):
        ExternalAdapterPreflightManifest.model_validate(payload)

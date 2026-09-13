from __future__ import annotations

import hashlib
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from scitaste.evaluation import (
    AgentLaboratoryPreparationManifest,
    ExternalResourceCorpus,
    load_adapter_contract_manifest,
    load_agent_laboratory_preparation,
    load_external_resource_corpus,
    prepare_agent_laboratory_adapter,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "configs/evaluation/adapters/agent_laboratory_best_native_contract_v1.yaml"
CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v9.yaml"


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, AgentLaboratoryPreparationManifest]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q")
    _git(upstream, "config", "user.email", "adapter@example.invalid")
    _git(upstream, "config", "user.name", "Adapter Fixture")
    (upstream / "ai_lab_repo.py").write_text("print('fixture')\n", encoding="utf-8")
    (upstream / "README.md").write_text("pinned fixture\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-q", "-m", "fixture")
    commit = _git(upstream, "rev-parse", "HEAD")

    evidence = tmp_path / "evidence.md"
    evidence.write_text("bounded adapter evidence\n", encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    loaded_contract = load_adapter_contract_manifest(CONTRACT).manifest
    requirements = {
        requirement: item.model_copy(
            update={
                "official_source_urls": (f"https://example.invalid/source/{commit}",),
                "evidence_ref": "evidence.md",
                "evidence_sha256": evidence_sha,
            }
        )
        for requirement, item in loaded_contract.requirements.items()
    }
    contract = loaded_contract.model_copy(
        update={"expected_upstream_commit": commit, "requirements": requirements}
    )
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(contract.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    loaded_corpus = load_external_resource_corpus(CORPUS).corpus
    resource = next(
        item for item in loaded_corpus.resources if item.resource_id == "agent-laboratory"
    ).model_copy(update={"repository_commit": commit})
    corpus = ExternalResourceCorpus(
        schema_version=loaded_corpus.schema_version,
        corpus_id="agent-laboratory-fixture",
        audited_on=date(2026, 9, 14),
        authorization_scope="metadata-only-no-execution",
        prior_snapshot=loaded_corpus.prior_snapshot,
        resources=(resource,),
    )
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(
        yaml.safe_dump(corpus.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    brief = tmp_path / "task.md"
    brief.write_text("# Exact task\n\nMeasure alpha without hidden labels.\n", encoding="utf-8")
    contract_bytes = contract_path.read_bytes()
    corpus_bytes = corpus_path.read_bytes()
    brief_bytes = brief.read_bytes()
    manifest = AgentLaboratoryPreparationManifest(
        preparation_id="agent-laboratory-fixture-v1",
        authorization_scope="prepare-only-no-execution",
        project_id="fixture-project",
        expected_upstream_commit=commit,
        upstream_checkout="upstream",
        adapter_contract_ref="contract.yaml",
        adapter_contract_file_sha256=hashlib.sha256(contract_bytes).hexdigest(),
        adapter_contract_proposal_sha256=contract.proposal_sha256,
        resource_corpus_ref="corpus.yaml",
        resource_corpus_file_sha256=hashlib.sha256(corpus_bytes).hexdigest(),
        resource_corpus_sha256=corpus.semantic_sha256,
        benchmark_resource_id="mlr-bench",
        task_id="exact-task",
        task_brief_ref="task.md",
        task_brief_sha256=hashlib.sha256(brief_bytes).hexdigest(),
        task_brief_bytes=len(brief_bytes),
        task_is_held_out=True,
        hidden_evaluation_content_included=False,
        no_provider_call_performed=True,
        no_upstream_execution_performed=True,
    )
    return brief, manifest


def test_real_git_source_and_exact_brief_compile_without_execution(tmp_path: Path) -> None:
    brief, manifest = _fixture(tmp_path)
    output = tmp_path / "prepared"

    receipt = prepare_agent_laboratory_adapter(
        manifest,
        source_root=tmp_path,
        output_dir=output,
    )

    assert (output / "input/task.md").read_bytes() == brief.read_bytes()
    config = yaml.safe_load((output / receipt.config_ref).read_text(encoding="utf-8"))
    assert config["research-topic"].encode("utf-8") == brief.read_bytes()
    assert config["llm-backend"] == "o3-mini"
    assert "api-key" not in config
    assert receipt.input_translation_complete is True
    assert receipt.upstream_source_unchanged is True
    assert receipt.ready_for_live_execution is False
    assert receipt.no_provider_call_performed is True
    assert receipt.no_upstream_execution_performed is True
    assert not (output / "upstream/.git").exists()


def test_preparation_manifest_loads_and_dirty_checkout_fails(tmp_path: Path) -> None:
    _, manifest = _fixture(tmp_path)
    manifest_path = tmp_path / "preparation.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    loaded = load_agent_laboratory_preparation(manifest_path)
    assert loaded.manifest.proposal_sha256 == manifest.proposal_sha256
    (tmp_path / "upstream/untracked.txt").write_text("drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checkout must be clean"):
        prepare_agent_laboratory_adapter(
            loaded.manifest,
            source_root=tmp_path,
            output_dir=tmp_path / "blocked",
        )

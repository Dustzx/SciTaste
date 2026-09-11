from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    AdapterRequirement,
    ExternalAdapterContractManifest,
    ReadinessStatus,
    inspect_adapter_contract,
    load_adapter_contract_manifest,
    load_external_resource_corpus,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v6.yaml"
MLR = ROOT / "configs/evaluation/adapters/mlr_agent_deepseek_v41_contract_v1.yaml"
AGENT_LAB = ROOT / "configs/evaluation/adapters/agent_laboratory_deepseek_v41_contract_v1.yaml"


@pytest.mark.parametrize("path", [MLR, AGENT_LAB])
def test_tracked_deepseek_contracts_preserve_real_incompatibilities(path: Path) -> None:
    manifest = load_adapter_contract_manifest(path).manifest
    corpus = load_external_resource_corpus(CORPUS).corpus

    report = inspect_adapter_contract(manifest, corpus, source_root=ROOT)

    assert report.ready_for_adapter_implementation is False
    assert report.ready_for_upstream_preflight is False
    assert report.ready_for_matched_adapter is False
    assert report.blocked_requirements == (
        AdapterRequirement.TASK_MAPPING,
        AdapterRequirement.MODEL_MAPPING,
        AdapterRequirement.SANDBOX,
        AdapterRequirement.TELEMETRY,
    )
    assert report.pending_requirements == (
        AdapterRequirement.ARTIFACT_MAPPING,
        AdapterRequirement.FAILURE_RESUME,
    )
    assert not report.verified_requirements
    assert len(report.blockers) == 4
    assert report.authorizes_execution is False
    assert report.no_external_download is True
    assert report.no_execution_performed is True


def test_verified_contract_must_match_task_and_model_semantics() -> None:
    payload = yaml.safe_load(MLR.read_text(encoding="utf-8"))
    for evidence in payload["requirements"].values():
        evidence["status"] = ReadinessStatus.VERIFIED.value

    with pytest.raises(ValidationError, match="exact, isolated task injection"):
        ExternalAdapterContractManifest.model_validate(payload)

    payload["task_translation"].update(
        {
            "one_task_per_process": True,
            "runtime_acquisition_policy_injectable": True,
        }
    )
    with pytest.raises(ValidationError, match="exact model ID for every role"):
        ExternalAdapterContractManifest.model_validate(payload)


def test_contract_rejects_shell_syntax() -> None:
    payload = yaml.safe_load(MLR.read_text(encoding="utf-8"))
    payload["invocation"]["argv_template"][0] = "python; unsafe"

    with pytest.raises(ValidationError, match="shell syntax"):
        ExternalAdapterContractManifest.model_validate(payload)


def test_missing_or_drifted_evidence_fails_closed(tmp_path: Path) -> None:
    manifest = load_adapter_contract_manifest(MLR).manifest
    corpus = load_external_resource_corpus(CORPUS).corpus

    report = inspect_adapter_contract(manifest, corpus, source_root=tmp_path)

    assert report.ready_for_adapter_implementation is False
    assert any(finding.code.endswith(":missing") for finding in report.blockers)


def test_adapter_contract_cli_exposes_no_run_decision(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(
        [
            "evaluation",
            "adapter-contract",
            "--manifest",
            str(MLR),
            "--resource-corpus",
            str(CORPUS),
            "--source-root",
            str(ROOT),
            "--require-upstream-preflight-ready",
        ]
    )

    assert status == 1
    output = capsys.readouterr().out
    assert '"ready_for_upstream_preflight": false' in output
    assert '"ready_for_matched_adapter": false' in output
    assert '"authorizes_execution": false' in output

from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.evaluation import (
    ComparisonRegime,
    ConfirmatoryContrastRole,
    ConfirmatoryEstimandKind,
    ContrastInferenceRole,
    EvaluationCriticDomain,
    EvaluationCriticSuite,
    EvaluationCriticVerdict,
    ExecutionLaneKind,
    ResourceGateName,
    ResourceGateStatus,
    compile_evaluation_cell_plan,
    inspect_adapter_contract,
    inspect_prelaunch_manifest,
    load_adapter_contract_manifest,
    load_external_resource_corpus,
    load_prelaunch_manifest,
)
from scitaste.project.models import content_sha256

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "docs/research/data/autoresearch_evaluation_resources_v8.yaml"
NATIVE_PATH = ROOT / "configs/evaluation/prelaunch/qwen3vl2b_native_taste_causal_prepilot_v9.yaml"
EXTERNAL_PATH = ROOT / "configs/evaluation/prelaunch/external_best_native_prepilot_v7.yaml"
AGENT_ADAPTER_PATH = (
    ROOT / "configs/evaluation/adapters/agent_laboratory_best_native_contract_v1.yaml"
)
TINY_ADAPTER_PATH = ROOT / "configs/evaluation/adapters/tiny_scientist_best_native_contract_v1.yaml"


def test_v8_resource_corpus_binds_best_native_models_and_tiny_license() -> None:
    inspection = load_external_resource_corpus(CORPUS_PATH)
    resources = {item.resource_id: item for item in inspection.corpus.resources}
    agent = resources["agent-laboratory"]
    tiny = resources["tiny-scientist"]

    assert inspection.corpus.schema_version == "2.5"
    assert inspection.semantic_sha256 == (
        "5d590fa7b502cfc67ae03fc0afc0ce4d084bfaeeca4ed2f1cfb297de5d63462f"
    )
    assert agent.gates[ResourceGateName.MODEL_MAPPING].status is ResourceGateStatus.VERIFIED
    assert tiny.gates[ResourceGateName.MODEL_MAPPING].status is ResourceGateStatus.VERIFIED
    assert tiny.code_license is not None
    assert tiny.code_license.identifier == "MIT"
    assert tiny.code_license.sha256 == (
        "389d00652aaea7a870e1128c95df7171580f347856b3993f8a0890f1a1cf09ae"
    )
    assert tiny.code_license.review_required is True


def test_native_taste_prepilot_compiles_as_one_matched_gpu_estimand() -> None:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    manifest = load_prelaunch_manifest(NATIVE_PATH).manifest
    assert manifest.analysis is not None
    claim = manifest.analysis.claim_admission
    assert claim is not None
    plan = compile_evaluation_cell_plan(manifest)

    assert manifest.resource_corpus_sha256 == corpus.semantic_sha256
    assert claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
    assert {item.role for item in claim.contrasts} >= {
        ConfirmatoryContrastRole.NO_TASTE_CONTROL,
        ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
    }
    assert len(claim.contrasts) == 5
    assert (
        sum(item.inference_role is ContrastInferenceRole.CONFIRMATORY for item in claim.contrasts)
        == 2
    )
    assert (
        sum(
            item.inference_role is ContrastInferenceRole.MECHANISM_DIAGNOSTIC
            for item in claim.contrasts
        )
        == 3
    )
    assert {
        item.role
        for item in claim.contrasts
        if item.inference_role is ContrastInferenceRole.MECHANISM_DIAGNOSTIC
    } == {ConfirmatoryContrastRole.COMPONENT_ONLY}
    assert all(
        system.real_implementation and system.implementation_ref is not None
        for system in manifest.systems
    )
    assert all(
        system.adapter_preflight_ref
        == "configs/evaluation/preflight/qwen3vl2b_native_condition_path_v1.yaml"
        and system.adapter_preflight_sha256
        == "180c02987385cd9ec851eee241a948a6b3f1a87b9b24976fc4a4076490d1583d"
        for system in manifest.systems
    )
    assert plan.schema_version == "1.2"
    assert plan.claim_contract_sha256 == content_sha256(claim)
    assert len(plan.cells) == 12
    assert {cell.lane_kind for cell in plan.cells} == {ExecutionLaneKind.GPU}
    assert {cell.resource.checkpoint_sha256 for cell in plan.cells} == {
        "47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34"
    }
    assert plan.authorizes_execution is False


def test_external_prepilot_compiles_as_confounded_best_native_description() -> None:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    manifest = load_prelaunch_manifest(EXTERNAL_PATH).manifest
    assert manifest.analysis is not None
    claim = manifest.analysis.claim_admission
    assert claim is not None
    plan = compile_evaluation_cell_plan(manifest)

    assert manifest.resource_corpus_sha256 == corpus.semantic_sha256
    assert claim.estimand_kind is ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE
    assert len(claim.contrasts) == 2
    assert all(item.role is ConfirmatoryContrastRole.EXTERNAL_METHOD for item in claim.contrasts)
    assert len(plan.cells) == 6
    assert plan.lanes[0].comparison_regime is ComparisonRegime.BEST_NATIVE
    assert plan.lanes[0].model_effects_confounded is True
    assert {cell.resource.provider_id for cell in plan.cells} == {"deepseek", "openai"}
    assert {cell.resource.model_id for cell in plan.cells} == {
        "deepseek-flash",
        "o3-mini",
        "gpt-4o-2024-08-06",
    }
    assert plan.authorizes_execution is False


def test_dual_estimand_prepilots_fail_closed_without_false_critic_requirements() -> None:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    for path in (NATIVE_PATH, EXTERNAL_PATH):
        manifest = load_prelaunch_manifest(path).manifest
        gate = inspect_prelaunch_manifest(
            manifest,
            corpus,
            observed_source_commit=manifest.source_commit,
            source_tree_clean=True,
        )
        review = EvaluationCriticSuite().review(manifest, corpus, gate, evidence_root=ROOT)
        baseline = next(
            finding
            for finding in review.findings
            if finding.domain is EvaluationCriticDomain.BASELINE_APPLICABILITY
        )
        replication = next(
            finding
            for finding in review.findings
            if finding.domain is EvaluationCriticDomain.STATISTICS
            and finding.criterion == "independent_replication"
        )

        assert gate.execution_authorized is False
        assert review.authorizes_execution is False
        assert "missing_direct_control" not in baseline.message
        assert "fewer_than_two_method_comparators" not in baseline.message
        assert "adapter_preflight_unbound" not in baseline.message
        assert replication.verdict is EvaluationCriticVerdict.ADVISORY
        assert "statistics:independent_replication" not in review.blocking_codes
        assert "gpu_inventory_checkpoint_sha256_mismatch" not in " ".join(
            finding.message for finding in review.findings
        )


def test_best_native_adapter_contracts_are_exactly_bound_and_still_no_run() -> None:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    external = load_prelaunch_manifest(EXTERNAL_PATH).manifest
    systems = {item.system_id: item for item in external.systems}
    expectations = (
        (AGENT_ADAPTER_PATH, "agent-laboratory", "o3-mini"),
        (TINY_ADAPTER_PATH, "tiny-scientist", "gpt-4o-2024-08-06"),
    )

    for path, system_id, model_id in expectations:
        inspection = load_adapter_contract_manifest(path)
        report = inspect_adapter_contract(inspection.manifest, corpus, source_root=ROOT)
        system = systems[system_id]

        assert hashlib.sha256(path.read_bytes()).hexdigest() == system.adapter_preflight_sha256
        assert inspection.manifest.model_translation.requested_model_id == model_id
        assert inspection.manifest.no_external_download is True
        assert inspection.manifest.no_execution_performed is True
        assert report.ready_for_upstream_preflight is False
        assert report.ready_for_matched_adapter is False
        assert report.authorizes_execution is False
        assert report.no_external_download is True
        assert report.no_execution_performed is True

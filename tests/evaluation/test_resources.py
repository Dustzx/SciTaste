from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation import (
    EvaluationResourceKind,
    ExternalResourceCorpus,
    ResourceGateDecision,
    ResourceGateName,
    ResourceGateStatus,
    ResourceUse,
    evaluate_resource_feasibility,
    load_external_resource_corpus,
)

CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")
V3_CORPUS_PATH = CORPUS_PATH.with_name("autoresearch_evaluation_resources_v3.yaml")


@pytest.fixture(scope="module")
def corpus() -> ExternalResourceCorpus:
    return load_external_resource_corpus(CORPUS_PATH).corpus


@pytest.fixture(scope="module")
def v3_corpus() -> ExternalResourceCorpus:
    return load_external_resource_corpus(V3_CORPUS_PATH).corpus


def test_v3_adds_accepted_headline_and_objective_benchmark_candidates(
    v3_corpus: ExternalResourceCorpus,
) -> None:
    resources = {item.resource_id: item for item in v3_corpus.resources}

    assert v3_corpus.schema_version == "2.1"
    assert set(resources) - {
        "ai-scientist-v2",
        "autoresearchclaw",
        "exp-bench",
        "mlr-agent",
        "mlr-bench",
    } == {"agent-laboratory", "ai-researcher", "mlrc-bench"}
    assert resources["agent-laboratory"].accepted_venue == "Findings of EMNLP 2025"
    assert resources["agent-laboratory"].code_license is not None
    assert resources["agent-laboratory"].code_license.identifier == "MIT"
    assert resources["ai-researcher"].code_license is None
    assert resources["mlrc-bench"].datasets[0].reported_rows == 7


def test_missing_license_is_a_blocker_not_a_pseudo_license(
    v3_corpus: ExternalResourceCorpus,
) -> None:
    reference = evaluate_resource_feasibility(
        v3_corpus,
        "ai-researcher",
        ResourceUse.REFERENCE,
    )
    comparison = evaluate_resource_feasibility(
        v3_corpus,
        "ai-researcher",
        ResourceUse.COMPARISON_SYSTEM,
    )

    assert reference.eligible is False
    assert "blocked_gate:code_license" in reference.blocker_codes
    assert comparison.eligible is False
    assert "blocked_gate:license_acceptance" in comparison.blocker_codes


def test_v3_overlay_is_bound_to_the_exact_v2_source(tmp_path: Path) -> None:
    overlay = tmp_path / V3_CORPUS_PATH.name
    base = tmp_path / CORPUS_PATH.name
    shutil.copyfile(V3_CORPUS_PATH, overlay)
    shutil.copyfile(CORPUS_PATH, base)
    base.write_text(base.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overlay base hash has drifted"):
        load_external_resource_corpus(overlay)


def test_tracked_corpus_has_exact_audited_resources_and_pins(
    corpus: ExternalResourceCorpus,
) -> None:
    resources = {item.resource_id: item for item in corpus.resources}

    assert set(resources) == {
        "ai-scientist-v2",
        "autoresearchclaw",
        "exp-bench",
        "mlr-agent",
        "mlr-bench",
    }
    assert resources["mlr-bench"].repository_commit == ("f728d571a992d71c8b526eeb4d9ab6bb5c8cc824")
    assert resources["exp-bench"].datasets[0].reported_rows == 461
    assert resources["ai-scientist-v2"].code_license.identifier == (
        "AI Scientist Source Code License v1.0"
    )
    assert resources["autoresearchclaw"].repository_commit == (
        "12d3fd809fa9658e91a0328c3280a0e462c78386"
    )
    assert all(
        dataset.local_copy_present is False
        for item in resources.values()
        for dataset in item.datasets
    )


def test_corpus_preserves_file_and_semantic_identity(corpus: ExternalResourceCorpus) -> None:
    first = load_external_resource_corpus(CORPUS_PATH)
    second = load_external_resource_corpus(CORPUS_PATH)

    assert first.file_sha256 == second.file_sha256
    assert first.semantic_sha256 == corpus.semantic_sha256
    assert len(first.semantic_sha256) == 64


@pytest.mark.parametrize(
    "resource_id",
    ["mlr-bench", "mlr-agent", "exp-bench", "ai-scientist-v2", "autoresearchclaw"],
)
def test_every_resource_is_reference_and_code_audit_eligible(
    corpus: ExternalResourceCorpus,
    resource_id: str,
) -> None:
    reference = evaluate_resource_feasibility(corpus, resource_id, ResourceUse.REFERENCE)
    code_audit = evaluate_resource_feasibility(corpus, resource_id, ResourceUse.CODE_AUDIT)

    assert reference.eligible is True
    assert code_audit.eligible is True
    assert reference.blocker_codes == ()
    assert len(reference.results) == 4


@pytest.mark.parametrize("resource_id", ["mlr-bench", "exp-bench"])
def test_benchmarks_are_not_yet_task_source_eligible(
    corpus: ExternalResourceCorpus,
    resource_id: str,
) -> None:
    report = evaluate_resource_feasibility(corpus, resource_id, ResourceUse.TASK_SOURCE)

    assert report.eligible is False
    assert "blocked_gate:selected_task_manifest" in report.blocker_codes
    assert "blocked_gate:task_assets" in report.blocker_codes
    assert report.report_sha256 == report.report_sha256


@pytest.mark.parametrize(
    ("resource_id", "required_blocker"),
    [
        ("mlr-agent", "blocked_gate:task_mapping"),
        ("ai-scientist-v2", "blocked_gate:license_acceptance"),
        ("autoresearchclaw", "blocked_gate:model_mapping"),
    ],
)
def test_external_systems_are_not_formal_comparison_eligible(
    corpus: ExternalResourceCorpus,
    resource_id: str,
    required_blocker: str,
) -> None:
    report = evaluate_resource_feasibility(
        corpus,
        resource_id,
        ResourceUse.COMPARISON_SYSTEM,
    )

    assert report.eligible is False
    assert required_blocker in report.blocker_codes


def test_not_applicable_gate_satisfies_a_required_gate(
    corpus: ExternalResourceCorpus,
) -> None:
    arc = next(item for item in corpus.resources if item.resource_id == "autoresearchclaw")
    resolved_gates = {
        name: ResourceGateDecision(
            status=(
                ResourceGateStatus.NOT_APPLICABLE
                if name is ResourceGateName.DISCLOSURE_ACCEPTANCE
                else ResourceGateStatus.VERIFIED
            ),
            evidence="synthetic unit-test evidence",
        )
        for name in ResourceGateName
    }
    eligible_arc = arc.model_copy(update={"gates": resolved_gates})
    eligible_corpus = corpus.model_copy(update={"resources": (eligible_arc,)})

    report = evaluate_resource_feasibility(
        eligible_corpus,
        "autoresearchclaw",
        ResourceUse.COMPARISON_SYSTEM,
    )

    assert report.eligible is True
    assert report.blocker_codes == ()


def test_not_applicable_cannot_bypass_a_material_gate(
    corpus: ExternalResourceCorpus,
) -> None:
    benchmark = next(item for item in corpus.resources if item.resource_id == "mlr-bench")
    gates = dict(benchmark.gates)
    gates[ResourceGateName.TASK_ASSETS] = ResourceGateDecision(
        status=ResourceGateStatus.NOT_APPLICABLE,
        evidence="invalid attempted bypass",
    )
    reduced = corpus.model_copy(
        update={"resources": (benchmark.model_copy(update={"gates": gates}),)}
    )

    report = evaluate_resource_feasibility(reduced, "mlr-bench", ResourceUse.TASK_SOURCE)

    assert "invalid_not_applicable:task_assets" in report.blocker_codes


def test_resource_kind_and_missing_gate_are_explicit_blockers(
    corpus: ExternalResourceCorpus,
) -> None:
    system = next(item for item in corpus.resources if item.resource_id == "mlr-agent")
    missing_repository_gate = system.model_copy(
        update={
            "resource_kind": EvaluationResourceKind.BENCHMARK,
            "datasets": next(
                item for item in corpus.resources if item.resource_id == "mlr-bench"
            ).datasets,
            "gates": {
                name: decision
                for name, decision in system.gates.items()
                if name is not ResourceGateName.REPOSITORY_PIN
            },
        }
    )
    reduced = corpus.model_copy(update={"resources": (missing_repository_gate,)})

    report = evaluate_resource_feasibility(
        reduced,
        "mlr-agent",
        ResourceUse.COMPARISON_SYSTEM,
    )

    assert "wrong_resource_kind:comparison_system_requires_system" in report.blocker_codes
    assert "missing_gate:repository_pin" in report.blocker_codes


def test_unknown_resource_is_rejected(corpus: ExternalResourceCorpus) -> None:
    with pytest.raises(ValueError, match="unknown evaluation resource"):
        evaluate_resource_feasibility(corpus, "missing", ResourceUse.REFERENCE)


def test_loader_rejects_symlink_and_non_mapping(tmp_path: Path) -> None:
    target = tmp_path / "corpus.yaml"
    target.write_text("[]\n", encoding="utf-8")
    symlink = tmp_path / "corpus-link.yaml"
    symlink.symlink_to(target)

    with pytest.raises(ValueError, match="must not be a symlink"):
        load_external_resource_corpus(symlink)
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_external_resource_corpus(target)


def test_schema_rejects_duplicate_resource_ids(corpus: ExternalResourceCorpus) -> None:
    payload = corpus.model_dump(mode="json")
    payload["resources"].append(payload["resources"][0])

    with pytest.raises(ValidationError, match="resource IDs must be unique"):
        ExternalResourceCorpus.model_validate(payload)


def test_schema_rejects_benchmark_without_dataset(corpus: ExternalResourceCorpus) -> None:
    payload = corpus.model_dump(mode="json")
    payload["resources"][0]["datasets"] = []

    with pytest.raises(ValidationError, match="benchmark resources require"):
        ExternalResourceCorpus.model_validate(payload)


def test_schema_rejects_verified_license_gate_without_license_evidence(
    corpus: ExternalResourceCorpus,
) -> None:
    payload = corpus.model_dump(mode="json")
    payload["resources"][0]["code_license"] = None

    with pytest.raises(ValidationError, match="requires license evidence"):
        ExternalResourceCorpus.model_validate(payload)


def test_yaml_declares_no_execution_authority() -> None:
    payload = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))

    assert payload["authorization_scope"] == "metadata-only-no-execution"

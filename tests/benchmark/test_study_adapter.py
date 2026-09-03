from __future__ import annotations

import hashlib
import json
import pprint

import pytest
import yaml

from scitaste.benchmark.study_adapter import (
    _analysis_consistency_audit,
    _artifact_consistency_audit,
    _audit_upstream_run,
    _citation_violations,
    _compact_refinement_log,
    _condition_context,
    _contract_matches,
    _extract_declared_contract,
    _guidance,
    _manuscript_structure_violations,
    _normalize_refinement_metrics,
    _outline_with_evidence_checkpoint,
    _parse_seed_evidence,
    _prepare_stage_seven,
    _publication_asset_violations,
    _remove_missing_publication_images,
    _sanitize_publication_artifacts,
    _selected_experiment,
    _stage_completed,
    _stdout_seed_ids,
    _usage,
    _validate_outline_artifact,
    _validate_paper_draft_artifact,
    _validate_selected_experiment,
    _write_analysis_synthesis_override,
    _write_prompt_overrides,
    _write_selected_experiment_evidence,
)
from scitaste.benchmark.study_models import SystemCondition


def load_task(name: str = "diagnosis_friendly_v1.yaml"):
    return yaml.safe_load(open(f"configs/experiments/tasks/{name}", encoding="utf-8"))


def request(condition: SystemCondition):
    return {
        "task": {
            "asset_path": "configs/experiments/tasks/diagnosis_friendly_v1.yaml",
            "asset_sha256": "a" * 64,
            "research_direction": "Diagnose a boundary",
            "domain": "scientific-language-modeling",
        },
        "cell": {
            "cell_id": "cell-test",
            "condition": condition.value,
            "seed": 7,
            "budget": {
                "gpu_hours": 1.0,
                "max_experiments": 8,
                "max_wall_time_hours": 1.0,
                "max_api_cost_usd": 10.0,
            },
        },
    }


def complete_paper(metric: float = 0.75) -> str:
    return f"""## Title
FROST: A Synthetic Factorial Diagnosis

## Abstract
Balanced accuracy was {metric:.6f} across three seeds (7, 19, and 31).

## Introduction
Position sensitivity motivates the controlled simulation [liu-etal-2024-lost].

## Related Work
Prior long-context evaluation separates position from length [liu-etal-2024-lost].

## Method
We execute three synthetic decision rules without neural inference.

## Experiments
The registered seeds are 7, 19, and 31.

## Results
Balanced accuracy was {metric:.6f} across three seeds (7, 19, and 31).

## Discussion
The measurements characterize the synthetic simulation only.

## Limitations
Transfer to language models remains untested.

## Conclusion
The synthetic benchmark completed and retained descriptive seed variation.
"""


def test_condition_context_keeps_ablations_distinct(tmp_path) -> None:
    task = load_task()
    base = _condition_context(
        SystemCondition.AUTORESEARCHCLAW,
        task,
        tmp_path / "base",
        request(SystemCondition.AUTORESEARCHCLAW),
    )
    knowledge = _condition_context(
        SystemCondition.KNOWLEDGE_RAG,
        task,
        tmp_path / "knowledge",
        request(SystemCondition.KNOWLEDGE_RAG),
    )
    taste = _condition_context(
        SystemCondition.TASTE_LIBRARY,
        task,
        tmp_path / "taste",
        request(SystemCondition.TASTE_LIBRARY),
    )
    full_dir = tmp_path / "full"
    full_dir.mkdir()
    full = _condition_context(
        SystemCondition.FULL_SCITASTE, task, full_dir, request(SystemCondition.FULL_SCITASTE)
    )

    assert not base["knowledge_document_ids"] and not base["taste_case_ids"]
    assert knowledge["knowledge_document_ids"] and not knowledge["taste_case_ids"]
    assert taste["taste_case_ids"] and not taste["knowledge_document_ids"]
    assert full["knowledge_document_ids"] and full["taste_case_ids"]
    assert full["controller_decision"]["selected_action"]["type"] == "PROBE"
    assert full["controller_decision"]["retrieved_taste_cases"] == [
        "diagnosis-factor-before-method-v1"
    ]


def test_stage_completed_requires_done_health_record(tmp_path) -> None:
    stage = tmp_path / "stage-18_v1"
    stage.mkdir()
    health = stage / "stage_health.json"
    health.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    assert not _stage_completed(tmp_path, "PEER_REVIEW")
    health.write_text(json.dumps({"status": "done"}), encoding="utf-8")
    assert _stage_completed(tmp_path, "PEER_REVIEW")
    assert not _stage_completed(tmp_path, "UNKNOWN")

    citation = tmp_path / "stage-23"
    citation.mkdir()
    (citation / "stage_health.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
    assert _stage_completed(tmp_path, "CITATION_VERIFY")


def test_guidance_only_exposes_registered_augmentation() -> None:
    task = load_task()
    trace = {"controller_decision": None}
    base = _guidance(task, SystemCondition.AUTORESEARCHCLAW, trace)["hypothesis_gen"]
    knowledge = _guidance(task, SystemCondition.KNOWLEDGE_RAG, trace)["hypothesis_gen"]
    taste = _guidance(task, SystemCondition.TASTE_LIBRARY, trace)["hypothesis_gen"]

    assert "Retrieved structured knowledge" not in base
    assert "factual constraints" in knowledge
    assert "decision precedents" in taste
    assert "decision precedents" not in knowledge


def test_guidance_separates_execution_and_publication_language() -> None:
    task = load_task()
    guidance = _guidance(
        task,
        SystemCondition.KNOWLEDGE_RAG,
        {"controller_decision": None},
        evidence={
            "registered_metrics": {
                "majority_vote": 0.8,
                "balanced_accuracy": 0.75,
            },
            "elapsed_sec": 2.0,
            "stdout_summary": "Condition: majority_vote",
        },
    )

    assert "diagnosis-factorial-v1" in guidance["code_generation"]
    assert "SCITASTE_BENCHMARK_CONTRACT" in guidance["code_generation"]
    assert "diagnosis-factorial-v1" not in guidance["paper_draft"]
    assert "SCITASTE_BENCHMARK_CONTRACT" not in guidance["paper_draft"]
    assert "majority vote=0.800000" in guidance["paper_draft"]
    assert "supersedes every earlier failed attempt" in guidance["result_analysis"]
    assert "does not run, train, probe, or evaluate a language model" in guidance["paper_draft"]
    assert "[liu-etal-2024-lost]" in guidance["paper_draft"]
    assert "never invent numbered references" in guidance["paper_draft"]


def test_stage_seven_materializes_only_registered_frozen_citations(tmp_path) -> None:
    run_dir = tmp_path / "run"
    _prepare_stage_seven(
        run_dir,
        load_task(),
        SystemCondition.KNOWLEDGE_RAG,
        {"controller_decision": None},
    )

    bibliography = (run_dir / "stage-07" / "references.bib").read_text()
    candidates = [
        json.loads(line)
        for line in (run_dir / "stage-07" / "candidates.jsonl").read_text().splitlines()
    ]
    assert "@article{liu-etal-2024-lost" in bibliography
    assert "10.1162/tacl_a_00638" in bibliography
    assert [item["cite_key"] for item in candidates] == ["liu-etal-2024-lost"]


def test_publication_sanitization_replaces_ids_and_records_hashes(tmp_path) -> None:
    analysis = tmp_path / "stage-14" / "analysis.md"
    analysis.parent.mkdir()
    analysis.write_text(
        "Execute the frozen synthetic benchmark contract diagnosis-factorial-v1; "
        "the diagnosis-factorial-v1 result compares majority_vote.",
        encoding="utf-8",
    )

    _sanitize_publication_artifacts(tmp_path, load_task(), relative_paths=("stage-14/analysis.md",))

    sanitized = analysis.read_text(encoding="utf-8")
    assert "diagnosis-factorial-v1" not in sanitized
    assert "majority_vote" not in sanitized
    assert "preregistered factorial benchmark" in sanitized
    assert "contract the preregistered" not in sanitized
    assert "benchmark benchmark" not in sanitized
    assert "the the preregistered" not in sanitized
    log = json.loads((tmp_path / "scitaste_publication_sanitization.json").read_text())
    assert log["artifacts"][0]["path"] == "stage-14/analysis.md"
    assert log["artifacts"][0]["before_sha256"] != log["artifacts"][0]["after_sha256"]


def test_prompt_override_freezes_plan_and_single_file_code(tmp_path) -> None:
    path = _write_prompt_overrides(tmp_path, load_task())
    override = yaml.safe_load(path.read_text(encoding="utf-8"))

    design = override["stages"]["experiment_design"]["user"]
    code = override["stages"]["code_generation"]["user"]
    assert "no GPU, no network, and no external dataset" in design
    assert "SCITASTE_BENCHMARK_CONTRACT" in code
    code_system = override["stages"]["code_generation"]["system"]
    assert "exactly one" in code_system
    assert "Every initial, review-fixed, or alignment-regenerated main.py MUST" in code_system
    assert "SCITASTE_BENCHMARK_CONTRACT" in code_system
    assert "diagnosis-factorial-v1" in code_system
    assert "SCITASTE_EVIDENCE_JSON=" in code_system
    assert "diagnosis-factorial-v1" in design
    assert "numpy.random.default_rng" in design
    assert "never assert that condition outputs" in code
    assert "Do not add an LLM call" in code
    assert "SCITASTE_EVIDENCE_JSON=" in code
    paper_system = override["stages"]["paper_draft"]["system"]
    assert "three times for disjoint section batches" in paper_system
    assert "never invent numeric citations" in paper_system.casefold()
    assert "never emit a framework-diagram" in paper_system
    improve = override["sub_prompts"]["iterative_improve"]["user"]
    assert "[7, 19, 31]" in improve
    assert "do not add, remove, rename" in improve
    assert "Equal outputs are a valid" in improve
    assert "SCITASTE_EVIDENCE_JSON=" in improve
    decision = override["stages"]["research_decision"]["user"]
    assert "write exactly PROCEED" in decision
    assert "future work" in decision

    _write_analysis_synthesis_override(
        tmp_path,
        load_task(),
        {
            "registered_metrics": {"balanced_accuracy": 0.75},
            "elapsed_sec": 2.0,
            "stdout_summary": "Seed 7: balanced_accuracy = 0.75",
        },
    )
    refreshed = yaml.safe_load(path.read_text(encoding="utf-8"))
    synthesis = refreshed["sub_prompts"]["analysis_synthesize"]
    assert "authoritative selected-experiment evidence" in synthesis["system"]
    assert "balanced accuracy=0.750000" in synthesis["user"]
    assert "{perspectives}" in synthesis["user"]


def test_contract_match_accepts_equivalent_upstream_labels() -> None:
    expected = load_task()["benchmark"]["contract"]
    observed = dict(expected)
    observed["name"] = observed.pop("generator")
    observed["baselines"] = observed.pop("conditions")
    metrics = observed.pop("metrics")
    observed["primary_metric"], observed["secondary_metric"] = metrics
    observed["derived_total"] = 1944

    assert _contract_matches(observed, expected)


def test_contract_match_accepts_complete_nested_contract_spec() -> None:
    expected = load_task()["benchmark"]["contract"]
    observed = {
        "contract_id": expected["generator"],
        "version": "1.0.0",
        "frozen": True,
        "seeds": expected["seeds"],
        "examples_per_cell": expected["examples_per_cell"],
        "factors": {
            "citation_topology": expected["citation_topologies"],
            "packet_length": expected["packet_lengths"],
            "contradiction_density": expected["contradiction_densities"],
            "target_position": expected["target_positions"],
        },
        "scoring_methods": expected["conditions"],
        "baselines": [],
        "metrics": expected["metrics"],
    }

    assert _contract_matches(observed, expected)


def test_contract_match_rejects_nested_contract_with_changed_factor() -> None:
    expected = load_task()["benchmark"]["contract"]
    observed = {
        "contract_id": expected["generator"],
        "seeds": expected["seeds"],
        "examples_per_cell": expected["examples_per_cell"],
        "factors": {
            "citation_topology": expected["citation_topologies"],
            "packet_length": [8, 32],
            "contradiction_density": expected["contradiction_densities"],
            "target_position": expected["target_positions"],
        },
        "scoring_methods": expected["conditions"],
        "metrics": expected["metrics"],
    }

    assert not _contract_matches(observed, expected)


def test_extract_declared_contract_reads_literal_compatible_name(tmp_path) -> None:
    source = tmp_path / "main.py"
    expected = load_task()["benchmark"]["contract"]
    source.write_text(
        "CONTRACT_SPEC = "
        + pprint.pformat(
            {
                "contract_id": expected["generator"],
                "seeds": expected["seeds"],
                "examples_per_cell": expected["examples_per_cell"],
                "factors": {
                    "citation_topology": expected["citation_topologies"],
                    "packet_length": expected["packet_lengths"],
                    "contradiction_density": expected["contradiction_densities"],
                    "target_position": expected["target_positions"],
                },
                "scoring_methods": expected["conditions"],
                "metrics": expected["metrics"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert _contract_matches(_extract_declared_contract([source]), expected)


def test_compaction_preserves_full_log_and_summary_metrics(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    path.write_text(
        json.dumps(
            {
                "iterations": [
                    {
                        "sandbox": {
                            "metrics": {
                                "ba_s7_flat_detail": 0.5,
                                "majority_vote/balanced_accuracy_mean": 0.6,
                            },
                            "stdout": "detail\nSUMMARY: ok\nmethod_mean: 0.6",
                            "stderr": "",
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    full = _compact_refinement_log(tmp_path)
    compact = json.loads(path.read_text(encoding="utf-8"))

    assert full.name == "refinement_log.full.json"
    assert (
        "ba_s7_flat_detail" in json.loads(full.read_text())["iterations"][0]["sandbox"]["metrics"]
    )
    metrics = compact["iterations"][0]["sandbox"]["metrics"]
    assert metrics == {"majority_vote/balanced_accuracy_mean": 0.6}
    assert compact["iterations"][0]["sandbox"]["stdout"] == "SUMMARY: ok\nmethod_mean: 0.6"


def test_metric_normalization_uses_real_stdout_aggregates(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    path.write_text(
        json.dumps(
            {
                "best_metric": None,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "metric": None,
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": (
                                "method_a: mean_balanced_accuracy=0.8, aggregate=0.8\n"
                                "method_b: mean_balanced_accuracy=0.6, aggregate=0.6"
                            ),
                        },
                        "sandbox_after_fix": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": "",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _normalize_refinement_metrics(tmp_path, "balanced_accuracy", "maximize")
    normalized = json.loads(path.read_text(encoding="utf-8"))

    assert normalized["best_version"] == "experiment_v1/"
    assert normalized["best_metric"] == pytest.approx(0.7)
    record = normalized["iterations"][0]
    assert record["sandbox"]["metrics"]["balanced_accuracy"] == pytest.approx(0.7)
    assert record["metric_normalization"]["source_values"] == [0.8, 0.6]


def test_metric_normalization_prefers_overall_mean_over_dispersion(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    path.write_text(
        json.dumps(
            {
                "best_metric": None,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "metric": None,
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": (
                                "Seed 7: mean_balanced_accuracy=0.5\n"
                                "Overall mean balanced_accuracy: 0.5\n"
                                "Overall std balanced_accuracy: 0.0\n"
                            ),
                        },
                        "sandbox_after_fix": {"returncode": 0, "metrics": {}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _normalize_refinement_metrics(tmp_path, "balanced_accuracy", "maximize")
    normalized = json.loads(path.read_text(encoding="utf-8"))

    assert normalized["best_metric"] == pytest.approx(0.5)
    assert normalized["iterations"][0]["metric_normalization"]["source_values"] == [0.5]


def test_metric_normalization_aggregates_every_registered_condition(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    path.write_text(
        json.dumps(
            {
                "best_metric": None,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {
                                "majority_vote": 0.8,
                                "confidence_weighted_vote": 0.9,
                                "position_aware_probe": 0.7,
                            },
                            "stdout": "",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    conditions = load_task()["benchmark"]["conditions"]
    _normalize_refinement_metrics(
        tmp_path, "balanced_accuracy", "maximize", condition_names=conditions
    )
    normalized = json.loads(path.read_text(encoding="utf-8"))

    assert normalized["best_metric"] == pytest.approx(0.8)
    record = normalized["iterations"][0]
    assert record["sandbox"]["metrics"]["balanced_accuracy"] == pytest.approx(0.8)
    assert record["metric_normalization"]["source_conditions"] == conditions


def test_metric_normalization_reads_condition_mean_summary(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    conditions = load_task()["benchmark"]["conditions"]
    path.write_text(
        json.dumps(
            {
                "best_metric": None,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": (
                                "PRIMARY METRIC SUMMARY: balanced_accuracy\n"
                                "  majority_vote: mean=0.81, dispersion=0.09\n"
                                "  confidence_weighted_vote: mean=0.84, dispersion=0.03\n"
                                "  position_aware_probe: mean=0.80, dispersion=0.04\n"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _normalize_refinement_metrics(
        tmp_path, "balanced_accuracy", "maximize", condition_names=conditions
    )
    normalized = json.loads(path.read_text(encoding="utf-8"))

    assert normalized["best_metric"] == pytest.approx((0.81 + 0.84 + 0.8) / 3)
    record = normalized["iterations"][0]
    assert record["metric_normalization"]["method"] == ("stdout-registered-condition-mean-v1")


def test_metric_normalization_reads_overall_named_condition_summary(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    conditions = load_task()["benchmark"]["conditions"]
    path.write_text(
        json.dumps(
            {
                "best_metric": 0.9,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": (
                                "PRIMARY METRIC SUMMARY: balanced_accuracy\n"
                                "majority_vote: overall_balanced_accuracy=0.81\n"
                                "confidence_weighted_vote: overall_balanced_accuracy=0.84\n"
                                "position_aware_probe: overall_balanced_accuracy=0.80\n"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _normalize_refinement_metrics(
        tmp_path, "balanced_accuracy", "maximize", condition_names=conditions
    )
    normalized = json.loads(path.read_text(encoding="utf-8"))

    assert normalized["best_version"] == "experiment_v1/"
    assert normalized["best_metric"] == pytest.approx((0.81 + 0.84 + 0.8) / 3)
    assert normalized["iterations"][0]["sandbox"]["metrics"] == {
        "majority_vote": 0.81,
        "confidence_weighted_vote": 0.84,
        "position_aware_probe": 0.8,
        "balanced_accuracy": pytest.approx((0.81 + 0.84 + 0.8) / 3),
    }


def test_metric_normalization_reads_quoted_primary_summary(tmp_path) -> None:
    stage = tmp_path / "stage-13"
    stage.mkdir()
    path = stage / "refinement_log.json"
    conditions = load_task()["benchmark"]["conditions"]
    path.write_text(
        json.dumps(
            {
                "best_metric": None,
                "best_version": "experiment/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {},
                            "stdout": (
                                "Condition 'majority_vote': primary metric "
                                "balanced_accuracy = 0.83\n"
                                "Condition 'confidence_weighted_vote': primary metric "
                                "balanced_accuracy = 0.81\n"
                                "Condition 'position_aware_probe': primary metric "
                                "balanced_accuracy = 0.80\n"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _normalize_refinement_metrics(
        tmp_path, "balanced_accuracy", "maximize", condition_names=conditions
    )
    record = json.loads(path.read_text())["iterations"][0]

    assert record["metric_normalization"]["method"] == "stdout-registered-condition-mean-v1"
    assert record["metric_normalization"]["source_conditions"] == conditions
    assert record["sandbox"]["metrics"]["balanced_accuracy"] == pytest.approx(0.8133333333)


def test_usage_sums_wire_tokens_and_prices_posted_rates(tmp_path) -> None:
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        json.dumps({"prompt_tokens": 1000, "completion_tokens": 500})
        + "\n"
        + json.dumps({"prompt_tokens": 2000, "completion_tokens": 1000})
        + "\n",
        encoding="utf-8",
    )

    usage = _usage(telemetry, load_task(), experiments=2)

    assert usage.llm_tokens == 4500
    assert usage.experiments == 2
    assert usage.search_queries == 0
    assert usage.api_cost_usd == 0.0125


def test_artifact_audit_requires_real_run_and_paper(tmp_path) -> None:
    (tmp_path / "stage-08").mkdir()
    (tmp_path / "stage-08" / "hypotheses.md").write_text(
        "## Hypothesis H1\n## Hypothesis H2", encoding="utf-8"
    )
    selected = tmp_path / "stage-13" / "experiment_v1"
    selected.mkdir(parents=True)
    contract = load_task()["benchmark"]["contract"]
    (selected / "main.py").write_text(
        "SCITASTE_BENCHMARK_CONTRACT = " + pprint.pformat(contract) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "stage-13" / "refinement_log.json").write_text(
        json.dumps(
            {
                "best_version": "experiment_v1/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "metric": 0.75,
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {"balanced_accuracy": 0.75},
                            "elapsed_sec": 2.0,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stage-14").mkdir()
    (tmp_path / "stage-14" / "analysis.md").write_text(
        "## Result\nBalanced accuracy was 0.75 across three seeds (7, 19, and 31).",
        encoding="utf-8",
    )
    (tmp_path / "stage-15").mkdir()
    (tmp_path / "stage-15" / "decision.md").write_text("## Decision\nPIVOT\n", encoding="utf-8")
    (tmp_path / "stage-16").mkdir()
    (tmp_path / "stage-16" / "outline.md").write_text(
        "Balanced accuracy was 0.75 across three seeds (7, 19, and 31).",
        encoding="utf-8",
    )
    (tmp_path / "stage-17").mkdir()
    (tmp_path / "stage-17" / "paper_draft.md").write_text(
        complete_paper(),
        encoding="utf-8",
    )

    outcome, experiments, audit = _audit_upstream_run(
        tmp_path, elapsed_seconds=360, task=load_task()
    )
    outline_audit = _validate_outline_artifact(tmp_path, load_task())
    draft_audit = _validate_paper_draft_artifact(tmp_path, load_task())

    assert experiments == outcome.total_experiments == 1
    assert outcome.useful_results == 1
    assert outcome.proposed_ideas == 2
    assert outcome.pivots == 1
    assert outcome.correct_pivots == 0
    assert audit["numerical_evidence_present"] is True
    assert audit["selected_experiment"]["metric"] == 0.75
    assert audit["artifact_consistency"]["paper_reports_primary_metric"] is True
    assert outline_audit["paper_reports_primary_metric"] is True
    assert draft_audit["paper_reports_primary_metric"] is True


def test_consistency_audit_rejects_internal_identifier_and_false_failure_story() -> None:
    task = load_task()
    selected = {
        "returncode": 0,
        "timed_out": False,
        "metric": 0.75,
        "metrics": {"balanced_accuracy": 0.75},
    }
    with pytest.raises(ValueError, match="internal-only identifiers"):
        _artifact_consistency_audit(
            analysis="Balanced accuracy was 0.75.",
            paper="The diagnosis-factorial-v1 balanced accuracy was 0.75.",
            selected_run=selected,
            task=task,
        )


def test_outline_checkpoint_materializes_missing_seed_table(tmp_path) -> None:
    task = load_task()
    selected_run = {
        "metrics": {
            "majority_vote": 0.0,
            "confidence_weighted_vote": 0.0,
            "position_aware_probe": 0.0,
            "balanced_accuracy": 0.0,
        },
        "seed_ids": [7, 19, 31],
        "per_seed_metrics": {
            str(seed): {
                "majority_vote": 0.0,
                "confidence_weighted_vote": 0.0,
                "position_aware_probe": 0.0,
            }
            for seed in (7, 19, 31)
        },
        "dispersion_metrics": {
            "majority_vote": {"mean": 0.0, "std": 0.0},
            "confidence_weighted_vote": {"mean": 0.0, "std": 0.0},
            "position_aware_probe": {"mean": 0.0, "std": 0.0},
        },
    }
    outline = "## Results\nA compact evidence table will be included in the manuscript.\n"

    repaired, changed = _outline_with_evidence_checkpoint(outline, selected_run, task)
    assert changed is True
    assert "Primary metric — balanced accuracy: 0.000000" in repaired
    assert "majority vote | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000" in repaired
    unchanged, changed = _outline_with_evidence_checkpoint(repaired, selected_run, task)
    assert changed is False
    assert unchanged == repaired


def test_manuscript_gate_rejects_duplicate_sections_and_placeholders() -> None:
    paper = complete_paper() + "\n## Results\nDuplicated.\n"
    assert _manuscript_structure_violations(paper) == ["duplicate-section:results"]

    placeholder = complete_paper().replace(
        "The measurements characterize the synthetic simulation only.",
        "A framework diagram will be inserted later.",
    )
    assert "publication-placeholder" in _manuscript_structure_violations(placeholder)


def test_manuscript_gate_rejects_unregistered_citations_and_missing_images(tmp_path) -> None:
    task = load_task()
    assert _citation_violations(complete_paper(), task) == []
    assert _citation_violations(complete_paper() + "\nPrior work [1, 2].", task) == [
        "invented-numeric-citations"
    ]
    assert _citation_violations(
        complete_paper().replace("liu-etal-2024-lost", "invented2026paper"), task
    ) == [
        "registered-citation-omitted",
        "unregistered-citation:invented2026paper",
    ]
    assert _publication_asset_violations(
        "![Framework](charts/framework_diagram.png)", tmp_path
    ) == ["missing-image:charts/framework_diagram.png"]


def test_missing_publication_image_is_removed_without_fabricating_asset(tmp_path) -> None:
    draft = tmp_path / "stage-17" / "paper_draft.md"
    draft.parent.mkdir()
    draft.write_text(
        "## Method\n\n![Framework](charts/missing.png)\n"
        "**Figure 1.** Planned framework.\n\nThe method remains described in prose.\n",
        encoding="utf-8",
    )

    assert _remove_missing_publication_images(draft, tmp_path) is True
    repaired = draft.read_text(encoding="utf-8")
    assert "missing.png" not in repaired
    assert "Figure 1" not in repaired
    assert "The method remains described in prose." in repaired
    assert _remove_missing_publication_images(draft, tmp_path) is False


def test_publication_image_cleanup_preserves_existing_and_unsafe_targets(tmp_path) -> None:
    existing = tmp_path / "stage-14" / "charts" / "observed.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"observed")
    draft = tmp_path / "stage-17" / "paper_draft.md"
    draft.parent.mkdir()
    draft.write_text(
        "![Observed](charts/observed.png)\n![Unsafe](../outside.png)\n",
        encoding="utf-8",
    )

    assert _remove_missing_publication_images(draft, tmp_path) is False
    assert "charts/observed.png" in draft.read_text(encoding="utf-8")
    assert "../outside.png" in draft.read_text(encoding="utf-8")


def test_analysis_gate_rejects_flattened_single_run_as_single_seed() -> None:
    task = load_task()
    selected = {
        "returncode": 0,
        "timed_out": False,
        "metric": 0.75,
        "metrics": {"balanced_accuracy": 0.75},
        "seed_ids": [7, 19, 31],
    }

    with pytest.raises(ValueError, match="single-seed-collapse"):
        _analysis_consistency_audit(
            analysis=("Balanced accuracy was 0.75, but n=1 and min=max=mean indicate a collapse."),
            selected_run=selected,
            task=task,
        )

    with pytest.raises(ValueError, match="single-seed-table"):
        _artifact_consistency_audit(
            analysis="Balanced accuracy was 0.75 across three seeds (7, 19, and 31).",
            paper=(
                "Balanced accuracy was 0.75 across three seeds (7, 19, and 31).\n"
                "Majority Vote & 0.7500 $\\pm$ 0.0000 & 1 \\\\"
            ),
            selected_run=selected,
            task=task,
        )

    with pytest.raises(ValueError, match="claimed-model-inference"):
        _analysis_consistency_audit(
            analysis="Balanced accuracy was 0.75 after actual model inference.",
            selected_run=selected,
            task=task,
        )

    accepted = _analysis_consistency_audit(
        analysis=(
            "Balanced accuracy was 0.75 across three seeds (7, 19, and 31). A summary n=1 "
            "denotes exactly one selected run, not one seed and not zero variance. The "
            "simulation provides no direct measurement of internal model confidence and "
            "does not perform model inference."
        ),
        selected_run=selected,
        task=task,
    )
    assert accepted["analysis_reports_primary_metric"] is True
    corrected = _analysis_consistency_audit(
        analysis=(
            "Balanced accuracy was 0.75 across seeds 7, 19, and 31. A conflicting "
            "perspective erroneously claimed the experiment had N=1; the evidence "
            "contains three seeds and nonzero dispersion."
        ),
        selected_run=selected,
        task=task,
    )
    assert corrected["analysis_reports_primary_metric"] is True
    instructional = _analysis_consistency_audit(
        analysis=(
            "Balanced accuracy was 0.75 across seeds 7, 19, and 31. The paper must "
            "not infer N=1 from one selected pipeline run."
        ),
        selected_run=selected,
        task=task,
    )
    assert instructional["analysis_reports_primary_metric"] is True
    prohibited = _analysis_consistency_audit(
        analysis=(
            "Balanced accuracy was 0.75 across seeds 7, 19, and 31. Collapsing the "
            "matrix into an N=1 summary is prohibited."
        ),
        selected_run=selected,
        task=task,
    )
    assert prohibited["analysis_reports_primary_metric"] is True
    limited = _analysis_consistency_audit(
        analysis=(
            "Balanced accuracy was 0.75 across seeds 7, 19, and 31. These findings do "
            "not serve as direct measurements of language-model internal confidence."
        ),
        selected_run=selected,
        task=task,
    )
    assert limited["analysis_reports_primary_metric"] is True
    with pytest.raises(ValueError, match="contradicts the successful"):
        _artifact_consistency_audit(
            analysis=(
                "Balanced accuracy was 0.75 across three seeds (7, 19, and 31), but the "
                "experiment did not execute."
            ),
            paper="The balanced accuracy was 0.75 across three seeds (7, 19, and 31).",
            selected_run=selected,
            task=task,
        )

    with pytest.raises(ValueError, match="single-seed-collapse"):
        _artifact_consistency_audit(
            analysis="Balanced accuracy was 0.75 across three seeds (7, 19, and 31).",
            paper=(
                "Balanced accuracy was 0.75 across three seeds (7, 19, and 31). "
                "The statistical summary reports N=1 and Min=Max=Mean."
            ),
            selected_run=selected,
            task=task,
        )


def test_selected_experiment_evidence_preserves_successful_stdout(tmp_path) -> None:
    task = load_task()
    selected = tmp_path / "stage-13" / "experiment_v1"
    selected.mkdir(parents=True)
    (selected / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "stage-13" / "refinement_log.json").write_text(
        json.dumps(
            {
                "best_version": "experiment_v1/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "metric": 0.75,
                        "sandbox": {
                            "returncode": 0,
                            "metrics": {
                                "majority_vote": 0.7,
                                "confidence_weighted_vote": 0.8,
                                "position_aware_probe": 0.75,
                                "balanced_accuracy": 0.75,
                            },
                            "elapsed_sec": 2.0,
                            "stdout": (
                                "Condition: majority_vote\n"
                                "  Seed 7: balanced_accuracy = 0.70\n"
                                "  Aggregate balanced_accuracy = 0.70\n"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    evidence = _write_selected_experiment_evidence(tmp_path, task)

    assert evidence["execution_status"] == "completed"
    assert evidence["registered_metrics"]["balanced_accuracy"] == 0.75
    assert "Seed 7" in evidence["stdout_summary"]
    assert (tmp_path / "scitaste_selected_experiment_evidence.json").is_file()


def test_seed_evidence_parser_handles_condition_blocks_and_true_zero_dispersion() -> None:
    stdout = """Condition: majority_vote
  Seed 7: balanced_accuracy=0.833333, std=0.2
  Seed 19: balanced_accuracy=0.833333, std=0.2
  Seed 31: balanced_accuracy=0.833333, std=0.2
  Primary metric balanced_accuracy=0.833333
Condition: confidence_weighted_vote
  Seed 7: balanced_accuracy=0.810185, std=0.2
  Seed 19: balanced_accuracy=0.800926, std=0.2
  Seed 31: balanced_accuracy=0.833333, std=0.2
  Primary metric balanced_accuracy=0.814815
Condition: majority_vote
  Cross-seed std: 0.000000
Condition: confidence_weighted_vote
  Cross-seed std: 0.013629
"""

    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert per_seed["19"]["confidence_weighted_vote"] == 0.800926
    assert dispersion["majority_vote"] == {"mean": 0.833333, "std": 0.0}
    assert dispersion["confidence_weighted_vote"] == {"mean": 0.814815, "std": 0.013629}


def test_seed_evidence_parser_handles_seed_scoped_condition_blocks() -> None:
    stdout = """--- Seed 7 ---
  Condition: majority_vote
    balanced_accuracy: mean=0.8450, std=0.1315
  Condition: confidence_weighted_vote
    balanced_accuracy: mean=0.8108, std=0.1386
--- Seed 19 ---
  Condition: majority_vote
    balanced_accuracy: mean=0.8303, std=0.1647
  Condition: confidence_weighted_vote
    balanced_accuracy: mean=0.7869, std=0.1740
--- Seed 31 ---
  Condition: majority_vote
    balanced_accuracy: mean=0.8281, std=0.1601
  Condition: confidence_weighted_vote
    balanced_accuracy: mean=0.7990, std=0.1525
AGGREGATE METRICS ACROSS SEEDS
Condition: majority_vote
  Overall balanced_accuracy: 0.8344 +/- 0.1182
Condition: confidence_weighted_vote
  Overall balanced_accuracy: 0.7989 +/- 0.1279
"""

    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert per_seed == {
        "7": {"majority_vote": 0.845, "confidence_weighted_vote": 0.8108},
        "19": {"majority_vote": 0.8303, "confidence_weighted_vote": 0.7869},
        "31": {"majority_vote": 0.8281, "confidence_weighted_vote": 0.799},
    }
    assert dispersion["majority_vote"]["mean"] == 0.8344
    assert dispersion["majority_vote"]["std"] == pytest.approx(0.00750214784)
    assert dispersion["confidence_weighted_vote"]["mean"] == 0.7989
    assert dispersion["confidence_weighted_vote"]["std"] == pytest.approx(0.00975739036)


def test_seed_evidence_parser_handles_condition_assignments_under_seed_blocks() -> None:
    stdout = """[Seed 7] balanced_accuracy = 0.80
Seed 7:
  condition=majority_vote mean_ba=0.77 std=0.2
  condition=confidence_weighted_vote mean_ba=0.89 std=0.1
Seed 19:
  condition=majority_vote mean_ba=0.75 std=0.2
  condition=confidence_weighted_vote mean_ba=0.93 std=0.1
Seed 31:
  condition=majority_vote mean_ba=0.76 std=0.2
  condition=confidence_weighted_vote mean_ba=0.91 std=0.1
AGGREGATE METRICS (across seeds)
  condition           : partial_eta^2 = 0.42
Primary metric balanced_accuracy: 0.81
"""

    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert per_seed["19"] == {
        "majority_vote": 0.75,
        "confidence_weighted_vote": 0.93,
    }
    assert dispersion["majority_vote"] == pytest.approx({"mean": 0.76, "std": 0.00816496581})
    assert dispersion["confidence_weighted_vote"] == pytest.approx(
        {"mean": 0.91, "std": 0.01632993162}
    )
    assert "partial_eta" not in dispersion


def test_seed_evidence_parser_handles_bracketed_condition_seed_assignments() -> None:
    stdout = """Grid size: 54, Examples per cell: 12, Total per seed: 648
Grid cells: 54, Examples/cell: 12, Total/seed: 648
[majority_vote] seed=7 balanced_accuracy=0.81
[confidence_weighted_vote] seed: 7 balanced_accuracy=0.82
[majority_vote] seed=19 balanced_accuracy=0.83
[confidence_weighted_vote] seed: 19 balanced_accuracy=0.84
[majority_vote] seed=31 balanced_accuracy=0.85
[confidence_weighted_vote] seed: 31 balanced_accuracy=0.86
"""

    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert _stdout_seed_ids(stdout) == [7, 19, 31]
    assert per_seed["19"] == {
        "majority_vote": 0.83,
        "confidence_weighted_vote": 0.84,
    }
    assert dispersion["majority_vote"] == pytest.approx({"mean": 0.83, "std": 0.01632993162})


def test_stdout_seed_ids_accept_condition_rows_but_not_factor_effects() -> None:
    stdout = """Condition=majority_vote Seed=7 BalancedAccuracy=0.54
Condition=majority_vote Seed=19 BalancedAccuracy=0.51
Condition=majority_vote Seed=31 BalancedAccuracy=0.50
Factor effects:
  seed: 0.008292
"""

    assert _stdout_seed_ids(stdout) == [7, 19, 31]


def test_seed_evidence_parser_prefers_verified_machine_record() -> None:
    payload = {
        "schema_version": "1.0",
        "primary_metric": {"name": "balanced_accuracy", "value": 0.75},
        "conditions": {
            "majority_vote": {
                "per_seed": {"7": 0.7, "19": 0.7, "31": 0.7},
                "mean": 0.7,
                "std": 0.0,
            },
            "confidence_weighted_vote": {
                "per_seed": {"7": 0.7, "19": 0.8, "31": 0.9},
                "mean": 0.8,
                "std": 0.08165,
            },
        },
    }
    stdout = "Seed 7: bad_condition: balanced_accuracy=0.1\nSCITASTE_EVIDENCE_JSON=" + json.dumps(
        payload, separators=(",", ":")
    )

    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert "bad_condition" not in per_seed["7"]
    assert per_seed["31"]["confidence_weighted_vote"] == 0.9
    assert dispersion["majority_vote"] == {"mean": 0.7, "std": 0.0}


def test_seed_evidence_parser_rejects_inconsistent_machine_record() -> None:
    payload = {
        "schema_version": "1.0",
        "primary_metric": {"name": "balanced_accuracy", "value": 0.7},
        "conditions": {
            "majority_vote": {
                "per_seed": {"7": 0.6, "19": 0.7, "31": 0.8},
                "mean": 0.1,
                "std": 0.0,
            }
        },
    }

    with pytest.raises(ValueError, match="mean is inconsistent"):
        _parse_seed_evidence("SCITASTE_EVIDENCE_JSON=" + json.dumps(payload), "balanced_accuracy")


def test_seed_evidence_parser_does_not_trust_redundant_machine_primary() -> None:
    payload = {
        "schema_version": "1.0",
        "primary_metric": {"name": "balanced_accuracy", "value": 0.9},
        "conditions": {
            "majority_vote": {
                "per_seed": {"7": 0.7, "19": 0.7, "31": 0.7},
                "mean": 0.7,
                "std": 0.0,
            }
        },
    }

    per_seed, dispersion = _parse_seed_evidence(
        "SCITASTE_EVIDENCE_JSON=" + json.dumps(payload), "balanced_accuracy"
    )

    assert per_seed["19"]["majority_vote"] == 0.7
    assert dispersion["majority_vote"] == {"mean": 0.7, "std": 0.0}


def test_selected_experiment_evidence_recovers_post_repair_trace(tmp_path) -> None:
    task = load_task()
    selected = tmp_path / "stage-13" / "experiment_v1"
    selected.mkdir(parents=True)
    source = selected / "main.py"
    source.write_text(
        "SCITASTE_BENCHMARK_CONTRACT = " + pprint.pformat(task["benchmark"]["contract"]) + "\n",
        encoding="utf-8",
    )
    metrics = {
        "majority_vote": 0.7,
        "confidence_weighted_vote": 0.8,
        "position_aware_probe": 0.75,
        "balanced_accuracy": 0.75,
    }
    refinement = {
        "best_version": "experiment_v1/",
        "iterations": [
            {
                "iteration": 1,
                "version_dir": "experiment_v1/",
                "metric": 0.75,
                "sandbox": {"returncode": 1, "metrics": {}, "stdout": "failed"},
                "sandbox_after_fix": {
                    "returncode": 0,
                    "timed_out": False,
                    "elapsed_sec": 1.25,
                    "metrics": metrics,
                },
                "metric_normalization": {
                    "method": "stdout-registered-condition-mean-v1",
                    "source_conditions": [
                        "majority_vote",
                        "confidence_weighted_vote",
                        "position_aware_probe",
                    ],
                    "source_values": [0.7, 0.8, 0.75],
                    "aggregate": "arithmetic_mean",
                },
            }
        ],
    }
    log_path = tmp_path / "stage-13" / "refinement_log.json"
    log_path.write_text(json.dumps(refinement), encoding="utf-8")

    with pytest.raises(ValueError, match="lacks an exact sandbox trace"):
        _write_selected_experiment_evidence(tmp_path, task)

    trace_dir = tmp_path / "stage-13" / "refine_sandbox_v1_fix"
    trace_dir.mkdir()
    stdout = (
        "Seed 7\n"
        "majority_vote: balanced_accuracy=0.69\n"
        "confidence_weighted_vote: balanced_accuracy=0.79\n"
        "position_aware_probe: balanced_accuracy=0.74\n"
        "Seed 19\n"
        "majority_vote: balanced_accuracy=0.70\n"
        "confidence_weighted_vote: balanced_accuracy=0.80\n"
        "position_aware_probe: balanced_accuracy=0.75\n"
        "Seed 31\n"
        "majority_vote: balanced_accuracy=0.71\n"
        "confidence_weighted_vote: balanced_accuracy=0.81\n"
        "position_aware_probe: balanced_accuracy=0.76\n"
        "majority_vote: mean_balanced_accuracy=0.70, std=0.01\n"
        "confidence_weighted_vote: mean_balanced_accuracy=0.80, std=0.01\n"
        "position_aware_probe: mean_balanced_accuracy=0.75, std=0.01\n"
    )
    trace = {
        "schema_version": "1.0",
        "method": "process-local-sandbox-result-trace-v1",
        "returncode": 0,
        "timed_out": False,
        "elapsed_sec": 1.25,
        "metrics": {},
        "project_source_sha256": {"main.py": hashlib.sha256(source.read_bytes()).hexdigest()},
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_bytes": len(stdout.encode()),
        "stderr_bytes": 0,
        "stdout_excerpt": stdout,
        "stderr_excerpt": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    trace_path = trace_dir / "scitaste_execution_trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    evidence = _write_selected_experiment_evidence(tmp_path, task)
    _validate_selected_experiment(tmp_path, task)

    assert evidence["seed_ids"] == [7, 19, 31]
    assert evidence["stdout_observed_seed_ids"] == [7, 19, 31]
    assert evidence["per_seed_metrics"]["19"]["confidence_weighted_vote"] == 0.8
    assert evidence["dispersion_metrics"]["position_aware_probe"]["std"] == 0.01
    assert evidence["stdout_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    assert evidence["execution_trace"]["path"] == (
        "stage-13/refine_sandbox_v1_fix/scitaste_execution_trace.json"
    )
    assert evidence["execution_trace"]["source_verified"] is True


def test_selected_experiment_pairs_mutated_version_with_matching_fix_trace(tmp_path) -> None:
    task = load_task()
    stage = tmp_path / "stage-13"
    selected_dir = stage / "experiment_v1"
    selected_dir.mkdir(parents=True)
    fixed_source = (
        "SCITASTE_BENCHMARK_CONTRACT = "
        + pprint.pformat(task["benchmark"]["contract"])
        + "\nprint('fixed')\n"
    )
    original_source = fixed_source.replace("fixed", "original")
    (selected_dir / "main.py").write_text(fixed_source, encoding="utf-8")
    iteration = {
        "iteration": 1,
        "version_dir": "experiment_v1/",
        "metric": 0.5,
        "sandbox": {
            "returncode": 0,
            "timed_out": False,
            "elapsed_sec": 1.0,
            "metrics": {"balanced_accuracy": 0.5},
            "stdout": "initial output is intentionally longer than repaired output",
        },
        "sandbox_after_fix": {
            "returncode": 0,
            "timed_out": False,
            "elapsed_sec": 1.0,
            "metrics": {
                "majority_vote": 0.61,
                "confidence_weighted_vote": 0.61,
                "position_aware_probe": 0.61,
                "balanced_accuracy": 0.61,
            },
            "stdout": "",
        },
    }
    log_path = stage / "refinement_log.json"
    log_path.write_text(
        json.dumps(
            {
                "best_version": "experiment_v1/",
                "best_metric": 0.5,
                "iterations": [iteration],
            }
        ),
        encoding="utf-8",
    )
    evidence_payload = {
        "schema_version": "1.0",
        "primary_metric": {"name": "balanced_accuracy", "value": 0.62},
        "conditions": {
            name: {
                "per_seed": {"7": 0.6, "19": 0.6, "31": 0.6},
                "mean": 0.6,
                "std": 0.0,
            }
            for name in task["benchmark"]["conditions"]
        },
    }
    repaired_stdout = (
        "Seed 7\nSeed 19\nSeed 31\nPrimary metric balanced_accuracy: 0.6\n"
        "SCITASTE_EVIDENCE_JSON=" + json.dumps(evidence_payload, separators=(",", ":"))
    )

    def write_trace(directory, source, stdout, metrics):
        directory.mkdir()
        trace = {
            "schema_version": "1.0",
            "method": "process-local-sandbox-result-trace-v1",
            "returncode": 0,
            "timed_out": False,
            "elapsed_sec": 1.0,
            "metrics": metrics,
            "project_source_sha256": {"main.py": hashlib.sha256(source.encode()).hexdigest()},
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "stdout_bytes": len(stdout.encode()),
            "stderr_bytes": 0,
            "stdout_excerpt": stdout,
            "stderr_excerpt": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }
        (directory / "scitaste_execution_trace.json").write_text(
            json.dumps(trace), encoding="utf-8"
        )

    write_trace(
        stage / "refine_sandbox_v1",
        original_source,
        "initial output is intentionally longer than repaired output",
        {"balanced_accuracy": 0.5},
    )
    repaired_parser_metrics = {
        "majority_vote": 0.61,
        "confidence_weighted_vote": 0.61,
        "position_aware_probe": 0.61,
        "balanced_accuracy": 0.61,
    }
    write_trace(
        stage / "refine_sandbox_v1_fix",
        fixed_source,
        repaired_stdout,
        repaired_parser_metrics,
    )

    _normalize_refinement_metrics(
        tmp_path,
        "balanced_accuracy",
        "maximize",
        condition_names=list(task["benchmark"]["conditions"]),
    )
    _validate_selected_experiment(tmp_path, task)
    _, selected = _selected_experiment(tmp_path, "balanced_accuracy")

    assert selected["execution_trace"]["sandbox_record"] == "sandbox_after_fix"
    assert selected["metrics"]["balanced_accuracy"] == 0.6
    assert selected["metric_sources"]["balanced_accuracy"] == (
        "derived-from-source-verified-machine-condition-means"
    )
    assert (
        selected["source_sha256"]["stage-13/experiment_v1/main.py"]
        == hashlib.sha256(fixed_source.encode()).hexdigest()
    )


def test_artifact_audit_rejects_failed_selected_experiment(tmp_path) -> None:
    selected = tmp_path / "stage-13" / "experiment_v1"
    selected.mkdir(parents=True)
    (selected / "main.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "stage-13" / "refinement_log.json").write_text(
        json.dumps(
            {
                "best_version": "experiment_v1/",
                "iterations": [
                    {
                        "version_dir": "experiment_v1/",
                        "metric": 0.5,
                        "sandbox": {
                            "returncode": 1,
                            "metrics": {"balanced_accuracy": 0.5},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="did not exit successfully"):
        _selected_experiment(tmp_path, "balanced_accuracy")

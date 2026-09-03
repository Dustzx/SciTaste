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
    _compact_refinement_log,
    _condition_context,
    _contract_matches,
    _guidance,
    _normalize_refinement_metrics,
    _sanitize_publication_artifacts,
    _selected_experiment,
    _stage_completed,
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


def test_publication_sanitization_replaces_ids_and_records_hashes(tmp_path) -> None:
    analysis = tmp_path / "stage-14" / "analysis.md"
    analysis.parent.mkdir()
    analysis.write_text(
        "The diagnosis-factorial-v1 result compares majority_vote.", encoding="utf-8"
    )

    _sanitize_publication_artifacts(tmp_path, load_task(), relative_paths=("stage-14/analysis.md",))

    sanitized = analysis.read_text(encoding="utf-8")
    assert "diagnosis-factorial-v1" not in sanitized
    assert "majority_vote" not in sanitized
    assert "preregistered factorial benchmark" in sanitized
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
    assert "exactly one" in override["stages"]["code_generation"]["system"]
    assert "diagnosis-factorial-v1" in design
    assert "numpy.random.default_rng" in design
    assert "never assert that condition outputs" in code
    assert "Do not add an LLM call" in code
    improve = override["sub_prompts"]["iterative_improve"]["user"]
    assert "[7, 19, 31]" in improve
    assert "do not add, remove, rename" in improve
    assert "Equal outputs are a valid" in improve
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
        "The balanced accuracy was 0.75 across three seeds (7, 19, and 31).",
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
        "Seed 7\nSeed 19\nSeed 31\n"
        "majority_vote: balanced_accuracy=0.7\n"
        "confidence_weighted_vote: balanced_accuracy=0.8\n"
        "position_aware_probe: balanced_accuracy=0.75\n"
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
    assert evidence["stdout_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    assert evidence["execution_trace"]["path"] == (
        "stage-13/refine_sandbox_v1_fix/scitaste_execution_trace.json"
    )
    assert evidence["execution_trace"]["source_verified"] is True


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

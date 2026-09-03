from __future__ import annotations

import json
import pprint

import pytest
import yaml

from scitaste.benchmark.study_adapter import (
    _audit_upstream_run,
    _compact_refinement_log,
    _condition_context,
    _contract_matches,
    _guidance,
    _normalize_refinement_metrics,
    _selected_experiment,
    _stage_completed,
    _usage,
    _write_prompt_overrides,
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


def test_prompt_override_freezes_plan_and_single_file_code(tmp_path) -> None:
    path = _write_prompt_overrides(tmp_path, load_task())
    override = yaml.safe_load(path.read_text(encoding="utf-8"))

    design = override["stages"]["experiment_design"]["user"]
    code = override["stages"]["code_generation"]["user"]
    assert "no GPU, no network, and no external dataset" in design
    assert "SCITASTE_BENCHMARK_CONTRACT" in code
    assert "exactly one" in override["stages"]["code_generation"]["system"]
    assert "diagnosis-factorial-v1" in design
    assert "never assert that condition outputs" in code
    assert "Do not add an LLM call" in code
    improve = override["sub_prompts"]["iterative_improve"]["user"]
    assert "[7, 19, 31]" in improve
    assert "do not add, remove, rename" in improve
    assert "Equal outputs are a valid" in improve
    decision = override["stages"]["research_decision"]["user"]
    assert "write exactly PROCEED" in decision
    assert "future work" in decision


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
        "## Result\nBalanced accuracy was 0.75.", encoding="utf-8"
    )
    (tmp_path / "stage-15").mkdir()
    (tmp_path / "stage-15" / "decision.md").write_text("## Decision\nPIVOT\n", encoding="utf-8")
    (tmp_path / "stage-17").mkdir()
    (tmp_path / "stage-17" / "paper_draft.md").write_text("paper", encoding="utf-8")

    outcome, experiments, audit = _audit_upstream_run(
        tmp_path, elapsed_seconds=360, task=load_task()
    )

    assert experiments == outcome.total_experiments == 1
    assert outcome.useful_results == 1
    assert outcome.proposed_ideas == 2
    assert outcome.pivots == 1
    assert outcome.correct_pivots == 0
    assert audit["numerical_evidence_present"] is True
    assert audit["selected_experiment"]["metric"] == 0.75


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

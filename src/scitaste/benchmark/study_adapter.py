"""Real AutoResearchClaw-backed adapters for the four core study conditions.

The adapter starts from one frozen task brief (stage 7), lets the pinned upstream
pipeline generate hypotheses through final artifacts, and varies only the
registered augmentation. It never synthesizes successful launcher results when
the upstream process fails.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from scitaste.benchmark.study_execution import LauncherResult, LauncherUsage
from scitaste.benchmark.study_models import (
    CellStatus,
    EvidenceClass,
    StudyOutcome,
    SystemCondition,
)
from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.retriever import TasteRetriever

REPOSITORY = Path(__file__).resolve().parents[3]
UPSTREAM = REPOSITORY / "third_party" / "autoresearchclaw"
UPSTREAM_COMMIT = "12d3fd809fa9658e91a0328c3280a0e462c78386"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def run_study_cell(
    *,
    request_path: str | Path,
    result_path: str | Path,
    to_stage: str = "CITATION_VERIFY",
    max_output_tokens: int = 8192,
    resume_existing: bool = False,
    resume_from_stage: str = "RESULT_ANALYSIS",
    finalize_existing: bool = False,
    reuse_existing: bool = False,
) -> LauncherResult:
    request_file = Path(request_path).resolve()
    result_file = Path(result_path).resolve()
    cell_dir = request_file.parent
    request = json.loads(request_file.read_text(encoding="utf-8"))
    condition = SystemCondition(request["cell"]["condition"])
    task_path = _resolve_task_asset(request_file, request["task"]["asset_path"])
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    _validate_inputs(request, task_path)

    upstream_run = cell_dir / "upstream_run"
    upstream_run.mkdir(parents=True, exist_ok=True)
    telemetry_path = cell_dir / "llm_telemetry.jsonl"
    if reuse_existing:
        if _stage_completed(upstream_run, to_stage):
            finalize_existing = True
        elif _stage_completed(upstream_run, "ITERATIVE_REFINE"):
            resume_existing = True
    if finalize_existing:
        resume_existing = True
    if resume_existing:
        trace_path = upstream_run / "condition_trace.json"
        config_path = upstream_run / "config.yaml"
        if not trace_path.is_file() or not config_path.is_file():
            raise ValueError("resume requested but existing run metadata is incomplete")
        controller_trace = json.loads(trace_path.read_text(encoding="utf-8"))
    else:
        controller_trace = _condition_context(condition, task, cell_dir, request)
        _prepare_stage_seven(upstream_run, task, condition, controller_trace)
        config_path = _write_upstream_config(
            upstream_run, task, condition, controller_trace, request
        )
        telemetry_path.unlink(missing_ok=True)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPOSITORY / "src"), str(UPSTREAM), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    environment["SCITASTE_ARC_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)
    environment["SCITASTE_ARC_MAX_TOTAL_TOKENS"] = str(request["cell"]["budget"]["max_llm_tokens"])
    environment["SCITASTE_ARC_TELEMETRY_PATH"] = str(telemetry_path)
    environment["SCITASTE_ARC_DISABLE_THINKING"] = "1"
    environment["SCITASTE_ARC_OFFLINE"] = "1"

    def upstream_command(from_stage: str, through_stage: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "scitaste.executor.arc_bootstrap",
            "run",
            "--config",
            str(config_path),
            "--output",
            str(upstream_run),
            "--from-stage",
            from_stage,
            "--to-stage",
            through_stage,
            "--auto-approve",
            "--skip-preflight",
        ]

    started = time.perf_counter()
    if resume_existing:
        experiment_returncode = 0
    else:
        experiment_process = subprocess.run(
            upstream_command("HYPOTHESIS_GEN", "ITERATIVE_REFINE"),
            cwd=UPSTREAM,
            env=environment,
            check=False,
            text=True,
        )
        experiment_returncode = experiment_process.returncode
    if experiment_returncode == 0:
        try:
            _normalize_refinement_metrics(
                upstream_run,
                str(task["benchmark"]["primary_metric"]),
                str(task["benchmark"]["metric_direction"]),
                condition_names=[str(item) for item in task["benchmark"]["conditions"]],
            )
            _validate_selected_experiment(upstream_run, task)
            selected_evidence = _write_selected_experiment_evidence(upstream_run, task)
            _write_guidance_files(
                upstream_run,
                _guidance(task, condition, controller_trace, evidence=selected_evidence),
            )
            _compact_refinement_log(upstream_run)
        except (OSError, ValueError) as exc:
            result = LauncherResult(
                status=CellStatus.FAILED,
                evidence_class=EvidenceClass.REAL,
                usage=_usage(telemetry_path, task, experiments=0),
                error=f"experiment pre-paper audit failed: {exc}",
            )
            _write_result(result_file, result)
            return result
        if finalize_existing:
            completed = subprocess.CompletedProcess(args=[], returncode=0)
        else:
            completed = subprocess.run(
                upstream_command(resume_from_stage, to_stage),
                cwd=UPSTREAM,
                env=environment,
                check=False,
                text=True,
            )
    else:
        completed = experiment_process
    elapsed = time.perf_counter() - started
    if finalize_existing:
        elapsed = _recorded_stage_seconds(upstream_run)
    if completed.returncode != 0:
        result = LauncherResult(
            status=CellStatus.FAILED,
            evidence_class=EvidenceClass.REAL,
            usage=_usage(telemetry_path, task, experiments=0),
            error=f"AutoResearchClaw exited with status {completed.returncode}",
        )
        _write_result(result_file, result)
        return result

    try:
        outcome, experiments, audit = _audit_upstream_run(
            upstream_run, elapsed_seconds=elapsed, task=task
        )
        artifact_paths = _materialize_artifacts(cell_dir, upstream_run, controller_trace, audit)
        result = LauncherResult(
            status=CellStatus.SUCCEEDED,
            evidence_class=EvidenceClass.REAL,
            usage=_usage(telemetry_path, task, experiments=experiments),
            outcome=outcome,
            artifact_paths=artifact_paths,
        )
    except (OSError, ValueError) as exc:
        result = LauncherResult(
            status=CellStatus.FAILED,
            evidence_class=EvidenceClass.REAL,
            usage=_usage(telemetry_path, task, experiments=0),
            error=f"upstream artifact audit failed: {exc}",
        )
    _write_result(result_file, result)
    return result


def _resolve_task_asset(request_path: Path, asset_path: str) -> Path:
    candidate = Path(asset_path)
    if candidate.is_absolute():
        return candidate
    for parent in request_path.parents:
        resolved = parent / candidate
        if resolved.is_file():
            return resolved.resolve()
    resolved = REPOSITORY / candidate
    if resolved.is_file():
        return resolved.resolve()
    raise ValueError(f"task asset does not exist: {asset_path}")


def _recorded_stage_seconds(run_dir: Path) -> float:
    total = 0.0
    for path in run_dir.glob("stage-*/stage_health.json"):
        try:
            total += float(json.loads(path.read_text(encoding="utf-8")).get("duration_sec", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return total


def _stage_completed(run_dir: Path, stage: str) -> bool:
    numbers = {
        "ITERATIVE_REFINE": 13,
        "RESULT_ANALYSIS": 14,
        "RESEARCH_DECISION": 15,
        "PAPER_OUTLINE": 16,
        "PAPER_DRAFT": 17,
        "PEER_REVIEW": 18,
        "PAPER_REVISION": 19,
        "QUALITY_GATE": 20,
        "KNOWLEDGE_ARCHIVE": 21,
        "EXPORT_PUBLISH": 22,
        "CITATION_VERIFY": 23,
    }
    number = numbers.get(stage.upper())
    if number is None:
        return False
    for path in run_dir.glob(f"stage-{number:02d}*/stage_health.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("status") == "done":
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def _validate_inputs(request: dict[str, Any], task_path: Path) -> None:
    actual_hash = _sha256(task_path)
    expected_hash = request["task"]["asset_sha256"]
    if actual_hash != expected_hash:
        raise ValueError(
            f"task asset hash mismatch: expected {expected_hash}, observed {actual_hash}"
        )
    process = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode or process.stdout.strip() != UPSTREAM_COMMIT:
        raise ValueError("AutoResearchClaw does not match the audited commit")
    snapshot = str(request["search_access"]["frozen_snapshot"])
    declared = str(task_path.parent.joinpath("frozen_search_snapshot_v1.json").resolve())
    snapshot_path = Path(declared)
    if not snapshot_path.is_file() or snapshot != f"sha256:{_sha256(snapshot_path)}":
        raise ValueError("frozen search snapshot is missing or does not match the protocol")


def _condition_context(
    condition: SystemCondition,
    task: dict[str, Any],
    cell_dir: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "schema_version": "1.0",
        "condition": condition.value,
        "knowledge_document_ids": [],
        "taste_case_ids": [],
        "controller_decision": None,
    }
    if condition in {SystemCondition.KNOWLEDGE_RAG, SystemCondition.FULL_SCITASTE}:
        trace["knowledge_document_ids"] = [
            item["document_id"] for item in task.get("knowledge_documents", [])
        ]
    if condition in {SystemCondition.TASTE_LIBRARY, SystemCondition.FULL_SCITASTE}:
        trace["taste_case_ids"] = [item["case_id"] for item in task.get("taste_cases", [])]
    if condition != SystemCondition.FULL_SCITASTE:
        return trace

    library = TasteLibrary(cell_dir / "taste_library.jsonl")
    provenance = ProvenanceRecord(
        source_type="curated-study-task",
        locator=request["task"]["asset_path"],
        content_hash=request["task"]["asset_sha256"],
        access_scope="derived decision annotation",
        derivation_method="preregistered task design",
        redistributable=True,
        personal_data_removed=True,
    )
    for raw in task.get("taste_cases", []):
        library.add(
            TasteCase.model_validate(
                {
                    **raw,
                    "provenance": [provenance.model_dump(mode="json")],
                    "human_verified": True,
                    "retrieval_eligible": True,
                    "label_basis": "project_curated",
                }
            )
        )
    actions = [ResearchAction.model_validate(item) for item in task["candidate_actions"]]
    cell = request["cell"]
    budget = cell["budget"]
    state = ResearchState(
        project_id=cell["cell_id"],
        research_direction=request["task"]["research_direction"],
        target_domain=request["task"]["domain"],
        resource_budget=ResourceBudget(
            gpu_hours=budget["gpu_hours"],
            max_experiments=budget["max_experiments"],
            max_wall_time_hours=budget["max_wall_time_hours"],
            max_api_cost_usd=budget["max_api_cost_usd"],
        ),
    )
    decision = TasteController(
        seed=cell["seed"],
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(library),
    ).decide(state=state, candidate_actions=actions)
    trace["controller_decision"] = decision.model_dump(mode="json")
    return trace


def _prepare_stage_seven(
    run_dir: Path,
    task: dict[str, Any],
    condition: SystemCondition,
    trace: dict[str, Any],
) -> None:
    for stage_number in range(8, 24):
        shutil.rmtree(run_dir / f"stage-{stage_number:02d}", ignore_errors=True)
    stage = run_dir / "stage-07"
    stage.mkdir(parents=True, exist_ok=True)
    common = task["research_brief"].strip()
    cards = "\n\n".join(
        f"### {item['title']} [{item['document_id']}]\n{item['content']}"
        for item in task.get("knowledge_documents", [])
    )
    synthesis = f"# Frozen synthesis: {task['research_direction']}\n\n{common}\n"
    if condition in {SystemCondition.KNOWLEDGE_RAG, SystemCondition.FULL_SCITASTE}:
        synthesis += f"\n## Retrieved structured knowledge\n\n{cards}\n"
    else:
        synthesis += f"\n## Frozen search snapshot excerpts\n\n{cards}\n"
    (stage / "synthesis.md").write_text(synthesis, encoding="utf-8")
    (stage / "topic_manifest.json").write_text(
        json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    checkpoint = {
        "last_completed_stage": 7,
        "last_completed_name": "SYNTHESIS",
        "run_id": run_dir.parent.name,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "scitaste.benchmark.study_adapter",
    }
    (run_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "condition_trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _write_upstream_config(
    run_dir: Path,
    task: dict[str, Any],
    condition: SystemCondition,
    trace: dict[str, Any],
    request: dict[str, Any],
) -> Path:
    guidance = _guidance(task, condition, trace)
    benchmark = task["benchmark"]
    prompt_overrides = _write_prompt_overrides(run_dir, task)
    config = {
        "project": {
            "name": request["cell"]["cell_id"],
            "mode": "full-auto",
            "profile": "ml_generic",
        },
        "research": {
            "topic": (
                "Execute the frozen synthetic benchmark contract "
                f"{benchmark['contract']['generator']}"
            ),
            "domains": [task["domain"]],
            "daily_paper_count": 0,
            "quality_threshold": 3.5,
            "graceful_degradation": False,
        },
        "runtime": {
            "timezone": "Asia/Shanghai",
            "max_parallel_tasks": 1,
            "approval_timeout_hours": 1,
            "retry_limit": 1,
        },
        "notifications": {
            "channel": "console",
            "target": "",
            "on_stage_start": False,
            "on_stage_fail": True,
            "on_gate_required": False,
        },
        "knowledge_base": {"backend": "markdown", "root": str(run_dir / "kb")},
        "openclaw_bridge": {
            "use_cron": False,
            "use_message": False,
            "use_memory": False,
            "use_sessions_spawn": False,
            "use_web_fetch": False,
            "use_browser": False,
        },
        "llm": {
            "provider": "openai-compatible",
            "base_url": os.environ.get("SCITASTE_LLM_BASE_URL", DEFAULT_BASE_URL),
            "wire_api": "chat_completions",
            "api_key_env": os.environ.get("SCITASTE_LLM_API_KEY_ENV", "DASHSCOPE_API_KEY"),
            "api_key": "",
            "primary_model": request["base_model_revision"],
            "fallback_models": [],
            "timeout_sec": 600,
        },
        "security": {
            "hitl_required_stages": [],
            "allow_publish_without_approval": True,
            "redact_sensitive_logs": True,
        },
        "experiment": {
            "mode": "sandbox",
            "time_budget_sec": 1200,
            # One refinement is enough to exercise real repair while preserving the
            # preregistered per-cell token envelope for stages 14--19.
            "max_iterations": 1,
            "metric_key": benchmark["primary_metric"],
            "metric_direction": benchmark["metric_direction"],
            "sandbox": {
                "python_path": str(REPOSITORY / ".venv" / "bin" / "python"),
                "gpu_required": False,
                "max_memory_mb": 8192,
                "allowed_imports": [
                    "numpy",
                    "scipy",
                    "sklearn",
                    "pandas",
                    "matplotlib",
                    "json",
                    "time",
                    "os",
                    "sys",
                    "math",
                    "random",
                    "collections",
                    "itertools",
                    "functools",
                    "typing",
                    "dataclasses",
                    "pathlib",
                    "csv",
                ],
            },
            "opencode": {"enabled": False},
            "code_agent": {"enabled": False},
            "benchmark_agent": {
                "enabled": False,
                "enable_hf_search": False,
                "enable_web_search": False,
            },
            "figure_agent": {
                "enabled": False,
                "nano_banana_enabled": False,
                "strict_mode": False,
            },
            # Stage 13 already performs the single preregistered repair. A second
            # post-analysis repair can silently replace an audited experiment.
            "repair": {"enabled": False},
        },
        "prompts": {
            "custom_file": str(prompt_overrides),
            "extra_prompts": _write_guidance_files(run_dir, guidance),
        },
        "web_search": {
            "enabled": False,
            "enable_scholar": False,
            "enable_crawling": False,
            "enable_pdf_extraction": False,
        },
    }
    path = run_dir / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _write_prompt_overrides(run_dir: Path, task: dict[str, Any]) -> Path:
    """Constrain the two generative execution stages to the frozen task contract."""

    benchmark = task["benchmark"]
    contract = json.dumps(benchmark["contract"], sort_keys=True, ensure_ascii=False)
    conditions = ", ".join(benchmark["conditions"])
    override = {
        "stages": {
            "experiment_design": {
                "system": (
                    "You design a preregistered benchmark execution. The supplied SciTaste "
                    "contract overrides novelty, benchmark-modernity, and scale suggestions."
                ),
                "user": (
                    "{preamble}\n\nProduce YAML with keys objectives, datasets, baselines, "
                    "proposed_methods, ablations, metrics, risks, compute_budget. Execute this "
                    f"immutable contract exactly: {contract}. Required conditions: {conditions}. "
                    "Use only deterministic synthetic data, numpy.random.default_rng with the "
                    "listed seeds, one CPU process, no GPU, no network, and no external dataset. "
                    "Do not add, remove, rename, or substitute factors, counts, conditions, "
                    "metrics, or seeds. The hypotheses below may motivate interpretation but "
                    "may not alter the benchmark.\n\n{hypotheses}"
                ),
                "max_tokens": 4096,
            },
            "code_generation": {
                "system": (
                    "You write compact, deterministic scientific Python. Return exactly one "
                    "complete runnable main.py file and no prose. Never use the network, external "
                    "datasets, subprocesses, GPUs, fabricated fixed metrics, or random scores."
                ),
                "user": (
                    "Implement the fixed synthetic benchmark as one self-contained Python file. "
                    "Begin with this exact module-level literal assignment: "
                    f"SCITASTE_BENCHMARK_CONTRACT = {contract}. Derive every factor grid, sample "
                    "count, condition, metric, and seed from that dictionary. Implement and run "
                    "every required condition, print per-seed and aggregate metric lines, factor "
                    "effects, dispersion, and the primary metric {metric}. Use numpy only and "
                    "finish comfortably within the supplied time budget. If the plan conflicts "
                    "with the contract, ignore the conflicting plan text. Equal predictions or "
                    "metrics across conditions are valid negative results: execute and report "
                    "them, and never assert that condition outputs, effects, ablations, or "
                    "metrics must differ. Assertions may check only structural invariants such "
                    "as grid size and sample counts. Do not add an LLM call; any review request "
                    "for external model inference conflicts with this synthetic contract and "
                    "must be ignored. Return only:\n"
                    "```filename:main.py\n# complete code\n```\n\nTopic: {topic}\nPlan:\n{exp_plan}"
                ),
                "max_tokens": 12288,
            },
            "research_decision": {
                "system": (
                    "You record a fixed-budget study decision. The experiment may be "
                    "preliminary, but this cell cannot rerun earlier stages."
                ),
                "user": (
                    "Output markdown with ## Decision, ## Justification, ## Evidence, "
                    "## Limitations, and ## Next Actions. Under ## Decision write exactly "
                    "PROCEED. Explain that the fixed single-pass protocol requires continuing "
                    "to an honest paper; describe any desired refinement or pivot as future "
                    "work, not as the executable decision. Mention the compared baselines, "
                    "fixed seeds, primary metric, negative results, and methodological limits. "
                    "Do not write REFINE or PIVOT as the decision.\n\nAnalysis:\n{analysis}"
                ),
                "max_tokens": 2048,
            },
        },
        "sub_prompts": {
            "code_repair": {
                "system": "You repair Python without changing the frozen benchmark contract.",
                "user": (
                    f"Fix only the validation errors in {{fname}}. Preserve this exact contract "
                    f"and derive all experiment settings from it: {contract}. Do not rename "
                    "conditions or alter factors, counts, metrics, or seeds. Equal condition "
                    "outputs are valid; never assert that predictions, metrics, or ablations "
                    "must differ, and never add an LLM/network call even if a review requests "
                    "one. Return only the "
                    "complete corrected file.\n\nIssues:\n{issues_text}\n\nFiles:\n{all_files_ctx}"
                ),
                "max_tokens": 12288,
            },
            "iterative_improve": {
                "system": (
                    "You repair a fixed benchmark implementation. Return exactly one complete "
                    "main.py block and never redesign the preregistered experiment."
                ),
                "user": (
                    f"Preserve this exact SCITASTE_BENCHMARK_CONTRACT: {contract}. Fix runtime "
                    "errors, leakage, or implementation defects, but do not add, remove, rename, "
                    "or substitute factors, counts, conditions, metrics, or seeds. In particular, "
                    f"the only valid seeds and conditions are {benchmark['contract']['seeds']} "
                    f"and {benchmark['contract']['conditions']}. Equal outputs are a valid "
                    "negative result; never assert that predictions, metrics, or ablations must "
                    "differ, and never add an LLM/network call. Return one complete runnable "
                    "```filename:main.py block.\n\nPlan:\n{exp_plan_anchor}\nCurrent code:\n"
                    "{files_context}\nRun summary:\n{run_summaries}"
                ),
                "max_tokens": 12288,
            },
            "iterative_repair": {
                "system": "You fix syntax/runtime errors while preserving a frozen contract.",
                "user": (
                    f"Fix all validation issues, preserving this exact contract: {contract}. "
                    "Do not alter factors, counts, conditions, metrics, or seeds. Equal outputs "
                    "are valid; never assert results must differ and never add an LLM/network "
                    "call. Return corrected "
                    "Python only.\n\nIssues:\n{issue_text}\n\nFiles:\n{all_files_ctx}"
                ),
                "max_tokens": 12288,
            },
        },
    }
    path = run_dir / "scitaste_prompt_overrides.yaml"
    path.write_text(yaml.safe_dump(override, sort_keys=False), encoding="utf-8")
    return path


def _write_guidance_files(run_dir: Path, guidance: dict[str, str]) -> dict[str, str]:
    prompt_dir = run_dir / "scitaste_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for stage, content in guidance.items():
        path = prompt_dir / f"{stage}.md"
        path.write_text(content + "\n", encoding="utf-8")
        paths[stage] = str(path)
    return paths


def _guidance(
    task: dict[str, Any],
    condition: SystemCondition,
    trace: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, str]:
    benchmark = task["benchmark"]
    serialized_contract = json.dumps(benchmark["contract"], sort_keys=True, ensure_ascii=False)
    execution_common = (
        "Use only the frozen task synthesis. Do not perform live retrieval. "
        "The benchmark contract below is IMMUTABLE: do not replace factors, sample "
        "counts, conditions, metrics, or seeds with alternatives. In every generated "
        "Python entry point declare SCITASTE_BENCHMARK_CONTRACT exactly equal to this "
        f"JSON object and derive the generator from it: {serialized_contract}. "
        "Implement and execute the preregistered fixed-generator benchmark exactly. "
        f"Primary metric: {benchmark['primary_metric']} ({benchmark['metric_direction']}). "
        f"Required conditions: {', '.join(benchmark['conditions'])}. "
        f"Fixed seeds: {benchmark['seeds']}. Preserve negative results and report dispersion."
    )
    execution_additions: list[str] = []
    if condition in {SystemCondition.KNOWLEDGE_RAG, SystemCondition.FULL_SCITASTE}:
        execution_additions.append(
            "Treat the 'Retrieved structured knowledge' cards as factual constraints and "
            "retain their document IDs in the internal evidence trail."
        )
    if condition in {SystemCondition.TASTE_LIBRARY, SystemCondition.FULL_SCITASTE}:
        cases = task.get("taste_cases", [])
        execution_additions.append(
            "Apply these decision precedents without treating them as factual evidence:\n"
            + "\n".join(
                f"- {item['case_id']}: {item['decision_principle']} "
                f"Preferred={item['preferred_action']}; rejected={item['rejected_actions']}."
                for item in cases
            )
        )
    if condition == SystemCondition.FULL_SCITASTE:
        decision = trace["controller_decision"]
        execution_additions.append(
            "SciTaste selected the next high-level action before upstream execution: "
            f"{decision['selected_action']['type']} — "
            f"{decision['selected_action']['description']}. Follow this ordering and preserve "
            "the alternatives in the analysis."
        )
    execution_text = execution_common + (
        "\n\n" + "\n\n".join(execution_additions) if execution_additions else ""
    )
    publication_text = _publication_guidance(task, evidence=evidence)
    guidance = {
        name: execution_text for name in ("hypothesis_gen", "experiment_design", "code_generation")
    }
    guidance.update(
        {
            name: publication_text
            for name in (
                "result_analysis",
                "research_decision",
                "paper_outline",
                "paper_draft",
                "peer_review",
                "paper_revision",
            )
        }
    )
    guidance["research_decision"] += (
        "\n\nThis matched-budget cell is a fixed single-pass execution. Preserve any "
        "recommended pivot or refinement as a written finding, but the structured "
        "pipeline decision must be CONTINUE so that the audit trail and paper are "
        "completed without rerunning earlier stages."
    )
    return guidance


def _publication_guidance(task: dict[str, Any], *, evidence: dict[str, Any] | None = None) -> str:
    """Build condition-blind, publication-facing guidance for analysis and writing."""

    benchmark = task["benchmark"]
    public_conditions = ", ".join(_public_term(str(item)) for item in benchmark["conditions"])
    text = (
        "Write the scientific analysis and manuscript for external readers, not an internal "
        "run report. The study topic is: "
        f"{task['research_direction']} Use the descriptive phrase 'the preregistered "
        "factorial benchmark' rather than any generator, task, document, case, action, cell, "
        "stage, adapter, or framework identifier. Do not emit code variable names, serialized "
        "contracts, snake_case labels, run paths, or the names of compared orchestration "
        "conditions. Refer to the experimental methods in prose as "
        f"{public_conditions}. Knowledge-card IDs are provenance metadata, not citations; use "
        "ordinary scholarly citations instead. Preserve negative results and methodological "
        "limitations, but never infer execution failure from a superseded attempt."
    )
    if evidence is None:
        return text + (
            " The adapter will append the authoritative selected-experiment evidence before "
            "analysis starts; do not substitute metrics from earlier attempts."
        )

    metrics = evidence.get("registered_metrics", {})
    metric_lines = "; ".join(
        f"{_public_term(str(name))}={float(value):.6f}"
        for name, value in metrics.items()
        if isinstance(value, (int, float))
    )
    stdout_summary = _publication_safe_text(str(evidence.get("stdout_summary", "")), task)
    return (
        text + "\n\nAUTHORITATIVE SELECTED-EXPERIMENT EVIDENCE (this supersedes every earlier "
        "failed attempt): execution completed with return code 0; "
        f"elapsed={float(evidence.get('elapsed_sec') or 0):.6f} seconds; {metric_lines}. "
        "Treat these as executed measurements, not cached, phantom, fabricated, or missing "
        "metrics. Any earlier crash may be mentioned only as a repaired implementation attempt, "
        "never as the scientific result.\n" + stdout_summary
    )


def _public_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _publication_safe_text(text: str, task: dict[str, Any]) -> str:
    replacements = {
        str(task.get("task_id", "")): "the preregistered task",
        str(task["benchmark"]["contract"].get("generator", "")): (
            "the preregistered factorial benchmark"
        ),
        "SCITASTE_BENCHMARK_CONTRACT": "the preregistered benchmark specification",
    }
    for condition_name in task["benchmark"]["conditions"]:
        replacements[str(condition_name)] = _public_term(str(condition_name))
    for item in task.get("knowledge_documents", []):
        replacements[str(item.get("document_id", ""))] = str(item.get("title", "the source"))
    for item in task.get("taste_cases", []):
        replacements[str(item.get("case_id", ""))] = "the registered decision precedent"
    for item in task.get("candidate_actions", []):
        replacements[str(item.get("action_id", ""))] = _public_term(str(item.get("type", "action")))
    for source, target in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
        if source:
            text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    return text


def _extract_declared_contract(source_paths: list[Path]) -> dict[str, Any] | None:
    for path in source_paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "SCITASTE_BENCHMARK_CONTRACT"
                for target in targets
            ):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                return None
            return value if isinstance(value, dict) else None
    return None


def _contract_matches(observed: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if observed is None:
        return False
    normalized = dict(observed)
    normalized.setdefault("generator", normalized.get("name"))
    normalized.setdefault("conditions", normalized.get("baselines"))
    if "metrics" not in normalized:
        normalized["metrics"] = [
            value
            for value in (
                normalized.get("primary_metric"),
                normalized.get("secondary_metric"),
            )
            if value is not None
        ]
    return all(normalized.get(key) == value for key, value in expected.items())


def _selected_experiment(run_dir: Path, primary_metric: str) -> tuple[list[Path], dict[str, Any]]:
    logs = sorted(
        run_dir.glob("stage-13*/refinement_log.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not logs:
        raise ValueError("refinement log is missing")
    log_path = logs[-1]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    best_version = str(log.get("best_version", ""))
    selected = next(
        (
            item
            for item in log.get("iterations", [])
            if str(item.get("version_dir", "")) == best_version
        ),
        None,
    )
    if selected is None:
        attempts = [
            int((item.get("sandbox_after_fix") or item.get("sandbox") or {}).get("returncode", 1))
            for item in log.get("iterations", [])
        ]
        raise ValueError(
            "no successful refined experiment was selected; "
            f"best_version={best_version!r}, iteration_returncodes={attempts}"
        )
    compact_sandbox = _best_successful_sandbox(selected)
    rich_selected = selected
    full_log_path = log_path.with_name("refinement_log.full.json")
    if full_log_path.is_file():
        try:
            full_log = json.loads(full_log_path.read_text(encoding="utf-8"))
            rich_selected = next(
                (
                    item
                    for item in full_log.get("iterations", [])
                    if str(item.get("version_dir", "")) == best_version
                ),
                selected,
            )
        except (OSError, json.JSONDecodeError):
            rich_selected = selected
    sandbox = _best_successful_sandbox(rich_selected) or compact_sandbox
    if sandbox is None:
        raise ValueError("selected refined experiment did not exit successfully")
    metrics = dict(sandbox.get("metrics") or {})
    if compact_sandbox is not None:
        metrics.update(compact_sandbox.get("metrics") or {})
    if primary_metric not in metrics and not any(
        str(key).endswith(f"/{primary_metric}") for key in metrics
    ):
        raise ValueError(f"selected refined experiment lacks {primary_metric}")
    source_dir = log_path.parent / best_version
    sources = sorted(source_dir.rglob("*.py"))
    if not sources:
        raise ValueError("selected refined experiment source is missing")
    stdout = str(sandbox.get("stdout", ""))
    stderr = str(sandbox.get("stderr", ""))
    return sources, {
        "refinement_log": str(log_path.relative_to(run_dir)),
        "best_version": best_version,
        "metric": selected.get("metric"),
        "metrics": metrics,
        "elapsed_sec": sandbox.get("elapsed_sec"),
        "returncode": int(sandbox.get("returncode", 1)),
        "timed_out": bool(sandbox.get("timed_out", False)),
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "stdout_summary": _selected_stdout_summary(stdout),
        "metric_normalization": selected.get("metric_normalization"),
        "source_sha256": {str(path.relative_to(run_dir)): _sha256(path) for path in sources},
    }


def _best_successful_sandbox(iteration: dict[str, Any]) -> dict[str, Any] | None:
    """Choose the richest successful execution record retained by upstream."""

    candidates = [
        item
        for item in (iteration.get("sandbox_after_fix"), iteration.get("sandbox"))
        if isinstance(item, dict) and int(item.get("returncode", 1)) == 0
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (bool(item.get("metrics")), len(str(item.get("stdout", "")))),
    )


def _selected_stdout_summary(stdout: str) -> str:
    """Retain bounded, human-auditable measurements from selected stdout."""

    markers = (
        "total cells",
        "total examples",
        "primary metric summary",
        "primary metric ",
        "condition:",
        "seed ",
        ": mean=",
        "overall_",
        "aggregate ",
        "dispersion ",
        "effect size",
        "interaction:",
        "drop(",
        "benchmark execution complete",
    )
    lines = [
        line.rstrip()
        for line in stdout.splitlines()
        if any(marker in line.casefold() for marker in markers)
    ]
    return "\n".join(lines[-160:])[-16000:]


def _write_selected_experiment_evidence(run_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    """Persist the sole authoritative execution projection used after Stage 13."""

    _, selected = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    registered_names = [
        *[str(item) for item in task["benchmark"]["conditions"]],
        str(task["benchmark"]["primary_metric"]),
    ]
    registered_metrics = {
        name: float(selected["metrics"][name])
        for name in registered_names
        if name in selected["metrics"] and isinstance(selected["metrics"][name], (int, float))
    }
    primary = str(task["benchmark"]["primary_metric"])
    if primary not in registered_metrics:
        raise ValueError(f"selected evidence lacks registered primary metric {primary}")
    evidence = {
        "schema_version": "1.0",
        "method": "selected-successful-refinement-evidence-v1",
        "authority": "supersedes-earlier-experiment-attempts",
        "execution_status": "completed",
        "returncode": selected["returncode"],
        "timed_out": selected["timed_out"],
        "elapsed_sec": selected["elapsed_sec"],
        "primary_metric": primary,
        "primary_metric_value": registered_metrics[primary],
        "registered_metrics": registered_metrics,
        "best_version": selected["best_version"],
        "refinement_log": selected["refinement_log"],
        "metric_normalization": selected["metric_normalization"],
        "stdout_sha256": selected["stdout_sha256"],
        "stderr_sha256": selected["stderr_sha256"],
        "stdout_summary": selected["stdout_summary"],
        "source_sha256": selected["source_sha256"],
    }
    path = run_dir / "scitaste_selected_experiment_evidence.json"
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return evidence


def _normalize_refinement_metrics(
    run_dir: Path,
    primary_metric: str,
    metric_direction: str,
    *,
    condition_names: list[str] | None = None,
) -> None:
    """Normalize real numeric stdout when upstream's parser misses ``name=value``."""

    candidates = sorted(
        run_dir.glob("stage-13*/refinement_log.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise ValueError("refinement log is missing")
    path = candidates[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    successful: list[tuple[float, dict[str, Any]]] = []
    escaped = re.escape(primary_metric)
    overall_pattern = re.compile(
        rf"(?im)^\s*overall\s+(?:mean\s+)?{escaped}\s*[=:]\s*([-+]?\d+(?:\.\d+)?)"
    )
    aggregate_pattern = re.compile(rf"(?im)^.*{escaped}.*?aggregate\s*[=:]\s*([-+]?\d+(?:\.\d+)?)")
    direct_pattern = re.compile(
        rf"(?im)^\s*(?:primary\s+metric\s+)?{escaped}\s*[=:]\s*([-+]?\d+(?:\.\d+)?)"
    )
    for iteration in data.get("iterations", []):
        sandbox = _best_successful_sandbox(iteration)
        if sandbox is None:
            continue
        metrics = sandbox.get("metrics") or {}
        value = metrics.get(primary_metric)
        if iteration.get("metric_normalization", {}).get("method") == (
            "stdout-numeric-equals-to-structured-v1"
        ):
            value = None
        sources: list[float] = []
        if value is None and condition_names and all(name in metrics for name in condition_names):
            try:
                sources = [float(metrics[name]) for name in condition_names]
            except (TypeError, ValueError):
                sources = []
            if sources and value is None:
                value = sum(sources) / len(sources)
                metrics[primary_metric] = round(value, 10)
                sandbox["metrics"] = metrics
                iteration["metric_normalization"] = {
                    "method": "registered-condition-mean-to-structured-v1",
                    "source_conditions": condition_names,
                    "source_values": sources,
                    "aggregate": "arithmetic_mean",
                }
        if value is None:
            stdout = str(sandbox.get("stdout", ""))
            if condition_names:
                condition_values: list[float] = []
                for name in condition_names:
                    condition_pattern = re.compile(
                        rf"(?im)^\s*{re.escape(name)}\s*:\s*"
                        rf"(?:(?:mean|(?:overall_)?{escaped})\s*[=:]\s*)?"
                        r"([-+]?\d+(?:\.\d+)?)"
                    )
                    block_pattern = re.compile(
                        rf"(?im)^\s*condition\s*:\s*{re.escape(name)}\s*$"
                        rf"[\s\S]{{0,240}}?^\s*(?:primary\s+metric\s+)?{escaped}\s*:\s*"
                        r"(?:mean\s*[=:]\s*)?([-+]?\d+(?:\.\d+)?)"
                    )
                    matches = condition_pattern.findall(stdout) or block_pattern.findall(stdout)
                    if not matches:
                        condition_values = []
                        break
                    condition_values.append(float(matches[-1]))
                if condition_values:
                    sources = condition_values
                    value = sum(sources) / len(sources)
                    metrics.update(dict(zip(condition_names, sources, strict=True)))
                    metrics[primary_metric] = round(value, 10)
                    sandbox["metrics"] = metrics
                    iteration["metric_normalization"] = {
                        "method": "stdout-registered-condition-mean-v1",
                        "source_conditions": condition_names,
                        "source_values": sources,
                        "aggregate": "arithmetic_mean",
                    }
            if value is None:
                sources = [float(item) for item in overall_pattern.findall(stdout)]
            if not sources:
                sources = [float(item) for item in aggregate_pattern.findall(stdout)]
            if not sources:
                sources = [float(item) for item in direct_pattern.findall(stdout)]
            if sources and value is None:
                value = sum(sources) / len(sources)
                metrics[primary_metric] = round(value, 10)
                sandbox["metrics"] = metrics
                iteration["metric_normalization"] = {
                    "method": "stdout-numeric-equals-to-structured-v1",
                    "source_values": sources,
                    "aggregate": "arithmetic_mean",
                }
        if value is not None:
            value = float(value)
            iteration["metric"] = value
            successful.append((value, iteration))
    if successful:
        chooser = min if metric_direction == "minimize" else max
        best_value, best = chooser(successful, key=lambda pair: pair[0])
        data["best_metric"] = best_value
        data["best_version"] = best["version_dir"]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _validate_selected_experiment(run_dir: Path, task: dict[str, Any]) -> None:
    sources, _ = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    observed = _extract_declared_contract(sources)
    if not _contract_matches(observed, task["benchmark"]["contract"]):
        raise ValueError("selected experiment does not preserve the frozen benchmark contract")
    forbidden_network = re.compile(
        r"(?i)(https?://|\brequests\.|urllib\.request|load_dataset\s*\(|download\s*\()"
    )
    violations = [path.name for path in sources if forbidden_network.search(path.read_text())]
    if violations:
        raise ValueError(
            "selected experiment violates frozen-network policy: " + ", ".join(violations)
        )


def _compact_refinement_log(run_dir: Path) -> Path:
    """Keep complete evidence while removing prompt-duplicate cell metrics."""

    candidates = sorted(
        run_dir.glob("stage-13*/refinement_log.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise ValueError("refinement log is missing")
    path = candidates[-1]
    full_path = path.with_name("refinement_log.full.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("scitaste_compaction") and full_path.is_file():
        return full_path
    if not full_path.is_file():
        shutil.copy2(path, full_path)
    for iteration in data.get("iterations", []):
        for key in ("sandbox", "sandbox_after_fix"):
            sandbox = iteration.get(key)
            if not isinstance(sandbox, dict):
                continue
            metrics = sandbox.get("metrics") or {}
            sandbox["metrics"] = {
                name: value
                for name, value in metrics.items()
                if not str(name).startswith("ba_s") and str(name).count("/") <= 2
            }
            stdout = str(sandbox.get("stdout", ""))
            summary_lines = [
                line
                for line in stdout.splitlines()
                if any(
                    marker in line for marker in ("SUMMARY", "_mean:", "_std:", "total_examples")
                )
            ]
            sandbox["stdout"] = "\n".join(summary_lines[-80:])
            sandbox["stderr"] = str(sandbox.get("stderr", ""))[-4000:]
    data["scitaste_compaction"] = {
        "schema_version": "1.0",
        "method": "prompt-context-deduplication-v1",
        "full_log": full_path.name,
        "full_log_sha256": _sha256(full_path),
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return full_path


def _publication_identifier_violations(text: str, task: dict[str, Any]) -> list[str]:
    terms = {
        "SCITASTE_BENCHMARK_CONTRACT",
        str(task.get("task_id", "")),
        str(task["benchmark"]["contract"].get("generator", "")),
        *[str(item) for item in task["benchmark"]["conditions"]],
        *[str(item.get("document_id", "")) for item in task.get("knowledge_documents", [])],
        *[str(item.get("case_id", "")) for item in task.get("taste_cases", [])],
        *[str(item.get("action_id", "")) for item in task.get("candidate_actions", [])],
        "Knowledge RAG",
        "Taste Library",
        "Full SciTaste",
        "AutoResearchClaw",
    }
    violations = sorted(
        term for term in terms if term and re.search(re.escape(term), text, re.IGNORECASE)
    )
    if re.search(r"(?i)\bstage-\d{2}\b", text):
        violations.append("stage-<number>")
    if re.search(r"(?i)\bcell-[0-9a-f]{8,}\b", text):
        violations.append("cell-<opaque-id>")
    if re.search(r"(?i)(?:^|[/\\])upstream_run(?:[/\\]|$)", text):
        violations.append("upstream_run path")
    return violations


def _text_reports_metric(text: str, name: str, value: float) -> bool:
    label = re.escape(_public_term(name)).replace(r"\ ", r"[\s_-]+")
    number = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?%?")
    for line in text.splitlines():
        if not re.search(label, _public_term(line), re.IGNORECASE):
            continue
        for match in number.findall(line):
            observed = float(match.rstrip("%"))
            if match.endswith("%"):
                observed /= 100
            if abs(observed - value) <= 0.0005:
                return True
    return False


def _artifact_consistency_audit(
    *, analysis: str, paper: str, selected_run: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    primary = str(task["benchmark"]["primary_metric"])
    value = selected_run["metrics"].get(primary, selected_run.get("metric"))
    if not isinstance(value, (int, float)):
        raise ValueError(f"selected experiment has no numeric {primary}")
    if int(selected_run.get("returncode", 1)) != 0 or selected_run.get("timed_out"):
        raise ValueError("selected experiment evidence is not a completed execution")

    failure_claims = {
        "experiment-did-not-execute": r"(?i)\b(?:the |this )?experiment did not execute\b",
        "no-scientific-test": (
            r"(?i)\bno scientific (?:hypothesis|computation|experiment) "
            r"(?:was|were) (?:tested|executed|performed)\b"
        ),
        "phantom-selected-metrics": (
            r"(?i)\b(?:reported|selected|resulting) metrics?.{0,80}"
            r"\b(?:phantom|cached|fabricated|epistemically void)\b"
        ),
        "failed-final-run": r"(?i)\brun status\s*[:=-]?\s*(?:was\s+)?failed\b",
        "false-positive-emission": r"(?i)\bfalse-positive emission rate\b",
    }
    contradictions = sorted(
        name
        for name, pattern in failure_claims.items()
        if re.search(pattern, analysis) or re.search(pattern, paper)
    )
    if contradictions:
        raise ValueError(
            "analysis/paper contradicts the successful selected experiment: "
            + ", ".join(contradictions)
        )

    analysis_metric = _text_reports_metric(analysis, primary, float(value))
    paper_metric = _text_reports_metric(paper, primary, float(value))
    if not analysis_metric or not paper_metric:
        missing = [
            label
            for label, present in (("analysis", analysis_metric), ("paper", paper_metric))
            if not present
        ]
        raise ValueError(
            f"selected {primary}={float(value):.6f} is absent from " + ", ".join(missing)
        )

    identifier_violations = _publication_identifier_violations(paper, task)
    if identifier_violations:
        raise ValueError(
            "paper exposes internal-only identifiers: " + ", ".join(identifier_violations)
        )
    return {
        "schema_version": "1.0",
        "method": "selected-evidence-publication-consistency-v1",
        "selected_execution_completed": True,
        "primary_metric": primary,
        "primary_metric_value": float(value),
        "analysis_reports_primary_metric": analysis_metric,
        "paper_reports_primary_metric": paper_metric,
        "failure_claim_contradictions": [],
        "publication_identifier_violations": [],
    }


def _audit_upstream_run(
    run_dir: Path, *, elapsed_seconds: float, task: dict[str, Any]
) -> tuple[StudyOutcome, int, dict[str, Any]]:
    hypotheses_path = run_dir / "stage-08" / "hypotheses.md"
    analysis_path = run_dir / "stage-14" / "analysis.md"
    decision_path = run_dir / "stage-15" / "decision.md"
    paper_candidates = [
        run_dir / "stage-19" / "paper_revised.md",
        run_dir / "stage-17" / "paper_draft.md",
    ]
    missing = [path for path in (hypotheses_path, analysis_path) if not path.is_file()]
    if missing:
        raise ValueError("required artifacts missing: " + ", ".join(str(p) for p in missing))
    paper_path = next((path for path in paper_candidates if path.is_file()), None)
    if paper_path is None:
        raise ValueError("paper draft/revision is missing")

    experiment_sources, selected_run = _selected_experiment(
        run_dir, str(task["benchmark"]["primary_metric"])
    )
    declared_contract = _extract_declared_contract(experiment_sources)
    if not _contract_matches(declared_contract, task["benchmark"]["contract"]):
        raise ValueError("selected experiment does not declare the frozen benchmark contract")
    forbidden_network = re.compile(
        r"(?i)(https?://|\brequests\.|urllib\.request|load_dataset\s*\(|download\s*\()"
    )
    network_sources = [
        path.relative_to(run_dir).as_posix()
        for path in experiment_sources
        if forbidden_network.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    if network_sources:
        raise ValueError(
            "generated experiment violates frozen-network policy: " + ", ".join(network_sources)
        )

    hypothesis_text = hypotheses_path.read_text(encoding="utf-8", errors="replace")
    analysis = analysis_path.read_text(encoding="utf-8", errors="replace")
    paper = paper_path.read_text(encoding="utf-8", errors="replace")
    consistency = _artifact_consistency_audit(
        analysis=analysis,
        paper=paper,
        selected_run=selected_run,
        task=task,
    )
    decision = (
        decision_path.read_text(encoding="utf-8", errors="replace")
        if decision_path.is_file()
        else ""
    )
    run_files = [p for p in run_dir.glob("stage-1[23]*/**/*") if p.is_file()]
    metric_files = [p for p in run_files if p.suffix.casefold() in {".json", ".csv"}]
    experiments = 1
    proposed = max(1, len(re.findall(r"(?im)^#{1,3}\s*(?:hypothesis|h\d+)", hypothesis_text)))
    numerical_evidence = consistency["analysis_reports_primary_metric"]
    useful = int(bool(run_files) and numerical_evidence)
    pivot = int(bool(re.search(r"(?im)^\s*(?:#+\s*)?(?:\*\*)?PIVOT\b", decision)))
    review_path = run_dir / "stage-18" / "reviews.md"
    review_text = (
        review_path.read_text(encoding="utf-8", errors="replace") if review_path.is_file() else ""
    )
    concern_count = len(re.findall(r"(?im)^\s*(?:[-*]|\d+[.)])\s+", review_text))
    total_claims = max(1, len(re.findall(r"(?im)^#{2,4}\s+", analysis)))
    unsupported = 0 if useful else total_claims
    evidence_components = (
        0.25 + 0.25 * bool(run_files) + 0.25 * numerical_evidence + 0.25 * bool(paper_path)
    )
    sufficiency = round(min(1.0, evidence_components), 3)
    outcome = StudyOutcome(
        useful_results=useful,
        proposed_ideas=proposed,
        valid_ideas=min(proposed, useful),
        pilots=int(bool(run_files)),
        discarded_ideas=max(0, proposed - max(1, useful)),
        unproductive_experiments=max(0, experiments - useful),
        total_experiments=experiments,
        gpu_hours_before_useful_signal=(elapsed_seconds / 3600 if useful else None),
        pivots=pivot,
        correct_pivots=0,
        evidence_sufficiency=sufficiency,
        reviewer_concerns_opened=concern_count,
        reviewer_concerns_closed=(
            concern_count if (run_dir / "stage-19" / "paper_revised.md").is_file() else 0
        ),
        total_claims=total_claims,
        unsupported_claims=unsupported,
    )
    audit = {
        "schema_version": "1.1",
        "method": "mechanical-artifact-and-consistency-audit-v2",
        "paper_source": str(paper_path.relative_to(run_dir)),
        "hypothesis_headings": proposed,
        "run_file_count": len(run_files),
        "metric_file_count": len(metric_files),
        "experiment_source_count": len(experiment_sources),
        "declared_benchmark_contract": declared_contract,
        "selected_experiment": selected_run,
        "artifact_consistency": consistency,
        "network_source_violations": network_sources,
        "numerical_evidence_present": numerical_evidence,
        "decision_pivot_detected": bool(pivot),
        "simulated_review_concerns": concern_count,
        "limitations": [
            "Correct-pivot attribution remains zero until blinded external review.",
            "Synthetic fixed-generator tasks measure controlled internal validity, "
            "not broad external validity.",
        ],
        "outcome": outcome.model_dump(mode="json"),
    }
    return outcome, experiments, audit


def _materialize_artifacts(
    cell_dir: Path,
    run_dir: Path,
    trace: dict[str, Any],
    audit: dict[str, Any],
) -> list[str]:
    paper_source = run_dir / audit["paper_source"]
    paper_target = cell_dir / "paper.md"
    shutil.copy2(paper_source, paper_target)
    evidence_source = run_dir / "scitaste_selected_experiment_evidence.json"
    if not evidence_source.is_file():
        raise ValueError("selected experiment evidence projection is missing")
    evidence_target = cell_dir / "selected_experiment_evidence.json"
    shutil.copy2(evidence_source, evidence_target)
    trace_path = cell_dir / "condition_trace.json"
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    audit_path = cell_dir / "outcome_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    entries = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            entries.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    manifest_path = cell_dir / "upstream_artifact_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "upstream_commit": UPSTREAM_COMMIT,
                "artifact_count": len(entries),
                "artifacts": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return [
        path.name
        for path in (
            paper_target,
            evidence_target,
            trace_path,
            audit_path,
            manifest_path,
        )
    ]


def _usage(path: Path, task: dict[str, Any], *, experiments: int) -> LauncherUsage:
    prompt = completion = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            prompt += int(item.get("prompt_tokens", 0))
            completion += int(item.get("completion_tokens", 0))
    pricing = task.get("pricing", {})
    input_cny = float(pricing.get("input_cny_per_million", 0.0))
    output_cny = float(pricing.get("output_cny_per_million", 0.0))
    cny_per_usd = float(pricing.get("cny_per_usd", 7.2))
    cost = ((prompt * input_cny + completion * output_cny) / 1_000_000) / cny_per_usd
    return LauncherUsage(
        experiments=experiments,
        api_cost_usd=round(cost, 8),
        search_queries=0,
        llm_tokens=prompt + completion,
    )


def _write_result(path: Path, result: LauncherResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one real matched-study condition cell")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--to-stage", default="CITATION_VERIFY")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--resume-from-stage", default="RESULT_ANALYSIS")
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    result = run_study_cell(
        request_path=args.request,
        result_path=args.result,
        to_stage=args.to_stage,
        max_output_tokens=args.max_output_tokens,
        resume_existing=args.resume_existing,
        resume_from_stage=args.resume_from_stage,
        finalize_existing=args.finalize_existing,
        reuse_existing=args.reuse_existing,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == CellStatus.SUCCEEDED else 1


if __name__ == "__main__":  # pragma: no cover - exercised as a condition process
    raise SystemExit(main())

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

from scitaste.benchmark.manuscript import materialize_manuscript
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
    environment["SCITASTE_ARC_TRACE_SANDBOX"] = "1"

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
            _write_analysis_synthesis_override(upstream_run, task, selected_evidence)
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
            completed = subprocess.CompletedProcess(args=[], returncode=0)
            target_stage_number = _stage_number(to_stage)
            if _stage_number(resume_from_stage) <= 14 <= target_stage_number:
                completed = subprocess.run(
                    upstream_command("RESULT_ANALYSIS", "RESULT_ANALYSIS"),
                    cwd=UPSTREAM,
                    env=environment,
                    check=False,
                    text=True,
                )
                if completed.returncode == 0:
                    try:
                        _sanitize_publication_artifacts(
                            upstream_run, task, relative_paths=("stage-14/analysis.md",)
                        )
                        _validate_analysis_artifact(upstream_run, task)
                    except (OSError, ValueError) as exc:
                        result = LauncherResult(
                            status=CellStatus.FAILED,
                            evidence_class=EvidenceClass.REAL,
                            usage=_usage(telemetry_path, task, experiments=1),
                            error=f"analysis pre-paper audit failed: {exc}",
                        )
                        _write_result(result_file, result)
                        return result
                next_stage = "RESEARCH_DECISION"
            else:
                _sanitize_publication_artifacts(
                    upstream_run, task, relative_paths=("stage-14/analysis.md",)
                )
                _validate_analysis_artifact(upstream_run, task)
                next_stage = resume_from_stage

            next_stage_number = _stage_number(next_stage)
            if completed.returncode == 0 and target_stage_number >= 16:
                if next_stage_number <= 16:
                    completed = subprocess.run(
                        upstream_command(next_stage, "PAPER_OUTLINE"),
                        cwd=UPSTREAM,
                        env=environment,
                        check=False,
                        text=True,
                    )
                    next_stage = "PAPER_DRAFT"
                    next_stage_number = 17
                if completed.returncode == 0:
                    try:
                        _sanitize_publication_artifacts(
                            upstream_run,
                            task,
                            relative_paths=(
                                "stage-14/analysis.md",
                                "stage-16/outline.md",
                            ),
                        )
                        _validate_outline_artifact(upstream_run, task)
                    except (OSError, ValueError) as exc:
                        result = LauncherResult(
                            status=CellStatus.FAILED,
                            evidence_class=EvidenceClass.REAL,
                            usage=_usage(telemetry_path, task, experiments=1),
                            error=f"outline pre-draft audit failed: {exc}",
                        )
                        _write_result(result_file, result)
                        return result

            if completed.returncode == 0 and target_stage_number >= 17:
                if next_stage_number <= 17:
                    completed = subprocess.run(
                        upstream_command(next_stage, "PAPER_DRAFT"),
                        cwd=UPSTREAM,
                        env=environment,
                        check=False,
                        text=True,
                    )
                    next_stage = "PEER_REVIEW"
                    next_stage_number = 18
                if completed.returncode == 0:
                    try:
                        _sanitize_publication_artifacts(
                            upstream_run,
                            task,
                            relative_paths=(
                                "stage-14/analysis.md",
                                "stage-16/outline.md",
                                "stage-17/paper_draft.md",
                            ),
                        )
                        _validate_paper_draft_artifact(upstream_run, task)
                    except (OSError, ValueError) as exc:
                        result = LauncherResult(
                            status=CellStatus.FAILED,
                            evidence_class=EvidenceClass.REAL,
                            usage=_usage(telemetry_path, task, experiments=1),
                            error=f"paper pre-review audit failed: {exc}",
                        )
                        _write_result(result_file, result)
                        return result

            if completed.returncode == 0 and next_stage_number <= target_stage_number:
                completed = subprocess.run(
                    upstream_command(next_stage, to_stage),
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

    _sanitize_publication_artifacts(
        upstream_run,
        task,
        relative_paths=(
            "stage-14/analysis.md",
            "stage-16/outline.md",
            "stage-17/paper_draft.md",
            "stage-18/reviews.md",
            "stage-19/paper_revised.md",
            "stage-22/paper_final.md",
            "stage-22/paper.tex",
        ),
    )

    try:
        outcome, experiments, audit = _audit_upstream_run(
            upstream_run, elapsed_seconds=elapsed, task=task
        )
        artifact_paths = _materialize_artifacts(
            cell_dir,
            upstream_run,
            controller_trace,
            audit,
        )
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


_STAGE_NUMBERS = {
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


def _stage_number(stage: str) -> int:
    try:
        return _STAGE_NUMBERS[stage.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown study adapter stage: {stage}") from exc


def _stage_completed(run_dir: Path, stage: str) -> bool:
    number = _STAGE_NUMBERS.get(stage.upper())
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
        f"### {item['title']} [{item['document_id']}]\n"
        + (
            f"Registered citation key: [{item['citation']['key']}]\n"
            if isinstance(item.get("citation"), dict)
            else ""
        )
        + str(item["content"])
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
    _write_frozen_bibliography(stage, task)
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


def _write_frozen_bibliography(stage_dir: Path, task: dict[str, Any]) -> tuple[Path, Path] | None:
    """Expose only task-registered scholarly sources to upstream writing stages."""

    citations = [
        item["citation"]
        for item in task.get("knowledge_documents", [])
        if isinstance(item.get("citation"), dict)
    ]
    if not citations:
        return None
    required = ("key", "title", "authors", "venue", "year", "url")
    for citation in citations:
        missing = [name for name in required if not citation.get(name)]
        if missing:
            raise ValueError("registered citation is incomplete: " + ", ".join(sorted(missing)))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", str(citation["key"])):
            raise ValueError(f"invalid registered citation key: {citation['key']!r}")
        if not isinstance(citation["authors"], list) or not all(
            isinstance(author, str) and author.strip() for author in citation["authors"]
        ):
            raise ValueError(f"registered citation authors are invalid: {citation['key']}")

    bibliography = []
    candidates = []
    for citation in citations:
        key = str(citation["key"])
        fields = [
            ("title", str(citation["title"])),
            ("author", " and ".join(str(author) for author in citation["authors"])),
            ("journal", str(citation["venue"])),
            ("year", str(citation["year"])),
            ("url", str(citation["url"])),
        ]
        for optional in ("volume", "pages", "doi"):
            if citation.get(optional):
                fields.append((optional, str(citation[optional])))
        rendered_fields = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
        bibliography.append(f"@article{{{key},\n{rendered_fields}\n}}")
        candidates.append(
            {
                "cite_key": key,
                "title": citation["title"],
                "authors": list(citation["authors"]),
                "venue": citation["venue"],
                "year": int(citation["year"]),
                "url": citation["url"],
                "doi": citation.get("doi"),
                "citation_count": 0,
                "source": "frozen-task-snapshot",
            }
        )
    bib_path = stage_dir / "references.bib"
    bib_path.write_text("\n\n".join(bibliography) + "\n", encoding="utf-8")
    candidates_path = stage_dir / "candidates.jsonl"
    candidates_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in candidates),
        encoding="utf-8",
    )
    return bib_path, candidates_path


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
            "paper_draft": {
                "system": (
                    "You write an evidence-bounded scientific manuscript from a frozen "
                    "experiment record. The pipeline calls you three times for disjoint section "
                    "batches. In every call, output only the sections explicitly requested by "
                    "the current user message; never repeat an earlier section or complete the "
                    "whole paper early. The authoritative selected-experiment evidence overrides "
                    "generic paper-writing requirements. With three registered seeds, report a "
                    "compact per-seed table and the observed descriptive dispersion; never emit "
                    "N=1, zero dispersion, or Min=Max=Mean summaries. Use only citation keys "
                    "listed under AVAILABLE REFERENCES, even when a generic instruction requests "
                    "more citations. Never invent numeric citations. Include a figure only when "
                    "its exact file is listed as available experiment evidence; never emit a "
                    "framework-diagram or chart placeholder. Do not claim neural-model execution "
                    "for a deterministic CPU simulation."
                ),
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


def _write_analysis_synthesis_override(
    run_dir: Path, task: dict[str, Any], evidence: dict[str, Any]
) -> Path:
    """Bind the debate synthesizer to selected evidence before Stage 14 starts."""

    path = run_dir / "scitaste_prompt_overrides.yaml"
    if not path.is_file():
        raise ValueError("prompt override file is missing")
    override = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    publication = _publication_guidance(task, evidence=evidence)
    override.setdefault("sub_prompts", {})["analysis_synthesize"] = {
        "system": (
            "You synthesize scientific analyses under a strict evidence contract. The "
            "authoritative selected-experiment evidence in the user prompt overrides every "
            "conflicting perspective, legacy run, inferred failure, or flattened summary."
        ),
        "user": (
            "Synthesize the perspectives into Metrics Summary, Consensus Findings, Contested "
            "Points, Statistical Checks, Methodology Audit, Limitations, and Conclusion. "
            "Correct rather than repeat any perspective that conflicts with the authoritative "
            "evidence. Explicitly report every registered method metric and the registered "
            "cross-method primary aggregate. A summary count of one denotes one selected run, "
            "not one seed and not zero variance. Preserve the three-seed measurements and "
            "descriptive dispersion; never emit an N=1 or Min=Max=Mean statistical summary. "
            "Do not expose any internal identifier.\n\n"
            "Perspectives:\n{perspectives}\n\n"
            f"{publication}"
        ),
        "max_tokens": 8192,
    }
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
    citation_keys = _registered_citation_keys(task)
    citation_text = ", ".join(f"[{key}]" for key in citation_keys) or "none"
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
        " This registered experiment is a deterministic, CPU-executable synthetic simulation. "
        "It does not run, train, probe, or evaluate a language model and provides no direct "
        "measurement of neural attention, calibration, internal confidence, or model latency. "
        "Describe the three methods as synthetic decision rules and their measurements as "
        "benchmark-simulation results; any connection to language-model behavior is a future "
        "empirical hypothesis, not an observed result. The only registered scholarly citation "
        f"keys are: {citation_text}. Use no other citation marker and never invent numbered "
        "references. A generic request for a larger bibliography does not override the frozen "
        "source set. Do not include an image, figure callout, or diagram placeholder unless its "
        "exact file is present in the supplied experiment artifacts."
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
    seed_ids = [int(item) for item in evidence.get("seed_ids", [])]
    seed_text = ", ".join(str(item) for item in seed_ids)
    return (
        text + "\n\nAUTHORITATIVE SELECTED-EXPERIMENT EVIDENCE (this supersedes every earlier "
        "failed attempt): execution completed with return code 0; "
        f"elapsed={float(evidence.get('elapsed_sec') or 0):.6f} seconds; {metric_lines}. "
        "Treat these as executed measurements, not cached, phantom, fabricated, or missing "
        "metrics. Any earlier crash may be mentioned only as a repaired implementation attempt, "
        "never as the scientific result. "
        f"This selected execution contains {len(seed_ids)} registered seeds ({seed_text}). "
        "The pipeline count of one means one selected run, not statistical N=1; never reproduce "
        "a Min=Max=Mean or N=1 table. Include one compact table containing every supplied "
        "per-seed value for every method, plus each method's observed mean and standard "
        "deviation; do not replace the matrix with selected examples.\n" + stdout_summary
    )


def _public_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _registered_citation_keys(task: dict[str, Any]) -> list[str]:
    return sorted(
        str(citation["key"])
        for item in task.get("knowledge_documents", [])
        if isinstance((citation := item.get("citation")), dict) and citation.get("key")
    )


def _publication_safe_text(text: str, task: dict[str, Any]) -> str:
    generator = str(task["benchmark"]["contract"].get("generator", ""))
    if generator:
        text = re.sub(
            rf"(?i)(?:the\s+)?frozen\s+synthetic\s+benchmark\s+contract\s+"
            rf"{re.escape(generator)}",
            "the preregistered factorial benchmark",
            text,
        )
    replacements = {
        str(task.get("task_id", "")): "the preregistered task",
        generator: "the preregistered factorial benchmark",
        str(task["benchmark"].get("primary_metric", "")): _public_term(
            str(task["benchmark"].get("primary_metric", ""))
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
    text = re.sub(
        r"(?i)\bthe preregistered factorial benchmark\s+(?:the preregistered factorial "
        r"benchmark|benchmark)\b",
        "the preregistered factorial benchmark",
        text,
    )
    text = re.sub(
        r"(?i)\bthe\s+the preregistered factorial benchmark\b",
        "the preregistered factorial benchmark",
        text,
    )
    return text


def _sanitize_publication_artifacts(
    run_dir: Path, task: dict[str, Any], *, relative_paths: tuple[str, ...]
) -> None:
    """Replace exact audit identifiers in prose while retaining a hash trail."""

    log_path = run_dir / "scitaste_publication_sanitization.json"
    if log_path.is_file():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log = {"schema_version": "1.0", "method": "exact-identifier-replacement-v1"}
    else:
        log = {"schema_version": "1.0", "method": "exact-identifier-replacement-v1"}
    entries = list(log.get("artifacts", []))
    seen = {(item.get("path"), item.get("before_sha256")) for item in entries}
    for relative in relative_paths:
        path = run_dir / relative
        if not path.is_file():
            continue
        before = path.read_text(encoding="utf-8", errors="replace")
        after = _publication_safe_text(before, task)
        if after == before:
            continue
        before_sha = hashlib.sha256(before.encode()).hexdigest()
        key = (relative, before_sha)
        if key in seen:
            continue
        path.write_text(after, encoding="utf-8")
        entries.append(
            {
                "path": relative,
                "before_sha256": before_sha,
                "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
                "replacement_scope": "registered exact internal identifiers only",
            }
        )
        seen.add(key)
    if entries:
        log["artifacts"] = entries
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    sandbox_key = next(
        (key for key in ("sandbox_after_fix", "sandbox") if rich_selected.get(key) is sandbox),
        "sandbox",
    )
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
    execution_trace = _selected_execution_trace(
        run_dir=run_dir,
        log_path=log_path,
        iteration=rich_selected,
        sandbox_key=sandbox_key,
        sandbox=sandbox,
        source_dir=source_dir,
        sources=sources,
    )
    if execution_trace is not None:
        stdout = str(execution_trace.get("stdout_excerpt", ""))
        stderr = str(execution_trace.get("stderr_excerpt", ""))
        stdout_sha256 = str(execution_trace["stdout_sha256"])
        stderr_sha256 = str(execution_trace["stderr_sha256"])
        execution_trace_summary: dict[str, Any] | None = {
            "path": execution_trace["relative_path"],
            "sha256": execution_trace["trace_sha256"],
            "sandbox_record": sandbox_key,
            "iteration": int(rich_selected.get("iteration", 0) or 0),
            "stdout_bytes": execution_trace["stdout_bytes"],
            "stderr_bytes": execution_trace["stderr_bytes"],
            "stdout_truncated": execution_trace["stdout_truncated"],
            "stderr_truncated": execution_trace["stderr_truncated"],
            "source_verified": True,
        }
    else:
        if sandbox_key == "sandbox_after_fix" and not stdout:
            raise ValueError("successful post-repair execution lacks an exact sandbox trace")
        stdout_sha256 = hashlib.sha256(stdout.encode()).hexdigest()
        stderr_sha256 = hashlib.sha256(stderr.encode()).hexdigest()
        execution_trace_summary = None
    stdout_seed_ids = sorted(
        {int(item) for item in re.findall(r"(?im)\bseed\s+([0-9]+)\b", stdout)}
    )
    per_seed_metrics, dispersion_metrics = _parse_seed_evidence(stdout, primary_metric)
    declared_contract = _extract_declared_contract(sources) or {}
    declared_seed_ids = sorted(
        int(item)
        for item in declared_contract.get("seeds", [])
        if isinstance(item, int) and not isinstance(item, bool)
    )
    unexpected_seed_ids = sorted(set(stdout_seed_ids) - set(declared_seed_ids))
    if declared_seed_ids and unexpected_seed_ids:
        raise ValueError(
            "selected execution reports seeds outside its declared contract: "
            + ", ".join(str(item) for item in unexpected_seed_ids)
        )
    source_sha256 = {str(path.relative_to(run_dir)): _sha256(path) for path in sources}
    return sources, {
        "refinement_log": str(log_path.relative_to(run_dir)),
        "best_version": best_version,
        "metric": selected.get("metric"),
        "metrics": metrics,
        "elapsed_sec": sandbox.get("elapsed_sec"),
        "returncode": int(sandbox.get("returncode", 1)),
        "timed_out": bool(sandbox.get("timed_out", False)),
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "stdout_summary": _selected_stdout_summary(stdout, primary_metric),
        "seed_ids": declared_seed_ids or stdout_seed_ids,
        "stdout_observed_seed_ids": stdout_seed_ids,
        "per_seed_metrics": per_seed_metrics,
        "dispersion_metrics": dispersion_metrics,
        "metric_normalization": selected.get("metric_normalization"),
        "source_sha256": source_sha256,
        "execution_trace": execution_trace_summary,
    }


def _selected_execution_trace(
    *,
    run_dir: Path,
    log_path: Path,
    iteration: dict[str, Any],
    sandbox_key: str,
    sandbox: dict[str, Any],
    source_dir: Path,
    sources: list[Path],
) -> dict[str, Any] | None:
    """Load and verify the process-local trace for the selected sandbox execution."""

    iteration_number = int(iteration.get("iteration", 0) or 0)
    if iteration_number <= 0:
        return None
    suffix = "_fix" if sandbox_key == "sandbox_after_fix" else ""
    trace_path = (
        log_path.parent
        / f"refine_sandbox_v{iteration_number}{suffix}"
        / "scitaste_execution_trace.json"
    )
    if not trace_path.is_file():
        return None
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"selected sandbox trace is unreadable: {exc}") from exc
    if int(trace.get("returncode", -1)) != int(sandbox.get("returncode", 1)):
        raise ValueError("selected sandbox trace return code does not match refinement log")
    if bool(trace.get("timed_out", False)) != bool(sandbox.get("timed_out", False)):
        raise ValueError("selected sandbox trace timeout status does not match refinement log")
    trace_metrics = trace.get("metrics") or {}
    trace_stdout = str(trace.get("stdout_excerpt", ""))
    normalization = iteration.get("metric_normalization") or {}
    source_conditions = list(normalization.get("source_conditions") or [])
    source_values = list(normalization.get("source_values") or [])
    normalized_names: set[str] = set()
    if source_conditions and len(source_conditions) == len(source_values):
        normalized_sources_verified = True
        numeric_source_values: list[float] = []
        for name, value in zip(source_conditions, source_values, strict=True):
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                normalized_sources_verified = False
                break
            traced_value = trace_metrics.get(name)
            trace_metric_matches = False
            if traced_value is not None:
                try:
                    trace_metric_matches = abs(float(traced_value) - numeric_value) <= 1e-9
                except (TypeError, ValueError):
                    trace_metric_matches = False
            if not trace_metric_matches and not _text_reports_metric(
                trace_stdout, str(name), numeric_value
            ):
                normalized_sources_verified = False
                break
            numeric_source_values.append(numeric_value)
        if normalized_sources_verified:
            normalized_names.update(str(name) for name in source_conditions)
            aggregate = sum(numeric_source_values) / len(numeric_source_values)
            normalized_names.update(
                str(name)
                for name, value in (sandbox.get("metrics") or {}).items()
                if isinstance(value, (int, float)) and abs(float(value) - aggregate) <= 1e-9
            )
    for name, value in (sandbox.get("metrics") or {}).items():
        if name not in trace_metrics:
            if name in normalized_names:
                continue
            raise ValueError(f"selected sandbox trace metric is missing: {name}")
        traced_value = trace_metrics.get(name)
        if isinstance(value, (int, float)):
            try:
                matches = abs(float(value) - float(traced_value)) <= 1e-9
            except (TypeError, ValueError):
                matches = False
            if not matches:
                raise ValueError(f"selected sandbox trace metric does not match: {name}")
    expected_sources = {path.relative_to(source_dir).as_posix(): _sha256(path) for path in sources}
    traced_sources = trace.get("project_source_sha256") or {}
    mismatched_sources = sorted(
        name for name, digest in expected_sources.items() if traced_sources.get(name) != digest
    )
    if mismatched_sources:
        raise ValueError(
            "selected sandbox trace source does not match: " + ", ".join(mismatched_sources)
        )
    required = (
        "stdout_sha256",
        "stderr_sha256",
        "stdout_bytes",
        "stderr_bytes",
        "stdout_truncated",
        "stderr_truncated",
    )
    missing = [name for name in required if name not in trace]
    if missing:
        raise ValueError("selected sandbox trace fields are missing: " + ", ".join(missing))
    if not trace["stdout_truncated"]:
        stdout = str(trace.get("stdout_excerpt", ""))
        if len(stdout.encode()) != int(trace["stdout_bytes"]):
            raise ValueError("selected sandbox trace stdout byte count does not match")
        if hashlib.sha256(stdout.encode()).hexdigest() != trace["stdout_sha256"]:
            raise ValueError("selected sandbox trace stdout hash does not match")
    return {
        **trace,
        "relative_path": trace_path.relative_to(run_dir).as_posix(),
        "trace_sha256": _sha256(trace_path),
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


def _selected_stdout_summary(stdout: str, primary_metric: str) -> str:
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
        primary_metric.casefold(),
        _public_term(primary_metric).casefold(),
    )
    lines = [
        line.rstrip()
        for line in stdout.splitlines()
        if any(marker in line.casefold() for marker in markers)
    ]
    return "\n".join(lines[-160:])[-16000:]


def _parse_seed_evidence(
    stdout: str, primary_metric: str
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Parse the registered per-seed matrix and descriptive dispersion from stdout."""

    per_seed: dict[str, dict[str, float]] = {}
    current_seed: str | None = None
    seed_pattern = re.compile(r"(?i)\bseed\s+([0-9]+)\b")
    metric_pattern = re.compile(
        rf"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*{re.escape(primary_metric)}\s*="
        r"\s*([-+]?\d+(?:\.\d+)?)"
    )
    dispersion_pattern = re.compile(
        rf"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*mean_{re.escape(primary_metric)}\s*="
        r"\s*([-+]?\d+(?:\.\d+)?),\s*std\s*=\s*([-+]?\d+(?:\.\d+)?)"
        r"(?:,\s*variance\s*=\s*([-+]?\d+(?:\.\d+)?))?",
        re.IGNORECASE,
    )
    dispersion: dict[str, dict[str, float]] = {}
    for line in stdout.splitlines():
        seed_match = seed_pattern.search(line)
        if seed_match and not metric_pattern.search(line):
            current_seed = seed_match.group(1)
            per_seed.setdefault(current_seed, {})
            continue
        metric_match = metric_pattern.search(line)
        if metric_match and current_seed is not None:
            per_seed[current_seed][metric_match.group(1)] = float(metric_match.group(2))
        dispersion_match = dispersion_pattern.search(line)
        if dispersion_match:
            values = {
                "mean": float(dispersion_match.group(2)),
                "std": float(dispersion_match.group(3)),
            }
            if dispersion_match.group(4) is not None:
                values["variance"] = float(dispersion_match.group(4))
            dispersion[dispersion_match.group(1)] = values
    return per_seed, dispersion


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
        "execution_semantics": {
            "synthetic_data": True,
            "cpu_executable": True,
            "language_model_inference": False,
            "neural_model_training": False,
        },
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
        "seed_ids": selected["seed_ids"],
        "stdout_observed_seed_ids": selected["stdout_observed_seed_ids"],
        "per_seed_metrics": selected["per_seed_metrics"],
        "dispersion_metrics": selected["dispersion_metrics"],
        "source_sha256": selected["source_sha256"],
        "execution_trace": selected["execution_trace"],
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
    sources, selected = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    observed = _extract_declared_contract(sources)
    if not _contract_matches(observed, task["benchmark"]["contract"]):
        raise ValueError("selected experiment does not preserve the frozen benchmark contract")
    if selected["execution_trace"] is None:
        raise ValueError("selected experiment lacks a source-verified sandbox trace")
    expected_seeds = sorted(int(item) for item in task["benchmark"]["contract"].get("seeds", []))
    if selected["seed_ids"] != expected_seeds:
        raise ValueError("selected experiment does not preserve the registered seed set")
    if selected["stdout_observed_seed_ids"] != expected_seeds:
        raise ValueError("selected execution stdout does not cover every registered seed")
    expected_conditions = [str(item) for item in task["benchmark"]["conditions"]]
    per_seed = selected["per_seed_metrics"]
    missing_seed_values = [
        f"seed={seed}:{condition}"
        for seed in expected_seeds
        for condition in expected_conditions
        if condition not in per_seed.get(str(seed), {})
    ]
    if missing_seed_values:
        raise ValueError(
            "selected execution lacks registered per-seed values: " + ", ".join(missing_seed_values)
        )
    dispersion = selected["dispersion_metrics"]
    missing_dispersion = [
        condition
        for condition in expected_conditions
        if not {"mean", "std"}.issubset(dispersion.get(condition, {}))
    ]
    if missing_dispersion:
        raise ValueError(
            "selected execution lacks registered seed dispersion: " + ", ".join(missing_dispersion)
        )
    inconsistent_means = [
        condition
        for condition in expected_conditions
        if condition in selected["metrics"]
        and abs(float(selected["metrics"][condition]) - dispersion[condition]["mean"]) > 5e-6
    ]
    if inconsistent_means:
        raise ValueError(
            "selected seed dispersion disagrees with registered metrics: "
            + ", ".join(inconsistent_means)
        )
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


def _text_contains_value(text: str, value: float, *, tolerance: float = 0.00005) -> bool:
    number = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?%?")
    for match in number.findall(text):
        observed = float(match.rstrip("%"))
        if match.endswith("%"):
            observed /= 100
        if abs(observed - value) <= tolerance:
            return True
    return False


def _seed_evidence_reporting_violations(
    text: str, selected_run: dict[str, Any], task: dict[str, Any]
) -> list[str]:
    violations: set[str] = set()
    for condition in task["benchmark"]["conditions"]:
        name = str(condition)
        value = selected_run.get("metrics", {}).get(name)
        if isinstance(value, (int, float)) and not _text_reports_metric(text, name, float(value)):
            violations.add(f"condition-mean-omitted:{name}")
    for seed, values in selected_run.get("per_seed_metrics", {}).items():
        for condition, value in values.items():
            if isinstance(value, (int, float)) and not _text_contains_value(text, float(value)):
                violations.add(f"per-seed-value-omitted:{condition}:seed-{seed}")
    for condition, values in selected_run.get("dispersion_metrics", {}).items():
        std = values.get("std") if isinstance(values, dict) else None
        if isinstance(std, (int, float)) and not _text_contains_value(text, float(std)):
            violations.add(f"seed-std-omitted:{condition}")
    return sorted(violations)


_FAILURE_CLAIMS = {
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


def _synthetic_claim_violations(text: str) -> list[str]:
    patterns = {
        "claimed-model-inference": (
            r"(?i)\b(?:actual|real|hosted|local) (?:LLM |language-model |model )?inference\b"
        ),
        "claimed-model-evaluation": (
            r"(?i)\b(?:language|large language) models? "
            r"(?:was|were|is|are|has been|have been) (?:evaluated|tested|run|trained)\b"
        ),
        "claimed-small-model-result": r"(?i)\b(?:using|with) smaller-scale models?\b",
        "claimed-internal-model-signal": (
            r"(?i)\b(?:internal (?:model )?(?:uncertainty|confidence|attention)|"
            r"leveraging model uncertainty)\b"
        ),
        "claimed-model-score": (
            r"(?i)\b(?:language|large language) models? "
            r"(?:achieved|obtained|scored|outperformed)\b"
        ),
    }
    corrective = re.compile(
        r"(?i)\b(?:does not|did not|no direct|not an? |rather than|incorrect|"
        r"incorrectly|invalid|falsely|erroneous|superseded|without (?:a )?neural|"
        r"future (?:empirical )?hypothesis|cannot be attributed)\b"
    )
    violations: set[str] = set()
    for line in text.splitlines():
        if corrective.search(line):
            continue
        violations.update(name for name, pattern in patterns.items() if re.search(pattern, line))
    return sorted(violations)


def _seed_claim_violations(text: str, seed_ids: list[int]) -> list[str]:
    if len(seed_ids) < 3:
        return []
    patterns = {
        "single-seed-collapse": r"(?i)(?:\bn\s*=\s*1\b|\bmin\s*=\s*max\s*=\s*mean\b)",
        "variance-unavailable": r"(?i)\binsufficient for variance estimation\b",
        "deterministic-collapse": r"(?i)\bdeterministic collapse(?:/bug)?\b",
    }
    corrective = re.compile(
        r"(?i)\b(?:not one seed|not zero variance|misinterpret|"
        r"denotes (?:exactly )?one selected run|must not be reported as n\s*=\s*1|"
        r"not statistical n\s*=\s*1|not an? n\s*=\s*1|incorrect|falsely|preclude|"
        r"superseded|do not reproduce|never (?:emit|report|reproduce))\b"
    )
    violations: set[str] = set()
    for line in text.splitlines():
        if corrective.search(line):
            continue
        violations.update(name for name, pattern in patterns.items() if re.search(pattern, line))
        public_method = re.search(
            r"(?i)(?:majority vote|confidence weighted vote|position aware probe|"
            r"cross[- ]method aggregate)",
            line,
        )
        if public_method and re.search(r"(?:±|\\pm\$?)\s*0(?:\.0+)?\b", line):
            violations.add("zero-seed-dispersion")
        if public_method and re.search(r"(?:\||&)\s*1\s*(?:\||\\\\|$)", line):
            violations.add("single-seed-table")
    if re.search(
        r"(?is)\bmean\b.{0,40}\b(?:standard deviation|std)\b.{0,40}"
        r"\bacross (?:the )?seeds?\b.{0,40}\b(?:identical|zero)\b",
        text,
    ):
        violations.add("zero-seed-dispersion")
    if re.search(
        r"(?is)\bmin(?:imum)?\b.{0,30}\bmax(?:imum)?\b.{0,30}\bmean\b.{0,30}"
        r"\b(?:identical|equal)\b",
        text,
    ):
        violations.add("single-seed-collapse")
    has_seed_count = bool(
        re.search(r"(?i)\b(?:three|3)\s+(?:(?:distinct|fixed|registered)\s+)*seeds?\b", text)
    )
    has_seed_ids = "seed" in text.casefold() and all(
        re.search(rf"(?<!\d){seed}(?!\d)", text) for seed in seed_ids
    )
    if not has_seed_count and not has_seed_ids:
        violations.add("registered-seed-set-omitted")
    return sorted(violations)


_REQUIRED_MANUSCRIPT_SECTIONS = (
    "title",
    "abstract",
    "introduction",
    "related work",
    "method",
    "experiments",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


def _canonical_manuscript_heading(heading: str) -> str:
    normalized = re.sub(r"^[0-9]+(?:\.[0-9]+)*[.)]?\s*", "", heading)
    normalized = re.sub(r"[*_`:#]", "", normalized).strip().casefold()
    aliases = {
        "methods": "method",
        "methodology": "method",
        "experiment": "experiments",
        "experimental setup": "experiments",
        "result": "results",
        "limitation": "limitations",
        "limitations and future work": "limitations",
        "conclusions": "conclusion",
    }
    return aliases.get(normalized, normalized)


def _manuscript_structure_violations(text: str) -> list[str]:
    headings = [
        _canonical_manuscript_heading(match.group(2))
        for match in re.finditer(r"(?m)^(#{1,2})\s+(.+?)\s*$", text)
    ]
    violations = {
        f"missing-section:{section}"
        for section in _REQUIRED_MANUSCRIPT_SECTIONS
        if section not in headings
    }
    violations.update(
        f"duplicate-section:{section}"
        for section in _REQUIRED_MANUSCRIPT_SECTIONS
        if headings.count(section) > 1
    )
    if re.search(r"(?i)\b(?:placeholder|(?:to|will) be (?:generated|inserted|completed))\b", text):
        violations.add("publication-placeholder")
    return sorted(violations)


def _citation_violations(text: str, task: dict[str, Any]) -> list[str]:
    allowed = set(_registered_citation_keys(task))
    without_math = re.sub(r"\$\$.*?\$\$|\$.*?\$", "", text, flags=re.DOTALL)
    numeric = set(re.findall(r"\[((?:\s*\d+\s*,)*\s*\d+\s*)\](?!\()", without_math))
    bracket_keys = set(
        re.findall(
            r"\[([A-Za-z][A-Za-z0-9_-]*\d{4}[A-Za-z0-9_-]*)\](?!\()",
            without_math,
        )
    )
    latex_keys: set[str] = set()
    for group in re.findall(r"\\cite[pt]?\{([^}]+)\}", without_math):
        latex_keys.update(key.strip() for key in group.split(",") if key.strip())
    violations = {"invented-numeric-citations"} if numeric else set()
    violations.update(
        f"unregistered-citation:{key}" for key in (bracket_keys | latex_keys) - allowed
    )
    if allowed and not (allowed & (bracket_keys | latex_keys)):
        violations.add("registered-citation-omitted")
    return sorted(violations)


def _publication_asset_violations(text: str, run_dir: Path) -> list[str]:
    violations: set[str] = set()
    for raw_target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        relative = Path(target)
        if relative.is_absolute() or ".." in relative.parts:
            violations.add(f"unsafe-image:{target}")
            continue
        if re.match(r"(?i)https?://", target):
            violations.add(f"remote-image:{target}")
            continue
        candidates = [run_dir / "stage-17" / target, run_dir / target]
        candidates.extend(stage / target for stage in run_dir.glob("stage-14*"))
        if not any(path.is_file() for path in candidates):
            violations.add(f"missing-image:{target}")
    return sorted(violations)


def _analysis_consistency_audit(
    *, analysis: str, selected_run: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    primary = str(task["benchmark"]["primary_metric"])
    value = selected_run["metrics"].get(primary, selected_run.get("metric"))
    if not isinstance(value, (int, float)):
        raise ValueError(f"selected experiment has no numeric {primary}")
    if int(selected_run.get("returncode", 1)) != 0 or selected_run.get("timed_out"):
        raise ValueError("selected experiment evidence is not a completed execution")

    contradictions = sorted(
        name for name, pattern in _FAILURE_CLAIMS.items() if re.search(pattern, analysis)
    )
    seed_ids = selected_run.get("seed_ids") or []
    contradictions.extend(_seed_claim_violations(analysis, seed_ids))
    contradictions = sorted(set(contradictions))
    contradictions.extend(_synthetic_claim_violations(analysis))
    contradictions = sorted(set(contradictions))
    if contradictions:
        raise ValueError(
            "analysis contradicts the successful selected experiment: " + ", ".join(contradictions)
        )
    metric_present = _text_reports_metric(analysis, primary, float(value))
    if not metric_present:
        raise ValueError(f"selected {primary}={float(value):.6f} is absent from analysis")
    identifier_violations = _publication_identifier_violations(analysis, task)
    if identifier_violations:
        raise ValueError(
            "analysis exposes internal-only identifiers: " + ", ".join(identifier_violations)
        )
    return {
        "selected_execution_completed": True,
        "primary_metric": primary,
        "primary_metric_value": float(value),
        "analysis_reports_primary_metric": True,
        "seed_ids": seed_ids,
        "failure_claim_contradictions": [],
        "analysis_identifier_violations": [],
    }


def _validate_analysis_artifact(run_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    analysis_path = run_dir / "stage-14" / "analysis.md"
    if not analysis_path.is_file():
        raise ValueError("result analysis artifact is missing")
    _, selected_run = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    return _analysis_consistency_audit(
        analysis=analysis_path.read_text(encoding="utf-8", errors="replace"),
        selected_run=selected_run,
        task=task,
    )


def _validate_paper_draft_artifact(run_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    analysis_path = run_dir / "stage-14" / "analysis.md"
    paper_path = run_dir / "stage-17" / "paper_draft.md"
    if not analysis_path.is_file():
        raise ValueError("result analysis artifact is missing")
    if not paper_path.is_file():
        raise ValueError("paper draft artifact is missing")
    _, selected_run = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    audit = _artifact_consistency_audit(
        analysis=analysis_path.read_text(encoding="utf-8", errors="replace"),
        paper=paper_path.read_text(encoding="utf-8", errors="replace"),
        selected_run=selected_run,
        task=task,
    )
    audit.update(
        _complete_manuscript_audit(
            paper_path.read_text(encoding="utf-8", errors="replace"),
            task=task,
            run_dir=run_dir,
        )
    )
    return audit


def _validate_outline_artifact(run_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    analysis_path = run_dir / "stage-14" / "analysis.md"
    outline_path = run_dir / "stage-16" / "outline.md"
    if not analysis_path.is_file():
        raise ValueError("result analysis artifact is missing")
    if not outline_path.is_file():
        raise ValueError("paper outline artifact is missing")
    _, selected_run = _selected_experiment(run_dir, str(task["benchmark"]["primary_metric"]))
    return _artifact_consistency_audit(
        analysis=analysis_path.read_text(encoding="utf-8", errors="replace"),
        paper=outline_path.read_text(encoding="utf-8", errors="replace"),
        selected_run=selected_run,
        task=task,
    )


def _artifact_consistency_audit(
    *, analysis: str, paper: str, selected_run: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    analysis_audit = _analysis_consistency_audit(
        analysis=analysis, selected_run=selected_run, task=task
    )
    primary = analysis_audit["primary_metric"]
    value = analysis_audit["primary_metric_value"]
    contradictions = sorted(
        name for name, pattern in _FAILURE_CLAIMS.items() if re.search(pattern, paper)
    )
    contradictions.extend(_synthetic_claim_violations(paper))
    contradictions.extend(_seed_claim_violations(paper, analysis_audit["seed_ids"]))
    contradictions = sorted(set(contradictions))
    if contradictions:
        raise ValueError(
            "paper contradicts the successful selected experiment: " + ", ".join(contradictions)
        )

    paper_metric = _text_reports_metric(paper, primary, float(value))
    if not paper_metric:
        raise ValueError(f"selected {primary}={float(value):.6f} is absent from paper")

    identifier_violations = _publication_identifier_violations(paper, task)
    if identifier_violations:
        raise ValueError(
            "paper exposes internal-only identifiers: " + ", ".join(identifier_violations)
        )
    seed_evidence_violations = _seed_evidence_reporting_violations(paper, selected_run, task)
    if seed_evidence_violations:
        raise ValueError(
            "paper omits selected seed evidence: " + ", ".join(seed_evidence_violations)
        )
    return {
        "schema_version": "1.0",
        "method": "selected-evidence-publication-consistency-v1",
        "selected_execution_completed": True,
        "primary_metric": primary,
        "primary_metric_value": float(value),
        "analysis_reports_primary_metric": True,
        "paper_reports_primary_metric": paper_metric,
        "seed_ids": analysis_audit["seed_ids"],
        "failure_claim_contradictions": [],
        "analysis_identifier_violations": [],
        "publication_identifier_violations": [],
        "seed_evidence_reporting_violations": [],
    }


def _complete_manuscript_audit(
    paper: str, *, task: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    structure = _manuscript_structure_violations(paper)
    citations = _citation_violations(paper, task)
    assets = _publication_asset_violations(paper, run_dir)
    violations = structure + citations + assets
    if violations:
        raise ValueError("paper is not publication-complete: " + ", ".join(violations))
    return {
        "manuscript_structure_complete": True,
        "registered_citations_only": True,
        "publication_assets_resolved": True,
        "manuscript_structure_violations": [],
        "citation_violations": [],
        "publication_asset_violations": [],
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
    consistency.update(_complete_manuscript_audit(paper, task=task, run_dir=run_dir))
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
    manuscript_paths = materialize_manuscript(
        markdown_path=paper_source,
        target_dir=cell_dir / "manuscript",
        bibliography_path=run_dir / "stage-07" / "references.bib",
        asset_roots=(
            run_dir / "stage-17",
            run_dir,
            *tuple(sorted(run_dir.glob("stage-14*"), reverse=True)),
        ),
    )
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
    core_paths = (
        paper_target,
        evidence_target,
        trace_path,
        audit_path,
        manifest_path,
    )
    return [path.relative_to(cell_dir).as_posix() for path in (*core_paths, *manuscript_paths)]


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

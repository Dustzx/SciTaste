"""SciTaste command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from scitaste.backends.local_transformers import (
    LocalTransformersBackend,
    load_local_transformers_config,
)
from scitaste.backends.openai_compatible import (
    OpenAICompatibleBackend,
    load_openai_compatible_config,
)
from scitaste.backends.replay import RecordingBackend, ReplayBackend
from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.benchmark import (
    BenchmarkCondition,
    MatchedStudyEvaluator,
    MatchedStudyPlanner,
    MatchedStudyRunner,
    ProjectMatchedStudyRunner,
    ProjectStudyConfig,
    SciTasteBenchRunner,
    SystemCondition,
    compare_model_boundaries,
    load_benchmark_report,
    load_benchmark_suite,
    load_study_launch_config,
    load_study_protocol,
    load_study_results,
    save_benchmark_report,
    save_boundary_comparison,
    save_study_plan,
    save_study_report,
    scripted_selections,
)
from scitaste.data.curation import CurationFormat, curate_snapshot
from scitaste.data.ingestion import audit_corpus_manifest, ingest_corpus
from scitaste.data.store import build_libraries
from scitaste.demo import run_nonlinear_demo
from scitaste.discovery.loop import DiscoveryLoop, load_discovery_scenario
from scitaste.evidence.workflow import EvidenceWorkflow, load_evidence_scenario
from scitaste.executor.autoresearchclaw import AutoResearchClawExecutor
from scitaste.executor.workflow import build_autoresearchclaw_workflow
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.generative_ui import ProjectSurfaceFactory
from scitaste.generative_ui.serve_cli import add_ui_commands
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.intrinsic import (
    IntrinsicTasteCalibrator,
    load_calibration_suite,
    save_calibration_report,
)
from scitaste.visual.workflow import FigureWorkflow, load_figure_scenario
from scitaste.writing.workflow import CommunicationWorkflow, load_communication_scenario


def _add_common_options(
    parser: argparse.ArgumentParser,
    *,
    default_output: str,
    default_backend: str = "mock",
) -> None:
    parser.add_argument("--seed", type=int, default=0, help="Deterministic selection seed")
    parser.add_argument("--output", type=Path, default=Path(default_output))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--backend", default=default_backend)
    parser.add_argument("--dry-run", action="store_true")
    _add_log_level_option(parser)


def _add_log_level_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _add_project_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--dry-run", action="store_true")
    _add_log_level_option(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scitaste", description="Scientific taste controller")
    parser.add_argument("--version", action="version", version="SciTaste 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    add_ui_commands(commands)

    baseline = commands.add_parser("baseline", help="Execution-substrate baseline commands")
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    baseline_run = baseline_commands.add_parser("run", help="Run the original substrate")
    baseline_run.add_argument("--topic", required=True)
    baseline_run.add_argument("--to-stage", default=None)
    baseline_run.add_argument("--max-output-tokens", type=int, default=None)
    _add_common_options(baseline_run, default_output="outputs/baseline")
    baseline_run.set_defaults(handler=_handle_baseline_run)

    substrate = commands.add_parser("substrate", help="Execute auditable substrate actions")
    substrate_commands = substrate.add_subparsers(dest="substrate_command", required=True)
    substrate_execute = substrate_commands.add_parser(
        "execute", help="Run one SciTaste-selected action through AutoResearchClaw"
    )
    _add_common_options(
        substrate_execute,
        default_output="outputs/substrate-action",
        default_backend="autoresearchclaw",
    )
    substrate_execute.add_argument(
        "--action",
        choices=[item.value for item in MetaAction],
        required=True,
    )
    substrate_execute.add_argument("--run-dir", type=Path, required=True)
    substrate_execute.add_argument("--state", type=Path, default=None)
    substrate_execute.add_argument("--project-id", default="scitaste-substrate-smoke")
    substrate_execute.add_argument(
        "--topic", default="Taste-guided control for autonomous scientific research"
    )
    substrate_execute.add_argument("--target-domain", default="autonomous-research")
    substrate_execute.add_argument("--timeout-seconds", type=float, default=1800.0)
    substrate_execute.add_argument("--max-output-tokens", type=int, default=1024)
    substrate_execute.set_defaults(handler=_handle_substrate_execute)

    run = commands.add_parser("run", help="End-to-end workflows")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    demo = run_commands.add_parser("demo", help="Run the Phase 1 nonlinear mock loop")
    _add_common_options(demo, default_output="outputs/demo")
    demo.set_defaults(handler=_handle_demo)
    full = run_commands.add_parser("full", help="Run the offline Phase 4-7 project workflow")
    _add_common_options(full, default_output="outputs")
    full.add_argument("--project-id", default=None)
    full.add_argument("--run-id", default=None)
    full.add_argument("--paper-directory", default=None)
    full.add_argument(
        "--resume",
        action="store_true",
        help="Resume one failed run from its validated contiguous stage prefix",
    )
    full.set_defaults(handler=_handle_full)

    project = commands.add_parser("project", help="Project-owned run and paper management")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_init = project_commands.add_parser("init", help="Create a canonical project tree")
    project_init.add_argument("--project-id", required=True)
    project_init.add_argument("--title", required=True)
    project_init.add_argument("--research-direction", required=True)
    project_init.add_argument("--target-domain", default=None)
    project_init.add_argument("--target-venue", default=None)
    project_init.add_argument("--status", default="active")
    project_init.add_argument("--stage-semantics", default="autoresearchclaw-stages")
    project_init.add_argument("--no-retrieval", action="store_true")
    _add_project_options(project_init)
    project_init.set_defaults(handler=_handle_project_init)

    project_status = project_commands.add_parser("status", help="Read a validated project snapshot")
    project_status.add_argument("--project-id", required=True)
    project_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(project_status)
    project_status.set_defaults(handler=_handle_project_status)

    project_surface = project_commands.add_parser(
        "surface", help="Build trusted project interface bundles"
    )
    project_surface_commands = project_surface.add_subparsers(
        dest="project_surface_command", required=True
    )
    project_surface_build = project_surface_commands.add_parser(
        "build", help="Build a content-addressed project overview"
    )
    project_surface_build.add_argument("--project-id", required=True)
    project_surface_build.add_argument("--destination", type=Path, required=True)
    _add_project_options(project_surface_build)
    project_surface_build.set_defaults(handler=_handle_project_surface_build)

    project_run = project_commands.add_parser("run", help="Register and select project runs")
    project_run_commands = project_run.add_subparsers(dest="project_run_command", required=True)
    project_run_begin = project_run_commands.add_parser("begin", help="Create a registered run")
    project_run_begin.add_argument("--project-id", required=True)
    project_run_begin.add_argument("--run-id", required=True)
    project_run_begin.add_argument("--provider", required=True)
    project_run_begin.add_argument("--model", required=True)
    project_run_begin.add_argument("--condition", required=True)
    project_run_begin.add_argument("--seed", type=int, default=0)
    project_run_begin.add_argument("--status", default="planned")
    project_run_begin.add_argument("--evidence-scope", default="engineering-only")
    project_run_begin.add_argument("--stage-path", default=None)
    project_run_begin.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_run_begin)
    project_run_begin.set_defaults(handler=_handle_project_run_begin)
    project_run_select = project_run_commands.add_parser("select", help="Select a current run")
    project_run_select.add_argument("--project-id", required=True)
    project_run_select.add_argument("--run-id", required=True)
    project_run_select.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_run_select)
    project_run_select.set_defaults(handler=_handle_project_run_select)

    project_paper = project_commands.add_parser("paper", help="Register and select paper bundles")
    project_paper_commands = project_paper.add_subparsers(
        dest="project_paper_command", required=True
    )
    project_paper_register = project_paper_commands.add_parser(
        "register", help="Register a materialized paper manifest"
    )
    project_paper_register.add_argument("--project-id", required=True)
    project_paper_register.add_argument("--directory-name", required=True)
    project_paper_register.add_argument("--manifest", type=Path, required=True)
    project_paper_register.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_paper_register)
    project_paper_register.set_defaults(handler=_handle_project_paper_register)
    project_paper_select = project_paper_commands.add_parser(
        "select", help="Select a current project paper"
    )
    project_paper_select.add_argument("--project-id", required=True)
    project_paper_select.add_argument("--directory-name", required=True)
    project_paper_select.add_argument("--expected-revision", type=int, required=True)
    project_paper_select.add_argument("--no-global-latest", action="store_true")
    _add_project_options(project_paper_select)
    project_paper_select.set_defaults(handler=_handle_project_paper_select)

    taste = commands.add_parser("taste", help="Scientific-taste calibration")
    taste_commands = taste.add_subparsers(dest="taste_command", required=True)
    calibrate = taste_commands.add_parser("calibrate", help="Run a fixed-candidate suite")
    _add_common_options(
        calibrate,
        default_output="outputs/calibration",
        default_backend="scripted",
    )
    calibrate.add_argument("--replay", type=Path, default=None)
    calibrate.add_argument("--record", type=Path, default=None)
    calibrate.add_argument(
        "--suite",
        type=Path,
        default=Path("configs/taste/intrinsic_calibration_v1.yaml"),
    )
    calibrate.set_defaults(handler=_handle_taste_calibrate)

    library = commands.add_parser("library", help="Knowledge and taste libraries")
    library_commands = library.add_subparsers(dest="library_command", required=True)
    library_build = library_commands.add_parser("build", help="Build separate local stores")
    _add_common_options(library_build, default_output="outputs/library")
    library_build.set_defaults(handler=_handle_library_build)
    library_ingest = library_commands.add_parser(
        "ingest", help="Ingest license-reviewed local corpus snapshots"
    )
    _add_common_options(
        library_ingest,
        default_output="outputs/library-ingest",
        default_backend="local",
    )
    library_ingest.set_defaults(handler=_handle_library_ingest)
    library_audit = library_commands.add_parser(
        "audit", help="Audit corpus rights declarations without reading snapshots"
    )
    _add_common_options(
        library_audit,
        default_output="outputs/library-audit",
        default_backend="local",
    )
    library_audit.set_defaults(handler=_handle_library_audit)
    library_curate = library_commands.add_parser(
        "curate", help="Project supported source snapshots into quarantined intake records"
    )
    _add_common_options(
        library_curate,
        default_output="outputs/library-curation",
        default_backend="local",
    )
    library_curate.add_argument("--input", type=Path, required=True)
    library_curate.add_argument(
        "--source-format",
        choices=[item.value for item in CurationFormat],
        required=True,
    )
    library_curate.add_argument("--limit", type=int, default=None)
    library_curate.set_defaults(handler=_handle_library_curate)
    discover = commands.add_parser("discover", help="Run the unified discovery loop")
    _add_common_options(discover, default_output="outputs/discovery")
    discover.set_defaults(handler=_handle_discover)
    _add_single_planned(commands, "hypothesize", "Phase 4")
    _add_single_planned(commands, "probe", "Phase 4")
    _add_single_planned(commands, "reformulate", "Phase 4")
    _add_single_planned(commands, "ideate", "Phase 4")
    _add_nested_planned(commands, "portfolio", "select", "Phase 4")
    evidence = commands.add_parser("evidence", help="Evidence-loop workflows")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_plan = evidence_commands.add_parser("plan", help="Plan and evaluate one evidence gap")
    _add_common_options(evidence_plan, default_output="outputs/evidence")
    evidence_plan.add_argument("--state", type=Path, default=None)
    evidence_plan.set_defaults(handler=_handle_evidence_plan)
    write = commands.add_parser("write", help="Run the evidence-grounded communication loop")
    _add_common_options(write, default_output="outputs/communication")
    write.set_defaults(handler=_handle_communication)
    review = commands.add_parser("review", help="Run reviewer-driven research and revision")
    _add_common_options(review, default_output="outputs/review")
    review.set_defaults(handler=_handle_communication)
    figure = commands.add_parser("figure", help="Contract-first editable figure workflows")
    figure_commands = figure.add_subparsers(dest="figure_command", required=True)
    figure_build = figure_commands.add_parser(
        "build", help="Build, critique, and patch an editable scientific figure"
    )
    _add_common_options(figure_build, default_output="outputs/figure")
    figure_build.set_defaults(handler=_handle_figure_build)
    benchmark = commands.add_parser("benchmark", help="Controlled SciTasteBench evaluation")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run = benchmark_commands.add_parser(
        "run", help="Compare intrinsic and augmented taste conditions"
    )
    _add_common_options(
        benchmark_run,
        default_output="outputs/benchmark",
        default_backend="scripted",
    )
    benchmark_run.add_argument(
        "--suite",
        type=Path,
        default=Path("configs/benchmark/scitastebench_v1.yaml"),
    )
    benchmark_run.add_argument(
        "--condition",
        action="append",
        choices=[condition.value for condition in BenchmarkCondition],
        default=None,
        help="Condition to run; repeat to select multiple conditions (base is required)",
    )
    benchmark_run.add_argument("--replay", type=Path, default=None)
    benchmark_run.add_argument("--record", type=Path, default=None)
    benchmark_run.set_defaults(handler=_handle_benchmark_run)
    benchmark_attribute = benchmark_commands.add_parser(
        "attribute", help="Separate model-specific misses from SciTaste regressions"
    )
    benchmark_attribute.add_argument("--primary-report", type=Path, required=True)
    benchmark_attribute.add_argument("--comparator-report", type=Path, required=True)
    benchmark_attribute.add_argument(
        "--output", type=Path, default=Path("outputs/capability-boundary")
    )
    _add_log_level_option(benchmark_attribute)
    benchmark_attribute.set_defaults(handler=_handle_benchmark_attribute)

    study = commands.add_parser("study", help="Matched-budget system-study operations")
    study_commands = study.add_subparsers(dest="study_command", required=True)
    study_plan = study_commands.add_parser("plan", help="Create a deterministic run matrix")
    _add_common_options(study_plan, default_output="outputs/matched-study", default_backend="local")
    study_plan.set_defaults(handler=_handle_study_plan)
    study_run = study_commands.add_parser(
        "run", help="Run isolated study cells through configured system launchers"
    )
    _add_common_options(
        study_run,
        default_output="outputs/matched-study-run",
        default_backend="local",
    )
    study_run.add_argument("--launch-config", type=Path, required=True)
    study_run.add_argument("--task", action="append", default=None)
    study_run.add_argument(
        "--condition",
        action="append",
        choices=[condition.value for condition in SystemCondition],
        default=None,
    )
    study_run.add_argument("--cell-id", action="append", default=None)
    study_run.add_argument("--max-cells", type=int, default=None)
    study_run.add_argument("--no-resume", action="store_true")
    study_run.set_defaults(handler=_handle_study_run)
    study_project_run = study_commands.add_parser(
        "project-run",
        help="Run integrity-checked study cells inside an existing project",
    )
    study_project_run.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/matched_budget_study_v1.yaml"),
    )
    study_project_run.add_argument("--launch-config", type=Path, required=True)
    study_project_run.add_argument("--project-id", required=True)
    study_project_run.add_argument("--run-id", required=True)
    study_project_run.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    study_project_run.add_argument("--provider", required=True)
    study_project_run.add_argument("--model", required=True)
    study_project_run.add_argument("--run-seed", type=int, default=0)
    study_project_run.add_argument(
        "--evidence-scope",
        default="phase9-engineering-evidence",
    )
    study_project_run.add_argument("--task", action="append", default=None)
    study_project_run.add_argument(
        "--condition",
        action="append",
        choices=[condition.value for condition in SystemCondition],
        default=None,
    )
    study_project_run.add_argument("--cell-id", action="append", default=None)
    study_project_run.add_argument("--max-cells", type=int, default=None)
    study_project_run.add_argument("--resume", action="store_true")
    study_project_run.add_argument("--dry-run", action="store_true")
    _add_log_level_option(study_project_run)
    study_project_run.set_defaults(handler=_handle_study_project_run)
    study_evaluate = study_commands.add_parser(
        "evaluate", help="Audit completed cells and blinded expert reviews"
    )
    _add_common_options(
        study_evaluate,
        default_output="outputs/matched-study-evaluation",
        default_backend="local",
    )
    study_evaluate.add_argument("--results", type=Path, required=True)
    study_evaluate.set_defaults(handler=_handle_study_evaluate)
    return parser


def _add_single_planned(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    milestone: str,
) -> None:
    command = commands.add_parser(name)
    _add_common_options(command, default_output=f"outputs/{name}")
    command.set_defaults(handler=_handle_planned, milestone=milestone)


def _add_nested_planned(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    operation: str,
    milestone: str,
) -> None:
    command = commands.add_parser(name)
    operations = command.add_subparsers(dest=f"{name}_command", required=True)
    leaf = operations.add_parser(operation)
    _add_common_options(leaf, default_output=f"outputs/{name}-{operation}")
    leaf.set_defaults(handler=_handle_planned, milestone=milestone)


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    return data


def _handle_project_init(args: argparse.Namespace) -> int:
    manifest = ProjectManifest(
        project_id=args.project_id,
        title=args.title,
        research_direction=args.research_direction,
        target_domain=args.target_domain,
        target_venue=args.target_venue,
        status=args.status,
        stage_semantics=args.stage_semantics,
        retrieval_eligible=not args.no_retrieval,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_locator": f"projects/{manifest.project_id}",
                    "manifest": manifest.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = ProjectRuntime(args.outputs_root).create(manifest)
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_status(args: argparse.Namespace) -> int:
    snapshot = ProjectRuntime(args.outputs_root).open(args.project_id)
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_surface_build(args: argparse.Namespace) -> int:
    factory = ProjectSurfaceFactory(ProjectRuntime(args.outputs_root))
    if args.dry_run:
        surface = factory.build_project_overview(args.project_id)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": surface.project_id,
                    "destination": str(args.destination),
                    "surface_fingerprint": surface.fingerprint,
                    "snapshot_sha256": surface.snapshot.snapshot_sha256,
                    "components": [item.component.value for item in surface.components],
                    "actions": [item.action_id for item in surface.actions],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    output = factory.write_project_overview(args.project_id, args.destination)
    print(
        json.dumps(
            {
                "status": "published",
                "project_id": output.surface.project_id,
                "destination": str(output.surface_path.parent),
                "surface_fingerprint": output.surface.fingerprint,
                "snapshot_sha256": output.surface.snapshot.snapshot_sha256,
                "files": {
                    "surface": str(output.surface_path),
                    "renderer": str(output.renderer_path),
                    "audit": str(output.audit_path),
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_run_begin(args: argparse.Namespace) -> int:
    run = ProjectRun(
        run_id=args.run_id,
        provider=args.provider,
        model=args.model,
        condition=args.condition,
        seed=args.seed,
        status=args.status,
        evidence_scope=args.evidence_scope,
        stage_path=args.stage_path,
    )
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "run": run.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = runtime.begin_run(
        args.project_id,
        run,
        expected_revision=args.expected_revision,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_run_select(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        if args.run_id not in snapshot.run_locators:
            raise ValueError(f"unknown project run {args.run_id!r}")
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "current_run": args.run_id,
                },
                indent=2,
            )
        )
        return 0
    snapshot = runtime.select_run(
        args.project_id,
        args.run_id,
        expected_revision=args.expected_revision,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_paper_register(args: argparse.Namespace) -> int:
    paper = PaperManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        if paper.project_id != args.project_id:
            raise ValueError("paper project_id must match the owning project")
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "paper": paper.model_dump(mode="json"),
                    "directory_name": args.directory_name,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = runtime.register_paper(
        args.project_id,
        paper,
        directory_name=args.directory_name,
        expected_revision=args.expected_revision,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_paper_select(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        known = {item.directory_name for item in snapshot.papers}
        if args.directory_name not in known:
            raise ValueError(f"unknown project paper {args.directory_name!r}")
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "current_paper": f"papers/{args.directory_name}",
                    "global_latest": not args.no_global_latest,
                },
                indent=2,
            )
        )
        return 0
    snapshot = runtime.select_paper(
        args.project_id,
        args.directory_name,
        expected_revision=args.expected_revision,
        global_latest=not args.no_global_latest,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_demo(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("Phase 1 demo supports only --backend mock")
    if args.dry_run:
        print(json.dumps({"status": "planned", "workflow": "nonlinear-demo"}, indent=2))
        return 0
    summary = run_nonlinear_demo(
        output_dir=args.output,
        seed=args.seed,
        config=_load_config(args.config),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_baseline_run(args: argparse.Namespace) -> int:
    executor = AutoResearchClawExecutor(
        config_path=args.config,
        dry_run=args.dry_run,
        max_output_tokens=args.max_output_tokens,
    )
    result = executor.baseline_run(
        topic=args.topic,
        output_dir=args.output,
        to_stage=args.to_stage,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status.value in {"PLANNED", "SUCCEEDED"} else 1


def _handle_substrate_execute(args: argparse.Namespace) -> int:
    if args.backend != "autoresearchclaw":
        raise ValueError("substrate execute supports only --backend autoresearchclaw")
    if args.config is None:
        raise ValueError("substrate execute requires an AutoResearchClaw --config PATH")
    action_type = MetaAction(args.action)
    if args.dry_run:
        result = AutoResearchClawExecutor(
            config_path=args.config,
            dry_run=True,
            timeout_seconds=args.timeout_seconds,
            max_output_tokens=args.max_output_tokens,
        ).execute(
            ResearchState(
                project_id=args.project_id,
                research_direction=args.topic,
                target_domain=args.target_domain,
                executor_context={"autoresearchclaw_run_dir": str(args.run_dir.resolve())},
            ),
            ResearchAction(
                action_id=f"dry-run-{action_type.value.casefold()}",
                type=action_type,
                description="Validate an AutoResearchClaw action contract",
            ),
        )
        print(result.model_dump_json(indent=2))
        return 0 if result.status.value in {"PLANNED", "SKIPPED"} else 1
    summary = build_autoresearchclaw_workflow(
        config_path=args.config,
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    ).run(
        action_type=action_type,
        run_dir=args.run_dir,
        output_dir=args.output,
        state_path=args.state,
        project_id=args.project_id,
        topic=args.topic,
        target_domain=args.target_domain,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["execution_status"] == "SUCCEEDED" else 1


def _handle_taste_calibrate(args: argparse.Namespace) -> int:
    suite = load_calibration_suite(args.suite)
    if args.dry_run:
        print(
            json.dumps(
                {"status": "planned", "suite_id": suite.suite_id, "cases": len(suite.cases)},
                indent=2,
            )
        )
        return 0
    if args.backend == "scripted":
        missing = [case.case_id for case in suite.cases if case.scripted_selection_id is None]
        if missing:
            raise ValueError(f"scripted selections missing for: {', '.join(missing)}")
        backend = ScriptedPreferenceBackend(
            {case.case_id: case.scripted_selection_id for case in suite.cases}
        )
    elif args.backend == "replay":
        if args.replay is None:
            raise ValueError("--backend replay requires --replay PATH")
        backend = ReplayBackend(args.replay)
    elif args.backend == "openai-compatible":
        if args.config is None:
            raise ValueError("--backend openai-compatible requires --config PATH")
        backend = OpenAICompatibleBackend(load_openai_compatible_config(args.config))
    elif args.backend == "local-transformers":
        if args.config is None:
            raise ValueError("--backend local-transformers requires --config PATH")
        backend = LocalTransformersBackend(load_local_transformers_config(args.config))
    else:
        raise ValueError(
            "supported calibration backends: scripted, replay, openai-compatible, "
            "local-transformers"
        )
    if args.record:
        backend = RecordingBackend(backend, args.record)
    report = IntrinsicTasteCalibrator(backend, seed=args.seed).evaluate(suite)
    report_path = args.output / "calibration_report.json"
    save_calibration_report(report, report_path)
    print(
        json.dumps(
            {
                "suite_id": report.suite_id,
                "backend": report.backend,
                "model": report.model,
                "accuracy": report.overall.accuracy,
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return 0


def _handle_library_build(args: argparse.Namespace) -> int:
    config_path = args.config or Path("configs/taste/library_seed_v1.yaml")
    if args.dry_run:
        config = _load_config(config_path)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "knowledge_count": len(config.get("knowledge_documents", [])),
                    "taste_count": len(config.get("taste_cases", [])),
                },
                indent=2,
            )
        )
        return 0
    manifest = build_libraries(config_path, args.output)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def _handle_library_ingest(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("library ingestion supports only --backend local")
    if args.config is None:
        raise ValueError("library ingest requires --config PATH")
    if args.dry_run:
        config = _load_config(args.config)
        print(
            json.dumps(
                {"status": "planned", "source_count": len(config.get("sources", []))},
                indent=2,
            )
        )
        return 0
    report = ingest_corpus(args.config, args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def _handle_library_audit(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("library audit supports only --backend local")
    if args.config is None:
        raise ValueError("library audit requires --config PATH")
    output_path = None if args.dry_run else args.output / "corpus_audit.json"
    report = audit_corpus_manifest(args.config, output_path)
    if output_path is not None:
        report["report"] = str(output_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["status_summary"].get("blocked", 0) else 0


def _handle_library_curate(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("library curation supports only --backend local")
    report = curate_snapshot(
        args.source_format,
        args.input,
        args.output,
        limit=args.limit,
        write=not args.dry_run,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def _handle_discover(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("offline Phase 4 discovery currently supports only --backend mock")
    config_path = args.config or Path("configs/experiments/discovery_weak.yaml")
    scenario = load_discovery_scenario(config_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": scenario.project_id,
                    "probe_signal_count": len(scenario.probe_signals),
                    "candidate_idea_count": len(scenario.idea_seeds),
                },
                indent=2,
            )
        )
        return 0
    summary = DiscoveryLoop(seed=args.seed).run(scenario, output_dir=args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_full(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("the integrated offline workflow currently supports only --backend mock")
    config_path = args.config or Path("configs/workflows/full_offline_v1.yaml")
    config = load_full_workflow_config(config_path)
    if args.project_id is not None or args.paper_directory is not None:
        payload = config.model_dump(mode="python")
        if args.project_id is not None:
            payload["project_id"] = args.project_id
        if args.paper_directory is not None:
            payload["paper_directory"] = args.paper_directory
        config = type(config).model_validate(payload)
    run_id = args.run_id or f"offline-full-seed-{args.seed:02d}"
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": config.project_id,
                    "run_id": run_id,
                    "provider": config.provider,
                    "model": config.model,
                    "resume": args.resume,
                    "stages": ["discovery", "evidence", "communication", "figure"],
                    "paper_directory": config.paper_directory,
                    "outputs_root": str(args.output),
                    "effectiveness_claim": False,
                },
                indent=2,
            )
        )
        return 0
    summary = FullWorkflow(seed=args.seed).run(
        config,
        outputs_root=args.output,
        run_id=run_id,
        resume=args.resume,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_evidence_plan(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("offline Phase 5 evidence workflow supports only --backend mock")
    config_path = args.config or Path("configs/evidence/contradiction_demo.yaml")
    scenario = load_evidence_scenario(config_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": scenario.project_id,
                    "claim_id": scenario.claim.claim_id,
                    "resume_state": str(args.state) if args.state else None,
                },
                indent=2,
            )
        )
        return 0
    summary = EvidenceWorkflow(seed=args.seed).run(
        scenario,
        output_dir=args.output,
        state_path=args.state,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_communication(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("offline Phase 6 communication currently supports only --backend mock")
    config_path = args.config or Path("configs/writing/reviewer_experiment_demo.yaml")
    scenario = load_communication_scenario(config_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": scenario.project_id,
                    "section_count": len(scenario.section_contracts),
                    "review_concern_count": len(scenario.review_feedback),
                },
                indent=2,
            )
        )
        return 0
    summary = CommunicationWorkflow(seed=args.seed).run(scenario, output_dir=args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_figure_build(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("offline Phase 7 figure workflow currently supports only --backend mock")
    config_path = args.config or Path("configs/visual/mechanism_demo.yaml")
    scenario = load_figure_scenario(config_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": scenario.project_id,
                    "figure_id": scenario.contract.figure_id,
                    "panel_count": len(scenario.contract.panel_plan),
                    "required_entity_count": len(scenario.contract.required_entities),
                },
                indent=2,
            )
        )
        return 0
    summary = FigureWorkflow(seed=args.seed).run(scenario, output_dir=args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_benchmark_run(args: argparse.Namespace) -> int:
    suite = load_benchmark_suite(args.suite)
    conditions = (
        [BenchmarkCondition(condition) for condition in args.condition]
        if args.condition
        else suite.conditions
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "suite_id": suite.suite_id,
                    "suite_sha256": suite.sha256,
                    "case_count": len(suite.cases),
                    "headline_case_count": sum(case.headline_eligible for case in suite.cases),
                    "conditions": [condition.value for condition in conditions],
                },
                indent=2,
            )
        )
        return 0
    if args.backend == "scripted":
        backend = ScriptedPreferenceBackend(scripted_selections(suite, conditions))
    elif args.backend == "replay":
        if args.replay is None:
            raise ValueError("--backend replay requires --replay PATH")
        backend = ReplayBackend(args.replay)
    elif args.backend == "openai-compatible":
        if args.config is None:
            raise ValueError("--backend openai-compatible requires --config PATH")
        backend = OpenAICompatibleBackend(load_openai_compatible_config(args.config))
    elif args.backend == "local-transformers":
        if args.config is None:
            raise ValueError("--backend local-transformers requires --config PATH")
        backend = LocalTransformersBackend(load_local_transformers_config(args.config))
    else:
        raise ValueError(
            "supported benchmark backends: scripted, replay, openai-compatible, local-transformers"
        )
    if args.record:
        backend = RecordingBackend(backend, args.record)
    report = SciTasteBenchRunner(backend, seed=args.seed).evaluate(suite, conditions=conditions)
    manifest = save_benchmark_report(report, args.output)
    base = report.conditions[BenchmarkCondition.BASE].headline
    print(
        json.dumps(
            {
                "suite_id": report.suite_id,
                "backend": report.backend,
                "model": report.model,
                "base_pairwise_accuracy": base.pairwise_accuracy,
                "comparisons_to_base": {
                    condition.value: comparison.model_dump(mode="json")
                    for condition, comparison in report.comparisons_to_base.items()
                },
                "report": manifest["report"],
                "manifest": manifest["manifest"],
            },
            indent=2,
        )
    )
    return 0


def _handle_benchmark_attribute(args: argparse.Namespace) -> int:
    comparison = compare_model_boundaries(
        load_benchmark_report(args.primary_report),
        load_benchmark_report(args.comparator_report),
    )
    paths = save_boundary_comparison(comparison, args.output)
    print(
        json.dumps(
            {
                "primary_model": comparison.primary_model,
                "comparator_model": comparison.comparator_model,
                "primary_model_limit_candidates": (
                    comparison.primary_model_limit_candidate_case_ids
                ),
                "comparator_model_limit_candidates": (
                    comparison.comparator_model_limit_candidate_case_ids
                ),
                "shared_failures": comparison.shared_base_failure_case_ids,
                "primary_system_regressions": (comparison.primary_system_regression_case_ids),
                "comparator_system_regressions": (comparison.comparator_system_regression_case_ids),
                **paths,
            },
            indent=2,
        )
    )
    return 0


def _handle_study_plan(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("study planning supports only --backend local")
    protocol_path = args.config or Path("configs/experiments/matched_budget_study_v1.yaml")
    protocol = load_study_protocol(protocol_path)
    plan = MatchedStudyPlanner().plan(protocol)
    payload = {
        "study_id": protocol.study_id,
        "protocol_sha256": protocol.sha256,
        "plan_sha256": plan.sha256,
        "planned_cells": len(plan.cells),
        "disabled_conditions": {
            condition.value: reason for condition, reason in plan.disabled_conditions.items()
        },
        "readiness_blockers": plan.readiness_blockers,
    }
    if args.dry_run:
        print(json.dumps({"status": "planned", **payload}, indent=2))
        return 0
    path = save_study_plan(plan, args.output)
    print(json.dumps({**payload, "plan": str(path)}, indent=2))
    return 0


def _handle_study_run(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("study execution supports only --backend local")
    protocol_path = args.config or Path("configs/experiments/matched_budget_study_v1.yaml")
    protocol = load_study_protocol(protocol_path)
    launch_config = load_study_launch_config(args.launch_config)
    summary = MatchedStudyRunner(
        protocol,
        launch_config,
        output_dir=args.output,
    ).run(
        task_ids=args.task,
        conditions=(
            [SystemCondition(condition) for condition in args.condition] if args.condition else None
        ),
        cell_ids=args.cell_id,
        max_cells=args.max_cells,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )
    print(summary.model_dump_json(indent=2))
    return 0 if summary.failed_cells == 0 else 1


def _handle_study_project_run(args: argparse.Namespace) -> int:
    protocol = load_study_protocol(args.config)
    launch_config = load_study_launch_config(args.launch_config)
    summary = ProjectMatchedStudyRunner(
        ProjectRuntime(args.outputs_root),
        protocol,
        launch_config,
    ).run(
        ProjectStudyConfig(
            project_id=args.project_id,
            run_id=args.run_id,
            provider=args.provider,
            model=args.model,
            seed=args.run_seed,
            evidence_scope=args.evidence_scope,
        ),
        task_ids=args.task,
        conditions=(
            [SystemCondition(condition) for condition in args.condition] if args.condition else None
        ),
        cell_ids=args.cell_id,
        max_cells=args.max_cells,
        resume=args.resume,
        dry_run=args.dry_run,
    )
    print(summary.model_dump_json(indent=2))
    return 0 if summary.study.failed_cells == 0 else 1


def _handle_study_evaluate(args: argparse.Namespace) -> int:
    if args.backend != "local":
        raise ValueError("study evaluation supports only --backend local")
    protocol_path = args.config or Path("configs/experiments/matched_budget_study_v1.yaml")
    protocol = load_study_protocol(protocol_path)
    report = MatchedStudyEvaluator().evaluate(protocol, load_study_results(args.results))
    payload = {
        "study_id": report.study_id,
        "status": report.status.value,
        "headline_eligible": report.headline_eligible,
        "planned_cells": report.planned_cells,
        "completed_cells": report.completed_cells,
        "blockers": report.blockers,
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    path = save_study_report(report, args.output)
    print(json.dumps({**payload, "report": str(path)}, indent=2))
    return 0 if not report.blockers else 1


def _handle_planned(args: argparse.Namespace) -> int:
    payload = {
        "status": "planned",
        "milestone": args.milestone,
        "message": "Command contract is reserved; implementation has not passed its roadmap gate.",
    }
    print(json.dumps(payload, indent=2))
    return 0 if args.dry_run else 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))
    try:
        return int(args.handler(args))
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

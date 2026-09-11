"""SciTaste command-line interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime
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
    CandidateOrder,
    MatchedStudyEvaluator,
    MatchedStudyPlanner,
    MatchedStudyRunner,
    ProjectMatchedStudyRunner,
    ProjectStudyConfig,
    SciTasteBenchRunner,
    SystemCondition,
    compare_model_boundaries,
    compile_curated_suite,
    discover_study_result_paths,
    inspect_curation_package,
    inspect_study_matrix,
    load_benchmark_report,
    load_benchmark_suite,
    load_curation_package,
    load_source_candidate_manifest,
    load_study_launch_config,
    load_study_protocol,
    load_study_results,
    save_benchmark_report,
    save_boundary_comparison,
    save_curated_suite,
    save_study_matrix_status,
    save_study_plan,
    save_study_report,
    scripted_selections,
    source_candidate_status,
)
from scitaste.benchmark.manuscript import materialize_venue_manuscript
from scitaste.data.curation import CurationFormat, curate_snapshot
from scitaste.data.ingestion import audit_corpus_manifest, ingest_corpus
from scitaste.data.store import build_libraries
from scitaste.demo import run_nonlinear_demo
from scitaste.discovery.commands import DiscoveryCommand, DiscoveryCommandRunner
from scitaste.discovery.knowledge import load_discovery_knowledge_binding
from scitaste.discovery.loop import DiscoveryLoop, load_discovery_scenario
from scitaste.discovery.project_workflow import ProjectDiscoveryWorkflow
from scitaste.discovery.semantic import DiscoverySemanticBinding
from scitaste.discovery.semantic_config import load_discovery_semantic_runtime_config
from scitaste.evaluation import (
    EvaluationCriticSuite,
    approve_dataset_acquisition_request,
    compile_evaluation_cell_plan,
    inspect_adapter_contract,
    inspect_adapter_preflight,
    inspect_dataset_acquisition_request,
    inspect_experiment_decision_dossier,
    inspect_git_source,
    inspect_prelaunch_manifest,
    inspect_task_package,
    inspect_task_selection,
    load_adapter_contract_manifest,
    load_adapter_preflight_manifest,
    load_dataset_acquisition_request,
    load_experiment_decision_dossier,
    load_external_resource_corpus,
    load_prelaunch_manifest,
    load_task_package_manifest,
    load_task_selection_manifest,
    materialize_dataset_acquisition,
    prepare_project_evaluation,
    prepare_project_evaluation_result,
    publish_project_evaluation,
    publish_project_evaluation_result,
    run_live_direct_agent,
    save_acquisition_gate_report,
    save_dataset_acquisition_request,
    save_evaluation_cell_plan,
    save_experiment_decision_dossier_report,
    summarize_evaluation_readiness,
)
from scitaste.evidence.workflow import EvidenceWorkflow, load_evidence_scenario
from scitaste.executor.autoresearchclaw import AutoResearchClawExecutor
from scitaste.executor.native_code import inspect_native_code_proposal
from scitaste.executor.native_code_generation import (
    load_native_code_generation_config,
    load_native_code_repair_config,
    validate_native_code_repair_binding,
)
from scitaste.executor.native_profile import (
    inspect_native_execution_profile,
    preflight_native_resources,
)
from scitaste.executor.native_sandbox import (
    NativeExperimentRunner,
    load_native_experiment_definition,
)
from scitaste.executor.workflow import build_autoresearchclaw_workflow
from scitaste.full_workflow import (
    FullWorkflow,
    inspect_full_workflow_intake,
    load_full_workflow_config,
)
from scitaste.generative_ui import ProjectSurfaceFactory
from scitaste.generative_ui.serve_cli import add_ui_commands
from scitaste.lifecycle import assess_project_lifecycle
from scitaste.model_node_pilot_cli import register_model_node_pilot_cli
from scitaste.model_node_runtime_cli import register_model_node_runtime_cli
from scitaste.model_nodes.full_workflow_tool_intelligence import (
    load_full_workflow_tool_intelligence,
)
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.schemas import VenuePaperReviewProposal
from scitaste.model_nodes.workflow_bridge import load_full_workflow_model_advisory
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.models import validate_entry_id
from scitaste.project_substrate_cli import register_project_substrate_cli
from scitaste.resource_cli import register_resource_cli
from scitaste.review import (
    VenueReviewReport,
    VenueReviewResponse,
    VenueReviewVerification,
    build_project_evaluation_closure_proofs,
    build_venue_review_packet,
    import_venue_review_report,
    import_venue_review_verification,
    inspect_project_evaluation_evidence,
    inspect_project_review_routing,
    inspect_venue_review,
    load_venue_review_packet,
    prepare_project_evaluation_evidence,
    prepare_project_review_routing,
    prepare_venue_review,
    publish_project_evaluation_evidence,
    publish_project_review_routing,
    submit_venue_review_response,
)
from scitaste.review.model_report import (
    build_internal_model_review_report,
    build_internal_model_review_report_from_runtime,
    build_venue_paper_review_material,
    build_venue_paper_review_runtime_config,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.intrinsic import (
    IntrinsicTasteCalibrator,
    load_calibration_suite,
    save_calibration_report,
)
from scitaste.visual.workflow import FigureWorkflow, load_figure_scenario
from scitaste.writing.argument import (
    PaperArgumentAssessment,
    PaperArgumentContract,
    assess_paper_argument,
    load_paper_argument_contract,
    write_paper_argument_assessment,
    write_paper_argument_contract,
)
from scitaste.writing.manuscript_quality import (
    RESEARCH_WORKING_DRAFT_MINIMUM_WORDS,
    assess_manuscript,
)
from scitaste.writing.paper_adoption import (
    inspect_project_paper_adoption,
    prepare_project_paper_adoption,
    publish_project_paper_adoption,
)
from scitaste.writing.paper_draft_materialization import materialize_accepted_paper_draft
from scitaste.writing.paper_revision_context import (
    build_project_paper_revision_runtime_config,
    prepare_project_paper_revision_context,
)
from scitaste.writing.paper_revision_materialization import (
    materialize_accepted_paper_revision,
)
from scitaste.writing.scientific_evidence import (
    materialize_paper_scientific_evidence,
    require_selected_scientific_evidence,
)
from scitaste.writing.taste import assess_writing_taste
from scitaste.writing.venue import assess_venue_submission, inspect_venue_template
from scitaste.writing.venue_taste import (
    PaperArchetype,
    VenueWritingTasteContext,
    build_venue_writing_taste_context,
    inspect_venue_writing_taste,
    require_venue_taste_matches_template,
)
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


def _add_paper_scientific_evidence_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evaluation-result-id",
        default=None,
        help=(
            "Bind the complete currently selected evaluation result into a new immutable "
            "paper sidecar"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scitaste", description="Scientific taste controller")
    parser.add_argument("--version", action="version", version="SciTaste 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    add_ui_commands(commands)
    register_resource_cli(commands)

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
    substrate_execute.add_argument("--max-total-tokens", type=int, default=100_000)
    substrate_execute.add_argument(
        "--allow-live",
        action="store_true",
        help="Explicitly authorize the provider call when not using --dry-run",
    )
    substrate_execute.set_defaults(handler=_handle_substrate_execute)
    register_project_substrate_cli(substrate_commands)

    run = commands.add_parser("run", help="End-to-end workflows")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    demo = run_commands.add_parser("demo", help="Run the Phase 1 nonlinear mock loop")
    _add_common_options(demo, default_output="outputs/demo")
    demo.set_defaults(handler=_handle_demo)
    full = run_commands.add_parser("full", help="Run the Phase 4-7 project workflow")
    _add_common_options(full, default_output="outputs")
    full.set_defaults(backend=None)
    full.add_argument("--project-id", default=None)
    full.add_argument("--run-id", default=None)
    full.add_argument("--paper-directory", default=None)
    full.add_argument(
        "--research-brief",
        type=Path,
        default=None,
        help="Override the config with a strict open-question research brief",
    )
    full.add_argument(
        "--resume",
        action="store_true",
        help="Resume one failed run from its validated contiguous stage prefix",
    )
    full.add_argument(
        "--allow-live-model-nodes",
        action="store_true",
        help="Explicitly authorize configured provider-backed advisory nodes",
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

    project_lifecycle = project_commands.add_parser(
        "lifecycle", help="Verify idea-to-paper-to-review lifecycle evidence"
    )
    project_lifecycle_commands = project_lifecycle.add_subparsers(
        dest="project_lifecycle_command", required=True
    )
    project_lifecycle_status = project_lifecycle_commands.add_parser(
        "status", help="Derive content-bound lifecycle gates"
    )
    project_lifecycle_status.add_argument("--project-id", required=True)
    project_lifecycle_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(project_lifecycle_status)
    project_lifecycle_status.set_defaults(handler=_handle_project_lifecycle_status)

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

    project_discovery = project_commands.add_parser(
        "discovery", help="Advance project-owned native discovery operations"
    )
    project_discovery_commands = project_discovery.add_subparsers(
        dest="project_discovery_command", required=True
    )
    project_discovery_advance = project_discovery_commands.add_parser(
        "advance", help="Reserve and execute one immutable discovery operation"
    )
    project_discovery_advance.add_argument("--project-id", required=True)
    project_discovery_advance.add_argument("--run-id", required=True)
    project_discovery_advance.add_argument(
        "--operation",
        choices=[item.value for item in DiscoveryCommand],
        required=True,
    )
    project_discovery_advance.add_argument("--config", type=Path, required=True)
    project_discovery_advance.add_argument("--seed", type=int, default=0)
    project_discovery_advance.add_argument("--expected-revision", type=int, required=True)
    project_discovery_advance.add_argument("--signal-number", type=int, default=None)
    project_discovery_advance.add_argument("--reformulation-number", type=int, default=None)
    project_discovery_advance.add_argument(
        "--evidence-scope",
        default="native-discovery-engineering-evidence",
    )
    project_discovery_advance.add_argument("--resume", action="store_true")
    project_discovery_advance.add_argument(
        "--semantic-config",
        type=Path,
        default=None,
        help="opt in to a command-compatible bounded semantic model-node config",
    )
    project_discovery_advance.add_argument("--semantic-profile-set", type=Path, default=None)
    project_discovery_advance.add_argument("--semantic-profile-id", default=None)
    project_discovery_advance.add_argument("--semantic-allow-live", action="store_true")
    project_discovery_advance.add_argument(
        "--native-knowledge-config",
        type=Path,
        default=None,
        help="bind a copied local Knowledge corpus to native Discovery retrieval",
    )
    _add_project_options(project_discovery_advance)
    project_discovery_advance.set_defaults(handler=_handle_project_discovery_advance)
    project_discovery_verify = project_discovery_commands.add_parser(
        "verify", help="Verify a committed project discovery lineage"
    )
    project_discovery_verify.add_argument("--project-id", required=True)
    project_discovery_verify.add_argument("--run-id", required=True)
    project_discovery_verify.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(project_discovery_verify)
    project_discovery_verify.set_defaults(handler=_handle_project_discovery_verify)

    project_evaluation = project_commands.add_parser(
        "evaluation", help="Register and select project-owned experiment proposals"
    )
    project_evaluation_commands = project_evaluation.add_subparsers(
        dest="project_evaluation_command", required=True
    )
    project_evaluation_register = project_evaluation_commands.add_parser(
        "register-prelaunch",
        help="Materialize a no-run prelaunch proposal below its owning project",
    )
    project_evaluation_register.add_argument("--project-id", required=True)
    project_evaluation_register.add_argument("--evaluation-id", required=True)
    project_evaluation_register.add_argument("--manifest", type=Path, required=True)
    project_evaluation_register.add_argument("--resource-corpus", type=Path, required=True)
    project_evaluation_register.add_argument("--source-root", type=Path, default=Path("."))
    project_evaluation_register.add_argument("--evidence-root", type=Path, default=Path("."))
    project_evaluation_register.add_argument("--expected-revision", type=int, required=True)
    project_evaluation_register.add_argument("--select", action="store_true")
    _add_project_options(project_evaluation_register)
    project_evaluation_register.set_defaults(handler=_handle_project_evaluation_register_prelaunch)
    project_evaluation_select = project_evaluation_commands.add_parser(
        "select", help="Select a registered experiment proposal"
    )
    project_evaluation_select.add_argument("--project-id", required=True)
    project_evaluation_select.add_argument("--evaluation-id", required=True)
    project_evaluation_select.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_evaluation_select)
    project_evaluation_select.set_defaults(handler=_handle_project_evaluation_select)
    project_evaluation_status = project_evaluation_commands.add_parser(
        "status", help="Summarize one proposal as seven decision-scale gates"
    )
    project_evaluation_status.add_argument("--project-id", required=True)
    project_evaluation_status.add_argument("--evaluation-id")
    project_evaluation_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(project_evaluation_status)
    project_evaluation_status.set_defaults(handler=_handle_project_evaluation_status)
    project_evaluation_result_register = project_evaluation_commands.add_parser(
        "register-result",
        help="Verify and register a project-owned evaluation result set",
    )
    project_evaluation_result_register.add_argument("--project-id", required=True)
    project_evaluation_result_register.add_argument("--evaluation-id", required=True)
    project_evaluation_result_register.add_argument("--result-id", required=True)
    project_evaluation_result_register.add_argument("--result-set", type=Path, required=True)
    project_evaluation_result_register.add_argument("--expected-revision", type=int, required=True)
    project_evaluation_result_register.add_argument("--select", action="store_true")
    _add_project_options(project_evaluation_result_register)
    project_evaluation_result_register.set_defaults(
        handler=_handle_project_evaluation_register_result
    )
    project_evaluation_result_select = project_evaluation_commands.add_parser(
        "select-result", help="Select a verified evaluation result"
    )
    project_evaluation_result_select.add_argument("--project-id", required=True)
    project_evaluation_result_select.add_argument("--result-id", required=True)
    project_evaluation_result_select.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_evaluation_result_select)
    project_evaluation_result_select.set_defaults(handler=_handle_project_evaluation_select_result)
    project_evaluation_result_status = project_evaluation_commands.add_parser(
        "result-status", help="Revalidate one registered evaluation result"
    )
    project_evaluation_result_status.add_argument("--project-id", required=True)
    project_evaluation_result_status.add_argument("--result-id")
    project_evaluation_result_status.add_argument(
        "--outputs-root", type=Path, default=Path("outputs")
    )
    _add_log_level_option(project_evaluation_result_status)
    project_evaluation_result_status.set_defaults(handler=_handle_project_evaluation_result_status)

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
    project_run_begin.add_argument("--artifact", default=None)
    project_run_begin.add_argument(
        "--generative-ui-projection",
        choices=[
            "autoresearch-evaluation-landscape-v1",
            "autoresearch-evaluation-landscape-v2",
            "autoresearch-evaluation-landscape-v3",
            "autoresearch-evaluation-landscape-v4",
            "autoresearch-evaluation-landscape-v5",
            "autoresearch-evaluation-landscape-v6",
        ],
        default=None,
    )
    project_run_begin.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_run_begin)
    project_run_begin.set_defaults(handler=_handle_project_run_begin)
    project_run_update = project_run_commands.add_parser(
        "update", help="Update one registered run's status and bounded failure metadata"
    )
    project_run_update.add_argument("--project-id", required=True)
    project_run_update.add_argument("--run-id", required=True)
    project_run_update.add_argument("--status", required=True)
    project_run_update.add_argument("--evidence-scope", default=None)
    project_run_update.add_argument("--artifact", default=None)
    project_run_update.add_argument("--superseded-by", default=None)
    project_run_update.add_argument("--failure-code", default=None)
    project_run_update.add_argument("--failure-invocation-id", default=None)
    project_run_update.add_argument("--failure-receipt-sha256", default=None)
    project_run_update.add_argument(
        "--backend-may-have-started",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    project_run_update.add_argument(
        "--cost-status",
        choices=["known", "unknown", "not-started"],
        default=None,
    )
    project_run_update.add_argument("--retry-policy", default=None)
    project_run_update.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_run_update)
    project_run_update.set_defaults(handler=_handle_project_run_update)
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
    project_paper_build = project_paper_commands.add_parser(
        "build", help="Build, gate, and register a venue-native paper bundle"
    )
    project_paper_build.add_argument("--project-id", required=True)
    project_paper_build.add_argument("--directory-name", required=True)
    project_paper_build.add_argument("--source", type=Path, required=True)
    project_paper_build.add_argument("--bibliography", type=Path, required=True)
    project_paper_build.add_argument(
        "--venue-config",
        type=Path,
        default=Path("configs/writing/venues/iclr-2027/submission.yaml"),
    )
    project_paper_build.add_argument(
        "--venue-taste-profile",
        type=Path,
        default=None,
        help="Optional venue Writing Taste profile; a sibling taste.yaml is auto-discovered",
    )
    project_paper_build.add_argument(
        "--paper-archetype",
        choices=[item.value for item in PaperArchetype],
        default=None,
        help=(
            "Paper form used to select venue guidance; inferred from an optional "
            "whole-paper argument contract"
        ),
    )
    project_paper_build.add_argument("--asset-root", type=Path, action="append", default=[])
    project_paper_build.add_argument(
        "--argument-contract",
        type=Path,
        default=None,
        help="Optional self-hashed whole-paper argument contract",
    )
    project_paper_build.add_argument(
        "--argument-state",
        type=Path,
        default=None,
        help="ResearchState supplying the contract's registered claims and evidence",
    )
    project_paper_build.add_argument(
        "--argument-artifact-root",
        type=Path,
        default=None,
        help="Root for rehashing contract-bound presentation artifacts (defaults to source parent)",
    )
    project_paper_build.add_argument("--source-run", default=None)
    project_paper_build.add_argument("--provider", default="scitaste-native")
    project_paper_build.add_argument("--model", default="deterministic-venue-renderer")
    project_paper_build.add_argument("--condition", default="venue-submission-build")
    project_paper_build.add_argument("--task", default="project-manuscript")
    project_paper_build.add_argument("--seed", type=int, default=0)
    project_paper_build.add_argument("--stage", type=int, default=17)
    project_paper_build.add_argument(
        "--evidence-scope",
        default="venue-compliance-only-no-scientific-effectiveness-claim",
    )
    _add_paper_scientific_evidence_option(project_paper_build)
    project_paper_build.add_argument("--date", default=date.today().isoformat())
    project_paper_build.add_argument("--expected-revision", type=int, required=True)
    project_paper_build.add_argument("--select", action="store_true")
    project_paper_build.add_argument("--no-global-latest", action="store_true")
    _add_project_options(project_paper_build)
    project_paper_build.set_defaults(handler=_handle_project_paper_build)
    project_paper_build_draft = project_paper_commands.add_parser(
        "build-draft",
        help="Build a venue paper from one accepted evidence-paper-draft ledger entry",
    )
    project_paper_build_draft.add_argument("--project-id", required=True)
    project_paper_build_draft.add_argument("--directory-name", required=True)
    project_paper_build_draft.add_argument("--run-id", required=True)
    project_paper_build_draft.add_argument("--invocation-id", required=True)
    project_paper_build_draft.add_argument("--bibliography", type=Path, required=True)
    project_paper_build_draft.add_argument(
        "--venue-config",
        type=Path,
        default=Path("configs/writing/venues/iclr-2027/submission.yaml"),
    )
    project_paper_build_draft.add_argument("--venue-taste-profile", type=Path, default=None)
    project_paper_build_draft.add_argument(
        "--paper-archetype",
        choices=[item.value for item in PaperArchetype],
        default=None,
    )
    project_paper_build_draft.add_argument("--asset-root", type=Path, action="append", default=[])
    project_paper_build_draft.add_argument("--argument-contract", type=Path, default=None)
    project_paper_build_draft.add_argument("--argument-state", type=Path, default=None)
    project_paper_build_draft.add_argument("--argument-artifact-root", type=Path, default=None)
    project_paper_build_draft.add_argument("--source-run", default=None)
    project_paper_build_draft.add_argument("--provider", default=None)
    project_paper_build_draft.add_argument("--model", default=None)
    project_paper_build_draft.add_argument("--condition", default="evidence-paper-draft-build")
    project_paper_build_draft.add_argument("--task", default="project-model-drafted-manuscript")
    project_paper_build_draft.add_argument("--seed", type=int, default=0)
    project_paper_build_draft.add_argument("--stage", type=int, default=17)
    project_paper_build_draft.add_argument(
        "--evidence-scope",
        default="model-drafted-from-registered-evidence-no-effectiveness-claim",
    )
    _add_paper_scientific_evidence_option(project_paper_build_draft)
    project_paper_build_draft.add_argument("--date", default=date.today().isoformat())
    project_paper_build_draft.add_argument("--expected-revision", type=int, required=True)
    project_paper_build_draft.add_argument("--select", action="store_true")
    project_paper_build_draft.add_argument("--no-global-latest", action="store_true")
    _add_project_options(project_paper_build_draft)
    project_paper_build_draft.set_defaults(handler=_handle_project_paper_build_draft)
    project_paper_build_revision = project_paper_commands.add_parser(
        "build-revision",
        help="Build a venue paper from one accepted evidence-paper-revision ledger entry",
    )
    project_paper_build_revision.add_argument("--project-id", required=True)
    project_paper_build_revision.add_argument("--directory-name", required=True)
    project_paper_build_revision.add_argument("--review-id", required=True)
    project_paper_build_revision.add_argument("--run-id", required=True)
    project_paper_build_revision.add_argument("--invocation-id", required=True)
    project_paper_build_revision.add_argument("--bibliography", type=Path, required=True)
    project_paper_build_revision.add_argument(
        "--venue-config",
        type=Path,
        default=Path("configs/writing/venues/iclr-2027/submission.yaml"),
    )
    project_paper_build_revision.add_argument("--venue-taste-profile", type=Path, default=None)
    project_paper_build_revision.add_argument(
        "--paper-archetype",
        choices=[item.value for item in PaperArchetype],
        default=None,
    )
    project_paper_build_revision.add_argument(
        "--asset-root", type=Path, action="append", default=[]
    )
    project_paper_build_revision.add_argument("--argument-contract", type=Path, default=None)
    project_paper_build_revision.add_argument("--argument-state", type=Path, default=None)
    project_paper_build_revision.add_argument("--argument-artifact-root", type=Path, default=None)
    project_paper_build_revision.add_argument("--source-run", default=None)
    project_paper_build_revision.add_argument("--provider", default=None)
    project_paper_build_revision.add_argument("--model", default=None)
    project_paper_build_revision.add_argument(
        "--condition", default="reviewer-driven-paper-revision"
    )
    project_paper_build_revision.add_argument("--task", default="project-model-revised-manuscript")
    project_paper_build_revision.add_argument("--seed", type=int, default=0)
    project_paper_build_revision.add_argument("--stage", type=int, default=19)
    project_paper_build_revision.add_argument(
        "--evidence-scope",
        default="model-revised-from-registered-review-and-evidence",
    )
    _add_paper_scientific_evidence_option(project_paper_build_revision)
    project_paper_build_revision.add_argument("--date", default=date.today().isoformat())
    project_paper_build_revision.add_argument("--expected-revision", type=int, required=True)
    project_paper_build_revision.add_argument("--select", action="store_true")
    project_paper_build_revision.add_argument("--no-global-latest", action="store_true")
    _add_project_options(project_paper_build_revision)
    project_paper_build_revision.set_defaults(handler=_handle_project_paper_build_revision)
    project_paper_select = project_paper_commands.add_parser(
        "select", help="Select a current project paper"
    )
    project_paper_select.add_argument("--project-id", required=True)
    project_paper_select.add_argument("--directory-name", required=True)
    project_paper_select.add_argument("--expected-revision", type=int, required=True)
    project_paper_select.add_argument("--no-global-latest", action="store_true")
    _add_project_options(project_paper_select)
    project_paper_select.set_defaults(handler=_handle_project_paper_select)

    project_paper_adopt = project_paper_commands.add_parser(
        "adopt-for-revision",
        help="Adopt exact registered prose as a no-evidence semantic revision source",
    )
    project_paper_adopt.add_argument("--project-id", required=True)
    project_paper_adopt.add_argument("--paper-directory", required=True)
    project_paper_adopt.add_argument("--run-id", required=True)
    project_paper_adopt.add_argument("--source-commit", required=True)
    project_paper_adopt.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(project_paper_adopt)
    project_paper_adopt.set_defaults(handler=_handle_project_paper_adopt_for_revision)

    project_paper_adoption_status = project_paper_commands.add_parser(
        "adoption-status",
        help="Reparse and rehash one registered-paper semantic adoption",
    )
    project_paper_adoption_status.add_argument("--project-id", required=True)
    project_paper_adoption_status.add_argument("--run-id", required=True)
    project_paper_adoption_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(project_paper_adoption_status)
    project_paper_adoption_status.set_defaults(handler=_handle_project_paper_adoption_status)

    project_paper_review = project_paper_commands.add_parser(
        "review", help="Prepare and close content-bound venue review rounds"
    )
    project_paper_review_commands = project_paper_review.add_subparsers(
        dest="project_paper_review_command", required=True
    )
    review_prepare = project_paper_review_commands.add_parser(
        "prepare", help="Prepare an exact paper packet without calling a reviewer"
    )
    review_prepare.add_argument("--project-id", required=True)
    review_prepare.add_argument("--paper-directory", required=True)
    review_prepare.add_argument("--review-id", required=True)
    review_prepare.add_argument("--round-number", type=int, default=1)
    review_prepare.add_argument(
        "--scope",
        choices=["development", "independent_pre_submission"],
        default="development",
    )
    review_prepare.add_argument(
        "--venue-taste-profile",
        type=Path,
        default=Path("configs/writing/venues/iclr-2027/taste.yaml"),
    )
    review_prepare.add_argument("--expected-revision", type=int, required=True)
    review_prepare.add_argument("--select", action="store_true")
    _add_project_options(review_prepare)
    review_prepare.set_defaults(handler=_handle_project_paper_review_prepare)

    review_import = project_paper_review_commands.add_parser(
        "import-report", help="Import one structured reviewer report"
    )
    review_import.add_argument("--project-id", required=True)
    review_import.add_argument("--review-id", required=True)
    review_import.add_argument("--report", type=Path, required=True)
    review_import.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_import)
    review_import.set_defaults(handler=_handle_project_paper_review_import)

    review_import_model = project_paper_review_commands.add_parser(
        "import-model-report",
        help="Bind accepted model feedback to an internal reviewer identity",
    )
    review_import_model.add_argument("--project-id", required=True)
    review_import_model.add_argument("--review-id", required=True)
    review_import_model.add_argument(
        "--proposal",
        type=Path,
        help="Legacy proposal file; requires --provider and --model",
    )
    review_import_model.add_argument("--report-id", required=True)
    review_import_model.add_argument("--reviewer-id", required=True)
    review_import_model.add_argument("--provider")
    review_import_model.add_argument("--model")
    review_import_model.add_argument(
        "--run-id",
        help="Verified model-node run containing the accepted review",
    )
    review_import_model.add_argument(
        "--invocation-id",
        help="Unique accepted invocation in the verified run ledger",
    )
    review_import_model.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_import_model)
    review_import_model.set_defaults(handler=_handle_project_paper_review_import_model)

    review_model_input = project_paper_review_commands.add_parser(
        "model-input",
        help="Project an exact registered paper into a model-review node input",
    )
    review_model_input.add_argument("--project-id", required=True)
    review_model_input.add_argument("--review-id", required=True)
    review_model_input.add_argument("--paper-label", default="source-markdown")
    review_model_input.add_argument(
        "--permitted-evidence-type",
        action="append",
        default=[],
    )
    review_model_input.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_model_input)
    review_model_input.set_defaults(handler=_handle_project_paper_review_model_input)

    review_runtime_config = project_paper_review_commands.add_parser(
        "runtime-config",
        help="Build a profile-bound internal-review invocation without calling a model",
    )
    review_runtime_config.add_argument("--project-id", required=True)
    review_runtime_config.add_argument("--review-id", required=True)
    review_runtime_config.add_argument("--paper-label", default="source-markdown")
    review_runtime_config.add_argument(
        "--permitted-evidence-type",
        action="append",
        default=[],
    )
    review_runtime_config.add_argument("--profile-set", type=Path, required=True)
    review_runtime_config.add_argument("--profile-id", required=True)
    review_runtime_config.add_argument("--backend-config", type=Path, required=True)
    review_runtime_config.add_argument("--expected-revision", type=int, required=True)
    review_runtime_config.add_argument("--seed", type=int, default=0)
    review_runtime_config.add_argument("--output", type=Path, required=True)
    review_runtime_config.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_runtime_config)
    review_runtime_config.set_defaults(handler=_handle_project_paper_review_runtime_config)

    review_respond = project_paper_review_commands.add_parser(
        "respond", help="Bind a complete response to a registered paper revision"
    )
    review_respond.add_argument("--project-id", required=True)
    review_respond.add_argument("--review-id", required=True)
    review_respond.add_argument("--response", type=Path, required=True)
    review_respond.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_respond)
    review_respond.set_defaults(handler=_handle_project_paper_review_respond)

    review_verify = project_paper_review_commands.add_parser(
        "verify-response", help="Import original-reviewer verification of a response"
    )
    review_verify.add_argument("--project-id", required=True)
    review_verify.add_argument("--review-id", required=True)
    review_verify.add_argument("--verification", type=Path, required=True)
    review_verify.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_verify)
    review_verify.set_defaults(handler=_handle_project_paper_review_verify)

    review_status = project_paper_review_commands.add_parser(
        "status", help="Rehash and inspect one registered review round"
    )
    review_status.add_argument("--project-id", required=True)
    review_status.add_argument("--review-id", required=True)
    review_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_status)
    review_status.set_defaults(handler=_handle_project_paper_review_status)
    review_route_state = project_paper_review_commands.add_parser(
        "route-state",
        help="Route one admitted review report into project-owned research obligations",
    )
    review_route_state.add_argument("--project-id", required=True)
    review_route_state.add_argument("--review-id", required=True)
    review_route_state.add_argument("--report-id", required=True)
    review_route_state.add_argument("--source-state", required=True)
    review_route_state.add_argument("--run-id", required=True)
    review_route_state.add_argument("--source-commit", required=True)
    review_route_state.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_route_state)
    review_route_state.set_defaults(handler=_handle_project_paper_review_route_state)

    review_routing_status = project_paper_review_commands.add_parser(
        "routing-status",
        help="Rehash one registered review-to-research-state routing bundle",
    )
    review_routing_status.add_argument("--project-id", required=True)
    review_routing_status.add_argument("--run-id", required=True)
    review_routing_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_routing_status)
    review_routing_status.set_defaults(handler=_handle_project_paper_review_routing_status)

    review_admit_evidence = project_paper_review_commands.add_parser(
        "admit-evaluation-evidence",
        help="Admit a selected formal result into routed review obligations",
    )
    review_admit_evidence.add_argument("--project-id", required=True)
    review_admit_evidence.add_argument("--routing-run-id", required=True)
    review_admit_evidence.add_argument("--result-id", required=True)
    review_admit_evidence.add_argument("--run-id", required=True)
    review_admit_evidence.add_argument("--source-commit", required=True)
    review_admit_evidence.add_argument("--expected-revision", type=int, required=True)
    _add_project_options(review_admit_evidence)
    review_admit_evidence.set_defaults(
        handler=_handle_project_paper_review_admit_evaluation_evidence
    )

    review_evidence_status = project_paper_review_commands.add_parser(
        "evaluation-evidence-status",
        help="Rehash one formal-result-to-review-state evidence transition",
    )
    review_evidence_status.add_argument("--project-id", required=True)
    review_evidence_status.add_argument("--run-id", required=True)
    review_evidence_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_evidence_status)
    review_evidence_status.set_defaults(
        handler=_handle_project_paper_review_evaluation_evidence_status
    )

    review_closure_proofs = project_paper_review_commands.add_parser(
        "evaluation-closure-proofs",
        help="Build paper-revision proofs from admitted formal evaluation evidence",
    )
    review_closure_proofs.add_argument("--project-id", required=True)
    review_closure_proofs.add_argument("--run-id", required=True)
    review_closure_proofs.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_closure_proofs)
    review_closure_proofs.set_defaults(
        handler=_handle_project_paper_review_evaluation_closure_proofs
    )

    review_revision_input = project_paper_review_commands.add_parser(
        "revision-input",
        help="Compile exact adopted prose, reports, and admitted evidence for revision",
    )
    review_revision_input.add_argument("--project-id", required=True)
    review_revision_input.add_argument("--review-id", required=True)
    review_revision_input.add_argument("--source-adoption-run-id", required=True)
    review_revision_input.add_argument("--target-manuscript-id", required=True)
    review_revision_input.add_argument("--evaluation-evidence-run-id", action="append", default=[])
    review_revision_input.add_argument("--expected-revision", type=int, required=True)
    review_revision_input.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional new file receiving only the typed revision-node input",
    )
    review_revision_input.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_revision_input)
    review_revision_input.set_defaults(handler=_handle_project_paper_review_revision_input)

    review_revision_runtime = project_paper_review_commands.add_parser(
        "revision-runtime-config",
        help="Build a profile-bound paper-revision invocation without calling a model",
    )
    review_revision_runtime.add_argument("--project-id", required=True)
    review_revision_runtime.add_argument("--review-id", required=True)
    review_revision_runtime.add_argument("--source-adoption-run-id", required=True)
    review_revision_runtime.add_argument("--target-manuscript-id", required=True)
    review_revision_runtime.add_argument(
        "--evaluation-evidence-run-id", action="append", default=[]
    )
    review_revision_runtime.add_argument("--profile-set", type=Path, required=True)
    review_revision_runtime.add_argument("--profile-id", required=True)
    review_revision_runtime.add_argument("--backend-config", type=Path, required=True)
    review_revision_runtime.add_argument("--expected-revision", type=int, required=True)
    review_revision_runtime.add_argument("--seed", type=int, default=0)
    review_revision_runtime.add_argument("--output", type=Path, required=True)
    review_revision_runtime.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(review_revision_runtime)
    review_revision_runtime.set_defaults(
        handler=_handle_project_paper_review_revision_runtime_config
    )

    register_model_node_pilot_cli(commands)
    register_model_node_runtime_cli(commands)

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
    hypothesize = commands.add_parser(
        "hypothesize",
        help="Initialize a discovery state and form a falsifiable working hypothesis",
    )
    _add_common_options(hypothesize, default_output="outputs/hypothesize")
    hypothesize.set_defaults(
        handler=_handle_discovery_command,
        discovery_command=DiscoveryCommand.HYPOTHESIZE,
        state=None,
        signal_number=None,
        reformulation_number=None,
    )
    probe = commands.add_parser(
        "probe",
        help="Run one diagnostic probe against a persisted working hypothesis",
    )
    _add_common_options(probe, default_output="outputs/probe")
    probe.add_argument("--state", type=Path, required=True)
    probe.add_argument(
        "--signal-number",
        type=int,
        default=None,
        help="1-based registered signal; defaults to the next unconsumed probe signal",
    )
    probe.set_defaults(
        handler=_handle_discovery_command,
        discovery_command=DiscoveryCommand.PROBE,
        reformulation_number=None,
    )
    reformulate = commands.add_parser(
        "reformulate",
        help="Retain a contradiction and form a new working hypothesis",
    )
    _add_common_options(reformulate, default_output="outputs/reformulate")
    reformulate.add_argument("--state", type=Path, required=True)
    reformulate.add_argument(
        "--reformulation-number",
        type=int,
        default=None,
        help="1-based registered reformulation; defaults to the next candidate",
    )
    reformulate.set_defaults(
        handler=_handle_discovery_command,
        discovery_command=DiscoveryCommand.REFORMULATE,
        signal_number=None,
    )
    ideate = commands.add_parser(
        "ideate",
        help="Form a research problem and generate normalized mature ideas",
    )
    _add_common_options(ideate, default_output="outputs/ideate")
    ideate.add_argument("--state", type=Path, required=True)
    ideate.set_defaults(
        handler=_handle_discovery_command,
        discovery_command=DiscoveryCommand.IDEATE,
        signal_number=None,
        reformulation_number=None,
    )
    portfolio = commands.add_parser("portfolio", help="Research idea portfolio operations")
    portfolio_commands = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_select = portfolio_commands.add_parser(
        "select",
        help="Select a primary idea and construct a multi-slot portfolio",
    )
    _add_common_options(portfolio_select, default_output="outputs/portfolio-select")
    portfolio_select.add_argument("--state", type=Path, required=True)
    portfolio_select.set_defaults(
        handler=_handle_discovery_command,
        discovery_command=DiscoveryCommand.PORTFOLIO_SELECT,
        signal_number=None,
        reformulation_number=None,
    )
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
    benchmark_run.add_argument(
        "--candidate-order",
        choices=[item.value for item in CandidateOrder],
        default=CandidateOrder.DECLARED.value,
        help="Fixed candidate ordering; formal v2 runs require separate declared and reversed arms",
    )
    benchmark_run.set_defaults(handler=_handle_benchmark_run)
    benchmark_curate = benchmark_commands.add_parser(
        "curate", help="Inspect or compile a human-labelled SciTasteBench v2 package"
    )
    benchmark_curate.add_argument("--package", type=Path, required=True)
    benchmark_curate.add_argument("--evidence-root", type=Path, required=True)
    benchmark_curate.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the compiled suite only when every curation gate passes",
    )
    _add_log_level_option(benchmark_curate)
    benchmark_curate.set_defaults(handler=_handle_benchmark_curate)
    benchmark_source_status = benchmark_commands.add_parser(
        "source-status",
        help="Inspect a metadata-only SciTasteBench source screen without acquisition",
    )
    benchmark_source_status.add_argument("--manifest", type=Path, required=True)
    _add_log_level_option(benchmark_source_status)
    benchmark_source_status.set_defaults(handler=_handle_benchmark_source_status)
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

    evaluation = commands.add_parser(
        "evaluation", help="Evaluation design and no-run resource gates"
    )
    evaluation_commands = evaluation.add_subparsers(dest="evaluation_command", required=True)
    prelaunch = evaluation_commands.add_parser(
        "prelaunch", help="Inspect a hash-bound experiment resource manifest"
    )
    prelaunch.add_argument("--manifest", type=Path, required=True)
    prelaunch.add_argument("--resource-corpus", type=Path, required=True)
    prelaunch.add_argument(
        "--source-root",
        type=Path,
        default=Path("."),
        help="inspect the exact executable Git checkout (default: current repository)",
    )
    prelaunch.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("."),
        help="verify content-bound protocol evidence (default: current repository)",
    )
    prelaunch.add_argument(
        "--require-ready",
        action="store_true",
        help="Return a nonzero status when readiness or authorization is incomplete",
    )
    _add_log_level_option(prelaunch)
    prelaunch.set_defaults(handler=_handle_evaluation_prelaunch)
    decision_dossier = evaluation_commands.add_parser(
        "decision-dossier",
        help="Inspect a compact API/GPU experiment campaign without external actions",
    )
    decision_dossier.add_argument("--manifest", type=Path, required=True)
    decision_dossier.add_argument("--evidence-root", type=Path, default=Path("."))
    decision_dossier.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional no-run JSON report output",
    )
    decision_dossier.add_argument(
        "--require-artifacts",
        action="store_true",
        help="return nonzero when any content-bound planning artifact is missing or drifted",
    )
    _add_log_level_option(decision_dossier)
    decision_dossier.set_defaults(handler=_handle_evaluation_decision_dossier)
    acquisition_request = evaluation_commands.add_parser(
        "acquisition-request",
        help="Inspect an exact download allowlist without accessing the network",
    )
    acquisition_request.add_argument("--manifest", type=Path, required=True)
    acquisition_request.add_argument("--workspace-root", type=Path, default=Path("."))
    acquisition_request.add_argument("--output", type=Path, default=None)
    acquisition_request.add_argument(
        "--require-review-ready",
        action="store_true",
        help="return nonzero when evidence, license, or destination gates block owner review",
    )
    acquisition_request.add_argument(
        "--require-authorized",
        action="store_true",
        help="return nonzero until the exact request hash has explicit owner approval",
    )
    _add_log_level_option(acquisition_request)
    acquisition_request.set_defaults(handler=_handle_evaluation_acquisition_request)
    acquisition_approve = evaluation_commands.add_parser(
        "acquisition-approve",
        help="Bind owner approval to an exact review-ready download request without downloading",
    )
    acquisition_approve.add_argument("--manifest", type=Path, required=True)
    acquisition_approve.add_argument("--workspace-root", type=Path, default=Path("."))
    acquisition_approve.add_argument("--confirm-request-sha256", required=True)
    acquisition_approve.add_argument("--approved-by", required=True)
    acquisition_approve.add_argument(
        "--approved-at",
        required=True,
        help="timezone-aware ISO-8601 owner approval timestamp",
    )
    acquisition_approve.add_argument("--output", type=Path, required=True)
    _add_log_level_option(acquisition_approve)
    acquisition_approve.set_defaults(handler=_handle_evaluation_acquisition_approve)
    acquisition_download = evaluation_commands.add_parser(
        "acquisition-download",
        help="Atomically materialize one exactly approved download-only request",
    )
    acquisition_download.add_argument("--manifest", type=Path, required=True)
    acquisition_download.add_argument("--workspace-root", type=Path, default=Path("."))
    acquisition_download.add_argument("--confirm-request-sha256", required=True)
    acquisition_download.add_argument(
        "--allow-network-download",
        action="store_true",
        help="explicitly permit only the approved allowlisted download transaction",
    )
    _add_log_level_option(acquisition_download)
    acquisition_download.set_defaults(handler=_handle_evaluation_acquisition_download)
    task_selection = evaluation_commands.add_parser(
        "task-selection",
        help="Inspect an exact metadata-only benchmark task selection",
    )
    task_selection.add_argument("--manifest", type=Path, required=True)
    task_selection.add_argument("--resource-corpus", type=Path, required=True)
    task_selection.add_argument(
        "--require-scope-ready",
        action="store_true",
        help="Return nonzero when the metadata scope is not ready for owner review",
    )
    _add_log_level_option(task_selection)
    task_selection.set_defaults(handler=_handle_evaluation_task_selection)
    task_package = evaluation_commands.add_parser(
        "task-package",
        help="Inspect already-acquired benchmark task bytes without downloading or running them",
    )
    task_package.add_argument("--manifest", type=Path, required=True)
    task_package.add_argument("--selection", type=Path, required=True)
    task_package.add_argument("--resource-corpus", type=Path, required=True)
    task_package.add_argument("--source-root", type=Path, default=Path("."))
    task_package.add_argument(
        "--require-binding-ready",
        action="store_true",
        help="Return nonzero until the package, selection, and resource gates allow binding",
    )
    _add_log_level_option(task_package)
    task_package.set_defaults(handler=_handle_evaluation_task_package)
    adapter_preflight = evaluation_commands.add_parser(
        "adapter-preflight",
        help="Inspect a pinned external-system adapter without running it",
    )
    adapter_preflight.add_argument("--manifest", type=Path, required=True)
    adapter_preflight.add_argument("--resource-corpus", type=Path, required=True)
    adapter_preflight.add_argument("--source-root", type=Path, default=Path("."))
    adapter_preflight.add_argument(
        "--require-adapter-ready",
        action="store_true",
        help="Return nonzero until every matched-adapter requirement is verified",
    )
    _add_log_level_option(adapter_preflight)
    adapter_preflight.set_defaults(handler=_handle_evaluation_adapter_preflight)
    adapter_contract = evaluation_commands.add_parser(
        "adapter-contract",
        help="Inspect external-system task/model translation feasibility without execution",
    )
    adapter_contract.add_argument("--manifest", type=Path, required=True)
    adapter_contract.add_argument("--resource-corpus", type=Path, required=True)
    adapter_contract.add_argument("--source-root", type=Path, default=Path("."))
    adapter_contract.add_argument(
        "--require-upstream-preflight-ready",
        action="store_true",
        help="Return nonzero until the translation can proceed to a local upstream preflight",
    )
    _add_log_level_option(adapter_contract)
    adapter_contract.set_defaults(handler=_handle_evaluation_adapter_contract)
    cell_plan = evaluation_commands.add_parser(
        "cell-plan",
        help="Expand a prelaunch proposal into a content-addressed no-run cell matrix",
    )
    cell_plan.add_argument("--manifest", type=Path, required=True)
    cell_plan.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional canonical JSON output; omitted for mutation-free inspection",
    )
    cell_plan.add_argument(
        "--require-preparation-ready",
        action="store_true",
        help="return nonzero until every cell is ready for launch preparation",
    )
    _add_log_level_option(cell_plan)
    cell_plan.set_defaults(handler=_handle_evaluation_cell_plan)
    direct_agent_run = evaluation_commands.add_parser(
        "direct-agent-run",
        help="Run one exactly approved prompt-only API control cell",
    )
    direct_agent_run.add_argument("--invocation", type=Path, required=True)
    direct_agent_run.add_argument("--task-root", type=Path, required=True)
    direct_agent_run.add_argument("--backend-config", type=Path, required=True)
    direct_agent_run.add_argument("--output", type=Path, required=True)
    direct_agent_run.add_argument(
        "--allow-live",
        action="store_true",
        help="explicitly authorize the one provider call bound by the invocation",
    )
    _add_log_level_option(direct_agent_run)
    direct_agent_run.set_defaults(handler=_handle_evaluation_direct_agent_run)

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
    study_status = study_commands.add_parser(
        "status",
        help="Inspect exact-protocol progress across integrity-checked result sources",
    )
    study_status.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/matched_budget_study_v1.yaml"),
    )
    study_status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    study_status.add_argument(
        "--results",
        type=Path,
        action="append",
        default=None,
        help="Additional study_results.json path; repeat to add sources",
    )
    study_status.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional status JSON path; omitted for a mutation-free inspection",
    )
    _add_log_level_option(study_status)
    study_status.set_defaults(handler=_handle_study_status)
    return parser


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


def _handle_project_lifecycle_status(args: argparse.Namespace) -> int:
    assessment = assess_project_lifecycle(ProjectRuntime(args.outputs_root), args.project_id)
    print(assessment.model_dump_json(indent=2))
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


def _handle_project_discovery_advance(args: argparse.Namespace) -> int:
    scenario = load_discovery_scenario(args.config)
    workflow = ProjectDiscoveryWorkflow(args.outputs_root, seed=args.seed)
    operation = DiscoveryCommand(args.operation)
    semantic = _load_project_discovery_semantic(args)
    knowledge = (
        load_discovery_knowledge_binding(args.native_knowledge_config)
        if args.native_knowledge_config is not None
        else None
    )
    arguments = {
        "project_id": args.project_id,
        "run_id": args.run_id,
        "command": operation,
        "expected_revision": args.expected_revision,
        "signal_number": args.signal_number,
        "reformulation_number": args.reformulation_number,
        "resume": args.resume,
        "semantic": semantic,
        "knowledge": knowledge,
    }
    if args.dry_run:
        print(workflow.preview(scenario, **arguments).model_dump_json(indent=2))
        return 0
    report = workflow.advance(
        scenario,
        evidence_scope=args.evidence_scope,
        **arguments,
    )
    print(report.model_dump_json(indent=2))
    return 0


def _load_project_discovery_semantic(
    args: argparse.Namespace,
) -> DiscoverySemanticBinding | None:
    values = (
        args.semantic_config,
        args.semantic_profile_set,
        args.semantic_profile_id,
    )
    if not any(value is not None for value in values):
        if args.semantic_allow_live:
            raise ValueError("--semantic-allow-live requires semantic configuration")
        return None
    if not all(value is not None for value in values):
        raise ValueError(
            "--semantic-config, --semantic-profile-set, and --semantic-profile-id "
            "must be supplied together"
        )
    loaded_config = load_discovery_semantic_runtime_config(args.semantic_config)
    loaded_profiles = load_model_node_profile_set(args.semantic_profile_set)
    try:
        profile = loaded_profiles.profiles[args.semantic_profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown semantic profile {args.semantic_profile_id!r}") from exc
    backend_is_live = loaded_config.config.backend.mode.value == "live"
    if backend_is_live and not loaded_profiles.profile_set.live_enabled:
        raise ValueError("semantic profile set does not enable live execution")
    return loaded_config.config.binding(
        profile,
        invocation_id="discovery-hypothesis-001",
        allow_live=args.semantic_allow_live,
    )


def _handle_project_discovery_verify(args: argparse.Namespace) -> int:
    report = ProjectDiscoveryWorkflow(args.outputs_root).verify(
        args.project_id,
        args.run_id,
    )
    print(report.model_dump_json(indent=2))
    return 0


def _handle_project_evaluation_register_prelaunch(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    if snapshot.revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
        )
    prepared = prepare_project_evaluation(
        project_id=args.project_id,
        evaluation_id=args.evaluation_id,
        manifest_path=args.manifest,
        resource_corpus_path=args.resource_corpus,
        source_root=args.source_root,
        evidence_root=args.evidence_root,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned-no-run-publication",
                    "next_revision": snapshot.revision + 1 + int(args.select),
                    "selection_requested": args.select,
                    "bundle": prepared.bundle.model_dump(mode="json"),
                    "no_execution_performed": True,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = publish_project_evaluation(
        runtime,
        prepared,
        expected_revision=args.expected_revision,
        select=args.select,
    )
    print(
        json.dumps(
            {
                "status": "registered-no-run-evaluation",
                "project_id": args.project_id,
                "project_revision": snapshot.revision,
                "evaluation_id": prepared.bundle.evaluation_id,
                "evaluation_status": prepared.bundle.status,
                "proposal_sha256": prepared.bundle.proposal_sha256,
                "planned_cells": prepared.bundle.planned_cells,
                "ready_for_author_review": prepared.bundle.ready_for_author_review,
                "execution_authorized": prepared.bundle.execution_authorized,
                "record_locator": snapshot.evaluation_locators[prepared.bundle.evaluation_id],
                "selected": snapshot.manifest.current_evaluation == prepared.bundle.evaluation_id,
                "no_execution_performed": True,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_evaluation_select(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        if args.evaluation_id not in snapshot.evaluation_locators:
            raise ValueError(f"unknown project evaluation {args.evaluation_id!r}")
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "current_evaluation": args.evaluation_id,
                    "no_execution_performed": True,
                },
                indent=2,
            )
        )
        return 0
    snapshot = runtime.select_evaluation(
        args.project_id,
        args.evaluation_id,
        expected_revision=args.expected_revision,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_evaluation_status(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    evaluation_id = args.evaluation_id or snapshot.manifest.current_evaluation
    if evaluation_id is None:
        raise ValueError("project has no current evaluation; pass --evaluation-id")
    bundle = runtime.open_evaluation(args.project_id, evaluation_id)
    decision_map = summarize_evaluation_readiness(bundle)
    print(
        json.dumps(
            {
                "project_id": args.project_id,
                "project_revision": snapshot.revision,
                "evaluation_id": evaluation_id,
                "status": bundle.status,
                "planned_cells": bundle.planned_cells,
                "api_resources": bundle.api_resources,
                "gpu_resources": bundle.gpu_resources,
                "decision_map": decision_map.model_dump(mode="json"),
                "no_execution_performed": True,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_evaluation_register_result(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    if snapshot.revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
        )
    prepared = prepare_project_evaluation_result(
        runtime,
        project_id=args.project_id,
        evaluation_id=args.evaluation_id,
        result_id=args.result_id,
        result_set_path=args.result_set,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "verified-result-publication-plan",
                    "next_revision": snapshot.revision + 1 + int(args.select),
                    "selection_requested": args.select,
                    "bundle": prepared.bundle.model_dump(mode="json"),
                    "no_new_execution_performed": True,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared,
        expected_revision=args.expected_revision,
        select=args.select,
    )
    print(
        json.dumps(
            {
                "status": "registered-evaluation-result",
                "project_id": args.project_id,
                "project_revision": snapshot.revision,
                "result": prepared.bundle.model_dump(mode="json"),
                "selected": (snapshot.manifest.current_evaluation_result == args.result_id),
                "no_new_execution_performed": True,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_evaluation_select_result(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        if args.result_id not in snapshot.evaluation_result_locators:
            raise ValueError(f"unknown project evaluation result {args.result_id!r}")
        runtime.open_evaluation_result(args.project_id, args.result_id)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "current_evaluation_result": args.result_id,
                    "no_new_execution_performed": True,
                },
                indent=2,
            )
        )
        return 0
    snapshot = runtime.select_evaluation_result(
        args.project_id,
        args.result_id,
        expected_revision=args.expected_revision,
    )
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_evaluation_result_status(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    result_id = args.result_id or snapshot.manifest.current_evaluation_result
    if result_id is None:
        raise ValueError("project has no current evaluation result; pass --result-id")
    bundle = runtime.open_evaluation_result(args.project_id, result_id)
    print(
        json.dumps(
            {
                "project_id": args.project_id,
                "project_revision": snapshot.revision,
                "result": bundle.model_dump(mode="json"),
                "revalidated": True,
                "no_new_execution_performed": True,
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
        artifact=args.artifact,
        generative_ui_projection=args.generative_ui_projection,
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


def _handle_project_run_update(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    if snapshot.revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
        )
    try:
        registered = next(item for item in snapshot.manifest.runs if item.run_id == args.run_id)
    except StopIteration as exc:
        raise ValueError(f"unknown project run {args.run_id!r}") from exc
    optional = {
        "evidence_scope": args.evidence_scope,
        "artifact": args.artifact,
        "superseded_by": args.superseded_by,
        "failure_code": args.failure_code,
        "failure_invocation_id": args.failure_invocation_id,
        "failure_receipt_sha256": args.failure_receipt_sha256,
        "backend_may_have_started": args.backend_may_have_started,
        "cost_status": args.cost_status,
        "retry_policy": args.retry_policy,
    }
    changes = {
        "status": args.status,
        **{key: value for key, value in optional.items() if value is not None},
    }
    if args.failure_receipt_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", args.failure_receipt_sha256
    ):
        raise ValueError("failure receipt SHA-256 must be 64 lowercase hexadecimal characters")
    failure_fields = {
        "failure_code",
        "failure_invocation_id",
        "failure_receipt_sha256",
        "backend_may_have_started",
        "cost_status",
        "retry_policy",
    }
    if failure_fields & changes.keys() and not args.status.startswith("failed"):
        raise ValueError("failure metadata requires a failed run status")
    updated = ProjectRun.model_validate({**registered.model_dump(mode="json"), **changes})
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1,
                    "run": updated.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot = runtime.update_run(
        args.project_id,
        args.run_id,
        expected_revision=args.expected_revision,
        **changes,
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


def _handle_project_paper_build(args: argparse.Namespace) -> int:
    """Materialize a venue submission under project ownership and register it."""

    validate_entry_id(args.directory_name, field_name="paper directory")
    runtime = ProjectRuntime(args.outputs_root)
    snapshot = runtime.open(args.project_id)
    if snapshot.revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
        )
    source_run = args.source_run or snapshot.manifest.current_run
    if source_run is not None and source_run not in snapshot.run_locators:
        raise ValueError(f"unknown project run {source_run!r}")
    evaluation_result_id = getattr(args, "evaluation_result_id", None)
    scientific_result = (
        require_selected_scientific_evidence(
            runtime,
            project_id=args.project_id,
            result_id=evaluation_result_id,
        )
        if evaluation_result_id is not None
        else None
    )
    source = args.source.resolve(strict=True)
    bibliography = args.bibliography.resolve(strict=True)
    if not source.is_file() or not bibliography.is_file():
        raise ValueError("paper source and bibliography must be regular files")
    template = inspect_venue_template(args.venue_config)
    markdown = source.read_text(encoding="utf-8", errors="strict")
    bibliography_text = bibliography.read_text(encoding="utf-8", errors="strict")
    preflight = assess_venue_submission(
        markdown,
        bibliography_text,
        template=template,
        compiled=False,
        main_text_pages=None,
    )
    manuscript_preflight = assess_manuscript(
        markdown,
        requested_role="research-working-draft",
    )
    writing_taste_preflight = assess_writing_taste(
        markdown,
        target_venue=template.config.venue_name,
    )
    argument_contract, argument_assessment = _assess_paper_argument_preflight(
        args,
        markdown=markdown,
    )
    venue_taste_context = _build_venue_taste_preflight(
        args,
        markdown=markdown,
        template_venue_id=template.config.venue_id,
        template_config_path=template.config_path,
        argument_contract=argument_contract,
    )
    project_dir = runtime.projects_root / args.project_id
    target = project_dir / "papers" / args.directory_name
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": args.project_id,
                    "directory_name": args.directory_name,
                    "source_run": source_run,
                    "venue_id": template.config.venue_id,
                    "template_fingerprint": template.fingerprint,
                    "preflight": preflight.model_dump(mode="json"),
                    "manuscript_preflight": manuscript_preflight.model_dump(mode="json"),
                    "writing_taste_preflight": writing_taste_preflight.model_dump(mode="json"),
                    "venue_taste_preflight": (
                        venue_taste_context.model_dump(mode="json")
                        if venue_taste_context is not None
                        else None
                    ),
                    "paper_argument_preflight": (
                        argument_assessment.model_dump(mode="json")
                        if argument_assessment is not None
                        else None
                    ),
                    "would_compile": True,
                    "would_register": True,
                    "would_select": args.select,
                    "paper_draft_trace": getattr(args, "_paper_draft_trace", None),
                    "paper_revision_trace": getattr(args, "_paper_revision_trace", None),
                    "scientific_evidence_binding": (
                        {
                            "result_id": scientific_result.result_id,
                            "evaluation_id": scientific_result.evaluation_id,
                            "result_bundle_sha256": scientific_result.bundle_sha256,
                            "assessment_sha256": scientific_result.assessment_sha256,
                            "scientific_effectiveness_established": (
                                scientific_result.scientific_effectiveness_established
                            ),
                            "would_bind_all_materialized_paper_artifacts": True,
                        }
                        if scientific_result is not None
                        else None
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    papers_dir = project_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".venue-build-", dir=papers_dir))
    moved = False
    registered = False
    try:
        paths, assessment, manuscript_assessment = materialize_venue_manuscript(
            markdown_path=source,
            bibliography_path=bibliography,
            target_dir=temporary,
            template=template,
            asset_roots=tuple(path.resolve(strict=True) for path in args.asset_root),
            venue_taste_context=venue_taste_context,
        )
        if argument_contract is not None and argument_assessment is not None:
            paths.extend(
                [
                    write_paper_argument_contract(
                        argument_contract,
                        temporary / "PAPER_ARGUMENT_CONTRACT.yaml",
                    ),
                    write_paper_argument_assessment(
                        argument_assessment,
                        temporary / "PAPER_ARGUMENT_ASSESSMENT.json",
                    ),
                ]
            )
        draft_trace_source = getattr(args, "_paper_draft_trace_source", None)
        if draft_trace_source is not None:
            draft_trace_target = temporary / "PAPER_DRAFT_TRACE.json"
            shutil.copyfile(draft_trace_source, draft_trace_target)
            paths.append(draft_trace_target)
        revision_trace_source = getattr(args, "_paper_revision_trace_source", None)
        if revision_trace_source is not None:
            revision_trace_target = temporary / "PAPER_REVISION_TRACE.json"
            shutil.copyfile(revision_trace_source, revision_trace_target)
            paths.append(revision_trace_target)
        scientific_evidence = None
        if evaluation_result_id is not None:
            materialized_evidence = materialize_paper_scientific_evidence(
                runtime,
                project_id=args.project_id,
                paper_id=args.directory_name,
                result_id=evaluation_result_id,
                paper_root=temporary,
                artifact_paths=tuple(paths),
            )
            paths.append(materialized_evidence.path)
            scientific_evidence = materialized_evidence.binding
        files = _venue_paper_file_map(paths, root=temporary)
        argument_metadata = (
            {
                "paper_argument_contract_sha256": argument_contract.contract_sha256,
                "paper_argument_assessment_sha256": argument_assessment.record_sha256,
                "paper_argument_contract_complete": argument_assessment.contract_complete,
            }
            if argument_contract is not None and argument_assessment is not None
            else {}
        )
        venue_taste_metadata = (
            {
                "venue_taste_profile_id": venue_taste_context.profile_id,
                "venue_taste_profile_fingerprint": venue_taste_context.profile_fingerprint,
                "venue_taste_context_sha256": venue_taste_context.record_sha256,
                "paper_archetype": venue_taste_context.paper_archetype.value,
            }
            if venue_taste_context is not None
            else {}
        )
        revision_metadata = getattr(args, "_paper_revision_manifest_metadata", {})
        paper = PaperManifest(
            paper_id=args.directory_name,
            project_id=args.project_id,
            title=assessment.title,
            date=date.fromisoformat(args.date),
            provider=args.provider,
            model=args.model,
            condition=args.condition,
            task=args.task,
            seed=args.seed,
            stage=args.stage,
            status="venue-submission-draft",
            evidence_scope=args.evidence_scope,
            publication_ready=False,
            source_run=source_run,
            files=files,
            scientific_evidence=scientific_evidence,
            venue_id=assessment.venue_id,
            template_fingerprint=assessment.template_fingerprint,
            submission_assessment_sha256=assessment.record_sha256,
            manuscript_assessment_sha256=manuscript_assessment.record_sha256,
            writing_taste_assessment_sha256=writing_taste_preflight.record_sha256,
            eligible_for_submission=(
                assessment.eligible_for_submission
                and revision_metadata.get("paper_revision_all_concerns_proof_complete", True)
            ),
            **argument_metadata,
            **venue_taste_metadata,
            **getattr(args, "_paper_draft_manifest_metadata", {}),
            **revision_metadata,
        )
        os.replace(temporary, target)
        moved = True
        snapshot = runtime.register_paper(
            args.project_id,
            paper,
            directory_name=args.directory_name,
            expected_revision=args.expected_revision,
        )
        registered = True
        if args.select:
            snapshot = runtime.select_paper(
                args.project_id,
                args.directory_name,
                expected_revision=snapshot.revision,
                global_latest=not args.no_global_latest,
            )
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        elif moved and not registered and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    print(snapshot.model_dump_json(indent=2))
    return 0


def _handle_project_paper_build_draft(args: argparse.Namespace) -> int:
    """Materialize one accepted evidence-paper-draft invocation through paper build."""

    runtime = ProjectRuntime(args.outputs_root)
    with tempfile.TemporaryDirectory(prefix="scitaste-paper-draft-") as temporary_root:
        materialized = materialize_accepted_paper_draft(
            runtime,
            project_id=args.project_id,
            run_id=args.run_id,
            invocation_id=args.invocation_id,
            bibliography_path=args.bibliography,
            target_dir=Path(temporary_root) / "source",
            expected_project_revision=args.expected_revision,
        )
        if materialized.input_data.manuscript_id != args.directory_name:
            raise ValueError("paper-draft manuscript_id must match the paper directory")
        delegated = vars(args).copy()
        delegated.update(
            source=materialized.manuscript_path,
            bibliography=materialized.bibliography_path,
            source_run=args.source_run or args.run_id,
            provider=args.provider or materialized.trace.provider,
            model=args.model or materialized.trace.model,
            _paper_draft_trace=materialized.trace.model_dump(mode="json"),
            _paper_draft_trace_source=materialized.trace_path,
            _paper_draft_manifest_metadata={
                "paper_draft_invocation_id": args.invocation_id,
                "paper_draft_ledger_entry_sha256": (materialized.trace.ledger_entry_sha256),
                "paper_draft_trace_sha256": materialized.trace.record_sha256,
                "paper_draft_input_fingerprint": materialized.trace.input_fingerprint,
                "paper_draft_proposal_sha256": materialized.trace.proposal_sha256,
            },
        )
        return _handle_project_paper_build(argparse.Namespace(**delegated))


def _handle_project_paper_build_revision(args: argparse.Namespace) -> int:
    """Materialize one accepted reviewer-driven revision through venue paper build."""

    runtime = ProjectRuntime(args.outputs_root)
    with tempfile.TemporaryDirectory(prefix="scitaste-paper-revision-") as temporary_root:
        materialized = materialize_accepted_paper_revision(
            runtime,
            project_id=args.project_id,
            review_id=args.review_id,
            run_id=args.run_id,
            invocation_id=args.invocation_id,
            bibliography_path=args.bibliography,
            target_dir=Path(temporary_root) / "source",
            expected_project_revision=args.expected_revision,
        )
        if materialized.input_data.target_manuscript_id != args.directory_name:
            raise ValueError("paper-revision target_manuscript_id must match the paper directory")
        delegated = vars(args).copy()
        delegated.update(
            source=materialized.manuscript_path,
            bibliography=materialized.bibliography_path,
            source_run=args.source_run or args.run_id,
            provider=args.provider or materialized.trace.provider,
            model=args.model or materialized.trace.model,
            _paper_revision_trace=materialized.trace.model_dump(mode="json"),
            _paper_revision_trace_source=materialized.trace_path,
            _paper_revision_manifest_metadata={
                "paper_revision_review_id": args.review_id,
                "paper_revision_invocation_id": args.invocation_id,
                "paper_revision_source_paper_directory": (
                    materialized.trace.source_paper_directory
                ),
                "paper_revision_source_manifest_sha256": (
                    materialized.trace.source_paper_manifest_sha256
                ),
                "paper_revision_ledger_entry_sha256": (materialized.trace.ledger_entry_sha256),
                "paper_revision_trace_sha256": materialized.trace.record_sha256,
                "paper_revision_input_fingerprint": materialized.trace.input_fingerprint,
                "paper_revision_proposal_sha256": (materialized.trace.revision_proposal_sha256),
                "paper_revision_blocked_concern_ids": list(materialized.trace.blocked_concern_ids),
                "paper_revision_all_concerns_proof_complete": (
                    materialized.trace.all_concerns_proof_complete
                ),
            },
        )
        return _handle_project_paper_build(argparse.Namespace(**delegated))


def _venue_paper_file_map(paths: list[Path], *, root: Path) -> dict[str, str]:
    labels = {
        "main.md": "source-markdown",
        "main.tex": "submission-tex",
        "main.pdf": "submission-pdf",
        "references.bib": "bibliography",
        "build.json": "build-record",
        "SUBMISSION_ASSESSMENT.json": "submission-assessment",
        "MANUSCRIPT_ASSESSMENT.json": "manuscript-assessment",
        "WRITING_TASTE_ASSESSMENT.json": "writing-taste-assessment",
        "PAPER_DRAFT_TRACE.json": "paper-draft-trace",
        "PAPER_REVISION_TRACE.json": "paper-revision-trace",
        "SCIENTIFIC_EVIDENCE_BINDING.json": "scientific-evidence-binding",
        "VENUE_TASTE_CONTEXT.json": "venue-taste-context",
        "PAPER_ARGUMENT_CONTRACT.yaml": "paper-argument-contract",
        "PAPER_ARGUMENT_ASSESSMENT.json": "paper-argument-assessment",
        "README.md": "bundle-readme",
    }
    mapped: dict[str, str] = {}
    for index, path in enumerate(sorted(paths)):
        relative = path.relative_to(root).as_posix()
        label = labels.get(relative, f"supporting-artifact-{index:02d}")
        mapped[label] = relative
    return mapped


def _build_venue_taste_preflight(
    args: argparse.Namespace,
    *,
    markdown: str,
    template_venue_id: str,
    template_config_path: Path,
    argument_contract: PaperArgumentContract | None,
) -> VenueWritingTasteContext | None:
    profile_path = args.venue_taste_profile
    if profile_path is None:
        sibling = template_config_path.parent / "taste.yaml"
        profile_path = sibling if sibling.is_file() else None
    if profile_path is None:
        return None
    inspection = inspect_venue_writing_taste(profile_path)
    require_venue_taste_matches_template(inspection, venue_id=template_venue_id)
    contract_archetype = argument_contract.archetype if argument_contract is not None else None
    if (
        args.paper_archetype is not None
        and contract_archetype is not None
        and args.paper_archetype != contract_archetype
    ):
        raise ValueError("--paper-archetype does not match the whole-paper argument contract")
    archetype = args.paper_archetype or contract_archetype or PaperArchetype.UNSPECIFIED.value
    return build_venue_writing_taste_context(
        markdown,
        inspection=inspection,
        paper_archetype=archetype,
    )


def _assess_paper_argument_preflight(
    args: argparse.Namespace,
    *,
    markdown: str,
) -> tuple[PaperArgumentContract | None, PaperArgumentAssessment | None]:
    contract_path = args.argument_contract
    state_path = args.argument_state
    if (contract_path is None) != (state_path is None):
        raise ValueError("--argument-contract and --argument-state must be supplied together")
    if contract_path is None or state_path is None:
        if args.argument_artifact_root is not None:
            raise ValueError("--argument-artifact-root requires an argument contract and state")
        return None, None
    contract = load_paper_argument_contract(contract_path.resolve(strict=True))
    state_source = state_path.resolve(strict=True)
    if not state_source.is_file():
        raise ValueError("argument state must be a regular file")
    state = ResearchState.model_validate_json(state_source.read_text(encoding="utf-8"))
    if contract.project_id != args.project_id or state.project_id != args.project_id:
        raise ValueError("paper argument contract and state must belong to the owning project")
    if contract.paper_id != args.directory_name:
        raise ValueError("paper argument contract paper_id must match --directory-name")
    artifact_root = (
        args.argument_artifact_root.resolve(strict=True)
        if args.argument_artifact_root is not None
        else args.source.resolve(strict=True).parent
    )
    assessment = assess_paper_argument(
        contract,
        claims=state.claims,
        evidence=state.evidence_graph.items,
        manuscript_markdown=markdown,
        artifact_root=artifact_root,
    )
    return contract, assessment


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


def _handle_project_paper_adopt_for_revision(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    prepared = prepare_project_paper_adoption(
        runtime,
        project_id=args.project_id,
        paper_directory=args.paper_directory,
        run_id=args.run_id,
        source_commit=args.source_commit,
        expected_revision=args.expected_revision,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": args.expected_revision + 2,
                    "would_call_model": False,
                    "would_generate_or_mutate_prose": False,
                    "scientific_evidence_established": False,
                    "adoption": prepared.bundle.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot, bundle = publish_project_paper_adoption(
        runtime,
        prepared=prepared,
        expected_revision=args.expected_revision,
    )
    print(
        json.dumps(
            {
                "project": snapshot.model_dump(mode="json"),
                "adoption": bundle.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_adoption_status(args: argparse.Namespace) -> int:
    bundle = inspect_project_paper_adoption(
        ProjectRuntime(args.outputs_root),
        args.project_id,
        args.run_id,
    )
    print(bundle.model_dump_json(indent=2))
    return 0


def _handle_project_paper_review_prepare(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    if args.dry_run:
        snapshot = runtime.open(args.project_id)
        if snapshot.revision != args.expected_revision:
            raise ValueError(
                f"stale project revision {args.expected_revision}; current is {snapshot.revision}"
            )
        packet = build_venue_review_packet(
            runtime,
            project_id=args.project_id,
            paper_directory=args.paper_directory,
            review_id=args.review_id,
            round_number=args.round_number,
            review_scope=args.scope,
            venue_taste_profile=args.venue_taste_profile,
        )
        print(
            json.dumps(
                {
                    "status": "planned",
                    "next_revision": snapshot.revision + 1 + int(args.select),
                    "would_call_model": False,
                    "packet": packet.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot, packet, review_round = prepare_venue_review(
        runtime,
        project_id=args.project_id,
        paper_directory=args.paper_directory,
        review_id=args.review_id,
        round_number=args.round_number,
        review_scope=args.scope,
        venue_taste_profile=args.venue_taste_profile,
        expected_revision=args.expected_revision,
        select=args.select,
    )
    _print_review_operation(snapshot, review_round, packet_sha256=packet.packet_sha256)
    return 0


def _handle_project_paper_review_import(args: argparse.Namespace) -> int:
    _reject_review_import_dry_run(args)
    report = VenueReviewReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    snapshot, review_round = import_venue_review_report(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        report=report,
        expected_revision=args.expected_revision,
    )
    _print_review_operation(snapshot, review_round, report_sha256=report.report_sha256)
    return 0


def _handle_project_paper_review_import_model(args: argparse.Namespace) -> int:
    _reject_review_import_dry_run(args)
    runtime = ProjectRuntime(args.outputs_root)
    legacy_values = (args.proposal, args.provider, args.model)
    ledger_values = (args.run_id, args.invocation_id)
    legacy_mode = all(value is not None for value in legacy_values) and not any(ledger_values)
    ledger_mode = all(value is not None for value in ledger_values) and not any(legacy_values)
    if not (legacy_mode or ledger_mode):
        raise ValueError(
            "model report import requires exactly one complete source: either "
            "--run-id with --invocation-id, or legacy --proposal with --provider and --model"
        )
    if ledger_mode:
        report = build_internal_model_review_report_from_runtime(
            runtime,
            project_id=args.project_id,
            review_id=args.review_id,
            run_id=args.run_id,
            invocation_id=args.invocation_id,
            report_id=args.report_id,
            reviewer_id=args.reviewer_id,
        )
    else:
        proposal = VenuePaperReviewProposal.model_validate_json(
            args.proposal.read_text(encoding="utf-8"), strict=True
        )
        packet = load_venue_review_packet(runtime, args.project_id, args.review_id)
        report = build_internal_model_review_report(
            packet,
            proposal,
            report_id=args.report_id,
            reviewer_id=args.reviewer_id,
            provider=args.provider,
            model=args.model,
        )
    snapshot, review_round = import_venue_review_report(
        runtime,
        project_id=args.project_id,
        review_id=args.review_id,
        report=report,
        expected_revision=args.expected_revision,
    )
    hashes = {"report_sha256": report.report_sha256}
    if report.model_invocation is not None:
        hashes["source_entry_sha256"] = report.model_invocation.entry_sha256
    _print_review_operation(snapshot, review_round, **hashes)
    return 0


def _handle_project_paper_review_model_input(args: argparse.Namespace) -> int:
    material = build_venue_paper_review_material(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        paper_label=args.paper_label,
        permitted_evidence_types=tuple(args.permitted_evidence_type),
    )
    print(material.model_dump_json(indent=2))
    return 0


def _handle_project_paper_review_runtime_config(args: argparse.Namespace) -> int:
    profiles = load_model_node_profile_set(args.profile_set)
    try:
        profile = profiles.profiles[args.profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown model-node profile {args.profile_id!r}") from exc
    material = build_venue_paper_review_material(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        paper_label=args.paper_label,
        permitted_evidence_types=tuple(args.permitted_evidence_type),
    )
    if material.project_revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; "
            f"current is {material.project_revision}"
        )
    config = build_venue_paper_review_runtime_config(
        material,
        profile=profile,
        backend_config=load_structured_openai_compatible_config(args.backend_config),
        seed=args.seed,
    )
    payload = (
        json.dumps(
            config.model_dump(mode="json", exclude_computed_fields=True),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "prepared",
                "project_id": material.project_id,
                "project_revision": material.project_revision,
                "review_id": material.review_id,
                "paper_text_sha256": material.node_input.paper_text_sha256,
                "packet_sha256": material.node_input.packet_sha256,
                "profile_id": profile.profile_id,
                "profile_fingerprint": profile.fingerprint,
                "profile_set_sha256": profiles.source_sha256,
                "backend_live_enabled": config.backend.config.live_enabled,
                "runtime_config": str(args.output),
                "runtime_config_sha256": hashlib.sha256(payload).hexdigest(),
                "model_called": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_review_respond(args: argparse.Namespace) -> int:
    _reject_review_import_dry_run(args)
    response = VenueReviewResponse.model_validate_json(args.response.read_text(encoding="utf-8"))
    snapshot, review_round = submit_venue_review_response(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        response=response,
        expected_revision=args.expected_revision,
    )
    _print_review_operation(snapshot, review_round, response_sha256=response.response_sha256)
    return 0


def _handle_project_paper_review_verify(args: argparse.Namespace) -> int:
    _reject_review_import_dry_run(args)
    verification = VenueReviewVerification.model_validate_json(
        args.verification.read_text(encoding="utf-8")
    )
    snapshot, review_round = import_venue_review_verification(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        verification=verification,
        expected_revision=args.expected_revision,
    )
    _print_review_operation(
        snapshot,
        review_round,
        verification_sha256=verification.verification_sha256,
    )
    return 0


def _handle_project_paper_review_status(args: argparse.Namespace) -> int:
    review_round = inspect_venue_review(
        ProjectRuntime(args.outputs_root), args.project_id, args.review_id
    )
    print(review_round.model_dump_json(indent=2))
    return 0


def _handle_project_paper_review_route_state(args: argparse.Namespace) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    prepared = prepare_project_review_routing(
        runtime,
        project_id=args.project_id,
        review_id=args.review_id,
        report_id=args.report_id,
        source_state_locator=args.source_state,
        run_id=args.run_id,
        source_commit=args.source_commit,
        expected_revision=args.expected_revision,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": args.project_id,
                    "current_revision": args.expected_revision,
                    "expected_published_revision": args.expected_revision + 2,
                    "bundle": prepared.bundle.model_dump(mode="json"),
                    "no_model_call_performed": True,
                    "scientific_evidence_established": False,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot, bundle = publish_project_review_routing(
        runtime,
        prepared=prepared,
        expected_revision=args.expected_revision,
    )
    print(
        json.dumps(
            {
                "project": snapshot.model_dump(mode="json"),
                "routing": bundle.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_review_routing_status(args: argparse.Namespace) -> int:
    bundle = inspect_project_review_routing(
        ProjectRuntime(args.outputs_root),
        args.project_id,
        args.run_id,
    )
    print(bundle.model_dump_json(indent=2))
    return 0


def _handle_project_paper_review_admit_evaluation_evidence(
    args: argparse.Namespace,
) -> int:
    runtime = ProjectRuntime(args.outputs_root)
    prepared = prepare_project_evaluation_evidence(
        runtime,
        project_id=args.project_id,
        routing_run_id=args.routing_run_id,
        result_id=args.result_id,
        run_id=args.run_id,
        source_commit=args.source_commit,
        expected_revision=args.expected_revision,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": args.project_id,
                    "current_revision": args.expected_revision,
                    "expected_published_revision": args.expected_revision + 2,
                    "bundle": prepared.bundle.model_dump(mode="json"),
                    "no_execution_performed": True,
                    "no_model_call_performed": True,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    snapshot, bundle = publish_project_evaluation_evidence(
        runtime,
        prepared=prepared,
        expected_revision=args.expected_revision,
    )
    print(
        json.dumps(
            {
                "project": snapshot.model_dump(mode="json"),
                "evaluation_evidence": bundle.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_review_evaluation_evidence_status(
    args: argparse.Namespace,
) -> int:
    bundle = inspect_project_evaluation_evidence(
        ProjectRuntime(args.outputs_root),
        args.project_id,
        args.run_id,
    )
    print(bundle.model_dump_json(indent=2))
    return 0


def _handle_project_paper_review_evaluation_closure_proofs(
    args: argparse.Namespace,
) -> int:
    proofs = build_project_evaluation_closure_proofs(
        ProjectRuntime(args.outputs_root),
        args.project_id,
        args.run_id,
    )
    print(
        json.dumps(
            {"closure_proofs": [item.model_dump(mode="json") for item in proofs]},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_review_revision_input(args: argparse.Namespace) -> int:
    evidence_run_ids = tuple(sorted(args.evaluation_evidence_run_id))
    if len(evidence_run_ids) != len(set(evidence_run_ids)):
        raise ValueError("evaluation-evidence run IDs must be unique")
    prepared = prepare_project_paper_revision_context(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        source_adoption_run_id=args.source_adoption_run_id,
        target_manuscript_id=args.target_manuscript_id,
        expected_revision=args.expected_revision,
        evaluation_evidence_run_ids=evidence_run_ids,
    )
    output = None
    if args.output is not None:
        output = args.output.expanduser().resolve()
        with output.open("x", encoding="utf-8") as handle:
            handle.write(prepared.input_data.model_dump_json(indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "prepared",
                "would_call_model": False,
                "would_execute_experiment": False,
                "context": prepared.bundle.model_dump(mode="json"),
                "revision_input": prepared.input_data.model_dump(mode="json"),
                "input_output": str(output) if output is not None else None,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_project_paper_review_revision_runtime_config(args: argparse.Namespace) -> int:
    evidence_run_ids = tuple(sorted(args.evaluation_evidence_run_id))
    if len(evidence_run_ids) != len(set(evidence_run_ids)):
        raise ValueError("evaluation-evidence run IDs must be unique")
    profiles = load_model_node_profile_set(args.profile_set)
    try:
        profile = profiles.profiles[args.profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown model-node profile {args.profile_id!r}") from exc
    prepared = prepare_project_paper_revision_context(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        review_id=args.review_id,
        source_adoption_run_id=args.source_adoption_run_id,
        target_manuscript_id=args.target_manuscript_id,
        expected_revision=args.expected_revision,
        evaluation_evidence_run_ids=evidence_run_ids,
    )
    config = build_project_paper_revision_runtime_config(
        prepared,
        profile=profile,
        backend_config=load_structured_openai_compatible_config(args.backend_config),
        seed=args.seed,
    )
    payload = (
        json.dumps(
            config.model_dump(mode="json", exclude_computed_fields=True),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "prepared",
                "project_id": prepared.bundle.project_id,
                "project_revision": prepared.bundle.project_revision,
                "review_id": prepared.bundle.review_id,
                "revision_context_sha256": prepared.bundle.record_sha256,
                "input_fingerprint": prepared.input_data.fingerprint,
                "blocked_concern_ids": prepared.bundle.blocked_concern_ids,
                "profile_id": profile.profile_id,
                "profile_fingerprint": profile.fingerprint,
                "profile_set_sha256": profiles.source_sha256,
                "backend_live_enabled": config.backend.config.live_enabled,
                "runtime_config": str(args.output),
                "runtime_config_sha256": hashlib.sha256(payload).hexdigest(),
                "model_called": False,
                "experiment_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _reject_review_import_dry_run(args: argparse.Namespace) -> None:
    if args.dry_run:
        raise ValueError(
            "review artifact imports are already validated before their atomic write; "
            "use review status for a read-only audit"
        )


def _print_review_operation(snapshot: object, review_round: object, **hashes: str) -> None:
    print(
        json.dumps(
            {
                "project": snapshot.model_dump(mode="json"),
                "review_round": review_round.model_dump(mode="json"),
                **hashes,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


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
    if not args.dry_run and not args.allow_live:
        raise ValueError("substrate execute requires --allow-live for provider-backed execution")
    action_type = MetaAction(args.action)
    if args.dry_run:
        result = AutoResearchClawExecutor(
            config_path=args.config,
            dry_run=True,
            timeout_seconds=args.timeout_seconds,
            max_output_tokens=args.max_output_tokens,
            max_total_tokens=args.max_total_tokens,
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
        max_total_tokens=args.max_total_tokens,
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


def _handle_discovery_command(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("offline discovery commands currently support only --backend mock")
    config_path = args.config or Path("configs/experiments/discovery_weak.yaml")
    scenario = load_discovery_scenario(config_path)
    state = (
        None
        if args.state is None
        else ResearchState.model_validate_json(args.state.read_text(encoding="utf-8"))
    )
    runner = DiscoveryCommandRunner(seed=args.seed)
    preview = runner.preview(
        args.discovery_command,
        scenario,
        state=state,
        signal_number=args.signal_number,
        reformulation_number=args.reformulation_number,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    **preview.model_dump(mode="json"),
                    "backend": args.backend,
                    "output": str(args.output),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    report = runner.run(
        args.discovery_command,
        scenario,
        output_dir=args.output,
        state=state,
        signal_number=args.signal_number,
        reformulation_number=args.reformulation_number,
    )
    print(report.model_dump_json(indent=2))
    return 0


def _handle_full(args: argparse.Namespace) -> int:
    config_path = args.config or Path("configs/workflows/full_offline_v1.yaml")
    config = load_full_workflow_config(config_path)
    if args.backend is not None and args.backend not in {"scitaste-native", "mock"}:
        raise ValueError("run full supports --backend scitaste-native or mock")
    if (
        args.project_id is not None
        or args.paper_directory is not None
        or args.backend is not None
        or args.research_brief is not None
    ):
        payload = config.model_dump(mode="python")
        if args.project_id is not None:
            payload["project_id"] = args.project_id
        if args.paper_directory is not None:
            payload["paper_directory"] = args.paper_directory
        if args.backend is not None:
            payload["execution_backend"] = args.backend
        if args.research_brief is not None:
            payload["research_brief"] = args.research_brief.resolve()
        config = type(config).model_validate(payload)
    run_id = args.run_id or f"offline-full-seed-{args.seed:02d}"
    if args.dry_run:
        execution_profile = (
            inspect_native_execution_profile(config.native_execution_profile)
            if config.native_execution_profile is not None
            else None
        )
        resource_preflight = (
            preflight_native_resources(
                execution_profile.profile,
                require_materialized_datasets=False,
            )
            if execution_profile is not None
            else None
        )
        code_generation = (
            load_native_code_generation_config(config.native_code_generation_config)
            if config.native_code_generation_config is not None
            else None
        )
        code_repair = (
            load_native_code_repair_config(config.native_code_repair_config)
            if config.native_code_repair_config is not None
            else None
        )
        if code_repair is not None:
            assert code_generation is not None
            validate_native_code_repair_binding(code_repair, code_generation)
        code_inspection = (
            inspect_native_code_proposal(config.native_code_proposal_config)
            if config.native_code_proposal_config is not None
            else None
        )
        registered_experiment = (
            load_native_experiment_definition(config.native_experiment_config)
            if config.native_experiment_config is not None
            else None
        )
        native_experiment = registered_experiment
        if code_inspection is not None and code_inspection.admission.decision == "accepted":
            native_experiment = code_inspection.experiment_definition(
                code_inspection.config.source_path
            )
        isolation = (
            NativeExperimentRunner(native_experiment).availability().model_dump(mode="json")
            if native_experiment is not None and config.execution_backend == "scitaste-native"
            else None
        )
        if isolation is not None and execution_profile is not None:
            isolation["resources"] = resource_preflight.model_dump(mode="json")
            isolation["resource_mount_probe"] = "deferred-until-project-materialization"
        model_advisory = (
            load_full_workflow_model_advisory(config.model_node_advisory)
            if config.model_node_advisory is not None
            else None
        )
        tool_intelligence = (
            load_full_workflow_tool_intelligence(config.tool_intelligence_advisory)
            if config.tool_intelligence_advisory is not None
            else None
        )
        research_intake = inspect_full_workflow_intake(config, run_id=run_id)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "project_id": config.project_id,
                    "run_id": run_id,
                    "provider": config.provider,
                    "model": config.model,
                    "execution_backend": config.execution_backend,
                    "research_intake": (
                        None
                        if research_intake is None
                        else {
                            "brief_id": research_intake.brief.brief_id,
                            "question": research_intake.brief.question,
                            "planning_mode": research_intake.plan.planning_mode,
                            "selected_bundle_id": research_intake.plan.selected_bundle_id,
                            "candidate_bundle_ids": list(research_intake.plan.candidate_bundle_ids),
                            "readiness": research_intake.plan.readiness,
                            "plan_sha256": research_intake.plan.record_sha256,
                            "input_bindings": [
                                item.model_dump(mode="json")
                                for item in research_intake.plan.input_bindings
                            ],
                            "model_authority": research_intake.plan.model_authority,
                            "execution_authority": research_intake.plan.execution_authority,
                            "would_materialize_on_run": True,
                            "limitations": list(research_intake.plan.limitations),
                        }
                    ),
                    "native_execution": {
                        "project_owned_records": config.execution_backend == "scitaste-native",
                        "knowledge_configured": config.native_knowledge_config is not None,
                        "knowledge_config": (
                            str(config.native_knowledge_config)
                            if config.native_knowledge_config is not None
                            else None
                        ),
                        "resource_profile": (
                            {
                                "profile_id": execution_profile.profile.profile_id,
                                "fingerprint": execution_profile.fingerprint,
                                "datasets": [
                                    item.model_dump(mode="json", exclude={"source_path"})
                                    for item in execution_profile.datasets
                                ],
                                "gpu_authorized": execution_profile.profile.gpu.enabled,
                                "preflight": resource_preflight.model_dump(mode="json"),
                                "would_materialize_datasets_on_run": True,
                            }
                            if execution_profile is not None
                            else {
                                "profile_id": "default-deny",
                                "datasets": [],
                                "gpu_authorized": False,
                            }
                        ),
                        "experiment_configured": (
                            registered_experiment is not None
                            or code_inspection is not None
                            or code_generation is not None
                        ),
                        "experiment_id": (
                            native_experiment.experiment_id
                            if native_experiment is not None
                            else (
                                code_inspection.config.experiment.experiment_id
                                if code_inspection is not None
                                else (
                                    code_generation.config.experiment.experiment_id
                                    if code_generation is not None
                                    else None
                                )
                            )
                        ),
                        "isolation_required": (
                            config.execution_backend == "scitaste-native"
                            and (native_experiment is not None or code_generation is not None)
                        ),
                        "isolation": isolation,
                        "code_admission": (
                            None
                            if code_inspection is None
                            else {
                                "proposal_id": code_inspection.config.proposal_id,
                                "producer_mode": code_inspection.config.producer.mode,
                                "decision": code_inspection.admission.decision,
                                "binding_sha256": code_inspection.binding_sha256,
                                "violation_count": len(code_inspection.admission.violations),
                                "violations": [
                                    item.model_dump(mode="json")
                                    for item in code_inspection.admission.violations
                                ],
                                "proposal_only": True,
                                "would_materialize_on_run": True,
                            }
                        ),
                        "code_generation": (
                            None
                            if code_generation is None
                            else {
                                "generation_id": code_generation.config.generation_id,
                                "proposal_id": code_generation.config.proposal_id,
                                "provider": code_generation.profile.provider,
                                "model": code_generation.profile.model,
                                "backend_mode": code_generation.config.backend.mode.value,
                                "max_output_tokens": (
                                    code_generation.profile.generation.max_output_tokens
                                ),
                                "live_configured": code_generation.config.live_enabled,
                                "caller_authorized": args.allow_live_model_nodes,
                                "would_contact_provider": (
                                    code_generation.config.live_enabled
                                    and args.allow_live_model_nodes
                                ),
                                "network_access": code_generation.config.live_enabled,
                                "proposal_only": True,
                                "deterministic_admission_required": True,
                                "runtime_isolation_required": True,
                                "would_materialize_on_run": True,
                            }
                        ),
                        "code_repair": (
                            None
                            if code_repair is None
                            else {
                                "repair_id": code_repair.config.repair_id,
                                "generation_id": code_repair.config.generation_id,
                                "repaired_proposal_id": (code_repair.config.repaired_proposal_id),
                                "provider": code_repair.profile.provider,
                                "model": code_repair.profile.model,
                                "backend_mode": code_repair.config.backend.mode.value,
                                "max_output_tokens": (
                                    code_repair.profile.generation.max_output_tokens
                                ),
                                "max_attempts": code_repair.config.max_attempts,
                                "conditional_on_static_rejection": True,
                                "live_configured": code_repair.config.live_enabled,
                                "caller_authorized": args.allow_live_model_nodes,
                                "would_contact_provider": (
                                    code_repair.config.live_enabled and args.allow_live_model_nodes
                                ),
                                "network_access": code_repair.config.live_enabled,
                                "repair_proposal_only": True,
                                "deterministic_readmission_required": True,
                                "runtime_isolation_required": True,
                                "would_materialize_only_if_rejected": True,
                            }
                        ),
                    },
                    "resume": args.resume,
                    "stages": ["discovery", "evidence", "communication", "figure"],
                    "model_advisory": (
                        None
                        if model_advisory is None
                        else {
                            "hook_id": model_advisory.config.hook_id,
                            "node_name": model_advisory.config.node_name,
                            "backend_mode": model_advisory.config.backend.mode.value,
                            "live_configured": model_advisory.config.live_enabled,
                            "caller_authorized": args.allow_live_model_nodes,
                            "would_contact_provider": (
                                model_advisory.config.live_enabled and args.allow_live_model_nodes
                            ),
                            "network_access": model_advisory.config.live_enabled,
                            "advisory_only": True,
                            "executable": False,
                        }
                    ),
                    "tool_intelligence": (
                        None
                        if tool_intelligence is None
                        else {
                            "hook_id": tool_intelligence.config.hook_id,
                            "trigger_claim_statuses": [
                                item.value
                                for item in tool_intelligence.config.trigger_claim_statuses
                            ],
                            "candidate_tools": [
                                item.value for item in tool_intelligence.config.candidate_tool_names
                            ],
                            "backend_mode": tool_intelligence.config.backend.mode.value,
                            "live_configured": tool_intelligence.config.live_enabled,
                            "caller_authorized": args.allow_live_model_nodes,
                            "would_contact_provider": (
                                tool_intelligence.config.live_enabled
                                and args.allow_live_model_nodes
                            ),
                            "network_access": tool_intelligence.config.live_enabled,
                            "automatic_trigger": "deterministic-claim-status-policy",
                            "advisory_only": True,
                            "canonical_evidence": False,
                            "state_transition_authorized": False,
                        }
                    ),
                    "paper_directory": config.paper_directory,
                    "paper": {
                        "title": config.paper_title,
                        "role": config.paper_role,
                        "publication_ready": False,
                        "research_working_draft_minimum_words": (
                            RESEARCH_WORKING_DRAFT_MINIMUM_WORDS
                        ),
                    },
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
        allow_live_model_nodes=args.allow_live_model_nodes,
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
    candidate_order = CandidateOrder(args.candidate_order)
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
                    "candidate_order": candidate_order.value,
                },
                indent=2,
            )
        )
        return 0
    if args.backend == "scripted":
        backend = ScriptedPreferenceBackend(
            scripted_selections(
                suite,
                conditions,
                candidate_order=candidate_order,
            )
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
            "supported benchmark backends: scripted, replay, openai-compatible, local-transformers"
        )
    if args.record:
        backend = RecordingBackend(backend, args.record)
    report = SciTasteBenchRunner(
        backend,
        seed=args.seed,
        candidate_order=candidate_order,
    ).evaluate(suite, conditions=conditions)
    manifest = save_benchmark_report(report, args.output)
    base = report.conditions[BenchmarkCondition.BASE].headline
    print(
        json.dumps(
            {
                "suite_id": report.suite_id,
                "backend": report.backend,
                "model": report.model,
                "candidate_order": report.candidate_order.value,
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


def _handle_benchmark_curate(args: argparse.Namespace) -> int:
    inspection = load_curation_package(args.package)
    report = inspect_curation_package(
        inspection.package,
        evidence_root=args.evidence_root,
    )
    payload: dict[str, object] = {
        "package_file_sha256": inspection.file_sha256,
        **report.model_dump(mode="json"),
        "compiled_suite": None,
        "no_model_call_performed": True,
        "no_gpu_work_performed": True,
    }
    if args.output is not None and report.ready_to_compile:
        suite = compile_curated_suite(
            inspection.package,
            evidence_root=args.evidence_root,
        )
        payload["compiled_suite"] = save_curated_suite(suite, args.output)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if report.ready_to_compile else 1


def _handle_benchmark_source_status(args: argparse.Namespace) -> int:
    inspection = load_source_candidate_manifest(args.manifest)
    report = source_candidate_status(inspection.manifest)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "hold",
                "file_sha256": inspection.file_sha256,
                **report.model_dump(mode="json"),
                "no_download_performed": True,
                "no_model_call_performed": True,
                "no_gpu_work_performed": True,
            },
            indent=2,
            ensure_ascii=False,
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


def _handle_evaluation_prelaunch(args: argparse.Namespace) -> int:
    inspection = load_prelaunch_manifest(args.manifest)
    corpus = load_external_resource_corpus(args.resource_corpus)
    source_commit, source_tree_clean = inspect_git_source(args.source_root)
    report = inspect_prelaunch_manifest(
        inspection.manifest,
        corpus.corpus,
        observed_source_commit=source_commit,
        source_tree_clean=source_tree_clean,
    )
    critic_report = EvaluationCriticSuite().review(
        inspection.manifest,
        corpus.corpus,
        report,
        evidence_root=args.evidence_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "resource_corpus_path": str(corpus.path),
        "resource_corpus_file_sha256": corpus.file_sha256,
        "resource_corpus_semantic_sha256": corpus.semantic_sha256,
        **report.model_dump(mode="json"),
        "critic_review": critic_report.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_ready and (
        not critic_report.ready_for_author_review or not report.execution_authorized
    ):
        return 1
    return 0


def _handle_evaluation_decision_dossier(args: argparse.Namespace) -> int:
    inspection = load_experiment_decision_dossier(args.manifest)
    report = inspect_experiment_decision_dossier(
        inspection.dossier,
        evidence_root=args.evidence_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        **report.model_dump(mode="json"),
    }
    if args.output is not None:
        payload["report"] = str(save_experiment_decision_dossier_report(report, args.output))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_artifacts and not report.artifact_bindings_verified:
        return 1
    return 0


def _handle_evaluation_acquisition_request(args: argparse.Namespace) -> int:
    inspection = load_dataset_acquisition_request(args.manifest)
    report = inspect_dataset_acquisition_request(
        inspection.request,
        workspace_root=args.workspace_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        **report.model_dump(mode="json"),
    }
    if args.output is not None:
        payload["report"] = str(save_acquisition_gate_report(report, args.output))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_review_ready and not report.ready_for_owner_approval:
        return 1
    if args.require_authorized and not report.download_authorized:
        return 1
    return 0


def _handle_evaluation_acquisition_approve(args: argparse.Namespace) -> int:
    inspection = load_dataset_acquisition_request(args.manifest)
    report = inspect_dataset_acquisition_request(
        inspection.request,
        workspace_root=args.workspace_root,
    )
    if not report.ready_for_owner_approval:
        codes = ", ".join(item.code for item in report.blockers)
        raise ValueError(f"dataset acquisition request is not review-ready: {codes}")
    approved = approve_dataset_acquisition_request(
        inspection.request,
        confirmed_request_sha256=args.confirm_request_sha256,
        approved_by=args.approved_by,
        approved_at=datetime.fromisoformat(args.approved_at),
    )
    output = save_dataset_acquisition_request(approved, args.output)
    approved_report = inspect_dataset_acquisition_request(
        approved,
        workspace_root=args.workspace_root,
    )
    print(
        json.dumps(
            {
                "manifest_path": str(inspection.path),
                "manifest_file_sha256": inspection.file_sha256,
                "approved_request": str(output),
                "request_sha256": approved.request_sha256,
                "download_authorized": approved_report.download_authorized,
                "authorization_scope": approved.authorization_scope,
                "authorizes_ingestion": approved.authorizes_ingestion,
                "authorizes_execution": approved.authorizes_execution,
                "download_performed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_evaluation_acquisition_download(args: argparse.Namespace) -> int:
    inspection = load_dataset_acquisition_request(args.manifest)
    receipt = materialize_dataset_acquisition(
        inspection.request,
        workspace_root=args.workspace_root,
        confirmed_request_sha256=args.confirm_request_sha256,
        allow_network_download=args.allow_network_download,
    )
    transaction_root = (
        args.workspace_root / Path(inspection.request.destination_root).parent
    ).resolve()
    print(
        json.dumps(
            {
                "manifest_path": str(inspection.path),
                "manifest_file_sha256": inspection.file_sha256,
                "receipt_path": str(transaction_root / "RECEIPT.json"),
                **receipt.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_evaluation_task_selection(args: argparse.Namespace) -> int:
    inspection = load_task_selection_manifest(args.manifest)
    corpus = load_external_resource_corpus(args.resource_corpus)
    report = inspect_task_selection(inspection.manifest, corpus.corpus)
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "resource_corpus_path": str(corpus.path),
        "resource_corpus_file_sha256": corpus.file_sha256,
        **report.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_scope_ready and not report.ready_for_owner_scope_review:
        return 1
    return 0


def _handle_evaluation_task_package(args: argparse.Namespace) -> int:
    inspection = load_task_package_manifest(args.manifest)
    selection = load_task_selection_manifest(args.selection)
    corpus = load_external_resource_corpus(args.resource_corpus)
    report = inspect_task_package(
        inspection.manifest,
        selection,
        corpus.corpus,
        source_root=args.source_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "selection_path": str(selection.path),
        "selection_file_sha256": selection.file_sha256,
        "resource_corpus_path": str(corpus.path),
        "resource_corpus_file_sha256": corpus.file_sha256,
        **report.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_binding_ready and not report.ready_for_prelaunch_binding:
        return 1
    return 0


def _handle_evaluation_adapter_preflight(args: argparse.Namespace) -> int:
    inspection = load_adapter_preflight_manifest(args.manifest)
    corpus = load_external_resource_corpus(args.resource_corpus)
    report = inspect_adapter_preflight(
        inspection.manifest,
        corpus.corpus,
        source_root=args.source_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "resource_corpus_path": str(corpus.path),
        "resource_corpus_file_sha256": corpus.file_sha256,
        **report.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_adapter_ready and not report.ready_for_matched_adapter:
        return 1
    return 0


def _handle_evaluation_adapter_contract(args: argparse.Namespace) -> int:
    inspection = load_adapter_contract_manifest(args.manifest)
    corpus = load_external_resource_corpus(args.resource_corpus)
    report = inspect_adapter_contract(
        inspection.manifest,
        corpus.corpus,
        source_root=args.source_root,
    )
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "resource_corpus_path": str(corpus.path),
        "resource_corpus_file_sha256": corpus.file_sha256,
        **report.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_upstream_preflight_ready and not report.ready_for_upstream_preflight:
        return 1
    return 0


def _handle_evaluation_cell_plan(args: argparse.Namespace) -> int:
    inspection = load_prelaunch_manifest(args.manifest)
    plan = compile_evaluation_cell_plan(inspection.manifest)
    payload = {
        "manifest_path": str(inspection.path),
        "manifest_file_sha256": inspection.file_sha256,
        "manifest_id": plan.manifest_id,
        "proposal_sha256": plan.proposal_sha256,
        "plan_sha256": plan.plan_sha256,
        "planned_cells": len(plan.cells),
        "ready_cells": sum(cell.ready_for_launch_preparation for cell in plan.cells),
        "blocked_cells": sum(not cell.ready_for_launch_preparation for cell in plan.cells),
        "ready_for_launch_preparation": plan.ready_for_launch_preparation,
        "proposal_author_approved": plan.proposal_author_approved,
        "authorizes_execution": plan.authorizes_execution,
        "plan_blockers": plan.plan_blockers,
        "no_provider_call_performed": plan.no_provider_call_performed,
        "no_gpu_work_performed": plan.no_gpu_work_performed,
        "no_task_download_performed": plan.no_task_download_performed,
    }
    if args.output is not None:
        payload["cell_plan"] = str(save_evaluation_cell_plan(plan, args.output))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_preparation_ready and not plan.ready_for_launch_preparation:
        return 1
    return 0


def _handle_evaluation_direct_agent_run(args: argparse.Namespace) -> int:
    receipt = run_live_direct_agent(
        invocation_path=args.invocation,
        task_root=args.task_root,
        backend_config_path=args.backend_config,
        output_dir=args.output,
        allow_live=args.allow_live,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                **receipt.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
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


def _handle_study_status(args: argparse.Namespace) -> int:
    protocol = load_study_protocol(args.config)
    paths = discover_study_result_paths(
        args.outputs_root,
        explicit_paths=args.results,
    )
    status = inspect_study_matrix(protocol, paths)
    payload = {
        "study_id": status.study_id,
        "protocol_sha256": status.protocol_sha256,
        "plan_sha256": status.plan_sha256,
        "evaluation_status": status.evaluation_status.value,
        "headline_eligible": status.headline_eligible,
        "planned_cells": status.planned_cells,
        "integrity_verified_records": status.integrity_verified_records,
        "succeeded_cells": status.succeeded_cells,
        "failed_cells": status.failed_cells,
        "valid_external_reviews": status.valid_external_reviews,
        "missing_cells": status.missing_cells,
        "compatible_sources": status.compatible_sources,
        "foreign_sources": status.foreign_sources,
        "invalid_sources": status.invalid_sources,
        "next_execution_batch": status.next_execution_batch,
        "next_review_batch": status.next_review_batch,
        "blockers": status.blockers,
        "sources": [source.model_dump(mode="json") for source in status.sources],
        "status_sha256": status.sha256,
    }
    if args.output is not None:
        saved = save_study_matrix_status(status, args.output)
        payload["status_report"] = str(saved)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


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

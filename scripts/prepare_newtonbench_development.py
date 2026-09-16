#!/usr/bin/env python3
"""Register and freeze one no-call NewtonBench Taste-development trajectory."""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import scitaste.evaluation.interactive_development as interactive_development_module
import scitaste.evaluation.interactive_research as interactive_research_module
import scitaste.evaluation.newtonbench_runtime as newtonbench_runtime_module
import scitaste.evaluation.sandboxed_code as sandboxed_code_module
from scitaste.evaluation.interactive_development import (
    InteractiveTasteDevelopmentProtocol,
    save_interactive_taste_development_protocol,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    StructuredInteractiveResearchAgent,
)
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.evaluation.sandboxed_code import BubblewrapPythonCodeRunner
from scitaste.evaluation.source_identity import (
    canonical_benchmark_task_source_group_id,
    load_canonical_source_identity_registry,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.idea_revision import (
    idea_scientific_contract_sha256,
    inspect_current_idea_revision,
)
from scitaste.project.models import ProjectRun, content_sha256
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.episodes import (
    TasteEpisodePartition,
    TasteEpisodeSourceRelationship,
)
from scitaste.taste.trajectory_reconstruction import (
    TasteTrajectoryAssignmentTiming,
    TasteTrajectorySamplingPlan,
    save_taste_trajectory_sampling_plan,
)

_MAX_CONFIG_BYTES = 4 * 1_048_576


def prepare(args: argparse.Namespace) -> tuple[InteractiveTasteDevelopmentProtocol, Path, Path]:
    runtime = ProjectRuntime(args.outputs_root)
    before = runtime.open(args.project_id)
    if before.revision != args.expected_revision:
        raise ValueError(
            f"stale project revision {args.expected_revision}; current is {before.revision}"
        )
    idea_report = inspect_current_idea_revision(runtime, args.project_id)
    if idea_report.current_binding is None or not idea_report.method_development_binding_available:
        raise ValueError("current project Idea is not available for method development")

    limits = _load_model(args.limits, InteractiveResearchLimits)
    task = _load_model(args.task, NewtonBenchTask)
    registry = load_canonical_source_identity_registry(args.source_identity_registry)
    source_group_id = canonical_benchmark_task_source_group_id("newtonbench", task.task_id)
    if registry.resolve(source_group_id) != source_group_id:
        raise ValueError("NewtonBench development task is absent from source registry")

    snapshot = runtime.begin_run(
        args.project_id,
        ProjectRun(
            run_id=args.run_id,
            provider=args.provider,
            model=args.model,
            condition="development-foundation",
            seed=args.agent_seed,
            status="planned",
            evidence_scope="development-scientific-outcome-no-formal-claim",
            stage_path="interactive_development",
        ),
        expected_revision=before.revision,
    )
    # Run registration is a project mutation, so the current Idea binding must
    # be derived from the resulting snapshot rather than reused from the
    # pre-registration revision.
    idea_report = inspect_current_idea_revision(runtime, args.project_id)
    idea = idea_report.current_binding
    if idea is None or idea.observed_project_revision != snapshot.revision:
        raise ValueError("current Idea could not be rebound after run registration")
    run_root = runtime.projects_root / args.project_id / "runs" / args.run_id
    stage_root = run_root / "interactive_development"
    plan = TasteTrajectorySamplingPlan.create(
        plan_id=f"{args.run_id}-prospective-taste",
        project_id=args.project_id,
        observed_project_revision=snapshot.revision,
        observed_project_snapshot_sha256=snapshot.snapshot_sha256,
        idea_revision=idea,
        source_project_id=args.project_id,
        source_run_id=args.run_id,
        source_relationship=TasteEpisodeSourceRelationship.SELF_PROJECT,
        source_group_id=source_group_id,
        dataset_partition=TasteEpisodePartition.DEVELOPMENT,
        assignment_timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE,
        decision_log_locator="interactive_development/decisions/DECISIONS.jsonl",
        state_snapshot_root_locator="interactive_development/states",
        frozen_at=datetime.now(UTC),
        source_absent_when_frozen=True,
    )
    plan_path = stage_root / "SAMPLING_PLAN.json"
    save_taste_trajectory_sampling_plan(plan, plan_path)

    agent_config_sha256 = _sha256_file(args.agent_backend_config)
    judge_config_sha256 = _sha256_file(args.judge_backend_config)
    agent = StructuredInteractiveResearchAgent(
        StructuredOpenAICompatibleBackend(
            load_structured_openai_compatible_config(args.agent_backend_config)
        ),
        policy_id=args.agent_policy_id,
        prompt_version=args.agent_prompt_version,
        seed=args.agent_seed,
        backend_configuration_sha256=agent_config_sha256,
    )
    judge = StructuredNewtonBenchJudge(
        StructuredOpenAICompatibleBackend(
            load_structured_openai_compatible_config(args.judge_backend_config)
        ),
        prompt_version=args.judge_prompt_version,
        seed=args.judge_seed,
        backend_configuration_sha256=judge_config_sha256,
    )
    code_runner = (
        BubblewrapPythonCodeRunner(
            python_executable=args.python_executable,
            bubblewrap_executable=args.bubblewrap_executable,
            timeout_seconds=args.code_timeout_seconds,
            cpu_seconds=args.code_cpu_seconds,
            memory_mib=args.code_memory_mib,
            max_output_bytes=args.code_max_output_bytes,
        )
        if task.code_assisted
        else None
    )
    toolbox = NewtonBenchToolbox(
        args.checkout,
        repository_commit=args.repository_commit,
        task=task,
        symbolic_judge=judge,
        code_runner=code_runner,
    )
    controller = TasteController(
        seed=args.taste_seed,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        preference_prompt_version=args.taste_prompt_version,
    )
    implementation_sha256 = content_sha256(
        {
            Path(module.__file__).name: _sha256_file(module.__file__)
            for module in (
                interactive_development_module,
                interactive_research_module,
                newtonbench_runtime_module,
                sandboxed_code_module,
            )
            if module.__file__ is not None
        }
    )
    sampling_rule = getattr(
        args,
        "episode_sampling_rule",
        "earliest-executed-nonterminal-after-observation",
    )
    target_action = getattr(args, "episode_target_action", None)
    target_turn = getattr(args, "episode_target_turn", None)
    credit_projection = getattr(
        args,
        "candidate_credit_projection",
        "action-local-scientific-v4",
    )
    protocol = InteractiveTasteDevelopmentProtocol.create(
        schema_version="1.2" if sampling_rule == "preassigned-action-stratum-v1" else "1.1",
        protocol_id=args.protocol_id,
        project_id=args.project_id,
        benchmark_id="newtonbench",
        task_id=task.task_id,
        source_group_id=source_group_id,
        task_sha256=toolbox.task_sha256,
        environment_sha256=toolbox.environment_sha256,
        toolbox_sha256=toolbox.fingerprint,
        target_domain=args.target_domain,
        target_venue=args.target_venue,
        primary_metric="symbolic_accuracy",
        metric_direction="higher",
        failure_primary_value=0.0,
        max_turns=limits.max_turns,
        max_experiments=limits.max_experiments,
        source_identity_registry_sha256=registry.registry_sha256,
        controller_backbone_sha256=controller.intervention_backbone_sha256,
        prompt_version=controller.preference_prompt_version,
        seed=args.taste_seed,
        resource_envelope_sha256=limits.fingerprint,
        research_agent_sha256=agent.fingerprint,
        tool_policy_sha256=content_sha256(
            {
                "toolbox_sha256": toolbox.fingerprint,
                "code_assisted": task.code_assisted,
                "code_runner_sha256": code_runner.fingerprint if code_runner else None,
            }
        ),
        repair_policy_sha256=content_sha256({"policy": "no-repair-inside-development-trajectory"}),
        executor_sha256=content_sha256(
            {
                "implementation_sha256": implementation_sha256,
                "toolbox_sha256": toolbox.fingerprint,
            }
        ),
        idea_scientific_contract_sha256=idea_scientific_contract_sha256(idea),
        idea_revision_binding_sha256=idea.binding_sha256,
        episode_sampling_rule=sampling_rule,
        maximum_episode_candidates=1,
        candidate_credit_projection=credit_projection,
        episode_target_action=target_action,
        episode_target_turn=target_turn,
    )
    protocol_path = stage_root / "PROTOCOL.json"
    save_interactive_taste_development_protocol(protocol, protocol_path)
    return protocol, plan_path, protocol_path


def _load_model(path: str | Path, model_type):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{model_type.__name__} input must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_CONFIG_BYTES:
        raise ValueError(f"{model_type.__name__} input exceeds its byte ceiling")
    return model_type.model_validate_json(source.read_bytes(), strict=True)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="scitaste-self-development")
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--source-identity-registry", required=True)
    parser.add_argument("--agent-backend-config", required=True)
    parser.add_argument("--judge-backend-config", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--target-domain", default="interactive-scientific-law-discovery")
    parser.add_argument("--target-venue", default="ICLR 2027")
    parser.add_argument("--agent-policy-id", default="newtonbench-research-agent-v1")
    parser.add_argument("--agent-prompt-version", default="newtonbench-agent-v1")
    parser.add_argument("--agent-seed", type=int, default=0)
    parser.add_argument("--judge-prompt-version", default="newtonbench-symbolic-equivalence-v1")
    parser.add_argument("--judge-seed", type=int, default=0)
    parser.add_argument("--taste-prompt-version", default="interactive-development-taste-v1")
    parser.add_argument("--taste-seed", type=int, default=0)
    parser.add_argument(
        "--episode-sampling-rule",
        choices=(
            "earliest-executed-nonterminal-after-observation",
            "preassigned-action-stratum-v1",
        ),
        default="earliest-executed-nonterminal-after-observation",
    )
    parser.add_argument(
        "--episode-target-action",
        choices=("EXPERIMENT", "REFINE", "STOP"),
    )
    parser.add_argument("--episode-target-turn", type=int)
    parser.add_argument(
        "--candidate-credit-projection",
        choices=("action-local-scientific-v4", "allocation-local-v5"),
        default="action-local-scientific-v4",
    )
    parser.add_argument("--python-executable", default="/usr/bin/python3.12")
    parser.add_argument("--bubblewrap-executable", default="/usr/bin/bwrap")
    parser.add_argument("--code-timeout-seconds", type=int, default=8)
    parser.add_argument("--code-cpu-seconds", type=int, default=6)
    parser.add_argument("--code-memory-mib", type=int, default=512)
    parser.add_argument("--code-max-output-bytes", type=int, default=128_000)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    return parser


def main() -> None:
    protocol, plan_path, protocol_path = prepare(build_parser().parse_args())
    print(
        content_sha256(
            {
                "protocol_sha256": protocol.protocol_sha256,
                "plan": plan_path.as_posix(),
                "protocol": protocol_path.as_posix(),
            }
        )
    )


if __name__ == "__main__":
    main()

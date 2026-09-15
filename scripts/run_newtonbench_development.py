#!/usr/bin/env python3
"""Run one frozen NewtonBench development trajectory and project Taste candidates."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from scitaste.evaluation.interactive_development import (
    DevelopmentTasteGuidanceProvider,
    finalize_interactive_development_episodes,
    load_interactive_taste_development_protocol,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    InteractiveResearchLoop,
    StructuredInteractiveResearchAgent,
    save_interactive_research_run_receipt,
)
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.evaluation.sandboxed_code import BubblewrapPythonCodeRunner
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.idea_revision import inspect_current_idea_revision
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.trajectory_reconstruction import load_taste_trajectory_sampling_plan

_MAX_CONFIG_BYTES = 4 * 1_048_576


def run(args: argparse.Namespace):
    runtime = ProjectRuntime(args.outputs_root)
    protocol = load_interactive_taste_development_protocol(args.protocol)
    plan = load_taste_trajectory_sampling_plan(args.sampling_plan)
    limits = _load_model(args.limits, InteractiveResearchLimits)
    task = _load_model(args.task, NewtonBenchTask)
    idea_report = inspect_current_idea_revision(runtime, protocol.project_id)
    idea = idea_report.current_binding
    if idea is None:
        raise ValueError("current project Idea is unavailable")
    if runtime.open(protocol.project_id).revision != plan.observed_project_revision:
        raise ValueError("project changed after the development trajectory was frozen")

    agent = StructuredInteractiveResearchAgent(
        StructuredOpenAICompatibleBackend(
            load_structured_openai_compatible_config(args.agent_backend_config)
        ),
        policy_id=args.agent_policy_id,
        prompt_version=args.agent_prompt_version,
        seed=args.agent_seed,
        backend_configuration_sha256=_sha256_file(args.agent_backend_config),
    )
    judge = StructuredNewtonBenchJudge(
        StructuredOpenAICompatibleBackend(
            load_structured_openai_compatible_config(args.judge_backend_config)
        ),
        prompt_version=args.judge_prompt_version,
        seed=args.judge_seed,
        backend_configuration_sha256=_sha256_file(args.judge_backend_config),
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
        seed=protocol.seed,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        preference_prompt_version=protocol.prompt_version,
    )
    run_root = runtime.projects_root / protocol.project_id / "runs" / plan.source_run_id
    provider = DevelopmentTasteGuidanceProvider(
        protocol,
        controller,
        sampling_plan=plan,
        runtime=runtime,
        current_idea_revision=idea,
        expected_project_revision=plan.observed_project_revision,
        lock_root=run_root / "interactive_development" / "taste_locks",
    )
    receipt = InteractiveResearchLoop(toolbox, agent, provider, limits).run(
        project_id=protocol.project_id,
        run_id=plan.source_run_id,
        condition_id=protocol.condition_id,
    )
    receipt_path = run_root / "interactive_development" / "RESULT" / "RECEIPT.json"
    save_interactive_research_run_receipt(receipt, receipt_path)
    lock_paths = tuple(
        run_root
        / "interactive_development"
        / "taste_locks"
        / f"turn-{turn.turn:03d}"
        / "LOCK.json"
        for turn in receipt.turns
    )
    batch = finalize_interactive_development_episodes(
        protocol,
        plan,
        runtime=runtime,
        current_idea_revision=idea,
        expected_project_revision=plan.observed_project_revision,
        lock_paths=lock_paths,
        receipt_path=receipt_path,
        output_root=run_root / "interactive_development" / "taste_episodes",
    )
    runtime.update_run(
        protocol.project_id,
        plan.source_run_id,
        expected_revision=plan.observed_project_revision,
        status="succeeded" if receipt.status == "completed" else "failed",
        evidence_scope=(
            "development-scientific-outcome-quarantined-no-formal-claim"
            if receipt.status == "completed"
            else "development-terminal-failure-quarantined-no-formal-claim"
        ),
        artifact=(
            f"runs/{plan.source_run_id}/interactive_development/"
            "taste_episodes/BATCH.json"
        ),
        interactive_status=receipt.status,
        receipt_sha256=receipt.receipt_sha256,
        batch_sha256=batch.batch_sha256,
        objective_primary_value=(
            receipt.objective_score.primary_value
            if receipt.objective_score is not None
            else None
        ),
        policy_update_authorized=False,
        formal_evidence=False,
    )
    return receipt, batch


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
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--sampling-plan", required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--agent-backend-config", required=True)
    parser.add_argument("--judge-backend-config", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--agent-policy-id", default="newtonbench-research-agent-v1")
    parser.add_argument("--agent-prompt-version", default="newtonbench-agent-v1")
    parser.add_argument("--agent-seed", type=int, default=0)
    parser.add_argument("--judge-prompt-version", default="newtonbench-symbolic-equivalence-v1")
    parser.add_argument("--judge-seed", type=int, default=0)
    parser.add_argument("--python-executable", default="/usr/bin/python3.12")
    parser.add_argument("--bubblewrap-executable", default="/usr/bin/bwrap")
    parser.add_argument("--code-timeout-seconds", type=int, default=8)
    parser.add_argument("--code-cpu-seconds", type=int, default=6)
    parser.add_argument("--code-memory-mib", type=int, default=512)
    parser.add_argument("--code-max-output-bytes", type=int, default=128_000)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    return parser


def main() -> None:
    receipt, batch = run(build_parser().parse_args())
    print(
        f"status={receipt.status} score="
        f"{receipt.objective_score.primary_value if receipt.objective_score else 'missing'} "
        f"episodes={len(batch.items)} batch_sha256={batch.batch_sha256}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Execute one protocol-bound SciTaste or Base NewtonBench trajectory."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    InteractiveResearchLoop,
    StructuredInteractiveResearchAgent,
    save_interactive_research_run_receipt,
)
from scitaste.evaluation.interactive_taste import (
    TasteControllerInteractiveGuidanceProvider,
    load_interactive_taste_execution_protocol,
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
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
    load_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.episode_learning import LifecycleTastePolicyModel
from scitaste.taste.intervention import TasteInterventionCondition

_MAX_CONFIG_BYTES = 4 * 1_048_576


def run(args: argparse.Namespace):
    protocol = load_interactive_taste_execution_protocol(args.protocol)
    limits = _load_model(args.limits, InteractiveResearchLimits)
    task = _load_model(args.task, NewtonBenchTask)
    family_policy, standalone_policy, idea = _load_taste_artifacts(args)

    agent_config = load_structured_openai_compatible_config(args.agent_backend_config)
    judge_config = load_structured_openai_compatible_config(args.judge_backend_config)
    agent_backend = StructuredOpenAICompatibleBackend(agent_config)
    judge_backend = StructuredOpenAICompatibleBackend(judge_config)
    agent = StructuredInteractiveResearchAgent(
        agent_backend,
        policy_id=args.agent_policy_id,
        prompt_version=args.agent_prompt_version,
        seed=args.agent_seed,
        backend_configuration_sha256=_sha256_file(args.agent_backend_config),
    )
    judge = StructuredNewtonBenchJudge(
        judge_backend,
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
    condition = TasteInterventionCondition(args.condition)
    weight = 1.0 if condition is TasteInterventionCondition.LEARNED_POLICY_ON else 0.0
    controller = TasteController(
        seed=protocol.seed,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        lifecycle_policy=standalone_policy,
        family_conditioned_policy=family_policy,
        lifecycle_decision_family=(
            ScientificTasteDecisionFamily(args.decision_family) if family_policy else None
        ),
        lifecycle_policy_weight=weight,
        preference_prompt_version=protocol.prompt_version,
    )
    provider = TasteControllerInteractiveGuidanceProvider(
        protocol,
        controller,
        current_idea_revision=idea,
    )
    receipt = InteractiveResearchLoop(toolbox, agent, provider, limits).run(
        project_id=protocol.project_id,
        run_id=args.run_id,
        condition_id=condition.value,
    )
    save_interactive_research_run_receipt(receipt, args.output)
    return receipt


def _load_model(path: str | Path, model_type):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{model_type.__name__} input must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_CONFIG_BYTES:
        raise ValueError(f"{model_type.__name__} input exceeds its byte ceiling")
    return model_type.model_validate_json(source.read_bytes(), strict=True)


def _load_taste_artifacts(
    args: argparse.Namespace,
) -> tuple[
    FamilyConditionedLifecycleTastePolicy | None,
    LifecycleTastePolicyModel | None,
    ProjectIdeaRevisionBinding,
]:
    if args.family_policy:
        family = load_family_conditioned_lifecycle_taste_policy(args.family_policy)
        idea = (
            _load_model(args.idea_binding, ProjectIdeaRevisionBinding)
            if args.idea_binding
            else family.idea_revision
        )
        if idea is None:
            raise ValueError("family policy has no Idea binding; pass --idea-binding")
        return family, None, idea
    policy = _load_model(args.lifecycle_policy, LifecycleTastePolicyModel)
    idea = (
        _load_model(args.idea_binding, ProjectIdeaRevisionBinding)
        if args.idea_binding
        else policy.config.idea_revision
    )
    if idea is None:
        raise ValueError("lifecycle policy has no Idea binding; pass --idea-binding")
    return None, policy, idea


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--task", required=True)
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--lifecycle-policy")
    policy.add_argument("--family-policy")
    parser.add_argument("--decision-family", default="adaptive-allocation")
    parser.add_argument("--idea-binding")
    parser.add_argument("--agent-backend-config", required=True)
    parser.add_argument("--judge-backend-config", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument(
        "--condition",
        required=True,
        choices=(
            TasteInterventionCondition.LEARNED_POLICY_ON.value,
            TasteInterventionCondition.LEARNED_POLICY_OFF.value,
        ),
    )
    parser.add_argument("--run-id", required=True)
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
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    receipt = run(build_parser().parse_args())
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

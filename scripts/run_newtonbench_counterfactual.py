#!/usr/bin/env python3
"""Run one shared-prefix NewtonBench action-counterfactual development study."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from scitaste.evaluation.counterfactual_taste import (
    CommonResearchRolloutGuidanceProvider,
    CounterfactualActionGuidanceProvider,
    CounterfactualActionSetAdequacy,
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
    save_counterfactual_action_intervention,
    save_counterfactual_action_set_adequacy,
    save_counterfactual_action_set_result,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    InteractiveResearchLoop,
    InteractiveResearchPrefix,
    InteractiveResearchRunReceipt,
    StructuredInteractiveResearchAgent,
    load_interactive_research_run_receipt,
    save_interactive_research_prefix,
    save_interactive_research_run_receipt,
)
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)

_MAX_CONFIG_BYTES = 4 * 1_048_576


def run(
    args: argparse.Namespace,
) -> CounterfactualActionSetResult | InteractiveResearchRunReceipt:
    limits = _load_model(args.limits, InteractiveResearchLimits)
    task = _load_model(args.task, NewtonBenchTask)
    if task.code_assisted or limits.max_code_calls:
        raise ValueError("counterfactual prefix v1 supports experiment-only NewtonBench tasks")
    actions = _parse_actions(args.actions)
    output_root = args.output_root.expanduser()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)

    agent_config = load_structured_openai_compatible_config(args.agent_backend_config)
    judge_config = load_structured_openai_compatible_config(args.judge_backend_config)
    agent_config_sha256 = _sha256_file(args.agent_backend_config)
    judge_config_sha256 = _sha256_file(args.judge_backend_config)

    def build_agent() -> StructuredInteractiveResearchAgent:
        return StructuredInteractiveResearchAgent(
            StructuredOpenAICompatibleBackend(agent_config),
            policy_id=args.agent_policy_id,
            prompt_version=args.agent_prompt_version,
            seed=args.agent_seed,
            backend_configuration_sha256=agent_config_sha256,
        )

    def build_toolbox() -> NewtonBenchToolbox:
        judge = StructuredNewtonBenchJudge(
            StructuredOpenAICompatibleBackend(judge_config),
            prompt_version=args.judge_prompt_version,
            seed=args.judge_seed,
            backend_configuration_sha256=judge_config_sha256,
        )
        return NewtonBenchToolbox(
            args.checkout,
            repository_commit=args.repository_commit,
            task=task,
            symbolic_judge=judge,
            code_runner=None,
        )

    common_condition = args.rollout_condition_id or f"{args.study_id}-common-rollout"
    common_policy_id = args.rollout_policy_id or f"{args.study_id}-rollout-v1"
    source_agent = build_agent()
    source_toolbox = build_toolbox()
    common_provider = CommonResearchRolloutGuidanceProvider(
        condition_id=common_condition,
        policy_id=common_policy_id,
    )
    source = (
        load_interactive_research_run_receipt(args.source_receipt)
        if args.source_receipt is not None
        else InteractiveResearchLoop(
            source_toolbox,
            source_agent,
            common_provider,
            limits,
        ).run(
            project_id=args.project_id,
            run_id=f"{args.study_id}-source",
            condition_id=common_condition,
        )
    )
    save_interactive_research_run_receipt(source, output_root / "SOURCE_RECEIPT.json")
    if source.status != "completed":
        raise ValueError(f"counterfactual source trajectory failed with {source.status}")
    if (
        source.project_id != args.project_id
        or source.task_id != source_toolbox.task_id
        or source.environment_sha256 != source_toolbox.environment_sha256
    ):
        raise ValueError("counterfactual source receipt targets another task environment")
    if args.source_only:
        return source

    prefix = InteractiveResearchPrefix.from_receipt(
        source,
        turn_count=args.prefix_turn_count,
        task_sha256=source_toolbox.task_sha256,
        toolbox_sha256=source_toolbox.fingerprint,
        resource_envelope_sha256=limits.fingerprint,
        research_agent_sha256=source_agent.fingerprint,
    )
    save_interactive_research_prefix(prefix, output_root / "PREFIX.json")

    receipts = []
    interventions = []
    for action in actions:
        agent = build_agent()
        toolbox = build_toolbox()
        rollout = CommonResearchRolloutGuidanceProvider(
            condition_id=common_condition,
            policy_id=common_policy_id,
        )
        provider = CounterfactualActionGuidanceProvider(
            prefix=prefix,
            forced_action=action,
            rollout_provider=rollout,
            rollout_condition_id=common_condition,
            rollout_policy_sha256=rollout.policy_sha256,
            study_id=args.study_id,
        )
        action_root = output_root / action.value.casefold()
        save_counterfactual_action_intervention(
            provider.intervention,
            action_root / "INTERVENTION.json",
        )
        receipt = InteractiveResearchLoop(toolbox, agent, provider, limits).run(
            project_id=args.project_id,
            run_id=f"{args.study_id}-{action.value.casefold()}",
            condition_id=f"{args.study_id}-forced-{action.value.casefold()}",
            prefix=prefix,
        )
        save_interactive_research_run_receipt(receipt, action_root / "RECEIPT.json")
        receipts.append(receipt)
        interventions.append(provider.intervention)

    result = CounterfactualActionSetResult.from_receipts(
        study_id=args.study_id,
        prefix=prefix,
        receipts=tuple(receipts),
        interventions=tuple(interventions),
        primary_metric=args.primary_metric,
        source_metric=args.source_metric,
        metric_transform=args.metric_transform,
        metric_direction=args.metric_direction,
        failure_value=args.failure_value,
        practical_equivalence_tolerance=args.practical_equivalence_tolerance,
    )
    save_counterfactual_action_set_result(result, output_root / "RESULT.json")
    adequacy = CounterfactualActionSetAdequacy.from_result(result)
    save_counterfactual_action_set_adequacy(adequacy, output_root / "ADEQUACY.json")
    return result


def _parse_actions(value: str) -> tuple[CounterfactualResearchAction, ...]:
    actions = tuple(
        CounterfactualResearchAction(item.strip().upper())
        for item in value.split(",")
        if item.strip()
    )
    if len(actions) < 2 or len(actions) != len(set(actions)):
        raise ValueError("counterfactual study requires at least two unique actions")
    return tuple(sorted(actions, key=lambda item: item.value))


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
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--agent-backend-config", required=True)
    parser.add_argument("--judge-backend-config", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--prefix-turn-count", type=int, default=2)
    parser.add_argument("--source-receipt", type=Path, default=None)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Generate and persist only the common source trajectory for coverage planning.",
    )
    parser.add_argument("--rollout-condition-id", default=None)
    parser.add_argument("--rollout-policy-id", default=None)
    parser.add_argument(
        "--actions",
        default=",".join(item.value for item in CounterfactualResearchAction),
    )
    parser.add_argument("--agent-policy-id", default="newtonbench-research-agent-v1")
    parser.add_argument("--agent-prompt-version", default="newtonbench-agent-v1")
    parser.add_argument("--agent-seed", type=int, default=0)
    parser.add_argument("--judge-prompt-version", default="newtonbench-symbolic-equivalence-v1")
    parser.add_argument("--judge-seed", type=int, default=0)
    parser.add_argument("--primary-metric", default="symbolic_accuracy")
    parser.add_argument("--source-metric", default=None)
    parser.add_argument(
        "--metric-transform",
        choices=("identity", "exp-negative"),
        default="identity",
    )
    parser.add_argument("--metric-direction", choices=("higher", "lower"), default="higher")
    parser.add_argument("--failure-value", type=float, default=0.0)
    parser.add_argument("--practical-equivalence-tolerance", type=float, default=0.0)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> None:
    result = run(build_parser().parse_args())
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

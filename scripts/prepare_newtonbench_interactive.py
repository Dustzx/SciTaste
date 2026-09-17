#!/usr/bin/env python3
"""Freeze a no-execution protocol for a paired SciTaste NewtonBench run."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import scitaste.evaluation.interactive_research as interactive_research_module
import scitaste.evaluation.interactive_taste as interactive_taste_module
import scitaste.evaluation.newtonbench_runtime as newtonbench_runtime_module
import scitaste.evaluation.sandboxed_code as sandboxed_code_module
from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    StructuredInteractiveResearchAgent,
)
from scitaste.evaluation.interactive_taste import (
    InteractiveTasteExecutionProtocol,
    save_interactive_taste_execution_protocol,
)
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.evaluation.sandboxed_code import BubblewrapPythonCodeRunner
from scitaste.evaluation.source_identity import load_canonical_source_identity_registry
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
    load_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.episode_learning import LifecycleTastePolicyModel
from scitaste.taste.intervention import lifecycle_policy_training_corpus_sha256

_MAX_CONFIG_BYTES = 4 * 1_048_576


def prepare(args: argparse.Namespace) -> InteractiveTasteExecutionProtocol:
    limits = _load_model(args.limits, InteractiveResearchLimits)
    task = _load_model(args.task, NewtonBenchTask)
    family_policy, standalone_policy, idea = _load_taste_artifacts(args)
    registry = load_canonical_source_identity_registry(args.source_identity_registry)

    agent_config_sha256 = _sha256_file(args.agent_backend_config)
    judge_config_sha256 = _sha256_file(args.judge_backend_config)
    agent_backend = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(args.agent_backend_config)
    )
    judge_backend = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(args.judge_backend_config)
    )
    agent = StructuredInteractiveResearchAgent(
        agent_backend,
        policy_id=args.agent_policy_id,
        prompt_version=args.agent_prompt_version,
        seed=args.agent_seed,
        backend_configuration_sha256=agent_config_sha256,
    )
    judge = StructuredNewtonBenchJudge(
        judge_backend,
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
        lifecycle_policy=standalone_policy,
        family_conditioned_policy=family_policy,
        lifecycle_decision_family=(
            ScientificTasteDecisionFamily(args.decision_family) if family_policy else None
        ),
        lifecycle_policy_weight=1.0,
        preference_prompt_version=args.taste_prompt_version,
    )

    policy = controller.lifecycle_policy
    if policy is None:
        raise ValueError("interactive preparation did not resolve a lifecycle policy")
    if not policy.h4_adaptive_policy_eligible:
        raise ValueError(
            "interactive H4 preparation requires state variation and different "
            "preferred actions across decision contexts; a global action prior is ineligible"
        )
    policy_groups = tuple(policy.source_group_ids)
    heldout_groups = (args.heldout_source_group_id,)
    # Held-out benchmark identities must be known canonical registry entries.
    # A learned policy may also contain immutable project-native episodes, whose
    # namespace is intentionally outside the paper/benchmark identity registry.
    # Keep those opaque IDs as frozen policy provenance while still rejecting a
    # registered legacy alias and enforcing exact held-out disjointness below.
    for group in policy_groups:
        if registry.resolve(group, require_known=False) != group:
            raise ValueError("interactive policy source group is a legacy alias")
    for group in heldout_groups:
        if registry.resolve(group) != group:
            raise ValueError("interactive held-out source group is not canonical")
    implementation_sha256 = content_sha256(
        {
            Path(module.__file__).name: _sha256_file(module.__file__)
            for module in (
                interactive_research_module,
                interactive_taste_module,
                newtonbench_runtime_module,
                sandboxed_code_module,
            )
            if module.__file__ is not None
        }
    )
    tool_policy_sha256 = content_sha256(
        {
            "toolbox_sha256": toolbox.fingerprint,
            "code_assisted": task.code_assisted,
            "code_runner_sha256": code_runner.fingerprint if code_runner else None,
        }
    )
    protocol = InteractiveTasteExecutionProtocol.create(
        protocol_id=args.protocol_id,
        project_id=idea.project_id,
        benchmark_id="newtonbench",
        task_id=task.task_id,
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
        canonical_source_group_ids=(*policy_groups, *heldout_groups),
        policy_source_group_ids=policy_groups,
        heldout_source_group_ids=heldout_groups,
        controller_backbone_sha256=controller.intervention_backbone_sha256,
        lifecycle_policy_sha256=policy.policy_sha256,
        policy_training_corpus_sha256=lifecycle_policy_training_corpus_sha256(policy),
        family_conditioned_policy_sha256=(
            family_policy.policy_sha256 if family_policy is not None else None
        ),
        decision_family=(
            ScientificTasteDecisionFamily(args.decision_family) if family_policy else None
        ),
        decision_provider="scitaste-native",
        decision_model="deterministic-utility-controller",
        prompt_version=controller.preference_prompt_version,
        seed=args.taste_seed,
        resource_envelope_sha256=limits.fingerprint,
        research_agent_sha256=agent.fingerprint,
        tool_policy_sha256=tool_policy_sha256,
        repair_policy_sha256=content_sha256({"policy": "no-repair-inside-fixed-trajectory"}),
        executor_sha256=content_sha256(
            {
                "implementation_sha256": implementation_sha256,
                "toolbox_sha256": toolbox.fingerprint,
            }
        ),
        idea_scientific_contract_sha256=idea_scientific_contract_sha256(idea),
        idea_revision_binding_sha256=idea.binding_sha256,
    )
    save_interactive_taste_execution_protocol(protocol, args.output)
    return protocol


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
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--task", required=True)
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--lifecycle-policy")
    policy.add_argument("--family-policy")
    parser.add_argument("--decision-family", default="adaptive-allocation")
    parser.add_argument("--idea-binding")
    parser.add_argument("--source-identity-registry", required=True)
    parser.add_argument("--heldout-source-group-id", required=True)
    parser.add_argument("--agent-backend-config", required=True)
    parser.add_argument("--judge-backend-config", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--target-domain", default="interactive-scientific-law-discovery")
    parser.add_argument("--target-venue", default="ICLR 2027")
    parser.add_argument("--agent-policy-id", default="newtonbench-research-agent-v1")
    parser.add_argument("--agent-prompt-version", default="newtonbench-agent-v1")
    parser.add_argument("--agent-seed", type=int, default=0)
    parser.add_argument("--judge-prompt-version", default="newtonbench-symbolic-equivalence-v1")
    parser.add_argument("--judge-seed", type=int, default=0)
    parser.add_argument("--taste-prompt-version", default="interactive-taste-v1")
    parser.add_argument("--taste-seed", type=int, default=0)
    parser.add_argument("--python-executable", default="/usr/bin/python3.12")
    parser.add_argument("--bubblewrap-executable", default="/usr/bin/bwrap")
    parser.add_argument("--code-timeout-seconds", type=int, default=8)
    parser.add_argument("--code-cpu-seconds", type=int, default=6)
    parser.add_argument("--code-memory-mib", type=int, default=512)
    parser.add_argument("--code-max-output-bytes", type=int, default=128_000)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    protocol = prepare(build_parser().parse_args())
    print(protocol.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Real pinned ResearchAgent with restricted tools and one remote development run."""

import argparse
import importlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, ProviderBudgetExhausted
from scitaste.backends.mlagentbench_session import MLAgentBenchSessionBridge
from scitaste.executor.iterative_research_tools import IterativeResearchToolEnvironment
from scitaste.executor.mlagentbench_tools import MLAgentBenchToolEnvironment
from scitaste.executor.remote_unlearning import RemoteUnlearningExperiment
from scitaste.executor.research_task import IterativeResearchToolTask, ResearchToolTask
from scitaste.executor.serialized_experiment import SerializedExperiment
from scripts import run_mlrc_native_development_loop as shared

PIN = "0d26417034811d2d4587646c4520cc305ea09dd6"


def execute_candidate(
    workspace,
    *,
    output,
    project,
    base,
    credentials,
    system_id="upstream-mlagentbench-researchagent-restricted-tools-development",
    system_revision=PIN,
    trajectory_path=None,
    gpu_index=3,
    wall_seconds=1200,
):
    """Agent chooses when to call; Native provides isolation and measured evidence only."""
    provenance = output / "CANDIDATE_PROVENANCE.json"
    shared.write_new(
        provenance,
        {
            "system_id": system_id,
            "system_revision": system_revision,
            "trajectory_sha256": shared._sha256(
                trajectory_path or output / "logs" / "agent_log" / "main_log"
            ),
            "budget_contract_sha256": shared._sha256(output / "CONTRACT.json"),
            "formal_evidence_eligible": False,
        },
    )
    bundle = output / "bundle"
    shared.package_candidate(
        base_bundle=base, method_source=workspace, provenance=provenance, output_root=bundle
    )
    remote_base = "/data/zfx/scitaste/mlrc-meta-dev-20260925"
    remote_root = remote_base + "/external-agents/" + output.name
    binding = shared.RemoteMLRCBinding(
        candidate_id=output.name,
        host="4090-2",
        python=remote_base + "/venv/bin/python",
        bundle=remote_root + "/bundle",
        bundle_manifest_sha256=shared._sha256(bundle / "MANIFEST.json"),
        data_root=remote_base + "/mlrc-meta-learning-development-v1/data",
        output_root=remote_root + "/experiment",
        gpu_index=gpu_index,
        wall_seconds=wall_seconds,
    )
    shared.write_new(output / "BINDING.json", asdict(binding))
    ssh_env = {
        "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(credentials.resolve(strict=True)),
        "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
        "SSH_ASKPASS": str(Path("scripts/ssh_askpass_resource_registry.py").resolve()),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
    }
    env = {**os.environ, **ssh_env}
    subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "ClearAllForwardings=yes",
            binding.host,
            "mkdir -p " + shlex.quote(remote_root),
        ],
        env=env,
        start_new_session=True,
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "rsync",
            "-rt",
            "-e",
            "ssh -T -o ClearAllForwardings=yes",
            str(bundle),
            f"{binding.host}:{remote_root}/",
        ],
        env=env,
        start_new_session=True,
        check=True,
        timeout=120,
    )
    handler = shared.RemoteMLRCActionHandler(
        project_id=project.name,
        binding=binding,
        workspace=output / "remote",
        artifact_root=project,
        ssh_environment=ssh_env,
        allow_launch=True,
    )
    executor = shared.SciTasteNativeExecutor(
        handlers={shared.MetaAction.EXPERIMENT: handler},
        workspace=output / "native",
        artifact_root=project,
        recover_completed_experiment=True,
    )
    state = shared.ResearchState(
        project_id=project.name,
        research_direction="Cross-domain few-shot classification",
        target_domain="MLRC development",
        target_venue="CVPR 2027",
        current_stage=shared.ResearchStage.EVIDENCE,
        resource_budget=shared.ResourceBudget(
            max_experiments=1, gpu_hours=1 / 3, max_wall_time_hours=1, max_api_cost_usd=2
        ),
    )
    action = shared.ResearchAction(
        action_id="upstream-agent-selected-experiment",
        type=shared.MetaAction.EXPERIMENT,
        description="Execute the candidate requested by the upstream ResearchAgent tool call",
        parameters={"candidate_id": output.name},
    )
    shared.write_new(output / "EXECUTION_STATE.json", state.model_dump(mode="json"))
    shared.write_new(output / "EXECUTION_ACTION.json", action.model_dump(mode="json"))
    result = executor.execute(state, action)
    shared.write_new(output / "EXECUTION_RESULT.json", result.model_dump(mode="json"))
    return result.model_dump(mode="json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--allow-api", action="store_true")
    transport.add_argument("--session", action="store_true")
    parser.add_argument("--session-wait-seconds", type=int, default=1800)
    parser.add_argument("--gpu-index", type=int, default=3)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--experiment-lock", type=Path)
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--continue-from", type=Path)
    parser.add_argument("--task", choices=("meta", "unlearning"), default="meta")
    parser.add_argument("--iterative", action="store_true")
    parser.add_argument("--delivery-baseline-run", type=Path)
    parser.add_argument("--delivery-baseline-source", type=Path)
    parser.add_argument("--task-context", type=Path)
    parser.add_argument("--enable-implementation-review", action="store_true")
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    if not (args.allow_api or args.session) or not args.allow_execution:
        raise ValueError("explicit API or session transport and remote execution are required")
    if not 0 <= args.gpu_index < 64 or not 1 <= args.session_wait_seconds <= 3600:
        raise ValueError("invalid GPU index or session wait limit")
    if args.session and (args.continue_from or args.enable_implementation_review):
        raise ValueError("session mode does not support continuation or implementation review")
    if args.iterative and (args.task != "unlearning" or args.continue_from):
        raise ValueError("iterative mode requires a new unlearning run, not legacy continuation")
    api_limit, max_calls, max_steps = (4.0, 40, 20) if args.iterative else (2.0, 20, 12)
    project = Path("outputs/projects/scitaste-self-development").resolve(strict=True)
    evaluations = project / "evaluations"
    checkout = evaluations / "acquisitions/mlrc-bench-source-v1/checkout"
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != PIN:
        raise ValueError("upstream checkout revision differs")
    if subprocess.check_output(
        ["git", "-C", str(checkout), "diff", "HEAD", "--", "MLAgentBench"], text=True
    ):
        raise ValueError("upstream agent source was modified")
    output = args.output.resolve()
    output.relative_to(evaluations)
    output.mkdir()  # New runs only; no accidental replay of an agent's live actions.
    base = evaluations / "scitastebench-mlrc-meta-visual-fork-remote-bundle-v4"
    if args.task == "unlearning":
        base = checkout / "MLAgentBench/benchmarks_base/machine_unlearning/env"
    workspace = output / "candidate"
    backend_path = args.backend
    bridge = None
    if args.session:
        bridge = MLAgentBenchSessionBridge(
            log_root=output / "logs",
            exchange=output / "session-exchange",
            wait_seconds=args.session_wait_seconds,
            max_calls=max_calls,
        )
        config = bridge.config
    else:
        config = shared.load_structured_openai_compatible_config(backend_path)
        shared._bind_credential(args.credentials, config.api_key_env)
    if args.iterative:
        task_contract = IterativeResearchToolTask.model_validate_json(
            (
                args.task_file or Path("configs/experiments/mlrc_unlearning_iterative_v1.json")
            ).read_text()
        )
    else:
        task_contract = ResearchToolTask.model_validate_json(
            (
                args.task_file
                or Path(f"configs/experiments/mlrc_{args.task}_shared_tool_task_v1.json")
            ).read_text()
        )
    context_binding = None
    if args.task_context:
        from scitaste.executor.task_context import bind_task_context

        task_contract, context_binding = bind_task_context(
            task_contract, args.task_context, evidence_root=Path.cwd()
        )
    continuation = None
    parent = None
    if args.continue_from:
        parent = args.continue_from.resolve(strict=True)
        parent.relative_to(evaluations)
        prior_result = json.loads((parent / "RESULT.json").read_text())
        prior_contract = json.loads((parent / "CONTRACT.json").read_text())
        if (
            prior_contract.get("optional_implementation_review", False)
            != args.enable_implementation_review
        ):
            raise ValueError("Continuation cannot change the available review tool")
        prior_task_id = prior_contract.get("task", {}).get(
            "task_id", "mlrc-meta-learning-development"
        )
        if prior_task_id != task_contract.task_id:
            raise ValueError("continuation cannot switch research tasks")
        if prior_result["status"] != "upstream-agent-interrupted":
            raise ValueError("continuation requires a terminal interrupted agent")
        if any(
            (parent / path).exists()
            for path in (
                "BINDING.json",
                "tools/EXPERIMENT_RESERVED.json",
                "EXECUTION_RESULT.json",
            )
        ):
            raise ValueError("remote experiment needs observation, not a fresh continuation")
        if prior_contract.get("continuation"):
            raise ValueError("nested continuation requires explicit cumulative-budget support")
        if (
            prior_contract["backend_sha256"] != shared._sha256(backend_path)
            or prior_contract["upstream_revision"] != PIN
        ):
            raise ValueError("continuation changes agent or backend")
        records = sorted((parent / "logs/provider_calls").glob("*.json"))
        if not records or any(not p.with_suffix(".completion").exists() for p in records):
            raise ValueError("unresolved provider request cannot be retried implicitly")
        imported_cost = sum(
            json.loads(p.with_suffix(".completion").read_text())["observed_usage_ceiling_usd"]
            for p in records
        )
        steps = [
            json.loads(line)
            for line in (parent / "tools/TOOL_TRACE.jsonl").read_text().splitlines()
        ]
        index = len(steps) - 1
        checkpoint = parent / "logs/agent_log" / f"agent_{index}_{index}.json"
        saved = json.loads(checkpoint.read_text())
        if len(saved["history_steps"]) != len(steps):
            raise ValueError("tool trace and saved agent state disagree")
        if imported_cost >= 2.0:
            raise ValueError("no API budget remains")
        continuation = {
            "parent": str(parent.relative_to(project)),
            "checkpoint": str(checkpoint.relative_to(project)),
            "checkpoint_sha256": shared._sha256(checkpoint),
            "tool_trace_sha256": shared._sha256(parent / "tools/TOOL_TRACE.jsonl"),
            "imported_api_cost_ceiling_usd": imported_cost,
            "imported_calls": len(records),
            "imported_steps": len(steps),
            "reason": "release resolved API reservations; preserve upstream state",
        }
    if parent:
        shutil.copytree(parent / "candidate", workspace)
    elif args.task == "unlearning":
        shutil.copytree(base / "methods", workspace / "methods")
    else:
        shutil.copytree(base / "branches/euclidean-prototypes", workspace)
    baseline_identity = shared._sha256(
        base / "methods/MyMethod.py" if args.task == "unlearning" else base / "MANIFEST.json"
    )
    shared.write_new(
        output / "CONTRACT.json",
        {
            "role": "upstream-agent-restricted-tools-development",
            "upstream_revision": PIN,
            "upstream_agent_sha256": shared._sha256(
                checkout / "MLAgentBench/agents/agent_research.py"
            ),
            "backend_sha256": None if args.session else shared._sha256(backend_path),
            "requested_provider": config.provider,
            "requested_model": config.model,
            "provider_fallback_enabled": False,
            "baseline_identity_sha256": baseline_identity,
            "max_experiments": task_contract.max_experiments,
            "wall_seconds": task_contract.wall_seconds,
            "max_agent_steps": max_steps,
            "max_api_liability_usd": 0 if args.session else api_limit,
            "max_api_calls": 0 if args.session else max_calls,
            "max_session_requests": max_calls if args.session else 0,
            "session_cost_usd": None,
            "actual_tokens": None,
            "gpu_index": args.gpu_index,
            "experiment_lock": str(args.experiment_lock.resolve())
            if args.experiment_lock
            else None,
            "formal_evidence_eligible": False,
            "tool_adaptation": "listed-source read/write; fixed isolated experiment; no shell",
            "matched_native_comparison": False,
            "task": task_contract.model_dump(mode="json"),
            "scientific_task_context": context_binding,
            "optional_implementation_review": args.enable_implementation_review,
            "continuation": continuation,
        },
    )
    sys.path.insert(0, str(checkout))
    agent_module = importlib.import_module("MLAgentBench.agents.agent_research")
    if bridge is None:
        bridge = MLAgentBenchProviderBridge(
            config=config,
            log_root=output / "logs",
            max_cost_usd=api_limit
            - (continuation["imported_api_cost_ceiling_usd"] if continuation else 0),
            max_calls=max_calls - (continuation["imported_calls"] if continuation else 0),
            transport=shared.RecordedTransport(output / "provider.jsonl"),
        )
    patched = bridge.install()
    shared.write_new(
        output / ("TRANSPORT_BINDING.json" if args.session else "PROVIDER_BINDING.json"),
        {"patched_references": patched},
    )
    if args.task == "unlearning":
        experiment = RemoteUnlearningExperiment(
            run_id=output.name,
            output=output,
            code_root=Path.cwd(),
            ssh_environment={
                "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(args.credentials.resolve(strict=True)),
                "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
                "SSH_ASKPASS": str(Path("scripts/ssh_askpass_resource_registry.py").resolve()),
                "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": ":0",
            },
            wall_seconds=task_contract.wall_seconds,
            gpu_index=args.gpu_index,
        )
    else:

        def experiment(path):
            return execute_candidate(
                path,
                output=output,
                project=project,
                base=base,
                credentials=args.credentials,
                gpu_index=args.gpu_index,
            )

    if args.iterative:
        ssh_environment = {
            key: value
            for key, value in experiment.environment.items()
            if key.startswith("SCITASTE_ASKPASS_")
            or key in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "DISPLAY"}
        }

        def factory(number, ceiling):
            attempt = RemoteUnlearningExperiment(
                run_id=f"{output.name}-attempt-{number:03d}",
                output=output / "executions" / f"attempt-{number:03d}",
                code_root=Path.cwd(),
                ssh_environment=ssh_environment,
                wall_seconds=ceiling,
                gpu_index=args.gpu_index,
            )
            return (
                SerializedExperiment(attempt, args.experiment_lock)
                if args.experiment_lock
                else attempt
            )

        environment = IterativeResearchToolEnvironment(
            workspace=workspace,
            log_root=output / "tools",
            task=task_contract,
            experiment_factory=factory,
        )
    else:
        environment = MLAgentBenchToolEnvironment(
            workspace=workspace,
            log_root=output / "tools",
            research_problem=task_contract.research_problem,
            task=task_contract,
            experiment=(
                SerializedExperiment(experiment, args.experiment_lock)
                if args.experiment_lock
                else experiment
            ),
        )
    if args.enable_implementation_review:
        from scitaste.executor.implementation_review_tool import install_implementation_review
        from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend

        install_implementation_review(
            environment,
            backend=SharedLedgerStructuredBackend(bridge),
            project_id=project.name,
            budget_usd=api_limit,
            spent=lambda: shared.api_ceiling(output),
        )
    shared.write_new(
        output / "TOOL_INTERFACE.json",
        {
            "descriptor": environment.interface_descriptor,
            "sha256": environment.interface_fingerprint,
        },
    )
    agent_args = argparse.Namespace(
        log_dir=str(output / "logs"),
        valid_format_entires=None,
        actions_remove_from_prompt=[],
        actions_add_to_prompt=["Read File", "Write File"],
        edit_script_llm_name=config.model,
        edit_script_llm_max_tokens=4096,
        resume=None,
        max_steps_in_context=max_steps,
        max_observation_steps_in_context=max_steps,
        retrieval=False,
        agent_max_steps=max_steps,
        max_retries=1,
        llm_name=config.model,
    )
    agent = agent_module.ResearchAgent(agent_args, environment)
    if continuation:
        from MLAgentBench.schema import Action, Step

        agent.restore(str(project / continuation["checkpoint"]))
        for row in steps:
            environment.trace.steps.append(
                Step(Action(**row["action"]), row["observation"], row["timestamp"])
            )
        shutil.copyfile(parent / "tools/TOOL_TRACE.jsonl", output / "tools/TOOL_TRACE.jsonl")
    runtime = shared.ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    runtime.begin_run(
        project.name,
        shared.ProjectRun(
            run_id=output.name,
            provider=config.provider,
            model=config.model,
            condition="upstream-mlagentbench-restricted-tools-development",
            seed=98,
            evidence_scope="consumed development task; adapted tools; no formal comparison",
            formal_evidence_eligible=False,
            status="agent-running",
            artifact=str((output / "CONTRACT.json").relative_to(project)),
        ),
        expected_revision=snapshot.manifest.revision,
    )
    try:
        result = agent.run(environment)
        status = "upstream-agent-returned"
    except ProviderBudgetExhausted as exc:
        result = {"stop_reason": "provider-request-admission", "budget": exc.details}
        status = "upstream-agent-budget-exhausted"
    except Exception as exc:
        # Persist a terminal agent observation, not a claim about a remote job's status.
        result = type(exc).__name__ + "; inspect provider/tool records before any continuation"
        status = "upstream-agent-interrupted"
    shared.write_new(
        output / "RESULT.json",
        {
            "status": status,
            "reason": result,
            "tool_steps": len(environment.trace.steps),
            "formal_evidence_eligible": False,
            "experiment_record_present": (output / "EXECUTION_RESULT.json").exists()
            or any((output / "tools/experiments").glob("attempt-*/RESULT.json")),
            "api_cost_ceiling_usd": 0 if args.session else shared.api_ceiling(output),
            "accounting": bridge.accounting() if args.session else None,
        },
    )
    if args.session:
        shared.write_new(
            output / "session-exchange" / "SESSION_CLOSED.json",
            {"status": status, "result": "../RESULT.json", "provider_api_calls": 0},
        )
    runtime.update_run(
        project.name,
        output.name,
        status=status,
        artifact=str((output / "RESULT.json").relative_to(project)),
        expected_revision=runtime.open(project.name).manifest.revision,
    )
    if args.iterative:
        from scripts.summarize_iterative_research import summarize
    else:
        from scripts.summarize_mlagentbench_development import summarize

    summarize(output)
    if args.iterative:
        from scripts.finalize_research_delivery import finalize

        finalize(
            output,
            project,
            baseline_run=args.delivery_baseline_run,
            baseline_source=args.delivery_baseline_source,
        )
    print(result)


if __name__ == "__main__":
    main()

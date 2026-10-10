"""Actual upstream ResearchAgent on NewtonBench, session-authored development only."""

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.backends.mlagentbench_session import MLAgentBenchSessionBridge
from scitaste.evaluation.newton_execution_setup import execution_setup
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.executor.newtonbench_agent_tools import NewtonBenchAgentToolEnvironment
from scitaste.model_nodes.session_exchange import SessionStructuredBackend, retain_json
from scitaste.project import ProjectRun, ProjectRuntime

AGENT_PIN = "0d26417034811d2d4587646c4520cc305ea09dd6"
BENCHMARK_PIN = "912a4ba5f4356ddd06acc16e44460ca30be4abc2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--allow-development-execution", action="store_true")
    parser.add_argument("--session-wait-seconds", type=int, default=600, choices=range(1, 3601))
    parser.add_argument("--agent-backend-config", type=Path)
    parser.add_argument("--judge-backend-config", type=Path)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--allow-code-execution", action="store_true")
    parser.add_argument("--common-terminal-delivery", action="store_true")
    args = parser.parse_args()
    if not args.allow_development_execution:
        raise ValueError("Explicit development execution is required")
    live = args.agent_backend_config is not None
    if live != (args.judge_backend_config is not None) or live != args.allow_api_execution:
        raise ValueError("API execution requires both configs and explicit opt-in")
    if args.common_terminal_delivery and not live:
        raise ValueError("Common terminal delivery requires a budgeted provider")
    if not args.task.name.startswith("development_task_"):
        raise ValueError("This runner does not consume formal or sealed task assignments")
    project = args.project.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(project / "evaluations")
    runtime = ProjectRuntime(project.parent.parent)
    runtime.open(project.name)
    task_bytes = args.task.read_bytes()
    task = NewtonBenchTask.model_validate_json(task_bytes)
    limits, code_runner = execution_setup(task, live=live, allow_code=args.allow_code_execution)
    acquisition = project / "evaluations/acquisitions"
    upstream = acquisition / "mlrc-bench-source-v1/checkout"
    benchmark = acquisition / "newtonbench-source-v1/checkout"
    pin = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    if pin != AGENT_PIN or subprocess.check_output(
        ["git", "-C", str(upstream), "diff", "HEAD", "--", "MLAgentBench"], text=True
    ):
        raise ValueError("Upstream ResearchAgent differs from its pinned source")
    output.mkdir()  # Never overwrite/replay an existing trajectory.
    if live:
        from scitaste.backends.research_provider import research_provider

        bridge, _ = research_provider(args.agent_backend_config, output / "logs")
        _, judge_backend = research_provider(
            args.judge_backend_config, output / "judge-provider", max_calls=4, max_cost_usd=2
        )
    else:
        bridge = MLAgentBenchSessionBridge(
            log_root=output / "logs",
            exchange=output / "session-exchange",
            max_calls=32,
            wait_seconds=args.session_wait_seconds,
        )
        judge_backend = SessionStructuredBackend(
            output / "judge-exchange", wait_seconds=args.session_wait_seconds, max_requests=4
        )
    judge = StructuredNewtonBenchJudge(
        judge_backend,
        backend_configuration_sha256=hashlib.sha256(
            args.judge_backend_config.read_bytes() if live else b"independent-session-judge-v1"
        ).hexdigest(),
    )
    toolbox = NewtonBenchToolbox(
        benchmark,
        repository_commit=BENCHMARK_PIN,
        task=task,
        symbolic_judge=judge,
        code_runner=code_runner,
    )
    environment = NewtonBenchAgentToolEnvironment(
        toolbox=toolbox,
        limits=limits,
        log_root=output / "tools",
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "system": "upstream-MLAgentBench-ResearchAgent",
            "agent_commit": AGENT_PIN,
            "benchmark_commit": BENCHMARK_PIN,
            "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
            "task_id": task.task_id,
            "tool_interface_sha256": environment.interface_fingerprint,
            "limits": limits.model_dump(mode="json"),
            "model_source": bridge.config.provider,
            "model": bridge.config.model,
            "stateless_requests": live,
            "backend_configuration_sha256": (
                hashlib.sha256(args.agent_backend_config.read_bytes()).hexdigest() if live else None
            ),
            "max_session_requests": 32,
            "adaptation": (
                "NewtonBench experiment/final-submission tools; unchanged upstream policy"
            ),
            "formal_evidence_eligible": False,
            "common_terminal_delivery": args.common_terminal_delivery,
            "scope": "development-external-system-arm",
            "token_budget_semantics": (
                "Provider usage retained; conservative liability, not invoice"
                if live
                else "Session tokenizer usage unknown; bounded requests/bytes instead"
            ),
            "judge_semantics": ("Separate requests after frozen submission; not human review"),
            "gpu_execution": False,
            "code_policy": code_runner.policy.model_dump(mode="json") if code_runner else None,
        },
    )
    sys.path.insert(0, str(upstream))
    agent_module = importlib.import_module("MLAgentBench.agents.agent_research")
    retain_json(output / "TRANSPORT_BINDING.json", {"patched_references": bridge.install()})
    agent_args = argparse.Namespace(
        log_dir=str(output / "logs"),
        valid_format_entires=None,
        actions_remove_from_prompt=[],
        actions_add_to_prompt=[],
        edit_script_llm_name=bridge.config.model,
        edit_script_llm_max_tokens=4096,
        resume=None,
        max_steps_in_context=8,
        max_observation_steps_in_context=8,
        retrieval=False,
        agent_max_steps=limits.max_turns,
        max_retries=1,
        llm_name=bridge.config.model,
    )
    agent = agent_module.ResearchAgent(agent_args, environment)
    runtime.begin_run(
        project.name,
        ProjectRun(
            run_id=output.name,
            provider=bridge.config.provider,
            model=bridge.config.model,
            condition="upstream-mlagentbench-newton-shared-tools",
            seed=task.environment_seed,
            status="agent-running",
            artifact=(output / "CONTRACT.json").relative_to(project).as_posix(),
            evidence_scope=(
                "adapted external system; consumed development family; not formal comparison"
            ),
            formal_evidence_eligible=False,
        ),
        expected_revision=runtime.open(project.name).revision,
    )
    result = {"formal_evidence_eligible": False}
    try:
        reason = agent.run(environment)
        result.update(
            status="agent-returned", reason=str(reason), submission=environment.submission
        )
    except Exception as exc:
        result.update(status="interrupted", error_type=type(exc).__name__, error=str(exc)[:500])
    retain_json(output / "CONTROLLER_TERMINAL.json", result)
    try:
        if args.common_terminal_delivery:
            from scitaste.evaluation.newton_terminal_delivery import deliver_terminal_hypothesis

            deliver_terminal_hypothesis(bridge=bridge, environment=environment, output=output)
            result["submission"] = environment.submission
        retain_json(output / "FROZEN_SUBMISSION.json", result)
        if environment.submission is not None:
            score = environment.score_submission()
            result.update(status="scored-development-run", objective=score.model_dump(mode="json"))
    except Exception as exc:
        result.update(
            status="interrupted",
            delivery_error_type=type(exc).__name__,
            delivery_error=str(exc)[:500],
        )
    result.update(
        accounting=bridge.accounting(),
        tool_steps=len(environment.trace.steps),
        queries_used=environment.experiments_used,
        code_calls_used=environment.code_calls_used,
        judge_accounting=(judge_backend.bridge.accounting() if live else None),
        judge_usage_semantics=(
            "Provider usage/liability retained"
            if live
            else "Session usage fields are conservative UTF-8 byte admission bounds, "
            "not measured tokens; cost_usd is incremental API liability, not session cost"
        ),
    )
    retain_json(output / "RESULT.json", result)
    runtime.update_run(
        project.name,
        output.name,
        status=result["status"],
        artifact=(output / "RESULT.json").relative_to(project).as_posix(),
        expected_revision=runtime.open(project.name).revision,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

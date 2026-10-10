"""Real Native controller/executor on shared NewtonBench development tools."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.backends.research_provider import terminal_proposal
from scitaste.backends.session import SessionNativeBridge, SessionPreferenceBackend
from scitaste.evaluation.newton_execution_setup import execution_setup
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.executor.newtonbench_agent_tools import NewtonBenchAgentToolEnvironment
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.session_exchange import SessionStructuredBackend, retain_json
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.research_tool_loop import run_research_tool_loop
from scitaste.state.research_state import ResearchStage, ResearchState, ResourceBudget
from scitaste.taste.controller import TasteController
from scitaste.taste.reviewed_library import reviewed_development_cases

BENCHMARK_PIN = "912a4ba5f4356ddd06acc16e44460ca30be4abc2"


def prepare_taste(args, project):
    """Resolve qualified cases before reserving an experiment; no raw JSONL bypass."""
    supplied = (args.taste_accepted_set, args.taste_quality_result, args.taste_profile)
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError("Taste requires accepted set, source-quality result and profile")
    profile = load_model_node_profile(args.taste_profile)
    if args.agent_backend_config is None and (profile.provider, profile.model) != (
        "assistant-session",
        "session-authored",
    ):
        raise ValueError("Session Taste requires a session profile")
    if "taste-deliberation" not in profile.allowed_node_names:
        raise ValueError("Profile does not permit taste-deliberation")
    cases = reviewed_development_cases(
        evidence_root=args.evidence_root,
        outputs_root=project.parent.parent,
        accepted_set=args.taste_accepted_set,
        quality_result=args.taste_quality_result,
    )
    extra_bindings = []
    for accepted, quality in args.taste_extra_source or []:
        cases.extend(
            reviewed_development_cases(
                evidence_root=args.evidence_root,
                outputs_root=project.parent.parent,
                accepted_set=accepted,
                quality_result=quality,
            )
        )
        extra_bindings.append(
            {
                "accepted_set_sha256": hashlib.sha256(accepted.read_bytes()).hexdigest(),
                "quality_result_sha256": hashlib.sha256(quality.read_bytes()).hexdigest(),
            }
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Reviewed library contains duplicate source cases")
    raw = "".join(case.model_dump_json() + "\n" for case in cases).encode()
    if args.resume_unqueried_provider:
        frozen = (args.output / "TASTE_LIBRARY.jsonl").read_bytes()

        def scientific_contents(data):
            records = [json.loads(line) for line in data.splitlines() if line.strip()]
            for record in records:
                for provenance in record.get("provenance", []):
                    provenance.pop("accessed_at", None)
            return records

        if scientific_contents(raw) != scientific_contents(frozen):
            raise ValueError("Frozen experience differs from reverified source/review chain")
        raw = frozen  # Preserve historical access timestamps and the original byte binding.
    return (
        profile,
        raw,
        {
            "library_sha256": hashlib.sha256(raw).hexdigest(),
            "profile_sha256": profile.fingerprint,
            "accepted_set_sha256": hashlib.sha256(args.taste_accepted_set.read_bytes()).hexdigest(),
            "quality_result_sha256": hashlib.sha256(
                args.taste_quality_result.read_bytes()
            ).hexdigest(),
            "case_count": len(cases),
            "case_ids": [case.case_id for case in cases],
            **({"extra_sources": extra_bindings} if extra_bindings else {}),
            "formal_evidence_eligible": False,
            "task_applicability": "assessed per action by grounded deliberation; not guaranteed",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--allow-development-execution", action="store_true")
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    parser.add_argument("--taste-accepted-set", type=Path)
    parser.add_argument("--taste-quality-result", type=Path)
    parser.add_argument("--taste-profile", type=Path)
    parser.add_argument("--session-wait-seconds", type=int, default=600, choices=range(1, 3601))
    parser.add_argument("--agent-backend-config", type=Path)
    parser.add_argument("--judge-backend-config", type=Path)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--resume-unqueried-provider", action="store_true")
    parser.add_argument("--allow-code-execution", action="store_true")
    parser.add_argument("--common-terminal-delivery", action="store_true")
    parser.add_argument("--taste-extra-source", nargs=2, type=Path, action="append")
    parser.add_argument("--continue-unqueried-session", type=Path)
    args = parser.parse_args()
    if not args.allow_development_execution:
        raise ValueError("Explicit development execution is required")
    live = args.agent_backend_config is not None
    if live != (args.judge_backend_config is not None) or live != args.allow_api_execution:
        raise ValueError("API execution requires both configs and explicit opt-in")
    if args.common_terminal_delivery and not live:
        raise ValueError("Common terminal delivery requires a budgeted provider")
    if not args.task.name.startswith("development_task_"):
        raise ValueError("This runner does not consume formal or sealed assignments")
    project = args.project.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(project / "evaluations")
    task_bytes = args.task.read_bytes()
    continuation = None
    session_request_limit = 32
    if args.continue_unqueried_session:
        if live or args.resume_unqueried_provider:
            raise ValueError("Session continuation cannot enable or resume provider execution")
        source = args.continue_unqueried_session.resolve(strict=True)
        source.relative_to(project / "evaluations")
        if (source / "SESSION_CONTINUATION.json").exists():
            raise ValueError("An unqueried continuation has already been reserved")
        prior = json.loads((source / "RESULT.json").read_text())
        contract = json.loads((source / "CONTRACT.json").read_text())
        if (
            prior.get("status") != "interrupted"
            or prior.get("queries_used") != 0
            or prior.get("code_calls_used") != 0
            or prior.get("tool_steps") != 0
            or prior.get("submission") is not None
            or prior.get("accounting", {}).get("source") != "assistant-session"
            or contract.get("task_sha256") != hashlib.sha256(task_bytes).hexdigest()
            or contract.get("session_continuation")
        ):
            raise ValueError("Only one unqueried, unsubmitted session may be continued")
        trace = source / "tools/TOOL_TRACE.jsonl"
        if trace.exists() and trace.read_text().strip():
            raise ValueError("A tool trace already exists; cannot continue as unqueried")
        spent = len(list((source / "session-exchange").glob("*.request.json")))
        session_request_limit -= spent
        if session_request_limit < 1:
            raise ValueError("No inherited session request budget remains")
        continuation = {
            "source": source.relative_to(project).as_posix(),
            "source_result_sha256": hashlib.sha256(
                (source / "RESULT.json").read_bytes()
            ).hexdigest(),
            "requests_previously_reserved": spent,
            "status": "supplementary-format-continuation-not-primary-replacement",
        }
    task = NewtonBenchTask.model_validate_json(task_bytes)
    limits, code_runner = execution_setup(task, live=live, allow_code=args.allow_code_execution)
    treatment = prepare_taste(args, project)
    if continuation and contract.get("taste_binding") != (treatment[2] if treatment else None):
        raise ValueError("Session continuation cannot change the frozen Taste treatment")
    if args.resume_unqueried_provider and not live:
        raise ValueError("Empty recovery requires provider execution")
    output.mkdir(exist_ok=args.resume_unqueried_provider)
    if continuation:
        with (source / "SESSION_CONTINUATION.json").open("x") as stream:
            json.dump({**continuation, "successor": output.relative_to(project).as_posix()}, stream)
    if args.resume_unqueried_provider:
        if (output / "RESULT.json").exists() or list((output / "loop").glob("decision-*.json")):
            raise ValueError("Cannot replay a terminal run or an already selected action")
    if treatment:
        profile, library_bytes, taste_binding = treatment
        library_path = output / "TASTE_LIBRARY.jsonl"
        if args.resume_unqueried_provider:
            if library_path.read_bytes() != library_bytes:
                raise ValueError("Frozen Taste library changed")
        else:
            with library_path.open("xb") as stream:
                stream.write(library_bytes)
        retain_json(output / "TASTE_PROFILE.json", profile.model_dump(mode="json"))
        retain_json(output / "TASTE_BINDING.json", taste_binding)
    if live:
        from scitaste.backends.research_provider import research_provider

        _, backend = research_provider(args.agent_backend_config, output / "provider")
        backend.recover_unqueried = args.resume_unqueried_provider
        _, judge_backend = research_provider(
            args.judge_backend_config, output / "judge-provider", max_calls=4, max_cost_usd=2
        )
        if treatment and (profile.provider, profile.model) != (backend.name, backend.model):
            raise ValueError("Taste profile differs from the bound research provider")
    else:
        backend = SessionStructuredBackend(
            output / "session-exchange",
            wait_seconds=args.session_wait_seconds,
            max_requests=session_request_limit,
        )
        judge_backend = SessionStructuredBackend(
            output / "judge-exchange", wait_seconds=args.session_wait_seconds, max_requests=4
        )
    bridge = SessionNativeBridge(backend)
    judge = StructuredNewtonBenchJudge(
        judge_backend,
        backend_configuration_sha256=hashlib.sha256(
            args.judge_backend_config.read_bytes() if live else b"independent-session-judge-v1"
        ).hexdigest(),
    )
    toolbox = NewtonBenchToolbox(
        project / "evaluations/acquisitions/newtonbench-source-v1/checkout",
        repository_commit=BENCHMARK_PIN,
        task=task,
        symbolic_judge=judge,
        code_runner=code_runner,
    )
    environment = NewtonBenchAgentToolEnvironment(
        toolbox=toolbox,
        limits=limits,
        log_root=output / "tools",
        resume_unqueried=args.resume_unqueried_provider,
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "system": "scitaste-native-reviewed-taste" if treatment else "scitaste-native-no-taste",
            "benchmark_commit": BENCHMARK_PIN,
            "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
            "task_id": task.task_id,
            "tool_interface_sha256": environment.interface_fingerprint,
            "limits": limits.model_dump(mode="json"),
            "model_source": backend.name,
            "model": backend.model,
            "stateless_requests": live,
            "backend_configuration_sha256": (
                hashlib.sha256(args.agent_backend_config.read_bytes()).hexdigest() if live else None
            ),
            "formal_evidence_eligible": False,
            "scope": "development-native-system-arm",
            "taste_enabled": bool(treatment),
            "taste_binding": treatment[2] if treatment else None,
            "max_session_requests": session_request_limit,
            "session_continuation": continuation,
            "treatment_semantics": "grounded deliberation with intrinsic fallback; not full system",
            "controller": "TasteController; no utility/critics/learned-policy; session preference",
            "proposal_count": 2,
            "common_terminal_delivery": args.common_terminal_delivery,
            "research_stage": "EVIDENCE",
            "token_budget_semantics": (
                "Provider usage retained; shared conservative liability ceiling, not invoice"
                if live
                else "Tokenizer usage unknown; bounded requests/bytes instead"
            ),
            "judge_semantics": "Separate requests after frozen submission; not human review",
            "gpu_execution": False,
            "code_policy": code_runner.policy.model_dump(mode="json") if code_runner else None,
        },
    )
    state = ResearchState(
        project_id=project.name,
        current_stage=ResearchStage.EVIDENCE,
        research_direction=toolbox.task_prompt,
        target_domain="NewtonBench scientific discovery",
        resource_budget=ResourceBudget(max_experiments=24, max_api_cost_usd=8 if live else 0),
    )
    controller = TasteController(
        utility_enabled=False,
        critics_enabled=False,
        preference_backend=SessionPreferenceBackend(backend),
    )
    runtime = ProjectRuntime(project.parent.parent)
    if treatment:
        from scitaste.data.store import TasteLibrary
        from scitaste.taste.controller import TasteMode
        from scitaste.taste.research_tool_deliberation import DeliberativeResearchToolController
        from scitaste.taste.retriever import TasteRetriever

        controller = DeliberativeResearchToolController(
            base=controller,
            augmented=TasteController(
                mode=TasteMode.AUGMENTED,
                retriever=TasteRetriever(TasteLibrary(output / "TASTE_LIBRARY.jsonl")),
                utility_enabled=False,
                critics_enabled=False,
                preference_backend=controller.preference_backend,
            ),
            runtime=runtime,
            run_id=output.name,
            backend=backend,
            profile=treatment[0],
            output=output / "taste_deliberation",
            resume=args.resume_unqueried_provider,
        )

    def proposer(current, history, env):
        prompt = json.dumps(
            {
                "research_problem": env.research_problem,
                "tools": {
                    name: {"description": info.description, "usage": info.usage}
                    for name, info in env.action_infos.items()
                },
                "limits": limits.model_dump(mode="json"),
                "turns_used": env.turns_used,
                "experiments_used": env.experiments_used,
                "code_calls_used": env.code_calls_used,
                "observed_history": history,
                "instruction": (
                    "Return exactly two distinct feasible proposals under key proposals. Each has "
                    "tool, arguments, rationale. Use only listed tools and measured observations. "
                    "Final Answer final_solution must follow the task's required law format. "
                    "Propose from these observations only; no external solutions. "
                    "Taste, if configured, is evaluated separately by the controller. "
                    f"Submit before turn {limits.max_turns}. "
                    "Keep candidate laws in final_solution, not invented best_score values."
                ),
            },
            ensure_ascii=False,
        )
        from scitaste.research_tool_loop import ResearchToolProposalBatch

        for attempt in range(2):
            suffix = "" if not attempt else "-format-repair"
            payload = json.loads(
                bridge.complete_text(
                    prompt,
                    output / f"proposal-{len(history):03d}{suffix}.json",
                    backend.model,
                    max_tokens_to_sample=8192,
                )
            )
            try:
                terminal = terminal_proposal(payload)
                if terminal is not None:
                    env.validate_tool_arguments(terminal["tool"], terminal["arguments"])
                    retain_json(
                        output / f"terminal-format-{len(history):03d}.json",
                        {
                            "operation": (
                                "Collapse identical final submissions without changing content"
                            ),
                            "original": payload,
                            "terminal": terminal,
                        },
                    )
                    return terminal
                batch = ResearchToolProposalBatch.model_validate(payload)
                if len(batch.proposals) != 2:
                    raise ValueError("Return exactly two alternatives")
                for item in batch.proposals:
                    env.validate_tool_arguments(item.tool, item.arguments)
                return payload
            except ValueError as exc:
                if attempt:
                    raise
                prompt += "\nFORMAT REPAIR (no tools executed): " + str(exc)[:2500]
                prompt += "\nPreserve proposed values; follow the tool schema. Previous proposal: "
                prompt += json.dumps(payload)

    register = runtime.begin_run
    if args.resume_unqueried_provider:
        existing = next(
            r for r in runtime.open(project.name).manifest.runs if r.run_id == output.name
        )
        if existing.provider != backend.name or existing.model != backend.model:
            raise ValueError("Recovery provider differs from the registered run")
        retain_json(
            output / "EMPTY_RECOVERY.json",
            {
                "no_tool_replay": True,
                "inherited_provider_budget": True,
                "reason": "Accounting failure after initial proposal; original responses retained",
            },
        )

        def register(*args, **kwargs):
            return None

    register(
        project.name,
        ProjectRun(
            run_id=output.name,
            provider=backend.name,
            model=backend.model,
            condition=("native-reviewed-taste" if treatment else "native-no-taste")
            + "-newton-shared-tools",
            seed=task.environment_seed,
            status="agent-running",
            artifact=(output / "CONTRACT.json").relative_to(project).as_posix(),
            evidence_scope="Native shared-tool arm; consumed development family; not formal",
            formal_evidence_eligible=False,
        ),
        expected_revision=runtime.open(project.name).revision,
    )
    result = {"formal_evidence_eligible": False}
    try:
        outcome = run_research_tool_loop(
            state=state,
            controller=controller,
            proposer=proposer,
            environment=environment,
            workspace=output / "loop",
            artifact_root=project,
            max_turns=limits.max_turns,
            max_proposals=2,
            finish_at_experiment_limit=False,
        )
        result.update(status="agent-returned", outcome=outcome, submission=environment.submission)
    except Exception as exc:
        result.update(status="interrupted", error_type=type(exc).__name__, error=str(exc)[:500])
    retain_json(output / "CONTROLLER_TERMINAL.json", result)
    if not live:
        retain_json(
            output / "session-exchange/SESSION_CLOSED.json",
            {
                "status": "research-role-complete",
                "controller_status": result["status"],
                "submission_present": environment.submission is not None,
                "judge_outputs_included": False,
            },
        )
    try:
        if args.common_terminal_delivery:
            from scitaste.evaluation.newton_terminal_delivery import deliver_terminal_hypothesis

            deliver_terminal_hypothesis(
                bridge=backend.bridge, environment=environment, output=output
            )
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
        judge_usage_semantics="Provider usage/liability retained"
        if live
        else "Session usage unknown",
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

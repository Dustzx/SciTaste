"""Project-owned Native workspace orchestration with terminal stage recovery."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scitaste.executor.workspace_task import load_native_workspace_plan
from scitaste.project.cycle_progress import publish_cycle_progress
from scitaste.project.models import validate_entry_id
from scitaste.project.paper_feedback import load_paper_feedback
from scitaste.project.research_artifact import register_artifact
from scitaste.project.workspace_experience import (
    finalize_workspace_experience,
    resolve_candidate_path,
)
from scitaste.taste.episodes import TasteEpisodeCandidate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retain(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError(f"Retained cycle record changed: {path.name}")
    else:
        with path.open("x") as stream:
            json.dump(value, stream, indent=2)


def retained_execution_boundary(execution, *, plan_sha256, taste_binding):
    """Recognize persisted execution, not subprocess success or scientific quality."""
    contract_path, result_path = execution / "CONTRACT.json", execution / "RESULT.json"
    if not contract_path.is_file() or not result_path.is_file():
        return None
    contract = json.loads(contract_path.read_text())
    result = json.loads(result_path.read_text())
    if (
        contract.get("plan_sha256") != plan_sha256
        or contract.get("controller_owner") != "scitaste-native"
        or result.get("controller_owner") != "scitaste-native"
        or contract.get("development_taste") != taste_binding
    ):
        raise ValueError("Persisted execution boundary belongs to another plan or treatment")
    if result.get("status") not in {
        "controller-finished",
        "turn-budget-exhausted",
        "experiment-budget-exhausted",
        "native-workspace-interrupted",
        "native-workspace-budget-exhausted",
        "execution-unresolved",
    }:
        raise ValueError("Unknown persisted Native execution boundary")
    return {
        "execution": str(execution),
        "result_sha256": sha(result_path),
        "contract_sha256": sha(contract_path),
        "status": result["status"],
        "execution_relaunched": False,
        "postprocessing_complete": False,
    }


def run_cycle(args):
    root, output = args.project.resolve(strict=True), args.output.resolve()
    base = root / "evaluations"
    session_exchange = getattr(args, "session_exchange", None)
    paper_flow = getattr(args, "paper_flow", None)
    if session_exchange:
        session_exchange = session_exchange.resolve()
        session_exchange.relative_to(root)
        if args.allow_api or getattr(args, "max_execution_continuations", 0):
            raise ValueError("Session cycles cannot enable API or automatic provider continuation")
    execution = (args.execution_run or base / (output.name + "-execution")).resolve()
    delivery = (args.report_delivery or base / (output.name + "-report")).resolve()
    prefix = args.paper_prefix or output.name + "-paper"
    validate_entry_id(prefix, field_name="paper prefix")
    validate_entry_id(output.name, field_name="cycle identity")
    for path in (output, execution, delivery, args.plan.resolve(strict=True)):
        path.relative_to(root)
    if len({output, execution, delivery}) != 3:
        raise ValueError("Cycle, execution and report delivery need separate directories")
    unsupported = (
        "brief",
        "baseline_run",
        "baseline_source",
        "task_context",
        "development_policy_refresh",
    )
    if any(getattr(args, key) for key in unsupported):
        raise ValueError("Unlearning-only options are not supported by Native workspace cycles")
    from scitaste.taste.research_tool_deliberation import workspace_taste_binding

    taste_binding, _ = workspace_taste_binding(
        args.development_taste_library, args.taste_deliberation_profile
    )
    plan_path = args.plan.resolve(strict=True)
    plan = json.loads(plan_path.read_text())
    if plan["executor_id"] != "scitaste-native-workspace":
        raise ValueError("Prepared plan is not Native workspace owned")
    # Validate current resources only before a new execution; historical delivery
    # remains recoverable after the current project idea or provider config changes.
    if not (execution / "RESULT.json").exists():
        load_native_workspace_plan(root, plan_path)
    contract = {
        "scope": "native-workspace-project-cycle",
        "project": root.name,
        "plan": plan_path.relative_to(root).as_posix(),
        "plan_sha256": sha(plan_path),
        "execution": execution.relative_to(root).as_posix(),
        "delivery": delivery.relative_to(root).as_posix(),
        "paper_prefix": prefix,
        "next_planning_objective": args.next_planning_objective,
        "positive_result_required": False,
        "automatic_experiment_relaunch": False,
        "workflow_gaps": None,
    }
    if taste_binding is not None:
        contract["development_taste"] = taste_binding
    context_options = {
        name: getattr(args, name, None)
        for name in ("taste_decision_context", "taste_proposal_context", "taste_action_selection")
        if getattr(args, name, None) is not None
    }
    if context_options:
        # Explicit opt-in keeps historical cycle contracts byte-compatible.
        # The executor independently checks these against the frozen campaign.
        contract["native_context_policy"] = context_options
    if args.research_state:
        from scitaste.executor.state_handoff import load_predecessor

        _, contract["predecessor_state"] = load_predecessor(root, args.research_state)
    if session_exchange:
        contract["session_exchange"] = str(session_exchange)
    if paper_flow:
        paper_flow = paper_flow.resolve(strict=True)
        paper_flow.relative_to(root)
        contract["paper_flow"] = str(paper_flow.relative_to(root))
    continuation_limit = getattr(args, "max_execution_continuations", 0)
    if not 0 <= continuation_limit <= 3:
        raise ValueError("Automatic continuation count must be bounded from zero to three")
    if continuation_limit:
        contract["max_execution_continuations"] = continuation_limit
    resources = getattr(args, "next_workspace_resources", [])
    acquisitions = getattr(args, "next_acquisition_option", [])
    acquire_next = getattr(args, "acquire_next_resources", False)
    if acquisitions:
        from scitaste.project.acquisition_selection import acquisition_option

        if not args.next_planning_objective:
            raise ValueError("Acquisition options require a next planning objective")
        contract["next_acquisition_options"] = [
            acquisition_option(root, p)[1] for p in acquisitions
        ]
        contract["acquire_next_resources"] = acquire_next
    elif acquire_next:
        raise ValueError("Resource acquisition requires declared next acquisition options")
    if resources:
        from scitaste.executor.workspace_provision import resource_option

        if not args.next_planning_objective:
            raise ValueError("Next workspace resources require a next planning objective")
        contract["next_workspace_resources"] = [resource_option(root, p)[1] for p in resources]
    if args.workflow_gaps:
        gaps = args.workflow_gaps.resolve(strict=True)
        gaps.relative_to(root)
        contract["workflow_gaps"] = {
            "locator": gaps.relative_to(root).as_posix(),
            "sha256": sha(gaps),
        }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        retain(output / "CONTRACT.json", contract)
        if not (output / "RESULT.json").exists():
            publish_cycle_progress(
                root,
                output,
                output / "CONTRACT.json",
                status="coordinator-entered",
                stage="preparation",
            )

        def launch(stage, command, *, once=True, execution_boundary=None):
            marker = output / (stage + ".started.json")
            if once:
                if marker.exists():
                    raise ValueError(f"Observe or recover {stage}; do not relaunch")
                retain(marker, {"command": command, "automatic_retry": False})
            publish_cycle_progress(
                root,
                output,
                marker if once else output / "CONTRACT.json",
                status="stage-start-recorded",
                stage=stage,
            )
            with (output / (stage + ".log")).open("a") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if once:
                retain(output / (stage + ".exit.json"), {"returncode": result.returncode})
            publish_cycle_progress(
                root,
                output,
                output / (stage + ".exit.json") if once else output / "CONTRACT.json",
                status="stage-returned" if result.returncode == 0 else "stage-needs-attention",
                stage=stage,
            )
            if result.returncode:
                if result.returncode == 75 and stage == "report-cycle" and session_exchange:
                    return 75
                if (
                    result.returncode == 75
                    and execution_boundary is not None
                    and session_exchange
                    and (execution_boundary / "SESSION_PENDING.json").is_file()
                ):
                    return
                if execution_boundary is not None:
                    boundary = retained_execution_boundary(
                        execution_boundary,
                        plan_sha256=contract["plan_sha256"],
                        taste_binding=taste_binding,
                    )
                    if boundary is not None:
                        retain(
                            output / (stage + ".retained-boundary.json"),
                            {**boundary, "returncode": result.returncode},
                        )
                        # Recovery/reporting retain their own pending-job, accounting,
                        # trajectory and collection gates. A receipt is not success.
                        return
                raise ValueError(f"{stage} stopped; prior stages retained, inspect its log")

        if not (execution / "RESULT.json").exists():
            from scitaste.project.planning_intervention import execution_boundary

            # Do not interrupt a committed/pending run; new intent governs the
            # next planning/run boundary rather than replaying old tool actions.
            if not execution.exists():
                execution_boundary(root, plan)
            pending_session = bool(
                session_exchange and (execution / "SESSION_PENDING.json").is_file()
            )
            if (
                execution.exists() or (output / "execution.started.json").exists()
            ) and not pending_session:
                raise ValueError("Execution already started; observe it, never silently relaunch")
            if (not args.allow_api and not session_exchange) or not args.allow_execution:
                publish_cycle_progress(
                    root,
                    output,
                    output / "CONTRACT.json",
                    status="awaiting-execution-enablement",
                    stage="preparation",
                )
                print(
                    json.dumps(
                        {
                            "status": "prepared-not-executed",
                            "contract": str(output / "CONTRACT.json"),
                        }
                    )
                )
                return
            execution_command = [
                sys.executable,
                "-m",
                "scitaste.executor.native_workspace",
                "--project",
                str(root),
                "--plan",
                str(plan_path),
                "--output",
                str(execution),
                "--allow-api",
                "--allow-execution",
            ]
            if args.credentials:
                execution_command.extend(["--credentials", str(args.credentials.resolve())])
            if args.research_state:
                execution_command.extend(["--research-state", str(args.research_state.resolve())])
            if session_exchange:
                execution_command.remove("--allow-api")
                execution_command.extend(
                    ["--session-exchange", str(execution / "session-exchange")]
                )
            if taste_binding is not None:
                execution_command.extend(
                    [
                        "--development-taste-library",
                        str(args.development_taste_library.resolve()),
                        "--taste-deliberation-profile",
                        str(args.taste_deliberation_profile.resolve()),
                    ]
                )
            for name, value in context_options.items():
                execution_command.extend(["--" + name.replace("_", "-"), value])
            stage = "execution"
            if pending_session:
                from scitaste.project.session_recovery import pending_resume_stage

                stage = pending_resume_stage(output, execution, execution_command, stage=stage)
            launch(stage, execution_command, execution_boundary=execution)
            if (
                not (execution / "RESULT.json").exists()
                and (execution / "SESSION_PENDING.json").is_file()
            ):
                pending = {
                    "status": "awaiting-session-response",
                    "stage": "execution",
                    "execution": str(execution),
                    "whole_project_lifecycle_complete": False,
                }
                (output / "WORKFLOW_STATUS_PENDING.json").write_text(json.dumps(pending, indent=2))
                publish_cycle_progress(
                    root,
                    output,
                    output / "WORKFLOW_STATUS_PENDING.json",
                    status="awaiting-session-response",
                    stage="execution",
                )
                print(json.dumps(pending))
                return
        continuations = []
        for index in range(continuation_limit):
            from scitaste.project.bounded_continuation import continuation_decision

            child = base / (output.name + f"-continuation-{index + 1:02d}")
            policy = continuation_decision(
                execution,
                plan_sha256=contract["plan_sha256"],
                taste_binding=taste_binding,
                expected_child=child,
            )
            if not policy["eligible"]:
                if policy["reason"] in {
                    "provider-request-unresolved",
                    "remaining-budget-already-claimed",
                }:
                    print(
                        json.dumps(
                            {
                                "status": "continuation-needs-observation",
                                "source_execution": str(execution),
                                "policy": policy,
                                "report_started": False,
                            }
                        )
                    )
                    return
                break
            stage = f"continuation-{index + 1:02d}"
            if not (child / "RESULT.json").exists():
                if child.exists() or (output / (stage + ".started.json")).exists():
                    raise ValueError("Continuation already started; observe it, never relaunch")
                if not args.allow_api or not args.allow_execution:
                    print(
                        json.dumps(
                            {
                                "status": "continuation-awaiting-enablement",
                                "source_execution": str(execution),
                                "policy": policy,
                            }
                        )
                    )
                    return
                retain(output / (stage + ".policy.json"), policy)
                command = [
                    sys.executable,
                    "-m",
                    "scitaste.executor.native_workspace",
                    "--project",
                    str(root),
                    "--plan",
                    str(plan_path),
                    "--output",
                    str(child),
                    "--continue-from",
                    str(execution),
                    "--allow-api",
                    "--allow-execution",
                ]
                for name in (
                    "credentials",
                    "development_taste_library",
                    "taste_deliberation_profile",
                ):
                    value = getattr(args, name)
                    if value:
                        command.extend(["--" + name.replace("_", "-"), str(value.resolve())])
                for name, value in context_options.items():
                    command.extend(["--" + name.replace("_", "-"), value])
                launch(stage, command, execution_boundary=child)
            child_contract = json.loads((child / "CONTRACT.json").read_text())
            lineage = child_contract.get("continuation") or {}
            if lineage.get("parent") != str(execution) or lineage.get(
                "parent_result_sha256"
            ) != sha(execution / "RESULT.json"):
                raise ValueError("Retained continuation belongs to another execution")
            continuations.append(
                {
                    "parent": execution.relative_to(root).as_posix(),
                    "child": child.relative_to(root).as_posix(),
                    "child_result_sha256": sha(child / "RESULT.json"),
                }
            )
            execution = child
        if continuation_limit:
            retain(
                output / "CONTINUATIONS.json",
                {
                    "continuations": continuations,
                    "effective_execution": execution.relative_to(root).as_posix(),
                    "budget_extension": False,
                },
            )
        executed_contract = json.loads((execution / "CONTRACT.json").read_text())
        terminal = json.loads((execution / "RESULT.json").read_text())
        if terminal["status"] == "execution-unresolved":
            print(
                json.dumps(
                    {
                        "status": "execution-still-unresolved",
                        "execution": str(execution),
                        "automatic_relaunch": False,
                        "report_started": False,
                    }
                )
            )
            return
        if (
            executed_contract["plan_sha256"] != contract["plan_sha256"]
            or executed_contract["controller_owner"] != "scitaste-native"
            or terminal["controller_owner"] != "scitaste-native"
            or executed_contract.get("development_taste") != taste_binding
        ):
            raise ValueError("Terminal execution does not belong to this Native plan")
        command = [
            sys.executable,
            "-m",
            "scitaste.writing.native_lifecycle",
            "--project",
            str(root),
            "--source-run",
            str(execution),
            "--delivery",
            str(delivery),
            "--paper-prefix",
            prefix,
        ]
        if args.allow_api:
            command.append("--allow-api")
        if session_exchange:
            command.extend(["--session-exchange", str(session_exchange / "paper")])
        if paper_flow:
            command.extend(["--paper-flow", str(paper_flow)])
        if getattr(args, "figure_contract_repair", None):
            command.extend(["--figure-contract-repair", str(args.figure_contract_repair.resolve())])
        for key, flag in (
            ("paper_backend", "backend"),
            ("review_profile", "review-profile"),
            ("venue_taste_profile", "venue-taste-profile"),
            ("credentials", "credentials"),
        ):
            value = getattr(args, key)
            if value:
                command.extend(["--" + flag, str(value.resolve())])
        paper_cycle = paper_flow or base / (prefix + "-cycle")
        if launch("report-cycle", command, once=False) == 75:
            pointer = paper_cycle / "WORKFLOW_STATUS_PENDING.json"
            pending = json.loads(pointer.read_text())
            if pending.get("status") != "awaiting-session-response":
                raise ValueError("Paper wait has no explicit pending state")
            node_pending = Path(pending["pending"]).resolve(strict=True)
            node_pending.relative_to(root)
            node = json.loads(node_pending.read_text())
            if node.get("status") != "awaiting-session-response" or node.get("api_calls") != 0:
                raise ValueError("Paper wait is not a retained no-API session request")
            pending = {
                **pending,
                "stage": "paper-" + pending["stage"],
                "execution_status": terminal["status"],
                "execution_relaunch_required": False,
                "whole_project_lifecycle_complete": False,
            }
            pointer = output / "WORKFLOW_STATUS_PENDING.json"
            temporary = pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps(pending, indent=2))
            temporary.replace(pointer)
            publish_cycle_progress(
                root,
                output,
                pointer,
                status="awaiting-session-response",
                stage=pending["stage"],
            )
            print(json.dumps(pending))
            return
        feedback = load_paper_feedback(root, paper_cycle)
        retain(output / "PAPER_FEEDBACK.json", feedback)
        from scitaste.project.workspace_collection_recovery import ensure_workspace_collection

        collection = ensure_workspace_collection(root, execution)
        collected = json.loads(collection.read_text())
        if collected["source_run_id"] != execution.name:
            raise ValueError("Experience collection belongs to a different execution")
        for row in collected["candidates"]:
            candidate = resolve_candidate_path(root, row["candidate"])
            candidate.relative_to(root)
            parsed = TasteEpisodeCandidate.model_validate_json(candidate.read_bytes())
            if parsed.candidate_sha256 != row["candidate_sha256"] or parsed.project_id != root.name:
                raise ValueError("Quarantined experience changed")
        result = {
            "status": "native-workspace-cycle-delivered",
            "contract_sha256": sha(output / "CONTRACT.json"),
            "execution_result_sha256": sha(execution / "RESULT.json"),
            "source_terminal_status": terminal["status"],
            "delivery_result_sha256": sha(delivery / "RESULT.json"),
            "paper_summary_sha256": sha(paper_cycle / "SUMMARY.json"),
            "planning_feedback_sha256": sha(output / "PAPER_FEEDBACK.json"),
            "current_run_experience_collection_sha256": sha(collection),
            "current_run_quarantined_candidates": len(collected["candidates"]),
            "historical_candidates_recounted": False,
            "policy_updated": False,
            "review_closed": False,
            "whole_project_lifecycle_complete": False,
            "paper_directory": prefix + "-revised",
        }
        if continuation_limit:
            result["effective_execution"] = execution.relative_to(root).as_posix()
            result["continuations_sha256"] = sha(output / "CONTINUATIONS.json")
        retain(output / "RESULT.json", result)
        register_artifact(
            project=root,
            artifact=output / "RESULT.json",
            provider="native-lifecycle",
            model="stage-bound",
            condition=contract["scope"],
            status=result["status"],
        )
        disposition_dir = base / (output.name + "-experience-disposition")
        disposition = finalize_workspace_experience(
            project=root, execution=execution, paper_cycle=paper_cycle, output=disposition_dir
        )
        retain(
            output / "EXPERIENCE_DISPOSITION.json",
            {
                "result": (disposition_dir / "RESULT.json").relative_to(root).as_posix(),
                "result_sha256": sha(disposition_dir / "RESULT.json"),
                "status": disposition["status"],
                "policy_updated": False,
            },
        )
        next_plan_status = "not-requested"
        next_plan_rejections = []
        acquisition_status = None
        if args.next_planning_objective:
            next_plan = base / (output.name + "-next-plan")
            if not (next_plan / "RESULT.json").exists():
                if next_plan.exists() and not (
                    session_exchange and (next_plan / "SESSION_PENDING.json").is_file()
                ):
                    raise ValueError("Existing next-plan attempt needs recovery")
                if not args.allow_api and not session_exchange:
                    print(json.dumps({**result, "next_plan_status": "awaiting-api-enablement"}))
                    return
                command = [
                    sys.executable,
                    "-m",
                    "scitaste.project.research_planning",
                    "--project",
                    str(root),
                    "--output",
                    str(next_plan),
                    "--objective",
                    args.next_planning_objective,
                    "--previous-paper-flow",
                    str(paper_cycle),
                    "--evidence",
                    str(output / "RESULT.json"),
                    "--allow-api",
                ]
                # Freeze the operational context once. Later session resumes must
                # not rebind model input to a moving project-progress pointer.
                progress_context = output / "PLANNING_PROGRESS.json"
                if not progress_context.exists() and not next_plan.exists():
                    observation = publish_cycle_progress(
                        root,
                        output,
                        output / "EXPERIENCE_DISPOSITION.json",
                        status="experience-disposition-recorded",
                        stage="next-plan",
                    )
                    retain(progress_context, observation)
                if progress_context.exists():
                    command.extend(["--evidence", str(progress_context)])
                if session_exchange:
                    command.remove("--allow-api")
                    command.extend(
                        [
                            "--session-exchange",
                            str(session_exchange / "planning"),
                            "--session-wait-seconds",
                            "600",
                        ]
                    )
                if args.workflow_gaps:
                    command.extend(["--workflow-gaps", str(args.workflow_gaps.resolve())])
                if terminal.get("research_state"):
                    canonical_state = (root / terminal["research_state"]).resolve(strict=True)
                    canonical_state.relative_to(execution)
                    if sha(canonical_state) != terminal["research_state_sha256"]:
                        raise ValueError("Execution canonical state changed before next planning")
                    command.extend(["--evidence", str(canonical_state)])
                if taste_binding is not None:
                    command.extend(
                        [
                            "--development-taste-library",
                            str(args.development_taste_library.resolve()),
                            "--taste-deliberation-profile",
                            str(args.taste_deliberation_profile.resolve()),
                        ]
                    )
                for resource in resources:
                    command.extend(["--workspace-resources", str(resource.resolve())])
                for option in acquisitions:
                    command.extend(["--acquisition-option", str(option.resolve())])
                if acquire_next:
                    command.append("--acquire-selection")
                if acquire_next and getattr(args, "allow_network_download", False):
                    command.append("--allow-network-download")
                if resources:
                    command.append("--compile-selection")
                # Session-bound open-research plans intentionally have no provider
                # configuration. Never invent one merely for delivery/planning.
                if not session_exchange:
                    command.extend(["--backend", str(Path(plan["backend"]["path"]).resolve())])
                if args.credentials:
                    command.extend(["--credentials", str(args.credentials.resolve())])
                command.extend(["--evidence", str(disposition_dir / "RESULT.json")])
                stage = "next-plan"
                if (output / "next-plan.started.json").exists() and session_exchange:
                    from scitaste.project.session_recovery import planning_resume_stage

                    stage = planning_resume_stage(output, next_plan, command)
                launch(stage, command)
                if session_exchange and not (next_plan / "RESULT.json").exists():
                    pending = json.loads((next_plan / "SESSION_PENDING.json").read_text())
                    status = {
                        "status": "awaiting-session-response",
                        "next_plan_status": "pending",
                        "request": pending["request"],
                        "completed_stages_reexecuted": False,
                        "whole_project_lifecycle_complete": False,
                    }
                    retain(output / "WORKFLOW_STATUS_PENDING.json", status)
                    publish_cycle_progress(
                        root,
                        output,
                        output / "WORKFLOW_STATUS_PENDING.json",
                        status="awaiting-session-response",
                        stage="next-plan",
                    )
                    print(json.dumps(status))
                    return
            retain(
                output / "NEXT_PLAN.json",
                {
                    "result": (next_plan / "RESULT.json").relative_to(root).as_posix(),
                    "result_sha256": sha(next_plan / "RESULT.json"),
                    "execution_authorized": False,
                },
            )
            next_result = json.loads((next_plan / "RESULT.json").read_text())
            effective_next_plan = next_plan
            format_recovery = getattr(args, "next_plan_format_recovery", None)
            if format_recovery:
                recovery = format_recovery.resolve(strict=True)
                recovery.relative_to(root)
                receipt = json.loads((recovery / "CONTRACT.json").read_text())
                if (
                    not session_exchange
                    or next_result["status"] != "rejected"
                    or next_result["rejection_reasons"] != ["output token budget exceeded"]
                    or receipt["session_format_recovery_from"] != str(next_plan)
                    or receipt["parent_result_sha256"] != sha(next_plan / "RESULT.json")
                    or receipt["parent_input_sha256"] != sha(next_plan / "INPUT.json")
                    or receipt["parent_contract_sha256"] != sha(next_plan / "CONTRACT.json")
                    or receipt["source_contract_sha256"] != sha(execution / "CONTRACT.json")
                    or receipt["budget_extension"] is not False
                    or receipt["max_additional_requests"] != 1
                    or receipt["execution_authorized"] is not False
                    or json.loads((recovery / "INPUT.json").read_text())
                    != json.loads((next_plan / "INPUT.json").read_text())
                ):
                    raise ValueError("Planning format recovery changed its source or authority")
                next_result = json.loads((recovery / "RESULT.json").read_text())
                effective_next_plan = recovery
                retain(
                    output / "NEXT_PLAN_FORMAT_RECOVERY.json",
                    {
                        "original_result": (next_plan / "RESULT.json").relative_to(root).as_posix(),
                        "original_result_sha256": sha(next_plan / "RESULT.json"),
                        "result": (recovery / "RESULT.json").relative_to(root).as_posix(),
                        "result_sha256": sha(recovery / "RESULT.json"),
                        "format_only": True,
                        "execution_authorized": False,
                    },
                )
            current_gaps = root / "docs/WORKFLOW_GAPS_CURRENT.json"
            gap_registry = args.workflow_gaps or (
                current_gaps if current_gaps.is_file() else root / "docs/WORKFLOW_GAPS.json"
            )
            if (
                next_result["status"] == "rejected"
                and not format_recovery
                and args.allow_api
                and gap_registry.is_file()
                and json.loads(gap_registry.read_text())
            ):
                child_plan = next_plan.with_name(next_plan.name + "-retry-01")
                if not (child_plan / "RESULT.json").exists():
                    if child_plan.exists():
                        raise ValueError(
                            "Planning retry already started; observe its retained work"
                        )
                    command = json.loads((output / "next-plan.started.json").read_text())["command"]
                    command[command.index("--output") + 1] = str(child_plan)
                    command.extend(["--retry-from", str(next_plan)])
                    launch("next-plan-retry-01", command)
                retry_contract = json.loads((child_plan / "CONTRACT.json").read_text())
                retry_binding = retry_contract.get("retry_from") or {}
                if retry_binding.get("parent") != str(next_plan) or retry_binding.get(
                    "result_sha256"
                ) != sha(next_plan / "RESULT.json"):
                    raise ValueError("Planning recovery belongs to another original result")
                retain(
                    output / "NEXT_PLAN_RECOVERY.json",
                    {
                        "original_result": (next_plan / "RESULT.json").relative_to(root).as_posix(),
                        "original_result_sha256": sha(next_plan / "RESULT.json"),
                        "result": (child_plan / "RESULT.json").relative_to(root).as_posix(),
                        "result_sha256": sha(child_plan / "RESULT.json"),
                        "execution_authorized": False,
                    },
                )
                next_result = json.loads((child_plan / "RESULT.json").read_text())
                effective_next_plan = child_plan
            next_plan_status = next_result["status"]
            next_plan_rejections = next_result.get("rejection_reasons", [])
            if acquire_next and next_plan_status == "accepted":
                from scitaste.project.acquisition_selection import materialize_accepted_acquisition

                materialized = materialize_accepted_acquisition(
                    project=root,
                    planning_run=effective_next_plan,
                    allow_network_download=getattr(args, "allow_network_download", False),
                )
                acquisition_status = materialized["status"]
        workflow_status = {
            "status": "delivered-with-planning-gap"
            if next_plan_status not in {"not-requested", "accepted"}
            else "lifecycle-segment-delivered",
            "execution_status": terminal["status"],
            "paper_cycle_delivered": True,
            "experience_status": disposition["status"],
            "next_plan_status": next_plan_status,
            "next_plan_rejection_reasons": next_plan_rejections,
            "whole_project_lifecycle_complete": False,
        }
        if acquisition_status is not None:
            workflow_status["resource_status"] = acquisition_status
            if acquisition_status not in {
                "workspace-resources-prepared",
                "no-acquisition-selected",
            }:
                workflow_status["status"] = "delivered-with-resource-gap"
        status_path = output / "WORKFLOW_STATUS.json"
        if status_path.exists() and json.loads(status_path.read_text()) != workflow_status:
            status_path = output / "WORKFLOW_STATUS_RECOVERY.json"
        # Preserve the original snapshots while permitting further genuine state
        # changes (e.g. planning rejection -> resource pending -> resources ready).
        if not status_path.exists() or json.loads(status_path.read_text()) == workflow_status:
            retain(status_path, workflow_status)
        journal = output / "WORKFLOW_STATUS_HISTORY.jsonl"
        history = journal.read_text().splitlines() if journal.exists() else []
        if not history or json.loads(history[-1]) != workflow_status:
            with journal.open("a") as stream:
                stream.write(json.dumps(workflow_status) + "\n")
        current = output / "WORKFLOW_STATUS_CURRENT.json"
        if not current.exists() or json.loads(current.read_text()) != workflow_status:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=output, prefix=".workflow-status-", delete=False
            ) as stream:
                json.dump(workflow_status, stream, indent=2)
                temporary = stream.name
            os.replace(temporary, current)
        publish_cycle_progress(
            root,
            output,
            current,
            status=workflow_status["status"],
            stage="delivery",
        )
        print(json.dumps({**result, "workflow_status": workflow_status}))

"""Continue terminal Native workspace runs without resetting evidence or budgets."""

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.executor.state_handoff import local_decision_count
from scitaste.state.persistence import StateStore


def restore_workspace(
    *,
    project: Path,
    parent: Path,
    output: Path,
    plan_sha256: str,
    report_only: bool = False,
    extra_turns: int = 0,
    resolve_closed_background: bool = False,
    recover_remote: bool = False,
):
    parent, output = parent.resolve(strict=True), output.resolve(strict=True)
    for path in (parent, output):
        path.relative_to(project.resolve(strict=True))
    if parent == output or parent.is_relative_to(output) or output.is_relative_to(parent):
        raise ValueError("Continuation requires separate sibling workspaces")
    contract = json.loads((parent / "CONTRACT.json").read_text())
    terminal = json.loads((parent / "RESULT.json").read_text())
    observed_stop = None
    if report_only and terminal["status"] == "native-workspace-observed-budget-stop":
        from scitaste.executor.native_observed_close import verified_report_stop

        observed_stop = verified_report_stop(parent, contract, terminal)
    terminal_report_closure = None
    if report_only and (parent / "REPORT_ONLY_SESSION_CLOSURE.json").is_file():
        from scitaste.executor.native_terminal_delivery import verified_terminal_report_closure

        terminal_report_closure = verified_terminal_report_closure(parent, contract, terminal)
    statuses = {"native-workspace-interrupted", "native-workspace-budget-exhausted"}
    if recover_remote and contract["plan"].get("remote_workspace"):
        statuses.add("execution-unresolved")
    if extra_turns:
        if not 1 <= extra_turns <= 16 or contract["max_turns"] + extra_turns > 120:
            raise ValueError("Recovery turn extension exceeds bound")
        statuses.add("turn-budget-exhausted")
    if report_only:
        statuses |= {"controller-finished", "turn-budget-exhausted", "experiment-budget-exhausted"}
        if observed_stop:
            statuses.add("native-workspace-observed-budget-stop")
    if terminal["status"] not in statuses or contract["plan_sha256"] != plan_sha256:
        raise ValueError("Source is not an eligible terminal run of the same plan")
    accounting = provider_ledger_accounting(parent / "logs/provider_calls")
    if accounting["unresolved_reservations"]:
        raise ValueError("Observe unresolved provider requests; do not replay them")
    state = StateStore(parent / "loop/state").load()
    history = [
        json.loads(line) for line in (parent / "loop/TRAJECTORY.jsonl").read_text().splitlines()
    ]
    if len(history) != local_decision_count(state):
        raise ValueError("Incomplete post-action checkpoint")
    precommit_recovery = None
    orphan = parent / "loop" / f"decision-{len(history):03d}.json"
    if orphan.exists() and not (recover_remote and contract["plan"].get("remote_workspace")):
        raise ValueError("Observe the uncommitted tool action before continuing")
    if recover_remote and contract["plan"].get("remote_workspace") and orphan.is_file():
        from scitaste.executor.base import ExecutionResult, ExecutionStatus
        from scitaste.schema.decisions import ResearchDecision
        from scitaste.state.persistence import snapshot_id

        decision = ResearchDecision.model_validate_json(orphan.read_bytes())
        action = decision.selected_action
        if (
            decision.state_snapshot_id != snapshot_id(state)
            or action.parameters.get("tool") != "Run Remote"
        ):
            raise ValueError("Uncommitted action does not match the retained remote decision")
        arguments = action.parameters["arguments"]
        signature = {**arguments, "sha256": {}}
        for name in arguments["files"]:
            source = (parent / "workspace" / name).resolve(strict=True)
            source.relative_to(parent / "workspace")
            signature["sha256"][name] = hashlib.sha256(source.read_bytes()).hexdigest()
        identity = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
        directory = parent / "remote_jobs" / identity
        if json.loads((directory / "REQUEST.json").read_text()) != signature:
            raise ValueError("Remote request differs from the uncommitted decision")
        binding = json.loads((directory / "job/BINDING.json").read_text())
        pending = ExecutionResult(
            action_id=action.action_id,
            executor="scitaste-native-remote-workspace",
            status=ExecutionStatus.PLANNED,
            observations=["Recovery projection of an uncommitted action, not original output"],
            data={"source_execution_action_id": Path(binding["remote"]).name},
        )
        history.append(
            {
                "proposal": {"recovered_from_decision": decision.decision_id},
                "selected": action.model_dump(mode="json"),
                "result": pending.model_dump(mode="json"),
            }
        )
        state.decision_history.append(decision)
        precommit_recovery = {
            "decision_sha256": hashlib.sha256(orphan.read_bytes()).hexdigest(),
            "source": str(orphan),
            "original_result_was_uncommitted": True,
        }
    recovery_source, reconciliation = parent, None
    predecessor_count = state.executor_context.get("predecessor_decision_count", 0)
    for index, (row, decision) in enumerate(
        zip(history, state.decision_history[predecessor_count:], strict=True)
    ):
        if (
            recover_remote
            and contract["plan"].get("remote_workspace")
            and index == len(history) - 1
            and row["result"]["status"] == "PLANNED"
            and row["selected"] == decision.selected_action.model_dump(mode="json")
        ):
            from scitaste.executor.remote_workspace_recovery import reconcile_pending_remote

            recovery_source, reconciliation = reconcile_pending_remote(
                parent=parent,
                output=output,
                plan=contract["plan"],
                state=state,
                history=history,
            )
        if (
            row["selected"] != decision.selected_action.model_dump(mode="json")
            or row["result"] != decision.actual_outcome
            or row["result"]["status"] == "PLANNED"
        ):
            raise ValueError("Checkpoint differs from complete execution history")
    closed_sessions = []
    prior_closed = {
        item["observation_sha256"]
        for item in (contract.get("continuation") or {}).get("closed_background_sessions", [])
    }
    for row in history:
        if row["selected"]["parameters"]["tool"] != "TerminalStart":
            continue
        observation = "\n".join(row["result"]["observations"])
        observation_sha = hashlib.sha256(observation.encode()).hexdigest()
        if not resolve_closed_background and observation_sha not in prior_closed:
            raise ValueError("Background sessions require explicit terminal observation")
        match = re.search(r"^pid: ([1-9][0-9]*)$", observation, re.MULTILINE)
        if not match or row["result"]["status"] != "SUCCEEDED":
            raise ValueError("Cannot resolve unknown background-session identity")
        pid = int(match.group(1))
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            closed_sessions.append(
                {
                    "pid": pid,
                    "status": "not-running-on-local-executor-host",
                    "observation_sha256": observation_sha,
                }
            )
        else:
            raise ValueError("Background session remains live; do not continue")
    prior = contract.get("continuation") or {}
    inherited_requests = prior.get("inherited_session_requests", 0)
    unconsumed_requests = []
    session_accounting = terminal.get("accounting")
    if contract.get("model_source") == "assistant-session":
        from scitaste.model_nodes.session_exchange import load_retained_request

        exchange = Path(contract["session_exchange"]).resolve(strict=True)
        exchange.relative_to(parent)
        requests = list(exchange.glob("*.request.json"))
        for request_path in requests:
            request = load_retained_request(request_path)
            response_path = exchange / (request.fingerprint + ".response.json")
            if not response_path.is_file():
                if observed_stop or terminal_report_closure:
                    unconsumed_requests.append(
                        {
                            "request": request_path.relative_to(parent).as_posix(),
                            "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                            "reply_consumed": False,
                        }
                    )
                    continue
                raise ValueError("Resolve pending session requests before terminal continuation")
            if json.loads(response_path.read_text())["request_fingerprint"] != request.fingerprint:
                raise ValueError("Retained session response binding changed")
        inherited_requests += len(requests)
        if observed_stop or terminal_report_closure:
            session_accounting = {
                "source": "assistant-session",
                "calls": 0,
                "api_calls": 0,
                "session_responses": len(requests) - len(unconsumed_requests),
                "pending_session_requests": len(unconsumed_requests),
                "liability_usd": 0,
                "unresolved_reservations": 0,
                "session_cost_usd": None,
                "actual_tokens": None,
                "accounting_origin": "observer inventory, not a native close receipt",
                "cost_semantics": "incremental API liability only; session cost unknown",
            }
        if not report_only and inherited_requests >= contract["plan"]["resource_envelope"].get(
            "max_requests", contract["max_turns"] * 4
        ):
            raise ValueError("No declared session requests remain")
    elif not (parent / "logs/provider_calls").exists():
        raise ValueError("Missing provider ledger")
    elapsed = prior.get("inherited_duration_seconds", 0) + terminal["duration_seconds"]
    # A terminated researcher does not acquire a fresh wall clock while its
    # coordinator diagnoses a failure. Include the offline continuation gap;
    # nested continuations carry this same original lifecycle allocation.
    elapsed = max(
        elapsed,
        prior.get("inherited_duration_seconds", 0)
        + time.time()
        - (parent / "CONTRACT.json").stat().st_mtime,
    )
    if reconciliation:
        elapsed += reconciliation["duration_seconds"]
    if not report_only and elapsed >= contract["plan"]["resource_envelope"]["wall_seconds"]:
        raise ValueError("No declared task time remains")
    files = {}
    for path in (recovery_source / "workspace").rglob("*"):
        if path.is_file():
            path.resolve(strict=True).relative_to(project.resolve(strict=True))
            files[path.relative_to(recovery_source / "workspace").as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    remote_files = {}
    remote_root = recovery_source / "remote_jobs"
    if contract["plan"].get("remote_workspace"):
        if not remote_root.is_dir() or remote_root.is_symlink():
            raise ValueError("Remote-bound continuation needs its original job ledger")
        jobs = sorted(remote_root.glob("*/REQUEST.json"))
        accounted = {
            row["result"]["result_id"]: row["result"]
            for row in history
            if row["selected"]["parameters"]["tool"] == "Run Remote"
            and not row["result"].get("data", {}).get("cost_already_accounted")
            and row["result"].get("data", {}).get("cost_complete") is True
        }
        retained_results = set()
        for request in jobs:
            directory = request.parent
            result_path = directory / "EXECUTION_RESULT.json"
            if not result_path.is_file():
                raise ValueError("Observe unresolved remote jobs before continuing the controller")
            result = json.loads(result_path.read_text())
            retained_results.add(result["result_id"])
            recorded = accounted.get(result["result_id"])
            if (
                result["status"] == "PLANNED"
                or result["data"].get("cost_complete") is not True
                or recorded is None
                or recorded["cost"] != result["cost"]
            ):
                raise ValueError(
                    "Remote outcome/cost is not committed to the controller checkpoint"
                )
            binding = json.loads((directory / "job/BINDING.json").read_text())
            manifest = directory / "job/staging/JOB.json"
            if hashlib.sha256(manifest.read_bytes()).hexdigest() != binding["manifest_sha256"]:
                raise ValueError("Remote job manifest binding changed")
        if retained_results != set(accounted):
            raise ValueError("Committed remote jobs are missing from the retained ledger")
        for path in remote_root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Inherited remote ledger cannot contain symbolic links")
            if path.is_file():
                remote_files[path.relative_to(remote_root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    claims = parent.parent / "continuation_claims"
    claims.mkdir(exist_ok=True)
    key = hashlib.sha256(str(parent).encode()).hexdigest()
    claim_path = claims / (key + ".json")
    claim_binding = {"parent": str(parent), "child": str(output)}
    reused_report_claim = False
    if claim_path.exists():
        # A failed report-only preparation can leave the reservation before
        # delivery. After explicit preservation of the failed child directory,
        # allow preparation into the same empty destination; never fork research
        # execution or overwrite a retained workspace/provider request.
        if (
            not report_only
            or json.loads(claim_path.read_text()) != claim_binding
            or any(output.iterdir())
        ):
            raise ValueError("Continuation is already claimed; preserve/recover its child")
        reused_report_claim = True
    else:
        with claim_path.open("x") as stream:
            json.dump(claim_binding, stream)
    shutil.copytree(recovery_source / "workspace", output / "workspace")
    provider_records = parent / "logs/provider_calls"
    if provider_records.exists():
        shutil.copytree(provider_records, output / "logs/provider_calls")
    if remote_files or contract["plan"].get("remote_workspace"):
        shutil.copytree(remote_root, output / "remote_jobs")
    lineage = {
        "parent": str(parent),
        "parent_result_sha256": hashlib.sha256((parent / "RESULT.json").read_bytes()).hexdigest(),
        "workspace_files": files,
        "inherited_duration_seconds": elapsed,
        "inherited_clock_basis": "original lifecycle wall including offline recovery gap",
        "inherited_turns": len(history),
        "inherited_session_requests": inherited_requests,
        "recovery_excluded_from_original_run_score": True,
        "inherited_api_accounting": accounting,
        **(
            {"inherited_session_accounting": session_accounting}
            if contract.get("model_source") == "assistant-session"
            else {}
        ),
        "historical_prefix_not_new_execution": True,
        "report_only": report_only,
        "reused_report_preparation_claim": reused_report_claim,
        "max_turns": contract["max_turns"] + extra_turns,
        "extra_turns_authorized": extra_turns,
        "closed_background_sessions": closed_sessions,
        "inherited_remote_job_files": remote_files,
        "remote_pending_reconciliation": reconciliation,
        "remote_precommit_recovery": precommit_recovery,
        **(
            {"observed_research_stop": observed_stop, "unconsumed_requests": unconsumed_requests}
            if observed_stop
            else {}
        ),
        **(
            {
                "terminal_report_closure": terminal_report_closure,
                "unconsumed_requests": unconsumed_requests,
            }
            if terminal_report_closure
            else {}
        ),
    }
    return state, history, lineage

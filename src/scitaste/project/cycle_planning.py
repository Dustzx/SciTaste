"""Connect objective planning to the existing Native execution entry.

The planner chooses the task; this module only verifies and forwards its compiled
selection. It never chooses a fallback study or starts another research iteration.
"""

import fcntl
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project.models import validate_entry_id
from scitaste.project.session_recovery import pending_resume_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_plan(root, planning):
    """Use an explicit compiler receipt, never infer a plan by globbing directories."""
    result = json.loads((planning / "RESULT.json").read_text())
    if result["status"] != "accepted":
        return None
    design = json.loads((planning / "DESIGN.json").read_text())
    if result.get("proposal") != design:
        raise ValueError("Planning result differs from its compiled design")
    task, workspace = design.get("task_selection"), design.get("workspace_selection")
    if task and workspace:
        raise ValueError("Ambiguous compiled research selection")
    if task:
        receipt_path = planning / "prepared-task/SELECTION.json"
        if not receipt_path.exists():
            from scitaste.executor.design_task_selection import compile_selected_task

            contract = json.loads((planning / "CONTRACT.json").read_text())
            source = contract["prepared_tasks"][task["task_option_id"]]
            compile_selected_task(
                project=root,
                design_path=planning / "DESIGN.json",
                source_plan=root / source["locator"],
                expected_plan_sha256=source["sha256"],
                output=planning / "prepared-task",
            )
        receipt = json.loads((planning / "prepared-task/SELECTION.json").read_text())
        plan = Path(receipt.get("compiled_plan", planning / "prepared-task/PLAN.json"))
        plan.resolve(strict=True).relative_to(planning.resolve())
        expected = receipt["compiled_plan_sha256"]
        if receipt["selection"] != task:
            raise ValueError("Compiled task differs from model selection")
    elif workspace:
        receipt = json.loads((planning / "provisioned-workspace/PROVISION.json").read_text())
        plan = Path(receipt["plan"]).resolve(strict=True)
        plan.relative_to(planning.resolve())
        expected = receipt["plan_sha256"]
        if receipt["selection"] != workspace:
            raise ValueError("Provisioned workspace differs from model selection")
    else:
        return None
    plan = plan.resolve(strict=True)
    plan.relative_to(root)
    payload = json.loads(plan.read_text())
    if digest(plan) != expected or payload["executor_id"] != "scitaste-native-workspace":
        raise ValueError("Compiled plan changed or is not executable by this Native entry")
    binding = payload["research_design"]
    if binding["sha256"] != digest(planning / "DESIGN.json"):
        raise ValueError("Compiled plan does not bind the accepted design")
    return plan


def prepare_cycle_plan(args):
    root, cycle = args.project.resolve(strict=True), args.output.resolve()
    cycle.relative_to(root)
    validate_entry_id(cycle.name, field_name="cycle identity")
    planning = cycle.with_name(cycle.name + "-planning")
    handoff = cycle.with_name(cycle.name + "-intake")
    if not args.allow_api and not args.session_exchange:
        raise ValueError("Objective planning requires explicit API or session enablement")
    if args.allow_api and args.session_exchange:
        raise ValueError("Choose session assistance or API, not both")
    command = [
        sys.executable,
        "-m",
        "scitaste.project.research_planning",
        "--project",
        str(root),
        "--output",
        str(planning),
        "--objective",
        args.objective,
        "--compile-selection",
    ]
    bound = {}
    if args.research_state:
        from scitaste.executor.state_handoff import load_predecessor

        _, binding = load_predecessor(root, args.research_state)
        source = args.research_state.resolve(strict=True)
        bound[str(source)] = binding["sha256"]
        command.extend(["--evidence", str(source)])
    for name, flag in (
        ("planning_prepared_task", "prepared-task"),
        ("planning_workspace_resources", "workspace-resources"),
        ("planning_evidence", "evidence"),
        ("planning_acquisition_option", "acquisition-option"),
    ):
        for supplied in getattr(args, name):
            path = supplied.resolve(strict=True)
            path.relative_to(root)
            bound[str(path)] = digest(path)
            command.extend(["--" + flag, str(path)])
    for name, flag in (
        ("planning_backend", "backend"),
        ("credentials", "credentials"),
        ("workflow_gaps", "workflow-gaps"),
        ("development_taste_library", "development-taste-library"),
        ("taste_deliberation_profile", "taste-deliberation-profile"),
    ):
        supplied = getattr(args, name)
        if supplied:
            path = supplied.resolve(strict=True)
            command.extend(["--" + flag, str(path)])
            # Never retain credential contents or digest them into project evidence.
            if name != "credentials":
                bound[str(path)] = digest(path)
    if args.session_exchange:
        exchange = args.session_exchange.resolve() / "initial-planning"
        exchange.relative_to(root)
        command.extend(["--session-exchange", str(exchange), "--session-wait-seconds", "0"])
    else:
        command.append("--allow-api")
    handoff.mkdir(parents=True, exist_ok=True)
    with (handoff / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        retain_json(handoff / "CONTRACT.json", {"command": command, "sources": bound})
        if not (planning / "RESULT.json").exists():
            stage = "initial-plan"
            if (handoff / (stage + ".started.json")).exists():
                stage = pending_resume_stage(handoff, planning, command, stage=stage)
            elif planning.exists():
                raise ValueError("Unowned planning directory; do not overwrite it")
            retain_json(handoff / (stage + ".started.json"), {"command": command})
            with (handoff / (stage + ".log")).open("a") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            retain_json(handoff / (stage + ".exit.json"), {"returncode": completed.returncode})
            if completed.returncode:
                raise ValueError("Initial planning stopped; inspect retained intake log")
        if not (planning / "RESULT.json").exists():
            if not (planning / "SESSION_PENDING.json").is_file():
                raise ValueError("Planner returned without a result or explicit pending request")
            status = {
                "status": "awaiting-session-response",
                "stage": "initial-planning",
                "planning": str(planning),
                "execution_started": False,
            }
        else:
            acquisition = prepare_initial_acquisition(
                root,
                planning,
                enabled=args.acquire_planning_resources,
                allow_network_download=args.allow_network_download,
            )
            if acquisition is not None:
                (handoff / "STATUS.json").write_text(json.dumps(acquisition, indent=2))
                print(json.dumps(acquisition))
                return None
            plan = selected_plan(root, planning)
            if plan:
                retain_json(
                    handoff / "SELECTED_PLAN.json",
                    {
                        "plan": str(plan),
                        "plan_sha256": digest(plan),
                        "design_sha256": digest(planning / "DESIGN.json"),
                        "result_sha256": digest(planning / "RESULT.json"),
                        "execution_authorized": False,
                    },
                )
                (handoff / "STATUS.json").write_text(
                    json.dumps(
                        {
                            "status": "prepared-not-executed",
                            "planning": str(planning),
                            "plan": str(plan),
                            "execution_started": False,
                        },
                        indent=2,
                    )
                )
                return plan
            result = json.loads((planning / "RESULT.json").read_text())
            status = {
                "status": "planning-" + result["status"],
                "planning": str(planning),
                "execution_started": False,
                "reason": "no executable Native selection",
                "next_work_item": (result.get("proposal") or {}).get("next_work_item"),
            }
        (handoff / "STATUS.json").write_text(json.dumps(status, indent=2))
        print(json.dumps(status))
        return None


def prepare_initial_acquisition(root, planning, *, enabled, allow_network_download):
    """Finish a selected resource step without authorizing or selecting a study.

    Materialization authority is separate from the immutable model invocation, so
    an operator can enable a retained accepted selection without recalling a model.
    Acquired resources must enter a fresh, explicitly bound planning invocation.
    """
    result = json.loads((planning / "RESULT.json").read_text())
    if result["status"] != "accepted" or not (result.get("proposal") or {}).get(
        "acquisition_selection"
    ):
        return None
    design = json.loads((planning / "DESIGN.json").read_text())
    if result["proposal"] != design:
        raise ValueError("Acquisition design differs from accepted planning result")
    status = {
        "status": "acquisition-awaiting-enablement",
        "planning": str(planning),
        "selection": design["acquisition_selection"],
        "execution_started": False,
        "execution_authorized": False,
        "new_model_calls": 0,
    }
    if not enabled:
        return status
    from scitaste.project.acquisition_selection import materialize_accepted_acquisition

    acquired = materialize_accepted_acquisition(
        project=root,
        planning_run=planning,
        allow_network_download=allow_network_download,
    )
    status.update(status=acquired["status"], acquisition=acquired)
    if acquired["status"] == "workspace-resources-prepared":
        resource = acquired["resource_result"]
        handoff = (root / resource["handoff"]).resolve(strict=True)
        handoff.relative_to(root)
        if digest(handoff) != resource["handoff_sha256"]:
            raise ValueError("Acquired resource handoff changed")
        bundle = json.loads(handoff.read_text()).get("resource_bundle")
        if bundle:
            path = (root / bundle).resolve(strict=True)
            path.relative_to(root)
            status.update(
                workspace_resources=str(path),
                workspace_resources_sha256=digest(path),
                next_step="Supply --planning-workspace-resources to a new objective cycle",
            )
    return status

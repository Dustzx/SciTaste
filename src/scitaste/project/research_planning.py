"""Run one bounded model-backed scientific design from the current project idea."""

import argparse
import fcntl
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.evaluation.development_selection import development_task_eligible
from scitaste.executor import native_support as shared
from scitaste.executor.capability_catalog import design_handoff, planning_capabilities
from scitaste.model_nodes.format_recovery import run_with_format_recovery
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.research_design import ResearchDesignInput, ResearchDesignNode
from scitaste.model_nodes.session_exchange import retain_session_pending
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.cycle_feedback import load_cycle_feedback
from scitaste.project.idea_revision import ProjectIdeaRevisionArtifact
from scitaste.project.paper_feedback import load_paper_feedback
from scitaste.project.research_artifact import register_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--previous-cycle", type=Path, action="append", default=[])
    parser.add_argument("--previous-paper-flow", type=Path, action="append", default=[])
    parser.add_argument(
        "--workflow-gaps",
        type=Path,
        help="Project JSON mapping of capability gaps; enables completeness-first",
    )
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--session-exchange",
        type=Path,
        help="Export input-bound model requests and consume session replies without API calls",
    )
    parser.add_argument("--session-wait-seconds", type=float, default=0)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--development-taste-library", type=Path)
    parser.add_argument("--taste-deliberation-profile", type=Path)
    parser.add_argument("--retry-from", type=Path)
    parser.add_argument(
        "--code-root",
        type=Path,
        help="Optional explicit trusted checkout for legacy adapter inventory",
    )
    parser.add_argument("--pilot-template", type=Path, action="append", default=[])
    parser.add_argument("--prepared-task", type=Path, action="append", default=[])
    parser.add_argument("--workspace-resources", type=Path, action="append", default=[])
    parser.add_argument("--acquisition-option", type=Path, action="append", default=[])
    parser.add_argument("--acquire-selection", action="store_true")
    parser.add_argument("--allow-network-download", action="store_true")
    parser.add_argument("--compile-selection", action="store_true")
    parser.add_argument(
        "--required-comparison-role",
        action="append",
        default=[],
        choices=("external-method", "mechanism-ablation", "validity-control"),
    )
    args = parser.parse_args()
    if not args.allow_api and not args.session_exchange:
        raise ValueError("Explicit API enablement required")
    if args.session_exchange and (args.allow_api or args.retry_from):
        raise ValueError("Session mode cannot enable API calls or inherit provider retries")
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    runtime = ProjectRuntime(root.parent.parent)
    current = inspect_current_idea_revision(runtime, root.name)
    if current.current_binding is None or not current.artifact_verified:
        raise ValueError("Verified registered idea required")
    binding = current.current_binding
    idea = ProjectIdeaRevisionArtifact.model_validate_json(
        (root / binding.record_locator).read_bytes()
    )
    evidence, sources = {}, {}
    from scitaste.project.planning_evidence import evidence_text

    for index, supplied in enumerate(args.evidence):
        path = supplied.resolve(strict=True)
        path.relative_to(root)
        raw = path.read_bytes()
        key = f"evidence-{index:02d}"
        evidence[key] = evidence_text(
            raw, project_id=root.name, locator=path.relative_to(root).as_posix()
        )
        sources[key] = {
            "locator": str(path.relative_to(root)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            **(
                {
                    "projection": "canonical-state-planning-projection",
                    "projection_sha256": hashlib.sha256(evidence[key].encode()).hexdigest(),
                    "complete_observations_visible": False,
                }
                if len(raw) > 60000
                else {}
            ),
        }
    capabilities, capability_sources = planning_capabilities(args.code_root)
    from scitaste.executor.design_task_selection import compile_selected_task, task_option

    task_options, task_sources = {}, {}
    from scitaste.executor.workspace_provision import (
        compile_workspace_selection,
        resource_option,
    )

    workspace_options, workspace_sources = {}, {}
    from scitaste.project.acquisition_selection import (
        acquisition_option,
        materialize_accepted_acquisition,
    )

    acquisition_options, acquisition_sources = {}, {}
    for path in args.acquisition_option:
        if path.stem in acquisition_options:
            raise ValueError("Acquisition option IDs must be unique")
        acquisition_options[path.stem], acquisition_sources[path.stem] = acquisition_option(
            root, path
        )
    for path in args.workspace_resources:
        identity = path.stem
        if identity in workspace_options:
            raise ValueError("Workspace resource option IDs must be unique")
        workspace_options[identity], workspace_sources[identity] = resource_option(root, path)
    for path in args.prepared_task:
        identity = path.resolve().parent.name
        if identity in task_options:
            raise ValueError("Prepared task option IDs must be unique")
        task_options[identity], task_sources[identity] = task_option(root, path)
    cycle_feedback = []
    for supplied in args.previous_cycle:
        feedback = load_cycle_feedback(root, supplied, current_idea_sha256=binding.artifact_sha256)
        if any(item["cycle"] == feedback["cycle"] for item in cycle_feedback):
            raise ValueError("Duplicate previous cycle")
        cycle_feedback.append(feedback)
        key = f"previous-cycle-{len(cycle_feedback):02d}"
        evidence[key] = json.dumps(feedback)
        sources[key] = {"cycle": feedback["cycle"], "sources": feedback["sources"]}
    from scitaste.evaluation.prelaunch import ExperimentPrelaunchManifest

    paper_feedback = []
    for supplied in args.previous_paper_flow:
        feedback = load_paper_feedback(root, supplied)
        if any(row["paper_flow"] == feedback["paper_flow"] for row in paper_feedback):
            raise ValueError("Duplicate previous paper flow")
        paper_feedback.append(feedback)
        key = f"previous-paper-flow-{len(paper_feedback):02d}"
        evidence[key] = json.dumps(feedback)
        sources[key] = {
            "paper_flow": feedback["paper_flow"],
            "sources": feedback["sources"],
            "review_packet_sha256": feedback["review_packet_sha256"],
            "report_sha256": sorted({row["report_sha256"] for row in feedback["concerns"]}),
        }
    options, templates = {}, {}
    for path in args.pilot_template:
        manifest = ExperimentPrelaunchManifest.model_validate(yaml.safe_load(path.read_text()))
        if manifest.study_scope != "pilot" or manifest.manifest_id in templates:
            raise ValueError("Unique pilot protocol templates required")
        options[manifest.manifest_id] = manifest.model_dump(mode="json")
        templates[manifest.manifest_id] = {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    # Expose selection eligibility explicitly; a template may exist while none
    # of its tasks are permitted by this development compiler's narrower policy.
    for option in options.values():
        option["compiler_selection"] = {
            "eligible_task_ids": [
                t["task_id"]
                for t in option["tasks"]
                if development_task_eligible(t, study_scope=option["study_scope"])
            ],
            "executor_ids_are_separate": sorted(capabilities),
            "no_eligible_tasks_action": (
                "Return execution_selection=null; do not relabel task split or isolation flags"
            ),
        }
    workflow_gaps = {}
    current_gaps = root / "docs/WORKFLOW_GAPS_CURRENT.json"
    gap_path = args.workflow_gaps or (
        current_gaps if current_gaps.is_file() else root / "docs/WORKFLOW_GAPS.json"
    )
    if args.workflow_gaps or gap_path.is_file():
        path = gap_path.resolve(strict=True)
        path.relative_to(root)
        raw = path.read_bytes()
        workflow_gaps = json.loads(raw)
        if not isinstance(workflow_gaps, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) or not value.strip()
            for key, value in workflow_gaps.items()
        ):
            raise ValueError("Workflow gaps must map identifiers to nonempty descriptions")
        sources["workflow-gaps"] = {
            "locator": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    from scitaste.project.planning_intervention import current_control, record_response

    user_control = current_control(root)
    packet = ResearchDesignInput(
        scientific_reasoning_required=True,
        user_intervention=user_control,
        idea_sha256=binding.artifact_sha256,
        idea=idea.model_dump(mode="json"),
        capabilities=capabilities,
        evidence=evidence,
        objective=args.objective,
        planning_priority="completeness-first" if workflow_gaps else "scientific-design",
        workflow_gaps=workflow_gaps,
        required_comparison_roles=tuple(args.required_comparison_role),
        protocol_options=options,
        task_options=task_options,
        workspace_resource_options=workspace_options,
        acquisition_options=acquisition_options,
    )
    if args.session_exchange:
        from scitaste.model_nodes.session_exchange import (
            SessionResponsePending,
            SessionStructuredBackend,
            retain_json,
        )

        args.session_exchange.resolve().relative_to(root)
        config = SimpleNamespace(provider="assistant-session", model="session-authored")
    else:
        config = shared.load_structured_openai_compatible_config(args.backend)
        shared._bind_credential(
            args.credentials or root.parent.parent / "resources/access/credentials.env",
            config.api_key_env,
        )
    retry_binding = None
    from scitaste.taste.research_tool_deliberation import workspace_taste_binding

    taste_binding, taste_profile = workspace_taste_binding(
        args.development_taste_library, args.taste_deliberation_profile
    )
    if taste_profile and (taste_profile.provider, taste_profile.model) != (
        config.provider,
        config.model,
    ):
        raise ValueError("Planning Taste must use the same configured backend")
    if taste_profile and args.allow_api and not taste_profile.live_execution_permitted:
        raise ValueError("Planning Taste profile does not permit live execution")
    if taste_profile and args.retry_from:
        raise ValueError(
            "Taste-configured rejected planning needs a new bound plan, not legacy retry"
        )
    max_calls = 3 if taste_profile else 2
    if args.retry_from:
        parent = args.retry_from.resolve(strict=True)
        parent.relative_to(root)
        previous = json.loads((parent / "RESULT.json").read_text())
        previous_contract = json.loads((parent / "CONTRACT.json").read_text())
        previous_input = ResearchDesignInput.model_validate_json(
            (parent / "INPUT.json").read_bytes()
        )
        mutable = {"workflow_gaps", "planning_priority", "prior_rejection_reasons"}
        if (
            previous.get("status") != "rejected"
            or previous_contract.get("retry_from")
            or previous_input.model_dump(exclude=mutable) != packet.model_dump(exclude=mutable)
            or previous["request"]["expected_backend"] != config.provider
            or previous["request"]["expected_model"] != config.model
        ):
            raise ValueError(
                "Planning retry must retain original idea, evidence, objective and provider"
            )
        inherited = provider_ledger_accounting(parent / "logs/provider_calls")
        if (
            inherited["unresolved_reservations"]
            or inherited["liability_usd"] >= 3
            or inherited["calls"] >= 2
        ):
            raise ValueError("Planning retry has unresolved or exhausted original budget")
        packet = packet.model_copy(
            update={"prior_rejection_reasons": tuple(previous["rejection_reasons"])}
        )
        retry_binding = {
            "parent": str(parent),
            "result_sha256": hashlib.sha256((parent / "RESULT.json").read_bytes()).hexdigest(),
            "inherited_accounting": inherited,
            "changed_input_fields_allowed": sorted(mutable),
            "budget_extension": False,
        }
        max_calls = 2
    output.mkdir(parents=True, exist_ok=bool(args.session_exchange))
    # Held until this invocation returns, including while awaiting a session reply.
    planning_lock = (output / ".planning.lock").open("a")
    fcntl.flock(planning_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    write = retain_json if args.session_exchange else shared.write_new
    if retry_binding:
        with (parent / "PLANNING_RETRY_CLAIM.json").open("x") as stream:
            json.dump({"child": str(output)}, stream)
        shutil.copytree(parent / "logs/provider_calls", output / "logs/provider_calls")
    write(output / "PLANNING_CONTEXT.json", packet.model_dump(mode="json"))
    if cycle_feedback:
        write(output / "CYCLE_FEEDBACK.json", {"cycles": cycle_feedback})
    if paper_feedback:
        write(output / "PAPER_FEEDBACK.json", {"paper_flows": paper_feedback})
    write(
        output / "CONTRACT.json",
        {
            "idea_revision": binding.model_dump(mode="json"),
            "evidence": sources,
            "user_intervention": user_control.model_dump(mode="json") if user_control else None,
            "capability_sources": capability_sources,
            "protocol_templates": templates,
            "prepared_tasks": task_sources,
            "workspace_resources": workspace_sources,
            **({"development_taste": taste_binding} if taste_binding else {}),
            **({"acquisition_options": acquisition_sources} if acquisition_sources else {}),
            "max_calls": max_calls,
            "max_api_liability_usd": 3,
            "execution_authorized": False,
            **(
                {"session_exchange": str(args.session_exchange.resolve())}
                if args.session_exchange
                else {}
            ),
            **({"retry_from": retry_binding} if retry_binding else {}),
        },
    )
    bridge = (
        None
        if args.session_exchange
        else MLAgentBenchProviderBridge(
            config=config,
            log_root=output / "logs",
            max_calls=max_calls,
            max_cost_usd=3,
            max_output_tokens=8192,
            max_request_bytes=180000,
            transport=shared.RecordedTransport(output / "provider.jsonl"),
        )
    )
    node = ResearchDesignNode()
    # Session transport uses UTF-8 byte bounds, not a measured tokenizer count.
    # A structured design + reasoning frame should not be restricted to 8 KB
    # just because the API path permits 8192 generated tokens.
    output_admission = 32000 if args.session_exchange else 8192
    node_kwargs = dict(
        context=NodeContext(
            project_id=root.name,
            stage="EXPERIMENT_DESIGN",
            state_snapshot_id=binding.artifact_sha256,
            cumulative_api_cost_usd=0,
            evidence_ids=list(evidence),
        ),
        policy=NodePolicy(
            policy_id="project-research-design-v1",
            enabled=True,
            allowed_node_names=[node.node_name],
            expected_backend=config.provider,
            expected_model=config.model,
            max_api_cost_usd=3,
            max_request_bytes=180000,
            max_input_tokens=180000,
            max_output_tokens=output_admission,
            max_total_tokens=180000 + output_admission,
        ),
        backend=(
            SessionStructuredBackend(
                args.session_exchange,
                wait_seconds=args.session_wait_seconds,
                max_requests=max_calls,
            )
            if args.session_exchange
            else SharedLedgerStructuredBackend(bridge, max_output_tokens=8192)
        ),
        request_id="research-design-" + binding.artifact_sha256[:16],
    )
    if args.session_exchange:
        if (output / "RESULT.json").exists():
            raise ValueError("Session planning already has a terminal result; use its handoff")
        try:
            if taste_profile:
                from scitaste.project.planning_taste import consult_planning_taste

                advice = consult_planning_taste(
                    packet=packet,
                    library=args.development_taste_library,
                    profile=taste_profile,
                    binding=taste_binding,
                    backend=node_kwargs["backend"],
                    output=output,
                    project_id=root.name,
                )
                packet = packet.model_copy(update={"planning_taste": advice})
            write(output / "INPUT.json", packet.model_dump(mode="json"))
            result = node.run(packet, **node_kwargs)
        except SessionResponsePending as exc:
            retain_session_pending(output, str(exc))
            print(json.dumps({"status": "awaiting-session-response", "request": str(exc)}))
            return
    else:
        if taste_profile:
            from scitaste.project.planning_taste import consult_planning_taste

            advice = consult_planning_taste(
                packet=packet,
                library=args.development_taste_library,
                profile=taste_profile,
                binding=taste_binding,
                backend=node_kwargs["backend"],
                output=output,
                project_id=root.name,
            )
            packet = packet.model_copy(update={"planning_taste": advice})
        write(output / "INPUT.json", packet.model_dump(mode="json"))
        result = run_with_format_recovery(node, packet, output=output, **node_kwargs)
    shared.write_new(output / "RESULT.json", result.model_dump(mode="json"))
    record_response(root, output, user_control, result)
    accounting = (
        {
            "source": "assistant-session",
            "api_calls": 0,
            "session_cost_usd": None,
            "actual_input_tokens": None,
            "actual_output_tokens": None,
        }
        if args.session_exchange
        else provider_ledger_accounting(bridge.records)
    )
    shared.write_new(
        output
        / ("SESSION_ACCOUNTING.json" if args.session_exchange else "PROVIDER_ACCOUNTING.json"),
        accounting,
    )
    if result.status.value == "accepted" and result.proposal:
        shared.write_new(output / "DESIGN.json", result.proposal.model_dump(mode="json"))
        shared.write_new(
            output / "EXECUTION_HANDOFF.json",
            design_handoff(
                result.proposal,
                design_sha256=hashlib.sha256((output / "DESIGN.json").read_bytes()).hexdigest(),
                capabilities=capability_sources,
            ),
        )
    register_artifact(
        project=root,
        artifact=output / "RESULT.json",
        provider=config.provider,
        model=config.model,
        condition="project-research-design-proposal",
        status="design-" + result.status.value,
    )
    if (
        result.status.value == "accepted"
        and result.proposal
        and result.proposal.acquisition_selection
    ):
        selection = result.proposal.acquisition_selection
        selected_binding = acquisition_sources[selection.option_id]
        handoff = {
            "selection": selection.model_dump(mode="json"),
            "binding": selected_binding,
            "execution_authorized": False,
        }
        shared.write_new(output / "ACQUISITION_HANDOFF.json", handoff)
        if args.acquire_selection:
            materialize_accepted_acquisition(
                project=root,
                planning_run=output,
                allow_network_download=args.allow_network_download,
            )
    if args.compile_selection and result.status.value == "accepted" and result.proposal:
        workspace_selection = result.proposal.workspace_selection
        if workspace_selection is not None:
            compile_workspace_selection(
                project=root,
                design_path=output / "DESIGN.json",
                resource_binding=workspace_sources[workspace_selection.resource_option_id],
                output=output / "provisioned-workspace",
            )
        task_selection = result.proposal.task_selection
        if task_selection is not None:
            task_source = task_sources[task_selection.task_option_id]
            compile_selected_task(
                project=root,
                design_path=output / "DESIGN.json",
                source_plan=root / task_source["locator"],
                expected_plan_sha256=task_source["sha256"],
                output=output / "prepared-task",
            )
        selection = result.proposal.execution_selection
        if selection is not None:
            template = templates[selection.template_id]
            if (
                hashlib.sha256(Path(template["path"]).read_bytes()).hexdigest()
                != template["sha256"]
            ):
                raise ValueError("Protocol template changed during planning")
            shared.write_new(
                output / "EXECUTION_SELECTION.json",
                selection.model_dump(mode="json", exclude={"template_id", "study_id"}),
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.compile_design_task_plan",
                    "--project",
                    str(root),
                    "--design",
                    str(output / "DESIGN.json"),
                    "--study-id",
                    selection.study_id,
                    "--template",
                    template["path"],
                    "--selection",
                    str(output / "EXECUTION_SELECTION.json"),
                    "--output",
                    str(output / "compiled"),
                ],
                check=True,
            )
    print(
        json.dumps(
            {
                "status": result.status.value,
                "accounting": accounting,
                "scientific_adequacy_established": False,
                "execution_authorized": False,
            }
        )
    )


if __name__ == "__main__":
    main()

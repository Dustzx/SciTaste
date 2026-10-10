"""Expose bounded acquisition options and materialize model-selected item IDs."""

import fcntl
import json
from pathlib import Path

from scitaste.evaluation.acquisition import load_dataset_acquisition_request
from scitaste.project.acquired_assets import digest
from scitaste.project.resource_acquisition import acquire_workspace_resources


def acquisition_option(project, path):
    root = project.resolve(strict=True)
    path = path.resolve(strict=True)
    path.relative_to(root)
    spec = json.loads(path.read_text())
    if set(spec) != {"request", "workspace_root", "resource_template", "role", "use_constraints"}:
        raise ValueError("Acquisition option requires exact source, template, role and constraints")
    request = (root / spec["request"]).resolve(strict=True)
    request.relative_to(root)
    template = (root / spec["resource_template"]).resolve(strict=True)
    template.relative_to(root)
    workspace = (root / spec["workspace_root"]).resolve(strict=True)
    root.relative_to(workspace)
    req = load_dataset_acquisition_request(request).request
    if req.project_id != root.name or spec["role"] not in {"reference", "data", "starter-code"}:
        raise ValueError("Acquisition option project or role mismatch")
    if not spec["use_constraints"].strip():
        raise ValueError("Acquisition use constraints cannot be empty")
    option = {
        "purpose": req.purpose,
        "claim_boundary": req.claim_boundary,
        "maximum_download_bytes": req.maximum_total_bytes,
        "role": spec["role"],
        "use_constraints": spec["use_constraints"],
        "receipt_present": (workspace / req.destination_root)
        .parent.joinpath("RECEIPT.json")
        .is_file(),
        "items": {
            item.item_id: {
                "source_url": item.source_url,
                "source_revision": item.source_revision,
                "license_identifier": item.license_identifier,
                "license_scope": item.license_scope,
                "license_status": item.license_status.value,
            }
            for item in req.items
        },
        "execution_authorized": False,
    }
    binding = {
        "locator": path.relative_to(root).as_posix(),
        "sha256": digest(path),
        "request_sha256": digest(request),
        "resource_template_sha256": digest(template),
    }
    return option, binding


def materialize_acquisition_selection(
    *, project, selection, binding, output, allow_network_download=False
):
    root = project.resolve(strict=True)
    option, current = acquisition_option(root, root / binding["locator"])
    if current != binding or selection.option_id != Path(binding["locator"]).stem:
        raise ValueError("Acquisition option changed since planning")
    if set(selection.item_ids) - option["items"].keys():
        raise ValueError("Selected acquisition items are outside the declared option")
    spec = json.loads((root / binding["locator"]).read_text())
    return acquire_workspace_resources(
        project=root,
        workspace_root=root / spec["workspace_root"],
        request=root / spec["request"],
        output=output,
        items=list(selection.item_ids),
        use_constraints=spec["use_constraints"],
        resource_template=root / spec["resource_template"],
        role=spec["role"],
        allow_network_download=allow_network_download,
    )


def materialize_accepted_acquisition(*, project, planning_run, allow_network_download=False):
    """Resume only resource work from a retained accepted design; no model call."""
    from scitaste.model_nodes.research_design import ResearchDesignProposal

    root = project.resolve(strict=True)
    run = planning_run.resolve(strict=True)
    run.relative_to(root)
    result = json.loads((run / "RESULT.json").read_text())
    contract = json.loads((run / "CONTRACT.json").read_text())
    design = ResearchDesignProposal.model_validate_json((run / "DESIGN.json").read_bytes())
    if (
        result["status"] != "accepted"
        or ResearchDesignProposal.model_validate(result["proposal"]) != design
    ):
        raise ValueError("Resource preparation requires the unchanged accepted design")
    selection = design.acquisition_selection
    if selection is None:
        return {"status": "no-acquisition-selected", "execution_authorized": False}
    binding = contract["acquisition_options"][selection.option_id]
    descriptor = {
        "selection": selection.model_dump(mode="json"),
        "binding": binding,
        "execution_authorized": False,
    }
    with (run / ".acquisition.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handoff = run / "ACQUISITION_HANDOFF.json"
        if handoff.exists():
            retained = json.loads(handoff.read_text())
            if any(retained.get(k) != v for k, v in descriptor.items()):
                raise ValueError("Acquisition handoff changed from accepted selection")
        else:
            with handoff.open("x") as stream:
                json.dump(descriptor, stream, indent=2)
        journal = run / "ACQUISITION_OUTCOMES.jsonl"

        def record(value):
            previous = journal.read_text().splitlines() if journal.exists() else []
            if not previous or json.loads(previous[-1]) != value:
                with journal.open("a") as stream:
                    stream.write(json.dumps(value) + "\n")

        try:
            resource = materialize_acquisition_selection(
                project=root,
                selection=selection,
                binding=binding,
                output=run / (run.name + "-acquisition"),
                allow_network_download=allow_network_download,
            )
        except Exception as exc:
            record(
                {
                    "status": "resource-materialization-interrupted",
                    "error_type": type(exc).__name__,
                    "new_model_calls": 0,
                }
            )
            raise
        outcome = {
            "status": resource["status"],
            "resource_result": resource,
            "design_sha256": digest(run / "DESIGN.json"),
            "accepted_result_sha256": digest(run / "RESULT.json"),
            "new_model_calls": 0,
            "execution_authorized": False,
        }
        record(outcome)
        if resource["status"] == "workspace-resources-prepared":
            terminal = run / "ACQUISITION_RESULT.json"
            if terminal.exists():
                if json.loads(terminal.read_text()) != outcome:
                    raise ValueError("Completed acquisition result changed")
            else:
                with terminal.open("x") as stream:
                    json.dump(outcome, stream, indent=2)
        return outcome


def configure_resume_parser(parser):
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--planning-run", type=Path, required=True)
    parser.add_argument("--allow-network-download", action="store_true")
    parser.set_defaults(handler=handle_resume)
    return parser


def handle_resume(args):
    print(
        json.dumps(
            materialize_accepted_acquisition(
                project=args.project,
                planning_run=args.planning_run,
                allow_network_download=args.allow_network_download,
            )
        )
    )

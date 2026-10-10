"""Bounded acquisition-to-workspace scheduling using the existing downloader."""

import argparse
import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.evaluation.acquisition import (
    approve_dataset_acquisition_request,
    load_dataset_acquisition_request,
    materialize_dataset_acquisition,
    save_dataset_acquisition_request,
)
from scitaste.project.acquired_assets import digest, prepare_acquired_assets
from scitaste.project.research_artifact import register_artifact


def acquire_workspace_resources(
    *,
    project,
    workspace_root,
    request,
    output,
    items,
    use_constraints,
    resource_template=None,
    role="reference",
    allow_network_download=False,
    maximum_download_bytes=10_000_000_000,
):
    root, workspace = project.resolve(strict=True), workspace_root.resolve(strict=True)
    root.relative_to(workspace)
    request = request.resolve(strict=True)
    request.relative_to(root)
    output = output.resolve()
    output.relative_to(root)
    parsed = load_dataset_acquisition_request(request)
    specification = parsed.request
    if specification.project_id != root.name:
        raise ValueError("Resource request belongs to another project")
    known_items = {item.item_id for item in specification.items}
    if not items or len(set(items)) != len(items) or set(items) - known_items:
        raise ValueError("Select unique items declared in the acquisition request")
    if not use_constraints.strip() or role not in {"reference", "data", "starter-code"}:
        raise ValueError("Explicit resource role and use constraints are required")
    if not 0 < maximum_download_bytes <= 10_000_000_000:
        raise ValueError("Automatic download allowance must be within 10 GB")
    if specification.maximum_total_bytes > maximum_download_bytes:
        raise ValueError("Request exceeds the explicit acquisition allowance")
    transaction = (workspace / specification.destination_root).resolve().parent
    transaction.relative_to(root)
    receipt = transaction / "RECEIPT.json"
    if resource_template:
        resource_template = resource_template.resolve(strict=True)
        resource_template.relative_to(root)
    contract = {
        "request_sha256": parsed.file_sha256,
        "project": str(root),
        "workspace_root": str(workspace),
        "items": sorted(items),
        "role": role,
        "use_constraints": use_constraints,
        "resource_template_sha256": digest(resource_template) if resource_template else None,
        "maximum_download_bytes": maximum_download_bytes,
        "maximum_attempts": 3,
        "execution_authorized": False,
    }
    output.mkdir(parents=True, exist_ok=True)

    def retain(path, value):
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise ValueError("Resource acquisition binding changed")
        else:
            with path.open("x") as stream:
                json.dump(value, stream, indent=2)

    def register(result):
        retain(output / "RESULT.json", result)
        register_artifact(
            project=root,
            artifact=output / "RESULT.json",
            provider="resource-acquisition",
            model="bounded-handoff",
            condition="acquisition-to-workspace",
            status=result["status"],
        )
        return result

    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        retain(output / "CONTRACT.json", contract)
        if (output / "RESULT.json").exists():
            result = json.loads((output / "RESULT.json").read_text())
            source = root / result["handoff"]
            if digest(source) != result["handoff_sha256"]:
                raise ValueError("Resource handoff changed")
            if digest(root / result["receipt"]) != result["receipt_sha256"]:
                raise ValueError("Acquisition receipt changed")
            handoff = json.loads(source.read_text())
            manifest = root / handoff["manifest"]
            if digest(manifest) != handoff["manifest_sha256"]:
                raise ValueError("Resource asset manifest changed")
            from scitaste.executor.workspace_task import asset_bindings

            files = asset_bindings(root, manifest)
            if {k: v["sha256"] for k, v in files.items()} != {
                k: v["sha256"] for k, v in handoff["sources"].items()
            }:
                raise ValueError("Prepared resource bytes changed")
            return register(result)
        if not receipt.exists() and not allow_network_download:
            return {
                "status": "awaiting-download-enablement",
                "new_downloads": 0,
                "execution_authorized": False,
            }
        attempts = sorted(output.glob("attempt-*.started.json"))
        if len(attempts) >= 3:
            raise ValueError("Acquisition attempts exhausted; retained failures require diagnosis")
        index = len(attempts) + 1
        retain(
            output / f"attempt-{index}.started.json",
            {
                "network_enabled": allow_network_download,
                "reusing_receipt": receipt.exists(),
            },
        )
        try:
            downloaded = False
            if not receipt.exists():
                approved = specification
                if not approved.approval.approved:
                    approved = approve_dataset_acquisition_request(
                        approved,
                        confirmed_request_sha256=approved.request_sha256,
                        approved_by="explicit-cli-bounded-download",
                        approved_at=datetime.now(UTC),
                    )
                    approved_path = output / "APPROVED_REQUEST.yaml"
                    if not approved_path.exists():
                        save_dataset_acquisition_request(approved, approved_path)
                    else:
                        approved = load_dataset_acquisition_request(approved_path).request
                materialize_dataset_acquisition(
                    approved,
                    workspace_root=workspace,
                    confirmed_request_sha256=approved.request_sha256,
                    allow_network_download=True,
                )
                downloaded = True
            handoff = output / f"{output.name}-assets-{index:02d}"
            prepare_acquired_assets(
                project=root,
                request=request,
                receipt=receipt,
                output=handoff,
                items=items,
                use_constraints=use_constraints,
                resource_template=resource_template,
                role=role,
            )
            result = {
                "status": "workspace-resources-prepared",
                "handoff": (handoff / "RESULT.json").relative_to(root).as_posix(),
                "handoff_sha256": digest(handoff / "RESULT.json"),
                "receipt": receipt.relative_to(root).as_posix(),
                "receipt_sha256": digest(receipt),
                "downloaded_this_attempt": downloaded,
                "experiment_execution_authorized": False,
                "authorizes_ingestion": False,
            }
            retain(output / f"attempt-{index}.result.json", result)
            return register(result)
        except Exception as exc:
            retain(
                output / f"attempt-{index}.error.json",
                {
                    "status": "acquisition-or-handoff-interrupted",
                    "error_type": type(exc).__name__,
                    "receipt_present": receipt.is_file(),
                    "automatic_retry": False,
                },
            )
            raise


def configure_parser(parser):
    for key in ("project", "workspace-root", "request", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--item", dest="items", action="append", required=True)
    parser.add_argument("--use-constraints", required=True)
    parser.add_argument("--resource-template", type=Path)
    parser.add_argument(
        "--role", choices=("reference", "data", "starter-code"), default="reference"
    )
    parser.add_argument("--allow-network-download", action="store_true")
    parser.add_argument("--maximum-download-bytes", type=int, default=10_000_000_000)
    parser.set_defaults(handler=handle)
    return parser


def handle(args):
    keys = (
        "project",
        "workspace_root",
        "request",
        "output",
        "items",
        "use_constraints",
        "resource_template",
        "role",
        "allow_network_download",
        "maximum_download_bytes",
    )
    print(json.dumps(acquire_workspace_resources(**{k: getattr(args, k) for k in keys})))


if __name__ == "__main__":
    handle(configure_parser(argparse.ArgumentParser(description=__doc__)).parse_args())

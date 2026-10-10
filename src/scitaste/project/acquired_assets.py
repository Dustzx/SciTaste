"""Connect completed acquisition receipts to declared Native workspace resources.

Preparation only: does not download, unpack, ingest, select formal tasks, or execute.
"""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.acquisition import (
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.executor.workspace_task import asset_bindings
from scitaste.project.research_artifact import register_artifact


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_acquired_assets(
    *,
    project,
    request,
    receipt,
    output,
    items,
    use_constraints,
    resource_template=None,
    role="reference",
):
    root = project.resolve(strict=True)
    request, receipt = request.resolve(strict=True), receipt.resolve(strict=True)
    output = output.resolve()
    for path in (request, receipt, output):
        path.relative_to(root)
    if not items or len(set(items)) != len(items) or not use_constraints.strip():
        raise ValueError("Select unique acquired items with explicit use constraints")
    prefixes = {"reference": "references", "data": "data", "starter-code": "code"}
    if role not in prefixes:
        raise ValueError("Unknown workspace asset role")
    req = load_dataset_acquisition_request(request)
    got = load_dataset_acquisition_receipt(receipt)
    if (
        req.request.project_id != root.name
        or got.receipt.request_sha256 != req.request.request_sha256
        or got.receipt.request_id != req.request.request_id
        or got.receipt.destination_root != req.request.destination_root
    ):
        raise ValueError("Acquisition request/receipt belongs to another project or transaction")
    requests = {item.item_id: item for item in req.request.items}
    acquired = {item.item_id: item for item in got.receipt.items}
    if set(items) - (requests.keys() & acquired.keys()):
        raise ValueError("Requested asset was not acquired; no implicit download")
    raw = (receipt.parent / "raw").resolve(strict=True)
    raw.relative_to(root)
    if raw.parent.name != req.request.request_id:
        raise ValueError("Raw directory is not owned by this acquisition")
    files, sources = {}, {}
    for item_id in items:
        original, actual = requests[item_id], acquired[item_id]
        if original.license_status.value != "verified" or (
            original.source_url,
            original.source_revision,
            original.destination,
        ) != (actual.source_url, actual.source_revision, actual.destination):
            raise ValueError("Acquisition source or license scope is not established")
        source = (raw / actual.destination).resolve(strict=True)
        source.relative_to(raw)
        if source.stat().st_size != actual.size_bytes or digest(source) != actual.sha256:
            raise ValueError("Acquired bytes changed")
        target = f"{prefixes[role]}/{req.request.request_id}/{actual.destination}"
        constraints = (
            use_constraints.strip()
            + "\nSource license: "
            + original.license_identifier
            + "; scope: "
            + original.license_scope
            + "\nAcquisition claim boundary: "
            + req.request.claim_boundary
            + "\nPreparation does not authorize ingestion, formal-task selection, or execution."
        )
        files[target] = {
            "locator": source.relative_to(root).as_posix(),
            "role": role,
            "use_constraints": constraints,
        }
        sources[target] = {
            "item_id": item_id,
            "sha256": actual.sha256,
            "source_url": actual.source_url,
            "source_revision": actual.source_revision,
            "license_identifier": original.license_identifier,
            "license_scope": original.license_scope,
        }
    template = None
    if resource_template:
        resource_template = resource_template.resolve(strict=True)
        resource_template.relative_to(root)
        template = json.loads(resource_template.read_text())
    output.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, indent=2)

    save("ASSETS.json", {"files": files})
    asset_bindings(root, output / "ASSETS.json")
    if template is not None:
        save(
            "WORKSPACE_RESOURCES.json",
            {
                **template,
                "assets": (output / "ASSETS.json").relative_to(root).as_posix(),
            },
        )
        from scitaste.executor.workspace_provision import resource_option

        resource_option(root, output / "WORKSPACE_RESOURCES.json")
    result = {
        "status": "acquired-assets-prepared",
        "project_id": root.name,
        "request": request.relative_to(root).as_posix(),
        "request_sha256": req.file_sha256,
        "receipt": receipt.relative_to(root).as_posix(),
        "receipt_sha256": got.file_sha256,
        "manifest": (output / "ASSETS.json").relative_to(root).as_posix(),
        "manifest_sha256": digest(output / "ASSETS.json"),
        "sources": sources,
        "resource_template_sha256": digest(resource_template) if resource_template else None,
        "resource_bundle": (output / "WORKSPACE_RESOURCES.json").relative_to(root).as_posix()
        if template is not None
        else None,
        "authorizes_ingestion": False,
        "execution_authorized": False,
        "new_downloads": 0,
        "new_api_calls": 0,
        "new_experiments": 0,
    }
    save("RESULT.json", result)
    register_artifact(
        project=root,
        artifact=output / "RESULT.json",
        provider="retained-acquisition",
        model="pinned-source",
        condition="acquisition-to-workspace-assets",
        status=result["status"],
    )
    return result


def configure_parser(parser):
    for key in ("project", "request", "receipt", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--item", dest="items", action="append", required=True)
    parser.add_argument("--use-constraints", required=True)
    parser.add_argument("--resource-template", type=Path)
    parser.add_argument(
        "--role", choices=("reference", "data", "starter-code"), default="reference"
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args):
    keys = (
        "project",
        "request",
        "receipt",
        "output",
        "items",
        "use_constraints",
        "resource_template",
        "role",
    )
    print(json.dumps(prepare_acquired_assets(**{key: getattr(args, key) for key in keys})))


def main():
    handle(configure_parser(argparse.ArgumentParser(description=__doc__)).parse_args())


if __name__ == "__main__":
    main()

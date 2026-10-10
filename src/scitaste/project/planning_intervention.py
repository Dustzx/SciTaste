"""Bridge published UI intent to Native planning without granting execution authority."""

import hashlib
import json

from scitaste.generative_ui.planning_directive import (
    load_latest_planning_directive,
    planning_control_from_publication,
)
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project import ProjectRuntime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_control(root):
    publication = load_latest_planning_directive(ProjectRuntime(root.parent.parent), root.name)
    return planning_control_from_publication(publication) if publication else None


def record_response(root, output, control, result):
    if control is None:
        return
    proposal = result.proposal
    response = proposal.intervention_response if proposal else None
    retain_json(
        output / "INTERVENTION_RECEIPT.json",
        {
            "schema_version": "1.0",
            "publication_sha256": control.source_publication_sha256,
            "status": response.disposition
            if result.status.value == "accepted" and response
            else "rejected",
            "explanation": response.explanation
            if response
            else "Planner did not accept a bound response",
            "input_sha256": sha(output / "INPUT.json"),
            "result_sha256": sha(output / "RESULT.json"),
            "execution_started": False,
            "execution_authorized": False,
        },
    )


def execution_boundary(root, plan):
    """Reject stale/ignored UI changes only before a new run, not while delivering old work."""
    latest = current_control(root)
    if latest is None:
        return
    binding = plan.get("research_design", {})
    locator = binding.get("locator")
    if not locator:
        raise ValueError("Published user plan requires a fresh intervention-aware research design")
    path = (root / locator).resolve(strict=True)
    path.relative_to(root)
    if sha(path) != binding.get("sha256"):
        raise ValueError("Bound research design changed")
    design = json.loads(path.read_text())
    response = design.get("intervention_response") or {}
    packet_path, result_path = path.parent / "INPUT.json", path.parent / "RESULT.json"
    packet, result = json.loads(packet_path.read_text()), json.loads(result_path.read_text())
    control = packet.get("user_intervention") or {}
    if (
        result.get("status") != "accepted"
        or result.get("proposal") != design
        or control != latest.model_dump(mode="json")
        or response.get("publication_sha256") != latest.source_publication_sha256
        or response.get("disposition") != "addressed"
    ):
        raise ValueError("User intervention unresolved or superseded; replan before execution")


def planning_status(runtime, publication):
    """Read verified registered planning receipts, not model-authored UI assertions."""
    root = runtime.projects_root / publication.project_id
    snapshot = runtime.open(publication.project_id)
    for run in reversed(snapshot.manifest.runs):
        if run.condition != "project-research-design-proposal" or not run.artifact:
            continue
        result_path = (root / run.artifact).resolve(strict=True)
        result_path.relative_to(root)
        receipt_path = result_path.parent / "INTERVENTION_RECEIPT.json"
        if not receipt_path.is_file():
            continue
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("publication_sha256") != publication.publication_sha256:
            continue
        packet_path = result_path.parent / "INPUT.json"
        if (
            sha(result_path) != run.artifact_sha256
            or sha(result_path) != receipt["result_sha256"]
            or sha(packet_path) != receipt["input_sha256"]
        ):
            raise ValueError("Native intervention receipt sources changed")
        result, packet = json.loads(result_path.read_text()), json.loads(packet_path.read_text())
        response = (result.get("proposal") or {}).get("intervention_response") or {}
        if (packet.get("user_intervention") or {}).get(
            "source_publication_sha256"
        ) != publication.publication_sha256:
            raise ValueError("Native planning input belongs to another intervention")
        accepted = result.get("status") == "accepted"
        status = response.get("disposition") if accepted else "rejected"
        if status != receipt["status"] or (
            accepted
            and (
                response.get("publication_sha256") != publication.publication_sha256
                or response.get("explanation") != receipt["explanation"]
            )
        ):
            raise ValueError("Native intervention receipt differs from planner response")
        return status, receipt["explanation"]
    return "awaiting-planning", ""

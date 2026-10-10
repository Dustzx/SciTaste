"""Recover advisory review with conservative flags, preserving the rejected invocation."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.models import NodeContext
from scitaste.model_nodes.nodes import VenuePaperReviewNode
from scitaste.model_nodes.schemas import VenuePaperReviewInput, VenuePaperReviewProposal
from scitaste.project import ProjectRuntime
from scitaste.review.model_report import build_internal_model_review_report
from scitaste.review.venue import import_venue_review_report, load_venue_review_packet


def recover(*, project, review_id, output):
    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root)
    raw = (output / "RESULT.json").read_bytes()
    receipt = json.loads(raw)
    result = receipt["result"]
    if receipt["outcome"] != "rejected" or result["node_name"] != "venue-paper-review":
        raise ValueError("Only rejected paper-review advice is eligible")
    if result["request"]["expected_backend"] == "assistant-session":
        return recover_session_advice(root, review_id, output, raw, receipt)
    response_raw = (output / "logs/provider_calls/00000.response").read_bytes()
    response = json.loads(response_raw)
    choice = response["choices"][0]
    if choice["finish_reason"] != "stop" or choice["message"].get("tool_calls"):
        raise ValueError("Incomplete or tool-requesting review cannot be recovered")
    payload = json.loads(choice["message"]["content"])
    if payload != result["response"]["output_payload"]:
        raise ValueError("Retained provider response differs from rejected runtime evidence")
    request = json.loads((output / "logs/provider_calls/00000.json").read_text())["request"]
    envelope = json.loads(request["messages"][0]["content"])
    if envelope["input"] != result["request"]["input_payload"]:
        raise ValueError("Retained request differs from runtime input")
    inputs = VenuePaperReviewInput.model_validate(envelope["input"]["input"])
    context = NodeContext.model_validate(envelope["input"]["context"])
    runtime = ProjectRuntime(root.parent.parent)
    packet = load_venue_review_packet(runtime, root.name, review_id)
    if inputs.packet_sha256 != packet.packet_sha256:
        raise ValueError("Review packet differs from retained request")
    node = VenuePaperReviewNode()
    proposal = VenuePaperReviewProposal.model_validate(payload)
    reasons = node._proposal_rejections(proposal, input_data=inputs, context=context, policy=None)
    if not reasons or any(
        not r.endswith("experiment action lacks evidence flags") for r in reasons
    ):
        raise ValueError("Review has failures beyond conservative evidence-flag recovery")
    edits = []
    for concern in payload["concerns"]:
        if concern["proposed_action_type"] in {"ADD_EXPERIMENT", "ADD_BASELINE", "REVISE_METHOD"}:
            for key in ("requires_new_experiment", "requires_new_evidence"):
                if not concern[key]:
                    edits.append(
                        {
                            "concern_id": concern["concern_id"],
                            "field": key,
                            "original": False,
                            "recovered": True,
                        }
                    )
                    concern[key] = True
    normalized = VenuePaperReviewProposal.model_validate(payload)
    remaining = node._proposal_rejections(
        normalized, input_data=inputs, context=context, policy=None
    )
    if remaining:
        raise ValueError("Recovered review still violates its original content contract")
    report = build_internal_model_review_report(
        packet,
        normalized,
        report_id="recovered-advisory-review-01",
        reviewer_id="retained-advisory-reviewer",
        provider=response.get("provider", "bailian"),
        model=response["model"],
    )
    recovery = {
        "status": "recovered-advisory-not-runtime-accepted",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "original_response_sha256": hashlib.sha256(response_raw).hexdigest(),
        "original_rejections": reasons,
        "edits": edits,
        "report_sha256": report.report_sha256,
        "review_id": review_id,
        "experiment_execution_authorized": False,
        "scientific_approval": False,
        "original_runtime_status_changed": False,
        "new_api_calls": 0,
        "note": "Flags conservatively require evidence; neither prose nor verdict changed. "
        "This is internal advisory recovery, not accepted model-node output.",
    }
    path = output / "ADVISORY_RECOVERY.json"
    if path.exists():
        if json.loads(path.read_text()) != recovery:
            raise ValueError("Existing recovery differs")
    else:
        with path.open("x") as stream:
            json.dump(recovery, stream, indent=2)
    from scitaste.review.venue import load_venue_review_reports

    existing = load_venue_review_reports(runtime, root.name, review_id)
    if existing:
        if not any(r.report_sha256 == report.report_sha256 for r in existing):
            raise ValueError("Review already has different imported feedback")
    else:
        import_venue_review_report(
            runtime,
            project_id=root.name,
            review_id=review_id,
            report=report,
            expected_revision=runtime.open(root.name).revision,
        )
    return recovery


def recover_session_advice(root, review_id, output, raw, receipt):
    """Import bounded advice without relabeling a byte-budget rejection as accepted."""
    from scitaste.model_nodes.session_exchange import load_retained_request, retain_json
    from scitaste.review.venue import load_venue_review_reports

    result = receipt["result"]
    revision_conflict = receipt["blockers"] == [
        "project revision changed while the model-node backend was running"
    ]
    recoverable = (
        ["output token budget exceeded"],
        ["project revision changed while the model-node backend was running"],
    )
    if receipt["blockers"] not in recoverable:
        raise ValueError(
            "Only byte admission or unchanged-paper revision conflicts are recoverable"
        )
    contract = json.loads((output / "CONTRACT.json").read_text())
    exchange = Path(contract["session_exchange"]).resolve(strict=True)
    exchange.relative_to(root)
    from scitaste.model_nodes.models import StructuredModelRequest

    recorded_request = StructuredModelRequest.model_validate(result["request"])
    fingerprint = recorded_request.fingerprint
    request = load_retained_request(exchange / (fingerprint + ".request.json"))
    retained = json.loads((exchange / (fingerprint + ".response.json")).read_text())
    if retained != result["response"] or request != recorded_request:
        raise ValueError("Session review differs from retained runtime evidence")
    payload = retained["output_payload"]
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 16384:
        raise ValueError("Advisory recovery exceeds the explicit 16 KiB byte limit")
    inputs = VenuePaperReviewInput.model_validate(request.input_payload["input"])
    context = NodeContext.model_validate(request.input_payload["context"])
    runtime = ProjectRuntime(root.parent.parent)
    packet = load_venue_review_packet(runtime, root.name, review_id)
    if inputs.packet_sha256 != packet.packet_sha256:
        raise ValueError("Review packet changed")
    # Unrelated project progress may change during a read-only review. This is
    # advisory import, NOT acceptance under stale project authority. Every bound
    # paper artifact and manifest must still match before importing the advice.
    snapshot = runtime.open(root.name)
    paper = next(
        (entry for entry in snapshot.papers if entry.directory_name == packet.paper_directory),
        None,
    )
    if paper is None or paper.manifest_sha256 != packet.paper_manifest_sha256:
        raise ValueError("Reviewed paper manifest changed")
    paper_root = root / "papers" / packet.paper_directory
    for label, expected in packet.paper_artifact_sha256.items():
        artifact = (paper_root / paper.manifest.files[label]).resolve(strict=True)
        artifact.relative_to(paper_root)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed paper artifact changed")
    if hashlib.sha256(inputs.paper_text.encode()).hexdigest() != inputs.paper_text_sha256:
        raise ValueError("Retained scientific text hash changed")
    if inputs.paper_text_sha256 not in packet.paper_artifact_sha256.values():
        raise ValueError("Retained review does not target the bound paper")
    proposal = VenuePaperReviewProposal.model_validate(payload)
    if VenuePaperReviewNode()._proposal_rejections(
        proposal, input_data=inputs, context=context, policy=None
    ):
        raise ValueError("Review has semantic failures; byte-budget recovery cannot waive them")
    report = build_internal_model_review_report(
        packet,
        proposal,
        report_id="recovered-session-advice-01",
        reviewer_id="retained-session-reviewer",
        provider="assistant-session",
        model="session-authored",
    )
    recovery = {
        "status": "recovered-advisory-not-runtime-accepted",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "original_request_fingerprint": fingerprint,
        "report_sha256": report.report_sha256,
        "original_runtime_status_changed": False,
        **({"original_rejections": receipt["blockers"]} if revision_conflict else {}),
        "scientific_approval": False,
        "experiment_execution_authorized": False,
        "new_api_calls": 0,
        "new_session_responses": 0,
        "edits": [],
        "explicit_advisory_byte_limit": 16384,
        "note": (
            "Original rejection retained; unchanged paper-bound advisory feedback only. "
            "Project execution authority is not renewed and no experiment is authorized."
            if revision_conflict
            else "Original byte-budget rejection retained; unchanged bounded advice only."
        ),
    }
    retain_json(output / "ADVISORY_RECOVERY.json", recovery)
    existing = load_venue_review_reports(runtime, root.name, review_id)
    if existing:
        if not any(r.report_sha256 == report.report_sha256 for r in existing):
            raise ValueError("Different review already imported")
    else:
        import_venue_review_report(
            runtime,
            project_id=root.name,
            review_id=review_id,
            report=report,
            expected_revision=runtime.open(root.name).revision,
        )
    return recovery


def recover_pending_advice(*, project, review_id, output):
    """Import an unchanged emitted reply after a pre-consumption revision conflict.

    No execution authority is renewed, no model response regenerated, and the
    original pending request and failed process attempts remain unchanged.
    """
    from scitaste.model_nodes.session_exchange import (
        SessionReply,
        load_retained_request,
        retain_json,
    )
    from scitaste.review.venue import load_venue_review_reports

    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root)
    if (output / "RESULT.json").exists():
        raise ValueError("Completed reviews require receipt-based recovery")
    pending_path = output / "SESSION_PENDING.json"
    pending = json.loads(pending_path.read_bytes())
    if pending.get("status") != "awaiting-session-response" or pending.get("api_calls") != 0:
        raise ValueError("Only retained no-API pending advice can be imported")
    contract = json.loads((output / "CONTRACT.json").read_bytes())
    if contract["review_id"] != review_id:
        raise ValueError("Review identity changed")
    exchange = Path(contract["session_exchange"]).resolve(strict=True)
    exchange.relative_to(root)
    request_path = Path(pending["request"]).resolve(strict=True)
    request_path.relative_to(exchange)
    request = load_retained_request(request_path)
    if request.node_name != "venue-paper-review" or request.expected_backend != "assistant-session":
        raise ValueError("Only session-authored venue review advice is eligible")
    reply_path = request_path.with_name(request_path.name.replace(".request.json", ".reply.json"))
    reply = SessionReply.model_validate_json(reply_path.read_bytes())
    if reply.request_fingerprint != request.fingerprint or reply.request_id != request.request_id:
        raise ValueError("Reply/request binding changed")
    inputs = VenuePaperReviewInput.model_validate(request.input_payload["input"])
    context = NodeContext.model_validate(request.input_payload["context"])
    runtime = ProjectRuntime(root.parent.parent)
    snapshot = runtime.open(root.name)
    packet = load_venue_review_packet(runtime, root.name, review_id)
    if inputs.packet_sha256 != packet.packet_sha256:
        raise ValueError("Review packet changed")
    paper = next((p for p in snapshot.papers if p.directory_name == packet.paper_directory), None)
    if paper is None or paper.manifest_sha256 != packet.paper_manifest_sha256:
        raise ValueError("Reviewed paper manifest changed")
    paper_root = root / "papers" / packet.paper_directory
    for label, expected in packet.paper_artifact_sha256.items():
        artifact = (paper_root / paper.manifest.files[label]).resolve(strict=True)
        artifact.relative_to(paper_root)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed paper artifact changed")
    if hashlib.sha256(inputs.paper_text.encode()).hexdigest() != inputs.paper_text_sha256:
        raise ValueError("Reviewed scientific text changed")
    if inputs.paper_text_sha256 not in packet.paper_artifact_sha256.values():
        raise ValueError("Review does not target the bound paper")
    evidence = context.metadata.get("supplemental_evidence", {})
    for locator, item in evidence.items():
        artifact = (root / locator).resolve(strict=True)
        artifact.relative_to(root)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Review evidence changed")
    if len(json.dumps(reply.output_payload, ensure_ascii=False).encode()) > 16384:
        raise ValueError("Pending advisory reply exceeds explicit byte bound")
    proposal = VenuePaperReviewProposal.model_validate(reply.output_payload)
    if VenuePaperReviewNode()._proposal_rejections(
        proposal, input_data=inputs, context=context, policy=None
    ):
        raise ValueError("Review has semantic failures; pending import cannot waive them")
    cycle = root / "evaluations" / (packet.paper_directory + "-cycle")
    conflicts = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in cycle.glob("review*.log")
        if b"ProjectRevisionConflictError: stale project revision" in path.read_bytes()
    }
    if not conflicts:
        raise ValueError("No retained pre-consumption revision conflict")
    report = build_internal_model_review_report(
        packet,
        proposal,
        report_id="pending-session-advice-01",
        reviewer_id="pending-session-reviewer",
        provider="assistant-session",
        model="session-authored",
    )
    recovery = {
        "status": "pending-advisory-import-not-runtime-accepted",
        "original_pending_sha256": hashlib.sha256(pending_path.read_bytes()).hexdigest(),
        "original_request_fingerprint": request.fingerprint,
        "original_reply_sha256": hashlib.sha256(reply_path.read_bytes()).hexdigest(),
        "reviewer_author_reference": reply.author_reference,
        "failed_process_logs": conflicts,
        "report_sha256": report.report_sha256,
        "scientific_approval": False,
        "experiment_execution_authorized": False,
        "original_runtime_status_changed": False,
        "new_api_calls": 0,
        "new_session_responses": 0,
        "edits": [],
    }
    retain_json(output / "PENDING_ADVISORY_RECOVERY.json", recovery)
    existing = load_venue_review_reports(runtime, root.name, review_id)
    if existing:
        if not any(r.report_sha256 == report.report_sha256 for r in existing):
            raise ValueError("Different advisory report already imported")
    else:
        import_venue_review_report(
            runtime,
            project_id=root.name,
            review_id=review_id,
            report=report,
            expected_revision=runtime.open(root.name).revision,
        )
    return recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pending-advisory", action="store_true")
    args = vars(parser.parse_args())
    function = recover_pending_advice if args.pop("pending_advisory") else recover
    print(json.dumps(function(**args)))


if __name__ == "__main__":
    main()

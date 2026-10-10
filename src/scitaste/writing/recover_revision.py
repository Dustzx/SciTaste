"""Materialize unchanged session revision advice after a legacy byte-budget rejection."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.model_nodes.models import NodeContext, StructuredModelRequest
from scitaste.model_nodes.session_exchange import load_retained_request, retain_json
from scitaste.project import ProjectRuntime
from scitaste.project.models import PaperManifest
from scitaste.review.venue import load_venue_review_packet, load_venue_review_reports
from scitaste.writing.candidate_revision import (
    CandidateRevisionInput,
    CandidateRevisionNode,
    CandidateRevisionProposal,
    apply_candidate_revision,
)


def recover(*, project: Path, output: Path, paper_directory: str):
    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root)
    target = (root / "papers" / paper_directory).resolve()
    target.relative_to(root / "papers")
    if target.exists():
        raise FileExistsError(target)
    raw = (output / "RESULT.json").read_bytes()
    result = json.loads(raw)
    contract = json.loads((output / "CONTRACT.json").read_text())
    request = StructuredModelRequest.model_validate(
        {k: v for k, v in result["request"].items() if k != "fingerprint"}
    )
    if request.fingerprint != result["request"]["fingerprint"]:
        raise ValueError("Recorded request fingerprint differs")
    if (
        result["status"] != "rejected"
        or result["node_name"] != "candidate-paper-revision"
        or result["rejection_reasons"] != ["output token budget exceeded"]
        or request.expected_backend != "assistant-session"
    ):
        raise ValueError("Only legacy session byte-admission rejection is eligible")
    exchange = Path(contract["session_exchange"]).resolve(strict=True)
    exchange.relative_to(root)
    fingerprint = request.fingerprint
    retained = json.loads((exchange / (fingerprint + ".response.json")).read_text())
    if (
        load_retained_request(exchange / (fingerprint + ".request.json")) != request
        or retained != result["response"]
    ):
        raise ValueError("Retained session request or response differs")
    payload = retained["output_payload"]
    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
    if payload_bytes > 32768:
        raise ValueError("Advice exceeds explicit 32 KiB byte admission")
    packet = CandidateRevisionInput.model_validate(request.input_payload["input"])
    if packet != CandidateRevisionInput.model_validate_json((output / "INPUT.json").read_bytes()):
        raise ValueError("Original revision packet differs")
    context = NodeContext.model_validate(request.input_payload["context"])
    proposal = CandidateRevisionProposal.model_validate(payload)
    if CandidateRevisionNode()._proposal_rejections(
        proposal, input_data=packet, context=context, policy=None
    ):
        raise ValueError("Semantic rejection cannot be waived by byte recovery")
    runtime = ProjectRuntime(root.parent.parent)
    review_id = contract["review_id"]
    review = load_venue_review_packet(runtime, root.name, review_id)
    reports = load_venue_review_reports(runtime, root.name, review_id)
    if contract["report_sha256"] != {r.report_id: r.report_sha256 for r in reports}:
        raise ValueError("Review reports changed")
    paper = runtime.open_paper(root.name, review.paper_directory)
    label = next(k for k in ("markdown", "source-markdown", "main.md") if k in paper.files)
    source = root / "papers" / review.paper_directory / paper.files[label]
    source_raw = source.read_bytes()
    digest = hashlib.sha256(source_raw).hexdigest()
    if digest != contract["paper_sha256"] or digest != review.paper_artifact_sha256[label]:
        raise ValueError("Reviewed source changed")
    for key, binding in contract["evidence"].items():
        path = (root / binding["locator"]).resolve(strict=True)
        path.relative_to(root)
        evidence = path.read_bytes()
        if hashlib.sha256(evidence).hexdigest() != binding["sha256"]:
            raise ValueError("Revision evidence changed")
        if packet.evidence[key] != evidence.decode():
            raise ValueError("Revision evidence does not match original input")
    revised = apply_candidate_revision(source_raw.decode(), packet, proposal)
    recovery = {
        "status": "recovered-advisory-not-runtime-accepted",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "original_request_fingerprint": fingerprint,
        "original_runtime_status_changed": False,
        "new_api_calls": 0,
        "new_session_responses": 0,
        "explicit_advisory_byte_limit": 32768,
        "payload_bytes": payload_bytes,
        "edits_to_model_response": [],
        "review_closed": False,
        "scientific_approval": False,
        "target_paper": paper_directory,
        "revised_sha256": hashlib.sha256(revised.encode()).hexdigest(),
    }
    retain_json(output / "ADVISORY_RECOVERY.json", recovery)
    markdown = output / "recovered-main.md"
    with markdown.open("x") as stream:
        stream.write(revised)
    paths = materialize_manuscript(
        markdown_path=markdown,
        target_dir=target,
        asset_roots=(source.parent,),
        evidence_audited=False,
    )
    trace = {
        "source_paper": review.paper_directory,
        "source_sha256": digest,
        "review_id": review_id,
        "revision_result": str((output / "RESULT.json").relative_to(root)),
        "advisory_recovery": str((output / "ADVISORY_RECOVERY.json").relative_to(root)),
        "revised_sha256": recovery["revised_sha256"],
        "responses": [r.model_dump(mode="json") for r in proposal.responses],
        "review_closed": False,
        "scientific_approval": False,
    }
    retain_json(target / "CANDIDATE_REVISION.json", trace)
    runtime.register_paper(
        root.name,
        PaperManifest(
            paper_id=paper_directory,
            project_id=root.name,
            title=paper.title,
            date=date.today(),
            provider="assistant-session",
            model="session-authored",
            condition="retained-session-advice-revised-unapproved-candidate",
            task=paper.task,
            seed=0,
            stage=18,
            status="revised-candidate-needs-review",
            evidence_scope=paper.evidence_scope,
            source_run=paper.source_run,
            publication_ready=False,
            files={
                **{
                    p.relative_to(target).as_posix(): p.relative_to(target).as_posix()
                    for p in paths
                },
                "revision": "CANDIDATE_REVISION.json",
            },
        ),
        directory_name=paper_directory,
        expected_revision=runtime.open(root.name).revision,
    )
    return recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paper-directory", required=True)
    print(json.dumps(recover(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

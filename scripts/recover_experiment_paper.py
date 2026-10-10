"""Recover retained drafting prose separately from the failed live invocation."""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from scitaste.model_nodes.models import NodeContext
from scitaste.writing.json_recovery import recover_extra_closing_braces
from scitaste.writing.semantic import EvidencePaperDraftNode, render_evidence_paper_markdown
from scitaste.writing.semantic_models import EvidencePaperDraftInput, EvidencePaperDraftProposal


def recover_candidate(*, project, input_path, response_path, output):
    args = SimpleNamespace(project=project, input=input_path, response=response_path, output=output)
    root = args.project.resolve(strict=True)
    for path in (args.input, args.response, args.output):
        path.resolve().relative_to(root)
    inputs = EvidencePaperDraftInput.model_validate_json(args.input.read_bytes())
    raw = args.response.read_bytes()
    response = json.loads(raw)
    choice = response["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("Truncated or unfinished responses cannot be recovered as full drafts")
    payload, normalized, edits = recover_extra_closing_braces(choice["message"]["content"])
    request_bytes = args.response.with_suffix(".json").read_bytes()
    recorded_request = json.loads(request_bytes)["request"]
    prompt = json.loads(recorded_request["messages"][0]["content"])
    if EvidencePaperDraftInput.model_validate(prompt["input"]["input"]) != inputs:
        raise ValueError("Provider request used different evidence input")
    binding_issues = []
    if payload.get("input_fingerprint") != inputs.fingerprint:
        binding_issues.append(
            "Model echoed a wrong input fingerprint; actual request input matched"
        )
    context = NodeContext(
        project_id=root.name,
        stage="COMMUNICATION",
        state_snapshot_id=inputs.fingerprint,
        cumulative_api_cost_usd=0,
        claim_ids=[item.claim_id for item in inputs.claims],
        evidence_ids=[item.evidence_id for item in inputs.evidence],
        section_ids=list(inputs.required_sections),
    )
    try:
        proposal = EvidencePaperDraftProposal.model_validate(payload)
    except ValidationError as exc:
        # A reviewable manuscript need not pass the scientific-admission schema.
        # Preserve exact prose and the rejection; never promote it as accepted.
        reasons = binding_issues + [f"{item['loc']}: {item['msg']}" for item in exc.errors()]
        if inputs.citations or tuple(s["section_name"] for s in payload["sections"]) != (
            inputs.required_sections
        ):
            raise ValueError("Recovery requires exact sections and citation-free prose") from exc
        paragraphs = [
            payload["abstract"],
            *[p for section in payload["sections"] for p in section["paragraphs"]],
        ]
        if any(
            not isinstance(p.get("text"), str) or not p["text"].strip() or p.get("citation_ids")
            for p in paragraphs
        ):
            raise ValueError(
                "Recovered prose is incomplete or requires citation rendering"
            ) from exc
        if not isinstance(payload.get("title"), str) or not payload["title"].strip():
            raise ValueError("Recovered draft has no title") from exc
        blocks = ["# " + payload["title"], "## Abstract", payload["abstract"]["text"]]
        for section in payload["sections"]:
            blocks.extend(
                ["## " + section["section_name"], *[p["text"] for p in section["paragraphs"]]]
            )
        markdown = "\n\n".join(blocks) + "\n"
        words = len(markdown.split())
    else:
        reasons = EvidencePaperDraftNode()._proposal_rejections(
            proposal,
            input_data=inputs,
            context=context,
            policy=None,
        )
        markdown = render_evidence_paper_markdown(proposal, input_data=inputs)
        words = proposal.word_count
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "main.md").write_text(markdown)
    (args.output / "NORMALIZED_PROPOSAL.json").write_text(normalized)
    report = {
        "status": "recovered-candidate-needs-review",
        "original_response_sha256": hashlib.sha256(raw).hexdigest(),
        "original_request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "input_fingerprint": inputs.fingerprint,
        "normalized_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "deleted_closing_brace_offsets_sequential": edits,
        "semantic_rejections": reasons,
        "word_count": words,
        "original_live_run_status_changed": False,
        "new_api_calls": 0,
        "scientific_approval": False,
        "formal_evidence_eligible": False,
    }
    (args.output / "RECOVERY.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "input", "response", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            recover_candidate(
                project=args.project,
                input_path=args.input,
                response_path=args.response,
                output=args.output,
            )
        )
    )


if __name__ == "__main__":
    main()

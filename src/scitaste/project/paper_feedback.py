"""Load completed paper-flow reviews as planning context, not automatic approval."""

import hashlib
import json
from pathlib import Path

from scitaste.project.runtime import ProjectRuntime
from scitaste.review.venue import load_venue_review_packet, load_venue_review_reports


def review_work_items(concerns):
    """Route scientific feedback without treating a revision paragraph as evidence.

    Reviewer flags and action hints are fallible suggestions, not execution orders.
    In particular ADD_ANALYSIS can require computation even when the reviewer says
    no new experiment or evidence acquisition is needed.
    """
    items = []
    for row in concerns:
        concern = row["concern"]
        response = row.get("revision_response") or {}
        action = concern.get("proposed_action_type")
        if concern.get("requires_new_experiment"):
            route = "new-experiment"
        elif concern.get("requires_new_evidence"):
            route = "evidence-acquisition"
        elif action == "ADD_ANALYSIS":
            route = "retained-evidence-analysis"
        elif response.get("disposition") == "pending-evidence":
            route = "scientific-planning-required"
        else:
            route = "claim-or-text-revision"
        items.append(
            {
                "concern_id": concern["concern_id"],
                "route": route,
                "request": concern["text"],
                "previous_response": response,
                "report_sha256": row["report_sha256"],
                "execution_authorized": False,
                "resolution_verified": False,
            }
        )
    return items


def load_paper_feedback(project: Path, flow: Path) -> dict:
    root = project.resolve(strict=True)
    flow = flow.resolve(strict=True)
    flow.relative_to(root)
    sources = {}

    def read(path, expected=None, *, structured=True):
        path = path.resolve(strict=True)
        locator = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and expected != digest:
            raise ValueError(f"Paper feedback source changed: {locator}")
        sources[locator] = digest
        return json.loads(raw) if structured else raw

    summary = read(flow / "SUMMARY.json")
    if summary["status"] not in {"measured-paper-segment-complete", "artifact-flow-complete"}:
        raise ValueError("Paper flow has not reached terminal delivery")
    contract = read(flow / "CONTRACT.json")
    if summary["status"] == "artifact-flow-complete":
        if contract["scope"] != "candidate-paper-review-revision-build":
            raise ValueError("Unsupported direct paper cycle scope")
        cycle_summary, cycle_contract = summary, contract
        # A direct actual-report cycle has no measured-draft wrapper. Normalize
        # only its local field names; retain the original contracts and hashes.
        contract = {**contract, "review_run": contract["review_id"]}
    else:
        cycle = flow / "paper-cycle"
        if (flow / "REVISION_RECOVERY.json").exists():
            recovery = read(flow / "REVISION_RECOVERY.json")
            original = root / "evaluations" / contract["revision_run"] / "RESULT.json"
            read(original, recovery["original_result_sha256"])
            cycle = flow / "paper-cycle-recovery"
        cycle_summary = read(cycle / "SUMMARY.json")
        if cycle_summary != summary["paper_cycle"]:
            raise ValueError("Paper segment and revision cycle differ")
        cycle_contract = read(cycle / "CONTRACT.json")
    if (
        cycle_contract["source_paper"] != contract["source_paper"]
        or cycle_contract["revised_paper"] != contract["revised_paper"]
        or cycle_contract["review_id"] != contract["review_run"]
        or cycle_contract["evidence"] != contract["evidence"]
    ):
        raise ValueError("Paper flow bindings differ")
    for locator, digest in contract["evidence"].items():
        read(root / locator, digest, structured=False)
    runtime = ProjectRuntime(root.parent.parent)
    review_id = cycle_contract["review_id"]
    packet = load_venue_review_packet(runtime, root.name, review_id)
    reports = load_venue_review_reports(runtime, root.name, review_id)
    if packet.paper_directory != contract["source_paper"]:
        raise ValueError("Review belongs to a different source paper")
    for directory in (contract["source_paper"], contract["revised_paper"]):
        runtime.open_paper(root.name, directory)
    read(
        root / "papers" / contract["source_paper"] / "main.md",
        cycle_summary["source_sha256"],
        structured=False,
    )
    paper = root / "papers" / contract["revised_paper"]
    read(paper / "main.md", cycle_summary["revised_sha256"], structured=False)
    read(paper / "main.pdf", cycle_summary["pdf_sha256"], structured=False)
    trace = read(paper / "CANDIDATE_REVISION.json")
    if (
        trace["review_id"] != review_id
        or trace["source_sha256"] != cycle_summary["source_sha256"]
        or trace["revised_sha256"] != cycle_summary["revised_sha256"]
    ):
        raise ValueError("Revision feedback belongs to different paper bytes")
    responses = {row["concern_id"]: row for row in trace["responses"]}
    concerns = []
    for report in reports:
        for concern in report.concerns:
            concerns.append(
                {
                    "report_id": report.report_id,
                    "report_sha256": report.report_sha256,
                    "concern": concern.model_dump(mode="json"),
                    "revision_response": responses.get(concern.concern_id),
                    "resolution_verified_by_this_feedback": False,
                    "experiment_execution_authorized": False,
                }
            )
    if len({row["concern"]["concern_id"] for row in concerns}) != len(concerns):
        raise ValueError("Ambiguous concern IDs across reports")
    return {
        "schema_version": "1.0",
        "role": "review-and-revision-context-not-admitted-taste",
        "paper_flow": flow.relative_to(root).as_posix(),
        "revised_paper": contract["revised_paper"],
        "review_id": review_id,
        "review_packet_sha256": packet.packet_sha256,
        "concerns": concerns,
        "work_items": review_work_items(concerns),
        "interpretation": (
            "Reviewer requests are fallible planning inputs, not mandatory execution gates. "
            "Text revision does not close an evidence gap. Prioritize missing workflow "
            "capabilities before quality/effectiveness optimization under completeness-first."
        ),
        "policy_update_authorized": False,
        "execution_authorized": False,
        "scientific_quality_established": False,
        "sources": sources,
    }

"""Link measured delivery, revised paper and conservative experience disposition.

This records a post-experiment lifecycle segment, not an autonomous Idea-to-paper
run. A no-credit observation may be retained without promoting it into policy.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scitaste.taste.episodes import TasteEpisodeCandidate
from scitaste.taste.experience_disposition import disposition_for_candidate
from scripts.register_research_artifact import register_artifact


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalize(*, project, delivery, paper_flow, output, reviews=()):
    root = project.resolve(strict=True)
    delivery, paper_flow, output = delivery.resolve(), paper_flow.resolve(), output.resolve()
    for path in (delivery, paper_flow, output, *reviews):
        path.resolve().relative_to(root)
    selection_path = delivery / "SELECTION.json"
    selection = json.loads(selection_path.read_text())
    summary_path = paper_flow / "SUMMARY.json"
    summary = json.loads(summary_path.read_text())
    contract = json.loads((paper_flow / "CONTRACT.json").read_text())
    if (
        summary["status"] != "measured-paper-segment-complete"
        or summary["input_selection_sha256"] != sha(selection_path)
        or contract["selection_sha256"] != sha(selection_path)
    ):
        raise ValueError("Completed paper flow does not bind this measured delivery")
    source = Path(selection["source_run"]).resolve(strict=True)
    source.relative_to(root)
    if sha(source / "CONTRACT.json") != selection["source_contract_sha256"]:
        raise ValueError("Measured source contract changed")
    revised = root / "papers" / contract["revised_paper"]
    revised.resolve(strict=True).relative_to(root / "papers")
    cycle = summary["paper_cycle"]
    if (
        sha(revised / "main.md") != cycle["revised_sha256"]
        or sha(revised / "main.pdf") != cycle["pdf_sha256"]
    ):
        raise ValueError("Revised manuscript differs from completed paper flow")
    collection_path = delivery / "experience/COLLECTION.json"
    collection = json.loads(collection_path.read_text())
    if collection["source_run_id"] != source.name:
        raise ValueError("Experience collection belongs to a different source run")
    review_map = {}
    for path in reviews:
        raw = path.read_bytes()
        # Binding is checked by load_attribution_feedback against each candidate.
        payload = json.loads(raw)["result"]["request"]["input_payload"]["input"]
        key = payload["candidate_sha256"]
        if key in review_map:
            raise ValueError("Multiple reviews require explicit adjudication, not last-write wins")
        review_map[key] = (path, raw)
    rows, seen = [], set()
    for item in collection["candidates"]:
        path = Path(item["candidate"]).resolve(strict=True)
        path.relative_to(root)
        candidate = TasteEpisodeCandidate.model_validate_json(path.read_bytes())
        key = candidate.candidate_sha256
        if (
            key != item["candidate_sha256"]
            or key in seen
            or candidate.project_id != root.name
            or candidate.source_project_id != root.name
            or candidate.source_group_id != source.name
        ):
            raise ValueError("Collected candidate identity or source changed")
        seen.add(key)
        review_locator, review_sha, raw = None, None, None
        if key in review_map:
            review_path, raw = review_map[key]
            review_locator = str(review_path.resolve().relative_to(root))
            review_sha = hashlib.sha256(raw).hexdigest()
        disposition, basis = disposition_for_candidate(candidate, review_bytes=raw)
        rows.append(
            {
                "candidate": str(path.relative_to(root)),
                "candidate_sha256": key,
                "candidate_file_sha256": sha(path),
                "disposition": disposition,
                "basis": basis,
                "review": review_locator,
                "review_sha256": review_sha,
                "policy_update_authorized": False,
                "retrieval_admitted": False,
            }
        )
    if set(review_map) - seen:
        raise ValueError("Supplied review does not belong to this collection")
    pending = collection["unresolved_decision_captures"]
    complete = (
        bool(rows)
        and not pending
        and all(row["disposition"] in {"rejected", "abstained"} for row in rows)
    )
    result = {
        "schema_version": "1.0",
        "scope": "measured-delivery-paper-experience-disposition",
        "status": "segment-complete" if complete else "experience-disposition-pending",
        "project_id": root.name,
        "source_run": str(source.relative_to(root)),
        "source_terminal_status": selection["terminal_status"],
        "delivery": str(delivery.relative_to(root)),
        "selection_sha256": sha(selection_path),
        "paper_flow": str(paper_flow.relative_to(root)),
        "paper_flow_sha256": sha(summary_path),
        "paper_directory": contract["revised_paper"],
        "collection_sha256": sha(collection_path),
        "experience_dispositions": rows,
        "disposition_counts": dict(Counter(row["disposition"] for row in rows)),
        "unresolved_captures": pending,
        "policy_updated": False,
        "experience_improvement_established": False,
        "scientific_quality_established": False,
        "whole_project_lifecycle_complete": False,
        "review_closed": False,
        "new_api_calls": 0,
        "new_gpu_experiments": 0,
    }
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "RESULT.json"
    if receipt.exists():
        if json.loads(receipt.read_text()) != result:
            raise ValueError(
                "Existing cycle disposition differs; preserve it and use a new identity"
            )
    else:
        with receipt.open("x") as stream:
            json.dump(result, stream, indent=2)
    register_artifact(
        project=root,
        artifact=receipt,
        provider="deterministic-lifecycle",
        model="none",
        condition="measured-paper-experience-disposition",
        status=result["status"],
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "delivery", "paper-flow", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, action="append", default=[])
    print(json.dumps(finalize(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

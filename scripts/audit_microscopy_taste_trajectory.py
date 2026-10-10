"""Bind observed Taste admission and abstention, without inferring causal value."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    root, study = args.project.resolve(strict=True), args.study.resolve(strict=True)
    study.relative_to(root)
    sealed = json.loads((study / "RESULTS.json").read_text())
    run = verified_asset(root, sealed["outcomes"]["taste"]["research_result"]).parent
    records, counts = [], Counter()
    for path in sorted((run / "taste_deliberation").glob("*.json")):
        value = json.loads(path.read_text())
        receipt = value.get("runtime_receipt")
        if not receipt:
            continue
        result = receipt["result"]
        proposal = result.get("proposal") or {}
        category = (
            "accepted-abstention"
            if result["status"] == "accepted" and not proposal.get("selected_case_ids")
            else "accepted-advice"
            if result["status"] == "accepted"
            else "engineering-fallback"
        )
        counts[category] += 1
        response = (result.get("response") or {}).get("output_payload") or {}
        records.append(
            {
                "binding": {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)},
                "invocation_id": receipt["invocation_id"],
                "category": category,
                "rejection_reasons": result["rejection_reasons"],
                "selected_case_ids": proposal.get("selected_case_ids"),
                "recommended_action_id": proposal.get("recommended_action_id"),
                "response_decision_id": response.get("decision_id"),
                "accepted_decision_id": proposal.get("decision_id"),
            }
        )
    retain_json(
        study / "INTERVENTION_AUDIT.json",
        {
            "results_sha256": digest(study / "RESULTS.json"),
            "counts": dict(counts),
            "records": records,
            "interpretation": (
                "Admission is distinct from scientific applicability. Controller-issued identity "
                "normalization is not scientific rejection. The actual rejection is retained. "
                "Abstention preserves the source-exposed proposal, not a no-experience trajectory; "
                "request/abstention counts neither identify opportunities nor causal Taste value."
            ),
        },
    )
    print(json.dumps(dict(counts)))


if __name__ == "__main__":
    main()

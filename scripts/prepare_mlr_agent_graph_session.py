"""Freeze a genuine MLR-Agent development assignment, not a retrospective main score."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-campaign", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    from scitaste.project.models import validate_entry_id

    for value in (args.campaign_id, args.run_id):
        validate_entry_id(value, field_name="assignment ID")
    project = args.project.resolve(strict=True)
    source = args.source_campaign.resolve(strict=True)
    contract = json.loads(source.read_text())
    assets = {
        name: verified_asset(project, binding)
        for name, binding in contract["researcher_assets"].items()
    }
    brief = verified_asset(project, contract["execution_brief"])
    campaign = project / "evaluations" / args.campaign_id
    campaign.mkdir(parents=True, exist_ok=False)
    interface = (assets["SUBMISSION.example.json"]).read_text()
    (campaign / "TASK.md").write_text(
        brief.read_text()
        + "\n# Exact common frozen-submission interface\n\n```json\n"
        + interface
        + "\n```\n"
        + "\nMLR-Agent workspace is /work. Native results/results.md and results/paper.md "
        "remain its own delivery paths. Complete frozen confirmation before summarizing "
        "results. Preserve data/; any native instruction to delete downloaded assets "
        "does not authorize removal of the supplied readonly research evidence.\n"
    )
    new = {
        **contract,
        "campaign_id": args.campaign_id,
        "frozen_at": datetime.now(UTC).isoformat(),
        "arms": ["mlr-agent"],
        "resource_envelope": {
            **contract["resource_envelope"],
            "wall_seconds": 14400,
            "max_requests": 80,
        },
        "source_development_campaign": {
            "locator": source.relative_to(project).as_posix(),
            "sha256": digest(source),
        },
        "execution_brief": {
            "locator": (campaign / "TASK.md").relative_to(project).as_posix(),
            "sha256": digest(campaign / "TASK.md"),
        },
        "comparison_scope": (
            "post-hoc genuine third-framework development; "
            "no matched formal ranking or latency claim"
        ),
        "new_independent_task": False,
        "formal_evidence_eligible": False,
        "native_review_revision_available": False,
        "literature_configuration": (
            "ordinary native text request, not original supplier search engine"
        ),
    }
    retain_json(campaign / "CAMPAIGN.json", new)
    retain_json(campaign / "ASSIGNMENTS.json", {"mlr-agent": {"run": f"evaluations/{args.run_id}"}})
    print(
        json.dumps(
            {
                "campaign": str(campaign),
                "task": str(campaign / "TASK.md"),
                "assets": str(next(iter(assets.values())).parent),
                "run": str(project / "evaluations" / args.run_id),
            }
        )
    )


if __name__ == "__main__":
    main()

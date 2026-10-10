"""Assign actual pinned framework comparators before any sensor outcome exists."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def prepare(project, study):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(project / "evaluations")
    original = json.loads((study / "STUDY.json").read_text())
    for row in original["allocations"].values():
        run = project / row["run"]
        if (run / "RESULT.json").exists():
            raise ValueError("External assignment must precede any whole-task outcome")
        contract = json.loads(verified_asset(project, row["campaign"]).read_text())
        if (verified_asset(project, row["campaign"]).parent / "confirmation").exists():
            raise ValueError("Do not choose external assignments after confirmation")
    native = original["allocations"]["taste"]
    source = verified_asset(project, native["campaign"])
    contract = json.loads(source.read_text())
    output = study / "external"
    output.mkdir(exist_ok=False)
    brief = output / "TASK.md"
    brief.write_text(
        verified_asset(project, contract["execution_brief"]).read_text()
        + "\n## Genuine external implementation\n\n"
        "AutoResearchClaw workspace is /work independent of its stage sandbox. "
        "Use native code/stages/tools and preserve every helper in the submitted "
        "entrypoint. Direct submission/READY or the first completed genuine "
        "sandbox submission is accepted, never a score-selected later run. "
        "MLR-Agent uses its real native stage sequence and real Codex coding CLI, "
        "with results/results.md and results/paper.md as upstream delivery paths. "
        "Do not delete the supplied data/ even if generic cleanup instructions "
        "suggest doing so. Read actual confirmation feedback before final paper. "
        "No post-paper MLR revision stage or supplier web-search is simulated. "
        "Models supply responses only; the real frameworks own all operations.\n"
    )
    new = {
        **contract,
        "campaign_id": study.name + "-external",
        "frozen_at": datetime.now(UTC).isoformat(),
        "arms": ["autoresearchclaw", "mlr-agent"],
        "execution_brief": {
            "locator": brief.relative_to(project).as_posix(),
            "sha256": digest(brief),
        },
        "native_taste": {"mode": "off", "binding": None},
        "external_research_title": "Probability-quality transfer under temporal gas-sensor drift",
        "external_task_mapping": "short title with unchanged scientific task in pinned native stage extras",
        "metadata_timeout_seconds": 20,
        "submission_path_policy": "executed-native-layout.v1",
        "confirmation_handoff": "aggregate-model-attachment.v1",
        "comparison_scope": "Actual pinned Native/ARC/MLR systems with common data, same screened source, total caps and CPU permissions; backbone identity/randomness unverified and native stage allocation differs",
        "native_comparator": {"campaign": native["campaign"], "run": native["run"]},
        "mlr_agent_configuration": {
            "source_commit": "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824",
            "coding_cli": "real installed Codex CLI with retained version/hash",
            "native_review_revision_available": False,
            "literature_configuration": "ordinary native text requests; no supplier search engine simulation",
        },
        "assignment_before_new_outcomes": True,
        "model_identity_and_randomness_matched": False,
    }
    retain_json(output / "CAMPAIGN.json", new)
    retain_json(
        output / "ASSIGNMENTS.json",
        {
            "autoresearchclaw": {"run": f"evaluations/{study.name}-arc"},
            "mlr-agent": {"run": f"evaluations/{study.name}-mlr-agent"},
        },
    )
    retain_json(
        output / "FREEZE.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "native_source_campaign_sha256": digest(source),
            "external_campaign_sha256": digest(output / "CAMPAIGN.json"),
            "before_any_sensor_confirmation_or_terminal_result": True,
            "source_assets_identical": True,
            "controller_source_shared": False,
            "external_frameworks_are_not_roleplaying_agents": True,
            "formal_evidence_eligible": False,
        },
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.project, args.study))

"""Freeze a Native OFF attribution arm before any parent outcomes are available.

The whole-system parent remains immutable. This is an internal mechanism study,
not an additional external framework or a replay of its completed experiments.
"""

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, prepare_native, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def prepare(project, parent, output):
    project, parent = project.resolve(strict=True), parent.resolve(strict=True)
    parent.relative_to(project / "evaluations")
    output = output.resolve()
    output.relative_to(project / "evaluations")
    original = json.loads(parent.read_text())
    if original["native_taste"]["mode"] != "reviewed-development":
        raise ValueError("Parent must have prospectively bound reviewed experience")
    assignments = json.loads((parent.parent / "ASSIGNMENTS.json").read_text())
    # Freeze before launching/revealing ANY parent outcome, not after finding
    # that a favorable parent result deserves an attribution study.
    if any((project / row["run"]).exists() for row in assignments.values()):
        raise ValueError("Parent execution has begun; prospective paired freeze is too late")
    output.mkdir(parents=True, exist_ok=False)

    def binding(path):
        return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}

    contract = dict(original)
    for field, name in (
        ("execution_brief", "EXECUTION_BRIEF.md"),
        ("brief", "TASK.md"),
        ("rubric", "RUBRIC.md"),
    ):
        shutil.copy2(verified_asset(project, original[field]), output / name)
        contract[field] = binding(output / name)
    (output / "discovery").mkdir()
    contract["researcher_assets"] = {}
    for name, source in original["researcher_assets"].items():
        if Path(name).name != name:
            raise ValueError("Shared assets must have flat names")
        target = output / "discovery" / name
        shutil.copy2(verified_asset(project, source), target)
        contract["researcher_assets"][name] = binding(target)
    treatment = {
        "mode": "off",
        "binding": None,
        "decision_context": original["native_taste"]["decision_context"],
        "proposal_context": "disabled",
    }
    contract.update(
        campaign_id=output.name,
        frozen_at=datetime.now(UTC).isoformat(),
        arms=["scitaste-native"],
        native_taste=treatment,
        comparison_scope=(
            "Prospective same-asset Native experience attribution; not external comparison"
        ),
        taste_scope=(
            "No external experience at proposal or selection; same skills/harness/total ceilings"
        ),
        source_system_campaign=binding(parent),
        formal_evidence_eligible=False,
    )
    retain_json(output / "CAMPAIGN.json", contract)
    prepare_native(
        project,
        output / "CAMPAIGN.json",
        project / "evaluations/acquisitions/researchharness-runtime-v1",
        output / "native-plan",
    )
    retain_json(
        output / "ASSIGNMENTS.json",
        {
            "scitaste-native": {
                "run": f"evaluations/{output.name}-native",
                "lifecycle": f"evaluations/{output.name}-native-lifecycle",
            }
        },
    )
    retain_json(
        output / "PAIRED_STUDY.json",
        {
            "parent": binding(parent),
            "off": binding(output / "CAMPAIGN.json"),
            "discovery_sha256": {n: b["sha256"] for n, b in original["researcher_assets"].items()},
            "execution_brief_sha256": original["execution_brief"]["sha256"],
            "resource_envelope": original["resource_envelope"],
            "frozen_before_all_execution": True,
            "same_harness_and_skills": True,
            "experience_scope": "Combined pre-proposal and post-proposal experience versus OFF",
            "task_families": 1,
            "formal_evidence_eligible": False,
            "model_identity_and_randomness_matched": False,
            "scope": "Session development attribution; no formal causal gain certified",
        },
    )
    print(json.dumps({"off_campaign": str(output), "external_runs_duplicated": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "parent", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.project, args.parent, args.output)


if __name__ == "__main__":
    main()

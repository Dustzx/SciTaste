"""Confirm genuine retained ARC code separately after a delivery-path failure.

No original campaign, program, native feedback or first-paper endpoint is edited.
This is engineering recovery evidence, not original-arm delivery success.
"""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json
from scripts.serve_pde_confirmation import confirm, submission_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    campaign = args.campaign.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    output = args.output.resolve()
    output.relative_to(campaign.parent)
    output.mkdir(parents=True, exist_ok=False)
    arm = "autoresearchclaw"
    assignment_file = campaign.parent / "ASSIGNMENTS.json"
    assignment = json.loads(assignment_file.read_text())[arm]
    run = (project / assignment["run"]).resolve(strict=True)
    run.relative_to(project / "evaluations")
    original_confirmation = campaign.parent / "confirmation" / arm / "RESULT.json"
    if original_confirmation.exists():
        raise ValueError("An already confirmed assignment cannot receive another private execution")
    contract = json.loads(campaign.read_text())
    submission, delivery = submission_source(
        run / "work", arm, {**contract, "submission_path_policy": "executed-native-layout.v1"}
    )
    if submission is None or delivery is None:
        raise ValueError("Recovery requires an actually completed native sandbox delivery")
    source_hashes = {
        path.relative_to(submission).as_posix(): digest(path)
        for path in sorted(submission.rglob("*"))
        if path.is_file()
    }
    retain_json(
        output / "CONTRACT.json",
        {
            "original_campaign_sha256": digest(campaign),
            "original_assignments_sha256": digest(assignment_file),
            "reason": "Original root-only delivery adapter missed completed native sandbox code",
            "native_delivery": delivery,
            "source_sha256": source_hashes,
            "adapter_source_sha256": digest(Path(__file__)),
            "confirmation_adapter_sha256": digest(
                Path(__file__).with_name("serve_pde_confirmation.py")
            ),
            "original_wall_budget_inherited": True,
            "scientific_program_repaired": False,
            "original_first_paper_replaced": False,
            "native_model_feedback_modified": False,
            "original_arm_delivery_success": False,
            "formal_evidence_eligible": False,
        },
    )
    recovery_assignment = {
        **assignment,
        "confirmation": (output / "confirmation").relative_to(project).as_posix(),
    }
    # This service-owned workspace receives feedback, not the original researcher.
    status = confirm(
        project,
        campaign,
        arm,
        output,
        run,
        recovery_assignment,
        submission=submission,
        delivery=delivery,
    )
    if any(digest(submission / name) != expected for name, expected in source_hashes.items()):
        raise ValueError("Original native program changed during recovery")
    print(
        json.dumps(
            {
                "status": status,
                "engineering_recovery": True,
                "original_arm_delivery_success": False,
                "result": str(output / "confirmation/RESULT.json"),
            }
        )
    )


if __name__ == "__main__":
    main()

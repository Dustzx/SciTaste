"""Score the same frozen predictions after an auxiliary-log admission error.

No program execution, scientific edit, resubmission or target-based method choice.
Original rejection remains immutable; only a separately bound recovery is emitted.
"""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.graph_task_data import confirm_submission
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def recover(project, campaign, arm):
    project, campaign = project.resolve(strict=True), campaign.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    contract = json.loads(campaign.read_text())
    assignment = json.loads((campaign.parent / "ASSIGNMENTS.json").read_text())[arm]
    owned = campaign.parent / "confirmation" / arm
    failed = json.loads((owned / "RESULT.json").read_text())
    if (
        failed["status"] != "failed"
        or failed.get("error_type") != "ValueError"
        or failed.get("error")
        != "Submit exactly all predeclared method/control predictions together"
    ):
        raise ValueError(
            "Only the retained all-file-versus-prediction-file admission error is recoverable"
        )
    execution = json.loads((owned / "EXECUTION_CONTRACT.json").read_text())
    release = owned / "release/RELEASE.json"
    if execution["campaign_sha256"] != digest(campaign) or execution["release_sha256"] != digest(
        release
    ):
        raise ValueError("Frozen execution binding differs")
    predictions = owned / "execution/predictions"
    submission = json.loads((owned / "release/frozen_submission/SUBMISSION.json").read_text())
    expected = {f"tolokers--{method}.npz" for method in submission["methods"]}
    paths = list(predictions.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("Recovery admits only regular retained output files")
    if {path.name for path in paths if path.suffix == ".npz"} != expected:
        raise ValueError("Prediction set is incomplete or has undeclared methods")
    auxiliary = [path for path in paths if path.suffix != ".npz"]
    if not auxiliary or any(path.suffix != ".json" for path in auxiliary):
        raise ValueError("This recovery only covers auxiliary JSON logs")
    before = {path.name: digest(path) for path in paths}
    retain_json(
        owned / "SCORING_RECOVERY_CONTRACT.json",
        {
            "campaign_sha256": digest(campaign),
            "original_failure_sha256": digest(owned / "RESULT.json"),
            "prediction_and_log_sha256": before,
            "scientific_program_rerun": False,
            "source_modified": False,
            "new_predictions_submitted": False,
            "return_code_note": "Service reached this scorer error only after subprocess exit 0",
            "scope": "Admission repair: separate auxiliary JSON from required NPZ predictions",
        },
    )
    result = confirm_submission(
        verified_asset(project, contract["pack"]).parent, release, predictions
    )
    if before != {path.name: digest(path) for path in paths}:
        raise ValueError("Retained outputs changed during scoring")
    feedback = {
        "arm": arm,
        "status": "completed",
        "result": json.loads(result.read_text()),
        "executed_frozen_source": True,
        "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
        "elapsed_seconds": failed["elapsed_seconds"],
        "engineering_recovery": True,
        "original_failure_sha256": digest(owned / "RESULT.json"),
        "scoring_recovery_contract_sha256": digest(owned / "SCORING_RECOVERY_CONTRACT.json"),
        "formal_evidence_eligible": False,
    }
    retain_json(owned / "RECOVERED_RESULT.json", feedback)
    workspace = project / assignment["run"] / ("work" if arm == "autoresearchclaw" else "workspace")
    retain_json(workspace / "confirmation_recovered_feedback.json", feedback)
    return {"status": "same-predictions-scored", "methods": len(expected), "program_rerun": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--arm", choices=("scitaste-native", "autoresearchclaw"), required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.project, args.campaign, args.arm)))

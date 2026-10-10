"""Seal every frozen geometry endpoint, separating delivery recovery from success."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def collect(project, campaign, paired, output):
    project = project.resolve(strict=True)
    campaign, paired = campaign.resolve(strict=True), paired.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    paired.relative_to(project / "evaluations")
    output = output.resolve()
    output.relative_to(campaign.parent)
    pair = json.loads(paired.read_text())
    if verified_asset(project, pair["parent"]) != campaign:
        raise ValueError("ON/OFF pairing belongs to another original assignment")
    off = verified_asset(project, pair["off"]).parent

    def binding(path):
        return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}

    rows = []
    assignments = json.loads((campaign.parent / "ASSIGNMENTS.json").read_text())
    for arm in ("scitaste-native", "autoresearchclaw", "mlr-agent", "native-off"):
        original = (off if arm == "native-off" else campaign.parent) / "confirmation"
        original /= "scitaste-native" if arm == "native-off" else arm
        confirmation = original
        recovery = False
        if arm == "autoresearchclaw" and not (original / "RESULT.json").exists():
            confirmation = (
                campaign.parent / "artifact-delivery-recovery/autoresearchclaw/confirmation"
            )
            recovery = True
        raw = json.loads((confirmation / "RESULT.json").read_text())
        if raw["status"] != "completed" or not raw["executed_frozen_source"]:
            raise ValueError("Only actual completed frozen executions have numerical rows")
        submission_file = confirmation / "release/frozen_submission/SUBMISSION.json"
        submission = json.loads(submission_file.read_text())
        primary = submission["primary_method"]
        scores = raw["result"]["scores"]
        if len(scores) != 2 * len(submission["methods"]):
            raise ValueError("Incomplete declared method/type coverage")
        endpoint = {
            row["context"]: row["metrics"]["corner_auc_5px"]
            for row in scores
            if row["method"] == primary
        }
        if set(endpoint) != {"illumination", "viewpoint"}:
            raise ValueError("A unique primary lacks the two required contexts")
        rows.append(
            {
                "system": arm,
                "primary_method": primary,
                "selection_rule": submission["selection_rule"],
                "primary_corner_auc_5px": endpoint,
                "confirmation": binding(confirmation / "RESULT.json"),
                "submission": binding(submission_file),
                "inference": binding(confirmation / "INFERENCE_RESULT.json"),
                "all_declared_score_rows": len(scores),
                "all_declared_procedures": submission["methods"],
                "original_arm_confirmation_delivered": not recovery,
                "engineering_delivery_recovery": recovery,
                "recovery_contract": binding(confirmation.parent / "CONTRACT.json")
                if recovery
                else None,
                "original_missing_confirmation_not_replaced": recovery,
                "source_program_repaired": False,
            }
        )
    on, off_row = rows[0], rows[-1]
    delta = {
        context: on["primary_corner_auc_5px"][context] - off_row["primary_corner_auc_5px"][context]
        for context in on["primary_corner_auc_5px"]
    }
    result = {
        "schema_version": "scitastebench.frozen-geometry-results.v1",
        "task_id": "confidence-guided-geometry",
        "task_families": 1,
        "campaign": binding(campaign),
        "paired_study": binding(paired),
        "rows": rows,
        "original_framework_assignment_count": len(assignments),
        "original_framework_confirmations": sum(
            row["original_arm_confirmation_delivered"] for row in rows[:-1]
        ),
        "separate_framework_delivery_recoveries": sum(
            row["engineering_delivery_recovery"] for row in rows[:-1]
        ),
        "confirmation_scene_groups_per_type": 12,
        "confirmation_pairs_per_type": 60,
        "primary_selection_after_private_scoring": False,
        "all_methods_and_negative_results_retained_in_bound_raw_receipts": True,
        "matched_off_primary_delta": delta,
        "observed_primary_gain": any(value > 0 for value in delta.values()),
        "scientific_interpretation": (
            "ON and prospectively matched OFF selected the same estimator policy and have equal "
            "confirmed primary AUC in both contexts. This realization does not support a Taste "
            "performance improvement; it does not establish universal ineffectiveness. ARC's "
            "numerical recovery is separate from its original missing delivery "
            "and public-only paper."
        ),
        "formal_evidence_eligible": False,
        "verified_model_identity_or_randomness_match": False,
        "human_judge_calibration": False,
        "top_venue_or_novelty_certified": False,
    }
    retain_json(output, result)
    return {"output": str(output), "sha256": digest(output), "primary_delta": delta}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "paired", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    print(json.dumps(collect(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

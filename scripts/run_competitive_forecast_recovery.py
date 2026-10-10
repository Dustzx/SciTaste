"""Finish exact-output collection and the reserved check after research terminates.

Never resume the researcher or modify source/selection after confirmation. The
failed original and all auxiliary output bytes remain separately retained.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scripts.recover_forecast_score_collection import recover
from scripts.run_forecast_outer_confirmation import run


def finish(
    project, study, *, queue_record="QUEUE_RECOVERY.json", collection_name="scitaste-native"
):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(project / "evaluations")
    specification = json.loads((study / "STUDY.json").read_text())
    assigned = specification["allocations"]["forecasting"]
    campaign = verified_asset(project, assigned["campaign"])
    source = project / assigned["run"]
    pack = study / "forecast-outer"
    original = campaign.parent / "confirmation/scitaste-native"
    if collection_name not in {"scitaste-native", "scitaste-native-v2"}:
        raise ValueError("Explicit bounded collection identity required")
    destination = campaign.parent / "scoring-recoveries" / collection_name
    if not re.fullmatch(r"QUEUE_RECOVERY(?:_V[2-9][0-9]*)?\.json", queue_record):
        raise ValueError("Queue record must be an explicit owned versioned filename")
    contract = {
        "schema_version": "competitive-forecast-output-recovery.v1",
        "started_at": datetime.now(UTC).isoformat(),
        "study_sha256": digest(study / "STUDY.json"),
        "original_failure_sha256": digest(original / "RESULT.json"),
        "inference_result_sha256": digest(original / "INFERENCE_RESULT.json"),
        "recovery_runtime_sha256": digest(Path(__file__)),
        "collection_runtime_sha256": digest(Path(recover.__code__.co_filename)),
        "outer_runtime_sha256": digest(Path(run.__code__.co_filename)),
        "original_outer_worker_stopped_before_any_outer_execution": not (
            pack / "execution"
        ).exists(),
        "stopped_original_outer_worker_sha256": (
            "777badbd3914a3ab9e86cdea8c43c4c4dc661dea9272def81789344be0c7b4b2"
        ),
        "stop_reason": (
            "Exact original output collection failed; explicit auxiliary projection required"
        ),
        "queue_record": queue_record,
        "collection_recovery_identity": collection_name,
        "scientific_array_identity_projection": collection_name == "scitaste-native-v2",
        "previous_queue_record_sha256": (
            digest(pack / "QUEUE_RECOVERY.json") if queue_record != "QUEUE_RECOVERY.json" else None
        ),
        "original_native_public_auxiliary_layout": "retained-original-native-public.v1",
        "original_failed_assignment_replaced": False,
        "source_repair_or_primary_reselection_allowed": False,
        "new_original_task_inference_runs": 0,
        "reserved_outer_inference_assignments": 2,
        "before_any_recovered_private_score": True,
        "outer_protocol_sha256": digest(pack / "PROTOCOL.json"),
        "formal_evidence_eligible": False,
    }
    retain_json(pack / queue_record, contract)
    deadline = time.monotonic() + 4500
    while not (source / "RESULT.json").is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Researcher remains active; no recovery scores exposed")
        time.sleep(10)
    # Publication of a recovery view cannot influence the original author endpoint.
    if not (destination / "RESULT.json").is_file():
        recover(
            project,
            campaign,
            original,
            destination,
            auxiliary_layout=(
                "competitive-cache-timing-v2"
                if collection_name == "scitaste-native-v2"
                else "competitive-cache-v1"
            ),
        )
    return run(project, pack, score_collection_recovery=destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "study"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--queue-record", default="QUEUE_RECOVERY.json")
    parser.add_argument("--collection-name", default="scitaste-native")
    args = parser.parse_args()
    value = finish(
        args.project,
        args.study,
        queue_record=args.queue_record,
        collection_name=args.collection_name,
    )
    print(json.dumps({key: row for key, row in value.items() if key != "assigned_procedures"}))

"""Execute two immutable public-selected forecast sources on a reserved outer set."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from scitaste.benchmark import forecasting_task_data as endpoint
from scitaste.benchmark.open_research import digest
from scitaste.executor.workspace_sandbox import command
from scitaste.model_nodes.session_exchange import retain_json
from scripts.recover_forecast_score_collection import (
    competitive_auxiliary,
    original_native_auxiliary,
    project_prediction_fields,
)


def execute(project, pack, name, source, *, execution_root=None):
    protocol = json.loads((pack / "PROTOCOL.json").read_text())
    source = source.resolve(strict=True)
    source.relative_to(project)
    recipe = json.loads((source / "SUBMISSION.json").read_text())
    owned = (pack / "execution" if execution_root is None else execution_root) / name
    owned.mkdir(parents=True, exist_ok=False)
    begin = time.monotonic()
    result = {
        "assignment": name,
        "primary_method": endpoint.primary_method(recipe),
        "primary_score": None,
        "status": "failed",
        "protocol_sha256": digest(pack / "PROTOCOL.json"),
        "source_manifest_sha256": digest(source / "SUBMISSION.json"),
        "formal_evidence_eligible": False,
    }
    try:
        release = owned / "release"
        endpoint.export_stage(pack, release, submission=source)
        retained = json.loads((release / "RELEASE.json").read_text())
        for filename, expected in retained["frozen_source"].items():
            if digest(source / filename) != expected:
                raise ValueError("Outer source does not match its original frozen source")
        target = owned / "target"
        target.mkdir()
        for filename in endpoint.target_assets(pack):
            shutil.copy2(release / filename, target / filename)
        predictions = owned / "predictions"
        argv = command(
            owned,
            [
                sys.executable,
                "/submission/" + recipe["entrypoint"],
                "--data",
                "/target",
                "--output",
                str(predictions),
            ],
            network=False,
            readonly={release / "frozen_submission": "/submission", target: "/target"},
        )
        retain_json(
            owned / "EXECUTION_CONTRACT.json",
            {
                "protocol_sha256": digest(pack / "PROTOCOL.json"),
                "source_manifest_sha256": result["source_manifest_sha256"],
                "source_locator": source.relative_to(project).as_posix(),
                "frozen_source": retained["frozen_source"],
                "public_selected_primary": result["primary_method"],
                "command": argv,
                "network_enabled": False,
                "gpu_enabled": False,
                "source_readonly": True,
                "private_labels_mounted": False,
                "timeout_seconds": 1800,
                "actual_supplier_api_calls": 0,
                "post_confirmation_selection_allowed": False,
            },
        )
        with (owned / "execution.log").open("x") as log:
            process = subprocess.Popen(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError("Outer frozen execution exceeded fixed allocation") from None
        result["return_code"] = code
        if code:
            raise RuntimeError("Frozen forecast execution failed; source repair forbidden")
        for filename, expected in retained["frozen_source"].items():
            if digest(release / "frozen_submission" / filename) != expected:
                raise ValueError("Read-only scientific source changed")
        hashes = {}
        for path in predictions.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Prediction outputs must be regular owned files")
            if path.is_file():
                hashes[path.relative_to(predictions).as_posix()] = digest(path)
        retain_json(
            owned / "INFERENCE_RESULT.json",
            {
                "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
                "prediction_sha256": hashes,
                "elapsed_seconds": time.monotonic() - begin,
                "before_private_scoring": True,
                "return_code": code,
            },
        )
        contexts = json.loads((pack / "PACK.json").read_text())["confirmation_contexts"]
        expected = {
            f"{context}--{method}.npz" for context in contexts for method in recipe["methods"]
        }
        if not expected <= hashes.keys():
            raise ValueError("Outer output is missing a declared target method")
        auxiliary = {name: sha for name, sha in hashes.items() if name not in expected}
        admitted_auxiliary = (
            (
                lambda filename: original_native_auxiliary(
                    filename, predictions=predictions, submission=recipe
                )
            )
            if name == "original-native"
            else (
                lambda filename: competitive_auxiliary(
                    filename,
                    predictions=predictions,
                    submission=recipe,
                    frozen=release / "frozen_submission",
                )
            )
        )
        if any(not admitted_auxiliary(filename) for filename in auxiliary):
            raise ValueError("Unknown outer auxiliary output; no silent method dropping")
        scoring = owned / "scoring-input"
        scoring.mkdir()
        field_projection = {}
        for name in sorted(expected):
            if digest(predictions / name) != hashes[name]:
                raise ValueError("Outer prediction bytes changed after execution")
            field_projection[name] = project_prediction_fields(
                predictions / name, scoring / name, timing_metadata=True
            )
        retain_json(
            owned / "OUTPUT_PROJECTION.json",
            {
                "policy": "all-declared-methods-with-identical-scientific-array-bytes.v2",
                "inference_result_sha256": digest(owned / "INFERENCE_RESULT.json"),
                "all_declared_target_predictions": {
                    name: hashes[name] for name in sorted(expected)
                },
                "auxiliary_outputs_retained": auxiliary,
                "field_projection": field_projection,
                "source_or_prediction_repair": False,
                "target_method_dropping": False,
                "before_private_scoring": True,
            },
        )
        score_path = endpoint.confirm_submission(pack, release / "RELEASE.json", scoring)
        scores = json.loads(score_path.read_text())
        result.update(
            status="scored",
            scores=scores,
            primary_score=scores["primary_scores"]["monthly"],
            score_sha256=digest(score_path),
            execution_contract_sha256=digest(owned / "EXECUTION_CONTRACT.json"),
            inference_result_sha256=digest(owned / "INFERENCE_RESULT.json"),
            output_projection_sha256=digest(owned / "OUTPUT_PROJECTION.json"),
            elapsed_seconds=time.monotonic() - begin,
            expected_series=protocol["series"],
            public_primary_unchanged=True,
        )
    except Exception as exc:
        result.update(
            error_type=type(exc).__name__, error=str(exc), elapsed_seconds=time.monotonic() - begin
        )
    retain_json(owned / "RESULT.json", result)
    return result


def run(project, pack, *, wait_seconds=7800, score_collection_recovery=None, export_recovery=False):
    project, pack = project.resolve(strict=True), pack.resolve(strict=True)
    pack.relative_to(project / "evaluations")
    if score_collection_recovery is not None:
        score_collection_recovery = score_collection_recovery.resolve(strict=True)
    protocol = json.loads((pack / "PROTOCOL.json").read_text())
    execution_root = None
    result_name = "RESULTS.json"
    if export_recovery:
        original_results = json.loads((pack / "RESULTS.json").read_text())
        for assignment, original in original_results["assigned_procedures"].items():
            if (
                original["status"] != "failed"
                or original.get("error") != "Export must be separate from the authoring pack"
                or (pack / "execution" / assignment / "EXECUTION_CONTRACT.json").exists()
                or (pack / "execution" / assignment / "INFERENCE_RESULT.json").exists()
            ):
                raise ValueError("Export recovery must precede both original source executions")
        execution_root = pack.parent / (pack.name + "-execution-recovery-v1")
        execution_root.relative_to(project / "evaluations")
        retain_json(
            pack / "EXPORT_RECOVERY_CONTRACT.json",
            {
                "protocol_sha256": digest(pack / "PROTOCOL.json"),
                "original_failure_results_sha256": digest(pack / "RESULTS.json"),
                "execution_root": execution_root.relative_to(project).as_posix(),
                "runtime_sha256": digest(Path(__file__)),
                "projection_runtime_sha256": digest(
                    Path(project_prediction_fields.__code__.co_filename)
                ),
                "source_execution_count_before_recovery": 0,
                "original_failures_replaced": False,
                "source_or_primary_change_allowed": False,
                "new_inference_assignments": 2,
                "before_any_outer_private_score": True,
                "formal_evidence_eligible": False,
            },
        )
        result_name = "RECOVERY_RESULTS.json"
    successor = project / protocol["assignments"]["successor-native"]
    # Outer results never enter public search or change an already frozen primary.
    deadline = time.monotonic() + wait_seconds
    while not (successor / "RESULT.json").is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Reserved outer check waits for terminal successor, no relaunch")
        time.sleep(10)
    # The campaign-owned path is derived rather than an arbitrary researcher directory.
    launch = json.loads((successor / "CONTRACT.json").read_text())
    campaign = project / launch["plan"]["campaign"]["locator"]
    confirmation = campaign.parent / "confirmation/scitaste-native"
    feedback = json.loads((confirmation / "RESULT.json").read_text())
    if feedback["status"] != "completed":
        if score_collection_recovery is None:
            raise ValueError("No original successor frozen confirmation exists for outer check")
        recovery = score_collection_recovery.resolve(strict=True)
        recovery.relative_to(campaign.parent / "scoring-recoveries")
        recovery_contract = json.loads((recovery / "CONTRACT.json").read_text())
        recovered = json.loads((recovery / "RESULT.json").read_text())
        if (
            recovered["status"] != "completed"
            or recovery_contract["original_failure_sha256"] != digest(confirmation / "RESULT.json")
            or recovery_contract["original_release_sha256"]
            != digest(confirmation / "release/RELEASE.json")
            or recovery_contract["new_inference_runs"] != 0
            or recovered["result"]["primary_method"]
            != json.loads((confirmation / "release/frozen_submission/SUBMISSION.json").read_text())[
                "primary_method"
            ]
        ):
            raise ValueError("Outer continuation requires exact unchanged-source score recovery")
    sources = {
        "original-native": project / protocol["assignments"]["original-native"],
        "successor-native": confirmation / "release/frozen_submission",
    }
    rows = {}
    for name, source in sources.items():
        root = pack / "execution" if execution_root is None else execution_root
        receipt = root / name / "RESULT.json"
        rows[name] = (
            json.loads(receipt.read_text())
            if receipt.is_file()
            else execute(project, pack, name, source, execution_root=execution_root)
        )
    old, new = rows["original-native"]["primary_score"], rows["successor-native"]["primary_score"]
    value = {
        "schema_version": "1.0",
        "protocol_sha256": digest(pack / "PROTOCOL.json"),
        "original_primary_retained": True,
        "successor_primary_retained": True,
        "assigned_procedures": rows,
        "primary_difference_new_minus_original": None if old is None or new is None else new - old,
        "relative_primary_error_reduction": None
        if old is None or new is None or old == 0
        else (old - new) / old,
        "independent_within_source_reserved_series": protocol["series"],
        "new_task_families": 0,
        "causal_taste_gain_established": False,
        "matched_backbone_or_budget_established": False,
        "formal_evidence_eligible": False,
        "supplier_api_calls": 0,
        "original_confirmation_status": feedback["status"],
        "original_outer_failures_retained": export_recovery,
        "export_recovery_contract_sha256": digest(pack / "EXPORT_RECOVERY_CONTRACT.json")
        if export_recovery
        else None,
        "score_collection_recovery": None
        if score_collection_recovery is None
        else {
            "locator": (score_collection_recovery / "RESULT.json").relative_to(project).as_posix(),
            "sha256": digest(score_collection_recovery / "RESULT.json"),
        },
    }
    retain_json(pack / result_name, value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "pack"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--score-collection-recovery", type=Path)
    parser.add_argument("--export-recovery", action="store_true")
    args = parser.parse_args()
    result = run(
        args.project,
        args.pack,
        score_collection_recovery=args.score_collection_recovery,
        export_recovery=args.export_recovery,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "assigned_procedures"}))

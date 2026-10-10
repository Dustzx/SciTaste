"""Score already executed, bound forecasts after an exact file-collection failure.

Never rerun inference, edit frozen source, change the primary or replace the
original failed assignment. All declared target methods must still be present.
"""

import argparse
import json
import re
import shutil
from pathlib import Path

import numpy as np

from scitaste.benchmark import forecasting_task_data
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.review.evidence_projection import aggregate_confirmation_view


def competitive_auxiliary(name, *, predictions, submission, frozen):
    """Recognize only this explicitly selected public/cache output layout."""
    if re.fullmatch(r"cache/[a-f0-9]{64}\.(fit|prediction)\.npz", name):
        return True
    if name == "SUBMISSION.json":
        return digest(predictions / name) == digest(frozen / name)
    if name == "PUBLIC.json":
        public = json.loads((predictions / name).read_text())
        return (
            public.get("primary_method") == submission["primary_method"]
            and public.get("methods") == submission["methods"]
        )
    if "--" not in name or "/" in name or not name.endswith("--losses.npz"):
        if "/" in name or not name.endswith(".npz") or "--" not in name:
            return False
        context, method = name.removesuffix(".npz").split("--", 1)
        return context in {"discovery", "validation"} and method in submission["methods"]
    context, method = name.removesuffix("--losses.npz").split("--", 1)
    return context in {"discovery", "validation"} and method in submission["methods"]


def original_native_auxiliary(name, *, predictions, submission):
    """The unchanged original Native writer's explicitly retained public layout."""
    if name in {"RUN_SUMMARY.json", "public/PUBLIC_STUDY.json"}:
        public = json.loads((predictions / name).read_text())
        return (
            public.get("primary_method") == submission["primary_method"]
            and public.get("methods") == submission["methods"]
        )
    if not name.startswith("public/") or name.count("/") != 1:
        return False
    filename = name.removeprefix("public/")
    if not filename.endswith(".npz") or "--" not in filename:
        return False
    context, method = filename.removesuffix(".npz").split("--", 1)
    return context in {"discovery", "validation"} and method in {*submission["methods"], "features"}


def project_prediction_fields(source, destination, *, timing_metadata=False):
    """Preserve every scientific array; optionally separate two timing diagnostics."""
    required = {"series_id", "forecast", "valid", "seconds"}
    optional = {"local_fit_seconds", "forecast_seconds"} if timing_metadata else set()
    with np.load(source, allow_pickle=False) as values:
        fields = set(values.files)
        if not required <= fields or fields - required - optional:
            raise ValueError("Unknown forecast fields; no score projection by guessing")
        arrays = {name: values[name].copy() for name in required}
        metadata = {name: values[name].copy() for name in fields - required}
    if not metadata:
        shutil.copy2(source, destination)
    else:
        np.savez_compressed(destination, **arrays)
    with np.load(destination, allow_pickle=False) as values:
        for name, original in arrays.items():
            projected = values[name]
            if (
                projected.dtype != original.dtype
                or projected.shape != original.shape
                or projected.tobytes() != original.tobytes()
            ):
                raise ValueError("Scientific forecast array changed during projection")
    return {
        "original_file_sha256": digest(source),
        "scoring_file_sha256": digest(destination),
        "scientific_fields_array_bytes_identical": True,
        "auxiliary_timing_fields_retained_in_original": sorted(metadata),
        "predictions_or_validity_repaired": False,
    }


def recover(project, campaign, original, output, *, auxiliary_layout="legacy"):
    project = project.resolve(strict=True)
    campaign = campaign.resolve(strict=True)
    original = original.resolve(strict=True)
    campaign.relative_to(project / "evaluations")
    original.relative_to(campaign.parent / "confirmation")
    output = output.resolve()
    output.relative_to(campaign.parent / "scoring-recoveries")
    contract = json.loads(campaign.read_text())
    failure = json.loads((original / "RESULT.json").read_text())
    inference = json.loads((original / "INFERENCE_RESULT.json").read_text())
    execution = json.loads((original / "EXECUTION_CONTRACT.json").read_text())
    old_release = original / "release/RELEASE.json"
    release = json.loads(old_release.read_text())
    pack = verified_asset(project, contract["pack"]).parent
    if (
        contract["task_id"] != forecasting_task_data.TASK_ID
        or failure.get("status") != "failed"
        or failure.get("error") != "Score every predeclared forecast procedure jointly"
        or inference["return_code"] != 0
        or not inference["before_private_scoring"]
        or execution["campaign_sha256"] != digest(campaign)
        or inference["execution_contract_sha256"] != digest(original / "EXECUTION_CONTRACT.json")
        or inference["release_sha256"] != digest(old_release)
        or execution["release_sha256"] != digest(old_release)
    ):
        raise ValueError("Require the exact bound post-inference collection failure")
    source_contract_name = (
        "EXECUTION_CONTRACT.json" if failure["arm"] == "autoresearchclaw" else "CONTRACT.json"
    )
    source_run = verified_asset(
        project,
        {
            "locator": execution["source_run"] + "/" + source_contract_name,
            "sha256": execution["source_contract_sha256"],
        },
    ).parent
    frozen = original / "release/frozen_submission"
    submission = json.loads((frozen / "SUBMISSION.json").read_text())
    if auxiliary_layout in {"competitive-cache-v1", "competitive-cache-timing-v2"}:
        # Verify an explicitly frozen competitive campaign, not a score-selected exemption.
        if contract.get("scientific_search_policy") != "evidence-directed-competitive-search-v1":
            raise ValueError("Cached auxiliary recovery requires a frozen competitive campaign")
    elif auxiliary_layout != "legacy":
        raise ValueError("Unknown auxiliary output layout")
    for name, expected in release["frozen_source"].items():
        source = (frozen / name).resolve(strict=True)
        source.relative_to(frozen.resolve(strict=True))
        if (frozen / name).is_symlink() or digest(source) != expected:
            raise ValueError("Original frozen source changed")
    predictions = original / "execution/predictions"
    actual = {}
    for path in sorted(predictions.rglob("*")):
        if path.is_symlink():
            raise ValueError("Outputs must remain regular retained files")
        if path.is_file():
            actual[path.relative_to(predictions).as_posix()] = digest(path)
    if actual != inference["output_sha256"]:
        raise ValueError("An original output changed after successful inference")
    contexts = json.loads((pack / "PACK.json").read_text())["confirmation_contexts"]
    expected = {
        f"{context}--{method}.npz" for context in contexts for method in submission["methods"]
    }
    if not expected <= actual.keys():
        raise ValueError("A predeclared target method is missing; no recovery by dropping it")
    extras = {name: value for name, value in actual.items() if name not in expected}
    allowed_contexts = {"discovery", "validation", *contexts}
    for name in extras:
        if auxiliary_layout in {
            "competitive-cache-v1",
            "competitive-cache-timing-v2",
        } and competitive_auxiliary(
            name, predictions=predictions, submission=submission, frozen=frozen
        ):
            continue
        stem = Path(name).stem
        if name in {
            "RUN.json",
            "summary.json",
            "per_series.csv",
            "PUBLIC_RESULTS.json",
            "RESULTS.json",
            "validation_mean_mase.svg",
            "discovery--analysis.npz",
            "validation--analysis.npz",
        }:
            continue
        if "--" not in stem:
            raise ValueError("Unrecognized auxiliary output")
        context, method = stem.split("--", 1)
        if context in {"discovery", "validation"} and method.endswith("--errors"):
            method = method.removesuffix("--errors")
        if context not in allowed_contexts or method not in {*submission["methods"], "diagnostics"}:
            raise ValueError("Unrecognized auxiliary output; do not silently discard it")
    output.mkdir(parents=True, exist_ok=False)
    retained = output / "release"
    retained.mkdir()
    shutil.copy2(old_release, retained / "RELEASE.json")
    shutil.copytree(frozen, retained / "frozen_submission")
    scoring = output / "scoring-input"
    scoring.mkdir()
    field_projection = {}
    for name in sorted(expected):
        field_projection[name] = project_prediction_fields(
            predictions / name,
            scoring / name,
            timing_metadata=auxiliary_layout == "competitive-cache-timing-v2",
        )
    retain_json(
        output / "CONTRACT.json",
        {
            "schema_version": "forecast-score-collection-recovery.v1",
            "campaign_sha256": digest(campaign),
            "original_failure_sha256": digest(original / "RESULT.json"),
            "inference_result_sha256": digest(original / "INFERENCE_RESULT.json"),
            "original_execution_contract_sha256": digest(original / "EXECUTION_CONTRACT.json"),
            "original_release_sha256": digest(old_release),
            "all_predeclared_target_predictions": {name: actual[name] for name in sorted(expected)},
            "field_projection": field_projection,
            "excluded_auxiliary_outputs_retained_in_original": extras,
            "auxiliary_layout": auxiliary_layout,
            "primary_method_unchanged": submission["primary_method"],
            "new_inference_runs": 0,
            "new_model_calls": 0,
            "original_failure_replaced": False,
            "formal_evidence_eligible": False,
        },
    )
    result = forecasting_task_data.confirm_submission(pack, retained / "RELEASE.json", scoring)
    feedback = {
        "arm": failure["arm"],
        "status": "completed",
        "result": json.loads(result.read_text()),
        "executed_frozen_source": True,
        "formal_evidence_eligible": False,
        "execution_contract_sha256": digest(original / "EXECUTION_CONTRACT.json"),
        "inference_result_sha256": digest(original / "INFERENCE_RESULT.json"),
        "explicit_scoring_collection_recovery_sha256": digest(output / "CONTRACT.json"),
        "original_failed_assignment_retained": True,
        "new_inference_runs": 0,
        "elapsed_seconds": failure["elapsed_seconds"],
    }
    retain_json(output / "RESULT.json", feedback)
    # Only a separate, visibly labelled receipt is delivered; the failure stays.
    view = json.loads(aggregate_confirmation_view((output / "RESULT.json").read_bytes()))
    workspace = source_run / ("work" if failure["arm"] == "autoresearchclaw" else "workspace")
    retain_json(workspace / "confirmation_scoring_recovery.json", view)
    return output / "RESULT.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "original", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument(
        "--auxiliary-layout",
        choices=("legacy", "competitive-cache-v1", "competitive-cache-timing-v2"),
        default="legacy",
    )
    args = parser.parse_args()
    print(
        recover(
            args.project,
            args.campaign,
            args.original,
            args.output,
            auxiliary_layout=args.auxiliary_layout,
        )
    )

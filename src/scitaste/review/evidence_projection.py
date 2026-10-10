"""Scientific views of oversized confirmations; never replace original evidence."""

import hashlib
import json


def aggregate_confirmation_view(raw: bytes) -> bytes:
    """Retain every aggregate/control and explicitly omit only unit-level display.

    This is a bounded read-only model input, not new scoring, sample selection or
    a replacement for the original receipt. Paired/stratified claims requiring
    omitted unit-level data cannot be established from this projection.
    """
    value = json.loads(raw)
    result = value.get("result", {})
    rows = result.get("scores", [])
    if (
        value.get("status") != "completed"
        or not value.get("executed_frozen_source")
        or result.get("status") != "scored-all-predeclared-procedures"
        or result.get("task_id")
        not in {
            "stable-physical-rollout",
            "cross-series-forecasting",
            "combinatorial-perturbation",
        }
        or not rows
    ):
        raise ValueError("Unrecognized aggregate confirmation")
    omitted = []
    for row in rows:
        metrics = row.get("metrics", {})
        for key in ("per_trajectory", "per_series", "per_condition"):
            if key not in metrics:
                continue
            units = metrics.pop(key)
            if not isinstance(units, list):
                raise ValueError("Unit-level confirmation records must be a list")
            omitted.append(
                {
                    "context": row["context"],
                    "method": row["method"],
                    "field": key,
                    "records": len(units),
                    "canonical_json_sha256": hashlib.sha256(
                        json.dumps(units, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                }
            )
    if not omitted:
        raise ValueError("No recognized unit-level evidence to project")
    result["review_projection"] = {
        "version": "complete-aggregate-view.v1",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "all_method_context_aggregate_values_and_qualification_flags_retained": True,
        "omitted_unit_level_display": omitted,
        "scope": (
            "Display projection only. No method/context removed, score recomputed, "
            "failure imputed, primary selected or qualification promoted. Original "
            "unit-level receipt remains authoritative. Do not infer paired effects, "
            "subgroup behavior or uncertainty from omitted records."
        ),
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def population_confirmation_view(raw: bytes) -> bytes:
    """Losslessly column-pack repeated group keys; do not drop subgroup evidence."""
    value = json.loads(raw)
    result = value.get("result", {})
    scores = result.get("scores", [])
    if (
        value.get("status") != "completed"
        or not value.get("executed_frozen_source")
        or result.get("task_id") != "population-shift-calibration"
        or result.get("status") != "scored-all-predeclared-procedures"
        or not scores
    ):
        raise ValueError("Unrecognized population confirmation")
    groups = [group for row in scores for group in row["metrics"]["group_diagnostics"]]
    if not groups or any(set(group) != set(groups[0]) for group in groups):
        raise ValueError("Population group records require a uniform explicit schema")
    constants = {
        key: groups[0][key]
        for key in groups[0]
        if all(group[key] == groups[0][key] for group in groups)
    }
    columns = [key for key in groups[0] if key not in constants]
    for row in scores:
        original = row["metrics"]["group_diagnostics"]
        row["metrics"]["group_diagnostics"] = [
            [group[key] for key in columns] for group in original
        ]
    result["group_diagnostic_columns"] = columns
    result["group_diagnostic_constant_fields"] = constants
    result["review_projection"] = {
        "version": "lossless-population-group-columns.v1",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "all_methods_contexts_groups_values_and_qualification_flags_retained": True,
        "omitted_fields": [],
        "scope": (
            "Lossless parsed-value representation, not scoring or new evidence. "
            "Reconstruct each group by zipping columns with its values, then adding "
            "constant fields. Preserve nulls, sparse-group flags and every group; "
            "no individual labels or paired uncertainty are supplied."
        ),
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def scientific_confirmation_view(raw: bytes) -> tuple[bytes, str]:
    """Select an explicit task-specific view, never summarize unknown evidence."""
    task = json.loads(raw).get("result", {}).get("task_id")
    if task == "population-shift-calibration":
        return population_confirmation_view(raw), "lossless-population-group-columns.v1"
    if task == "sensor-drift-probability-transfer":
        return sensor_confirmation_view(raw), "lossless-sensor-score-columns.v1"
    if task in {
        "stable-physical-rollout",
        "cross-series-forecasting",
        "combinatorial-perturbation",
    }:
        return aggregate_confirmation_view(raw), "complete-aggregate-view.v1; unit-level omitted"
    return microscopy_confirmation_view(raw), "microscopy-scientific-view-v1; partial field-level"


def sensor_confirmation_view(raw: bytes) -> bytes:
    """Column-pack every score and metric value, without omitting a procedure.

    Failure/null fields, class vectors, timing and prediction provenance remain.
    This changes parsed-value representation only, not the scoring or receipt.
    """
    value = json.loads(raw)
    result = value.get("result", {})
    rows = result.get("scores", [])
    if (
        value.get("status") != "completed"
        or value.get("executed_frozen_source") is not True
        or result.get("task_id") != "sensor-drift-probability-transfer"
        or not rows
        or any(not isinstance(row, dict) or set(row) != set(rows[0]) for row in rows)
        or any(not isinstance(row.get("metrics"), dict) for row in rows)
        or any(set(row["metrics"]) != set(rows[0]["metrics"]) for row in rows)
    ):
        raise ValueError("Unrecognized uniform sensor confirmation")
    row_constants = {
        key: rows[0][key]
        for key in rows[0]
        if key != "metrics" and all(row[key] == rows[0][key] for row in rows)
    }
    row_columns = [key for key in rows[0] if key not in row_constants]
    metric_constants = {
        key: rows[0]["metrics"][key]
        for key in rows[0]["metrics"]
        if all(row["metrics"][key] == rows[0]["metrics"][key] for row in rows)
    }
    metric_columns = [key for key in rows[0]["metrics"] if key not in metric_constants]
    result["scores"] = [
        [
            [row["metrics"][key] for key in metric_columns] if column == "metrics" else row[column]
            for column in row_columns
        ]
        for row in rows
    ]
    result["score_columns"] = row_columns
    result["score_constant_fields"] = row_constants
    result["metric_columns"] = metric_columns
    result["metric_constant_fields"] = metric_constants
    result["review_projection"] = {
        "version": "lossless-sensor-score-columns.v1",
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "all_method_context_metric_values_and_qualification_flags_retained": True,
        "omitted_fields": [],
        "scope": (
            "Lossless parsed-value display only, not new scoring or reproduction. "
            "Reconstruct each score by zipping score_columns and adding score_constant_fields; "
            "reconstruct its metrics with metric_columns plus metric_constant_fields. "
            "All class vectors, nulls, failures, timing and provenance remain."
        ),
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def compact_json_evidence(raw: bytes) -> bytes:
    """Remove JSON formatting whitespace without altering a token or field.

    Unlike parse-and-reserialize, this also retains the exact numeric literals.
    Strings, escaped quotes and Unicode bytes are untouched. Original evidence
    remains bound by its full SHA; this is input compaction, not a measurement.
    """
    json.loads(raw)
    output = bytearray()
    quoted = escaped = False
    for byte in raw:
        if quoted:
            output.append(byte)
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            output.append(byte)
            quoted = True
        elif byte not in b" \t\r\n":
            output.append(byte)
    return bytes(output)


def bounded_json_evidence(raw: bytes, remaining: int) -> tuple[bytes, str]:
    """Prefer known lossless packing so later provenance still has input space."""
    task = json.loads(raw).get("result", {}).get("task_id")
    if task == "sensor-drift-probability-transfer":
        return scientific_confirmation_view(raw)
    compacted = compact_json_evidence(raw)
    if len(compacted) <= remaining:
        return compacted, "lossless-json-whitespace-compaction.v1; every field/token retained"
    return scientific_confirmation_view(raw)


def microscopy_confirmation_view(raw: bytes) -> bytes:
    """Keep every method/budget mean and field PSNR/SSIM/frequency error.

    Reference half diagnostics are retained per field when identical across all
    predictions. Variable per-field reference errors and corrected MSE are omitted
    explicitly, not rounded, imputed or presented as visible evidence. A review
    requiring them must withhold its inference or request the original record.
    """
    value = json.loads(raw)
    result = value.get("result", {})
    rows = result.get("scores", [])
    if (
        value.get("arm") != "scitaste-native"
        or result.get("status") != "scored-all-predeclared-procedures"
        or not rows
        or any(row.get("task_id") != "microscopy-structure-restoration" for row in rows)
    ):
        raise ValueError("Oversized evidence is not a recognized microscopy confirmation")
    projected = []
    field_keys = ("fov_id", "psnr_db", "ssim", "bandpass_mse")
    constants = {
        key: rows[0][key]
        for key in rows[0]
        if key != "fovs" and all(row.get(key) == rows[0][key] for row in rows)
    }
    diagnostics = {}
    omitted = set()
    diagnostic_keys = (
        "half_reference_mse",
        "conditional_reference_noise_floor",
        "bandpass_half_agreement",
        "reference_independence_stationarity_verified",
    )
    for row in rows:
        fields = row["fovs"]
        projected.append(
            {
                **{
                    key: item for key, item in row.items() if key != "fovs" and key not in constants
                },
                "per_field_values": [[field[key] for key in field_keys] for field in fields],
            }
        )
        for field in fields:
            omitted.update(set(field) - set(field_keys) - set(diagnostic_keys))
            key = str(field["fov_id"])
            current = {name: field[name] for name in diagnostic_keys}
            if key in diagnostics and diagnostics[key] != current:
                raise ValueError("Reference diagnostics vary; cannot imply a common field value")
            diagnostics[key] = current
    result["scores"] = projected
    result["score_constant_fields"] = constants
    result["per_field_columns"] = field_keys
    result["reference_diagnostics_by_field"] = diagnostics
    result["review_projection"] = {
        "version": "microscopy-scientific-view-v1",
        "all_method_budget_aggregate_fields_retained": True,
        "per_field_omitted_keys": sorted(omitted),
        "interpretation": (
            "Partial per-field view, not a replacement score or new measurement. "
            "All original mean metrics and flags are exact. Omitted reference-error "
            "and corrected-MSE details cannot establish assumptions, significance "
            "or biological validity; original record is bound by its full SHA256."
        ),
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()

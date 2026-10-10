"""Author a prefix-grouped research task from the Monash M4 monthly archive."""
# ruff: noqa: E501 -- Frozen scientific contract and explicit limits.

import argparse
import hashlib
import json
import shutil
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json

TASK_ID = "cross-series-forecasting"
SEED = "scitastebench/m4-monthly/v1/20261008"
SOURCE_SHA = "473aa4fc814b625174be2b5615959f35f85f566fbed09c30acf44c350b2a1efe"
COUNTS = {"fit": 4000, "discovery": 500, "validation": 500, "confirmation": 1000}
HORIZON, MIN_HISTORY, MAX_HISTORY, PERIOD = 18, 72, 360, 12

BRIEF = """# When does cross-series learning help a heterogeneous forecast?

Investigate which observable evidence supports a forecast for a previously unseen
series. Form competing explanations for cross-series pooling, scale normalization,
seasonality and sensitivity to recent change. Execute discriminating controls;
renaming a known global model or observing a score improvement is not by itself a
scientific contribution. A justified failure boundary or negative result is valid.

## Source and information boundaries

Monash Time Series Forecasting Archive (NeurIPS 2021 Datasets and Benchmarks)
supplies real M4 monthly competition series spanning heterogeneous domains.
This authored subset is NOT the full M4 leaderboard or the official competition
ranking. The final 18 observations are the original forecasting horizon; histories
use at most their latest 360 preceding observations. Series with fewer than 72
history observations are excluded by an input-length rule, not forecast outcomes.
Exact permitted-history hashes group duplicates before interpreting future numeric
values. Fit, discovery, validation and confirmation use disjoint groups selected
by a frozen hash order. Unknown near duplicates, shared economic drivers, sector
dependencies and controller pretraining exposure remain limits. One source family,
not a research task for every series or horizon. Absolute calendar/sector labels
are not supplied, so do not invent calendar alignment or claim sector transfer.

All NPZ histories are zero-padded on the LEFT to length 360; history_length[N]
distinguishes padding from actual zero observations. Fields are series_id[N] integer,
history[N,360], history_length[N]. Fit has 4000 histories only; train parameters and
representations from rolling windows WITHIN those histories, never their original
18-point future targets. Discovery and validation each have 500 disjoint histories
and future[N,18]. Use these futures to analyze explanations/select fixed settings,
not fit or augment global predictive coefficients. Confirmation has 1000 new
histories with private futures. Public validation uses the same horizon, so this
is new-series confirmation, not unseen-time-distribution extrapolation.

Global predictive parameters fit the supplied training histories only. Ordinary
local estimation or a backtest on an individual query's observed history is legal
if its rule is fixed before READY; it may not use the query's withheld future or
adapt global representations across query groups. No original source/archive,
outside future table, pretrained competition model, other project/run or private
identity access. Parameter-fitting models and training-free fixed rules are both
experimental subjects; this does not require training the SciTaste controller.

## Outcomes and scientific explanation

Freeze exactly one public-selected primary_method BEFORE READY. Primary outcome
is mean per-series MASE on the complete 18-point forecast: mean absolute forecast
error divided by mean |history[t]-history[t-12]|, with explicit 1e-8 denominator
floor on the same permitted history. Retain median/p90 MASE, absolute errors,
sMAPE (zero/zero contribution 0, legacy diagnostic) and near-zero scale counts.
Metrics are not pooled across other task domains; MASE is not causal insight.
The fixed-length horizon is not multiple independent experiments. No original
M4 OWA or full-population ranking is implied by subset metrics.

Test explanations using actual controls: normalization and training weights,
local versus global capacity, history truncation and seasonal/trend alternatives
must not silently change exposure or test information. A recent-change feature
is an observed predictor, not a certified structural break. Analyze failure and
tail cases rather than selecting a favorable group after confirmation. Measure
fitting/inference cost separately. reference.py provides ordinary naive/seasonal/
drift and pooled linear controls, not modern neural-model competitiveness or any
autonomous-framework outcome. Stronger methods can be developed in the shared
allocation, but describe known methods as controls rather than new discoveries.

## Ordinary control policy, revision 2

The original pooled_normalized implementation is retained only as a pathological
standard-deviation-floor diagnostic, not the sole normalized comparator or a
credible target to beat. pooled_level_normalized uses observed-window RMS, floored
at 0.01 times the median positive RMS of permitted training windows (all-zero
training-input fallback: 1). The same training-input-only floor applies at query
time; no row is excluded using its continuation or forecast result.
pooled_balanced_raw and pooled_level_normalized expose identical 36-lag/18-target
rolling windows within fit histories. Each window weight is inverse window count
of its own training series, so each series has equal total fit weight. Both use
column-scaled ridge with penalty 1e-3. Centering/scaling changes the squared-error
target units and regularization geometry: their difference is NOT an isolated
normalization effect. Any causal interpretation requires the researcher's actual
loss-, exposure- and capacity-matched controls. The global RMS floor is equivariant
under a common unit rescaling but not arbitrary per-series rescaling. A constant
window does not prove its future is constant; this control does not invent such
a guarantee. No modern forecast competitiveness is certified by this correction.

## Frozen execution and research-to-paper delivery

The entrypoint accepts --data DIRECTORY --output DIRECTORY, independently replays
its training/public selection and follows QUERY.json. Public histories/futures
and a redacted monthly query are mounted, not caches or private labels. Emit
monthly--METHOD.npz for EVERY declared method containing series_id[N],
forecast[N,18] finite real, valid[N] boolean, seconds[N] finite nonnegative.
All IDs remain present. Failed series use valid=false with finite placeholders;
any failure leaves the complete endpoint missing, not a survivor mean or zero
imputation. Freeze SUBMISSION.json and all helpers, then write READY once.
The trusted service snapshots source before query inputs, executes unchanged
offline and scores all procedures jointly once. No post-READY source repair,
best-private-method selection or manual confirmation. Read actual
confirmation_feedback.json before interpreting results or writing the final paper.
Retain real code, measurements, evidence-linked figures, a full manuscript and
grounded critique/revision. A persuasive narrative cannot replace measured evidence.
"""


def build(source, output):
    source = source.resolve(strict=True)
    started = time.monotonic()
    archive = source / "m4_monthly_dataset.zip"
    receipt = json.loads((source / "ACQUISITION.json").read_text())
    if digest(archive) != SOURCE_SHA or receipt["sha256"] != SOURCE_SHA:
        raise ValueError("Wrong original archive bytes")
    metadata = json.loads((source / "SOURCE_METADATA.json").read_text())
    if metadata["metadata"]["license"]["id"] != "cc-by-4.0":
        raise ValueError("Wrong source rights")
    output.mkdir(parents=True, exist_ok=False)
    public, private, target = output / "public" / TASK_ID, output / "private", output / "target"
    for folder in (public, private, target):
        folder.mkdir(parents=True)
    groups, total, excluded, header = {}, 0, 0, []
    with zipfile.ZipFile(archive) as z:
        if z.namelist() != ["m4_monthly_dataset.tsf"]:
            raise ValueError("Unexpected archive layout")
        with z.open("m4_monthly_dataset.tsf") as stream:
            in_data = False
            for raw in stream:
                line = raw.decode("cp1252").strip()
                if not line or line.startswith("#"):
                    continue
                if not in_data:
                    header.append(line)
                    if line.lower() == "@data":
                        in_data = True
                    continue
                original_id, timestamp, values_text = line.split(":")
                tokens = values_text.split(",")
                history_tokens = tokens[:-HORIZON]
                total += 1
                if len(history_tokens) < MIN_HISTORY:
                    excluded += 1
                    continue
                observed = np.asarray(history_tokens[-MAX_HISTORY:], dtype="<f8")
                if not np.isfinite(observed).all():
                    raise ValueError("Invalid observed history; no outcome-driven exclusion")
                key = hashlib.sha256(observed.tobytes()).hexdigest()
                # Future strings are not interpreted or used in grouping/selection.
                groups.setdefault(key, []).append(
                    (original_id, timestamp, observed, tokens[-HORIZON:])
                )
    if (
        total != 48000
        or "@frequency monthly" not in header
        or "@horizon 18" not in header
        or "@missing false" not in header
        or len(groups) < sum(COUNTS.values())
    ):
        raise ValueError("Source schema/population differs")
    ordered = sorted(
        groups, key=lambda key: hashlib.sha256((SEED + ":" + key).encode()).hexdigest()
    )
    assigned, offset = {}, 0
    for phase, count in COUNTS.items():
        assigned[phase] = ordered[offset : offset + count]
        offset += count
    frozen_at = datetime.now(UTC).isoformat()
    retain_json(
        private / "SPLIT_FREEZE.json",
        {
            "frozen_at": frozen_at,
            "before_future_numeric_interpretation": True,
            "source_sha256": SOURCE_SHA,
            "seed": SEED,
            "groups": assigned,
            "identity_rule": "SHA256 of all permitted capped float64 history bytes",
            "source_series": total,
            "excluded_short_history": excluded,
            "distinct_groups": len(groups),
            "exact_duplicate_groups": sum(len(rows) > 1 for rows in groups.values()),
            "near_duplicate_or_shared_driver_independence": "unknown",
        },
    )
    for phase, keys in assigned.items():
        rows = [groups[key][0] for key in keys]
        ids = np.asarray(
            [
                int(hashlib.sha256((SEED + ":id:" + key).encode()).hexdigest()[:15], 16)
                for key in keys
            ],
            dtype=np.int64,
        )
        histories = np.zeros((len(rows), MAX_HISTORY), dtype=np.float64)
        lengths = np.asarray([len(row[2]) for row in rows], dtype=np.int64)
        for index, row in enumerate(rows):
            histories[index, -lengths[index] :] = row[2]
        arrays = {"series_id": ids, "history": histories, "history_length": lengths}
        if phase == "fit":
            np.savez_compressed(public / "train.npz", **arrays)
            continue
        futures = np.asarray([row[3] for row in rows], dtype=np.float64)
        if futures.shape != (len(rows), HORIZON) or not np.isfinite(futures).all():
            raise ValueError("Invalid future source values; refuse rather than select other cases")
        if phase == "confirmation":
            np.savez_compressed(target / "monthly-query.npz", **arrays)
            np.savez_compressed(private / "monthly-labels.npz", **arrays, future=futures)
        else:
            np.savez_compressed(public / f"{phase}.npz", **arrays, future=futures)
    claims = [
        {
            "claim_id": "prediction",
            "obligation": "Report every frozen procedure on complete new-series confirmation; retain failures",
        },
        {
            "claim_id": "learning_boundary",
            "obligation": "Global fits use training histories only; local query-history estimation and public selection disclosed",
        },
        {
            "claim_id": "scientific_explanation",
            "obligation": "Actual controls distinguish scale, pooling, capacity and recent-history explanations without oracle selection",
        },
        {
            "claim_id": "generalization",
            "obligation": "New-series, capped-history monthly subset is not unseen temporal law, sector transfer or full M4 leaderboard",
        },
        {
            "claim_id": "reproduction",
            "obligation": "Self-contained frozen source fits/predicts offline with all IDs and original source boundaries",
        },
        {
            "claim_id": "cost_and_novelty",
            "obligation": "Measure fit/inference cost; known normalizers and global/local predictors are not new discovery alone",
        },
    ]
    retain_json(
        public / "PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": claims,
            "inventories": COUNTS,
            "horizon": HORIZON,
            "period": PERIOD,
            "min_history": MIN_HISTORY,
            "max_history": MAX_HISTORY,
            "padding": "zeros on left; history_length is authoritative",
            "primary_endpoint": "mean_mase",
            "mase_denominator_floor": 1e-8,
            "confirmation_contexts": ["monthly"],
            "subject_routes": ["parameter-fitting", "training-free-fixed-rule"],
            "source_type": "real competition time series",
            "confirmation_construct": "new permitted-history groups",
            "original_calendar_and_sector_metadata_released": False,
            "source_counts": {
                "original_series": total,
                "short_excluded": excluded,
                "distinct_permitted_history_groups": len(groups),
            },
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "role": "Fresh independent evidence-linked reviewer; not expert gold or publication acceptance",
            "task_id": TASK_ID,
            "claim_rubric": claims,
            "outcome": "Distinguish scientific validity, important insight and reproducible execution; narrowing a claim cannot invent missing measurements",
            "rights": "CC BY4.0 archive with original competition attribution; all materials for authorized local research",
        },
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "predict.py",
            "files": ["predict.py"],
            "methods": ["primary", "control"],
            "primary_method": "REPLACE_WITH_PUBLIC_SELECTED_METHOD",
            "fit_policy": "REPLACE_WITH_ACTUAL_TRAINING_AND_LOCAL_ESTIMATION_RULE",
            "selection_rule": "REPLACE_WITH_PUBLIC_RULE_BEFORE_READY",
            "hypotheses": [
                {
                    "statement": "REPLACE_WITH_EXPLANATION",
                    "discriminating_prediction": "REPLACE_WITH_CONTROL_AND_PREDICTION",
                },
                {
                    "statement": "REPLACE_WITH_ALTERNATIVE",
                    "discriminating_prediction": "REPLACE_WITH_ALTERNATIVE_PREDICTION",
                },
            ],
            "scope": "REPLACE_WITH_NEW_SERIES_SUBSET_LIMITS",
        },
    )
    retain_json(
        target / "QUERY.json",
        {
            "task_id": TASK_ID,
            "contexts": {"monthly": "monthly-query.npz"},
            "horizon": HORIZON,
            "period": PERIOD,
            "labels_released": False,
        },
    )
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "Source: Monash Time Series Forecasting Archive, NeurIPS 2021 Datasets and Benchmarks; original M4 competition. Author-linked DOI 10.5281/zenodo.4656480 version 3, CC BY 4.0. This authored capped-history subset is not the full original evaluation. Original source/model exposure unknown.\n"
    )
    shutil.copy2(Path(__file__).with_name("forecasting_task_reference.py"), public / "reference.py")
    discovery = sorted(p.relative_to(output).as_posix() for p in public.iterdir() if p.is_file())
    transfer = sorted(p.relative_to(output).as_posix() for p in target.iterdir() if p.is_file())
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    manifest = {
        "schema_version": "scitastebench.forecasting-task-pack.v2",
        "task_id": TASK_ID,
        "family": "monash-m4-monthly",
        "frozen_at": frozen_at,
        "source_sha256": SOURCE_SHA,
        "files": files,
        "discovery_files": discovery,
        "transfer_files": transfer,
        "confirmation_contexts": ["monthly"],
        "task_families": 1,
        "formal_evidence_eligible": False,
        "quality_admitted": False,
        "authoring_development_only": False,
        "research_outcomes_before_freeze": False,
        "future_numeric_values_used_for_selection": False,
        "public_source_contamination": "unknown",
        "build_seconds": time.monotonic() - started,
        "inventories": COUNTS,
        "scope": "Prospectively authored new-series monthly research adaptation; not official full M4 or a quality certification",
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in {"files", "discovery_files", "transfer_files"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)

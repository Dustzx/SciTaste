"""Author household-disjoint ACS calibration research before system outcomes."""
# ruff: noqa: E501 -- Complete scientific contract and source caveats.

import argparse
import hashlib
import json
import shutil
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from scitaste.benchmark.graph_task_data import digest, retain_json

TASK_ID = "population-shift-calibration"
SEED = "scitastebench/acs-population/v1/20261008"
FEATURES = ("AGEP", "COW", "SCHL", "MAR", "OCCP", "POBP", "RELP", "WKHP", "SEX", "RAC1P")
SOURCES = {
    (2014, "ca"): {"fit": 5000, "discovery": 750, "validation": 750},
    (2014, "tx"): {"discovery": 750, "validation": 750},
    (2018, "ca"): {"california_later": 1500},
    (2018, "ny"): {"new_york_later": 1500},
}
BRIEF = """# Which calibration evidence transfers across populations?

Develop and test a probability-prediction hypothesis for income classification
under geographic and temporal population variation. Distinguish ranking changes,
class prevalence, calibration and the effects of representation/model capacity.
Construct actual controls; lower Brier score alone does not identify a calibration
mechanism. A justified negative finding or applicability boundary is valid.
Known calibration or reweighting recipes are controls, not novel methods by name.

## Original source and population

Retiring Adult (NeurIPS 2021 main conference) introduces ACS/Folktables prediction
tasks. This adaptation uses original Census ACS one-year person PUMS records;
the task label is PINCP > 50000 among people with AGEP >16, WKHP >0, PINCP >100
and PWGTP >=1. This is a nominal-dollar statistical label, NOT comparable real
income, a causal socioeconomic conclusion, national inference or a deployment
decision. Public inputs retain source sex/race codes for statistical diagnostics.
No re-identification, linkage to any outside person/household information, or
individual deployment is permitted. Preserve original attribution; code licenses
do not grant permission to redistribute source or derived records.

Before numeric income is interpreted, source year/state/household identifiers
define the deterministic group split. All eligible persons of a selected household
remain together. Source files contain raw outcomes, so this is numeric input-key
assignment, not byte-blind access or absence from model pretraining. Eligibility
uses income by the source task definition; we do not call eligibility label-blind.
Unknown repeated individuals, near duplicates and wider regional dependencies
remain limits. Person/household IDs are opaque; neither is a separate research task.

Training contains eligible persons from 5000 sampled California-2014 households.
Public discovery and validation each have 750 distinct California-2014 and 750
Texas-2014 households, with all their eligible persons. Global representations,
predictors and calibration parameters fit training only; labelled discovery and
validation select fixed configurations and diagnose explanations, not supply
additional fitted parameters. Use household-aware cross-fitting within training
for calibration. Public context=0 means CA-2014; context=1 means TX-2014.
Confirmation samples 1500 CA-2018 and 1500 NY-2018 households separately. CA-2018
changes year; NY-2018 changes year AND geography. Their contrast is descriptive,
not a randomized geography effect or a certified new causal distribution.

NPZ public fields: person_id[N] and household_id[N] int64; x[N,10] float64;
target[N] binary; weight[N] positive original PWGTP; sex[N], race[N] original
codes; context[N] integers. Feature order: AGEP,COW,SCHL,MAR,OCCP,POBP,RELP,WKHP,
SEX,RAC1P. Only missing feature values map to zero, an explicit missing/universe
code; features remain source codes, not automatically meaningful real distances.
Query files omit target. Original archive, outside labels, pretrained task model
or private pack access is forbidden. Fixed train-only predictors and predefined
training-free probability rules are both legal experimental subjects.

## Endpoints and controls

Freeze exactly one public-selected primary_method BEFORE READY. Primary is
person-survey-weighted Brier score, reported separately on each complete target
population; lower is better. Do not collapse tasks/contexts into a quality score.
Weighted AUC, fixed-threshold accuracy, signed calibration-in-the-large,
unweighted Brier, original-code group diagnostics, explicit failures and cost
are distinct. Lower proper-score loss is not a fairness or causal certificate.
Group TPR with fewer than 20 positive persons is unavailable, not zero; the
diagnostic threshold does not certify stable uncertainty. Survey weights describe
the sampled eligible state/year population, not all US residents.

Separate probability recalibration from threshold changes and discrimination.
Use identical exposure and capacity where attributing a mechanism; diagnose
class-prevalence and group-conditioned shifts using public data. Unknown transfer
premises justify abstention or narrower interpretation, not invention of target
labels. reference.py supplies constant, one-hot logistic and histogram-boosted
train-only controls. Beating a deliberately weak constant is not sufficient
scientific insight. The three controls do not certify modern model superiority.

## Genuine research delivery and one-time confirmation

Retain code, actual measurements and informative evidence-linked figures, plus
report/report.md and native framework delivery. Declare all methods, one primary,
fitting and public-selection rules, competing hypotheses and meaningful scope in
submission/SUBMISSION.json; include every source/helper in files. Write
submission/READY once. Entrypoint accepts --data DIRECTORY --output DIRECTORY,
replays permitted training itself and follows QUERY.json contexts. Emit
CONTEXT--METHOD.npz for EVERY declared method/target containing exactly
person_id[N] int64, probabilities[N,2] normalized finite nonnegative class
probabilities, valid[N] booleans and seconds[N] finite nonnegative inference cost.
Retain all persons including failures; any failure leaves complete Brier missing,
not a survivor score or zero-imputed success. The trusted evaluator freezes source
before queries, executes it unchanged offline once and scores all methods jointly.
No post-READY source repair or best-private-method substitution. Read actual
confirmation_feedback.json before final claims. A persuasive paper cannot replace
actual experiments or establish novelty from cautious prose.
"""


def identifier(value):
    return int(hashlib.sha256((SEED + ":" + value).encode()).hexdigest()[:15], 16)


def build(source, output):
    source = source.resolve(strict=True)
    receipt = json.loads((source / "ACQUISITION.json").read_text())
    records = {(row["year"], row["state"]): row for row in receipt["records"]}
    if receipt["status"] != "acquired-original-statistical-source" or set(records) != set(SOURCES):
        raise ValueError("Wrong fixed original ACS sources")
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    public, private, target = output / "public" / TASK_ID, output / "private", output / "target"
    for folder in (public, private, target):
        folder.mkdir(parents=True)
    assigned, archive_members = {}, {}
    for (year, state), counts in SOURCES.items():
        record = records[year, state]
        path = (source / record["file"]).resolve(strict=True)
        path.relative_to(source)
        if digest(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError("Original source bytes changed")
        with zipfile.ZipFile(path) as archive:
            csv = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(csv) != 1:
                raise ValueError("Unexpected original person-file archive layout")
            archive_members[year, state] = csv[0]
            with archive.open(csv[0]) as stream:
                identities = pd.read_csv(stream, usecols=["SERIALNO"], dtype={"SERIALNO": str})
        if identities["SERIALNO"].isna().any():
            raise ValueError("Missing household identity; do not invent grouping")
        households = sorted(
            set(identities["SERIALNO"]),
            key=lambda key: identifier(f"group:{year}:{state}:{key}"),
        )
        if len(households) < sum(counts.values()):
            raise ValueError("Insufficient original households")
        start = 0
        assigned[year, state] = {}
        for split, count in counts.items():
            assigned[year, state][split] = households[start : start + count]
            start += count
    frozen_at = datetime.now(UTC).isoformat()
    retain_json(
        private / "SPLIT_FREEZE.json",
        {
            "frozen_at": frozen_at,
            "before_numeric_income_interpretation": True,
            "household_assignments": {
                f"{year}-{state}": rows for (year, state), rows in assigned.items()
            },
            "source_hashes": {
                f"{year}-{state}": row["sha256"] for (year, state), row in records.items()
            },
            "seed": SEED,
            "eligibility_uses_income": True,
            "person_or_near_duplicate_independence": "unknown",
        },
    )
    collected = {}
    for (year, state), splits in assigned.items():
        with zipfile.ZipFile(source / records[year, state]["file"]) as archive:
            with archive.open(archive_members[year, state]) as stream:
                frame = pd.read_csv(
                    stream,
                    usecols=["SERIALNO", "SPORDER", "PWGTP", "PINCP", *FEATURES],
                    dtype={"SERIALNO": str},
                )
        # The original 2014 person CSV encodes out-of-universe numeric fields
        # as one ASCII space. Recognize only empty/whitespace missing values;
        # reject other nonnumeric source tokens instead of silently coercing them.
        for column in ["SPORDER", "PWGTP", "PINCP", *FEATURES]:
            values = frame[column]
            if values.dtype == object:
                values = values.astype("string").str.strip().replace("", pd.NA)
            frame[column] = pd.to_numeric(values, errors="raise")
        eligible = (frame.AGEP > 16) & (frame.WKHP > 0) & (frame.PINCP > 100) & (frame.PWGTP >= 1)
        frame = frame.loc[eligible]
        for split, households in splits.items():
            selected = frame.loc[frame.SERIALNO.isin(households)].copy()
            ids = np.array(
                [
                    identifier(f"person:{year}:{state}:{h}:{int(order)}")
                    for h, order in zip(selected.SERIALNO, selected.SPORDER, strict=True)
                ],
                dtype=np.int64,
            )
            hids = np.array(
                [identifier(f"household:{year}:{state}:{h}") for h in selected.SERIALNO],
                dtype=np.int64,
            )
            x = selected[list(FEATURES)].to_numpy(dtype=float)
            x[np.isnan(x)] = 0
            arrays = {
                "person_id": ids,
                "household_id": hids,
                "x": x,
                "target": (selected.PINCP.to_numpy() > 50000).astype(np.int64),
                "weight": selected.PWGTP.to_numpy(dtype=float),
                "sex": selected.SEX.to_numpy(dtype=np.int64),
                "race": selected.RAC1P.to_numpy(dtype=np.int64),
                "context": np.full(
                    len(selected),
                    0 if state == "ca" else (1 if state == "tx" else 2),
                    dtype=np.int64,
                ),
            }
            if not len(ids) or len(np.unique(ids)) != len(ids) or not np.isfinite(x).all():
                raise ValueError("Invalid original source rows; refuse rather than resample")
            collected.setdefault(split, []).append(arrays)
    inventories = {}
    for split, blocks in collected.items():
        arrays = {key: np.concatenate([block[key] for block in blocks]) for key in blocks[0]}
        inventories[split] = {
            "persons": len(arrays["person_id"]),
            "eligible_households": len(np.unique(arrays["household_id"])),
        }
        if split in {"fit", "discovery", "validation"}:
            name = "train" if split == "fit" else split
            np.savez_compressed(public / f"{name}.npz", **arrays)
        else:
            np.savez_compressed(private / f"{split}-labels.npz", **arrays)
            np.savez_compressed(
                target / f"{split}-query.npz",
                **{key: value for key, value in arrays.items() if key != "target"},
            )
    claims = [
        {
            "claim_id": "prediction",
            "obligation": "Retain every procedure/population and failures; distinguish proper score, ranking and threshold diagnostics",
        },
        {
            "claim_id": "learning_boundary",
            "obligation": "All fitted parameters use training only; group-aware calibration and public selection accurately stated",
        },
        {
            "claim_id": "scientific_explanation",
            "obligation": "Actual controls separate calibration, prevalence, capacity and discrimination or leave causal mechanism unresolved",
        },
        {
            "claim_id": "population_scope",
            "obligation": "Household/nominal-label/survey-weight and joint year-geography limits retained; no national or causal inference",
        },
        {
            "claim_id": "reproduction",
            "obligation": "Self-contained unchanged offline program, full unique IDs/probabilities, original source rights and privacy preserved",
        },
        {
            "claim_id": "cost_and_novelty",
            "obligation": "Actual fit/inference cost retained; known methods and small score gains are not novel discovery alone",
        },
    ]
    contexts = list(SOURCES[2018, "ca"]) + list(SOURCES[2018, "ny"])
    protocol = {
        "task_id": TASK_ID,
        "claim_rubric": claims,
        "inventories": inventories,
        "feature_order": FEATURES,
        "confirmation_contexts": contexts,
        "primary_endpoint": "weighted_brier",
        "subject_routes": ["parameter-fitting", "training-free-fixed-rule"],
        "formal_evidence_eligible": False,
    }
    retain_json(public / "PROTOCOL.json", protocol)
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": claims,
            "role": "Fresh evidence-linked reviewer, not expert gold or venue approval",
            "limits": "Predictive loss and demographic diagnostics are not causal or fairness certification",
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
            "fit_policy": "REPLACE_WITH_TRAIN_ONLY_RULE",
            "selection_rule": "REPLACE_WITH_PUBLIC_SELECTION_RULE",
            "hypotheses": [
                {
                    "statement": "REPLACE_WITH_EXPLANATION",
                    "discriminating_prediction": "REPLACE_WITH_CONTROL",
                },
                {
                    "statement": "REPLACE_WITH_ALTERNATIVE",
                    "discriminating_prediction": "REPLACE_WITH_ALTERNATIVE_CONTROL",
                },
            ],
            "scope": "REPLACE_WITH_ACTUAL_LIMITS",
        },
    )
    retain_json(
        target / "QUERY.json",
        {
            "task_id": TASK_ID,
            "contexts": {c: f"{c}-query.npz" for c in contexts},
            "labels_released": False,
        },
    )
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "Original Census ACS one-year person PUMS; ACSIncome task defined by Retiring Adult (NeurIPS 2021). Authored household-sampled nominal-income adaptation, not official national inference. Statistical research only; no re-identification, outside identity linkage, deployment, or raw/derived redistribution approval. https://www.census.gov/data/developers/about/terms-of-service.html\n"
    )
    shutil.copy2(Path(__file__).with_name("population_shift_reference.py"), public / "reference.py")
    manifest = {
        "schema_version": "scitastebench.population-shift-task-pack.v1",
        "task_id": TASK_ID,
        "family": "census-acs-calibration",
        "frozen_at": frozen_at,
        "source_acquisition_sha256": digest(source / "ACQUISITION.json"),
        "files": {
            p.relative_to(output).as_posix(): digest(p)
            for directory in (public, private, target)
            for p in directory.rglob("*")
            if p.is_file()
        },
        "discovery_files": sorted(
            p.relative_to(output).as_posix() for p in public.iterdir() if p.is_file()
        ),
        "transfer_files": sorted(
            p.relative_to(output).as_posix() for p in target.iterdir() if p.is_file()
        ),
        "confirmation_contexts": contexts,
        "inventories": inventories,
        "task_families": 1,
        "formal_evidence_eligible": False,
        "quality_admitted": False,
        "research_outcomes_before_freeze": False,
        "source_exposure": "unknown",
        "build_seconds": time.monotonic() - started,
        "redistribution_approved": False,
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in {"files", "discovery_files", "transfer_files"}
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)

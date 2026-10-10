"""Materialize the first authored full-research task data, with real reference runs.

The pack is a release candidate, not a newly admitted formal population. Public
source data are access-separated, not secret or proven absent from model training.
"""
# ruff: noqa: E501 -- Frozen protocol literals and embedded reference source.

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from scitaste.benchmark.full_task_data import digest, prediction_metrics, recipe_groups

TASKS = {
    "concrete-recipe-transfer": {
        "uci_id": 165,
        "title": "Which strength relationships transfer to unseen concrete recipes?",
        "domain": "materials-property modeling",
        "url": "https://archive.ics.uci.edu/static/public/165/data.csv",
        "page": "https://archive.ics.uci.edu/dataset/165/concrete+compressive+strength",
        "doi": "10.24432/C5PK67",
        "citation": "Yeh, I. (1998). Concrete Compressive Strength. UCI.",
        "units": "MPa",
        "question": (
            "Investigate which predictive relationships between composition, curing age and "
            "strength transfer to previously unseen mix recipes. Propose competing explanations "
            "for failures of transfer, develop a method or a scientifically useful negative "
            "finding, and use discriminating controls to establish the limits of the explanation. "
            "The task is not to reproduce a prescribed method or merely maximize a random-row score."
        ),
        "constraints": (
            "Seven ingredient quantities are kg/m^3, age is in days, target is strength in MPa. "
            "Recipe groups connect rows with all ingredient differences <=0.5 kg/m^3, transitively; "
            "age and strength are excluded from grouping. Train, validation and evaluator test "
            "groups are disjoint. A component can span more than 0.5 through chains. "
            "The endpoint is mean per-recipe MAE, then mean across recipes; row MAE and RMSE "
            "are secondary. This measures transfer within this dataset, not independent-lab "
            "or causal material effects. No batch/lab identifiers are available."
        ),
        "claims": [
            [
                "transfer",
                "State the exact recipe-generalization population and compare a fixed "
                "reference with a proposed method or informative negative finding.",
            ],
            [
                "mechanism",
                "Separate representation/model effects from recipe overlap with a "
                "matched control; do not require a positive effect.",
            ],
            [
                "scope",
                "Address curing-age support and absent lab/batch metadata; observational "
                "predictions do not establish causal ingredient effects.",
            ],
            [
                "uncertainty",
                "Use recipe-level uncertainty or explicitly state why evidence is "
                "insufficient; individual repeated-age rows are not independent recipes.",
            ],
        ],
    },
    "bike-demand-temporal-transfer": {
        "uci_id": 275,
        "title": "What limits calendar-only demand forecasts across time?",
        "domain": "mobility time-series forecasting",
        "url": "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip",
        "page": "https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset",
        "doi": "10.24432/C5W894",
        "citation": "Fanaee-T, H. (2013). Bike Sharing. UCI.",
        "units": "rentals/hour",
        "question": (
            "Investigate the failure modes of calendar-only hourly rental forecasts under temporal "
            "change. Develop competing explanations involving changing demand level, calendar "
            "structure and distribution mismatch; choose a method and discriminating evidence. "
            "A supported finding that the available information cannot resolve the mechanism is "
            "valid. A lower error without an explanatory comparison is not a complete submission."
        ),
        "constraints": (
            "Forecast each next calendar day's observed hourly rentals from a fixed model fit "
            "only to the supplied training period. No online updating, no intervening validation "
            "or test counts, and no contemporaneous weather inputs. Calendar information is "
            "known at the previous day's 23:00 forecast origin (horizons 1-24 hours). Train ends "
            "2012-06-30, validation spans July-September 2012, evaluator test is October-December "
            "2012. Only observed hours are scored; missing hours are not zero rentals. "
            "day.csv, casual, registered, cnt, and raw weather are not predictor assets. "
            "The endpoint is MAE within each date, then averaged across dates, in rentals/hour. "
            "Use contiguous date blocks for uncertainty; a single future quarter cannot establish "
            "cross-city or general seasonal transfer. No genuine weather forecast data exist here."
        ),
        "claims": [
            [
                "forecast",
                "Define origin, horizons, frozen fit and information available at "
                "prediction; measure temporal performance against a fixed reference.",
            ],
            [
                "explanation",
                "Distinguish calendar representation from temporal demand change "
                "using public training/validation controls, or state non-identifiability.",
            ],
            [
                "leakage",
                "Do not use target components, future counts, actual future weather or "
                "random-row validation as evidence of prospective forecasting.",
            ],
            [
                "scope",
                "Account for dependent dates, missing hours and one-city/one-quarter "
                "limits; no unsupported transportability or causal weather claim.",
            ],
        ],
    },
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(value)


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("Refuse to overwrite an acquired source")
    request = urllib.request.Request(url, headers={"User-Agent": "SciTaste-data-authoring/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(10_000_001)
    if len(data) > 10_000_000:
        raise ValueError("Acquisition exceeds the declared 10 MB per-source bound")
    with path.open("xb") as stream:
        stream.write(data)
    return data


def data_split(task_id, raw):
    if task_id == "concrete-recipe-transfer":
        frame = pd.read_csv(io.BytesIO(raw))
        if frame.shape != (1030, 9):
            raise ValueError("Concrete source schema changed; do not silently adapt")
        frame.columns = [
            "cement",
            "slag",
            "fly_ash",
            "water",
            "superplasticizer",
            "coarse_aggregate",
            "fine_aggregate",
            "age",
            "target",
        ]
        features = list(frame.columns[:-1])
        frame["group_id"], pairs = recipe_groups(frame, features[:7])
        groups = sorted(frame.group_id.unique())
        rng = np.random.default_rng(20261001)
        ordered = rng.permutation(groups)
        first, second = int(len(groups) * 0.6), int(len(groups) * 0.8)
        mapping = {
            g: name
            for name, values in zip(
                ("train", "validation", "test"), np.split(ordered, [first, second]), strict=True
            )
            for g in values
        }
        split = frame.group_id.map(mapping)
        checks = {
            "near_recipe_pairs": pairs,
            "grouping_excludes_age_and_target": True,
            "recipe_tolerance_kg_m3": 0.5,
            "exact_duplicate_source_rows": int(frame.iloc[:, :9].duplicated().sum()),
        }
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if Path(n).name == "hour.csv"]
            if len(names) != 1 or archive.getinfo(names[0]).file_size > 5_000_000:
                raise ValueError("Unexpected hourly archive contents")
            original = pd.read_csv(archive.open(names[0]))
        dates = pd.to_datetime(original.dteday)
        if original.duplicated(["dteday", "hr"]).any():
            raise ValueError("Duplicate hourly observation keys")
        frame = original[["mnth", "hr", "weekday", "holiday", "workingday"]].copy()
        frame["elapsed_days"] = (dates - pd.Timestamp("2011-01-01")).dt.days
        features = list(frame.columns)
        frame["group_id"] = original.dteday
        frame["target"] = original.cnt
        split = pd.Series(
            np.where(
                dates <= "2012-06-30",
                "train",
                np.where(dates <= "2012-09-30", "validation", "test"),
            )
        )
        checks = {
            "hourly_observations": len(frame),
            "unique_dates": int(dates.nunique()),
            "target_component_identity_verified": bool(
                (original.cnt == original.casual + original.registered).all()
            ),
            "excluded_predictors": [
                "casual",
                "registered",
                "cnt",
                "temp",
                "atemp",
                "hum",
                "windspeed",
                "weathersit",
                "instant",
            ],
            "excluded_archive_file": "day.csv",
            "online_label_updates": False,
        }
    if frame[[*features, "target"]].isna().any().any():
        raise ValueError("Missing values require an explicit data protocol amendment")
    raw_hash = hashlib.sha256(raw).hexdigest()
    frame.insert(
        0,
        "row_id",
        [hashlib.sha256(f"{raw_hash}:{i}".encode()).hexdigest()[:20] for i in range(len(frame))],
    )
    partitions = {
        name: frame.loc[split == name].reset_index(drop=True)
        for name in ("train", "validation", "test")
    }
    if any(part.empty for part in partitions.values()):
        raise ValueError("Empty task partition")
    if any(
        set(partitions[a].group_id) & set(partitions[b].group_id)
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    ):
        raise ValueError("Source groups cross partitions")
    checks["cross_partition_group_overlap"] = 0
    checks["counts"] = {
        name: {"rows": len(part), "groups": int(part.group_id.nunique())}
        for name, part in partitions.items()
    }
    return partitions, features, checks


def build(output):
    if (output / "private").exists() or (output / "PACK.json").exists():
        raise ValueError("Preserve the existing pack; use a new explicit version")
    output.mkdir(parents=True, exist_ok=True)
    tasks = []
    code_path = Path(__file__).resolve()
    write_text(output / "private/builder.py", code_path.read_text())
    write_text(
        output / "private/scorer.py",
        (code_path.parents[1] / "src/scitaste/benchmark/full_task_data.py").read_text(),
    )
    reference_config = {
        "model": "ExtraTreesRegressor",
        "n_estimators": 64,
        "min_samples_leaf": 3,
        "random_state": 2718,
        "n_jobs": 1,
        "selection": "fixed-before-measurements; no hyperparameter search",
    }
    write_json(output / "private/REFERENCE_CONFIG.json", reference_config)
    write_json(
        output / "private/ENVIRONMENT.json",
        {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
            "builder_sha256": digest(code_path),
            "scorer_sha256": digest(
                Path(__file__).resolve().parents[1] / "src/scitaste/benchmark/full_task_data.py"
            ),
        },
    )
    for task_id, spec in TASKS.items():
        public, private = output / "public" / task_id, output / "private" / task_id
        public.mkdir(parents=True)
        private.mkdir(parents=True)
        source = output / "private/sources" / f"uci-{spec['uci_id']}.data"
        raw = download(spec["url"], source)
        metadata = download(
            f"https://archive.ics.uci.edu/api/dataset?id={spec['uci_id']}",
            source.with_suffix(".metadata.json"),
        )
        page = download(spec["page"], source.with_suffix(".html"))
        if b"CC BY 4.0" not in page and b"creativecommons.org/licenses/by/4.0" not in page:
            raise ValueError("Retain and inspect changed source license before redistribution")
        if json.loads(metadata)["data"]["uci_id"] != spec["uci_id"]:
            raise ValueError("Source metadata identity mismatch")
        parts, features, checks = data_split(task_id, raw)
        for name in ("train", "validation"):
            parts[name].to_csv(public / f"{name}.csv", index=False)
        parts["test"][["row_id", *features]].to_csv(private / "features.csv", index=False)
        parts["test"][["row_id", "group_id", "target"]].to_csv(private / "labels.csv", index=False)
        write_json(private / "DATA_QUALITY.json", checks)
        write_text(
            public / "ATTRIBUTION.md",
            f"# Source and changes\n\n{spec['citation']} "
            f"https://doi.org/{spec['doi']}\n\nDataset license: CC BY 4.0. "
            "https://creativecommons.org/licenses/by/4.0/\n\n"
            "SciTaste authors added the research question, leakage-controlled partitions, "
            "fixed claim rubric and review protocol; columns are renamed/subselected and "
            "row identifiers are replaced. No original observations are claimed as new data. "
            "The source author does not endorse this benchmark.\n",
        )
        protocol = {
            "task_id": task_id,
            "features": features,
            "primary_endpoint": "group_macro_mae",
            "units": spec["units"],
            "secondary_endpoints": ["row_mae", "row_rmse"],
            "direction": "minimize",
            "submission": "solution.py --train TRAIN.csv --features FEATURES.csv --output PREDICTIONS.csv",
            "prediction_columns": ["row_id", "prediction"],
            "final_fit_data": "train.csv only; validation for research and selection, not final fit",
            "researcher_network": "disabled during task; provenance URLs are attribution, not fetch permission",
            "hidden_endpoint": "evaluator supplies unlabelled features only after submission lock",
            "review_endpoint": "fixed same heldout partition before and after review; no scores fed back",
            "experimental_subject_modes": ["training_free", "training_based"],
            "controller_training": False,
            "mode_semantics": "Actual fitted parameters/optimizer steps must be reported. A CPU fit is training; "
            "GPU use does not define the mode. Neither task requires controller training.",
            "resource_ceiling": {
                "research_wall_seconds": 14400,
                "research_model_calls": 80,
                "cpu_threads": 2,
                "memory_gib": 8,
                "gpu_count": 0,
                "review_model_calls": 1,
                "revision_model_calls": 8,
                "revision_wall_seconds": 1800,
            },
            "completion_requires": [
                "hypotheses and discriminating design",
                "executed experiment logs",
                "runnable solution",
                "paper with figures/tables",
                "claim-evidence mapping",
                "review response and revised paper or justified stop",
            ],
            "claim_rubric": [
                {
                    "claim_id": key,
                    "requirement": value,
                    "grading": "supported / contradicted / insufficient; unsupported assertion flagged separately",
                }
                for key, value in spec["claims"]
            ],
            "empty_or_omitted_claims": "insufficient, never perfect groundedness",
            "scientific_quality": "prediction error alone does not grade explanation, novelty or paper quality",
        }
        write_json(public / "PROTOCOL.json", protocol)
        write_text(
            public / "TASK.md",
            f"# {spec['title']}\n\n{spec['question']}\n\n"
            f"## Scientific setting\n\n{spec['constraints']}\n\n"
            "## Deliverable\n\nRead PROTOCOL.json. Develop your own hypotheses and method; "
            "there is no supplied correct hypothesis or compulsory positive gain. Run actual "
            "experiments, preserve code/results, write a scientific paper, map the four "
            "required conclusions to evidence, then respond to the standardized review. "
            "Use only train.csv and validation.csv for research. A reference implementation "
            "is provided as a comparison, not a target solution. No scorer queries during "
            "research or revision; the final test population remains fixed.\n",
        )
        write_json(
            public / "REVIEW_PROTOCOL.json",
            {
                "visible_from_start": True,
                "reviewer_blinded_to_system": True,
                "review_input_allowlist": [
                    "submitted paper",
                    "submitted code",
                    "public train/validation",
                    "submitted public-validation predictions and logs",
                ],
                "forbidden_inputs": [
                    "private labels",
                    "private predictions",
                    "private scores",
                    "other arms",
                ],
                "review_evidence": "Recompute public-validation group metrics and condition counts from submitted "
                "predictions. Assess each public claim requirement; retain contradictions and "
                "uncertainty rather than inventing a preferred conclusion.",
                "response": "Revise, justify retaining a claim, or retract; new experiment need not improve score.",
                "counterfactual_review_variants": "not implemented or counted in this first task-data pack",
                "reviewer_type": "independent AI initially; not human gold or calibrated validity",
            },
        )
        baseline = '''"""Fixed task reference, not a research-framework result."""
import argparse
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

p = argparse.ArgumentParser()
for key in ("train", "features", "output"):
    p.add_argument("--" + key, required=True)
a = p.parse_args()
train, features = pd.read_csv(a.train), pd.read_csv(a.features)
columns = [c for c in train if c not in {"row_id", "group_id", "target"}]
model = ExtraTreesRegressor(n_estimators=64, min_samples_leaf=3, random_state=2718, n_jobs=1)
model.fit(train[columns], train.target)
pd.DataFrame({"row_id": features.row_id, "prediction": model.predict(features[columns])}).to_csv(a.output, index=False)
'''
        write_text(public / "reference.py", baseline)
        started = time.monotonic()
        inputs = private / "reference-features.csv"
        predictions_path = private / "reference-predictions.csv"
        pd.concat([parts["validation"], parts["test"]])[["row_id", *features]].to_csv(
            inputs, index=False
        )
        command = [
            sys.executable,
            str(public / "reference.py"),
            "--train",
            str(public / "train.csv"),
            "--features",
            str(inputs),
            "--output",
            str(predictions_path),
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "CUDA_VISIBLE_DEVICES": "",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            },
        )
        predictions = pd.read_csv(predictions_path)
        metrics = {}
        for name in ("validation", "test"):
            predicted = predictions.loc[predictions.row_id.isin(parts[name].row_id)]
            predicted.to_csv(private / f"reference-{name}-predictions.csv", index=False)
            metrics[name] = prediction_metrics(parts[name], predicted)
        write_json(
            private / "REFERENCE_RUN.json",
            {
                "status": "executed",
                "duration_seconds": time.monotonic() - started,
                "reference_config_sha256": digest(output / "private/REFERENCE_CONFIG.json"),
                "dataset_sha256": digest(source),
                "reference_source_sha256": digest(public / "reference.py"),
                "metrics": metrics,
                "new_gpu_seconds": 0,
                "model_api_calls": 0,
                "scope": "fixed reference feasibility, not an autonomous research run or an optimal result",
                "execution": "actual published reference CLI, one fit; no parameter search",
                "command": command,
                "returncode": completed.returncode,
            },
        )
        write_json(
            private / "SOURCE_RECEIPT.json",
            {
                "source_url": spec["url"],
                "source_page": spec["page"],
                "doi": spec["doi"],
                "raw_sha256": digest(source),
                "source_page_sha256": digest(source.with_suffix(".html")),
                "license": "CC BY 4.0 as declared on source landing page",
                "rights_scope": "dataset only; not unrestricted rights to cited paper text/code",
                "dataset_family": f"uci-{spec['uci_id']}",
                "prior_controller_exposure": "not found in scoped intake; not certified",
                "pretraining_contamination": "unknown; public source targets reconstructable outside sandbox",
            },
        )
        tasks.append(
            {
                "task_id": task_id,
                "title": spec["title"],
                "domain": spec["domain"],
                "source_family": f"uci-{spec['uci_id']}",
                "origin": "benchmark-authored research/evidence protocol on attributed existing data",
                "split": "candidate-unassigned",
                "primary_endpoint": "group_macro_mae",
                "units": spec["units"],
                "counts": checks["counts"],
                "reference_executed": True,
                "researcher_files": sorted(
                    p.relative_to(output).as_posix() for p in public.iterdir()
                ),
            }
        )
    files = {
        p.relative_to(output).as_posix(): digest(p)
        for folder in ("public", "private")
        for p in (output / folder).rglob("*")
        if p.is_file()
    }
    pack = {
        "schema_version": "scitastebench.task-data.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "tasks": tasks,
        "files": files,
        "formal_release": False,
        "qualification_remaining": [
            "source-bound independent design/data review",
            "researcher/evaluator process isolation and actual framework binding",
            "exposure-ledger reconciliation before formal split assignment",
            "claim/review scorer calibration and counterfactual review subset",
            "broader domains and remote-GPU task families",
        ],
        "benchmark_novelty_established": False,
    }
    write_json(output / "PACK.json", pack)
    return {
        "pack": str(output),
        "task_families": len(tasks),
        "reference_runs": len(tasks),
        "formal_tasks": 0,
        "counts": {t["task_id"]: t["counts"] for t in tasks},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()

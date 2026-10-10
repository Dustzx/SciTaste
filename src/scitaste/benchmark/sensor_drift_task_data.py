"""Original temporal sensor data, source-frozen delivery and proper-score outcomes.

This is an authored research task, not the original supervised online-ensemble
protocol, a new independent task per batch, or a certified contamination firewall.
"""

import io
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.datasets import load_svmlight_file

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "sensor-drift-probability-transfer"
SOURCE_URL = (
    "https://archive.ics.uci.edu/static/public/224/gas%2Bsensor%2Barray%2Bdrift%2Bdataset.zip"
)
BRIEF = """# What probability evidence survives temporal sensor drift?

Conduct actual research on multiclass gas discrimination across temporally
ordered sensor batches. Form competing explanations for probability-quality
changes, run discriminating controls, select a procedure on public evidence,
and deliver an evidence-linked paper. Separate calibration, discrimination,
class composition and representation/capacity changes. A negative result or
useful boundary is a valid finding; a recipe's name is not a novel contribution.

## Original observations and exposure

UCI Gas Sensor Array Drift, Vergara (2012), DOI 10.24432/C5RP6W, supplies 13,910
observations, 128 aggregate features (8 per sensor, 16 sensors), six pure gases
and ten temporal batches. Features are already source-engineered, not raw
time series or concentration measurements. IDs 0..5 correspond to original
labels 1..6: ethanol, ethylene, ammonia, acetaldehyde, acetone, toluene.
Batch membership groups nonconsecutive months in some cases; elapsed time
is not a randomized treatment and repeated chamber/measurement dependence
is unknown. Missing classes in a batch remain missing. Gas-class composition
differs between batches. Do not interpret a performance change as an identified
physical drift mechanism, concentration compensation, safety or deployment.

Training: complete original batches 1..3. Public discovery: batch 4; public
validation: batch 5. Confirmation: batches 6..10, each scored separately.
The split is fixed by source batch before performance measurements, not tuned
to a winner. Fit ALL predictors, transformations, calibration parameters and
any adaptation rules on training only. Public discovery/validation may choose
fixed hyperparameters/procedures and diagnose rival explanations, but may not
fit numerical model/calibration parameters. Cross-fitting inside training is
permitted; explain temporal limitations of the chosen training calibration
split. Confirmation queries may be used for per-instance prediction only:
no transductive refitting, batch-derived normalization or target adaptation.
No target labels, original archive, extra data/weights, pretrained task model,
other assignments, credentials or supplier APIs. Prior model exposure to this
public dataset is unknown; source availability is not proof of unseen data.

NPZ fields: observation_id[N] int64; x[N,128] float64; batch[N] int64; and
target[N] int64 in 0..5 for PUBLIC labelled data only. Query omits target.
No measurement row or temporal batch is a separate research task. The supplied
reference.py implements train-only scaled logistic, scaled RBF SVM and extra
trees controls. RBF SVM is motivated by the original source, but these fixed
parameters are not a reproduction of its cross-validated supervised ensemble.
Do not invent an exact reproduction or claim superiority to all drift methods.
Both fitted and training-free experimental subjects are legal within the
exposure constraints; SciTaste's controller is not trained by this assignment.

## Endpoints and scientific obligations

Primary: complete multiclass Brier, mean(sum_c(p_c - 1[y=c])^2), range [0,2],
lower is better, separately for EACH confirmation batch. Keep log-loss,
balanced accuracy over present classes, overall accuracy, predicted/observed
class proportions, declared failures and measured runtime separate. Report
absent classes and do not replace them with zero recall. Log-loss clips only
for scoring at 1e-15 and reports the clipped true-class fraction. Confidence
ECE, if explored, is a diagnostic rather than the primary score or proof of
useful probabilities. Proper-score improvement alone does not establish that
recalibration rather than ranking/composition/capacity explains the change.
Controls must isolate the claimed intervention with matching inputs, training
exposure and capacity where possible; record remaining confounders explicitly.

Freeze exactly one primary_method selected using public evidence before READY;
never choose a better confirmation method after seeing results. Include every
attempted control, failed branch and competing prediction in retained artifacts.
Use relevant original literature without invented citations or prestigious-name
claims. Real measured controls and executable findings determine claim scope.

## Delivery and one-time confirmation

Keep code, raw measurements, informative plots, and report/report.md. Freeze
submission/SUBMISSION.json and EVERY required helper in submission/. The
entrypoint accepts --data DIRECTORY --output DIRECTORY, independently replays
train-only fitting and reads QUERY.json. All training/public data and protocol
are supplied again; workspace caches are not mounted. Output exactly
CONTEXT--METHOD.npz at the output root for EVERY declared method and every
query context, containing observation_id[N] int64, probabilities[N,6] finite
normalized nonnegative floats, valid[N] bool, seconds[N] finite nonnegative
inference costs. IDs cover all query observations exactly once. Put auxiliary
fit files in subdirectories, never additional top-level NPZs. Any valid=false
keeps the complete primary missing, not a survivor average or zero.

Finalize sources, then publish READY ONCE (the Native Freeze Submission tool
is available). The trusted service freezes sources before releasing redacted
queries, executes unchanged code offline, and releases ONE joint feedback
packet. No post-READY source repair, refreeze or target re-execution. Read
confirmation_feedback.json before final claims; retain source failures and
missing outcomes. Deliver a first paper, evidence-based review and appropriate
revision within the same lifecycle, not an extra budget. Paper prose cannot
replace actual research evidence or certify novel methodology.
"""

REFERENCE = '''"""Train-only ordinary controls; no target fitting or scientific winner."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.svm import SVC

def models():
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=1., max_iter=1500, random_state=0)),
        "rbf_svm": make_pipeline(MinMaxScaler(feature_range=(-1, 1)), SVC(C=64., gamma="scale", probability=True, random_state=0)),
        "extra_trees": ExtraTreesClassifier(n_estimators=256, min_samples_leaf=2, max_features="sqrt", n_jobs=2, random_state=0),
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    train = np.load(a.data / "train.npz", allow_pickle=False)
    query = json.loads((a.data / "QUERY.json").read_text()) if (a.data / "QUERY.json").exists() else {"contexts": {"discovery": "discovery.npz", "validation": "validation.npz"}}
    for name, model in models().items():
        model.fit(train["x"], train["target"])
        for context, filename in query["contexts"].items():
            rows = np.load(a.data / filename, allow_pickle=False)
            started = time.monotonic()
            raw = model.predict_proba(rows["x"])
            elapsed = time.monotonic() - started
            probabilities = np.zeros((len(raw), 6))
            probabilities[:, model.classes_.astype(int)] = raw
            np.savez_compressed(a.output / f"{context}--{name}.npz", observation_id=rows["observation_id"], probabilities=probabilities, valid=np.ones(len(raw), dtype=bool), seconds=np.full(len(raw), elapsed / len(raw)))

if __name__ == "__main__":
    main()
'''


def build(archive, output):
    """Preserve every original row; batch split precedes outcome evaluation."""
    archive = Path(archive).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    public = output / "public" / TASK_ID
    private, target = output / "private", output / "target"
    for folder in (public, private, target):
        folder.mkdir(parents=True)
    shutil.copy2(archive, private / "ORIGINAL.zip")
    retain_json(
        private / "SPLIT_FREEZE.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "original_sha256": digest(archive),
            "train_batches": [1, 2, 3],
            "discovery_batches": [4],
            "validation_batches": [5],
            "confirmation_batches": [6, 7, 8, 9, 10],
            "before_performance_measurement": True,
            "row_or_batch_independence": "unknown",
        },
    )
    batches, descriptions = {}, []
    with zipfile.ZipFile(archive) as compressed:
        for batch in range(1, 11):
            name = f"Dataset/batch{batch}.dat"
            # Parse in memory; no arbitrary archive extraction or paths.
            x, y = load_svmlight_file(io.BytesIO(compressed.read(name)), n_features=128)
            y = y.astype(np.int64) - 1
            if not set(np.unique(y)).issubset(range(6)):
                raise ValueError("Original labels outside six source gases")
            x = x.toarray()
            if not np.isfinite(x).all():
                raise ValueError("Nonfinite original features")
            rows = {
                "observation_id": batch * 1_000_000 + np.arange(len(y), dtype=np.int64),
                "x": x,
                "target": y,
                "batch": np.full(len(y), batch, dtype=np.int64),
            }
            batches[batch] = rows
            descriptions.append(
                {
                    "batch": batch,
                    "observations": len(y),
                    "class_counts": np.bincount(y, minlength=6).tolist(),
                }
            )
    if sum(row["observations"] for row in descriptions) != 13910:
        raise ValueError("Unexpected original source row count")
    train = {key: np.concatenate([batches[b][key] for b in (1, 2, 3)]) for key in batches[1]}
    if set(np.unique(train["target"])) != set(range(6)):
        raise ValueError("Training must represent all six gas labels")
    for name, rows in (("train", train), ("discovery", batches[4]), ("validation", batches[5])):
        np.savez_compressed(public / f"{name}.npz", **rows)
        shutil.copy2(public / f"{name}.npz", target / f"{name}.npz")
    contexts = {}
    for batch in range(6, 11):
        context, rows = f"batch{batch}", batches[batch]
        np.savez_compressed(private / f"{context}-labels.npz", **rows)
        np.savez_compressed(
            target / f"{context}-query.npz", **{k: v for k, v in rows.items() if k != "target"}
        )
        contexts[context] = f"{context}-query.npz"
    retain_json(
        target / "QUERY.json",
        {"task_id": TASK_ID, "contexts": contexts, "classes": 6, "target_fitting_permitted": False},
    )
    claims = [
        {
            "claim_id": "probability_transfer",
            "statement": "The public-selected procedure transfers a probability-quality effect.",
            "required_evidence": [
                "Frozen unchanged execution",
                "Complete Brier separately in all five temporal batches",
                "Matched input/exposure controls and retained missing outcomes",
            ],
        },
        {
            "claim_id": "calibration_mechanism",
            "statement": "The gain is attributable to the proposed probability intervention rather than changed discrimination/capacity/composition.",
            "required_evidence": [
                "Fixed underlying predictor/input",
                "Train-only map fitting",
                "Discriminating control and reversal prediction",
                "Accuracy/class-composition/proper-score diagnostics",
            ],
            "prohibited_extension": "Identified physical drift mechanism or general adaptation superiority",
        },
    ]
    protocol = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "primary": "multiclass_brier",
        "brier_convention": "mean sum over six classes; range [0,2]",
        "classes": 6,
        "batch_description": descriptions[:5],
        "confirmation_batches": [6, 7, 8, 9, 10],
        "fit_policy": "train only; no transductive confirmation fitting",
        "selection_policy": "public discovery and validation choose rules, not fit parameters",
        "confirmation_scope": "One family, five within-task temporal contexts; composition varies",
        "claim_rubric": claims,
        "formal_evidence_eligible": False,
    }
    retain_json(public / "PROTOCOL.json", protocol)
    shutil.copy2(public / "PROTOCOL.json", target / "PROTOCOL.json")
    example = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "methods": ["primary", "control"],
        "primary_method": "primary",
        "entrypoint": "predict.py",
        "files": ["predict.py"],
        "selection_rule": "REPLACE with public-only selection rule",
        "fit_policy": "REPLACE with exact train-only fitting/exposure",
        "scope": "REPLACE with warranted inference scope",
        "hypotheses": [
            {
                "statement": "REPLACE first explanation",
                "discriminating_prediction": "REPLACE first falsifiable prediction",
            },
            {
                "statement": "REPLACE rival explanation",
                "discriminating_prediction": "REPLACE distinguishing prediction",
            },
        ],
    }
    retain_json(public / "SUBMISSION.example.json", example)
    (public / "TASK.md").write_text(BRIEF)
    (public / "reference.py").write_text(REFERENCE)
    (public / "ATTRIBUTION.md").write_text(
        "Vergara, A. (2012). Gas Sensor Array Drift Dataset. UCI, DOI 10.24432/C5RP6W.\n"
        f"Original archive: {SOURCE_URL}\n"
        "Dataset page https://archive.ics.uci.edu/dataset/224/gas currently lists CC BY 4.0; "
        "legacy text says research-only/noncommercial. This use is research-only; do not "
        "infer redistribution/commercial permission from this task. Batch10 is the corrected original.\n"
        "Source method: Vergara et al., Chemical gas sensor drift compensation using classifier ensembles, "
        "Sensors and Actuators B (2012), DOI 10.1016/j.snb.2012.01.074. "
        "Our fixed train-only task is not its supervised online ensemble protocol.\n"
    )
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    manifest = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "source_url": SOURCE_URL,
        "original_sha256": digest(archive),
        "observations": 13910,
        "batch_description": descriptions,
        "task_families": 1,
        "confirmation_contexts": list(contexts),
        "files": files,
        "discovery_files": sorted(p.relative_to(output).as_posix() for p in public.iterdir()),
        "transfer_files": sorted(
            p.relative_to(output).as_posix()
            for p in target.iterdir()
            if p.name not in {q.name for q in public.iterdir()}
        ),
        "formal_evidence_eligible": False,
        "pretraining_exposure": "unknown",
    }
    retain_json(output / "PACK.json", manifest)
    return manifest


def primary_method(contract):
    method = contract.get("primary_method")
    if not isinstance(method, str) or method not in contract.get("methods", []):
        raise ValueError("Freeze a single public-selected primary_method")
    return method


def export_stage(pack, destination, *, submission=None):
    if submission is not None:
        primary_method(json.loads((submission / "SUBMISSION.json").read_text()))
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.sensor-drift-release.v1",
    )


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    return [f"{c}-query.npz" for c in manifest["confirmation_contexts"]] + [
        "QUERY.json",
        "PROTOCOL.json",
        "train.npz",
        "discovery.npz",
        "validation.npz",
    ]


def probability_metrics(labels, prediction):
    expected, ids, p = (
        labels["observation_id"],
        prediction["observation_id"],
        prediction["probabilities"],
    )
    n = len(expected)
    if (
        not n
        or ids.shape != (n,)
        or not np.issubdtype(ids.dtype, np.integer)
        or len(np.unique(ids)) != n
        or set(ids) != set(expected)
        or p.shape != (n, 6)
        or not np.isrealobj(p)
        or not np.isfinite(p).all()
        or np.any(p < 0)
        or np.any(p > 1)
        or not np.allclose(p.sum(1), 1.0, atol=1e-8, rtol=0)
        or prediction["valid"].shape != (n,)
        or prediction["valid"].dtype != np.bool_
        or prediction["seconds"].shape != (n,)
        or not np.isrealobj(prediction["seconds"])
        or not np.isfinite(prediction["seconds"]).all()
        or np.any(prediction["seconds"] < 0)
    ):
        raise ValueError("Full unique IDs and finite normalized six-class probabilities required")
    lookup = {int(value): i for i, value in enumerate(ids)}
    order = [lookup[int(value)] for value in expected]
    p, valid = p[order], prediction["valid"][order]
    y = labels["target"]
    complete = bool(valid.all())
    chosen = p.argmax(1)
    class_counts = np.bincount(y, minlength=6)
    recalls = [
        float(np.mean(chosen[y == c] == c)) if class_counts[c] and complete else None
        for c in range(6)
    ]
    true_probability = p[np.arange(n), y]
    return {
        "multiclass_brier": float(np.mean(np.sum((p - np.eye(6)[y]) ** 2, axis=1)))
        if complete
        else None,
        "log_loss": float(-np.mean(np.log(np.maximum(true_probability, 1e-15))))
        if complete
        else None,
        "log_loss_clipped_fraction": float(np.mean(true_probability < 1e-15)) if complete else None,
        "accuracy": float(np.mean(chosen == y)) if complete else None,
        "balanced_accuracy_present_classes": float(np.mean([r for r in recalls if r is not None]))
        if complete
        else None,
        "class_recall": recalls,
        "class_counts": class_counts.tolist(),
        "mean_predicted_class_probability": p.mean(0).tolist() if complete else None,
        "observed_class_fraction": (class_counts / n).tolist(),
        "observations": n,
        "declared_failure_fraction": float(np.mean(~valid)),
        "self_reported_cpu_seconds": float(prediction["seconds"].sum()),
        "partial_outcome_policy": "Any failure leaves complete primary missing; no survivor score",
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if (
        receipt.get("phase") != "transfer"
        or receipt["pack_sha256"] != digest(pack / "PACK.json")
        or not receipt.get("frozen_source")
    ):
        raise ValueError("Matching source-frozen confirmation required")
    frozen = release.parent / "frozen_submission"
    for name, sha in receipt["frozen_source"].items():
        path = (frozen / name).resolve(strict=True)
        path.relative_to(frozen.resolve(strict=True))
        if digest(path) != sha:
            raise ValueError("Frozen source changed")
    contract = json.loads((frozen / "SUBMISSION.json").read_text())
    primary = primary_method(contract)
    manifest = json.loads((pack / "PACK.json").read_text())
    contexts, methods = manifest["confirmation_contexts"], contract["methods"]
    expected = {f"{c}--{m}.npz" for c in contexts for m in methods}
    found = {p.name for p in predictions.glob("*.npz")}
    records = []
    for context in contexts:
        with np.load(
            bound_file(pack, manifest, f"private/{context}-labels.npz"), allow_pickle=False
        ) as labels:
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                failure, sha = None, None
                try:
                    if found - expected or path.is_symlink() or not path.is_file():
                        raise ValueError("Missing, nonregular or undeclared prediction outputs")
                    sha = digest(path)
                    with np.load(path, allow_pickle=False) as prediction:
                        if set(prediction.files) != {
                            "observation_id",
                            "probabilities",
                            "valid",
                            "seconds",
                        }:
                            raise ValueError("Unexpected output fields")
                        metrics = probability_metrics(labels, prediction)
                except Exception as exc:
                    failure = {"error_type": type(exc).__name__, "error": str(exc)}
                    metrics = {"multiclass_brier": None, "observations": len(labels["target"])}
                records.append(
                    {
                        "context": context,
                        "method": method,
                        "metrics": metrics,
                        "status": "invalid-or-missing-output"
                        if failure
                        else "scored"
                        if metrics["declared_failure_fraction"] == 0
                        else "scored-with-declared-failures",
                        "prediction_sha256": sha,
                        "output_failure": failure,
                    }
                )
    result = {
        "task_id": TASK_ID,
        "primary_method": primary,
        "primary_endpoint": "multiclass_brier",
        "primary_scores": {
            r["context"]: r["metrics"]["multiclass_brier"]
            for r in records
            if r["method"] == primary
        },
        "scores": records,
        "missing_prediction_files": sorted(expected - found),
        "undeclared_npz_files": sorted(found - expected),
        "pack_sha256": digest(pack / "PACK.json"),
        "all_predeclared_method_context_records_retained": True,
        "output_contract_valid": not (found - expected)
        and all(r["output_failure"] is None for r in records),
        "task_families": 1,
        "formal_evidence_eligible": False,
        "source_execution_verified": False,
    }
    destination = release.parent / "confirmation/RESULT.json"
    retain_json(destination, result)
    return destination

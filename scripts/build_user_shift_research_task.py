"""Build one authentic user-shift task; never select data using model outcomes."""
# ruff: noqa: E501 -- Authored scientific protocol and original-source URLs.

import argparse
import csv
import hashlib
import json
import tarfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.user_shift_task_data import CLAIM_RUBRIC, TASK_ID

BRIEF = """# Which validation evidence supports robustness to unseen reviewers?

Study star-rating prediction on real Amazon reviews under the official WILDS user
split. Training reviewers, validation reviewers and confirmation reviewers come
from the original source, not synthetic demographic groups or artificially flipped
labels. Propose competing explanations for unequal reviewer performance, execute
informative experiments, and develop either a justified procedure or a useful
negative finding about robust selection/intervention under limited validation.

Do not simply rename ERM, JTT, a worst-group selector, or a data-reweighting heuristic
as a novel contribution. Ask what an experiment can distinguish: label frequencies,
small-group estimation noise, lexical diversity and a transferable intervention may
produce similar apparent improvements. Your account needs an executed matched
control, explicit validation access and an honest residual uncertainty statement.

## Data and resource boundary

Read train.jsonl, id_val.jsonl, ood_val.jsonl and PROTOCOL.json in data/. Each line
has review_id, text, pseudonymous user, category and label in 0..4 (original 1..5
stars minus one). Fit vectorizers and predictive parameters only on training data.
Validation labels/groups may choose predeclared configurations, but are not fitting
examples; no validation-fitted vocabulary or retuning on confirmation feedback.
Unseen reviewers are not necessarily unseen products or times. User-ID disjointness
is not evidence for causal fairness or universal out-of-distribution robustness.

Use either training-based experimental subjects (e.g. text vectorizers and linear
classifiers) or training-free experimental procedures (e.g. fixed-feature retrieval
with a labelled training memory). This choice concerns the research subject, NOT
training the SciTaste controller. You choose the defensible subject and hypothesis.
Two CPU threads; existing Python 3.12 numpy/scipy/sklearn/pandas/matplotlib/torch.
No new weights, paid API or GPU are needed in this cohort. Report all executed
procedures and selection cost; they are not free because one final model is small.

## Whole-research delivery

Form at least two falsifiable explanations and meaningful controls. Retain runnable
source, measurements and figures; produce an initial paper, evidence-based critique
and justified revision. Before target access, declare method/control identifiers,
their selection/fit policies and competing discriminating predictions in
SUBMISSION.json. Place every helper and entrypoint under submission/, then write
submission/READY exactly once. Only frozen source and installed dependencies will
be available to confirmation; source must retrain from supplied train/validation
files, not load an undeclared workspace checkpoint or cache.

Confirmation receives the SAME train/validation files plus query.jsonl with target
review texts, pseudonymous user/category and review_id, but NO target labels.
The entrypoint accepts --data DIRECTORY --output DIRECTORY. Write precisely
amazon--METHOD.npz for each declared method, containing review_id[N] (integer)
and probabilities[N,5] (finite normalized probabilities), with complete unique IDs.
All controls score jointly once. Do not repair or change source after READY. Wait
for confirmation_feedback.json before final scientific interpretation and paper.
Confirmation failures and negative results remain outcomes, not substituted scores.

Report overall accuracy and the official unweighted 10th percentile of per-user
accuracies separately. Worst-user accuracy and NLL may be descriptive but are not
the official primary metric, and unlike metrics must not be averaged. This is one
deterministic user subset, NOT the official complete WILDS benchmark or multiple
independent research tasks. Original full text is retained; state any preprocessing
or truncation, which may differ from WILDS' reference 512-token model input.
Complete report/report.md plus the framework's native paper artifacts, including
related work, actual experiments, scope/limitations and review-response evidence.
"""


def extract_sources(acquisition):
    receipt = json.loads((acquisition / "RECEIPT.json").read_text())
    if not receipt["status"].startswith("source-acquired"):
        raise ValueError("Official acquisition did not complete")
    archive = acquisition / receipt["archive"]
    # The acquisition already hashed all streamed bytes. Rehash before extraction
    # because incorrect source identity would irreversibly contaminate a cohort.
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != receipt["sha256"]:
        raise ValueError("Acquired archive changed")
    raw = acquisition / "extracted-research-source"
    raw.mkdir(exist_ok=False)
    selected = {}
    total = 0
    with tarfile.open(archive, "r|gz") as source:
        for member in source:
            parts = Path(member.name).parts
            name = (
                "reviews.csv"
                if parts and parts[-1] == "reviews.csv"
                else (
                    "user.csv" if len(parts) >= 2 and parts[-2:] == ("splits", "user.csv") else None
                )
            )
            if name is None:
                continue
            if not member.isfile() or name in selected or member.size > 8_000_000_000:
                raise ValueError("Unsafe or duplicate official source member")
            total += member.size
            if total > 9_000_000_000:
                raise ValueError("Selected uncompressed source exceeds the bounded extraction")
            sha = hashlib.sha256()
            with source.extractfile(member) as data, (raw / name).open("xb") as target:
                while chunk := data.read(8 * 1024 * 1024):
                    target.write(chunk)
                    sha.update(chunk)
            selected[name] = {
                "archive_member": member.name,
                "sha256": sha.hexdigest(),
                "bytes": member.size,
            }
    if set(selected) != {"reviews.csv", "user.csv"}:
        raise ValueError("Official archive misses reviewer split or review data")
    retain_json(raw / "EXTRACTION.json", {"archive_sha256": receipt["sha256"], "files": selected})
    return raw


def user_rank(user):
    return hashlib.sha256(("scitaste-user-shift-v1:" + user).encode()).hexdigest()


def build(acquisition, output, train_users, validation_users, confirmation_users):
    started = time.monotonic()
    raw = acquisition / "extracted-research-source"
    if not raw.exists():
        raw = extract_sources(acquisition)
    extraction = json.loads((raw / "EXTRACTION.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    private, public, target = output / "private", output / "public" / TASK_ID, output / "target"
    for path in (private, public, target):
        path.mkdir(parents=True)
    splits = pd.read_csv(raw / "user.csv", usecols=["split"])["split"].to_numpy()
    # The v2.1 archive is shared with AmazonUnlabeledDataset. Its official
    # 11/12/13 splits are not supervised training/validation/test examples.
    if not set(np.unique(splits)) <= {-1, 0, 1, 2, 3, 4, 11, 12, 13}:
        raise ValueError("Unknown official split value")
    populations = {i: Counter() for i in range(5)}
    offset = 0
    for chunk in pd.read_csv(
        raw / "reviews.csv",
        usecols=["reviewerID"],
        dtype=str,
        keep_default_na=False,
        quoting=csv.QUOTE_NONNUMERIC,
        chunksize=100_000,
    ):
        section = splits[offset : offset + len(chunk)]
        if len(section) != len(chunk):
            raise ValueError("Official reviews and split rows are misaligned")
        users = chunk["reviewerID"].to_numpy()
        for code in populations:
            populations[code].update(users[section == code].tolist())
        offset += len(chunk)
    if offset != len(splits):
        raise ValueError("Official review and split lengths differ")
    selected = {
        code: set(sorted(populations[code], key=user_rank)[:count])
        for code, count in ((0, train_users), (1, validation_users), (3, confirmation_users))
    }
    if any(
        len(selected[code]) != count
        for code, count in ((0, train_users), (1, validation_users), (3, confirmation_users))
    ):
        raise ValueError("Requested subset exceeds source population")
    if any(selected[a] & selected[b] for a, b in ((0, 1), (0, 3), (1, 3))):
        raise ValueError("Official reviewer-disjoint split is violated")
    retain_json(
        private / "SAMPLING.json",
        {
            "selection": "lowest SHA256 of fixed prefix and reviewerID, no label/outcome access",
            "selected_users": {str(c): sorted(u) for c, u in selected.items()},
            "official_population": {
                str(c): {"users": len(u), "reviews": sum(u.values())}
                for c, u in populations.items()
            },
            "excluded_splits": [-1, 4, 11, 12, 13],
        },
    )
    handles = {
        0: (public / "train.jsonl").open("x"),
        1: (public / "ood_val.jsonl").open("x"),
        2: (public / "id_val.jsonl").open("x"),
        3: (target / "query.jsonl").open("x"),
    }
    counts, label_counts = Counter(), {code: Counter() for code in handles}
    query_ids, query_labels, query_users = [], [], []
    offset = 0
    try:
        for chunk in pd.read_csv(
            raw / "reviews.csv",
            usecols=["reviewerID", "reviewText", "category", "overall"],
            dtype={"reviewerID": str, "reviewText": str, "category": str},
            keep_default_na=False,
            quoting=csv.QUOTE_NONNUMERIC,
            chunksize=50_000,
        ):
            for local, row in enumerate(chunk.itertuples(index=False, name=None)):
                # CSV column order, not the usecols argument order, controls tuples.
                item = dict(zip(chunk.columns, row, strict=True))
                index, code = offset + local, int(splits[offset + local])
                user = item["reviewerID"]
                if code not in handles or user not in selected[0 if code == 2 else code]:
                    continue
                stars = float(item["overall"])
                if stars not in (1.0, 2.0, 3.0, 4.0, 5.0):
                    raise ValueError("Invalid original star rating")
                label = int(stars) - 1
                record = {
                    "review_id": index,
                    "text": item["reviewText"],
                    "user": user_rank(user)[:24],
                    "category": item["category"],
                }
                if code == 3:
                    query_ids.append(index)
                    query_labels.append(label)
                    query_users.append(record["user"])
                else:
                    record["label"] = label
                handles[code].write(json.dumps(record, ensure_ascii=False) + "\n")
                counts[code] += 1
                label_counts[code][label] += 1
            offset += len(chunk)
            if offset % 500_000 == 0:
                print(
                    json.dumps({"source_rows": offset, "retained_reviews": dict(counts)}),
                    flush=True,
                )
    finally:
        for stream in handles.values():
            stream.close()
    if not all(counts[code] for code in handles) or set(label_counts[0]) != set(range(5)):
        raise ValueError("Materialized source lacks required data or training classes")
    np.savez_compressed(
        private / "query-labels.npz",
        review_id=np.array(query_ids, dtype=np.int64),
        label=np.array(query_labels, dtype=np.int64),
        user=np.array(query_users),
    )
    protocol = {
        "task_id": TASK_ID,
        "task_families": 1,
        "dataset": "WILDS Amazon 2.1",
        "split_scheme": "official user",
        "source_pin": json.loads((acquisition / "RECEIPT.json").read_text())["source_pin"],
        "selection": "lowest SHA256 of scitaste-user-shift-v1: + reviewerID; all included-split rows",
        "user_counts": {
            "train": train_users,
            "ood_validation": validation_users,
            "confirmation": confirmation_users,
        },
        "review_counts": {str(k): v for k, v in counts.items()},
        "validation_fitting_permitted": False,
        "confirmation_labels_visible": False,
        "claim_rubric": CLAIM_RUBRIC,
        "endpoints": ["overall accuracy", "10th percentile of per-reviewer accuracy"],
        "sampling_scope": "bounded natural user subset; not full official WILDS leaderboard",
        "train_subjects": "researcher-selected training-based or training-free; controller is not trained",
        "redistribution_authorized": False,
        "research_use_only": True,
        "public_source_contamination": "unknown; public source and model prior exposure not certified",
    }
    retain_json(public / "PROTOCOL.json", protocol)
    (public / "TASK.md").write_text(BRIEF)
    (public / "UPSTREAM-USE.txt").write_text(
        "Original source: WILDS Amazon 2.1, official user split. No explicit license. "
        "Original authors request research purposes only. Do not redistribute raw/derived text "
        "as an openly licensed benchmark. Release loaders, locators and sampling rules instead.\n"
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "predict.py",
            "files": ["predict.py"],
            "methods": ["primary", "control"],
            "selection_rule": "REPLACE with exact validation-only rule",
            "fit_policy": "REPLACE with training-only representation/parameter fit and fixed refit rule",
            "scope": "REPLACE with bounded claim",
            "hypotheses": [
                {
                    "statement": "REPLACE first explanation",
                    "discriminating_prediction": "REPLACE testable contrast",
                },
                {
                    "statement": "REPLACE alternative explanation",
                    "discriminating_prediction": "REPLACE testable contrast",
                },
            ],
        },
    )
    retain_json(
        target / "QUERY.json",
        {
            "task_id": TASK_ID,
            "context_id": "amazon",
            "query": "query.jsonl",
            "train": "train.jsonl",
            "validation": ["id_val.jsonl", "ood_val.jsonl"],
            "classes": 5,
            "output": "amazon--METHOD.npz",
            "query_labels": "evaluator-only",
        },
    )
    files = {
        p.relative_to(output).as_posix(): digest(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    discovery = [f"public/{TASK_ID}/{p.name}" for p in sorted(public.iterdir())]
    retain_json(
        output / "PACK.json",
        {
            "schema_version": "scitastebench.user-shift-task.v1",
            "task_id": TASK_ID,
            "source_commit": protocol["source_pin"],
            "files": files,
            "discovery_files": discovery,
            "transfer_files": ["target/query.jsonl", "target/QUERY.json"],
            "task_families": 1,
            "source_extraction": extraction,
            "counts": protocol["review_counts"],
            "users": protocol["user_counts"],
            "private_label_distribution": {str(c): dict(v) for c, v in label_counts.items()},
            "formal_evidence_eligible": False,
            "scientific_task_admitted": False,
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    print(
        json.dumps(
            {
                "pack": str(output),
                "reviews": dict(counts),
                "elapsed_seconds": time.monotonic() - started,
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-users", type=int, default=1024)
    parser.add_argument("--validation-users", type=int, default=128)
    parser.add_argument("--confirmation-users", type=int, default=256)
    args = parser.parse_args()
    if not all(
        1 <= n <= 4096 for n in (args.train_users, args.validation_users, args.confirmation_users)
    ):
        parser.error("Bound reviewer sample sizes explicitly")
    build(
        args.acquisition.resolve(strict=True),
        args.output.resolve(),
        args.train_users,
        args.validation_users,
        args.confirmation_users,
    )


if __name__ == "__main__":
    main()

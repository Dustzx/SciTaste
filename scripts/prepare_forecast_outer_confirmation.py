"""Reserve an additional history-disjoint forecast check before successor outcomes.

Same public assets and fitted rules, new within-source series identities. This is
not a new task family, a source-disjoint test or a full M4 competition evaluation.
"""

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scripts.build_forecasting_research_task import (
    COUNTS,
    HORIZON,
    MAX_HISTORY,
    MIN_HISTORY,
    SEED,
    SOURCE_SHA,
)


def prepare(project, study, output, *, series=1000):
    project, study, output = (
        project.resolve(strict=True),
        study.resolve(strict=True),
        output.resolve(),
    )
    output.relative_to(study)
    study_contract = json.loads((study / "STUDY.json").read_text())
    successor_run = project / study_contract["allocations"]["forecasting"]["run"]
    # Predeclare before the first new measured panel, not after a favorable result.
    if (
        list((successor_run / "workspace").glob("**/SUMMARY.json"))
        or (successor_run / "workspace/confirmation_feedback.json").exists()
    ):
        raise ValueError("Reserve the outer check before successor numerical outcomes")
    campaign = verified_asset(project, study_contract["allocations"]["forecasting"]["campaign"])
    contract = json.loads(campaign.read_text())
    original_pack = verified_asset(project, contract["pack"]).parent
    original = json.loads((original_pack / "PACK.json").read_text())
    split = json.loads((original_pack / "private/SPLIT_FREEZE.json").read_text())
    if split["seed"] != SEED or original["source_sha256"] != SOURCE_SHA or series != 1000:
        raise ValueError("Keep the one prespecified 1000-series outer check")
    archive = project / (
        "evaluations/acquisitions/m4-monthly-official-20261008-v1/m4_monthly_dataset.zip"
    )
    if digest(archive) != SOURCE_SHA:
        raise ValueError("Original source bytes changed")
    groups = {}
    with zipfile.ZipFile(archive) as zipped:
        with zipped.open("m4_monthly_dataset.tsf") as stream:
            in_data = False
            for raw in stream:
                line = raw.decode("cp1252").strip()
                if not line or line.startswith("#"):
                    continue
                if not in_data:
                    in_data = line.lower() == "@data"
                    continue
                original_id, _, values = line.split(":")
                tokens = values.split(",")
                if len(tokens) - HORIZON < MIN_HISTORY:
                    continue
                history = np.asarray(tokens[:-HORIZON][-MAX_HISTORY:], dtype="<f8")
                if not np.isfinite(history).all():
                    raise ValueError("Invalid history; no outcome-dependent exclusions")
                key = hashlib.sha256(history.tobytes()).hexdigest()
                # Neither convert nor inspect future numbers before identity assignment.
                groups.setdefault(key, (original_id, history, tokens[-HORIZON:]))
    ordered = sorted(
        groups, key=lambda key: hashlib.sha256((SEED + ":" + key).encode()).hexdigest()
    )
    offset = sum(COUNTS.values())
    prior = [key for phase in COUNTS for key in split["groups"][phase]]
    if ordered[:offset] != prior or len(ordered) < offset + series:
        raise ValueError("Original identity grouping or population changed")
    selected = ordered[offset : offset + series]
    if set(selected) & set(prior):
        raise ValueError("Outer identities overlap original exposed population")
    output.mkdir(exist_ok=False)
    public, private, target = (
        output / "public/cross-series-forecasting",
        output / "private",
        output / "target",
    )
    public.mkdir(parents=True)
    private.mkdir()
    target.mkdir()
    for name in original["discovery_files"]:
        source = original_pack / name
        if digest(source) != original["files"][name]:
            raise ValueError("Public training or selection asset changed")
        shutil.copy2(source, public / source.name)
    frozen_at = datetime.now(UTC).isoformat()
    # Write the identity reservation BEFORE interpreting the reserved futures.
    retain_json(
        private / "SPLIT_FREEZE.json",
        {
            "frozen_at": frozen_at,
            "source_sha256": SOURCE_SHA,
            "original_pack_sha256": digest(original_pack / "PACK.json"),
            "seed": SEED,
            "groups": selected,
            "hash_order_offset": offset,
            "before_reserved_future_numeric_interpretation": True,
            "disjoint_from_original_fit_discovery_validation_confirmation": True,
            "same_source_near_duplicate_or_model_pretraining_exposure": "unknown",
        },
    )
    lengths = np.array([len(groups[key][1]) for key in selected], dtype=np.int64)
    histories = np.zeros((series, MAX_HISTORY), dtype=np.float64)
    for index, key in enumerate(selected):
        histories[index, -lengths[index] :] = groups[key][1]
    arrays = {
        "series_id": np.array(
            [
                int(hashlib.sha256((SEED + ":id:" + key).encode()).hexdigest()[:15], 16)
                for key in selected
            ],
            dtype=np.int64,
        ),
        "history": histories,
        "history_length": lengths,
    }
    futures = np.asarray([groups[key][2] for key in selected], dtype=np.float64)
    if futures.shape != (series, HORIZON) or not np.isfinite(futures).all():
        raise ValueError("Invalid reserved futures; no alternative subset may be selected")
    np.savez_compressed(target / "monthly-query.npz", **arrays)
    np.savez_compressed(private / "monthly-labels.npz", **arrays, future=futures)
    retain_json(
        target / "QUERY.json",
        {"task_id": contract["task_id"], "contexts": {"monthly": "monthly-query.npz"}},
    )
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    pack = {
        **original,
        "frozen_at": frozen_at,
        "files": files,
        "inventories": {**original["inventories"], "confirmation": series},
        "original_pack_sha256": digest(original_pack / "PACK.json"),
        "scope": "Prespecified history-disjoint within-source outer development check; "
        "not a new task family, source-disjoint generalization or formal full M4 ranking",
        "research_outcomes_before_freeze": False,
        "formal_evidence_eligible": False,
    }
    retain_json(output / "PACK.json", pack)
    retain_json(
        output / "PROTOCOL.json",
        {
            "frozen_at": frozen_at,
            "source_study_sha256": digest(study / "STUDY.json"),
            "pack_sha256": digest(output / "PACK.json"),
            "primary_endpoint": "mean_mase",
            "series": series,
            "assignments": {
                "original-native": "evaluations/"
                "scitastebench-m4-monthly-three-systems-20261008-v2/confirmation/"
                "scitaste-native/release/frozen_submission",
                "successor-native": study_contract["allocations"]["forecasting"]["run"],
            },
            "selection": "Retain each assignment's original public-selected primary; no "
            "selection or repair from either old or outer confirmation outcomes",
            "execution": "Exactly one read-only source execution per assignment, same public "
            "training/selection assets, 2 CPU threads, no network/GPU, 1800 CPU seconds max",
            "failure": "Any missing or invalid output leaves complete primary missing; "
            "retain failures, no survivor mean or new identity subset",
            "report_all_assigned_outcomes": True,
            "unobserved_outer_outcomes_certified": False,
            "limits": "Named original population is identity-disjoint, not proof of absent "
            "pretraining exposure/near duplicates or source-family independence. Different "
            "allocations and combined successor changes do not isolate a Taste effect.",
            "formal_evidence_eligible": False,
        },
    )
    return {"pack": str(output), "reserved_series": series, "new_task_families": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "study", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.project, args.study, args.output)))

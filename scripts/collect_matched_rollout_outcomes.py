"""Retain a prospectively matched ON/OFF observation, including adverse results."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.graph_task_data import bound_file
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def collect(project, parent, off, output, allow_score_collection_recovery=False):
    project = project.resolve(strict=True)
    parent, off = parent.resolve(strict=True), off.resolve(strict=True)
    parent.relative_to(project / "evaluations")
    off.relative_to(project / "evaluations")
    output = output.resolve()
    output.relative_to(off.parent)
    on_contract, off_contract = [json.loads(path.read_text()) for path in (parent, off)]
    prospective_pair = None
    if "matched_parent_campaign" in off_contract:
        bound_parent = verified_asset(project, off_contract["matched_parent_campaign"])
    else:
        # Older frozen cohorts bind the prospective match separately. Do not
        # edit their immutable campaign merely to adopt a newer schema.
        pair_path = off.parent / "PAIRED_STUDY.json"
        pair = json.loads(pair_path.read_text())
        bound_parent = verified_asset(project, pair["parent"])
        if (
            verified_asset(project, pair["off"]) != off
            or not pair["frozen_before_all_execution"]
            or not pair["same_harness_and_skills"]
            or pair["resource_envelope"] != on_contract["resource_envelope"]
        ):
            raise ValueError("Separate pair contract is not a prospective identical-budget match")
        prospective_pair = {
            "locator": pair_path.relative_to(project).as_posix(),
            "sha256": digest(pair_path),
        }
    if (
        bound_parent != parent
        or on_contract["task_id"] != off_contract["task_id"]
        or on_contract["pack"] != off_contract["pack"]
        or on_contract["resource_envelope"] != off_contract["resource_envelope"]
        or off_contract["arms"] != ["scitaste-native"]
        or off_contract["native_taste"]["mode"] != "off"
        or off_contract["native_taste"]["binding"] is not None
        or off_contract["native_taste"]["proposal_context"] != "disabled"
    ):
        raise ValueError("Not an explicitly matched, no-experience assignment")
    for key in ("execution_brief", "rubric", "claim_rubric"):
        if key not in on_contract and key not in off_contract:
            continue
        if digest(verified_asset(project, on_contract[key])) != digest(
            verified_asset(project, off_contract[key])
        ):
            raise ValueError("Scientific task or claim rubric differs")
    for name, asset in on_contract["researcher_assets"].items():
        if digest(verified_asset(project, asset)) != digest(
            verified_asset(project, off_contract["researcher_assets"][name])
        ):
            raise ValueError("Released scientific evidence differs")
    observed, sources, launches, original_receipts, score_recoveries = [], [], [], [], []
    for path in (parent, off):
        source = path.parent / "SCIENTIFIC_RESULTS.json"
        value = json.loads(source.read_text())
        if (
            verified_asset(project, value["campaign"]) != path
            or value["pack"] != on_contract["pack"]
            or value["primary_selected_after_private_scoring"]
            or not value["all_declared_procedures_failures_and_qualification_flags_retained"]
        ):
            raise ValueError("Scientific outcomes are not bound to the matched contracts")
        row = next(r for r in value["original_rows"] if r["system"] == "scitaste-native")
        original_receipts.append(row["confirmation"])
        collection_recovery = None
        if not row.get("executed_frozen_source") or row["primary_method"] is None:
            candidates = [
                r
                for r in value.get("separate_score_collection_recovery_rows", [])
                if r["system"] == "scitaste-native"
            ]
            if not allow_score_collection_recovery or len(candidates) != 1:
                raise ValueError(
                    "Missing original primary; explicit unique score-only recovery required"
                )
            recovered = candidates[0]
            collection_recovery = recovered["score_collection_recovery"]
            recovery = json.loads(verified_asset(project, collection_recovery).read_text())
            if (
                recovered["source_run"] != row["source_run"]
                or not row.get("inference_completed_before_scoring")
                or recovery["original_failure_sha256"] != row["confirmation"]["sha256"]
                or recovery["new_inference_runs"] != 0
                or recovery["new_model_calls"] != 0
                or recovery["original_failure_replaced"]
            ):
                raise ValueError("Cannot replace an original failure or rerun a paired arm")
            row = recovered
        score_recoveries.append(collection_recovery)
        if not row.get("executed_frozen_source") or row["primary_method"] is None:
            raise ValueError("Both arms require actual execution and one frozen primary")
        for key in ("confirmation", "submission", "inference", "release", "execution"):
            verified_asset(project, row[key])
        origin = project / row["source_run"] / "CONTRACT.json"
        execution = json.loads(verified_asset(project, row["execution"]).read_text())
        if digest(origin) != execution["source_contract_sha256"]:
            raise ValueError("Original Native launch changed")
        launches.append(json.loads(origin.read_text()))
        observed.append(row)
        sources.append(
            {"locator": source.relative_to(project).as_posix(), "sha256": digest(source)}
        )
    for key in ("harness", "research_harness", "runtime_sources"):
        if launches[0]["plan"][key] != launches[1]["plan"][key]:
            raise ValueError("Native harness, skills or runtime allocation differs")
    if set(observed[0]["primary_scores"]) != set(observed[1]["primary_scores"]):
        raise ValueError("Unequal target contexts")
    pack_path = verified_asset(project, on_contract["pack"])
    pack = json.loads(pack_path.read_bytes())
    roster_keys = {
        "stable-physical-rollout": ("per_trajectory", "trajectory_id"),
        "cross-series-forecasting": ("per_series", "series_id"),
        "combinatorial-perturbation": ("per_condition", "condition_id"),
    }
    for context in observed[0]["primary_scores"]:
        units = []
        for row in observed:
            primary = next(
                r
                for r in row["all_method_context_scores"]
                if r["context"] == context and r["method"] == row["primary_method"]
            )
            metrics = primary["metrics"]
            if on_contract["task_id"] == "population-shift-calibration":
                # Population receipts deliberately avoid publishing person-level
                # outcomes. Check their already-produced identity roster against
                # the exact redacted target instead; do not query labels or infer.
                import numpy as np

                query = bound_file(pack_path.parent, pack, f"target/{context}-query.npz")
                execution_root = verified_asset(project, row["execution"]).parent
                prediction = (
                    execution_root
                    / "execution/predictions"
                    / f"{context}--{row['primary_method']}.npz"
                )
                prediction = prediction.resolve(strict=True)
                prediction.relative_to(execution_root)
                if digest(prediction) != primary["prediction_sha256"]:
                    raise ValueError("Retained selected population prediction changed")
                with np.load(query, allow_pickle=False) as target:
                    expected_ids = target["person_id"].tolist()
                with np.load(prediction, allow_pickle=False) as proposed:
                    ids = proposed["person_id"].tolist()
                if (
                    len(ids) != len(set(ids))
                    or set(ids) != set(expected_ids)
                    or metrics["persons"] != len(ids)
                ):
                    raise ValueError("Population primary must cover the frozen target roster")
            else:
                if on_contract["task_id"] not in roster_keys:
                    raise ValueError("No declared target identity unit for this task")
                key, id_key = roster_keys[on_contract["task_id"]]
                ids = [record[id_key] for record in metrics[key]]
                if len(ids) != len(set(ids)):
                    raise ValueError("Repeated target identities cannot establish full coverage")
            units.append(set(ids))
        if not units[0] or units[0] != units[1]:
            raise ValueError("Selected methods do not cover identical target identities")
    scores = [row["primary_scores"] for row in observed]
    result = {
        "schema_version": "scitastebench.matched-rollout-observation.v1",
        "task_id": on_contract["task_id"],
        "task_families": 1,
        "scientific_results": sources,
        "prospective_pair_contract": prospective_pair,
        "original_confirmation_receipts": original_receipts,
        "score_collection_recoveries": score_recoveries,
        "original_failure_replaced": False,
        "new_inference_runs": 0,
        "secondary_observation_uses_score_collection_recovery": any(score_recoveries),
        "primary_methods": {
            "taste": observed[0]["primary_method"],
            "off": observed[1]["primary_method"],
        },
        "primary_scores": {"taste": scores[0], "off": scores[1]},
        "taste_minus_off": {
            context: scores[0][context] - scores[1][context]
            if scores[0][context] is not None and scores[1][context] is not None
            else None
            for context in scores[0]
        },
        "lower_is_better": True,
        "task_assets_budget_and_target_ids_matched": True,
        "within_task_id_counts_are_not_independent_research_tasks": True,
        "verified_backbone_randomness_parity": False,
        "causal_taste_effect_established": False,
        "formal_evidence_eligible": False,
        "scope": "One observed pair of genuinely executed research trajectories. Preserve "
        "adverse/null outcomes. Different selected procedures and unknown backbone/randomness "
        "parity do not establish causal benefit or harm, mediation, or universal efficacy.",
    }
    retain_json(output, result)
    return {
        "output": str(output),
        "sha256": digest(output),
        "difference": result["taste_minus_off"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "parent", "off", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument(
        "--allow-score-collection-recovery",
        action="store_true",
        help="Secondary observation only; retain original failures and require zero new inference",
    )
    print(json.dumps(collect(**vars(parser.parse_args()))))

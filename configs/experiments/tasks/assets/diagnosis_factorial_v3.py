"""Frozen executable kernel for the diagnosis-friendly v2 study task.

This file is a content-addressed study asset.  It generates explicit binary
evidence packets, applies three transparent decision rules to the same packets,
and reports measurements computed from their predictions.  It intentionally
contains no model calls, network access, external data, or fitted parameters.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from itertools import product
from typing import Any

import numpy as np

MACHINE_EVIDENCE_PREFIX = "SCITASTE_EVIDENCE_JSON="
KERNEL_ID = "diagnosis-factorial-v3"

EXPECTED_CONTRACT = {
    "citation_topologies": ["flat", "chain"],
    "conditions": [
        "majority_vote",
        "confidence_weighted_vote",
        "position_aware_probe",
    ],
    "contradiction_densities": [0.0, 0.25, 0.5],
    "examples_per_cell": 12,
    "failure_threshold": 0.75,
    "generator": KERNEL_ID,
    "metrics": ["balanced_accuracy", "factor_effects", "failure_boundaries"],
    "minimum_reproducing_seeds": 2,
    "packet_lengths": [8, 32, 128],
    "seeds": [7, 19, 31],
    "target_positions": ["start", "middle", "end"],
}


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract != EXPECTED_CONTRACT:
        raise ValueError("benchmark contract does not match the frozen executable kernel")


def _balanced_accuracy(labels: list[int], predictions: list[int]) -> float:
    paired = zip(labels, predictions, strict=True)
    positive = [prediction for label, prediction in paired if label == 1]
    paired = zip(labels, predictions, strict=True)
    negative = [prediction for label, prediction in paired if label == -1]
    if not positive or not negative:
        raise ValueError("balanced accuracy requires both registered classes")
    true_positive_rate = sum(value == 1 for value in positive) / len(positive)
    true_negative_rate = sum(value == -1 for value in negative) / len(negative)
    return float((true_positive_rate + true_negative_rate) / 2.0)


def _predict(votes: np.ndarray, confidence: np.ndarray, salience: np.ndarray, method: str) -> int:
    if method == "majority_vote":
        score = float(votes.sum())
    elif method == "confidence_weighted_vote":
        score = float(np.dot(votes, confidence))
    elif method == "position_aware_probe":
        selected_count = max(1, math.ceil(math.log2(len(votes))))
        selected = np.argsort(salience, kind="stable")[-selected_count:]
        score = float(np.dot(votes[selected], confidence[selected] * (1.0 + salience[selected])))
    else:
        raise ValueError(f"unsupported registered condition: {method}")
    return 1 if score >= 0.0 else -1


def _packet(
    *,
    seed: int,
    factor_indexes: tuple[int, int, int, int],
    example_index: int,
    target_position: str,
    packet_length: int,
    contradiction_density: float,
    citation_topology: str,
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    position_index, length_index, density_index, topology_index = factor_indexes
    seed_sequence = np.random.SeedSequence(
        [seed, position_index, length_index, density_index, topology_index, example_index]
    )
    rng = np.random.default_rng(seed_sequence)
    label = 1 if example_index % 2 else -1
    target_index = {
        "start": 0,
        "middle": packet_length // 2,
        "end": packet_length - 1,
    }[target_position]

    contradictory = rng.random(packet_length) < contradiction_density
    votes = np.where(contradictory, -label, label).astype(np.int8)
    votes[target_index] = label

    confidence = np.where(
        contradictory,
        rng.uniform(0.35, 0.60, packet_length),
        rng.uniform(0.55, 0.85, packet_length),
    )
    confidence[target_index] = 0.95

    salience = rng.uniform(0.05, 0.65, packet_length)
    salience[target_index] = {"start": 1.0, "middle": 0.45, "end": 0.72}[target_position]
    if citation_topology == "chain":
        depth = np.linspace(0.0, 1.0, packet_length)
        confidence *= 1.0 - 0.30 * depth
        salience += 0.12 * (1.0 - depth)
    elif citation_topology != "flat":
        raise ValueError(f"unsupported citation topology: {citation_topology}")
    return label, votes, confidence, salience


def _factor_effects(
    cell_scores: list[dict[str, Any]], conditions: list[str]
) -> dict[str, dict[str, float]]:
    effects: dict[str, dict[str, float]] = {}
    factors = (
        "target_position",
        "packet_length",
        "contradiction_density",
        "citation_topology",
    )
    for condition in conditions:
        effects[condition] = {}
        for factor in factors:
            grouped: dict[str, list[float]] = defaultdict(list)
            for cell in cell_scores:
                grouped[str(cell[factor])].append(float(cell["accuracy"][condition]))
            means = [sum(values) / len(values) for values in grouped.values()]
            effects[condition][factor] = float(max(means) - min(means))
    return effects


def _failure_boundaries(
    cell_scores: list[dict[str, Any]],
    conditions: list[str],
    *,
    threshold: float,
    minimum_seeds: int,
) -> dict[str, Any]:
    """Find factor cells whose failures recur across registered seeds."""

    grouped: dict[str, dict[tuple[str, int, float, str], dict[int, float]]] = {
        condition: defaultdict(dict) for condition in conditions
    }
    for cell in cell_scores:
        factor_cell = (
            str(cell["target_position"]),
            int(cell["packet_length"]),
            float(cell["contradiction_density"]),
            str(cell["citation_topology"]),
        )
        for condition in conditions:
            grouped[condition][factor_cell][int(cell["seed"])] = float(cell["accuracy"][condition])

    by_condition: dict[str, dict[str, Any]] = {}
    for condition in conditions:
        reproduced: list[dict[str, Any]] = []
        for factor_cell, seed_values in grouped[condition].items():
            below = sorted(seed for seed, value in seed_values.items() if value < threshold)
            if len(below) < minimum_seeds:
                continue
            position, packet_length, density, topology = factor_cell
            values = list(seed_values.values())
            reproduced.append(
                {
                    "target_position": position,
                    "packet_length": packet_length,
                    "contradiction_density": density,
                    "citation_topology": topology,
                    "mean_balanced_accuracy": float(sum(values) / len(values)),
                    "reproducing_seeds": below,
                }
            )
        reproduced.sort(
            key=lambda item: (
                item["mean_balanced_accuracy"],
                item["packet_length"],
                item["contradiction_density"],
                item["target_position"],
                item["citation_topology"],
            )
        )
        by_condition[condition] = {
            "count": len(reproduced),
            "worst_cells": reproduced[:8],
        }
    return {
        "balanced_accuracy_threshold": threshold,
        "minimum_reproducing_seeds": minimum_seeds,
        "criterion": "cell balanced accuracy below threshold on the minimum seed count",
        "by_condition": by_condition,
    }


def execute_benchmark(contract: dict[str, Any]) -> dict[str, Any]:
    """Execute the complete registered packet grid and return audited evidence."""

    _validate_contract(contract)
    conditions = list(contract["conditions"])
    labels_by_seed: dict[int, list[int]] = {int(seed): [] for seed in contract["seeds"]}
    predictions_by_seed: dict[int, dict[str, list[int]]] = {
        int(seed): {condition: [] for condition in conditions} for seed in contract["seeds"]
    }
    cell_scores: list[dict[str, Any]] = []

    factor_grid = product(
        enumerate(contract["target_positions"]),
        enumerate(contract["packet_lengths"]),
        enumerate(contract["contradiction_densities"]),
        enumerate(contract["citation_topologies"]),
    )
    registered_cells = list(factor_grid)
    for seed in contract["seeds"]:
        seed = int(seed)
        for indexed_position, indexed_length, indexed_density, indexed_topology in registered_cells:
            position_index, target_position = indexed_position
            length_index, packet_length = indexed_length
            density_index, contradiction_density = indexed_density
            topology_index, citation_topology = indexed_topology
            cell_labels: list[int] = []
            cell_predictions = {condition: [] for condition in conditions}
            for example_index in range(int(contract["examples_per_cell"])):
                label, votes, confidence, salience = _packet(
                    seed=seed,
                    factor_indexes=(position_index, length_index, density_index, topology_index),
                    example_index=example_index,
                    target_position=str(target_position),
                    packet_length=int(packet_length),
                    contradiction_density=float(contradiction_density),
                    citation_topology=str(citation_topology),
                )
                cell_labels.append(label)
                labels_by_seed[seed].append(label)
                for condition in conditions:
                    prediction = _predict(votes, confidence, salience, condition)
                    cell_predictions[condition].append(prediction)
                    predictions_by_seed[seed][condition].append(prediction)
            cell_scores.append(
                {
                    "seed": seed,
                    "target_position": target_position,
                    "packet_length": packet_length,
                    "contradiction_density": contradiction_density,
                    "citation_topology": citation_topology,
                    "accuracy": {
                        condition: _balanced_accuracy(cell_labels, cell_predictions[condition])
                        for condition in conditions
                    },
                }
            )

    per_seed = {
        condition: {
            str(seed): _balanced_accuracy(
                labels_by_seed[seed], predictions_by_seed[seed][condition]
            )
            for seed in contract["seeds"]
        }
        for condition in conditions
    }
    condition_evidence: dict[str, dict[str, Any]] = {}
    for condition in conditions:
        values = list(per_seed[condition].values())
        mean = sum(values) / len(values)
        std = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        condition_evidence[condition] = {
            "per_seed": per_seed[condition],
            "mean": float(mean),
            "std": float(std),
        }
    primary = sum(item["mean"] for item in condition_evidence.values()) / len(condition_evidence)
    packets_per_seed = (
        len(contract["target_positions"])
        * len(contract["packet_lengths"])
        * len(contract["contradiction_densities"])
        * len(contract["citation_topologies"])
        * int(contract["examples_per_cell"])
    )
    return {
        "schema_version": "1.0",
        "primary_metric": {"name": "balanced_accuracy", "value": float(primary)},
        "conditions": condition_evidence,
        "diagnostics": {
            "kernel_id": KERNEL_ID,
            "packets_per_seed": packets_per_seed,
            "generated_packets": packets_per_seed * len(contract["seeds"]),
            "factor_effects": _factor_effects(cell_scores, conditions),
            "failure_boundaries": _failure_boundaries(
                cell_scores,
                conditions,
                threshold=float(contract["failure_threshold"]),
                minimum_seeds=int(contract["minimum_reproducing_seeds"]),
            ),
        },
    }


def run_and_emit(contract: dict[str, Any]) -> dict[str, Any]:
    """Execute once, report harness metrics, and emit human and machine evidence."""

    from experiment_harness import ExperimentHarness

    evidence = execute_benchmark(contract)
    harness = ExperimentHarness(time_budget=1200)
    for seed in contract["seeds"]:
        print(f"Seed {seed}")
        for condition in contract["conditions"]:
            value = evidence["conditions"][condition]["per_seed"][str(seed)]
            print(f"{condition}: balanced_accuracy={value:.12f}")
    for condition in contract["conditions"]:
        record = evidence["conditions"][condition]
        print(
            f"{condition}: mean_balanced_accuracy={record['mean']:.12f}, std={record['std']:.12f}"
        )
        harness.report_metric(condition, float(record["mean"]))
    harness.report_metric("balanced_accuracy", float(evidence["primary_metric"]["value"]))
    for condition, effects in evidence["diagnostics"]["factor_effects"].items():
        for factor, value in effects.items():
            print(f"factor_effect {condition} {factor}={value:.12f}")
    boundaries = evidence["diagnostics"]["failure_boundaries"]
    for condition, record in boundaries["by_condition"].items():
        print(f"failure_boundary_count {condition}={record['count']}")
    print(f"Total examples: {evidence['diagnostics']['generated_packets']}")
    harness.finalize()
    print(MACHINE_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return evidence

#!/usr/bin/env python3
"""Admit a valid counterfactual confirmation into a venue-gap evidence portfolio."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from scitaste.evaluation.counterfactual_confirmation import (
    CounterfactualConfirmationReport,
)
from scitaste.evidence.venue_gap import VenueComparisonProfile, VenueGapManifest


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
        handle.flush()
        os.fsync(handle.fileno())


def _append_unique(items: list[str], value: str) -> list[str]:
    return sorted({*items, value})


def run(args: argparse.Namespace) -> tuple[VenueGapManifest, VenueComparisonProfile]:
    report = CounterfactualConfirmationReport.model_validate_json(
        args.report.read_bytes(), strict=True
    )
    if not report.confirmation_population_valid or report.verdict == "inadmissible":
        raise ValueError("inadmissible confirmation cannot enter the venue evidence portfolio")

    protocol = yaml.safe_load(args.protocol.read_text(encoding="utf-8"))
    manifest_payload = yaml.safe_load(args.source_manifest.read_text(encoding="utf-8"))
    profile_payload = yaml.safe_load(args.source_comparison.read_text(encoding="utf-8"))
    manifest_payload["manifest_id"] = args.manifest_id
    profile_payload["profile_id"] = args.comparison_id
    profile_payload["venue_gap_manifest_id"] = args.manifest_id

    completed_action_id = "build-objective-counterfactual-taste-study"
    successor_action_id = "learn-content-conditioned-taste-policy"
    for criterion in manifest_payload["criteria"]:
        criterion["candidate_action_ids"] = sorted(
            successor_action_id if item == completed_action_id else item
            for item in criterion["candidate_action_ids"]
        )
    for action in manifest_payload["candidate_actions"]:
        if action["action_id"] == completed_action_id:
            action.update(
                {
                    "action_id": successor_action_id,
                    "title": (
                        "Learn content- and applicability-conditioned Taste, then confirm "
                        "on a new disjoint population"
                    ),
                    "estimated_hours": 16.0,
                    "expected_information_gain": 1.0,
                    "feasibility": 0.8,
                    "estimated_api_cost_usd": 60.0,
                }
            )

    research_model = protocol["models"]["research_agent"]["requested_model"]
    judge_model = protocol["models"]["terminal_judge"]["model"]
    domains = sorted({item.task_cluster_id for item in report.states})
    primary = next(
        item for item in report.contrasts if item.baseline_action.value == "PROBE"
    )
    experiment = next(
        item for item in report.contrasts if item.baseline_action.value == "EXPERIMENT"
    )
    low, high = primary.exhaustive_task_cluster_bootstrap_95_interval
    direction = "supporting" if report.verdict == "supported" else "contradicting"
    shared = {
        "family_id": "newtonbench-counterfactual-formal-v4",
        "maturity": "admitted",
        "headline_eligible": report.headline_eligible,
        "objective_measurement": True,
        "held_out": True,
        "model_ids": [research_model, judge_model],
        "domain_ids": domains,
    }
    signals = [
        {
            "evidence_id": "newtonbench-formal-v4-policy-effect",
            **shared,
            "dimension": "downstream-causal-utility",
            "evidence_type": "decision-to-outcome-causal-effect",
            "summary": (
                f"On {report.state_count} held-out states in {report.task_cluster_count} task "
                f"clusters, the frozen policy minus static PROBE was "
                f"{primary.paired_mean_difference:+.6f} with exhaustive task-cluster interval "
                f"[{low:.6f}, {high:.6f}], {primary.practical_wins} practical wins, "
                f"{primary.practical_losses} losses, and {primary.practical_ties} ties. "
                f"Static EXPERIMENT exceeded the policy by "
                f"{-experiment.paired_mean_difference:.6f}; verdict={report.verdict}."
            ),
            "direction": direction,
        },
        {
            "evidence_id": "newtonbench-formal-v4-status-representation",
            **shared,
            "dimension": "mechanism-and-selectivity",
            "evidence_type": "state-conditional-action-transfer",
            "summary": (
                "The evidence-status-only policy selected ANALYZE or PROBE but did not "
                "transfer across held-out heat, magnetic-force, and refraction states; "
                "content and applicability variables are missing from the representation."
            ),
            "direction": direction,
        },
        {
            "evidence_id": "newtonbench-formal-v4-failure-boundary",
            **shared,
            "dimension": "failure-boundaries",
            "evidence_type": "transfer-failure-taxonomy",
            "summary": (
                "A valid held-out confirmation identifies evidence status as an insufficient "
                "conditioning variable and locks the split against post-hoc policy refitting."
            ),
            "direction": "supporting",
        },
        {
            "evidence_id": "newtonbench-formal-v4-independent-population",
            **shared,
            "dimension": "statistical-strength",
            "evidence_type": "independent-task-population",
            "summary": (
                "The policy was frozen on disjoint development results before evaluation on "
                "four held-out task clusters; four clusters remain too few for a positive "
                "generalization claim."
            ),
            "direction": "supporting",
        },
    ]
    existing_ids = {item["evidence_id"] for item in manifest_payload["evidence"]}
    if existing_ids & {item["evidence_id"] for item in signals}:
        raise ValueError("confirmation evidence is already present in the source manifest")
    manifest_payload["evidence"].extend(signals)

    claim_bindings = {
        "scientific-taste-problem": "newtonbench-formal-v4-policy-effect",
        "conditional-taste-policy": "newtonbench-formal-v4-status-representation",
        "outcome-calibrated-learning": "newtonbench-formal-v4-policy-effect",
        "contrastive-taste-abstraction": "newtonbench-formal-v4-status-representation",
    }
    for claim in profile_payload["innovation_claims"]:
        evidence_id = claim_bindings.get(claim["claim_id"])
        if evidence_id is not None:
            claim["effect_evidence_ids"] = _append_unique(
                claim["effect_evidence_ids"], evidence_id
            )

    component_bindings = {
        "failure-boundary-analysis": "newtonbench-formal-v4-failure-boundary",
        "mechanism-ablation": "newtonbench-formal-v4-status-representation",
        "objective-or-hidden-evaluation": "newtonbench-formal-v4-policy-effect",
        "statistical-uncertainty": "newtonbench-formal-v4-independent-population",
        "task-and-domain-breadth": "newtonbench-formal-v4-independent-population",
    }
    by_component = {
        item["component"]: item for item in profile_payload["current_evidence_components"]
    }
    for component, evidence_id in component_bindings.items():
        binding = by_component.get(component)
        if binding is None:
            binding = {"component": component, "evidence_ids": []}
            profile_payload["current_evidence_components"].append(binding)
        binding["evidence_ids"] = _append_unique(binding["evidence_ids"], evidence_id)
    profile_payload["current_evidence_components"].sort(key=lambda item: item["component"])

    manifest = VenueGapManifest.model_validate(manifest_payload)
    profile = VenueComparisonProfile.model_validate(profile_payload)
    _write_exclusive(args.output_manifest, manifest.model_dump(mode="json"))
    _write_exclusive(args.output_comparison, profile.model_dump(mode="json"))
    return manifest, profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-comparison", type=Path, required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--comparison-id", required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-comparison", type=Path, required=True)
    return parser


def main() -> None:
    manifest, profile = run(build_parser().parse_args())
    print(f"{manifest.manifest_id}\t{profile.profile_id}")


if __name__ == "__main__":
    main()

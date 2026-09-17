#!/usr/bin/env python3
"""Summarize development-only counterfactual action sets as one cohort."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_cohort import (
    CounterfactualDevelopmentCohortProtocol,
    CounterfactualTrajectoryPhase,
    save_counterfactual_development_cohort_report,
    summarize_counterfactual_development_cohort,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult


def _result(path: str) -> CounterfactualActionSetResult:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"counterfactual result must be a regular file: {source}")
    return CounterfactualActionSetResult.model_validate_json(source.read_bytes(), strict=True)


def run(args: argparse.Namespace):
    entries = tuple(_parse_entry(value) for value in args.state)
    protocol = CounterfactualDevelopmentCohortProtocol(
        protocol_id=args.protocol_id,
        minimum_state_count=args.minimum_states,
        minimum_domain_count=args.minimum_domains,
        minimum_phase_count=args.minimum_phases,
        minimum_objective_observation_rate=args.minimum_metric_coverage,
        minimum_choice_sensitive_state_count=args.minimum_choice_sensitive_states,
        require_complete_action_space=True,
    )
    report = summarize_counterfactual_development_cohort(
        cohort_id=args.cohort_id,
        project_id=args.project_id,
        protocol=protocol,
        results=tuple(_result(item[3]) for item in entries),
        state_ids=tuple(item[0] for item in entries),
        domain_ids=tuple(item[1] for item in entries),
        phases=tuple(item[2] for item in entries),
    )
    save_counterfactual_development_cohort_report(report, args.output)
    return report


def _parse_entry(value: str) -> tuple[str, str, CounterfactualTrajectoryPhase, str]:
    parts = value.split(",", maxsplit=3)
    if len(parts) != 4:
        raise ValueError("--state must be STATE_ID,DOMAIN_ID,PHASE,RESULT_PATH")
    return parts[0], parts[1], CounterfactualTrajectoryPhase(parts[2]), parts[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--project-id", default="scitaste-self-development")
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--minimum-states", type=int, required=True)
    parser.add_argument("--minimum-domains", type=int, required=True)
    parser.add_argument("--minimum-phases", type=int, required=True)
    parser.add_argument("--minimum-metric-coverage", type=float, required=True)
    parser.add_argument("--minimum-choice-sensitive-states", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    print(run(build_parser().parse_args()).model_dump_json(indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Select one development Taste successor from frozen decision artifacts.

This command never invokes a model, executor, API, or GPU. It cannot promote
the selected policy into a deployed research system or establish an RSI claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
    DecisionScoringKey,
)
from scitaste.evaluation.taste_evolution import (
    TasteEvolutionPlan,
    TasteEvolutionRound,
    select_taste_evolution_round,
)


def _records(path: Path, model: type) -> tuple:
    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("["):
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError(f"{path} must contain a JSON array")
        return tuple(model.model_validate(item) for item in rows)
    return tuple(model.model_validate_json(line) for line in raw.splitlines() if line.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "requests", "private-keys", "parent", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path)
    arguments = parser.parse_args()
    plan = TasteEvolutionPlan.model_validate_json(arguments.plan.read_bytes())
    predecessor = (
        None
        if arguments.predecessor is None
        else TasteEvolutionRound.model_validate_json(arguments.predecessor.read_bytes())
    )
    result = select_taste_evolution_round(
        plan,
        _records(arguments.requests, DecisionMethodRequest),
        _records(arguments.private_keys, DecisionScoringKey),
        _records(arguments.parent, DecisionMethodSubmission),
        _records(arguments.candidate, DecisionMethodSubmission),
        predecessor=predecessor,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")
    print(
        f"{result.disposition}: active-development-policy="
        f"{result.active_development_policy_sha256} "
        f"task-mean-regret-reduction={result.mean_task_regret_reduction:.6f}"
    )


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import pytest

from scitaste.evaluation.counterfactual_abstraction import (
    build_counterfactual_taste_abstraction_input,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import load_interactive_research_prefix


def test_real_counterfactual_state_becomes_grounded_abstraction_input() -> None:
    root = Path(
        "outputs/projects/scitaste-self-development/evaluations/"
        "counterfactual-taste-formal-v4-coulomb-early"
    )
    if not root.exists():
        pytest.skip("project-owned formal output is not present in source-only CI")
    result = CounterfactualActionSetResult.model_validate_json(
        (root / "RESULT.json").read_bytes(), strict=True
    )
    prefix = load_interactive_research_prefix(root / "PREFIX.json")

    abstraction_input = build_counterfactual_taste_abstraction_input(result, prefix)
    projection = json.loads(abstraction_input.source_projection)

    assert abstraction_input.outcome_information_availability == "available"
    assert projection["fields"]["resource_aware_choice"]["value"] in {
        item.value for item in result.preferred_actions
    }
    assert len(json.loads(projection["fields"]["counterfactual_outcomes"]["value"])) == 7

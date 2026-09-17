from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationTarget,
    prepare_counterfactual_deliberation_inputs,
)
from scitaste.taste.deliberation import TasteDeliberationInput


def test_real_precedents_prepare_cross_task_outcome_hidden_inputs(tmp_path: Path) -> None:
    base = Path("outputs/projects/scitaste-self-development/evaluations")
    precedent_root = base / "counterfactual-taste-policy-v2-development-precedents-v1"
    if not precedent_root.exists():
        pytest.skip("project-owned development precedent bundle is absent in source-only CI")

    outputs = prepare_counterfactual_deliberation_inputs(
        project_id="scitaste-self-development",
        state_root=base,
        precedent_root=precedent_root,
        output_root=tmp_path / "deliberations",
    )

    assert len(outputs) == 12
    for output in outputs:
        input_data = TasteDeliberationInput.model_validate_json(
            (output / "INPUT.json").read_bytes(), strict=True
        )
        target = CounterfactualDeliberationTarget.model_validate_json(
            (output / "TARGET.json").read_bytes(), strict=True
        )
        serialized = json.dumps(input_data.model_dump(mode="json"))
        assert len(input_data.candidates) == 9
        assert not set(target.excluded_same_cluster_case_ids) & {
            item.case_id for item in input_data.candidates
        }
        assert "outcome_summary" not in serialized
        assert "objective_value" not in serialized
        assert target.selector_input_sha256 == input_data.fingerprint

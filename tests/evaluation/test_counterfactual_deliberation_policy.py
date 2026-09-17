from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationRetrievalRecord,
    CounterfactualDeliberationTarget,
    prepare_counterfactual_deliberation_inputs,
)
from scitaste.evaluation.counterfactual_temporal_precedents import (
    CounterfactualTemporalSafePrecedentAudit,
    derive_temporal_safe_counterfactual_precedents,
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
        maximum_candidate_cases=3,
    )

    assert len(outputs) == 12
    for output in outputs:
        input_data = TasteDeliberationInput.model_validate_json(
            (output / "INPUT.json").read_bytes(), strict=True
        )
        target = CounterfactualDeliberationTarget.model_validate_json(
            (output / "TARGET.json").read_bytes(), strict=True
        )
        retrieval = CounterfactualDeliberationRetrievalRecord.model_validate_json(
            (output / "RETRIEVAL.json").read_bytes(), strict=True
        )
        serialized = json.dumps(input_data.model_dump(mode="json"))
        assert len(input_data.candidates) == 3
        assert len(retrieval.population_scores) == 9
        assert retrieval.selected_case_ids == tuple(
            item.case_id for item in input_data.candidates
        )
        assert len({item.preferred_action for item in input_data.candidates}) == 3
        assert retrieval.selector_input_sha256 == input_data.fingerprint
        assert not set(target.excluded_same_cluster_case_ids) & {
            item.case_id for item in input_data.candidates
        }
        assert "outcome_summary" not in serialized
        assert "objective_value" not in serialized
        assert target.selector_input_sha256 == input_data.fingerprint


def test_real_precedents_can_be_rebuilt_from_predecision_observables(tmp_path: Path) -> None:
    base = Path("outputs/projects/scitaste-self-development/evaluations")
    precedent_root = base / "counterfactual-taste-policy-v2-development-precedents-v1"
    if not precedent_root.exists():
        pytest.skip("project-owned development precedent bundle is absent in source-only CI")
    safe_root = tmp_path / "temporal-safe"
    audit = derive_temporal_safe_counterfactual_precedents(
        audit_id="counterfactual-temporal-safe-test",
        manifest_id="counterfactual-temporal-safe-test",
        precedent_root=precedent_root,
        state_root=base,
        output_root=safe_root,
    )
    loaded = CounterfactualTemporalSafePrecedentAudit.model_validate_json(
        (safe_root / "TEMPORAL_SAFETY.json").read_bytes(), strict=True
    )

    assert loaded == audit
    assert len(audit.cases) == 12
    assert all(item.terminal_metrics_absent_from_selector_fields for item in audit.cases)

    outputs = prepare_counterfactual_deliberation_inputs(
        project_id="scitaste-self-development",
        state_root=base,
        precedent_root=safe_root,
        output_root=tmp_path / "safe-deliberations",
        maximum_candidate_cases=3,
    )
    inputs = [
        TasteDeliberationInput.model_validate_json(
            (output / "INPUT.json").read_bytes(), strict=True
        )
        for output in outputs
    ]
    serialized = json.dumps([item.model_dump(mode="json") for item in inputs])
    assert "objective_value" not in serialized
    assert "objective_observed" not in serialized
    assert "additional_tokens" not in serialized
    assert all(
        candidate.hard_applicability_satisfied is not None
        for item in inputs
        for candidate in item.candidates
    )

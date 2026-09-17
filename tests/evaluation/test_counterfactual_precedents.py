from __future__ import annotations

from pathlib import Path

import pytest

from scitaste.data.store import TasteLibrary
from scitaste.evaluation.counterfactual_precedents import (
    compile_counterfactual_taste_precedents,
)


def test_real_verified_counterfactual_ledgers_compile_once(tmp_path: Path) -> None:
    outputs = Path("outputs")
    state_root = outputs / "projects/scitaste-self-development/evaluations"
    input_root = state_root / "counterfactual-taste-policy-v2-development-abstractions-v2"
    run_id = (
        "2026-09-17__deepseek-v41-flash__"
        "counterfactual-taste-v2-abstraction-v3__seed-00"
    )
    ledger_root = (
        outputs
        / "projects/scitaste-self-development/runs"
        / run_id
        / "model_nodes/ledger"
    )
    if not ledger_root.exists():
        pytest.skip("project-owned verified model ledger is absent in source-only CI")

    target = tmp_path / "precedents"
    manifest = compile_counterfactual_taste_precedents(
        manifest_id="counterfactual-taste-v2-development-precedents-v1",
        project_id="scitaste-self-development",
        source_run_id=run_id,
        state_root=state_root,
        abstraction_input_root=input_root,
        ledger_root=ledger_root,
        evidence_root=outputs,
        output_root=target,
    )
    cases = TasteLibrary(target / "TASTE_LIBRARY.jsonl").all()

    assert len(manifest.bindings) == 12
    assert len(cases) == 12
    assert {item.preferred_action for item in cases} >= {"PILOT", "PIVOT", "STOP"}
    assert all(item.retrieval_eligible and not item.human_verified for item in cases)
    assert all(item.label_basis == "objective-counterfactual-development" for item in cases)
    assert manifest.same_task_cluster_exclusion_required is True
    assert manifest.confirmation_population_reuse_prohibited is True

    with pytest.raises(FileExistsError):
        compile_counterfactual_taste_precedents(
            manifest_id="counterfactual-taste-v2-development-precedents-v1",
            project_id="scitaste-self-development",
            source_run_id=run_id,
            state_root=state_root,
            abstraction_input_root=input_root,
            ledger_root=ledger_root,
            evidence_root=outputs,
            output_root=target,
        )

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

import pytest

from scitaste.cli import main
from scitaste.state.persistence import StateStore
from scitaste.state.research_state import FigureContract


def test_figure_contract_rejects_unknown_relation_entity() -> None:
    with pytest.raises(ValueError, match="unknown entity"):
        FigureContract.model_validate(
            {
                "figure_id": "fig-invalid",
                "purpose": "Explain a relation",
                "target_claim_ids": ["claim-1"],
                "intended_reader_takeaway": "A causes B",
                "required_entities": [{"entity_id": "a", "label": "A", "role": "input"}],
                "required_relations": [
                    {
                        "relation_id": "a-b",
                        "source_entity_id": "a",
                        "target_entity_id": "b",
                        "label": "causes",
                    }
                ],
                "panel_plan": [
                    {
                        "panel_id": "p1",
                        "title": "One",
                        "objective": "Show A",
                        "entity_ids": ["a"],
                    }
                ],
            }
        )


def test_text_to_editable_reviewed_and_patched_figure(tmp_path) -> None:
    output = tmp_path / "figure"

    assert main(["figure", "build", "--output", str(output), "--seed", "7"]) == 0

    summary = json.loads((output / "figure_summary.json").read_text())
    state = StateStore(output).load()
    assert summary["selected_actions"] == ["DESIGN_FIGURE"]
    assert summary["initial_blocking_findings"] == 2
    assert summary["patch_count"] == 1
    assert summary["patched_object_ids"] == ["executor"]
    assert summary["final_blocking_findings"] == 0
    assert state.figure_state is not None
    assert state.figure_state.status == "reviewed"
    assert state.figure_state.retrieved_taste_case_ids == ["taste-figure-mechanism"]
    assert state.figure_state.contract is not None
    assert state.figure_state.contract.target_claim_ids == ["claim-control-boundary"]
    assert len(state.figure_state.final_critic_report) == 10
    assert {item.category for item in state.figure_state.final_critic_report} == {
        "communication",
        "aesthetics",
    }

    svg = ET.parse(output / "figure.svg").getroot()
    assert svg.attrib["role"] == "img"
    drawio = ET.parse(output / "figure.drawio").getroot()
    assert drawio.attrib["compressed"] == "false"
    assert 'id="executor"' in (output / "figure.svg").read_text()
    assert 'data-emphasis="normal"' in (output / "figure.svg").read_text()


def test_figure_build_dry_run_does_not_write(tmp_path) -> None:
    output = tmp_path / "dry"
    assert main(["figure", "build", "--output", str(output), "--dry-run"]) == 0
    assert not output.exists()

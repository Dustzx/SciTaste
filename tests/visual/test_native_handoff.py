import json

import pytest

from scitaste.state.research_state import ResearchState, ScientificClaim
from scitaste.visual.native_handoff import digest, load_figure_delivery, prepare_native_figure


def test_bound_editable_figure_exports_and_rejects_changed_caption(tmp_path):
    pytest.importorskip("cairosvg")
    root = tmp_path / "project"
    run = root / "execution"
    report = run / "workspace/report"
    report.mkdir(parents=True)
    state = ResearchState(
        project_id="project",
        research_direction="illustrate a process",
        target_domain="science",
        claims=[
            ScientificClaim(
                claim_id="c",
                text="A process has input and output",
                claim_type="mechanism",
                strength="exploratory",
            )
        ],
    )
    state_path = run / "state.json"
    state_path.write_text(state.model_dump_json())
    contract = {
        "figure_id": "process",
        "purpose": "Explain a two-stage process",
        "target_claim_ids": ["c"],
        "intended_reader_takeaway": "Inputs precede outputs.",
        "required_entities": [
            {"entity_id": "input", "label": "Input", "role": "input"},
            {"entity_id": "output", "label": "Output", "role": "output"},
        ],
        "required_relations": [
            {
                "relation_id": "flow",
                "source_entity_id": "input",
                "target_entity_id": "output",
                "label": "transform",
            }
        ],
        "panel_plan": [
            {
                "panel_id": "p",
                "title": "Process",
                "objective": "Show order",
                "entity_ids": ["input", "output"],
            }
        ],
    }
    source = report / "figure_contract.json"
    source.write_text(json.dumps(contract))
    (run / "RESULT.json").write_text(
        json.dumps(
            {
                "research_state": "execution/state.json",
                "research_state_sha256": digest(state_path),
                "figure_contract_sha256": digest(source),
            }
        )
    )
    output = root / "figure"
    result = prepare_native_figure(root, run, output)
    assert (output / "figure.pdf").read_bytes().startswith(b"%PDF")
    assert (output / "figure.svg").is_file() and (output / "figure.drawio").is_file()
    assert result["scientific_approval"] is False
    assert result["target_claim_statuses"] == {"c": "unsupported"}
    assert prepare_native_figure(root, run, output) == result
    result["caption"] = "Fabricated improvement"
    (output / "RESULT.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="caption"):
        load_figure_delivery(root, output / "RESULT.json", execution=run)

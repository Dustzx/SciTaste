import hashlib
import json

import pytest

from scitaste.executor.native_proposal_context import (
    proposal_experience_projection,
    proposal_scientific_context,
    retain_proposal_prompt,
)
from scitaste.state.research_state import ResearchObservation, ResearchState


def test_only_exact_duplicate_evidence_becomes_a_reference(tmp_path):
    observations = ["measured loss = 1.25; no confirmation yet"]
    statement = json.dumps(
        {"tool": "Bash", "status": "SUCCEEDED", "observations": observations, "primary_value": None}
    )
    state = ResearchState(
        project_id="context-test",
        target_domain="autonomous research",
        research_direction="complete task",
        observations=[
            ResearchObservation(observation_id="o1", statement=statement, source_result_id="r1"),
            ResearchObservation(
                observation_id="o2",
                statement="An independent interpretation",
                source_result_id="r1",
            ),
        ],
    )
    history = [
        {
            "selected": {"parameters": {"tool": "Bash"}},
            "result": {
                "result_id": "r1",
                "status": "SUCCEEDED",
                "observations": observations,
                "data": {},
            },
        }
    ]
    context = proposal_scientific_context(state, history, task="complete task")
    reference = json.loads(context["observations"][0]["statement"])
    assert reference["original_statement_sha256"] == hashlib.sha256(statement.encode()).hexdigest()
    assert context["observations"][1]["statement"] == "An independent interpretation"
    assert state.observations[0].statement == statement
    assert history[0]["result"]["observations"] == observations
    assert context["research_direction"]["identical_text_not_repeated"]
    partial = proposal_scientific_context(
        state,
        history,
        task="complete task",
        observed_history=[{"result_id": "r1", "observations": ["excerpt only"]}],
    )
    assert partial["observations"][0]["statement"] == statement

    original = retain_proposal_prompt(
        tmp_path, "proposal-4", prompt="time remaining 60", scientific_binding=context
    )
    assert (
        retain_proposal_prompt(
            tmp_path, "proposal-4", prompt="time remaining 30", scientific_binding=context
        )
        == original
    )
    with pytest.raises(ValueError, match="scientific inputs changed"):
        retain_proposal_prompt(
            tmp_path,
            "proposal-4",
            prompt="time remaining 30",
            scientific_binding={"different": True},
        )
    retained = tmp_path / "proposal-4.prompt.json"
    value = json.loads(retained.read_text())
    value["prompt"] = "tampered"
    retained.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="prompt changed"):
        retain_proposal_prompt(
            tmp_path, "proposal-4", prompt="time remaining 30", scientific_binding=context
        )


def test_offered_experience_is_not_selection_or_adoption(tmp_path):
    precedent = {
        "version": "reviewed-conditional-v1",
        "cases": [{"case_id": "case-one", "source_lineage_sha256": "a" * 64}],
    }
    retain_proposal_prompt(
        tmp_path,
        "proposal-0",
        prompt="actual bound prompt",
        scientific_binding={"precedent": precedent},
    )
    value = json.loads((tmp_path / "proposal-0.prompt.json").read_text())["experience_projection"]
    assert value["offered_case_ids"] == ["case-one"]
    assert value["offered_source_lineages"] == ["a" * 64]
    assert (
        value["context_sha256"]
        == hashlib.sha256(json.dumps(precedent, ensure_ascii=False).encode()).hexdigest()
    )
    assert not value["model_consumption_or_use_established"]
    assert not value["scientific_effect_established"]
    off = proposal_experience_projection(None)
    assert off["context_version"] == "disabled" and off["context_utf8_bytes"] == 0

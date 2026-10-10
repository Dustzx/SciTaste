"""Unknown unexecuted metadata should reach the existing bounded correction route."""

from types import SimpleNamespace

import pytest

from scitaste.evidence.research_reasoning import (
    ResearchReasoningUpdateRejected,
    validate_action_probe_references,
)


def test_declared_probe_and_operational_omission_are_admitted():
    state = SimpleNamespace(
        executor_context={"research_reasoning": {"frame": {"probes": [{"probe_id": "active"}]}}}
    )
    validate_action_probe_references(
        state,
        [SimpleNamespace(scientific_probe_id="active"), SimpleNamespace(scientific_probe_id=None)],
    )


def test_unknown_probe_uses_reasoning_rejection_before_any_execution():
    state = SimpleNamespace(
        executor_context={"research_reasoning": {"frame": {"probes": [{"probe_id": "active"}]}}}
    )
    with pytest.raises(ResearchReasoningUpdateRejected, match="unknown scientific probe"):
        validate_action_probe_references(state, [SimpleNamespace(scientific_probe_id="invented")])


def test_missing_frame_is_not_implicit_scientific_authority():
    state = SimpleNamespace(executor_context={})
    validate_action_probe_references(state, [SimpleNamespace(scientific_probe_id=None)])
    with pytest.raises(ResearchReasoningUpdateRejected):
        validate_action_probe_references(state, [SimpleNamespace(scientific_probe_id="invented")])

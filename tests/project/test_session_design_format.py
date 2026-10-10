"""Format repair must retain authority and scientific identity, not improve a grade."""

from scitaste.project.session_design_format import binding_shape


def test_format_shape_allows_prose_but_not_anchors_ids_or_authority():
    original = {
        "hypothesis_id": "H1",
        "prediction": "A carefully qualified prediction.",
        "evidence": [{"source_id": "observed-1", "quote": "actual observation"}],
        "execution_authorized": False,
        "task_selection": None,
        "probe": {"next_action": "stop", "horizon": 2},
    }
    compressed = {**original, "prediction": "Qualified prediction."}
    assert binding_shape(original) == binding_shape(compressed)
    for changed in (
        {**original, "hypothesis_id": "H2"},
        {**original, "execution_authorized": True},
        {**original, "evidence": [{"source_id": "observed-1", "quote": "better result"}]},
        {**original, "probe": {"next_action": "discriminate", "horizon": 2}},
    ):
        assert binding_shape(original) != binding_shape(changed)

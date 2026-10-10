import hashlib

import pytest

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.source_reference import RAW_PROPOSAL_CONTEXT, load_source_reference


def test_bound_verbatim_source_cannot_be_replaced_by_a_lesson(tmp_path):
    text = tmp_path / "original.txt"
    text.write_text("Original conditional statement, not evidence from this task.")

    def binding(path):
        return {"locator": path.name, "sha256": digest(path)}

    quote = "Original conditional statement"
    packet = tmp_path / "packet.json"
    value = {
        "version": RAW_PROPOSAL_CONTEXT,
        "execution_authorized": False,
        "sources": [
            {
                "text": binding(text),
                "passages": [
                    {
                        "quote": quote,
                        "sha256": hashlib.sha256(quote.encode()).hexdigest(),
                    }
                ],
            }
        ],
    }
    retain_json(packet, value)
    campaign = tmp_path / "campaign.json"
    retain_json(campaign, {"raw_reference_context": binding(packet)})
    plan = {"campaign": binding(campaign)}
    assert load_source_reference(tmp_path, plan) == value
    text.write_text("Later source cannot retroactively replace the original")
    with pytest.raises(ValueError, match="Bound benchmark input changed"):
        load_source_reference(tmp_path, plan)

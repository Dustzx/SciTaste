"""Freeze model inputs across known pre-tool waits, not tool execution crashes."""

import json

from scitaste.model_nodes.session_exchange import retain_json
from scitaste.model_nodes.tool_intelligence import canonical_sha256
from scitaste.schema.actions import ResearchAction
from scitaste.state.persistence import snapshot_id


def retain_turn(path, *, state, history, interface, proposals=None, proposal_record=None):
    record = {
        "state_snapshot_id": snapshot_id(state),
        "history_sha256": canonical_sha256(history),
        "tool_interface_sha256": interface,
        "state": state.model_dump(mode="json"),
        "proposal_record": proposal_record,
        "proposals": (
            [action.model_dump(mode="json") for action in proposals]
            if proposals is not None
            else None
        ),
        "execution_authorized": False,
        "live_deadline_rechecked_by_executor": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    retain_json(path, record)


def load_turn(path, *, state, history, interface):
    record = json.loads(path.read_text())
    if (
        record["state_snapshot_id"] != snapshot_id(state)
        or record["state"] != state.model_dump(mode="json")
        or record["history_sha256"] != canonical_sha256(history)
        or record["tool_interface_sha256"] != interface
        or record["execution_authorized"] is not False
        or record["live_deadline_rechecked_by_executor"] is not True
    ):
        raise ValueError("Prepared research turn differs from its exact pre-tool checkpoint")
    proposals = record["proposals"]
    return (
        tuple(ResearchAction.model_validate(action) for action in proposals)
        if proposals is not None
        else None,
        record["proposal_record"],
    )

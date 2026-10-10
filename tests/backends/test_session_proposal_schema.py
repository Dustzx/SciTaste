"""The session packet must agree with the configured controller parser."""

from pathlib import Path
from types import SimpleNamespace

from scitaste.backends.session import SessionNativeBridge
from scitaste.research_tool_loop import ResearchToolProposal, ResearchToolProposalBatch


def test_single_and_batch_session_proposal_schema():
    proposal = {"tool": "List Files", "arguments": {}, "rationale": "Inspect candidate files."}
    alternative = {
        "tool": "Read File",
        "arguments": {"file_name": "model.py"},
        "rationale": "Inspect the baseline implementation.",
    }
    for count, model, payload in (
        (1, ResearchToolProposal, proposal),
        (2, ResearchToolProposalBatch, {"proposals": [proposal, alternative]}),
    ):
        requests = []

        def complete(request, requests=requests, payload=payload):
            requests.append(request)
            return SimpleNamespace(output_payload=payload)

        backend = SimpleNamespace(
            name="assistant-session", model="session-authored", complete=complete
        )
        raw = SessionNativeBridge(backend, proposal_count=count).complete_text(
            "Supplied tool contract", Path("proposal-0.log"), "session-authored"
        )
        assert requests[0].output_schema == model.model_json_schema()
        assert model.model_validate_json(raw).model_dump(exclude_unset=True) == payload

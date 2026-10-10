import json

import pytest

from scitaste.executor.implementation_review_tool import install_implementation_review
from scitaste.executor.research_tools import ResearchToolEnvironment, ToolAction
from scitaste.model_nodes.backends import ScriptedStructuredBackend, ScriptedStructuredReply
from scitaste.research_tool_loop import ResearchToolProposal


def test_optional_review_returns_advice_without_edit_or_experiment(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    source = workspace / "model.py"
    source.write_text("value = 1\n")
    environment = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Study an update",
        experiment=lambda _: pytest.fail("review cannot run an experiment"),
    )
    proposal = ResearchToolProposal(
        tool="Review Implementation",
        arguments={"file_name": "model.py", "proposed_method": "update"},
        rationale="Uncertain implementation",
    )
    with pytest.raises(ValueError, match="not enabled"):
        proposal.action(environment, 0)

    class Backend(ScriptedStructuredBackend):
        def complete(self, request):
            self.replies[request.request_id] = ScriptedStructuredReply(
                output_payload={
                    "threats": [],
                    "alternative_explanations": [],
                    "recommended_action_type": None,
                    "rationale": "Fixture only",
                    "confidence": 0.5,
                }
            )
            return super().complete(request)

    backend = Backend(name="fixture", model="fixture", replies={})
    install_implementation_review(
        environment,
        backend=backend,
        project_id="fixture",
        budget_usd=1,
        spent=lambda: 0,
    )
    assert proposal.action(environment, 0).type.value == "REVIEW"
    observation = json.loads(environment.execute(ToolAction(proposal.tool, proposal.arguments)))
    assert observation["advisory_only"] is True
    assert observation["result"]["status"] == "accepted"
    assert source.read_text() == "value = 1\n"
    assert not (environment.log_root / "EXPERIMENT_RESERVED.json").exists()
    environment.execute(
        ToolAction("Write File", {"file_name": "model.py", "content": "value = 2\n"})
    )
    assert source.read_text() == "value = 2\n"
    assert len(backend.calls) == 1

import pytest

from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.research_tool_handler import ResearchToolActionHandler
from scitaste.executor.research_tools import ResearchToolEnvironment
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def test_native_uses_shared_tools_without_upstream_or_model(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "model.py").write_text("x = 1\n")
    environment = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="inspect candidate",
        experiment=lambda _: pytest.fail("no experiment selected"),
    )
    handler = ResearchToolActionHandler(project_id="p", environment=environment)
    native = SciTasteNativeExecutor(
        handlers=handler.native_handlers, workspace=tmp_path / "native", artifact_root=tmp_path
    )
    state = ResearchState(project_id="p", research_direction="inspect", target_domain="general")
    action = ResearchAction(
        type=MetaAction.SEARCH,
        description="read candidate",
        parameters={
            "tool": "Read File",
            "arguments": {"file_name": "model.py"},
            "tool_interface_sha256": environment.interface_fingerprint,
        },
    )
    result = native.execute(state, action)
    assert result.observations == ["x = 1\n"]
    assert "execution_record" in result.data
    bad = action.model_copy(
        update={"parameters": {**action.parameters, "tool_interface_sha256": "bad"}}
    )
    with pytest.raises(ValueError, match="interface changed"):
        native.execute(state, bad)

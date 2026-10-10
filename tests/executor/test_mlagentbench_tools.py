"""One no-call pass through the actual pinned upstream agent when acquired."""

import argparse
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge
from scitaste.executor.mlagentbench_tools import MLAgentBenchToolEnvironment


def test_actual_upstream_agent_uses_restricted_tools(tmp_path, monkeypatch):
    checkout = Path(
        "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
        "mlrc-bench-source-v1/checkout"
    )
    if not checkout.exists():
        pytest.skip("optional pinned upstream checkout not acquired")
    pytest.importorskip("anthropic")
    monkeypatch.syspath_prepend(str(checkout))
    module = importlib.import_module("MLAgentBench.agents.agent_research")
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "model.py").write_text("x = 1\n")
    monkeypatch.setenv("UPSTREAM_TEST_KEY", "test-secret")
    completions = iter(
        [
            ("Read File", '{"file_name": "model.py"}'),
            (
                "Final Answer",
                '{"final_solution": "Inspected source; no measurement", "best_score": null}',
            ),
        ]
    )

    class Transport:
        def post(self, url, **kwargs):
            name, arguments = next(completions)
            content = (
                "Reflection: Inspect source.\nResearch Plan and Status: Inspect then stop.\n"
                "Fact Check: No measurements claimed.\nThought: Follow plan.\n"
                f"Action: {name}\nAction Input: {arguments}\n"
            )
            return {
                "model": "fixture",
                "usage": {"prompt_tokens": 20, "completion_tokens": 30},
                "choices": [{"message": {"content": content}}],
            }

    bridge = MLAgentBenchProviderBridge(
        config=SimpleNamespace(
            model="fixture",
            api_key_env="UPSTREAM_TEST_KEY",
            base_url="https://example.invalid",
            extra_body={},
        ),
        log_root=tmp_path / "logs",
        transport=Transport(),
    )
    # Restore module globals after the test, including upstream imported references.
    import sys

    for name, loaded in list(sys.modules.items()):
        if name.startswith("MLAgentBench.") and loaded is not None:
            for attribute in ("complete_text", "complete_text_fast"):
                if hasattr(loaded, attribute):
                    monkeypatch.setattr(loaded, attribute, getattr(loaded, attribute))
    bridge.install()
    env = MLAgentBenchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Inspect source then stop.",
        experiment=lambda _: pytest.fail("fixture must not run a GPU experiment"),
    )
    args = argparse.Namespace(
        log_dir=str(tmp_path / "logs"),
        valid_format_entires=None,
        actions_remove_from_prompt=[],
        actions_add_to_prompt=["Read File", "Write File"],
        edit_script_llm_name="fixture",
        edit_script_llm_max_tokens=4096,
        resume=None,
        max_steps_in_context=12,
        max_observation_steps_in_context=12,
        retrieval=False,
        agent_max_steps=3,
        max_retries=1,
        llm_name="fixture",
    )
    agent = module.ResearchAgent(args, env)
    agent.run(env)
    assert env.is_final()
    assert len(env.trace.steps) == 2
    assert env.trace.steps[0].observation == "x = 1\n"
    with pytest.raises(ValueError):
        env.read_file("../credentials.env")

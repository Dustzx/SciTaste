from __future__ import annotations

import sys
from types import ModuleType

import pytest

from scitaste.executor.arc_bootstrap import main


def test_bootstrap_clamps_upstream_output_tokens(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeLLMClient:
        def chat(self, *args, **kwargs):
            seen["max_tokens"] = kwargs.get("max_tokens")
            return "ok"

    def upstream_main(argv):
        seen["argv"] = argv
        FakeLLMClient().chat([], max_tokens=999)
        return 7

    researchclaw = ModuleType("researchclaw")
    llm = ModuleType("researchclaw.llm")
    client = ModuleType("researchclaw.llm.client")
    client.LLMClient = FakeLLMClient
    cli = ModuleType("researchclaw.cli")
    cli.main = upstream_main
    monkeypatch.setitem(sys.modules, "researchclaw", researchclaw)
    monkeypatch.setitem(sys.modules, "researchclaw.llm", llm)
    monkeypatch.setitem(sys.modules, "researchclaw.llm.client", client)
    monkeypatch.setitem(sys.modules, "researchclaw.cli", cli)
    monkeypatch.setenv("SCITASTE_ARC_MAX_OUTPUT_TOKENS", "64")

    assert main(["run", "--topic", "test"]) == 7
    assert seen == {"argv": ["run", "--topic", "test"], "max_tokens": 64}


def test_bootstrap_preserves_upstream_defaults_without_limit(monkeypatch) -> None:
    cli = ModuleType("researchclaw.cli")
    cli.main = lambda argv: 3
    monkeypatch.setitem(sys.modules, "researchclaw", ModuleType("researchclaw"))
    monkeypatch.setitem(sys.modules, "researchclaw.cli", cli)
    monkeypatch.delenv("SCITASTE_ARC_MAX_OUTPUT_TOKENS", raising=False)

    assert main(None) == 3


def test_bootstrap_stops_after_exact_total_token_overrun(monkeypatch) -> None:
    class Response:
        total_tokens = 1001
        prompt_tokens = 50
        completion_tokens = 51
        model = "test"

    class FakeLLMClient:
        def chat(self, *args, **kwargs):
            return Response()

    def upstream_main(argv):
        FakeLLMClient().chat([{"role": "user", "content": "x"}], max_tokens=1)
        return 0

    researchclaw = ModuleType("researchclaw")
    llm = ModuleType("researchclaw.llm")
    client = ModuleType("researchclaw.llm.client")
    client.LLMClient = FakeLLMClient
    cli = ModuleType("researchclaw.cli")
    cli.main = upstream_main
    monkeypatch.setitem(sys.modules, "researchclaw", researchclaw)
    monkeypatch.setitem(sys.modules, "researchclaw.llm", llm)
    monkeypatch.setitem(sys.modules, "researchclaw.llm.client", client)
    monkeypatch.setitem(sys.modules, "researchclaw.cli", cli)
    monkeypatch.setenv("SCITASTE_ARC_MAX_TOTAL_TOKENS", "1000")

    with pytest.raises(RuntimeError, match="budget exceeded"):
        main(["run"])

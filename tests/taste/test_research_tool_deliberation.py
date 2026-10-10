import json
from types import SimpleNamespace

from scitaste.taste.research_tool_deliberation import DeliberativeResearchToolController


def test_missing_grounded_pool_uses_intrinsic_not_raw_retrieval(tmp_path, monkeypatch):
    import scitaste.taste.research_tool_deliberation as module

    monkeypatch.setattr(module, "ModelNodeRuntime", lambda *a, **k: None)
    monkeypatch.setattr(module, "ModelNodeFacade", lambda *a, **k: None)
    sentinel = object()

    class Base:
        def decide(self, **kwargs):
            return sentinel

    class Augmented:
        def prepare_taste_deliberation(self, **kwargs):
            raise ValueError("No grounded transfer pool")

        def decide(self, **kwargs):
            raise AssertionError("Raw retrieval fallback must not be used")

    controller = DeliberativeResearchToolController(
        base=Base(),
        augmented=Augmented(),
        runtime=None,
        run_id="fixture",
        backend=None,
        profile=None,
        output=tmp_path / "decisions",
    )
    actions = [
        SimpleNamespace(
            parameters={"tool": "Run Experiment"},
            model_dump=lambda **kw: {"tool": "Run Experiment"},
        ),
        SimpleNamespace(
            parameters={"tool": "Final Answer"}, model_dump=lambda **kw: {"tool": "Final Answer"}
        ),
    ]
    assert (
        controller.decide(
            state=SimpleNamespace(decision_history=[], model_dump=lambda **kw: {}),
            candidate_actions=actions,
        )
        is sentinel
    )
    record = json.loads((tmp_path / "decisions/000.json").read_text())
    assert record["intrinsic_fallback"] is True
    assert record["reason"] == "no-valid-grounded-transfer-pool"


def test_native_inspection_does_not_invoke_deliberation(tmp_path, monkeypatch):
    import scitaste.taste.research_tool_deliberation as module

    monkeypatch.setattr(module, "ModelNodeRuntime", lambda *a, **k: None)
    monkeypatch.setattr(module, "ModelNodeFacade", lambda *a, **k: None)
    controller = DeliberativeResearchToolController(
        base=SimpleNamespace(decide=lambda **kwargs: "intrinsic"),
        augmented=None,
        runtime=None,
        run_id="inspection",
        backend=None,
        profile=None,
        output=tmp_path / "decisions",
    )
    actions = [
        SimpleNamespace(
            parameters={"tool": tool}, model_dump=lambda tool=tool, **kw: {"tool": tool}
        )
        for tool in ("Read", "Glob", "Grep", "Final Answer")
    ]
    assert (
        controller.decide(
            state=SimpleNamespace(decision_history=[], model_dump=lambda **kw: {}),
            candidate_actions=actions,
        )
        == "intrinsic"
    )
    record = json.loads((tmp_path / "decisions/000.json").read_text())
    assert record["reason"] == "inspection-or-report-only"
    assert module.workspace_taste_binding(None, None) == (None, None)


def test_generation_only_keeps_retriever_but_never_deliberates(tmp_path, monkeypatch):
    import scitaste.taste.research_tool_deliberation as module

    monkeypatch.setattr(module, "ModelNodeRuntime", lambda *a, **k: None)
    monkeypatch.setattr(module, "ModelNodeFacade", lambda *a, **k: None)

    def forbidden(**kwargs):
        raise AssertionError("Generation-only arm must not call Taste selection or maintenance")

    retriever = object()
    controller = DeliberativeResearchToolController(
        base=SimpleNamespace(decide=lambda **kwargs: "intrinsic"),
        augmented=SimpleNamespace(
            retriever=retriever, prepare_taste_deliberation=forbidden, decide=forbidden
        ),
        runtime=None,
        run_id="generation-only",
        backend=SimpleNamespace(session_enabled=True),
        profile=None,
        output=tmp_path / "decisions",
        selection_enabled=False,
        maintenance=SimpleNamespace(observe=forbidden),
    )
    state = SimpleNamespace(decision_history=[], model_dump=lambda **kwargs: {"revision": 0})
    actions = [
        SimpleNamespace(
            parameters={"tool": "Run Experiment"},
            model_dump=lambda **kwargs: {"tool": "Run Experiment"},
        )
    ]
    for _ in range(2):
        assert controller.decide(state=state, candidate_actions=actions) == "intrinsic"
    assert controller.augmented.retriever is retriever
    record = json.loads((tmp_path / "decisions/000.json").read_text())
    assert record["reason"] == "taste-action-selection-disabled"
    assert record["intrinsic_selection"] and not record["intrinsic_fallback"]
    assert record["runtime_receipt"] is None

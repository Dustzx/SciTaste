from __future__ import annotations

import json

import pytest

from scitaste.data.models import KnowledgeDocument, ProvenanceRecord
from scitaste.data.store import KnowledgeLibrary
from scitaste.executor import (
    ExecutionResult,
    ExecutionStatus,
    NativeExecutionRecord,
    ResearchExecutor,
    SciTasteNativeExecutor,
    build_builtin_executor,
    require_execution_success,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def _state() -> ResearchState:
    return ResearchState(
        project_id="native-executor-test",
        research_direction="Exercise the first-party execution boundary",
        target_domain="autonomous-research",
    )


def test_native_executor_is_protocol_compatible_and_does_not_invent_observations() -> None:
    executor = SciTasteNativeExecutor()
    action = ResearchAction(
        action_id="native-control",
        type=MetaAction.FORMULATE_PROBLEM,
        description="Form a bounded problem from existing evidence",
    )

    result = executor.execute(_state(), action)

    assert isinstance(executor, ResearchExecutor)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.executor == "scitaste-native"
    assert result.observations == []
    assert result.data["capability"] == "control"
    assert result.data["result_basis"] == "workflow-component-receipt"


def test_native_executor_preserves_scenario_bound_observation_and_cost_basis() -> None:
    executor = SciTasteNativeExecutor()
    action = ResearchAction(
        action_id="native-probe",
        type=MetaAction.PROBE,
        description="Run a bounded diagnostic probe",
        parameters={"observation": "The effect persists under the matched control."},
        expected_cost={"wall_time_hours": 0.25},
    )

    result = executor.probe(_state(), action)

    assert result.observations == ["The effect persists under the matched control."]
    assert result.cost == {"wall_time_hours": 0.25}
    assert result.data["capability"] == "probing"
    assert result.data["cost_basis"] == "action-declared"


def test_native_executor_rejects_invalid_observation_without_advancing_authority() -> None:
    result = SciTasteNativeExecutor().execute(
        _state(),
        ResearchAction(
            action_id="invalid-native-probe",
            type=MetaAction.PROBE,
            description="Reject malformed action input",
            parameters={"observation": ""},
        ),
    )

    assert result.status == ExecutionStatus.FAILED
    with pytest.raises(RuntimeError, match="invalid-native-probe"):
        require_execution_success(result)


def test_native_handler_must_return_the_selected_action_identity() -> None:
    def mismatched(_state: ResearchState, _action: ResearchAction) -> ExecutionResult:
        return ExecutionResult(
            action_id="different-action",
            status=ExecutionStatus.SUCCEEDED,
            executor="fixture",
        )

    executor = SciTasteNativeExecutor(handlers={MetaAction.ANALYZE: mismatched})
    with pytest.raises(ValueError, match="does not match"):
        executor.analyze(
            _state(),
            ResearchAction(
                action_id="selected-analysis",
                type=MetaAction.ANALYZE,
                description="Analyze selected evidence",
            ),
        )


def test_builtin_executor_factory_keeps_mock_explicit() -> None:
    assert isinstance(build_builtin_executor("scitaste-native"), SciTasteNativeExecutor)
    assert build_builtin_executor("mock", seed=7).__class__.__name__ == "MockExecutor"
    with pytest.raises(ValueError, match="unsupported built-in executor"):
        build_builtin_executor("autoresearchclaw")


def test_native_knowledge_search_writes_content_bound_project_evidence(tmp_path) -> None:
    root = tmp_path / "run"
    knowledge = KnowledgeLibrary(root / "context/knowledge.jsonl")
    knowledge.add(
        KnowledgeDocument(
            document_id="knowledge-contradiction",
            title="Stable contradictory evidence",
            content="Stable contradictions should trigger a research pivot.",
            domain_tags=["autonomous-research"],
            provenance=[ProvenanceRecord(source_type="test", locator="fixture://knowledge")],
        )
    )
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        knowledge_library=knowledge,
    )
    action = ResearchAction(
        action_id="search-knowledge",
        type=MetaAction.SEARCH,
        description="Retrieve evidence about research pivots",
        parameters={
            "query": "contradictory evidence pivot",
            "domain_tags": ["autonomous-research"],
            "limit": 3,
        },
    )

    result = executor.search(_state(), action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["result_basis"] == "knowledge-library-retrieval"
    assert result.data["retrieved_document_ids"] == ["knowledge-contradiction"]
    assert result.data["cost_basis"] == "measured-wall-time"
    assert len(result.artifacts) == 1
    retrieval = json.loads((root / result.artifacts[0]).read_text(encoding="utf-8"))
    assert retrieval["query"] == "contradictory evidence pivot"
    assert retrieval["results"][0]["document"]["document_id"] == "knowledge-contradiction"
    record_path = root / result.data["execution_record"]
    record = NativeExecutionRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    assert record.result.result_id == result.result_id
    assert list(record.input_sha256) == ["context/knowledge.jsonl"]
    assert len(record.input_sha256["context/knowledge.jsonl"]) == 64
    assert list(record.artifact_sha256) == result.artifacts
    assert len(record.artifact_sha256[result.artifacts[0]]) == 64
    verification = executor.store.verify()  # type: ignore[union-attr]
    assert verification.record_count == 1
    assert verification.head_record_sha256 == record.record_sha256


def test_native_execution_store_detects_output_or_input_tampering(tmp_path) -> None:
    root = tmp_path / "run"
    knowledge = KnowledgeLibrary(root / "context/knowledge.jsonl")
    knowledge.add(
        KnowledgeDocument(
            document_id="knowledge-probe",
            title="Diagnostic probe",
            content="A cheap diagnostic probe reduces uncertainty.",
            provenance=[ProvenanceRecord(source_type="test", locator="fixture://probe")],
        )
    )
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        knowledge_library=knowledge,
    )
    result = executor.search(
        _state(),
        ResearchAction(
            action_id="tamper-search",
            type=MetaAction.SEARCH,
            description="Retrieve diagnostic probe evidence",
            parameters={"query": "diagnostic probe", "domain_tags": [], "limit": 1},
        ),
    )
    (root / result.artifacts[0]).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        executor.store.verify()  # type: ignore[union-attr]

    record = next((root / "native_execution/records").glob("*.json"))
    record.unlink()
    (root / result.artifacts[0]).unlink()
    knowledge.path.write_text("", encoding="utf-8")
    second = SciTasteNativeExecutor(
        workspace=root / "native_execution-second",
        artifact_root=root,
        knowledge_library=knowledge,
    )
    empty_result = second.search(
        _state(),
        ResearchAction(
            action_id="input-tamper-search",
            type=MetaAction.SEARCH,
            description="Record an empty search",
            parameters={"query": "nothing", "domain_tags": [], "limit": 1},
        ),
    )
    assert empty_result.status == ExecutionStatus.SUCCEEDED
    knowledge.path.write_text('{"invalid": true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        second.store.verify()  # type: ignore[union-attr]


def test_native_knowledge_search_rejects_invalid_bounds_and_records_failure(tmp_path) -> None:
    root = tmp_path / "run"
    knowledge = KnowledgeLibrary(root / "knowledge.jsonl")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        knowledge_library=knowledge,
    )

    result = executor.execute(
        _state(),
        ResearchAction(
            action_id="invalid-search-limit",
            type=MetaAction.SEARCH,
            description="Reject an unbounded request",
            parameters={"query": "evidence", "domain_tags": [], "limit": 1000},
        ),
    )

    assert result.status == ExecutionStatus.FAILED
    assert result.data["execution_sequence"] == 1
    assert result.data["execution_record_sha256"]
    assert executor.store.verify().record_count == 1  # type: ignore[union-attr]


def test_native_knowledge_recovery_reuses_the_exact_successful_retrieval(tmp_path) -> None:
    root = tmp_path / "run"
    knowledge = KnowledgeLibrary(root / "knowledge.jsonl")
    knowledge.add(
        KnowledgeDocument(
            document_id="knowledge-recovery",
            title="Interruption-safe retrieval",
            content="An exact successful retrieval can be reused during explicit recovery.",
            provenance=[ProvenanceRecord(source_type="test", locator="fixture://recovery")],
        )
    )
    action = ResearchAction(
        action_id="recover-search",
        type=MetaAction.SEARCH,
        description="Retrieve interruption-safe evidence",
        parameters={"query": "interruption safe retrieval", "domain_tags": [], "limit": 1},
    )
    first_executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        knowledge_library=knowledge,
    )
    first = first_executor.execute(_state(), action)
    recovering_executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        knowledge_library=knowledge,
        recover_completed_retrieval=True,
    )

    recovered = recovering_executor.execute(_state(), action)

    assert recovered == first
    assert recovering_executor.store.verify().record_count == 1  # type: ignore[union-attr]

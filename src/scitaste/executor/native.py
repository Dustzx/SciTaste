"""First-party execution boundary for SciTaste-owned workflow components."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from scitaste.data.retrieval import KnowledgeRetriever
from scitaste.data.store import KnowledgeLibrary
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.native_sandbox import NativeExperimentRunner
from scitaste.executor.native_store import NativeExecutionStore
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState

NativeHandler = Callable[[ResearchState, ResearchAction], ExecutionResult]


class NativeCapability(StrEnum):
    """Auditable capability families implemented by the first-party executor."""

    RETRIEVAL = "retrieval"
    PROBING = "probing"
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    WRITING = "writing"
    FIGURE = "figure"
    CONTROL = "control"


_CAPABILITIES: dict[MetaAction, NativeCapability] = {
    MetaAction.SEARCH: NativeCapability.RETRIEVAL,
    MetaAction.PROBE: NativeCapability.PROBING,
    MetaAction.RE_PROBE: NativeCapability.PROBING,
    MetaAction.PILOT: NativeCapability.EXPERIMENT,
    MetaAction.EXPERIMENT: NativeCapability.EXPERIMENT,
    MetaAction.COLLECT_EVIDENCE: NativeCapability.EXPERIMENT,
    MetaAction.REPRODUCE: NativeCapability.EXPERIMENT,
    MetaAction.ADD_EXPERIMENT: NativeCapability.EXPERIMENT,
    MetaAction.ADD_BASELINE: NativeCapability.EXPERIMENT,
    MetaAction.ANALYZE: NativeCapability.ANALYSIS,
    MetaAction.ADD_ANALYSIS: NativeCapability.ANALYSIS,
    MetaAction.WRITE: NativeCapability.WRITING,
    MetaAction.BUILD_STORY: NativeCapability.WRITING,
    MetaAction.RESPOND: NativeCapability.WRITING,
    MetaAction.CLARIFY_EXISTING_TEXT: NativeCapability.WRITING,
    MetaAction.CITE_EXISTING_EVIDENCE: NativeCapability.WRITING,
    MetaAction.ACKNOWLEDGE_LIMITATION: NativeCapability.WRITING,
    MetaAction.CORRECT_ERROR: NativeCapability.WRITING,
    MetaAction.REJECT_CONCERN_WITH_EVIDENCE: NativeCapability.WRITING,
    MetaAction.DEFER_FUTURE_WORK: NativeCapability.WRITING,
    MetaAction.DESIGN_FIGURE: NativeCapability.FIGURE,
}


class SciTasteNativeExecutor:
    """Dispatch selected actions to SciTaste-owned in-process capabilities.

    The Phase 4--7 workflow components currently perform their bounded domain
    operation immediately around this execution boundary. This executor emits a
    truthful receipt for that first-party operation and never fabricates a mock
    observation. Action-specific handlers can replace a capability incrementally
    as open-ended retrieval, sandbox, and generation implementations are added.
    """

    name = "scitaste-native"

    def __init__(
        self,
        *,
        handlers: dict[MetaAction, NativeHandler] | None = None,
        workspace: str | Path | None = None,
        artifact_root: str | Path | None = None,
        knowledge_library: KnowledgeLibrary | None = None,
        experiment_runner: NativeExperimentRunner | None = None,
        recover_completed_retrieval: bool = False,
        recover_completed_experiment: bool = False,
    ) -> None:
        self.handlers = handlers or {}
        if workspace is None and artifact_root is not None:
            raise ValueError("native artifact_root requires a workspace")
        if workspace is not None and artifact_root is None:
            raise ValueError("native workspace requires an artifact_root")
        self.store = (
            NativeExecutionStore(workspace, artifact_root=artifact_root)
            if workspace is not None and artifact_root is not None
            else None
        )
        self.knowledge_library = knowledge_library
        self.recover_completed_retrieval = recover_completed_retrieval
        self.recover_completed_experiment = recover_completed_experiment
        if experiment_runner is not None and self.store is None:
            raise ValueError("native experiment runner requires a project-owned workspace")
        self.experiment_runner = experiment_runner
        self.calls: list[str] = []

    def execute(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        self.calls.append(action.action_id)
        return self._dispatch(state, action, capability=_capability_for(action.type))

    def search(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.RETRIEVAL)

    def probe(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.PROBING)

    def implement(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.CONTROL)

    def run_experiment(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.EXPERIMENT)

    def analyze(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.ANALYSIS)

    def write(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.WRITING)

    def generate_figure(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.FIGURE)

    def _direct(
        self,
        state: ResearchState,
        action: ResearchAction,
        capability: NativeCapability,
    ) -> ExecutionResult:
        self.calls.append(action.action_id)
        return self._dispatch(state, action, capability=capability)

    def _dispatch(
        self,
        state: ResearchState,
        action: ResearchAction,
        *,
        capability: NativeCapability,
    ) -> ExecutionResult:
        input_paths: tuple[Path, ...] = ()
        recover_exact_success = (
            capability == NativeCapability.RETRIEVAL and self.recover_completed_retrieval
        ) or (capability == NativeCapability.EXPERIMENT and self.recover_completed_experiment)
        if recover_exact_success and self.store is not None:
            recovered = self.store.recover_successful(
                state=state,
                action=action,
                capability=capability.value,
            )
            if recovered is not None:
                record, locator = recovered
                return record.result.model_copy(
                    update={
                        "data": {
                            **record.result.data,
                            "execution_record": locator,
                            "execution_record_sha256": record.record_sha256,
                            "execution_sequence": record.sequence,
                        }
                    }
                )
        if handler := self.handlers.get(action.type):
            result = handler(state, action)
            if result.action_id != action.action_id:
                raise ValueError(
                    "native handler result action_id does not match the selected action"
                )
        elif (
            capability == NativeCapability.RETRIEVAL
            and self.store is not None
            and self.knowledge_library is not None
        ):
            result = self._retrieve_knowledge(state, action)
            input_paths = (
                (self.knowledge_library.path,) if self.knowledge_library.path.is_file() else ()
            )
        elif (
            capability == NativeCapability.EXPERIMENT
            and self.experiment_runner is not None
            and action.parameters.get("experiment_id")
            == self.experiment_runner.definition.experiment_id
        ):
            if self.store is None:
                result = self._failed(
                    action,
                    NativeCapability.EXPERIMENT,
                    "native experiment isolation is not configured",
                )
            else:
                result = self.experiment_runner.run(state, action, store=self.store)
                input_paths = self.experiment_runner.input_paths
        else:
            result = self._complete(state, action, capability=capability)
        if self.store is None:
            return result
        record, locator = self.store.publish(
            state=state,
            action=action,
            capability=capability.value,
            result=result,
            input_paths=input_paths,
        )
        return result.model_copy(
            update={
                "data": {
                    **result.data,
                    "execution_record": locator,
                    "execution_record_sha256": record.record_sha256,
                    "execution_sequence": record.sequence,
                }
            }
        )

    def _retrieve_knowledge(
        self,
        state: ResearchState,
        action: ResearchAction,
    ) -> ExecutionResult:
        assert self.store is not None
        assert self.knowledge_library is not None
        query = action.parameters.get("query", action.description)
        domain_tags = action.parameters.get("domain_tags", [state.target_domain])
        limit = action.parameters.get("limit", 5)
        if not isinstance(query, str) or not query.strip():
            return self._failed(action, NativeCapability.RETRIEVAL, "query must be non-empty")
        if (
            not isinstance(domain_tags, list)
            or any(not isinstance(item, str) or not item.strip() for item in domain_tags)
            or len(domain_tags) > 20
        ):
            return self._failed(
                action,
                NativeCapability.RETRIEVAL,
                "domain_tags must contain at most 20 non-empty strings",
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            return self._failed(
                action,
                NativeCapability.RETRIEVAL,
                "limit must be an integer from 1 to 20",
            )
        started_at = datetime.now(UTC)
        started = perf_counter()
        retrieved = KnowledgeRetriever(self.knowledge_library).retrieve(
            query.strip(),
            domain_tags=domain_tags,
            limit=limit,
        )
        finished_at = datetime.now(UTC)
        wall_time_hours = max(0.0, perf_counter() - started) / 3600.0
        result_id = f"res-{uuid4().hex}"
        artifact = self.store.write_artifact_json(
            result_id,
            "retrieval.json",
            {
                "schema_version": "1.0",
                "project_id": state.project_id,
                "action_id": action.action_id,
                "query": query.strip(),
                "domain_tags": domain_tags,
                "limit": limit,
                "results": [item.model_dump(mode="json") for item in retrieved],
            },
        )
        return ExecutionResult(
            result_id=result_id,
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            executor=self.name,
            started_at=started_at,
            finished_at=finished_at,
            observations=[
                f"{item.document.document_id}: {item.document.title}" for item in retrieved
            ],
            artifacts=[self.store.locator(artifact)],
            cost={"wall_time_hours": wall_time_hours},
            data={
                "action_type": action.type.value,
                "capability": NativeCapability.RETRIEVAL.value,
                "execution_mode": "first-party-in-process",
                "result_basis": "knowledge-library-retrieval",
                "cost_basis": "measured-wall-time",
                "state_revision_before": state.revision,
                "retrieved_document_ids": [item.document.document_id for item in retrieved],
                "retrieval_scores": {item.document.document_id: item.score for item in retrieved},
            },
        )

    @classmethod
    def _failed(
        cls,
        action: ResearchAction,
        capability: NativeCapability,
        error: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor=cls.name,
            error=error,
            data={
                "action_type": action.type.value,
                "capability": capability.value,
                "execution_mode": "first-party-in-process",
            },
        )

    @staticmethod
    def _complete(
        state: ResearchState,
        action: ResearchAction,
        *,
        capability: NativeCapability,
    ) -> ExecutionResult:
        raw_observation = action.parameters.get("observation")
        if raw_observation is not None and (
            not isinstance(raw_observation, str) or not raw_observation.strip()
        ):
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor=SciTasteNativeExecutor.name,
                error="native action observation must be a non-empty string",
                data={
                    "action_type": action.type.value,
                    "capability": capability.value,
                    "execution_mode": "first-party-in-process",
                    "state_revision_before": state.revision,
                },
            )
        observations = [raw_observation.strip()] if isinstance(raw_observation, str) else []
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            executor=SciTasteNativeExecutor.name,
            observations=observations,
            cost=dict(action.expected_cost),
            data={
                "action_type": action.type.value,
                "capability": capability.value,
                "execution_mode": "first-party-in-process",
                "result_basis": (
                    "scenario-declared-observation"
                    if observations
                    else "workflow-component-receipt"
                ),
                "cost_basis": "action-declared",
                "state_revision_before": state.revision,
            },
        )


def build_builtin_executor(
    name: str,
    *,
    seed: int = 0,
    workspace: str | Path | None = None,
    artifact_root: str | Path | None = None,
    knowledge_library: KnowledgeLibrary | None = None,
    experiment_runner: NativeExperimentRunner | None = None,
    recover_completed_retrieval: bool = False,
    recover_completed_experiment: bool = False,
):
    """Build a dependency-free executor used by the integrated workflow."""

    if name == SciTasteNativeExecutor.name:
        return SciTasteNativeExecutor(
            workspace=workspace,
            artifact_root=artifact_root,
            knowledge_library=knowledge_library,
            experiment_runner=experiment_runner,
            recover_completed_retrieval=recover_completed_retrieval,
            recover_completed_experiment=recover_completed_experiment,
        )
    if name == "mock":
        from scitaste.executor.mock import MockExecutor

        return MockExecutor(seed=seed)
    raise ValueError(f"unsupported built-in executor {name!r}")


def _capability_for(action_type: MetaAction) -> NativeCapability:
    return _CAPABILITIES.get(action_type, NativeCapability.CONTROL)


__all__ = [
    "NativeCapability",
    "NativeHandler",
    "SciTasteNativeExecutor",
    "build_builtin_executor",
]

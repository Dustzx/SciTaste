"""Auditable one-action vertical slice through an external research substrate."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.executor.autoresearchclaw import AutoResearchClawExecutor
from scitaste.executor.base import ExecutionResult, ExecutionStatus, ResearchExecutor
from scitaste.executor.call_protocol import (
    ExternalCallPhase,
    ExternalCallProtocol,
    tree_fingerprint,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore, canonical_json, snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController


class SubstrateActionInvocation(BaseModel):
    """Pre-call decision intent bound before any external execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    run_dir: str = Field(min_length=1)
    state_snapshot_id: str = Field(pattern=r"^state-[0-9a-f]{64}$")
    action: ResearchAction
    decision: ResearchDecision
    binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    invocation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> SubstrateActionInvocation:
        payload = {"schema_version": "1.0", **values}
        return cls(**payload, invocation_sha256=_content_sha256(payload))

    @model_validator(mode="after")
    def invocation_is_consistent(self) -> SubstrateActionInvocation:
        if self.invocation_sha256 != _content_sha256(
            self.model_dump(mode="json", exclude={"invocation_sha256"})
        ):
            raise ValueError("substrate invocation hash mismatch")
        if (
            self.decision.state_snapshot_id != self.state_snapshot_id
            or self.decision.candidate_actions != [self.action]
            or self.decision.selected_action != self.action
            or self.decision.executor_result_id is not None
            or self.decision.actual_outcome is not None
        ):
            raise ValueError("substrate invocation decision binding mismatch")
        return self


class SubstrateActionWorkflow:
    def __init__(
        self,
        *,
        executor: ResearchExecutor,
        controller: TasteController | None = None,
        seed: int = 0,
    ) -> None:
        self.executor = executor
        self.controller = controller or TasteController(seed=seed)

    def run(
        self,
        *,
        action_type: MetaAction,
        run_dir: str | Path,
        output_dir: str | Path,
        state_path: str | Path | None = None,
        invocation_binding: str | None = None,
        before_execute: Callable[[SubstrateActionInvocation], None] | None = None,
        before_call: Callable[[ResearchState, ResearchAction], None] | None = None,
        project_id: str = "scitaste-substrate-smoke",
        owned_run_id: str = "standalone",
        external_call_attempt: int = 1,
        call_spec_sha256: str | None = None,
        topic: str = "Taste-guided control for autonomous scientific research",
        target_domain: str = "autonomous-research",
    ) -> dict[str, object]:
        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise FileExistsError(f"refusing to append to existing substrate log: {logger.path}")
        state = (
            ResearchState.model_validate_json(Path(state_path).read_text(encoding="utf-8"))
            if state_path
            else ResearchState(
                project_id=project_id,
                research_direction=topic,
                target_domain=target_domain,
            )
        )
        state.executor_context["autoresearchclaw_run_dir"] = str(Path(run_dir).resolve())
        store = StateStore(root)
        state_id = store.save(state)
        action = _substrate_action(action_type)
        decision = self.controller.decide(state=state, candidate_actions=[action])
        invocation = SubstrateActionInvocation.create(
            project_id=state.project_id,
            run_dir=str(Path(run_dir).resolve()),
            state_snapshot_id=state_id,
            action=action,
            decision=decision,
            binding_sha256=invocation_binding,
        )
        _write_once(
            root / "invocation.json",
            invocation.model_dump_json(indent=2) + "\n",
        )
        protocol = ExternalCallProtocol(root / "call_protocol")
        protocol.publish_prepared(
            project_id=project_id,
            run_id=owned_run_id,
            operation="selected_action",
            external_call_attempt=external_call_attempt,
            request_sha256=invocation.invocation_sha256,
            call_spec_sha256=call_spec_sha256
            or _default_call_spec_sha256(self.executor, action, run_dir),
            pre_call_work_sha256=tree_fingerprint(run_dir),
        )
        if before_execute is not None:
            before_execute(invocation)
        return self._execute_prepared(
            state=state,
            action_type=action_type,
            action=action,
            decision=decision,
            invocation=invocation,
            run_dir=run_dir,
            root=root,
            logger=logger,
            store=store,
            protocol=protocol,
            before_call=before_call,
        )

    def resume_prepared(
        self,
        *,
        action_type: MetaAction,
        run_dir: str | Path,
        output_dir: str | Path,
        invocation_binding: str | None = None,
        before_execute: Callable[[SubstrateActionInvocation], None] | None = None,
        before_call: Callable[[ResearchState, ResearchAction], None] | None = None,
        project_id: str = "scitaste-substrate-smoke",
        owned_run_id: str = "standalone",
        external_call_attempt: int = 1,
        call_spec_sha256: str | None = None,
        topic: str = "Taste-guided control for autonomous scientific research",
        target_domain: str = "autonomous-research",
    ) -> dict[str, object]:
        """Continue an exact prepared attempt whose external call never started."""

        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise ValueError("prepared substrate attempt already has a decision log")
        if (root / "executor_result.json").exists() or (root / "executor_result.json").is_symlink():
            raise ValueError("prepared substrate attempt unexpectedly has an executor result")
        invocation = _load_invocation(root)
        state = StateStore(root).load(invocation.state_snapshot_id)
        expected_context = str(Path(run_dir).resolve())
        action = _substrate_action(action_type)
        if (
            state.project_id != project_id
            or state.research_direction != topic
            or state.target_domain != target_domain
            or state.executor_context.get("autoresearchclaw_run_dir") != expected_context
            or invocation.project_id != project_id
            or invocation.run_dir != expected_context
            or invocation.state_snapshot_id != snapshot_id(state)
            or invocation.binding_sha256 != invocation_binding
            or invocation.action != action
        ):
            raise ValueError("prepared substrate predecessor identity drift")
        protocol = ExternalCallProtocol(root / "call_protocol")
        protocol.require_prepared(
            project_id=project_id,
            run_id=owned_run_id,
            operation="selected_action",
            external_call_attempt=external_call_attempt,
            request_sha256=invocation.invocation_sha256,
            call_spec_sha256=call_spec_sha256
            or _default_call_spec_sha256(self.executor, action, run_dir),
            pre_call_work_sha256=tree_fingerprint(run_dir),
        )
        if before_execute is not None:
            before_execute(invocation)
        return self._execute_prepared(
            state=state,
            action_type=action_type,
            action=action,
            decision=invocation.decision.model_copy(deep=True),
            invocation=invocation,
            run_dir=run_dir,
            root=root,
            logger=logger,
            store=StateStore(root),
            protocol=protocol,
            before_call=before_call,
        )

    def _execute_prepared(
        self,
        *,
        state: ResearchState,
        action_type: MetaAction,
        action: ResearchAction,
        decision: ResearchDecision,
        invocation: SubstrateActionInvocation,
        run_dir: str | Path,
        root: Path,
        logger: DecisionLogger,
        store: StateStore,
        protocol: ExternalCallProtocol,
        before_call: Callable[[ResearchState, ResearchAction], None] | None,
    ) -> dict[str, object]:
        prepared = protocol.load(required=True)[0]
        if before_call is not None:
            before_call(state, action)
        protocol.require_prepared(
            project_id=prepared.project_id,
            run_id=prepared.run_id,
            operation="selected_action",
            external_call_attempt=prepared.external_call_attempt,
            request_sha256=invocation.invocation_sha256,
            call_spec_sha256=prepared.call_spec_sha256,
            pre_call_work_sha256=tree_fingerprint(run_dir),
        )
        started = protocol.publish_call_started()
        result = self.executor.execute(state, decision.selected_action)
        result = result.model_copy(
            update={
                "data": {
                    **result.data,
                    "invocation_sha256": invocation.invocation_sha256,
                    "call_started_sha256": started.receipt_sha256,
                }
            }
        )
        # Persist the paid/external result before any later state or decision-log
        # mutation can fail. A retry can then distinguish a recorded response
        # from a call whose outcome is genuinely unknown.
        result_path = root / "executor_result.json"
        _write_once(result_path, result.model_dump_json(indent=2) + "\n")
        call_receipt = protocol.publish_result(
            executor_result_sha256=_file_sha256(result_path),
            result_work_tree_sha256=tree_fingerprint(run_dir),
            result_id=result.result_id,
            execution_status=result.status,
        )
        decision.executor_result_id = result.result_id
        decision.actual_outcome = result.model_dump(mode="json")
        logger.append(decision)
        applied = result.status == ExecutionStatus.SUCCEEDED
        if applied:
            state = apply_transition(state, decision)
            state = record_resource_usage(state, result.cost)
        session = result.data.get("session")
        if isinstance(session, dict):
            state.executor_context["autoresearchclaw_session_id"] = session.get("session_id")
            state.executor_context["autoresearchclaw_upstream_run_id"] = session.get(
                "current_upstream_run_id"
            )
        store.save(state)
        summary: dict[str, object] = {
            "project_id": state.project_id,
            "action": action_type.value,
            "execution_status": result.status.value,
            "transition_applied": applied,
            "state_revision": state.revision,
            "run_dir": str(Path(run_dir).resolve()),
            "artifact_count": len(result.artifacts),
            "artifact_refs": result.artifacts,
            "executor_result": str(result_path),
            "decision_log": str(logger.path),
            "latest_state": str(store.latest_path),
            "call_phase": ExternalCallPhase.RESULT_PUBLISHED.value,
            "call_receipt_sha256": call_receipt.receipt_sha256,
        }
        _write_once(
            root / "substrate_summary.json",
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        )
        return summary

    def recover_recorded_success(
        self,
        *,
        action_type: MetaAction,
        run_dir: str | Path,
        output_dir: str | Path,
        predecessor_run_dir: str | Path | None = None,
        invocation_binding: str | None = None,
        project_id: str = "scitaste-substrate-smoke",
        owned_run_id: str = "standalone",
        external_call_attempt: int = 1,
        call_spec_sha256: str | None = None,
        topic: str = "Taste-guided control for autonomous scientific research",
        target_domain: str = "autonomous-research",
        require_call_protocol: bool = False,
    ) -> dict[str, object] | None:
        """Finish deterministic bookkeeping around one durable successful result.

        The external result is written before the decision log and state update.
        A project-level resume can therefore enter here after an interruption and
        complete those local steps without contacting the executor again.  Every
        already-published local step must either equal the reconstructed value or
        recovery fails closed.
        """

        root = Path(output_dir)
        result_path = root / "executor_result.json"
        if not result_path.is_file() or result_path.is_symlink():
            return None
        result = ExecutionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        if result.status is not ExecutionStatus.SUCCEEDED:
            return None

        store = StateStore(root)
        invocation = _load_invocation(root)
        state = store.load(invocation.state_snapshot_id)
        expected_context = str(Path(run_dir).resolve())
        if (
            state.project_id != project_id
            or state.research_direction != topic
            or state.target_domain != target_domain
            or state.executor_context.get("autoresearchclaw_run_dir") != expected_context
            or invocation.project_id != project_id
            or invocation.run_dir != expected_context
            or invocation.state_snapshot_id != snapshot_id(state)
            or invocation.binding_sha256 != invocation_binding
        ):
            raise ValueError("recorded substrate predecessor state identity drift")

        action = _substrate_action(action_type)
        if result.action_id != action.action_id or invocation.action != action:
            raise ValueError("recorded substrate result belongs to another action")
        if result.data.get("invocation_sha256") != invocation.invocation_sha256:
            raise ValueError("recorded substrate result invocation binding drift")
        protocol = ExternalCallProtocol(root / "call_protocol")
        chain = protocol.load(required=require_call_protocol)
        expected_call_spec = call_spec_sha256 or _default_call_spec_sha256(
            self.executor, action, run_dir
        )
        if chain:
            if len(chain) < 2 or result.data.get("call_started_sha256") != chain[1].receipt_sha256:
                raise ValueError("recorded substrate result call-start binding drift")
            if len(chain) == 3:
                protocol.require_result(
                    project_id=project_id,
                    run_id=owned_run_id,
                    operation="selected_action",
                    external_call_attempt=external_call_attempt,
                    request_sha256=invocation.invocation_sha256,
                    call_spec_sha256=expected_call_spec,
                    pre_call_work_sha256=chain[0].pre_call_work_sha256,
                    result_path=result_path,
                    result_work_tree_sha256=tree_fingerprint(run_dir),
                    result_id=result.result_id,
                    execution_status=result.status,
                )
            elif len(chain) != 2 or chain[-1].phase is not ExternalCallPhase.CALL_STARTED:
                raise ValueError("recorded substrate result has an invalid call phase")
        verifier = getattr(self.executor, "verify_recorded_success", None)
        if not callable(verifier):
            raise ValueError("executor does not support recorded-success verification")
        verified = verifier(
            state,
            action,
            result,
            predecessor_run_dir=predecessor_run_dir,
        )
        if verified != result:
            raise ValueError("executor changed the recorded substrate result during verification")
        if chain and len(chain) == 2:
            protocol.require_result(
                project_id=project_id,
                run_id=owned_run_id,
                operation="selected_action",
                external_call_attempt=external_call_attempt,
                request_sha256=invocation.invocation_sha256,
                call_spec_sha256=expected_call_spec,
                pre_call_work_sha256=chain[0].pre_call_work_sha256,
                result_path=result_path,
                result_work_tree_sha256=tree_fingerprint(run_dir),
                result_id=result.result_id,
                execution_status=result.status,
                allow_unjournaled_publication=True,
            )
            chain = protocol.load(required=True)
        logger = DecisionLogger(root / "decisions.jsonl")
        decisions = logger.read_all()
        if len(decisions) > 1:
            raise ValueError("recorded substrate recovery found multiple decisions")
        if decisions:
            decision = decisions[0]
            _validate_recovered_decision(decision, invocation, state, action, result)
        else:
            decision = invocation.decision.model_copy(deep=True)
            decision.executor_result_id = result.result_id
            decision.actual_outcome = result.model_dump(mode="json")
            logger.append(decision)

        recovered_state = apply_transition(state, decision)
        recovered_state = record_resource_usage(recovered_state, result.cost)
        session = result.data.get("session")
        if isinstance(session, dict):
            recovered_state.executor_context["autoresearchclaw_session_id"] = session.get(
                "session_id"
            )
            recovered_state.executor_context["autoresearchclaw_upstream_run_id"] = session.get(
                "current_upstream_run_id"
            )
        if store.latest_path.is_file():
            current = store.load()
            if current.revision not in {state.revision, recovered_state.revision}:
                raise ValueError("recorded substrate latest state has an invalid revision")
            if current.revision == recovered_state.revision:
                expected = recovered_state.model_copy(deep=True)
                if (
                    not current.transition_history
                    or not expected.transition_history
                    or current.transition_history[-1].transition_id
                    != expected.transition_history[-1].transition_id
                ):
                    raise ValueError("recorded substrate final state drift")
                # The transition timestamp was assigned when the transition was
                # first applied. Replay every semantic field while preserving
                # that durable timestamp instead of inventing a later one.
                expected.transition_history[-1].timestamp = current.transition_history[-1].timestamp
                if current != expected:
                    raise ValueError("recorded substrate final state drift")
                recovered_state = current
        store.save(recovered_state)
        summary: dict[str, object] = {
            "project_id": recovered_state.project_id,
            "action": action_type.value,
            "execution_status": result.status.value,
            "transition_applied": True,
            "state_revision": recovered_state.revision,
            "run_dir": expected_context,
            "artifact_count": len(result.artifacts),
            "artifact_refs": result.artifacts,
            "executor_result": str(result_path),
            "decision_log": str(logger.path),
            "latest_state": str(store.latest_path),
        }
        if chain:
            summary.update(
                {
                    "call_phase": ExternalCallPhase.RESULT_PUBLISHED.value,
                    "call_receipt_sha256": chain[-1].receipt_sha256,
                }
            )
        summary_path = root / "substrate_summary.json"
        if summary_path.is_file():
            if (
                summary_path.is_symlink()
                or json.loads(summary_path.read_text(encoding="utf-8")) != summary
            ):
                raise ValueError("recorded substrate summary drift")
        else:
            _write_once(
                summary_path,
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            )
        return summary


def _substrate_action(action_type: MetaAction) -> ResearchAction:
    return ResearchAction(
        action_id=f"substrate-{action_type.value.casefold().replace('_', '-')}",
        type=action_type,
        description=f"Execute {action_type.value} through the pinned AutoResearchClaw adapter",
        expected_value={"information_gain": 0.5},
    )


def _validate_recovered_decision(
    decision: ResearchDecision,
    invocation: SubstrateActionInvocation,
    state: ResearchState,
    action: ResearchAction,
    result: ExecutionResult,
) -> None:
    expected_outcome = result.model_dump(mode="json")
    expected_decision = invocation.decision.model_copy(deep=True)
    expected_decision.executor_result_id = result.result_id
    expected_decision.actual_outcome = expected_outcome
    if (
        decision != expected_decision
        or decision.stage != state.current_stage.value
        or decision.state_snapshot_id != snapshot_id(state)
        or decision.selected_action != action
    ):
        raise ValueError("recorded substrate decision drift")


def _load_invocation(root: Path) -> SubstrateActionInvocation:
    path = root / "invocation.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("recorded substrate invocation must be a regular file")
    try:
        return SubstrateActionInvocation.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid recorded substrate invocation") from exc


def _content_sha256(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, dict):
        value = {
            key: item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for key, item in value.items()
        }
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _default_call_spec_sha256(
    executor: ResearchExecutor,
    action: ResearchAction,
    run_dir: str | Path,
) -> str:
    return _content_sha256(
        {
            "executor_type": f"{type(executor).__module__}.{type(executor).__qualname__}",
            "action": action.model_dump(mode="json"),
            "run_dir": str(Path(run_dir).resolve()),
        }
    )


def _write_once(path: Path, contents: str) -> None:
    """Atomically publish a new evidence file without replacing an earlier one."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(path.parent)


def build_autoresearchclaw_workflow(
    *,
    config_path: str | Path,
    seed: int,
    timeout_seconds: float,
    max_output_tokens: int | None,
    max_total_tokens: int | None = None,
) -> SubstrateActionWorkflow:
    return SubstrateActionWorkflow(
        executor=AutoResearchClawExecutor(
            config_path=config_path,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            max_total_tokens=max_total_tokens,
        ),
        seed=seed,
    )

"""Auditable one-action vertical slice through an external research substrate."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from scitaste.executor.autoresearchclaw import AutoResearchClawExecutor
from scitaste.executor.base import ExecutionStatus, ResearchExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchState
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController


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
        project_id: str = "scitaste-substrate-smoke",
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
        store.save(state)
        action = ResearchAction(
            action_id=f"substrate-{action_type.value.casefold().replace('_', '-')}",
            type=action_type,
            description=f"Execute {action_type.value} through the pinned AutoResearchClaw adapter",
            expected_value={"information_gain": 0.5},
        )
        decision = self.controller.decide(state=state, candidate_actions=[action])
        result = self.executor.execute(state, decision.selected_action)
        # Persist the paid/external result before any later state or decision-log
        # mutation can fail. A retry can then distinguish a recorded response
        # from a call whose outcome is genuinely unknown.
        result_path = root / "executor_result.json"
        _write_once(result_path, result.model_dump_json(indent=2) + "\n")
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
        }
        _write_once(
            root / "substrate_summary.json",
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        )
        return summary


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
    finally:
        temporary.unlink(missing_ok=True)


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

"""Durable orchestration primitives for an adaptive-policy activation campaign.

The scientific state machine lives in :mod:`adaptive_policy_activation`.  This
module adds only the append-only journal and the deterministic next-action
projection needed by a live operator.  It never contacts a provider, loads a
model, allocates a GPU, or executes a benchmark.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from scitaste.evaluation.adaptive_policy_activation import (
    AdaptivePolicyActivationCampaignState,
    AdaptivePolicyActivationReviewPermit,
    AdaptivePolicyActivationTaskPermit,
    load_adaptive_policy_activation_review_permit,
    load_adaptive_policy_activation_state,
    load_adaptive_policy_activation_task_permit,
    save_adaptive_policy_activation_artifact,
)


class AdaptivePolicyActivationAction(StrEnum):
    """The one legal operator action implied by a sealed campaign state."""

    ISSUE_TASK = "issue-task"
    EXECUTE_TASK = "execute-task"
    ISSUE_REVIEW = "issue-review"
    EXECUTE_REVIEW = "execute-review"
    CLOSE_EMPTY_REVIEW = "close-empty-review"
    FINALIZE = "finalize"
    COMPLETE = "complete"


def next_adaptive_policy_activation_action(
    state: AdaptivePolicyActivationCampaignState,
) -> AdaptivePolicyActivationAction:
    """Project one state to one action without performing external work."""

    if state.status == "awaiting-owner-approval":
        raise ValueError("adaptive activation campaign still requires exact owner approval")
    if state.status == "ready":
        return AdaptivePolicyActivationAction.ISSUE_TASK
    if state.status == "running":
        return AdaptivePolicyActivationAction.EXECUTE_TASK
    if state.status == "trajectory-complete":
        if any(item.status == "review-pending" for item in state.tasks):
            return AdaptivePolicyActivationAction.ISSUE_REVIEW
        return AdaptivePolicyActivationAction.CLOSE_EMPTY_REVIEW
    if state.status == "review-ready":
        return AdaptivePolicyActivationAction.ISSUE_REVIEW
    if state.status == "reviewing":
        return AdaptivePolicyActivationAction.EXECUTE_REVIEW
    if state.status == "review-complete":
        return AdaptivePolicyActivationAction.FINALIZE
    if state.status == "finalized":
        return AdaptivePolicyActivationAction.COMPLETE
    raise ValueError(f"unsupported adaptive activation state: {state.status}")


class AdaptivePolicyActivationJournal:
    """Append-only state and one-use-permit store for one campaign."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError(f"activation journal cannot be a symlink: {self.root}")
        self.states = self.root / "states"
        self.task_permits = self.root / "permits" / "tasks"
        self.review_permits = self.root / "permits" / "reviews"
        self.results = self.root / "results"

    def bootstrap(
        self, state: AdaptivePolicyActivationCampaignState
    ) -> AdaptivePolicyActivationCampaignState:
        """Create the journal once, or verify it resumes the same campaign."""

        self._recover_pending_states()
        existing = self._state_paths()
        if existing:
            latest = self.latest_state()
            if (
                latest.campaign_id != state.campaign_id
                or latest.project_id != state.project_id
                or latest.plan_sha256 != state.plan_sha256
                or latest.approval_sha256 != state.approval_sha256
            ):
                raise ValueError("activation journal belongs to another approved campaign")
            return latest
        self.append_state(state, require_successor=False)
        return state

    def latest_state(self) -> AdaptivePolicyActivationCampaignState:
        self._recover_pending_states()
        paths = self._state_paths()
        if not paths:
            raise FileNotFoundError(f"activation journal has no states: {self.states}")
        observed: dict[int, tuple[Path, AdaptivePolicyActivationCampaignState]] = {}
        for path in paths:
            state = load_adaptive_policy_activation_state(path)
            if state.sequence in observed:
                raise ValueError(
                    f"activation journal repeats state sequence {state.sequence}: {path}"
                )
            expected = self._state_name(state)
            if path.name != expected:
                raise ValueError(f"activation journal state filename is not canonical: {path}")
            observed[state.sequence] = (path, state)
        sequences = sorted(observed)
        if sequences != list(range(sequences[0], sequences[-1] + 1)):
            raise ValueError("activation journal state sequence is not contiguous")
        campaign_keys = {
            (item.campaign_id, item.project_id, item.plan_sha256, item.approval_sha256)
            for _, item in observed.values()
        }
        if len(campaign_keys) != 1:
            raise ValueError("activation journal mixes campaign authorities")
        return observed[sequences[-1]][1]

    def append_state(
        self,
        state: AdaptivePolicyActivationCampaignState,
        *,
        require_successor: bool = True,
    ) -> Path:
        if require_successor and self._state_paths():
            latest = self.latest_state()
            if state.sequence != latest.sequence + 1:
                raise ValueError("activation journal accepts only the next state sequence")
            if (
                state.campaign_id,
                state.project_id,
                state.plan_sha256,
                state.approval_sha256,
            ) != (
                latest.campaign_id,
                latest.project_id,
                latest.plan_sha256,
                latest.approval_sha256,
            ):
                raise ValueError("activation journal successor changed campaign authority")
        return save_adaptive_policy_activation_artifact(
            state, self.states / self._state_name(state)
        )

    def save_task_permit(self, permit: AdaptivePolicyActivationTaskPermit) -> Path:
        return self._save_permit(
            permit,
            self.task_permits
            / f"{permit.ordinal:02d}-{permit.task_id}-{permit.permit_sha256[:12]}.json",
        )

    def save_review_permit(self, permit: AdaptivePolicyActivationReviewPermit) -> Path:
        return self._save_permit(
            permit,
            self.review_permits
            / f"{permit.ordinal:02d}-{permit.task_id}-{permit.permit_sha256[:12]}.json",
        )

    def active_task_permit(
        self, state: AdaptivePolicyActivationCampaignState
    ) -> tuple[Path, AdaptivePolicyActivationTaskPermit]:
        if state.active_permit_sha256 is None:
            raise ValueError("activation state has no active task permit")
        matches = []
        for path in self._regular_json_files(self.task_permits):
            permit = load_adaptive_policy_activation_task_permit(path)
            if permit.permit_sha256 == state.active_permit_sha256:
                matches.append((path, permit))
        if len(matches) != 1:
            raise ValueError("activation journal cannot resolve one active task permit")
        return matches[0]

    def active_review_permit(
        self, state: AdaptivePolicyActivationCampaignState
    ) -> tuple[Path, AdaptivePolicyActivationReviewPermit]:
        if state.active_review_permit_sha256 is None:
            raise ValueError("activation state has no active review permit")
        matches = []
        for path in self._regular_json_files(self.review_permits):
            permit = load_adaptive_policy_activation_review_permit(path)
            if permit.permit_sha256 == state.active_review_permit_sha256:
                matches.append((path, permit))
        if len(matches) != 1:
            raise ValueError("activation journal cannot resolve one active review permit")
        return matches[0]

    def state_output_path(self, sequence: int, status: str) -> Path:
        """Return a recoverable pending path that the runner must create once."""

        return self.states / f"{sequence:04d}-{status}.json.pending"

    def adopt_runner_state(self, temporary: Path) -> AdaptivePolicyActivationCampaignState:
        """Rename a freshly sealed runner state to its hash-canonical journal name."""

        state = load_adaptive_policy_activation_state(temporary)
        canonical = self.states / self._state_name(state)
        if canonical.exists() or canonical.is_symlink():
            raise FileExistsError(canonical)
        latest_without_temporary = [path for path in self._state_paths() if path != temporary]
        if latest_without_temporary:
            previous = max(
                (load_adaptive_policy_activation_state(path) for path in latest_without_temporary),
                key=lambda item: item.sequence,
            )
            if state.sequence != previous.sequence + 1:
                raise ValueError("activation runner state is not the next journal sequence")
        temporary.replace(canonical)
        return state

    def result_path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("activation result name must be one safe path component")
        return self.results / name

    def state_path(self, state: AdaptivePolicyActivationCampaignState) -> Path:
        path = self.states / self._state_name(state)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        return path

    @staticmethod
    def _state_name(state: AdaptivePolicyActivationCampaignState) -> str:
        return f"{state.sequence:04d}-{state.status}-{state.state_sha256[:12]}.json"

    def _state_paths(self) -> list[Path]:
        return self._regular_json_files(self.states)

    def _recover_pending_states(self) -> None:
        """Canonicalize complete runner outputs left between write and rename."""

        if not self.states.exists():
            return
        if self.states.is_symlink():
            raise ValueError(f"activation journal directory cannot be a symlink: {self.states}")
        for path in sorted(self.states.glob("*.pending")):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"activation pending state must be a regular file: {path}")
            state = load_adaptive_policy_activation_state(path)
            canonical = self.states / self._state_name(state)
            if canonical.exists() or canonical.is_symlink():
                raise FileExistsError(canonical)
            path.replace(canonical)

    @staticmethod
    def _regular_json_files(directory: Path) -> list[Path]:
        if directory.is_symlink():
            raise ValueError(f"activation journal directory cannot be a symlink: {directory}")
        if not directory.exists():
            return []
        paths = []
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"activation journal artifact must be a regular file: {path}")
            paths.append(path)
        return paths

    @staticmethod
    def _save_permit(permit: BaseModel, path: Path) -> Path:
        return save_adaptive_policy_activation_artifact(permit, path)


__all__ = [
    "AdaptivePolicyActivationAction",
    "AdaptivePolicyActivationJournal",
    "next_adaptive_policy_activation_action",
]

"""Reconstruct exact decision foundations without inventing scientific outcomes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import ProjectIdeaRevisionBinding, idea_binding_matches_current
from scitaste.project.models import content_sha256, validate_project_id, validate_relative_locator
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.taste.episodes import TasteEpisodePartition, TasteEpisodeSourceRelationship

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_STATE_ID = r"^state-[0-9a-f]{64}$"
_MAX_DECISION_LOG_BYTES = 16 * 1024 * 1024
_MAX_DECISION_LINE_BYTES = 2 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_CONTRACT_BYTES = 4 * 1024 * 1024
_MAX_STATE_TREE_ENTRIES = 50_000


class TasteTrajectoryAssignmentTiming(StrEnum):
    PROSPECTIVE = "prospective"
    RETROSPECTIVE_DEVELOPMENT = "retrospective-development"


class TasteTrajectoryFollowup(StrEnum):
    AWAITING_DELAYED_SCIENTIFIC_OUTCOME = "awaiting-delayed-scientific-outcome"
    NOT_COMPARATIVE = "not-comparative-decision"
    NOT_EXECUTED = "not-executed"
    STATE_UNAVAILABLE = "state-unavailable"
    RETROSPECTIVE_AUDIT_ONLY = "retrospective-audit-only"


class TasteTrajectorySamplingPlan(BaseModel):
    """A split and natural sampling unit fixed before attribution review."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    idea_revision: ProjectIdeaRevisionBinding
    source_project_id: str
    source_run_id: str = Field(pattern=_ID)
    source_relationship: TasteEpisodeSourceRelationship
    source_group_id: str = Field(pattern=_ID)
    dataset_partition: TasteEpisodePartition
    assignment_timing: TasteTrajectoryAssignmentTiming
    decision_log_locator: str
    state_snapshot_root_locator: str
    frozen_at: datetime
    source_absent_when_frozen: bool
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def sampling_plan_is_closed(self) -> TasteTrajectorySamplingPlan:
        validate_project_id(self.project_id)
        validate_project_id(self.source_project_id)
        validate_relative_locator(self.decision_log_locator, field_name="decision log locator")
        validate_relative_locator(
            self.state_snapshot_root_locator,
            field_name="state snapshot root locator",
        )
        if self.frozen_at.utcoffset() is None:
            raise ValueError("trajectory sampling freeze time must include a timezone")
        if self.idea_revision.project_id != self.project_id:
            raise ValueError("trajectory sampling plan Idea belongs to another project")
        if self.idea_revision.observed_project_revision > self.observed_project_revision:
            raise ValueError("trajectory sampling plan predates its Idea binding")
        if self.source_relationship is TasteEpisodeSourceRelationship.EXTERNAL_RECORD:
            raise ValueError("decision-log reconstruction accepts project trajectories only")
        if (self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT) != (
            self.source_project_id == self.project_id
        ):
            raise ValueError("trajectory source relationship disagrees with project identity")
        if (
            self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT
            and self.dataset_partition is not TasteEpisodePartition.DEVELOPMENT
        ):
            raise ValueError("self-project trajectories are development-only")
        if self.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
            if self.dataset_partition is not TasteEpisodePartition.DEVELOPMENT:
                raise ValueError("retrospective trajectories are development-only")
            if self.source_absent_when_frozen:
                raise ValueError("retrospective sampling cannot claim a pre-source freeze")
        elif not self.source_absent_when_frozen:
            raise ValueError("prospective sampling requires a pre-source freeze")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("trajectory sampling plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteTrajectorySamplingPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class TasteTrajectoryDecisionSeed(BaseModel):
    """Exact pre-attribution decision material from one immutable log line."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    line_number: int = Field(ge=1)
    line_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    decision_sha256: str = Field(pattern=_SHA256)
    decision_timestamp: datetime
    stage: str
    state_snapshot_id: str = Field(pattern=_STATE_ID)
    state_snapshot_locators: tuple[str, ...]
    state_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    state_verified: bool
    alternative_count: int = Field(ge=1)
    selected_action_id: str
    executor_result_id: str | None
    executor_outcome_sha256: str | None = Field(default=None, pattern=_SHA256)
    executor_status: str | None = None
    execution_binding_complete: bool
    delayed_scientific_outcome_bound: Literal[False] = False
    foundation_eligible: bool
    followup: TasteTrajectoryFollowup
    finding_codes: tuple[str, ...]

    @model_validator(mode="after")
    def seed_does_not_invent_an_outcome(self) -> TasteTrajectoryDecisionSeed:
        for locator in self.state_snapshot_locators:
            validate_relative_locator(locator, field_name="state snapshot locator")
        if self.decision_timestamp.utcoffset() is None:
            raise ValueError("trajectory decision timestamp must include a timezone")
        if self.state_verified != (
            self.state_file_sha256 is not None and bool(self.state_snapshot_locators)
        ):
            raise ValueError("trajectory state verification and digest disagree")
        if self.execution_binding_complete != (
            self.executor_result_id is not None and self.executor_outcome_sha256 is not None
        ):
            raise ValueError("trajectory executor binding is incomplete")
        expected_eligible = (
            self.state_verified
            and self.alternative_count >= 2
            and self.execution_binding_complete
            and self.followup is TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME
        )
        if self.foundation_eligible != expected_eligible:
            raise ValueError("trajectory foundation eligibility disagrees with its evidence")
        if len(self.finding_codes) != len(set(self.finding_codes)):
            raise ValueError("trajectory finding codes must be unique")
        return self


class TasteTrajectoryInventory(BaseModel):
    """Read-only reconstruction receipt; it has no attribution or training authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_revision_record_sha256: str = Field(pattern=_SHA256)
    decision_log_locator: str
    decision_log_sha256: str = Field(pattern=_SHA256)
    decision_count: int = Field(ge=0)
    multi_alternative_count: int = Field(ge=0)
    state_verified_count: int = Field(ge=0)
    execution_bound_count: int = Field(ge=0)
    foundation_eligible_count: int = Field(ge=0)
    decisions: tuple[TasteTrajectoryDecisionSeed, ...]
    scientific_outcome_labels_created: Literal[False] = False
    policy_training_authorized: Literal[False] = False
    inventory_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def inventory_is_closed(self) -> TasteTrajectoryInventory:
        validate_relative_locator(self.decision_log_locator, field_name="decision log locator")
        if self.decision_count != len(self.decisions):
            raise ValueError("trajectory decision count differs")
        if len({item.decision_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("trajectory decision IDs must be unique")
        expected_counts = (
            sum(item.alternative_count >= 2 for item in self.decisions),
            sum(item.state_verified for item in self.decisions),
            sum(item.execution_binding_complete for item in self.decisions),
            sum(item.foundation_eligible for item in self.decisions),
        )
        observed_counts = (
            self.multi_alternative_count,
            self.state_verified_count,
            self.execution_bound_count,
            self.foundation_eligible_count,
        )
        if observed_counts != expected_counts:
            raise ValueError("trajectory inventory aggregate counts differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))
        if self.inventory_sha256 != expected:
            raise ValueError("trajectory inventory hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteTrajectoryInventory:
        payload = {"schema_version": "1.0", **values}
        payload.pop("inventory_sha256", None)
        unsigned = cls.model_construct(inventory_sha256="0" * 64, **payload)
        return cls(
            **payload,
            inventory_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"inventory_sha256"})
            ),
        )


def reconstruct_taste_trajectory(
    plan: TasteTrajectorySamplingPlan,
    *,
    source_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> TasteTrajectoryInventory:
    """Verify exact decisions and states while leaving scientific outcomes unlabelled."""

    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("trajectory sampling plan belongs to a stale Idea revision")
    root = _canonical_root(source_root)
    decision_path = _owned_file(
        root,
        plan.decision_log_locator,
        max_bytes=_MAX_DECISION_LOG_BYTES,
    )
    decision_bytes = decision_path.read_bytes()
    decision_log_sha256 = hashlib.sha256(decision_bytes).hexdigest()
    state_index = _index_state_snapshots(root, plan.state_snapshot_root_locator)
    decisions: list[TasteTrajectoryDecisionSeed] = []
    for line_number, raw_line in enumerate(decision_bytes.splitlines(keepends=True), 1):
        if len(raw_line) > _MAX_DECISION_LINE_BYTES:
            raise ValueError(f"decision log line {line_number} exceeds the byte limit")
        if not raw_line.strip():
            raise ValueError(f"decision log line {line_number} is empty")
        try:
            decision = ResearchDecision.model_validate_json(raw_line)
        except ValueError as exc:
            raise ValueError(f"invalid decision log line {line_number}") from exc
        decisions.append(
            _reconstruct_decision(plan, root, state_index, line_number, raw_line, decision)
        )
    return TasteTrajectoryInventory.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        idea_revision_id=plan.idea_revision.revision_id,
        idea_revision_record_sha256=plan.idea_revision.record_sha256,
        decision_log_locator=plan.decision_log_locator,
        decision_log_sha256=decision_log_sha256,
        decision_count=len(decisions),
        multi_alternative_count=sum(item.alternative_count >= 2 for item in decisions),
        state_verified_count=sum(item.state_verified for item in decisions),
        execution_bound_count=sum(item.execution_binding_complete for item in decisions),
        foundation_eligible_count=sum(item.foundation_eligible for item in decisions),
        decisions=tuple(decisions),
    )


def load_taste_trajectory_sampling_plan(path: str | Path) -> TasteTrajectorySamplingPlan:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteTrajectorySamplingPlan.model_validate_json(source.read_bytes())


def save_taste_trajectory_sampling_plan(
    plan: TasteTrajectorySamplingPlan,
    path: str | Path,
) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def save_taste_trajectory_inventory(
    inventory: TasteTrajectoryInventory,
    path: str | Path,
) -> Path:
    return _write_new_json(path, inventory.model_dump_json(indent=2) + "\n")


def _reconstruct_decision(
    plan: TasteTrajectorySamplingPlan,
    root: Path,
    state_index: dict[str, tuple[str, ...]],
    line_number: int,
    raw_line: bytes,
    decision: ResearchDecision,
) -> TasteTrajectoryDecisionSeed:
    state_locators = state_index.get(decision.state_snapshot_id, ())
    state_verified = False
    state_file_sha256: str | None = None
    findings: list[str] = []
    try:
        state_paths = tuple(
            _owned_file(root, locator, max_bytes=_MAX_STATE_BYTES) for locator in state_locators
        )
        if not state_paths:
            raise FileNotFoundError(decision.state_snapshot_id)
    except FileNotFoundError:
        findings.append("state-snapshot-missing")
    else:
        state_bytes = state_paths[0].read_bytes()
        if any(path.read_bytes() != state_bytes for path in state_paths[1:]):
            raise ValueError("duplicate state snapshot locators contain different bytes")
        try:
            state = ResearchState.model_validate_json(state_bytes)
        except ValueError:
            findings.append("state-snapshot-invalid")
        else:
            if snapshot_id(state) != decision.state_snapshot_id:
                findings.append("state-snapshot-identity-drift")
            else:
                state_verified = True
                state_file_sha256 = hashlib.sha256(state_bytes).hexdigest()

    alternative_count = len(decision.candidate_actions)
    if alternative_count < 2:
        findings.append("decision-has-no-recorded-alternative")
    outcome = decision.actual_outcome
    outcome_sha256 = content_sha256(outcome) if outcome is not None else None
    execution_complete = decision.executor_result_id is not None and outcome_sha256 is not None
    if not execution_complete:
        findings.append("executor-outcome-unbound")
    if plan.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
        findings.append("retrospective-development-audit")

    if not state_verified:
        followup = TasteTrajectoryFollowup.STATE_UNAVAILABLE
    elif alternative_count < 2:
        followup = TasteTrajectoryFollowup.NOT_COMPARATIVE
    elif not execution_complete:
        followup = TasteTrajectoryFollowup.NOT_EXECUTED
    elif plan.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
        followup = TasteTrajectoryFollowup.RETROSPECTIVE_AUDIT_ONLY
    else:
        followup = TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME

    executor_status = outcome.get("status") if isinstance(outcome, dict) else None
    if not isinstance(executor_status, str):
        executor_status = None
    return TasteTrajectoryDecisionSeed(
        line_number=line_number,
        line_sha256=hashlib.sha256(raw_line).hexdigest(),
        decision_id=decision.decision_id,
        decision_sha256=content_sha256(decision.model_dump(mode="json")),
        decision_timestamp=decision.timestamp,
        stage=decision.stage,
        state_snapshot_id=decision.state_snapshot_id,
        state_snapshot_locators=state_locators if state_verified else (),
        state_file_sha256=state_file_sha256,
        state_verified=state_verified,
        alternative_count=alternative_count,
        selected_action_id=decision.selected_action.action_id,
        executor_result_id=decision.executor_result_id,
        executor_outcome_sha256=outcome_sha256,
        executor_status=executor_status,
        execution_binding_complete=execution_complete,
        foundation_eligible=followup is TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME,
        followup=followup,
        finding_codes=tuple(findings),
    )


def _canonical_root(value: str | Path) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise ValueError("trajectory source root cannot be a symbolic link")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("trajectory source root must be a directory")
    return resolved


def _owned_file(root: Path, locator: str, *, max_bytes: int) -> Path:
    validate_relative_locator(locator, field_name="trajectory source locator")
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("trajectory sources cannot use symbolic links")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    stat = resolved.stat()
    if not resolved.is_file() or stat.st_size > max_bytes:
        raise ValueError("trajectory source is not a bounded regular file")
    return resolved


def _index_state_snapshots(root: Path, locator: str) -> dict[str, tuple[str, ...]]:
    search_root = _owned_directory(root, locator)
    discovered: dict[str, list[str]] = {}
    entry_count = 0
    for directory, names, files in os.walk(search_root, followlinks=False):
        directory_path = Path(directory)
        entry_count += len(names) + len(files)
        if entry_count > _MAX_STATE_TREE_ENTRIES:
            raise ValueError("trajectory state tree exceeds the entry limit")
        for name in (*names, *files):
            if (directory_path / name).is_symlink():
                raise ValueError("trajectory state tree cannot contain symbolic links")
        if directory_path.name != "state_snapshots":
            continue
        for name in files:
            if not name.startswith("state-") or not name.endswith(".json"):
                continue
            identifier = name.removesuffix(".json")
            if len(identifier) != 70 or any(
                character not in "0123456789abcdef" for character in identifier[6:]
            ):
                raise ValueError("trajectory state snapshot filename is not content-addressed")
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            discovered.setdefault(identifier, []).append(relative)
    return {identifier: tuple(sorted(locators)) for identifier, locators in discovered.items()}


def _owned_directory(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="trajectory source locator")
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("trajectory sources cannot use symbolic links")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_dir():
        raise ValueError("trajectory source is not a directory")
    return resolved


def _bounded_input_file(value: str | Path, *, max_bytes: int) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("trajectory contract input cannot be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > max_bytes:
        raise ValueError("trajectory contract input is not a bounded regular file")
    return resolved


def _write_new_json(value: str | Path, contents: str) -> Path:
    path = Path(value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    parent = path.parent.resolve(strict=True)
    if parent.is_symlink():
        raise ValueError("trajectory output parent cannot be a symbolic link")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


__all__ = [
    "TasteTrajectoryAssignmentTiming",
    "TasteTrajectoryDecisionSeed",
    "TasteTrajectoryFollowup",
    "TasteTrajectoryInventory",
    "TasteTrajectorySamplingPlan",
    "load_taste_trajectory_sampling_plan",
    "reconstruct_taste_trajectory",
    "save_taste_trajectory_inventory",
    "save_taste_trajectory_sampling_plan",
]

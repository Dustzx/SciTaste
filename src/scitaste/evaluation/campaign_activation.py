"""Authorize one complete pilot task block without granting claim authority."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.cell_plan import EvaluationCellPlan, PlannedEvaluationCell
from scitaste.evaluation.prelaunch import ExecutionLaneKind
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_ACTIVATION_BYTES = 1_048_576


class EvaluationCampaignActivationApproval(BaseModel):
    """Owner decision over the exact activation scope and resource ceiling."""

    model_config = _CONFIG

    approved: bool = False
    approved_activation_sha256: str | None = Field(default=None, pattern=_SHA256)
    approved_by: str | None = Field(default=None, min_length=1, max_length=200)
    approved_at: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def approval_is_complete_or_empty(self) -> EvaluationCampaignActivationApproval:
        values = (self.approved_activation_sha256, self.approved_by, self.approved_at)
        if self.approved and not all(values):
            raise ValueError("campaign activation approval requires hash, owner, and time")
        if not self.approved and any(values):
            raise ValueError("unapproved campaign activation cannot contain approval metadata")
        return self


class EvaluationCampaignActivation(BaseModel):
    """A closed feasibility-only subset of a larger pilot cell plan."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    activation_id: str
    project_id: str
    evaluation_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    purpose: Literal["feasibility-task-block"] = "feasibility-task-block"
    selected_task_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    selected_lane_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    selected_system_ids: tuple[str, ...] = Field(min_length=2, max_length=30)
    selected_cell_ids: tuple[str, ...] = Field(min_length=2, max_length=10_000)
    maximum_total_gpu_hours: float = Field(ge=0)
    maximum_total_api_cost: float = Field(ge=0)
    maximum_total_tokens: int = Field(ge=0)
    maximum_total_storage_bytes: int = Field(ge=0)
    claim_authority: Literal[False] = False
    approval: EvaluationCampaignActivationApproval = Field(
        default_factory=EvaluationCampaignActivationApproval
    )
    authorizes_unselected_cells: Literal[False] = False
    authorizes_claim_analysis: Literal[False] = False

    @model_validator(mode="after")
    def activation_identity_is_safe_and_approved_exactly(
        self,
    ) -> EvaluationCampaignActivation:
        validate_entry_id(self.activation_id, field_name="activation_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.evaluation_id, field_name="evaluation_id")
        for field_name, values in (
            ("selected_task_ids", self.selected_task_ids),
            ("selected_lane_ids", self.selected_lane_ids),
            ("selected_system_ids", self.selected_system_ids),
            ("selected_cell_ids", self.selected_cell_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"campaign activation {field_name} must be unique")
            for value in values:
                validate_entry_id(value, field_name=field_name)
        if self.approval.approved and (
            self.approval.approved_activation_sha256 != self.activation_sha256
        ):
            raise ValueError("campaign activation approval targets different bytes")
        return self

    @computed_field
    @property
    def activation_sha256(self) -> str:
        return content_sha256(
            self.model_dump(mode="json", exclude={"approval", "activation_sha256"})
        )


def compile_evaluation_campaign_activation(
    plan: EvaluationCellPlan,
    *,
    activation_id: str,
    project_id: str,
    evaluation_id: str,
    task_ids: tuple[str, ...],
) -> EvaluationCampaignActivation:
    """Compile whole task blocks; never select a favorable condition or result."""

    if plan.study_scope != "pilot":
        raise ValueError("feasibility task-block activation is limited to pilot plans")
    selected = _selected_task_block(plan, task_ids)
    return EvaluationCampaignActivation(
        activation_id=activation_id,
        project_id=project_id,
        evaluation_id=evaluation_id,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        selected_task_ids=_ordered_unique(cell.task_id for cell in selected),
        selected_lane_ids=_ordered_unique(cell.lane_id for cell in selected),
        selected_system_ids=_ordered_unique(cell.system_id for cell in selected),
        selected_cell_ids=tuple(cell.cell_id for cell in selected),
        maximum_total_gpu_hours=sum(
            float(cell.resource.max_gpu_hours or 0)
            for cell in selected
            if cell.lane_kind is ExecutionLaneKind.GPU
        ),
        maximum_total_api_cost=sum(
            float(cell.resource.max_cost or 0)
            for cell in selected
            if cell.lane_kind is ExecutionLaneKind.API_ONLY
        ),
        maximum_total_tokens=sum(
            int(cell.resource.max_total_tokens or 0)
            for cell in selected
            if cell.lane_kind is ExecutionLaneKind.API_ONLY
        ),
        maximum_total_storage_bytes=sum(
            int(cell.resource.max_storage_bytes or 0)
            for cell in selected
            if cell.lane_kind is ExecutionLaneKind.GPU
        ),
    )


def approve_evaluation_campaign_activation(
    activation: EvaluationCampaignActivation,
    *,
    confirm_activation_sha256: str,
    approved_by: str,
    approved_at: str,
) -> EvaluationCampaignActivation:
    """Attach an exact owner decision without changing the activation identity."""

    if activation.approval.approved:
        raise ValueError("campaign activation is already approved")
    if confirm_activation_sha256 != activation.activation_sha256:
        raise ValueError("campaign activation confirmation hash mismatch")
    return activation.model_copy(
        update={
            "approval": EvaluationCampaignActivationApproval(
                approved=True,
                approved_activation_sha256=activation.activation_sha256,
                approved_by=approved_by,
                approved_at=approved_at,
            )
        }
    )


def validate_evaluation_campaign_activation(
    activation: EvaluationCampaignActivation,
    plan: EvaluationCellPlan,
    *,
    project_id: str,
    evaluation_id: str,
) -> tuple[PlannedEvaluationCell, ...]:
    """Recompile an activation and reject any scope or ceiling drift."""

    expected = compile_evaluation_campaign_activation(
        plan,
        activation_id=activation.activation_id,
        project_id=project_id,
        evaluation_id=evaluation_id,
        task_ids=activation.selected_task_ids,
    )
    if (
        activation.project_id != project_id
        or activation.evaluation_id != evaluation_id
        or activation.proposal_sha256 != plan.proposal_sha256
        or activation.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("campaign activation binds another project, evaluation, or plan")
    if activation.model_dump(exclude={"approval"}) != expected.model_dump(exclude={"approval"}):
        raise ValueError("campaign activation scope or resource ceiling differs from its plan")
    return tuple(cell for cell in plan.cells if cell.cell_id in set(activation.selected_cell_ids))


def load_evaluation_campaign_activation(path: str | Path) -> EvaluationCampaignActivation:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("campaign activation must be a regular non-symlink file")
    raw = candidate.read_bytes()
    if not raw or len(raw) > _MAX_ACTIVATION_BYTES:
        raise ValueError("campaign activation has an invalid size")
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("campaign activation must contain UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("campaign activation root must be a mapping")
    serialized = payload.pop("activation_sha256", None)
    activation = EvaluationCampaignActivation.model_validate(payload)
    if serialized is not None and serialized != activation.activation_sha256:
        raise ValueError("campaign activation serialized hash mismatch")
    return activation


def save_evaluation_campaign_activation(
    activation: EvaluationCampaignActivation,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = activation.model_dump(mode="json")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _selected_task_block(
    plan: EvaluationCellPlan,
    task_ids: tuple[str, ...],
) -> tuple[PlannedEvaluationCell, ...]:
    requested = set(task_ids)
    known = {cell.task_id for cell in plan.cells}
    unknown = requested - known
    if not requested:
        raise ValueError("campaign activation selected no task")
    if unknown:
        raise ValueError("unknown activation tasks: " + ", ".join(sorted(unknown)))
    selected = tuple(cell for cell in plan.cells if cell.task_id in requested)
    ordered_tasks = _ordered_unique(cell.task_id for cell in selected)
    if tuple(task_ids) != ordered_tasks:
        raise ValueError("activation tasks must follow cell-plan order")
    return selected


def _ordered_unique(values) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    return tuple(dict.fromkeys(values))


__all__ = [
    "EvaluationCampaignActivation",
    "EvaluationCampaignActivationApproval",
    "approve_evaluation_campaign_activation",
    "compile_evaluation_campaign_activation",
    "load_evaluation_campaign_activation",
    "save_evaluation_campaign_activation",
    "validate_evaluation_campaign_activation",
]

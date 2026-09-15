"""Unified execution contract for training-free and training-based research workloads."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256, validate_entry_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class ResearchWorkloadParadigm(StrEnum):
    """Whether the scientific task executed by SciTaste updates task-model weights."""

    TRAINING_FREE = "training-free-research"
    TRAINING_BASED = "training-based-research"


class ResearchWorkloadContract(BaseModel):
    """Separate scientific-workload training from SciTaste's own Taste mechanism."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    task_id: str
    paradigm: ResearchWorkloadParadigm
    task_model_id: str | None = None
    task_model_weight_updates: bool
    task_model_initialization_sha256: str | None = Field(default=None, pattern=_SHA256)
    training_recipe_sha256: str | None = Field(default=None, pattern=_SHA256)
    candidate_checkpoint_required: bool
    scitaste_research_backbone_weight_updates: Literal[False] = False
    outcome_updated_taste_state_allowed: Literal[True] = True
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def training_semantics_are_closed(self) -> ResearchWorkloadContract:
        validate_entry_id(self.contract_id, field_name="research workload contract_id")
        validate_entry_id(self.task_id, field_name="research workload task_id")
        if self.paradigm is ResearchWorkloadParadigm.TRAINING_FREE:
            if self.task_model_weight_updates:
                raise ValueError("training-free workloads cannot update task-model weights")
            if self.training_recipe_sha256 is not None or self.candidate_checkpoint_required:
                raise ValueError(
                    "training-free workloads cannot require a training recipe or "
                    "candidate checkpoint"
                )
        else:
            if not self.task_model_weight_updates:
                raise ValueError("training-based workloads must update task-model weights")
            if (
                self.task_model_id is None
                or self.task_model_initialization_sha256 is None
                or self.training_recipe_sha256 is None
                or not self.candidate_checkpoint_required
            ):
                raise ValueError(
                    "training-based workloads require model, initialization, recipe, and checkpoint"
                )
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("research workload contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ResearchWorkloadContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


__all__ = ["ResearchWorkloadContract", "ResearchWorkloadParadigm"]

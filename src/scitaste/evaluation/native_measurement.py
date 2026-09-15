"""Cycle-free scorer-owned measurement contract for first-party benchmark cells."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256, validate_entry_id
from scitaste.taste.intervention import TasteInterventionCondition

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class NativeBenchmarkObjectiveMeasurement(BaseModel):
    """Raw task score retained outside the count-oriented study outcome."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    cell_id: str
    task_id: str
    condition_id: str
    outcome_status: Literal["measured", "itt_bounded_failure"] = "measured"
    frozen_candidate_sha256: str | None = Field(default=None, pattern=_SHA256)
    heldout_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    metric_name: str
    metric_direction: Literal["higher", "lower"]
    heldout_score: float | None = Field(default=None, allow_inf_nan=False)
    baseline_heldout_score: float = Field(allow_inf_nan=False)
    directed_progress: float = Field(allow_inf_nan=False)
    h4_execution_profile_sha256: str | None = Field(default=None, pattern=_SHA256)
    h4_arm_run_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    loop_result_sha256: str | None = Field(default=None, pattern=_SHA256)
    terminal_evidence_sha256: str | None = Field(default=None, pattern=_SHA256)
    lifecycle_policy_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    scorer_owned: Literal[True] = True
    model_invocations_after_freeze: Literal[0] = 0
    measurement_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def identity_and_hash_are_closed(self) -> NativeBenchmarkObjectiveMeasurement:
        validate_entry_id(self.cell_id, field_name="cell_id")
        validate_entry_id(self.task_id, field_name="task_id")
        validate_entry_id(self.condition_id, field_name="condition_id")
        h4_fields = (
            self.h4_execution_profile_sha256,
            self.h4_arm_run_request_sha256,
            self.terminal_evidence_sha256,
            self.lifecycle_policy_weight,
        )
        if self.schema_version == "1.0":
            if (
                self.outcome_status != "measured"
                or self.frozen_candidate_sha256 is None
                or self.heldout_receipt_sha256 is None
                or self.heldout_score is None
                or any(item is not None for item in h4_fields)
            ):
                raise ValueError("native benchmark legacy measurement fields differ")
        elif any(item is None for item in h4_fields):
            raise ValueError("native benchmark H4 measurement lacks its evidence chain")
        elif self.lifecycle_policy_weight != {
            TasteInterventionCondition.LEARNED_POLICY_ON.value: 1.0,
            TasteInterventionCondition.LEARNED_POLICY_OFF.value: 0.0,
        }.get(self.condition_id):
            raise ValueError("native benchmark H4 measurement condition and weight differ")
        if self.outcome_status == "measured":
            if (
                self.frozen_candidate_sha256 is None
                or self.heldout_receipt_sha256 is None
                or self.heldout_score is None
                or (self.schema_version == "1.1" and self.loop_result_sha256 is None)
            ):
                raise ValueError("measured native objective lacks held-out evidence")
            expected_progress = (
                self.heldout_score - self.baseline_heldout_score
                if self.metric_direction == "higher"
                else self.baseline_heldout_score - self.heldout_score
            )
            if abs(self.directed_progress - expected_progress) > 1e-12:
                raise ValueError("native benchmark directed progress mismatch")
        elif self.heldout_score is not None:
            raise ValueError("bounded H4 failure cannot report a measured held-out score")
        expected = content_sha256(_objective_measurement_hash_payload(self))
        if self.measurement_sha256 != expected:
            raise ValueError("native benchmark objective measurement hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> NativeBenchmarkObjectiveMeasurement:
        payload = {"schema_version": "1.0", **values}
        payload.pop("measurement_sha256", None)
        unsigned = cls.model_construct(measurement_sha256="0" * 64, **payload)
        digest = content_sha256(_objective_measurement_hash_payload(unsigned))
        return cls(**payload, measurement_sha256=digest)


def _objective_measurement_hash_payload(
    measurement: NativeBenchmarkObjectiveMeasurement,
) -> dict[str, object]:
    payload = measurement.model_dump(mode="json", exclude={"measurement_sha256"})
    if measurement.schema_version == "1.0":
        for field in (
            "outcome_status",
            "h4_execution_profile_sha256",
            "h4_arm_run_request_sha256",
            "loop_result_sha256",
            "terminal_evidence_sha256",
            "lifecycle_policy_weight",
        ):
            payload.pop(field)
    return payload


__all__ = ["NativeBenchmarkObjectiveMeasurement"]

"""Cheap diagnostic probe planning and interpretation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.state.research_state import ResearchObservation, WorkingHypothesis


class ProbeDisposition(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    INCONCLUSIVE = "inconclusive"


class ProbeSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation: str = Field(min_length=1)
    expected: bool
    reproducible: bool
    stability: float = Field(ge=0.0, le=1.0)
    effect_size: float | None = None
    boundary_conditions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)


class DiagnosticProbePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: str
    hypothesis_id: str
    probe_type: str
    objective: str
    falsifiable_prediction: str
    estimated_cost: dict[str, float] = Field(default_factory=dict)


class ProbeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: DiagnosticProbePlan
    observation: ResearchObservation
    disposition: ProbeDisposition
    informative: bool


class DiagnosticProbeAgent:
    def plan(
        self,
        hypothesis: WorkingHypothesis,
        *,
        probe_index: int,
        estimated_cost: dict[str, float] | None = None,
    ) -> DiagnosticProbePlan:
        if not hypothesis.falsifiable_predictions or not hypothesis.proposed_probe_types:
            raise ValueError("hypothesis is not sufficiently testable for a probe")
        return DiagnosticProbePlan(
            probe_id=f"probe-{probe_index:02d}-{hypothesis.hypothesis_id}",
            hypothesis_id=hypothesis.hypothesis_id,
            probe_type=hypothesis.proposed_probe_types[0],
            objective=f"Test whether: {hypothesis.falsifiable_predictions[0]}",
            falsifiable_prediction=hypothesis.falsifiable_predictions[0],
            estimated_cost=estimated_cost or {"experiments": 1.0, "gpu_hours": 0.1},
        )

    def assess(
        self,
        plan: DiagnosticProbePlan,
        result: ExecutionResult,
        signal: ProbeSignal,
    ) -> ProbeAssessment:
        if result.status != ExecutionStatus.SUCCEEDED:
            disposition = ProbeDisposition.INCONCLUSIVE
        elif not signal.reproducible or signal.stability < 0.6:
            disposition = ProbeDisposition.INCONCLUSIVE
        elif signal.expected:
            disposition = ProbeDisposition.SUPPORT
        else:
            disposition = ProbeDisposition.CONTRADICT
        observation = ResearchObservation(
            observation_id=f"obs-{plan.probe_id}",
            statement=signal.observation,
            source_result_id=result.result_id,
            hypothesis_id=plan.hypothesis_id,
            probe_type=plan.probe_type,
            reproducible=signal.reproducible,
            stability=signal.stability,
            expected=signal.expected,
            effect_size=signal.effect_size,
            boundary_conditions=signal.boundary_conditions,
            alternative_explanations=signal.alternative_explanations,
        )
        return ProbeAssessment(
            plan=plan,
            observation=observation,
            disposition=disposition,
            informative=disposition != ProbeDisposition.INCONCLUSIVE,
        )

"""Formation and evidence-aware updates for provisional hypotheses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.state.research_state import (
    ResearchIntuition,
    ResearchObservation,
    WorkingHypothesis,
    WorkingHypothesisStatus,
)


class HypothesisSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=1)
    falsifiable_predictions: list[str] = Field(min_length=1)
    proposed_probe_types: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def is_testable(self) -> HypothesisSeed:
        if not any(item.strip() for item in self.falsifiable_predictions):
            raise ValueError("a working hypothesis requires a falsifiable prediction")
        return self


class HypothesisAgent:
    def form_intuition(
        self,
        *,
        intuition_id: str,
        statement: str,
        source: str,
        supporting_context_ids: list[str],
        confidence: float,
    ) -> ResearchIntuition:
        return ResearchIntuition(
            intuition_id=intuition_id,
            statement=statement,
            source=source,
            supporting_context_ids=supporting_context_ids,
            confidence=confidence,
        )

    def form_working_hypothesis(
        self,
        *,
        hypothesis_id: str,
        seed: HypothesisSeed,
        intuition_ids: list[str],
        parent_hypothesis_ids: list[str] | None = None,
    ) -> WorkingHypothesis:
        return WorkingHypothesis(
            hypothesis_id=hypothesis_id,
            statement=seed.statement,
            derived_from_intuition_ids=intuition_ids,
            derived_from_hypothesis_ids=parent_hypothesis_ids or [],
            falsifiable_predictions=seed.falsifiable_predictions,
            proposed_probe_types=seed.proposed_probe_types,
            confidence=seed.confidence,
            status=(
                WorkingHypothesisStatus.REFINED
                if parent_hypothesis_ids
                else WorkingHypothesisStatus.PROVISIONAL
            ),
        )

    def incorporate_observation(
        self,
        hypothesis: WorkingHypothesis,
        observation: ResearchObservation,
    ) -> None:
        if observation.expected is False:
            hypothesis.contradicting_evidence_ids.append(observation.observation_id)
            hypothesis.status = WorkingHypothesisStatus.CONTRADICTED
            hypothesis.confidence = max(0.0, round(hypothesis.confidence * 0.25, 4))
        elif observation.expected is True and observation.reproducible:
            hypothesis.supporting_evidence_ids.append(observation.observation_id)
            hypothesis.status = WorkingHypothesisStatus.SUPPORTED
            stability = observation.stability or 0.5
            hypothesis.confidence = min(1.0, round(hypothesis.confidence + 0.35 * stability, 4))

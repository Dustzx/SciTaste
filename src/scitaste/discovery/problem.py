"""Convert stable observations into researchable problem statements."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.state.research_state import ResearchObservation, ResearchProblem


class ProblemSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation_gap: str = Field(min_length=1)
    importance: str = Field(min_length=1)


class ProblemFormationAgent:
    def form(
        self,
        *,
        problem_id: str,
        observations: list[ResearchObservation],
        seed: ProblemSeed,
    ) -> ResearchProblem:
        reproducible = [item for item in observations if item.reproducible]
        if not reproducible:
            raise ValueError("problem formation requires a reproducible observation")
        unexpected = [item for item in reproducible if item.expected is False]
        focal = max(unexpected or reproducible, key=lambda item: item.stability or 0.0)
        boundaries = sorted(
            {condition for item in reproducible for condition in item.boundary_conditions}
        )
        return ResearchProblem(
            problem_id=problem_id,
            observed_phenomenon=focal.statement,
            boundary_conditions=boundaries,
            explanation_gap=seed.explanation_gap,
            importance=seed.importance,
            reproducible=True,
            supporting_evidence_ids=[item.observation_id for item in reproducible],
        )

"""Turn stable contradictory pilot evidence into a new research direction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.discovery.ideas import IdeaSeed, MatureIdeaGenerator
from scitaste.discovery.problem import ProblemFormationAgent, ProblemSeed
from scitaste.state.research_state import ResearchIdea, ResearchObservation, ResearchProblem


class ContradictoryPilotEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pilot_id: str
    idea_id: str
    expected: str = Field(min_length=1)
    observed: str = Field(min_length=1)
    stable: bool
    stability: float = Field(ge=0.0, le=1.0)
    boundary_conditions: list[str] = Field(default_factory=list)
    explanation_gap: str = Field(min_length=1)
    importance: str = Field(min_length=1)
    literature_already_explains: bool = False

    @model_validator(mode="after")
    def is_a_real_contradiction(self) -> ContradictoryPilotEvidence:
        if self.expected.strip().casefold() == self.observed.strip().casefold():
            raise ValueError("pilot evidence is not contradictory")
        return self


class EvidenceBackedIdeationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected: str
    observed: str
    why_interesting: str
    observation: ResearchObservation
    problem: ResearchProblem
    idea: ResearchIdea


class EvidenceToIdeaEngine:
    def transform(
        self,
        evidence: ContradictoryPilotEvidence,
        *,
        idea_seed: IdeaSeed,
    ) -> EvidenceBackedIdeationResult:
        if not evidence.stable or evidence.stability < 0.6:
            raise ValueError("contradictory evidence must be stable before ideation")
        if evidence.literature_already_explains:
            raise ValueError("the contradiction is already explained by existing literature")
        observation = ResearchObservation(
            observation_id=f"obs-pilot-{evidence.pilot_id}",
            statement=evidence.observed,
            source_result_id=evidence.pilot_id,
            expected=False,
            reproducible=evidence.stable,
            stability=evidence.stability,
            boundary_conditions=evidence.boundary_conditions,
        )
        problem = ProblemFormationAgent().form(
            problem_id=f"problem-from-{evidence.pilot_id}",
            observations=[observation],
            seed=ProblemSeed(
                explanation_gap=evidence.explanation_gap,
                importance=evidence.importance,
            ),
        )
        idea = (
            MatureIdeaGenerator()
            .generate(
                problem=problem,
                observations=[observation],
                seeds=[idea_seed],
            )[0]
            .model_copy(update={"idea_id": f"idea-from-{evidence.pilot_id}"})
        )
        return EvidenceBackedIdeationResult(
            expected=evidence.expected,
            observed=evidence.observed,
            why_interesting=(
                "The stable pilot contradiction exposes a reproducible boundary that existing "
                "literature does not explain."
            ),
            observation=observation,
            problem=problem,
            idea=idea,
        )

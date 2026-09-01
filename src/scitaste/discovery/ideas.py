"""Style-normalized mature idea generation and portfolio construction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.state.research_state import (
    IdeaPortfolio,
    ResearchIdea,
    ResearchObservation,
    ResearchProblem,
)


class IdeaSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    proposed_mechanism: str = Field(min_length=1)
    expected_validation: list[str] = Field(min_length=1)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    expected_value: dict[str, float] = Field(default_factory=dict)
    main_risk: str = Field(min_length=1)


class MatureIdeaGenerator:
    """Generate first, then normalize every idea to the same evidence-bearing schema."""

    def generate(
        self,
        *,
        problem: ResearchProblem,
        observations: list[ResearchObservation],
        seeds: list[IdeaSeed],
    ) -> list[ResearchIdea]:
        if not seeds:
            raise ValueError("mature idea generation requires at least one divergent seed")
        evidence = "; ".join(item.statement for item in observations if item.reproducible)
        observation_ids = [item.observation_id for item in observations if item.reproducible]
        return [
            ResearchIdea(
                idea_id=f"idea-{index:02d}-{seed.generator.replace('_', '-')}",
                problem=problem.observed_phenomenon,
                observation_evidence=evidence,
                hypothesis=seed.hypothesis,
                proposed_mechanism=seed.proposed_mechanism,
                expected_validation=seed.expected_validation,
                expected_cost=seed.expected_cost,
                expected_value=seed.expected_value,
                main_risk=seed.main_risk,
                generator=seed.generator,
                source_problem_ids=[problem.problem_id],
                source_observation_ids=observation_ids,
            )
            for index, seed in enumerate(seeds, 1)
        ]


class IdeaPortfolioBuilder:
    def build(self, ideas: list[ResearchIdea], *, primary_idea_id: str) -> IdeaPortfolio:
        by_id = {idea.idea_id: idea for idea in ideas}
        if primary_idea_id not in by_id:
            raise ValueError("primary idea must belong to the candidate set")
        remaining = [idea for idea in ideas if idea.idea_id != primary_idea_id]
        low_risk = min(
            remaining,
            key=lambda idea: (
                idea.expected_cost.get("implementation_risk", 0.5),
                idea.expected_cost.get("gpu_hours", 0.0),
                idea.idea_id,
            ),
            default=None,
        )
        high_reward_pool = [idea for idea in remaining if idea is not low_risk]
        high_reward = max(
            high_reward_pool,
            key=lambda idea: (
                idea.expected_value.get("novelty", 0.0)
                + idea.expected_value.get("scientific_importance", 0.0),
                idea.idea_id,
            ),
            default=None,
        )
        reserved_backup_ids = {item.idea_id for item in (low_risk, high_reward) if item is not None}
        diagnostic = [
            idea.idea_id
            for idea in remaining
            if idea.generator in {"evaluation-centric", "diagnostic"}
            and idea.idea_id not in reserved_backup_ids
        ]
        reserved = {
            primary_idea_id,
            *reserved_backup_ids,
            *diagnostic,
        }
        return IdeaPortfolio(
            primary_idea_id=primary_idea_id,
            low_risk_backup_id=low_risk.idea_id if low_risk else None,
            high_risk_high_reward_id=high_reward.idea_id if high_reward else None,
            diagnostic_only_ids=diagnostic,
            dropped_ids=sorted(set(by_id) - reserved),
        )

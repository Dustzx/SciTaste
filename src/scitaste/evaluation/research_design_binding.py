"""Bind design comparisons to the existing campaign plan, not a second scheduler."""

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonSystems(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    treatment: str = Field(min_length=1)
    comparator: str = Field(min_length=1)

    @model_validator(mode="after")
    def different_systems(self):
        if self.treatment == self.comparator:
            raise ValueError("Comparison must bind distinct system identities")
        return self


class CampaignResearchDesignBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    design_locator: str
    design_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    study_id: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparisons: dict[str, ComparisonSystems] = Field(min_length=1)


def validate_research_design_binding(binding, *, project_root: Path, idea_sha256, plan):
    # Evaluation's public package imports this binding while design input models
    # import program_control. Load the proposal only at validation, not mid-import.
    from scitaste.model_nodes.research_design import ResearchDesignProposal

    root = project_root.resolve(strict=True)
    relative = Path(binding.design_locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Design locator must be project-relative")
    path = (root / relative).resolve(strict=True)
    path.relative_to(root)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding.design_sha256:
        raise ValueError("Campaign design changed")
    design = ResearchDesignProposal.model_validate_json(raw)
    if design.idea_sha256 != idea_sha256 or plan.plan_sha256 != binding.plan_sha256:
        raise ValueError("Campaign design targets a different idea or execution plan")
    study = next((item for item in design.studies if item.study_id == binding.study_id), None)
    if study is None or set(study.comparison_ids) != set(binding.comparisons):
        raise ValueError("Every study comparison must have exactly one system binding")
    known = {c.comparison_id for c in design.comparisons}
    if set(binding.comparisons) - known:
        raise ValueError("Unknown design comparison")
    for systems in binding.comparisons.values():
        groups = []
        for system in (systems.treatment, systems.comparator):
            cells = [c for c in plan.cells if c.system_id == system]
            keys = [(c.lane_id, c.task_id, c.seed, c.repetition) for c in cells]
            if not keys or len(keys) != len(set(keys)):
                raise ValueError("Comparison arm is absent or repeats a task/seed assignment")
            groups.append(set(keys))
        if groups[0] != groups[1]:
            raise ValueError("Comparison arms do not cover matched task/seed assignments")
    # Resource authorization, scorer provenance and primary outcomes remain
    # governed by the existing campaign/prelaunch contracts, not model prose.
    return study

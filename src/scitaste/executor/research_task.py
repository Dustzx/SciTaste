"""Task-specific inputs for a framework-independent bounded research workspace."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchToolTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    task_id: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    research_problem: str = Field(min_length=1)
    objective_direction: Literal["maximize", "minimize"]
    baseline_score: float | None = Field(default=None, allow_inf_nan=False)
    required_files: tuple[str, ...] = Field(min_length=1)
    writable_files: tuple[str, ...] = Field(min_length=1)
    execution_mode: Literal["cpu", "gpu", "api"]
    wall_seconds: int = Field(default=1200, ge=1, le=86400)
    max_experiments: Literal[1] = 1
    split_role: Literal["development"] = "development"

    @model_validator(mode="after")
    def paths_are_explicit(self):
        for names in (self.required_files, self.writable_files):
            if len(names) != len(set(names)):
                raise ValueError("task file paths must be unique")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
                    raise ValueError("task paths must be canonical relative files")
        if any(not name.endswith(".py") for name in self.writable_files):
            raise ValueError("this tool adapter currently supports Python source edits only")
        return self


class IterativeResearchToolTask(ResearchToolTask):
    """Explicit opt-in: legacy v1.0 tasks remain single-attempt contracts."""

    schema_version: Literal["1.1"] = "1.1"
    max_experiments: int = Field(ge=2, le=8)
    total_wall_seconds: int = Field(ge=60, le=86400)

    @model_validator(mode="after")
    def total_budget_is_explicit(self):
        if self.total_wall_seconds < self.wall_seconds:
            raise ValueError("total wall budget must cover the first attempt ceiling")
        return self

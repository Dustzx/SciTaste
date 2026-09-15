"""Idea- and related-work-first model candidate governance.

This catalog is intentionally upstream of resource inventory.  It records why a
model family belongs in an experiment before asking whether the project already
has a checkpoint or API credential.  The catalog does not select a formal model;
formal selection still requires task-excluded role conformance and an exact
identity receipt.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"

ModelPlane = Literal[
    "taste-impact-judge",
    "taste-ideator",
    "research-agent",
    "code-agent",
    "figure-reviewer",
    "paper-reviewer",
    "adjudicator",
    "embedding",
    "benchmark-task-model",
]


class RelatedWorkIdeaBinding(BaseModel):
    model_config = _CONFIG

    idea_revision_id: str
    locator: str
    sha256: str = Field(pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_repository_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("Idea binding must be repository relative")
        return path.as_posix()


class RelatedWorkModelAnchor(BaseModel):
    model_config = _CONFIG

    work_id: str
    title: str
    source_url: str
    relationship: Literal[
        "direct-scientific-taste-neighbor",
        "autoresearch-method",
        "autoresearch-benchmark",
    ]
    reported_models: tuple[str, ...] = Field(min_length=1, max_length=32)
    informs_planes: tuple[ModelPlane, ...] = Field(min_length=1)
    selection_implication: str = Field(min_length=20)

    @field_validator("source_url")
    @classmethod
    def source_is_public_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("related-work model anchors require an HTTPS primary source")
        return value


class RelatedWorkModelCandidate(BaseModel):
    model_config = _CONFIG

    candidate_id: str
    model_id: str
    model_family: str
    source_kind: Literal[
        "released-open-checkpoint",
        "hosted-api",
        "historical-reported-model",
        "benchmark-owned-model",
        "current-family-successor",
    ]
    planes: tuple[ModelPlane, ...] = Field(min_length=1)
    experimental_role: Literal[
        "external-neighbor-baseline",
        "primary-matched-candidate",
        "cross-model-robustness-candidate",
        "review-panel-candidate",
        "task-recipe-owned",
    ]
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)
    task_fit_rationale: str = Field(min_length=20)
    access_state: Literal[
        "available-exact",
        "available-exact-b0-passed",
        "available-exact-b0-passed-with-2048-token-envelope",
        "download-authorized-pending",
        "access-not-configured",
        "historical-comparability-only",
        "benchmark-runtime-bound",
    ]
    resource_locator: str | None = None
    exact_revision: str | None = None
    selection_state: Literal[
        "external-baseline-pending-execution",
        "task-excluded-conformance-pending",
        "task-excluded-conformance-passed-for-subset",
        "task-excluded-conformance-failed-for-role",
        "task-model-fixed-by-benchmark",
        "historical-context-only",
    ]
    availability_may_select_model: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_role_is_not_conflated(self) -> RelatedWorkModelCandidate:
        if "benchmark-task-model" in self.planes and len(self.planes) != 1:
            raise ValueError("benchmark task models cannot also act as scientific agents")
        if "scijudge" in self.model_family.casefold() and any(
            plane in self.planes for plane in ("paper-reviewer", "adjudicator")
        ):
            raise ValueError("impact prediction is not full-paper peer review")
        if self.access_state.startswith("available-exact") and self.resource_locator is None:
            raise ValueError("available exact candidates require a resource locator")
        if self.source_kind == "benchmark-owned-model" and (
            self.selection_state != "task-model-fixed-by-benchmark"
            or self.access_state != "benchmark-runtime-bound"
        ):
            raise ValueError("benchmark-owned models must remain task-recipe-owned")
        return self


class RelatedWorkRoleRequirement(BaseModel):
    model_config = _CONFIG

    plane: ModelPlane
    minimum_distinct_families: int = Field(ge=1, le=8)
    required_experimental_roles: tuple[
        Literal[
            "external-neighbor-baseline",
            "primary-matched-candidate",
            "cross-model-robustness-candidate",
            "review-panel-candidate",
            "task-recipe-owned",
        ],
        ...,
    ] = Field(min_length=1)


class RelatedWorkModelCatalog(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"]
    catalog_id: str
    refreshed_at: str
    idea: RelatedWorkIdeaBinding
    candidate_universe_authority: Literal[
        "frozen-idea-then-direct-neighbors-then-autoresearch-conventions"
    ]
    resource_inventory_role: Literal["feasibility-and-cost-tiebreak-only"]
    selection_data: Literal["source-disjoint-task-excluded-conformance-only"]
    formal_model_selected: Literal[False] = False
    selection_order: tuple[
        Literal[
            "freeze-idea-and-causal-roles",
            "admit-direct-neighbor-and-autoresearch-model-evidence",
            "construct-role-specific-candidate-universe-without-access-filter",
            "test-source-disjoint-task-fit-and-reliability",
            "bind-exact-identity-license-and-serving-window",
            "use-resource-cost-and-throughput-only-as-tiebreakers",
        ],
        ...,
    ]
    anchors: tuple[RelatedWorkModelAnchor, ...] = Field(min_length=4)
    candidates: tuple[RelatedWorkModelCandidate, ...] = Field(min_length=8)
    role_requirements: tuple[RelatedWorkRoleRequirement, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def catalog_is_idea_and_evidence_driven(self) -> RelatedWorkModelCatalog:
        expected_order = (
            "freeze-idea-and-causal-roles",
            "admit-direct-neighbor-and-autoresearch-model-evidence",
            "construct-role-specific-candidate-universe-without-access-filter",
            "test-source-disjoint-task-fit-and-reliability",
            "bind-exact-identity-license-and-serving-window",
            "use-resource-cost-and-throughput-only-as-tiebreakers",
        )
        if self.selection_order != expected_order:
            raise ValueError("model selection must end, not start, with resource preference")

        anchor_ids = {item.work_id for item in self.anchors}
        direct_neighbors = {
            item.work_id
            for item in self.anchors
            if item.relationship == "direct-scientific-taste-neighbor"
        }
        if len(direct_neighbors) < 2:
            raise ValueError("model catalog requires at least two direct Taste neighbors")
        for candidate in self.candidates:
            if not set(candidate.evidence_anchor_ids).issubset(anchor_ids):
                raise ValueError(f"unknown evidence anchor for {candidate.candidate_id}")

        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("model candidate IDs must be unique")

        requirements = {item.plane: item for item in self.role_requirements}
        for plane, requirement in requirements.items():
            eligible = [item for item in self.candidates if plane in item.planes]
            families = {item.model_family for item in eligible}
            roles = {item.experimental_role for item in eligible}
            if len(families) < requirement.minimum_distinct_families:
                raise ValueError(f"insufficient model-family coverage for {plane}")
            if not set(requirement.required_experimental_roles).issubset(roles):
                raise ValueError(f"missing experimental model role for {plane}")

        if all(item.access_state.startswith("available-exact") for item in self.candidates):
            raise ValueError("candidate universe appears improperly restricted to inventory")
        return self


class RelatedWorkModelCatalogSummary(BaseModel):
    model_config = _CONFIG

    catalog_id: str
    catalog_sha256: str = Field(pattern=_SHA256)
    formal_model_selected: Literal[False]
    candidate_count: int
    model_family_count: int
    direct_neighbor_count: int
    candidates_by_plane: dict[str, tuple[str, ...]]
    unresolved_access_candidates: tuple[str, ...]
    selection_blockers: tuple[str, ...]


def load_related_work_model_catalog(
    path: str | Path,
) -> tuple[RelatedWorkModelCatalog, str]:
    source = Path(path)
    raw = source.read_bytes()
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("related-work model catalog root must be a mapping")
    return RelatedWorkModelCatalog.model_validate(payload), hashlib.sha256(raw).hexdigest()


def summarize_related_work_model_catalog(
    catalog: RelatedWorkModelCatalog,
    *,
    catalog_sha256: str,
) -> RelatedWorkModelCatalogSummary:
    by_plane: dict[str, tuple[str, ...]] = {}
    for requirement in catalog.role_requirements:
        by_plane[requirement.plane] = tuple(
            item.candidate_id for item in catalog.candidates if requirement.plane in item.planes
        )
    unresolved = tuple(
        item.candidate_id
        for item in catalog.candidates
        if item.access_state in {"access-not-configured", "download-authorized-pending"}
    )
    return RelatedWorkModelCatalogSummary(
        catalog_id=catalog.catalog_id,
        catalog_sha256=catalog_sha256,
        formal_model_selected=False,
        candidate_count=len(catalog.candidates),
        model_family_count=len({item.model_family for item in catalog.candidates}),
        direct_neighbor_count=sum(
            item.relationship == "direct-scientific-taste-neighbor" for item in catalog.anchors
        ),
        candidates_by_plane=by_plane,
        unresolved_access_candidates=unresolved,
        selection_blockers=(
            "source-disjoint-role-conformance-not-complete",
            "exact-primary-serving-identities-not-frozen",
            "independent-review-panel-not-qualified",
        ),
    )


__all__ = [
    "RelatedWorkIdeaBinding",
    "RelatedWorkModelAnchor",
    "RelatedWorkModelCandidate",
    "RelatedWorkModelCatalog",
    "RelatedWorkModelCatalogSummary",
    "RelatedWorkRoleRequirement",
    "load_related_work_model_catalog",
    "summarize_related_work_model_catalog",
]

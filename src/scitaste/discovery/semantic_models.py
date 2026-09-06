"""Dependency-light data contracts for bounded Discovery semantics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.discovery.hypothesis import HypothesisSeed
from scitaste.discovery.landscape import LandscapeFinding
from scitaste.state.research_state import ResearchObservation, WorkingHypothesis

DISCOVERY_HYPOTHESIS_NODE = "discovery-hypothesis"
DISCOVERY_REFORMULATION_NODE = "discovery-reformulation"
DISCOVERY_SEMANTIC_NODES = (
    DISCOVERY_HYPOTHESIS_NODE,
    DISCOVERY_REFORMULATION_NODE,
)
DEFAULT_PROBE_TYPES = (
    "ablation",
    "benchmark",
    "counterexample",
    "reproduction",
    "sanity-check",
    "sensitivity-analysis",
)


class DiscoverySemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryHypothesisInput(DiscoverySemanticModel):
    """Only the registered project identity and bounded landscape reach the model."""

    schema_version: Literal["1.0"] = "1.0"
    research_direction: str = Field(min_length=1, max_length=4_000)
    target_domain: str = Field(min_length=1, max_length=500)
    target_venue: str | None = Field(default=None, max_length=500)
    landscape_findings: tuple[LandscapeFinding, ...] = Field(min_length=1, max_length=40)
    permitted_probe_types: tuple[str, ...] = Field(
        default=DEFAULT_PROBE_TYPES,
        min_length=1,
        max_length=20,
    )

    @field_validator("permitted_probe_types")
    @classmethod
    def probe_types_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values)
        if any(not item or len(item) > 100 for item in normalized):
            raise ValueError("permitted probe types must be non-blank and at most 100 characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("permitted probe types must be unique")
        return tuple(sorted(normalized))

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    source_id
                    for finding in self.landscape_findings
                    for source_id in finding.source_ids
                }
            )
        )


class DiscoveryIntuitionProposal(DiscoverySemanticModel):
    statement: str = Field(min_length=1, max_length=4_000)
    supporting_source_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("supporting_source_ids")
    @classmethod
    def sources_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("supporting source identifiers must be unique")
        return tuple(sorted(values))


class DiscoveryHypothesisProposal(DiscoverySemanticModel):
    """Data-only scientific proposal; it carries no action or execution field."""

    schema_version: Literal["1.0"] = "1.0"
    intuition: DiscoveryIntuitionProposal
    hypothesis: HypothesisSeed
    alternative_explanations: tuple[str, ...] = Field(min_length=1, max_length=5)
    uncertainty: str = Field(min_length=1, max_length=2_000)

    @field_validator("alternative_explanations")
    @classmethod
    def alternatives_are_distinct(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        stripped = tuple(item.strip() for item in values)
        if any(not item or len(item) > 2_000 for item in stripped):
            raise ValueError("alternative explanations must be non-blank and bounded")
        if len({item.casefold() for item in stripped}) != len(stripped):
            raise ValueError("alternative explanations must be distinct")
        return stripped

    @model_validator(mode="after")
    def intuition_and_hypothesis_are_distinct(self) -> DiscoveryHypothesisProposal:
        intuition = self.intuition.statement.strip().casefold()
        hypothesis = self.hypothesis.statement.strip().casefold()
        if intuition == hypothesis:
            raise ValueError("intuition and working hypothesis must not be identical")
        return self


class DiscoveryReformulationInput(DiscoverySemanticModel):
    """Contradictory state evidence visible to one bounded reformulation call."""

    schema_version: Literal["1.0"] = "1.0"
    research_direction: str = Field(min_length=1, max_length=4_000)
    target_domain: str = Field(min_length=1, max_length=500)
    target_venue: str | None = Field(default=None, max_length=500)
    parent_hypothesis: WorkingHypothesis
    observations: tuple[ResearchObservation, ...] = Field(min_length=1, max_length=40)
    permitted_probe_types: tuple[str, ...] = Field(
        default=DEFAULT_PROBE_TYPES,
        min_length=1,
        max_length=20,
    )

    @field_validator("observations")
    @classmethod
    def observations_are_unique(
        cls,
        values: tuple[ResearchObservation, ...],
    ) -> tuple[ResearchObservation, ...]:
        identifiers = [item.observation_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reformulation observation identifiers must be unique")
        return values

    @field_validator("permitted_probe_types")
    @classmethod
    def probe_types_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return DiscoveryHypothesisInput.probe_types_are_bounded_and_unique(values)

    @model_validator(mode="after")
    def includes_parent_contradiction(self) -> DiscoveryReformulationInput:
        observed = {item.observation_id for item in self.observations}
        if not observed.intersection(self.parent_hypothesis.contradicting_evidence_ids):
            raise ValueError("reformulation requires a registered parent contradiction")
        return self

    @property
    def observation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.observation_id for item in self.observations))


class DiscoveryReformulationProposal(DiscoverySemanticModel):
    """Evidence-linked replacement hypothesis without transition authority."""

    schema_version: Literal["1.0"] = "1.0"
    hypothesis: HypothesisSeed
    supporting_observation_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    retained_constraints: tuple[str, ...] = Field(min_length=1, max_length=8)
    alternative_explanations: tuple[str, ...] = Field(min_length=1, max_length=5)
    uncertainty: str = Field(min_length=1, max_length=2_000)

    @field_validator("supporting_observation_ids")
    @classmethod
    def observation_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("supporting observation identifiers must be unique")
        return tuple(sorted(values))

    @field_validator("retained_constraints", "alternative_explanations")
    @classmethod
    def bounded_text_is_distinct(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        stripped = tuple(item.strip() for item in values)
        if any(not item or len(item) > 2_000 for item in stripped):
            raise ValueError("reformulation text items must be non-blank and bounded")
        if len({item.casefold() for item in stripped}) != len(stripped):
            raise ValueError("reformulation text items must be distinct")
        return stripped


class DiscoverySemanticReference(DiscoverySemanticModel):
    """Content binding from a discovery state to one accepted runtime proposal."""

    schema_version: Literal["1.0"] = "1.0"
    node_name: Literal["discovery-hypothesis", "discovery-reformulation"]
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ledger_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recording_locator: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    recovered_without_provider: bool = False
    advisory_only: Literal[True] = True
    executable: Literal[False] = False


__all__ = [
    "DEFAULT_PROBE_TYPES",
    "DISCOVERY_HYPOTHESIS_NODE",
    "DISCOVERY_REFORMULATION_NODE",
    "DISCOVERY_SEMANTIC_NODES",
    "DiscoveryHypothesisInput",
    "DiscoveryHypothesisProposal",
    "DiscoveryIntuitionProposal",
    "DiscoveryReformulationInput",
    "DiscoveryReformulationProposal",
    "DiscoverySemanticReference",
]

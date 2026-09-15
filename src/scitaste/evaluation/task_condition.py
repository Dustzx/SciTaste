"""Content-bound guidance compilation for native benchmark-research conditions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.benchmark.models import MechanismContextBundle
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_relative_locator,
)
from scitaste.taste.conditions import (
    NativeConditionId,
    NativeConditionMatrixInspection,
    NativeConfirmatoryCondition,
    NativeLifecycleCondition,
    NativeTasteCondition,
    NativeTasteRetrievalMode,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_GUIDANCE_BYTES = 1_048_576


class BenchmarkGuidanceArtifact(BaseModel):
    """One reviewed input channel; entries carry no model or execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    guidance_id: str
    channel: Literal["utility", "knowledge", "taste", "critic"]
    taste_relation: Literal["not-applicable", "matched", "mismatched"]
    source_locator: str = Field(min_length=1, max_length=1_000)
    source_sha256: str = Field(pattern=_SHA256)
    derivation_receipt_locator: str = Field(min_length=1, max_length=1_000)
    derivation_receipt_sha256: str = Field(pattern=_SHA256)
    entries: tuple[str, ...] = Field(min_length=1, max_length=32)
    outcome_information_available: Literal[False] = False
    advisory_only: Literal[True] = True

    @field_validator("source_locator", "derivation_receipt_locator")
    @classmethod
    def locators_are_safe(cls, value: str, info: object) -> str:
        return validate_relative_locator(
            value,
            field_name=str(getattr(info, "field_name", "guidance locator")),
        )

    @model_validator(mode="after")
    def identity_and_relation_are_consistent(self) -> BenchmarkGuidanceArtifact:
        validate_entry_id(self.guidance_id, field_name="guidance_id")
        if len(self.entries) != len(set(self.entries)):
            raise ValueError("benchmark guidance entries must be unique")
        if any(not entry or len(entry) > 2_000 for entry in self.entries):
            raise ValueError("benchmark guidance entries must be non-empty and bounded")
        if self.channel == "taste":
            if self.taste_relation == "not-applicable":
                raise ValueError("Taste guidance requires a corpus relation")
        elif self.taste_relation != "not-applicable":
            raise ValueError("only Taste guidance can declare a corpus relation")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class BenchmarkResearchGuidanceSet(BaseModel):
    """The common registered input pool from which every native condition is compiled."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    guidance_set_id: str
    condition_matrix_sha256: str = Field(pattern=_SHA256)
    condition_matrix_fingerprint: str = Field(pattern=_SHA256)
    corpus_pair_report_sha256: str = Field(pattern=_SHA256)
    utility: BenchmarkGuidanceArtifact
    knowledge: BenchmarkGuidanceArtifact
    matched_taste: BenchmarkGuidanceArtifact
    mismatched_taste: BenchmarkGuidanceArtifact
    critic: BenchmarkGuidanceArtifact
    mechanism_context: MechanismContextBundle | None = None

    @model_validator(mode="after")
    def complete_channels_are_distinct(self) -> BenchmarkResearchGuidanceSet:
        validate_entry_id(self.guidance_set_id, field_name="guidance_set_id")
        identities = (
            (self.utility.channel, self.utility.taste_relation),
            (self.knowledge.channel, self.knowledge.taste_relation),
            (self.matched_taste.channel, self.matched_taste.taste_relation),
            (self.mismatched_taste.channel, self.mismatched_taste.taste_relation),
            (self.critic.channel, self.critic.taste_relation),
        )
        expected = (
            ("utility", "not-applicable"),
            ("knowledge", "not-applicable"),
            ("taste", "matched"),
            ("taste", "mismatched"),
            ("critic", "not-applicable"),
        )
        if identities != expected:
            raise ValueError("benchmark guidance set does not contain the exact five channels")
        artifact_ids = (
            self.utility.guidance_id,
            self.knowledge.guidance_id,
            self.matched_taste.guidance_id,
            self.mismatched_taste.guidance_id,
            self.critic.guidance_id,
        )
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("benchmark guidance artifact IDs must be unique")
        if (
            self.matched_taste.source_locator == self.mismatched_taste.source_locator
            or self.matched_taste.source_sha256 == self.mismatched_taste.source_sha256
        ):
            raise ValueError("matched and mismatched Taste guidance sources must be disjoint")
        if self.schema_version == "1.0":
            if self.mechanism_context is not None:
                raise ValueError("guidance schema 1.0 cannot carry a formal mechanism context")
            return self
        if self.mechanism_context is None:
            raise ValueError("guidance schema 1.1 requires a formal mechanism context")
        context = self.mechanism_context
        expected_entries = {
            "knowledge": (context.raw_source_rag.rendered_context,),
            "matched_taste": (context.matched_abstracted_taste.rendered_context,),
            "mismatched_taste": (context.mismatched_taste.rendered_context,),
        }
        for field, expected in expected_entries.items():
            if getattr(self, field).entries != expected:
                raise ValueError(
                    "formal mechanism guidance must expose the exact token-accounted context"
                )
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class BenchmarkResearchConditionGuidance(BaseModel):
    """Exact condition projection consumed by one autonomous task loop."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    condition_id: NativeConditionId
    condition_matrix_fingerprint: str = Field(pattern=_SHA256)
    guidance_set_sha256: str = Field(pattern=_SHA256)
    utility_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    knowledge_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    taste_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    critic_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    artifact_sha256: dict[str, str] = Field(max_length=5)

    @model_validator(mode="after")
    def component_presence_matches_condition(self) -> BenchmarkResearchConditionGuidance:
        present = {
            "utility": bool(self.utility_guidance),
            "knowledge": bool(self.knowledge_guidance),
            "taste": bool(self.taste_guidance),
            "critic": bool(self.critic_guidance),
        }
        expected = {
            NativeTasteCondition.BASE: (False, False, False, False),
            NativeTasteCondition.KNOWLEDGE: (False, True, False, False),
            NativeTasteCondition.TASTE: (True, False, True, False),
            NativeTasteCondition.CRITICS: (False, False, False, True),
            NativeTasteCondition.FULL: (True, True, True, True),
            NativeTasteCondition.MISMATCHED_PLACEBO: (True, True, True, True),
            NativeConfirmatoryCondition.RAW_SOURCE_RAG: (False, True, False, False),
            NativeConfirmatoryCondition.MATCHED_ABSTRACTED_TASTE: (
                False,
                False,
                True,
                False,
            ),
            NativeConfirmatoryCondition.MISMATCHED_TASTE: (False, False, True, False),
            NativeLifecycleCondition.LEARNED_POLICY_ON: (True, True, True, True),
            NativeLifecycleCondition.LEARNED_POLICY_OFF: (True, True, True, True),
        }[self.condition_id]
        if tuple(present.values()) != expected:
            raise ValueError("benchmark condition guidance does not match its component matrix")
        if set(self.artifact_sha256) != {name for name, enabled in present.items() if enabled}:
            raise ValueError("benchmark condition artifact bindings do not match its guidance")
        if any(not value or not _is_sha256(value) for value in self.artifact_sha256.values()):
            raise ValueError("benchmark condition artifact binding is invalid")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


def compile_benchmark_condition_guidance(
    matrix: NativeConditionMatrixInspection,
    guidance: BenchmarkResearchGuidanceSet,
    condition: str | NativeConditionId,
) -> BenchmarkResearchConditionGuidance:
    """Project one guidance pool through a closed diagnostic or confirmatory matrix."""

    if guidance.condition_matrix_sha256 != matrix.file_sha256:
        raise ValueError("benchmark guidance set binds another condition-matrix file")
    if guidance.condition_matrix_fingerprint != matrix.matrix.fingerprint:
        raise ValueError("benchmark guidance set binds another condition matrix")
    if (matrix.matrix.schema_version in {"1.1", "1.2"}) != (guidance.schema_version == "1.1"):
        raise ValueError("formal condition matrix and mechanism guidance schema must match")
    profile = matrix.matrix.profile(condition)
    components = profile.components
    selected: dict[str, BenchmarkGuidanceArtifact] = {}
    if components.utility_policy_enabled:
        selected["utility"] = guidance.utility
    if components.knowledge_retrieval_enabled:
        selected["knowledge"] = guidance.knowledge
    if components.taste_retrieval is NativeTasteRetrievalMode.MATCHED:
        selected["taste"] = guidance.matched_taste
    elif components.taste_retrieval is NativeTasteRetrievalMode.MISMATCHED:
        selected["taste"] = guidance.mismatched_taste
    if components.taste_critics_enabled:
        selected["critic"] = guidance.critic
    return BenchmarkResearchConditionGuidance(
        condition_id=profile.condition_id,
        condition_matrix_fingerprint=matrix.matrix.fingerprint,
        guidance_set_sha256=guidance.fingerprint,
        utility_guidance=_entries(selected, "utility"),
        knowledge_guidance=_entries(selected, "knowledge"),
        taste_guidance=_entries(selected, "taste"),
        critic_guidance=_entries(selected, "critic"),
        artifact_sha256={name: artifact.fingerprint for name, artifact in selected.items()},
    )


def load_benchmark_research_guidance_set(
    path: str | Path,
) -> BenchmarkResearchGuidanceSet:
    """Load one bounded JSON/YAML guidance set without reading referenced source bodies."""

    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_GUIDANCE_BYTES:
        raise ValueError("benchmark research guidance set must be a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
        rendered = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("benchmark research guidance set is invalid") from exc
    return BenchmarkResearchGuidanceSet.model_validate_json(rendered, strict=True)


def _entries(
    selected: dict[str, BenchmarkGuidanceArtifact],
    channel: str,
) -> tuple[str, ...]:
    artifact = selected.get(channel)
    return artifact.entries if artifact is not None else ()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "BenchmarkGuidanceArtifact",
    "BenchmarkResearchConditionGuidance",
    "BenchmarkResearchGuidanceSet",
    "compile_benchmark_condition_guidance",
    "load_benchmark_research_guidance_set",
]

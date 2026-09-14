"""Executable component contracts for the native Scientific Taste study."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.backends.base import CandidateGenerationBackend, PreferenceBackend
from scitaste.data.store import TasteLibrary
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.retriever import TasteDomainRelation, TasteRetriever

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_MAX_CONFIG_BYTES = 256 * 1024


class NativeTasteCondition(StrEnum):
    """Legacy six-arm integration/diagnostic condition identifiers."""

    BASE = "native-base"
    KNOWLEDGE = "native-knowledge"
    TASTE = "native-taste"
    CRITICS = "native-critics"
    FULL = "full-scitaste"
    MISMATCHED_PLACEBO = "mismatched-taste-placebo"


class NativeConfirmatoryCondition(StrEnum):
    """Reference treatments needed to identify the formal H1/H2 mechanisms."""

    RAW_SOURCE_RAG = "raw-source-rag"
    MATCHED_ABSTRACTED_TASTE = "matched-abstracted-taste"
    MISMATCHED_TASTE = "mismatched-taste"


NativeConditionId = NativeTasteCondition | NativeConfirmatoryCondition


class NativeTasteRetrievalMode(StrEnum):
    DISABLED = "disabled"
    MATCHED = "matched"
    MISMATCHED = "mismatched"


class NativeConditionRole(StrEnum):
    BUNDLE_CONTROL = "bundle_control"
    COMPONENT_SUFFICIENCY = "component_sufficiency"
    FULL_SYSTEM = "full_system"
    MATCHED_PLACEBO = "matched_placebo"
    REPRESENTATION_CONTROL = "representation_control"
    MECHANISM_TREATMENT = "mechanism_treatment"


class NativeConditionComponents(BaseModel):
    model_config = _CONFIG

    utility_policy_enabled: bool
    knowledge_retrieval_enabled: bool
    taste_retrieval: NativeTasteRetrievalMode
    taste_critics_enabled: bool
    integrity_gates_enabled: Literal[True] = True


class NativeConditionProfile(BaseModel):
    model_config = _CONFIG

    condition_id: NativeConditionId
    role: NativeConditionRole
    components: NativeConditionComponents


_EXPECTED_PROFILES: dict[
    NativeTasteCondition,
    tuple[NativeConditionRole, bool, bool, NativeTasteRetrievalMode, bool],
] = {
    NativeTasteCondition.BASE: (
        NativeConditionRole.BUNDLE_CONTROL,
        False,
        False,
        NativeTasteRetrievalMode.DISABLED,
        False,
    ),
    NativeTasteCondition.KNOWLEDGE: (
        NativeConditionRole.COMPONENT_SUFFICIENCY,
        False,
        True,
        NativeTasteRetrievalMode.DISABLED,
        False,
    ),
    NativeTasteCondition.TASTE: (
        NativeConditionRole.COMPONENT_SUFFICIENCY,
        True,
        False,
        NativeTasteRetrievalMode.MATCHED,
        False,
    ),
    NativeTasteCondition.CRITICS: (
        NativeConditionRole.COMPONENT_SUFFICIENCY,
        False,
        False,
        NativeTasteRetrievalMode.DISABLED,
        True,
    ),
    NativeTasteCondition.FULL: (
        NativeConditionRole.FULL_SYSTEM,
        True,
        True,
        NativeTasteRetrievalMode.MATCHED,
        True,
    ),
    NativeTasteCondition.MISMATCHED_PLACEBO: (
        NativeConditionRole.MATCHED_PLACEBO,
        True,
        True,
        NativeTasteRetrievalMode.MISMATCHED,
        True,
    ),
}

_EXPECTED_CONFIRMATORY_PROFILES: dict[
    NativeConditionId,
    tuple[NativeConditionRole, bool, bool, NativeTasteRetrievalMode, bool],
] = {
    NativeTasteCondition.BASE: _EXPECTED_PROFILES[NativeTasteCondition.BASE],
    NativeConfirmatoryCondition.RAW_SOURCE_RAG: (
        NativeConditionRole.REPRESENTATION_CONTROL,
        False,
        True,
        NativeTasteRetrievalMode.DISABLED,
        False,
    ),
    NativeConfirmatoryCondition.MATCHED_ABSTRACTED_TASTE: (
        NativeConditionRole.MECHANISM_TREATMENT,
        False,
        False,
        NativeTasteRetrievalMode.MATCHED,
        False,
    ),
    NativeConfirmatoryCondition.MISMATCHED_TASTE: (
        NativeConditionRole.MATCHED_PLACEBO,
        False,
        False,
        NativeTasteRetrievalMode.MISMATCHED,
        False,
    ),
    NativeTasteCondition.FULL: _EXPECTED_PROFILES[NativeTasteCondition.FULL],
}


class NativeConditionMatrix(BaseModel):
    """A closed legacy-diagnostic or formal-confirmatory condition matrix.

    Schema 1.0 preserves the original six-arm integration/diagnostic matrix.
    Schema 1.1 is the five-arm formal matrix: Raw RAG versus matched abstracted
    Taste changes representation over identical sources, matched versus
    mismatched Taste changes source-domain relation, and Full versus Base tests
    the complete Scientific Taste bundle.
    """

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    matrix_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    profiles: tuple[NativeConditionProfile, ...] = Field(min_length=5, max_length=6)
    component_only_effect_claims_forbidden: Literal[True] = True

    @model_validator(mode="after")
    def exact_scientific_matrix(self) -> NativeConditionMatrix:
        by_id = {profile.condition_id: profile for profile in self.profiles}
        expected_profiles = (
            _EXPECTED_PROFILES if self.schema_version == "1.0" else _EXPECTED_CONFIRMATORY_PROFILES
        )
        if len(by_id) != len(self.profiles) or set(by_id) != set(expected_profiles):
            label = "legacy six-arm" if self.schema_version == "1.0" else "confirmatory five-arm"
            raise ValueError(f"native condition matrix must contain the exact {label} set")
        for condition_id, expected in expected_profiles.items():
            profile = by_id[condition_id]
            observed = (
                profile.role,
                profile.components.utility_policy_enabled,
                profile.components.knowledge_retrieval_enabled,
                profile.components.taste_retrieval,
                profile.components.taste_critics_enabled,
            )
            if observed != expected:
                raise ValueError(f"native condition profile drift: {condition_id.value}")
        if self.schema_version == "1.0":
            full = by_id[NativeTasteCondition.FULL].components
            placebo = by_id[NativeTasteCondition.MISMATCHED_PLACEBO].components
            if full.model_copy(update={"taste_retrieval": placebo.taste_retrieval}) != placebo:
                raise ValueError(
                    "mismatched placebo may differ from Full only by Taste corpus relation"
                )
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))

    def profile(self, condition: str | NativeConditionId) -> NativeConditionProfile:
        try:
            condition_id: NativeConditionId = NativeTasteCondition(condition)
        except ValueError:
            condition_id = NativeConfirmatoryCondition(condition)
        return next(item for item in self.profiles if item.condition_id is condition_id)


class NativeConditionMatrixInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    matrix: NativeConditionMatrix


@dataclass(frozen=True)
class NativeConditionRuntime:
    profile: NativeConditionProfile
    controller: TasteController
    taste_retriever: TasteRetriever | None

    @property
    def model_backed(self) -> bool:
        return self.controller.preference_backend is not None

    @property
    def model_backed_candidate_generation(self) -> bool:
        return self.controller.candidate_generation_backend is not None

    @property
    def knowledge_retrieval_enabled(self) -> bool:
        return self.profile.components.knowledge_retrieval_enabled

    @property
    def taste_context_enabled(self) -> bool:
        return self.taste_retriever is not None


def load_native_condition_matrix(path: str | Path) -> NativeConditionMatrixInspection:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("native condition matrix cannot be a symbolic link")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("native condition matrix must be a regular file")
    if source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("native condition matrix exceeds the byte ceiling")
    raw = source.read_bytes()
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ValueError("native condition matrix exceeds the byte ceiling")
    payload = yaml.safe_load(raw) or {}
    if not isinstance(payload, dict):
        raise ValueError("native condition matrix root must be a mapping")
    return NativeConditionMatrixInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        matrix=NativeConditionMatrix.model_validate(payload),
    )


def build_native_condition_runtime(
    profile: NativeConditionProfile,
    *,
    seed: int,
    taste_library: TasteLibrary | None,
    preference_backend: PreferenceBackend | None = None,
    expected_preference_backend: str | None = None,
    expected_preference_model: str | None = None,
    candidate_generation_backend: CandidateGenerationBackend | None = None,
    expected_candidate_generation_backend: str | None = None,
    expected_candidate_generation_model: str | None = None,
) -> NativeConditionRuntime:
    mode = profile.components.taste_retrieval
    retriever: TasteRetriever | None = None
    if mode is not NativeTasteRetrievalMode.DISABLED:
        if taste_library is None or len(taste_library) == 0:
            raise ValueError(f"{profile.condition_id.value} requires a non-empty Taste Library")
        relation = (
            TasteDomainRelation.MATCHED
            if mode is NativeTasteRetrievalMode.MATCHED
            else TasteDomainRelation.MISMATCHED
        )
        retriever = TasteRetriever(taste_library, domain_relation=relation)
    controller = TasteController(
        seed=seed,
        mode=(TasteMode.AUGMENTED if retriever is not None else TasteMode.INTRINSIC),
        retriever=retriever,
        utility_enabled=profile.components.utility_policy_enabled,
        critics_enabled=profile.components.taste_critics_enabled,
        preference_backend=preference_backend,
        expected_preference_backend=expected_preference_backend,
        expected_preference_model=expected_preference_model,
        candidate_generation_backend=candidate_generation_backend,
        expected_candidate_generation_backend=expected_candidate_generation_backend,
        expected_candidate_generation_model=expected_candidate_generation_model,
    )
    return NativeConditionRuntime(
        profile=profile,
        controller=controller,
        taste_retriever=retriever,
    )


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "NativeConditionComponents",
    "NativeConditionId",
    "NativeConditionMatrix",
    "NativeConditionMatrixInspection",
    "NativeConditionProfile",
    "NativeConditionRole",
    "NativeConditionRuntime",
    "NativeConfirmatoryCondition",
    "NativeTasteCondition",
    "NativeTasteRetrievalMode",
    "build_native_condition_runtime",
    "load_native_condition_matrix",
]

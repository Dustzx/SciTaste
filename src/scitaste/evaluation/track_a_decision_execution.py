"""Bounded Track-A decision execution and AI-only preference-panel handoff."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.ai_preference_execution import (
    AIPreferenceHTTPResponse,
    AIPreferenceHTTPTransport,
    HttpxAIPreferenceTransport,
)
from scitaste.evaluation.ai_preference_panel import (
    AIPreferenceFileBinding,
    AIPreferencePrimaryRequest,
    AIPreferenceRequestItem,
    AIPreferenceRequestPack,
    AIPreferenceVisibleDecision,
    AIReviewUsage,
    load_ai_blind_preference_protocol,
)
from scitaste.evaluation.human_outcomes import (
    BlindedHumanComparison,
    BlindedOutputBinding,
    HumanBlindKey,
    HumanBlindKeyEntry,
    HumanOutcomeStudyManifest,
    HumanStudyFileBinding,
    HumanStudyTreatmentCommitment,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    TreatmentGenerationLedger,
    TreatmentGenerationRecord,
)
from scitaste.evaluation.human_study_preparation import BlindedDecisionArtifact
from scitaste.evaluation.taste_mechanism_suite import (
    TrackAArmExecutionConfig,
    TrackAModelVisibleRequest,
    TrackAPilotSuiteManifest,
    TrackASuiteArmRecord,
    TrackASuiteCaseRecord,
    TrackATargetPrompt,
)
from scitaste.model_nodes.models import ModelCostProvenance

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 256 * 1_048_576
_PLANNED_CASE_COUNT = 24
_PLANNED_CALL_COUNT = 72
_CONDITIONS = (
    "raw-source-rag",
    "abstracted-matched-taste",
    "abstracted-mismatched-taste",
)
_FORBIDDEN_PROVIDER_LABELS = (
    b"raw-source-rag",
    b"abstracted-matched-taste",
    b"abstracted-mismatched-taste",
    b"same-source-raw-rag",
    b"matched-abstracted-taste",
    b"source-disjoint-mismatched-taste",
)


class TrackADecisionFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> TrackADecisionFileBinding:
        pure = PurePosixPath(self.path)
        if (
            pure.is_absolute()
            or not pure.parts
            or pure.as_posix() != self.path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("Track-A file binding must be normalized and relative")
        return self


class TrackAInputTokenCount(BaseModel):
    """Exact pre-execution tokenizer evidence for one model-visible request."""

    model_config = _CONFIG

    request_sha256: str = Field(pattern=_SHA256)
    tokenizer_id: str = Field(min_length=1, max_length=300)
    tokenizer_revision: str = Field(min_length=1, max_length=300)
    input_tokens: int = Field(gt=0)
    token_sequence_sha256: str = Field(pattern=_SHA256)
    token_trace: TrackADecisionFileBinding


class TrackATokenizerTemplateArguments(BaseModel):
    """Pinned arguments that affect the official GLM chat-template rendering."""

    model_config = _CONFIG

    add_generation_prompt: Literal[True] = True
    tools: None = None
    reasoning_effort: Literal["max"] = "max"
    clear_thinking: Literal[False] = False
    add_special_tokens: Literal[False] = False


class TrackATokenizerAssetAttestation(BaseModel):
    """One locally verified file from the pinned official tokenizer snapshot."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    bytes: int = Field(gt=0, le=_MAX_INPUT_BYTES)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> TrackATokenizerAssetAttestation:
        pure = PurePosixPath(self.path)
        if (
            pure.is_absolute()
            or not pure.parts
            or pure.as_posix() != self.path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("Track-A tokenizer asset path must be normalized and relative")
        return self


class TrackATokenizerSourceConfig(BaseModel):
    model_config = _CONFIG

    repository: str = Field(
        min_length=3,
        max_length=300,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_on: date
    source_url: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def source_url_binds_revision(self) -> TrackATokenizerSourceConfig:
        expected = f"https://huggingface.co/{self.repository}/tree/{self.revision}"
        if self.source_url != expected:
            raise ValueError("Track-A tokenizer source URL does not bind its HF revision")
        return self


class TrackATokenizerSnapshotConfig(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    payload_bytes: int = Field(gt=0, le=_MAX_INPUT_BYTES)
    files: tuple[TrackATokenizerAssetAttestation, ...] = Field(min_length=4, max_length=32)

    @model_validator(mode="after")
    def snapshot_is_closed(self) -> TrackATokenizerSnapshotConfig:
        root = Path(self.path)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("Track-A tokenizer snapshot path must be absolute and normalized")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("Track-A tokenizer snapshot repeats an asset")
        if sum(item.bytes for item in self.files) != self.payload_bytes:
            raise ValueError("Track-A tokenizer snapshot byte total drifted")
        return self


class TrackATokenizerLoadingConfig(BaseModel):
    model_config = _CONFIG

    library: Literal["transformers"] = "transformers"
    library_revision: str = Field(min_length=1, max_length=100)
    implementation: Literal["PreTrainedTokenizerFast"] = "PreTrainedTokenizerFast"
    tokenizer_file: str = Field(min_length=1, max_length=300)
    chat_template_file: str = Field(min_length=1, max_length=300)
    add_generation_prompt: Literal[True] = True
    tools: None = None
    reasoning_effort: Literal["max"] = "max"
    clear_thinking: Literal[False] = False
    add_special_tokens: Literal[False] = False
    trust_remote_code: Literal[False] = False
    load_verified: Literal[True] = True
    verified_on: date

    @model_validator(mode="after")
    def loader_paths_are_relative(self) -> TrackATokenizerLoadingConfig:
        for value in (self.tokenizer_file, self.chat_template_file):
            pure = PurePosixPath(value)
            if (
                pure.is_absolute()
                or not pure.parts
                or pure.as_posix() != value
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise ValueError("Track-A tokenizer loader paths must be normalized and relative")
        return self


class TrackATokenizerUseConfig(BaseModel):
    model_config = _CONFIG

    selected_for: Literal["scitastebench-track-a-natural-pilot-input-accounting"]
    exact_for_pinned_local_template: Literal[True] = True
    provider_serving_build_attested: Literal[False] = False
    formal_provider_token_equivalence_claim_allowed: Literal[False] = False
    note: str = Field(min_length=1, max_length=4_000)


class TrackATokenizerMaterializationConfig(BaseModel):
    """Strict, secret-free declaration of one local tokenizer implementation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    tokenizer_config_id: str = Field(pattern=_ID)
    model: str = Field(min_length=1, max_length=300)
    model_family: str = Field(min_length=1, max_length=300)
    source: TrackATokenizerSourceConfig
    local_snapshot: TrackATokenizerSnapshotConfig
    loading: TrackATokenizerLoadingConfig
    use: TrackATokenizerUseConfig

    @model_validator(mode="after")
    def model_family_is_the_source(self) -> TrackATokenizerMaterializationConfig:
        if self.model_family != self.source.repository:
            raise ValueError("Track-A tokenizer model family differs from its HF source")
        family_leaf = self.model_family.rsplit("/", 1)[-1].casefold()
        if family_leaf != self.model.casefold():
            raise ValueError("Track-A tokenizer HF model differs from its API model alias")
        assets = {item.path for item in self.local_snapshot.files}
        required = {
            self.loading.tokenizer_file,
            self.loading.chat_template_file,
            "tokenizer_config.json",
            "config.json",
        }
        if not required.issubset(assets):
            raise ValueError("Track-A tokenizer snapshot omits a required pinned file")
        return self

    @computed_field
    @property
    def config_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"config_sha256"}))


class TrackAInputTokenTrace(BaseModel):
    """Exact tokenizer output used to authorize one call."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "2.0"] = "1.0"
    request_sha256: str = Field(pattern=_SHA256)
    tokenizer_id: str = Field(min_length=1, max_length=300)
    tokenizer_revision: str = Field(min_length=1, max_length=300)
    prompt_template_revision: str = Field(min_length=1, max_length=300)
    add_special_tokens: bool
    token_ids: tuple[int, ...] = Field(min_length=1, max_length=262_144)
    token_sequence_sha256: str = Field(pattern=_SHA256)
    provider_payload_sha256: str | None = Field(default=None, pattern=_SHA256)
    provider_messages_sha256: str | None = Field(default=None, pattern=_SHA256)
    provider_request_identity_sha256: str | None = Field(default=None, pattern=_SHA256)
    rendered_prompt_sha256: str | None = Field(default=None, pattern=_SHA256)
    rendered_prompt_bytes: int | None = Field(default=None, gt=0, le=_MAX_INPUT_BYTES)
    tokenizer_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    chat_template_sha256: str | None = Field(default=None, pattern=_SHA256)
    template_arguments: TrackATokenizerTemplateArguments | None = None

    @model_validator(mode="after")
    def sequence_is_self_hashed(self) -> TrackAInputTokenTrace:
        if self.token_sequence_sha256 != _canonical_sha256(list(self.token_ids)):
            raise ValueError("Track-A input token sequence hash mismatch")
        v2_values = (
            self.provider_payload_sha256,
            self.provider_messages_sha256,
            self.provider_request_identity_sha256,
            self.rendered_prompt_sha256,
            self.rendered_prompt_bytes,
            self.tokenizer_config_sha256,
            self.chat_template_sha256,
            self.template_arguments,
        )
        if self.schema_version == "2.0" and any(item is None for item in v2_values):
            raise ValueError("Track-A v2 token trace lacks exact rendering evidence")
        if self.schema_version == "1.0" and any(item is not None for item in v2_values):
            raise ValueError("Track-A v1 token trace cannot contain v2 rendering evidence")
        return self


class TrackAInputTokenManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "2.0"] = "1.0"
    token_manifest_id: str = Field(pattern=_ID)
    suite_manifest_sha256: str = Field(pattern=_SHA256)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    prompt_template_revision: str = Field(min_length=1, max_length=300)
    counts: tuple[TrackAInputTokenCount, ...] = Field(min_length=3, max_length=72)
    all_requests_measured_before_execution: Literal[True] = True
    backend_config: TrackADecisionFileBinding | None = None
    backend_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    tokenizer_config: TrackADecisionFileBinding | None = None
    tokenizer_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    tokenizer_repository: str | None = Field(default=None, min_length=1, max_length=300)
    tokenizer_assets: tuple[TrackATokenizerAssetAttestation, ...] | None = None
    tokenizer_snapshot_path: str | None = Field(default=None, min_length=1, max_length=2_000)
    tokenizer_library: str | None = Field(default=None, min_length=1, max_length=100)
    tokenizer_library_revision: str | None = Field(default=None, min_length=1, max_length=100)
    tokenizer_implementation: str | None = Field(default=None, min_length=1, max_length=200)
    chat_template_sha256: str | None = Field(default=None, pattern=_SHA256)
    template_arguments: TrackATokenizerTemplateArguments | None = None
    exact_for_pinned_local_template: bool | None = None
    provider_serving_build_attested: bool | None = None
    formal_provider_token_equivalence_claim_allowed: bool | None = None
    observed_api_usage_receipt_is_authoritative: bool | None = None
    natural_pilot_only: bool | None = None

    @model_validator(mode="after")
    def requests_are_unique(self) -> TrackAInputTokenManifest:
        if len({item.request_sha256 for item in self.counts}) != len(self.counts):
            raise ValueError("Track-A token manifest repeats a request")
        v2_values = (
            self.backend_config,
            self.backend_config_sha256,
            self.tokenizer_config,
            self.tokenizer_config_sha256,
            self.tokenizer_repository,
            self.tokenizer_assets,
            self.tokenizer_snapshot_path,
            self.tokenizer_library,
            self.tokenizer_library_revision,
            self.tokenizer_implementation,
            self.chat_template_sha256,
            self.template_arguments,
            self.exact_for_pinned_local_template,
            self.provider_serving_build_attested,
            self.formal_provider_token_equivalence_claim_allowed,
            self.observed_api_usage_receipt_is_authoritative,
            self.natural_pilot_only,
        )
        if self.schema_version == "2.0":
            if any(item is None for item in v2_values):
                raise ValueError("Track-A v2 token manifest lacks tokenizer provenance")
            if (
                self.exact_for_pinned_local_template is not True
                or self.provider_serving_build_attested is not False
                or self.formal_provider_token_equivalence_claim_allowed is not False
                or self.observed_api_usage_receipt_is_authoritative is not True
                or self.natural_pilot_only is not True
            ):
                raise ValueError("Track-A v2 tokenizer claim boundary is unsafe")
        elif any(item is not None for item in v2_values):
            raise ValueError("Track-A v1 token manifest cannot contain v2 provenance")
        return self

    @computed_field
    @property
    def token_manifest_sha256(self) -> str:
        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"token_manifest_sha256"},
                exclude_none=self.schema_version == "1.0",
            )
        )


class TrackADecisionCallBudget(BaseModel):
    model_config = _CONFIG

    max_request_bytes: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    max_latency_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def total_is_bounded(self) -> TrackADecisionCallBudget:
        if self.max_total_tokens > self.max_input_tokens + self.max_output_tokens:
            raise ValueError("Track-A call total exceeds input plus output ceilings")
        return self


class TrackADecisionExecutionBudget(BaseModel):
    """Exact all-or-nothing resource envelope for the eligible subset."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    budget_id: str = Field(pattern=_ID)
    expected_eligible_call_count: int = Field(gt=0, le=72)
    maximum_calls: int = Field(gt=0, le=72)
    per_call: TrackADecisionCallBudget
    max_total_tokens: int = Field(gt=0)
    max_total_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    max_retries: Literal[0] = 0
    failure_policy: Literal["terminal-no-resume-no-resample"] = "terminal-no-resume-no-resample"

    @model_validator(mode="after")
    def aggregate_is_bounded(self) -> TrackADecisionExecutionBudget:
        if self.maximum_calls != self.expected_eligible_call_count:
            raise ValueError("Track-A maximum calls must equal eligible frozen calls")
        if self.per_call.max_total_tokens * self.maximum_calls > self.max_total_tokens:
            raise ValueError("Track-A reserved calls exceed aggregate token budget")
        if self.per_call.max_cost_usd * self.maximum_calls > self.max_total_cost_usd + 1e-12:
            raise ValueError("Track-A reserved calls exceed aggregate cost budget")
        return self

    @computed_field
    @property
    def budget_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"budget_sha256"}))


class TrackADecisionBackendConfig(BaseModel):
    """Secret-free OpenAI-compatible endpoint configuration."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    config_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2_000)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    api_key_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    live_enabled: bool = False
    timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    max_retries: Literal[0] = 0
    pricing: ModelCostProvenance

    @model_validator(mode="after")
    def endpoint_is_safe(self) -> TrackADecisionBackendConfig:
        parsed = urlparse(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
            raise ValueError("Track-A endpoint must use HTTPS except localhost")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError("Track-A endpoint cannot contain credentials or a query")
        return self

    @computed_field
    @property
    def model_identity_sha256(self) -> str:
        return _canonical_sha256(
            {
                "provider": self.provider,
                "model": self.model,
                "model_revision": self.model_revision,
            }
        )

    @computed_field
    @property
    def config_sha256(self) -> str:
        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"config_sha256", "model_identity_sha256"},
            )
        )


class TrackADecisionCall(BaseModel):
    """Opaque public call identity; condition remains in controller evidence only."""

    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=72)
    call_id: str = Field(pattern=_ID)
    model_request_sha256: str = Field(pattern=_SHA256)
    http_request: TrackADecisionFileBinding
    input_token_count: int = Field(gt=0)
    token_sequence_sha256: str = Field(pattern=_SHA256)
    token_trace: TrackADecisionFileBinding
    parameter_profile_sha256: str = Field(pattern=_SHA256)
    condition_label_absent_from_http_request: Literal[True] = True


class TrackADecisionBatch(BaseModel):
    """No-call batch for the suite's eligible coverage-aware subset."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    batch_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    suite_manifest: TrackADecisionFileBinding
    suite_manifest_sha256: str = Field(pattern=_SHA256)
    backend_config: TrackADecisionFileBinding
    backend_config_sha256: str = Field(pattern=_SHA256)
    execution_budget: TrackADecisionFileBinding
    execution_budget_sha256: str = Field(pattern=_SHA256)
    token_manifest: TrackADecisionFileBinding
    token_manifest_sha256: str = Field(pattern=_SHA256)
    model_identity_sha256: str = Field(pattern=_SHA256)
    parameter_profile_sha256: str = Field(pattern=_SHA256)
    planned_case_count: Literal[24] = 24
    eligible_case_count: int = Field(gt=0, le=24)
    excluded_or_unmaterialized_case_count: int = Field(ge=0, le=24)
    planned_call_count: Literal[72] = 72
    eligible_call_count: int = Field(gt=0, le=72)
    calls: tuple[TrackADecisionCall, ...] = Field(min_length=3, max_length=72)
    full_planned_population_materialized: bool
    complete_triplet_for_each_eligible_case: Literal[True] = True
    condition_identity_absent_from_http_requests: Literal[True] = True
    same_model_and_parameters_for_every_arm: Literal[True] = True
    missing_cases_will_not_be_resampled: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def coverage_is_honest(self) -> TrackADecisionBatch:
        if self.excluded_or_unmaterialized_case_count != (
            self.planned_case_count - self.eligible_case_count
        ):
            raise ValueError("Track-A case coverage counts disagree")
        if self.eligible_call_count != self.eligible_case_count * 3:
            raise ValueError("Track-A eligible calls must be three per eligible case")
        if len(self.calls) != self.eligible_call_count:
            raise ValueError("Track-A public calls differ from eligible call count")
        if self.full_planned_population_materialized != (
            self.eligible_case_count == self.planned_case_count
        ):
            raise ValueError("Track-A full-population flag differs from coverage")
        if [item.ordinal for item in self.calls] != list(range(1, len(self.calls) + 1)):
            raise ValueError("Track-A call ordinals must be contiguous")
        if len({item.call_id for item in self.calls}) != len(self.calls):
            raise ValueError("Track-A call IDs must be unique")
        if len({item.model_request_sha256 for item in self.calls}) != len(self.calls):
            raise ValueError("Track-A model requests must be unique")
        if any(
            item.parameter_profile_sha256 != self.parameter_profile_sha256 for item in self.calls
        ):
            raise ValueError("Track-A calls do not share one parameter profile")
        return self

    @computed_field
    @property
    def batch_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"batch_sha256"}))


class TrackADecisionPreparation(BaseModel):
    model_config = _CONFIG

    output_dir: Path
    batch_path: Path
    batch: TrackADecisionBatch


@dataclass(frozen=True)
class TrackATokenManifestMaterialization:
    output_dir: Path
    manifest_path: Path
    manifest: TrackAInputTokenManifest


class TrackARawDecision(BaseModel):
    model_config = _CONFIG

    selected_action_id: Literal["option-a", "option-b", "abstain"]
    abstained: bool
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def abstention_is_consistent(self) -> TrackARawDecision:
        if self.abstained != (self.selected_action_id == "abstain"):
            raise ValueError("Track-A selected action and abstention flag disagree")
        return self


class TrackADecisionExecutionReceipt(BaseModel):
    """One exact, successful, zero-retry model call."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=_ID)
    call_id: str = Field(pattern=_ID)
    model_request_sha256: str = Field(pattern=_SHA256)
    batch: TrackADecisionFileBinding
    batch_sha256: str = Field(pattern=_SHA256)
    backend_config: TrackADecisionFileBinding
    backend_config_sha256: str = Field(pattern=_SHA256)
    execution_budget: TrackADecisionFileBinding
    execution_budget_sha256: str = Field(pattern=_SHA256)
    http_request: TrackADecisionFileBinding
    raw_http_body: TrackADecisionFileBinding
    raw_response: TrackADecisionFileBinding
    provider: str = Field(min_length=1, max_length=200)
    requested_model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    provider_reported_model: str = Field(min_length=1, max_length=300)
    model_identity_sha256: str = Field(pattern=_SHA256)
    parameter_profile_sha256: str = Field(pattern=_SHA256)
    provider_request_id: str = Field(min_length=1, max_length=1_000)
    started_at: datetime
    completed_at: datetime
    http_status: int = Field(ge=200, lt=300)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    usage: AIReviewUsage
    max_retries: Literal[0] = 0
    semantic_attempts: Literal[1] = 1
    replacement_or_resample_call: Literal[False] = False
    model_call_observed: Literal[True] = True

    @model_validator(mode="after")
    def timestamps_are_coherent(self) -> TrackADecisionExecutionReceipt:
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("Track-A receipt timestamps must include a timezone")
        if self.completed_at < self.started_at:
            raise ValueError("Track-A receipt completion precedes its start")
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class TrackADecisionObservation(BaseModel):
    """Controller-private condition mapping for one completed decision."""

    model_config = _CONFIG

    observation_id: str = Field(pattern=_ID)
    call_id: str = Field(pattern=_ID)
    target_id: str = Field(pattern=_ID)
    target_source_group_id: str = Field(pattern=_ID)
    condition: Literal["raw-source-rag", "abstracted-matched-taste", "abstracted-mismatched-taste"]
    model_request_sha256: str = Field(pattern=_SHA256)
    selected_action_id: Literal["option-a", "option-b", "abstain"]
    abstained: bool
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=4_000)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    execution_receipt: TrackADecisionFileBinding
    execution_receipt_sha256: str = Field(pattern=_SHA256)
    recorded_at: datetime
    source_observed_action_is_natural_proxy_not_truth: Literal[True] = True
    objective_correctness_claim_allowed: Literal[False] = False
    observation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def observation_is_coherent(self) -> TrackADecisionObservation:
        if self.recorded_at.utcoffset() is None:
            raise ValueError("Track-A observation timestamp must include a timezone")
        if self.abstained != (self.selected_action_id == "abstain"):
            raise ValueError("Track-A observation action and abstention disagree")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"observation_sha256"}))
        if self.observation_sha256 != expected:
            raise ValueError("Track-A observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TrackADecisionObservation:
        payload = dict(values)
        payload.pop("observation_sha256", None)
        unsigned = cls.model_construct(observation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            observation_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"observation_sha256"})
            ),
        )


class TrackADecisionCompletedCall(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=72)
    call_id: str = Field(pattern=_ID)
    model_request_sha256: str = Field(pattern=_SHA256)
    receipt: TrackADecisionFileBinding
    receipt_sha256: str = Field(pattern=_SHA256)
    observation_sha256: str = Field(pattern=_SHA256)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)


class TrackADecisionRun(BaseModel):
    """Successful all-or-nothing eligible-subset execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=_ID)
    batch: TrackADecisionFileBinding
    batch_sha256: str = Field(pattern=_SHA256)
    private_recording: TrackADecisionFileBinding
    planned_case_count: Literal[24] = 24
    eligible_case_count: int = Field(gt=0, le=24)
    executed_case_count: int = Field(gt=0, le=24)
    planned_call_count: Literal[72] = 72
    eligible_call_count: int = Field(gt=0, le=72)
    executed_call_count: int = Field(gt=0, le=72)
    completed: tuple[TrackADecisionCompletedCall, ...] = Field(min_length=3, max_length=72)
    total_tokens: int = Field(ge=0)
    total_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    started_at: datetime
    completed_at: datetime
    max_retries: Literal[0] = 0
    failure_policy: Literal["terminal-no-resume-no-resample"] = "terminal-no-resume-no-resample"
    missing_or_failed_cases_resampled: Literal[False] = False
    partial_recording_admissible: Literal[False] = False
    all_calls_use_one_model_identity: Literal[True] = True
    all_calls_use_one_parameter_profile: Literal[True] = True
    condition_identity_absent_from_http_requests: Literal[True] = True

    @model_validator(mode="after")
    def execution_counts_are_honest(self) -> TrackADecisionRun:
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("Track-A run timestamps must include a timezone")
        if self.completed_at < self.started_at:
            raise ValueError("Track-A run completion precedes its start")
        if not (
            self.executed_case_count == self.eligible_case_count
            and self.eligible_call_count == self.executed_call_count
            and self.executed_call_count == len(self.completed)
            and self.executed_call_count == self.executed_case_count * 3
        ):
            raise ValueError("Track-A successful run must cover every eligible case triplet")
        if [item.ordinal for item in self.completed] != list(range(1, len(self.completed) + 1)):
            raise ValueError("Track-A completed call ordinals must be contiguous")
        if len({item.call_id for item in self.completed}) != len(self.completed):
            raise ValueError("Track-A successful run repeats a call identity")
        if self.total_tokens != sum(item.total_tokens for item in self.completed):
            raise ValueError("Track-A run token total differs from completed calls")
        if abs(self.total_cost_usd - sum(item.cost_usd for item in self.completed)) > 1e-12:
            raise ValueError("Track-A run cost total differs from completed calls")
        return self

    @computed_field
    @property
    def run_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"run_sha256"}))


class TrackAAIPreferenceBridgeReport(BaseModel):
    """No-call handoff from completed decisions to the existing AI-only panel."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    bridge_id: str = Field(pattern=_ID)
    decision_run: TrackADecisionFileBinding
    decision_run_sha256: str = Field(pattern=_SHA256)
    private_recording: TrackADecisionFileBinding
    public_study: TrackADecisionFileBinding
    private_blind_key: TrackADecisionFileBinding
    private_generation_ledger: TrackADecisionFileBinding
    study_sha256: str = Field(pattern=_SHA256)
    ai_preference_pack: TrackADecisionFileBinding
    ai_preference_pack_sha256: str = Field(pattern=_SHA256)
    planned_case_count: Literal[24] = 24
    eligible_case_count: int = Field(gt=0, le=24)
    executed_case_count: int = Field(gt=0, le=24)
    excluded_or_unmaterialized_case_count: int = Field(ge=0, le=24)
    planned_decision_call_count: Literal[72] = 72
    eligible_decision_call_count: int = Field(gt=0, le=72)
    executed_decision_call_count: int = Field(gt=0, le=72)
    ai_primary_request_count: Literal[2] = 2
    ai_adjudicator_policy: Literal["disputed-only"] = "disputed-only"
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    source_observed_action_is_natural_proxy_not_truth: Literal[True] = True
    objective_correctness_claim_allowed: Literal[False] = False
    model_calls_performed_by_bridge: Literal[False] = False
    authorizes_additional_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def counts_are_honest(self) -> TrackAAIPreferenceBridgeReport:
        if self.excluded_or_unmaterialized_case_count != (
            self.planned_case_count - self.eligible_case_count
        ):
            raise ValueError("Track-A bridge case coverage counts disagree")
        if not (
            self.executed_case_count == self.eligible_case_count
            and self.eligible_decision_call_count == self.executed_decision_call_count
            and self.executed_decision_call_count == self.executed_case_count * 3
        ):
            raise ValueError("Track-A bridge may expose only a complete eligible execution")
        return self

    @computed_field
    @property
    def bridge_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"bridge_sha256"}))


@dataclass(frozen=True)
class _ProviderResponse:
    provider_model: str
    provider_request_id: str
    content: str
    usage: dict[str, object]


def load_track_a_decision_backend_config(path: str | Path) -> TrackADecisionBackendConfig:
    return TrackADecisionBackendConfig.model_validate(
        _load_mapping(Path(path), "Track-A backend config")
    )


def load_track_a_tokenizer_materialization_config(
    path: str | Path,
) -> TrackATokenizerMaterializationConfig:
    return TrackATokenizerMaterializationConfig.model_validate(
        _load_mapping(Path(path), "Track-A tokenizer materialization config")
    )


def load_track_a_decision_budget(path: str | Path) -> TrackADecisionExecutionBudget:
    return TrackADecisionExecutionBudget.model_validate(
        _load_mapping(Path(path), "Track-A execution budget")
    )


def load_track_a_input_token_manifest(path: str | Path) -> TrackAInputTokenManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Track-A token manifest must be a JSON object")
    recorded = payload.pop("token_manifest_sha256", None)
    manifest = TrackAInputTokenManifest.model_validate(payload)
    if recorded != manifest.token_manifest_sha256:
        raise ValueError("Track-A token manifest semantic hash mismatch")
    return manifest


def materialize_track_a_input_token_manifest(
    *,
    evidence_root: str | Path,
    suite_manifest_path: str | Path,
    backend_config_path: str | Path,
    tokenizer_config_path: str | Path,
    output_dir: str | Path,
) -> TrackATokenManifestMaterialization:
    """Render and freeze exact local-template token IDs without any model call."""

    root = Path(evidence_root).resolve(strict=True)
    suite_file = _regular_file(root, suite_manifest_path)
    backend_file = _regular_file(root, backend_config_path)
    tokenizer_config_file = _regular_file(root, tokenizer_config_path)
    target = _new_target(root, output_dir)
    suite = _load_suite_manifest(suite_file)
    backend = load_track_a_decision_backend_config(backend_file)
    tokenizer_config = load_track_a_tokenizer_materialization_config(tokenizer_config_file)
    arm_configs = _verify_suite(root, suite_file, suite)
    if not suite.natural_pilot or suite.study_mode != "natural-ai-pilot":
        raise ValueError("Pinned GLM tokenizer manifest is authorized only for a natural pilot")
    if (suite.provider, suite.model) != (backend.provider, backend.model):
        raise ValueError("Track-A tokenizer input suite differs from its backend")
    if tokenizer_config.model != suite.model:
        raise ValueError("Track-A tokenizer model differs from suite/backend model")
    snapshot = _verify_tokenizer_snapshot(tokenizer_config)
    tokenizer = _load_pinned_fast_tokenizer(tokenizer_config, snapshot)
    template = snapshot / tokenizer_config.loading.chat_template_file
    template_sha256 = _sha256(template)
    template_revision = f"hf-{tokenizer_config.source.revision}-template-{template_sha256[:16]}"
    arguments = TrackATokenizerTemplateArguments()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        counts: list[TrackAInputTokenCount] = []
        for case in suite.cases:
            for arm in case.arms:
                execution = arm_configs[arm.model_request_sha256]
                payload = _provider_payload(execution.model_visible_request)
                messages = payload.get("messages")
                if not isinstance(messages, list):
                    raise ValueError("Track-A provider payload does not expose chat messages")
                rendered = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    tools=None,
                    reasoning_effort="max",
                    clear_thinking=False,
                )
                token_ids = tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    tools=None,
                    reasoning_effort="max",
                    clear_thinking=False,
                )
                if not isinstance(rendered, str) or not rendered:
                    raise ValueError("Track-A chat template produced no rendered prompt")
                if (
                    not isinstance(token_ids, list)
                    or not token_ids
                    or not all(isinstance(item, int) and item >= 0 for item in token_ids)
                ):
                    raise ValueError("Track-A chat template produced invalid token IDs")
                replay_ids = tokenizer.encode(rendered, add_special_tokens=False)
                if token_ids != replay_ids:
                    raise ValueError("Track-A tokenizer trace does not replay rendered prompt")
                if len(token_ids) > execution.model_visible_request.maximum_input_tokens:
                    raise ValueError("Track-A rendered prompt exceeds its request token ceiling")
                payload_sha256 = _canonical_sha256(payload)
                messages_sha256 = _canonical_sha256(messages)
                request_identity_sha256 = _canonical_sha256(
                    {
                        "model_visible_request_sha256": arm.model_request_sha256,
                        "provider_payload_sha256": payload_sha256,
                        "provider_messages_sha256": messages_sha256,
                    }
                )
                sequence_sha256 = _canonical_sha256(token_ids)
                trace = TrackAInputTokenTrace(
                    schema_version="2.0",
                    request_sha256=arm.model_request_sha256,
                    tokenizer_id=tokenizer_config.model_family,
                    tokenizer_revision=tokenizer_config.source.revision,
                    prompt_template_revision=template_revision,
                    add_special_tokens=False,
                    token_ids=tuple(token_ids),
                    token_sequence_sha256=sequence_sha256,
                    provider_payload_sha256=payload_sha256,
                    provider_messages_sha256=messages_sha256,
                    provider_request_identity_sha256=request_identity_sha256,
                    rendered_prompt_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                    rendered_prompt_bytes=len(rendered.encode("utf-8")),
                    tokenizer_config_sha256=tokenizer_config.config_sha256,
                    chat_template_sha256=template_sha256,
                    template_arguments=arguments,
                )
                relative = Path("traces") / f"{arm.model_request_sha256}.json"
                _write_json(workspace / relative, trace.model_dump(mode="json"))
                counts.append(
                    TrackAInputTokenCount(
                        request_sha256=arm.model_request_sha256,
                        tokenizer_id=tokenizer_config.model_family,
                        tokenizer_revision=tokenizer_config.source.revision,
                        input_tokens=len(token_ids),
                        token_sequence_sha256=sequence_sha256,
                        token_trace=_workspace_binding(root, target, workspace, relative),
                    )
                )
        manifest_identity = _canonical_sha256(
            [
                suite.manifest_sha256,
                backend.config_sha256,
                tokenizer_config.config_sha256,
                [item.request_sha256 for item in counts],
            ]
        )
        manifest = TrackAInputTokenManifest(
            schema_version="2.0",
            token_manifest_id=f"track-a-token-manifest-{manifest_identity[:20]}",
            suite_manifest_sha256=suite.manifest_sha256,
            model=suite.model,
            model_revision=backend.model_revision,
            prompt_template_revision=template_revision,
            counts=tuple(counts),
            backend_config=_binding(root, backend_file),
            backend_config_sha256=backend.config_sha256,
            tokenizer_config=_binding(root, tokenizer_config_file),
            tokenizer_config_sha256=tokenizer_config.config_sha256,
            tokenizer_repository=tokenizer_config.source.repository,
            tokenizer_assets=tokenizer_config.local_snapshot.files,
            tokenizer_snapshot_path=str(snapshot),
            tokenizer_library=tokenizer_config.loading.library,
            tokenizer_library_revision=tokenizer_config.loading.library_revision,
            tokenizer_implementation=tokenizer_config.loading.implementation,
            chat_template_sha256=template_sha256,
            template_arguments=arguments,
            exact_for_pinned_local_template=True,
            provider_serving_build_attested=False,
            formal_provider_token_equivalence_claim_allowed=False,
            observed_api_usage_receipt_is_authoritative=True,
            natural_pilot_only=True,
        )
        relative = Path("MANIFEST.json")
        _write_json(workspace / relative, manifest.model_dump(mode="json"))
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return TrackATokenManifestMaterialization(
        output_dir=target,
        manifest_path=target / relative,
        manifest=manifest,
    )


def load_track_a_decision_batch(path: str | Path) -> TrackADecisionBatch:
    return TrackADecisionBatch.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_track_a_decision_run(path: str | Path) -> TrackADecisionRun:
    return TrackADecisionRun.model_validate_json(Path(path).read_text(encoding="utf-8"))


def prepare_track_a_decision_batch(
    *,
    evidence_root: str | Path,
    suite_manifest_path: str | Path,
    backend_config_path: str | Path,
    budget_path: str | Path,
    token_manifest_path: str | Path,
    output_dir: str | Path,
) -> TrackADecisionPreparation:
    """Compile exact provider-visible requests without performing model calls."""

    root = Path(evidence_root).resolve(strict=True)
    suite_file = _regular_file(root, suite_manifest_path)
    config_file = _regular_file(root, backend_config_path)
    budget_file = _regular_file(root, budget_path)
    token_file = _regular_file(root, token_manifest_path)
    target = _new_target(root, output_dir)
    suite = _load_suite_manifest(suite_file)
    config = load_track_a_decision_backend_config(config_file)
    budget = load_track_a_decision_budget(budget_file)
    token_manifest = load_track_a_input_token_manifest(token_file)
    arm_configs = _verify_suite(root, suite_file, suite)
    _verify_control_contract(root, suite, config, budget, token_manifest, arm_configs)
    counts = {item.request_sha256: item for item in token_manifest.counts}
    parameter_profile = _parameter_profile_sha256(suite, config)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        calls: list[TrackADecisionCall] = []
        ordinal = 0
        for case in suite.cases:
            for arm in case.arms:
                ordinal += 1
                execution = arm_configs[arm.model_request_sha256]
                payload = _provider_payload(execution.model_visible_request)
                payload_bytes = _canonical_json_bytes(payload)
                _require_arm_hidden(payload_bytes)
                token_count = counts[arm.model_request_sha256]
                _require_call_within_budget(
                    payload_bytes,
                    token_count.input_tokens,
                    suite,
                    budget.per_call,
                )
                call_id = f"track-a-call-{arm.model_request_sha256[:24]}"
                relative = Path("public") / "requests" / f"{call_id}.json"
                _write_bytes(workspace / relative, payload_bytes)
                calls.append(
                    TrackADecisionCall(
                        ordinal=ordinal,
                        call_id=call_id,
                        model_request_sha256=arm.model_request_sha256,
                        http_request=_workspace_binding(root, target, workspace, relative),
                        input_token_count=token_count.input_tokens,
                        token_sequence_sha256=token_count.token_sequence_sha256,
                        token_trace=token_count.token_trace,
                        parameter_profile_sha256=parameter_profile,
                    )
                )
        batch_identity = _canonical_sha256([suite.manifest_sha256, parameter_profile])
        batch = TrackADecisionBatch(
            batch_id=f"track-a-decision-batch-{batch_identity[:20]}",
            project_id=suite.project_id,
            suite_manifest=_binding(root, suite_file),
            suite_manifest_sha256=suite.manifest_sha256,
            backend_config=_binding(root, config_file),
            backend_config_sha256=config.config_sha256,
            execution_budget=_binding(root, budget_file),
            execution_budget_sha256=budget.budget_sha256,
            token_manifest=_binding(root, token_file),
            token_manifest_sha256=token_manifest.token_manifest_sha256,
            model_identity_sha256=config.model_identity_sha256,
            parameter_profile_sha256=parameter_profile,
            eligible_case_count=suite.case_count,
            excluded_or_unmaterialized_case_count=_PLANNED_CASE_COUNT - suite.case_count,
            eligible_call_count=suite.arm_count,
            calls=tuple(calls),
            full_planned_population_materialized=suite.full_target_coverage,
        )
        relative = Path("public") / "BATCH.json"
        _write_json(workspace / relative, batch.model_dump(mode="json", exclude={"batch_sha256"}))
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return TrackADecisionPreparation(
        output_dir=target,
        batch_path=target / relative,
        batch=batch,
    )


def execute_track_a_decision_batch(
    *,
    evidence_root: str | Path,
    batch_path: str | Path,
    output_dir: str | Path,
    allow_live: bool = False,
    transport: AIPreferenceHTTPTransport | None = None,
) -> TrackADecisionRun:
    """Call every eligible arm once, or terminate without an admissible recording."""

    root = Path(evidence_root).resolve(strict=True)
    batch_file = _regular_file(root, batch_path)
    target = _new_target(root, output_dir)
    batch = load_track_a_decision_batch(batch_file)
    suite_file = _bound_file(root, batch.suite_manifest)
    config_file = _bound_file(root, batch.backend_config)
    budget_file = _bound_file(root, batch.execution_budget)
    token_file = _bound_file(root, batch.token_manifest)
    suite = _load_suite_manifest(suite_file)
    config = load_track_a_decision_backend_config(config_file)
    budget = load_track_a_decision_budget(budget_file)
    token_manifest = load_track_a_input_token_manifest(token_file)
    arm_configs = _verify_suite(root, suite_file, suite)
    _verify_batch(
        root,
        batch_file,
        batch,
        suite,
        config,
        budget,
        token_manifest,
        arm_configs,
    )
    if not allow_live or not config.live_enabled:
        raise ValueError("Track-A execution requires CLI and config live opt-in")
    api_key = os.getenv(config.api_key_env)
    if api_key is None or not api_key.strip():
        raise RuntimeError(f"missing API key environment variable {config.api_key_env}")
    control_hashes = {
        batch_file: _sha256(batch_file),
        suite_file: _sha256(suite_file),
        config_file: _sha256(config_file),
        budget_file: _sha256(budget_file),
        token_file: _sha256(token_file),
    }
    arm_by_request = _arm_index(suite, arm_configs)
    target.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(UTC)
    completed: list[TrackADecisionCompletedCall] = []
    observations: list[TrackADecisionObservation] = []
    attempted_call_id: str | None = None
    try:
        for call in batch.calls:
            attempted_call_id = call.call_id
            case, arm, execution = arm_by_request[call.model_request_sha256]
            summary, observation = _execute_call_once(
                root=root,
                batch_file=batch_file,
                batch=batch,
                suite=suite,
                config_file=config_file,
                config=config,
                budget_file=budget_file,
                budget=budget,
                call=call,
                case=case,
                arm=arm,
                execution=execution,
                output_root=target,
                api_key=api_key.strip(),
                transport=transport,
            )
            completed.append(summary)
            observations.append(observation)
        if any(_sha256(path) != expected for path, expected in control_hashes.items()):
            raise ValueError("Track-A control evidence changed during execution")
        recording_file = target / "private" / "recording.jsonl"
        _write_bytes(
            recording_file,
            b"".join((item.model_dump_json() + "\n").encode("utf-8") for item in observations),
        )
        run = TrackADecisionRun(
            run_id=f"track-a-run-{batch.batch_sha256[:20]}",
            batch=_binding(root, batch_file),
            batch_sha256=batch.batch_sha256,
            private_recording=_binding(root, recording_file),
            eligible_case_count=batch.eligible_case_count,
            executed_case_count=batch.eligible_case_count,
            eligible_call_count=batch.eligible_call_count,
            executed_call_count=len(completed),
            completed=tuple(completed),
            total_tokens=sum(item.total_tokens for item in completed),
            total_cost_usd=sum(item.cost_usd for item in completed),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        if (
            run.total_tokens > budget.max_total_tokens
            or run.total_cost_usd > budget.max_total_cost_usd + 1e-12
        ):
            raise ValueError("Track-A completed run exceeds aggregate budget")
        _write_json(target / "RUN.json", run.model_dump(mode="json", exclude={"run_sha256"}))
    except BaseException as exc:
        _write_failure(target, exc, batch, completed, attempted_call_id)
        raise
    return run


def bridge_track_a_run_to_ai_preference(
    *,
    evidence_root: str | Path,
    decision_run_path: str | Path,
    ai_preference_protocol_path: str | Path,
    study_protocol_path: str | Path,
    rubric_path: str | Path,
    interface_path: str | Path,
    analysis_contract_path: str | Path,
    study_output_dir: str | Path,
    ai_preference_pack_output_dir: str | Path,
    report_path: str | Path,
    randomization_seed: int,
) -> TrackAAIPreferenceBridgeReport:
    """Blind a successful subset and compile the existing AI preference requests."""

    root = Path(evidence_root).resolve(strict=True)
    run_file = _regular_file(root, decision_run_path)
    run = load_track_a_decision_run(run_file)
    batch_file, batch, suite, config, observations = _verify_successful_run(root, run_file, run)
    ai_protocol_file = _regular_file(root, ai_preference_protocol_path)
    ai_protocol = load_ai_blind_preference_protocol(ai_protocol_file)
    if _bound_ai_file(root, ai_protocol.benchmark_suite) != _bound_file(root, batch.suite_manifest):
        raise ValueError("AI preference protocol and Track-A run bind different suites")
    assignments = tuple(item.assignment_identity_sha256 for item in ai_protocol.primary_reviewers)
    if any(item is None for item in assignments):
        raise ValueError("AI preference primaries lack assignment identities")
    study_target = _new_target(root, study_output_dir)
    pack_target = _new_target(root, ai_preference_pack_output_dir)
    report_target = _new_target(root, report_path)
    _require_disjoint_bridge_outputs(study_target, pack_target, report_target)
    contract_files = tuple(
        _regular_file(root, item)
        for item in (
            study_protocol_path,
            rubric_path,
            interface_path,
            analysis_contract_path,
        )
    )
    study, blind_key, ledger, study_paths = _materialize_blind_study(
        root=root,
        target=study_target,
        suite_file=_bound_file(root, batch.suite_manifest),
        suite=suite,
        config=config,
        observations=observations,
        receipts={item.call_id: _bound_file(root, item.receipt) for item in run.completed},
        study_id=ai_protocol.study_id,
        reviewer_assignments=assignments,  # type: ignore[arg-type]
        randomization_seed=randomization_seed,
        protocol_file=contract_files[0],
        rubric_file=contract_files[1],
        interface_file=contract_files[2],
        analysis_file=contract_files[3],
    )
    pack = _materialize_ai_preference_pack(
        root=root,
        target=pack_target,
        suite_file=_bound_file(root, batch.suite_manifest),
        suite=suite,
        study_file=study_paths["study"],
        study=study,
        ai_protocol_file=ai_protocol_file,
        observations=observations,
    )
    pack_file = pack_target / "PACK.json"
    report = TrackAAIPreferenceBridgeReport(
        bridge_id=f"track-a-ai-bridge-{_canonical_sha256([run.run_sha256, pack.pack_sha256])[:20]}",
        decision_run=_binding(root, run_file),
        decision_run_sha256=run.run_sha256,
        private_recording=run.private_recording,
        public_study=_binding(root, study_paths["study"]),
        private_blind_key=_binding(root, study_paths["blind_key"]),
        private_generation_ledger=_binding(root, study_paths["ledger"]),
        study_sha256=study.study_sha256,
        ai_preference_pack=_binding(root, pack_file),
        ai_preference_pack_sha256=pack.pack_sha256,
        eligible_case_count=run.eligible_case_count,
        executed_case_count=run.executed_case_count,
        excluded_or_unmaterialized_case_count=(_PLANNED_CASE_COUNT - run.eligible_case_count),
        eligible_decision_call_count=run.eligible_call_count,
        executed_decision_call_count=run.executed_call_count,
    )
    _write_json(
        report_target,
        report.model_dump(mode="json", exclude={"bridge_sha256"}),
    )
    del batch_file, blind_key, ledger
    return report


def _load_suite_manifest(path: Path) -> TrackAPilotSuiteManifest:
    return TrackAPilotSuiteManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _verify_suite(
    root: Path,
    suite_file: Path,
    suite: TrackAPilotSuiteManifest,
) -> dict[str, TrackAArmExecutionConfig]:
    if suite.case_count != len(suite.cases) or suite.arm_count != suite.case_count * 3:
        raise ValueError("Track-A suite eligible coverage counts drifted")
    if suite.model_calls_performed or suite.execution_authorized:
        raise ValueError("Track-A suite manifest must remain a no-call construction artifact")
    for binding in (suite.pilot_plan, suite.suite_spec, suite.accepted_abstraction_set):
        _bound_suite_root_file(root, binding.locator, binding.file_sha256)
    arm_configs: dict[str, TrackAArmExecutionConfig] = {}
    for case in suite.cases:
        for arm in case.arms:
            path = _bound_suite_relative_file(
                suite_file.parent,
                arm.execution_config.locator,
                arm.execution_config.file_sha256,
            )
            execution = TrackAArmExecutionConfig.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if (
                execution.config_sha256 != arm.execution_config.semantic_sha256
                or execution.target_id != case.target_id
                or execution.condition != arm.condition
                or execution.model_visible_request.request_sha256 != arm.model_request_sha256
                or execution.model_visible_request.provider != suite.provider
                or execution.model_visible_request.model != suite.model
                or execution.model_visible_request.sampling != suite.sampling
                or not execution.condition_metadata_absent_from_model_request
            ):
                raise ValueError("Track-A arm execution config differs from its suite")
            if arm.model_request_sha256 in arm_configs:
                raise ValueError("Track-A suite repeats a model-visible request")
            arm_configs[arm.model_request_sha256] = execution
    if len(arm_configs) != suite.arm_count:
        raise ValueError("Track-A suite arm config coverage is incomplete")
    return arm_configs


def _verify_control_contract(
    root: Path,
    suite: TrackAPilotSuiteManifest,
    config: TrackADecisionBackendConfig,
    budget: TrackADecisionExecutionBudget,
    token_manifest: TrackAInputTokenManifest,
    arm_configs: dict[str, TrackAArmExecutionConfig],
) -> None:
    if (config.provider, config.model) != (suite.provider, suite.model):
        raise ValueError("Track-A runtime provider/model differs from the suite")
    if budget.expected_eligible_call_count != suite.arm_count:
        raise ValueError("Track-A budget does not match eligible suite arms")
    if (
        token_manifest.suite_manifest_sha256 != suite.manifest_sha256
        or token_manifest.model != suite.model
        or token_manifest.model_revision != config.model_revision
    ):
        raise ValueError("Track-A token manifest binds another suite or model")
    tokenizer_config: TrackATokenizerMaterializationConfig | None = None
    if token_manifest.schema_version == "2.0":
        if not suite.natural_pilot:
            raise ValueError("Track-A v2 local tokenizer evidence is natural-pilot only")
        if token_manifest.tokenizer_config is None:
            raise ValueError("Track-A v2 token manifest lacks its tokenizer config")
        if token_manifest.backend_config is None:
            raise ValueError("Track-A v2 token manifest lacks its backend config")
        bound_backend_file = _bound_file(root, token_manifest.backend_config)
        bound_backend = load_track_a_decision_backend_config(bound_backend_file)
        tokenizer_config_file = _bound_file(root, token_manifest.tokenizer_config)
        tokenizer_config = load_track_a_tokenizer_materialization_config(tokenizer_config_file)
        snapshot = _verify_tokenizer_snapshot(tokenizer_config)
        if (
            bound_backend.config_sha256 != config.config_sha256
            or bound_backend.config_sha256 != token_manifest.backend_config_sha256
            or tokenizer_config.config_sha256 != token_manifest.tokenizer_config_sha256
            or tokenizer_config.model != suite.model
            or tokenizer_config.source.repository != token_manifest.tokenizer_repository
            or tokenizer_config.source.revision != token_manifest.counts[0].tokenizer_revision
            or tokenizer_config.local_snapshot.files != token_manifest.tokenizer_assets
            or str(snapshot) != token_manifest.tokenizer_snapshot_path
            or tokenizer_config.loading.library != token_manifest.tokenizer_library
            or tokenizer_config.loading.library_revision
            != token_manifest.tokenizer_library_revision
            or tokenizer_config.loading.implementation != token_manifest.tokenizer_implementation
            or tokenizer_config.loading.chat_template_file
            not in {item.path for item in tokenizer_config.local_snapshot.files}
            or tokenizer_config.loading.tokenizer_file
            not in {item.path for item in tokenizer_config.local_snapshot.files}
            or _sha256(snapshot / tokenizer_config.loading.chat_template_file)
            != token_manifest.chat_template_sha256
            or token_manifest.template_arguments != TrackATokenizerTemplateArguments()
        ):
            raise ValueError("Track-A v2 tokenizer provenance drifted")
    counts = {item.request_sha256: item for item in token_manifest.counts}
    if set(counts) != set(arm_configs):
        raise ValueError("Track-A token manifest does not exactly cover eligible arms")
    for item in token_manifest.counts:
        trace_file = _bound_file(root, item.token_trace)
        trace = TrackAInputTokenTrace.model_validate_json(trace_file.read_text(encoding="utf-8"))
        if (
            trace.request_sha256 != item.request_sha256
            or trace.tokenizer_id != item.tokenizer_id
            or trace.tokenizer_revision != item.tokenizer_revision
            or trace.prompt_template_revision != token_manifest.prompt_template_revision
            or len(trace.token_ids) != item.input_tokens
            or trace.token_sequence_sha256 != item.token_sequence_sha256
        ):
            raise ValueError("Track-A token-count entry differs from its exact trace")
        if token_manifest.schema_version == "2.0":
            execution = arm_configs[item.request_sha256]
            payload = _provider_payload(execution.model_visible_request)
            messages = payload.get("messages")
            request_identity = _canonical_sha256(
                {
                    "model_visible_request_sha256": item.request_sha256,
                    "provider_payload_sha256": _canonical_sha256(payload),
                    "provider_messages_sha256": _canonical_sha256(messages),
                }
            )
            if (
                tokenizer_config is None
                or trace.schema_version != "2.0"
                or trace.provider_payload_sha256 != _canonical_sha256(payload)
                or trace.provider_messages_sha256 != _canonical_sha256(messages)
                or trace.provider_request_identity_sha256 != request_identity
                or trace.tokenizer_config_sha256 != tokenizer_config.config_sha256
                or trace.chat_template_sha256 != token_manifest.chat_template_sha256
                or trace.template_arguments != token_manifest.template_arguments
                or trace.add_special_tokens
            ):
                raise ValueError("Track-A v2 token trace differs from provider-visible request")
        if item.input_tokens > suite.context_budget.maximum_input_tokens:
            raise ValueError("Track-A measured input exceeds the suite token budget")
    if suite.sampling.maximum_output_tokens > budget.per_call.max_output_tokens:
        raise ValueError("Track-A suite output ceiling exceeds the execution budget")
    if config.timeout_seconds * 1_000 > budget.per_call.max_latency_ms:
        raise ValueError("Track-A runtime timeout exceeds the execution budget")
    maximum_cost = _maximum_cost(config.pricing, budget.per_call)
    if maximum_cost > budget.per_call.max_cost_usd + 1e-12:
        raise ValueError("Track-A maximum priced call exceeds its hard cost ceiling")
    if maximum_cost * suite.arm_count > budget.max_total_cost_usd + 1e-12:
        raise ValueError("Track-A reserved eligible batch exceeds aggregate cost ceiling")


def _verify_batch(
    root: Path,
    batch_file: Path,
    batch: TrackADecisionBatch,
    suite: TrackAPilotSuiteManifest,
    config: TrackADecisionBackendConfig,
    budget: TrackADecisionExecutionBudget,
    token_manifest: TrackAInputTokenManifest,
    arm_configs: dict[str, TrackAArmExecutionConfig],
) -> None:
    del batch_file
    _verify_control_contract(root, suite, config, budget, token_manifest, arm_configs)
    if (
        batch.suite_manifest_sha256 != suite.manifest_sha256
        or batch.backend_config_sha256 != config.config_sha256
        or batch.execution_budget_sha256 != budget.budget_sha256
        or batch.token_manifest_sha256 != token_manifest.token_manifest_sha256
        or batch.model_identity_sha256 != config.model_identity_sha256
        or batch.parameter_profile_sha256 != _parameter_profile_sha256(suite, config)
        or batch.eligible_case_count != suite.case_count
        or batch.eligible_call_count != suite.arm_count
    ):
        raise ValueError("Track-A prepared batch control identities drifted")
    token_counts = {item.request_sha256: item for item in token_manifest.counts}
    calls = {item.model_request_sha256: item for item in batch.calls}
    if set(calls) != set(arm_configs):
        raise ValueError("Track-A public batch does not exactly cover eligible arms")
    for request_sha, call in calls.items():
        execution = arm_configs[request_sha]
        token_count = token_counts[request_sha]
        payload = _canonical_json_bytes(_provider_payload(execution.model_visible_request))
        request_file = _bound_file(root, call.http_request)
        if request_file.read_bytes() != payload:
            raise ValueError("Track-A provider request bytes do not replay")
        if (
            call.input_token_count != token_count.input_tokens
            or call.token_sequence_sha256 != token_count.token_sequence_sha256
            or call.token_trace != token_count.token_trace
        ):
            raise ValueError("Track-A public call differs from token evidence")
        _require_arm_hidden(payload)
        _require_call_within_budget(
            payload,
            token_count.input_tokens,
            suite,
            budget.per_call,
        )


def _arm_index(
    suite: TrackAPilotSuiteManifest,
    arm_configs: dict[str, TrackAArmExecutionConfig],
) -> dict[
    str,
    tuple[TrackASuiteCaseRecord, TrackASuiteArmRecord, TrackAArmExecutionConfig],
]:
    return {
        arm.model_request_sha256: (
            case,
            arm,
            arm_configs[arm.model_request_sha256],
        )
        for case in suite.cases
        for arm in case.arms
    }


def _execute_call_once(
    *,
    root: Path,
    batch_file: Path,
    batch: TrackADecisionBatch,
    suite: TrackAPilotSuiteManifest,
    config_file: Path,
    config: TrackADecisionBackendConfig,
    budget_file: Path,
    budget: TrackADecisionExecutionBudget,
    call: TrackADecisionCall,
    case: TrackASuiteCaseRecord,
    arm: TrackASuiteArmRecord,
    execution: TrackAArmExecutionConfig,
    output_root: Path,
    api_key: str,
    transport: AIPreferenceHTTPTransport | None,
) -> tuple[TrackADecisionCompletedCall, TrackADecisionObservation]:
    directory = output_root / call.call_id
    directory.mkdir(parents=True, exist_ok=False)
    http_request_file = _bound_file(root, call.http_request)
    payload = http_request_file.read_bytes()
    _require_arm_hidden(payload)
    _require_call_within_budget(
        payload,
        call.input_token_count,
        suite,
        budget.per_call,
    )
    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    response: AIPreferenceHTTPResponse = (transport or HttpxAIPreferenceTransport()).post(
        endpoint,
        headers=headers,
        content=payload,
        timeout=config.timeout_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1_000
    completed_at = datetime.now(UTC)
    raw_http = directory / "provider-response.body"
    _write_bytes(raw_http, response.raw_body)
    if response.status_code < 200 or response.status_code >= 300:
        raise ValueError(f"Track-A provider returned HTTP {response.status_code}")
    provider = _parse_provider_response(response.raw_body, config)
    decision = TrackARawDecision.model_validate_json(provider.content)
    raw_response = directory / "raw-response.json"
    _write_bytes(raw_response, provider.content.encode("utf-8"))
    usage = _review_usage(provider.usage, config.pricing)
    if usage.input_tokens != call.input_token_count:
        raise ValueError("Track-A provider input usage differs from premeasured tokens")
    if (
        usage.output_tokens > suite.sampling.maximum_output_tokens
        or usage.output_tokens > budget.per_call.max_output_tokens
        or usage.total_tokens > budget.per_call.max_total_tokens
        or usage.cost_usd > budget.per_call.max_cost_usd + 1e-12
        or latency_ms > budget.per_call.max_latency_ms
    ):
        raise ValueError("Track-A provider telemetry exceeds its per-call ceiling")
    receipt = TrackADecisionExecutionReceipt(
        invocation_id=f"invoke-{call.call_id}",
        call_id=call.call_id,
        model_request_sha256=call.model_request_sha256,
        batch=_binding(root, batch_file),
        batch_sha256=batch.batch_sha256,
        backend_config=_binding(root, config_file),
        backend_config_sha256=config.config_sha256,
        execution_budget=_binding(root, budget_file),
        execution_budget_sha256=budget.budget_sha256,
        http_request=call.http_request,
        raw_http_body=_binding(root, raw_http),
        raw_response=_binding(root, raw_response),
        provider=config.provider,
        requested_model=config.model,
        model_revision=config.model_revision,
        provider_reported_model=provider.provider_model,
        model_identity_sha256=config.model_identity_sha256,
        parameter_profile_sha256=batch.parameter_profile_sha256,
        provider_request_id=provider.provider_request_id,
        started_at=started_at,
        completed_at=completed_at,
        http_status=response.status_code,
        latency_ms=latency_ms,
        usage=usage,
    )
    receipt_file = directory / "RECEIPT.json"
    _write_json(
        receipt_file,
        receipt.model_dump(mode="json", exclude={"receipt_sha256"}),
    )
    observation = TrackADecisionObservation.create(
        observation_id=f"observation-{call.model_request_sha256[:24]}",
        call_id=call.call_id,
        target_id=case.target_id,
        target_source_group_id=case.target_source_group_id,
        condition=arm.condition,
        model_request_sha256=call.model_request_sha256,
        selected_action_id=decision.selected_action_id,
        abstained=decision.abstained,
        confidence=decision.confidence,
        rationale=decision.rationale,
        provider=config.provider,
        model=config.model,
        execution_receipt=_binding(root, receipt_file),
        execution_receipt_sha256=receipt.receipt_sha256,
        recorded_at=completed_at,
    )
    return (
        TrackADecisionCompletedCall(
            ordinal=call.ordinal,
            call_id=call.call_id,
            model_request_sha256=call.model_request_sha256,
            receipt=_binding(root, receipt_file),
            receipt_sha256=receipt.receipt_sha256,
            observation_sha256=observation.observation_sha256,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
        ),
        observation,
    )


def _verify_successful_run(
    root: Path,
    run_file: Path,
    run: TrackADecisionRun,
) -> tuple[
    Path,
    TrackADecisionBatch,
    TrackAPilotSuiteManifest,
    TrackADecisionBackendConfig,
    tuple[TrackADecisionObservation, ...],
]:
    del run_file
    batch_file = _bound_file(root, run.batch)
    batch = load_track_a_decision_batch(batch_file)
    if batch.batch_sha256 != run.batch_sha256:
        raise ValueError("Track-A run binds another batch semantic identity")
    suite_file = _bound_file(root, batch.suite_manifest)
    config_file = _bound_file(root, batch.backend_config)
    budget_file = _bound_file(root, batch.execution_budget)
    token_file = _bound_file(root, batch.token_manifest)
    suite = _load_suite_manifest(suite_file)
    config = load_track_a_decision_backend_config(config_file)
    budget = load_track_a_decision_budget(budget_file)
    token_manifest = load_track_a_input_token_manifest(token_file)
    arm_configs = _verify_suite(root, suite_file, suite)
    _verify_batch(
        root,
        batch_file,
        batch,
        suite,
        config,
        budget,
        token_manifest,
        arm_configs,
    )
    recording = _bound_file(root, run.private_recording)
    observations = _load_observations(recording)
    if len(observations) != run.executed_call_count:
        raise ValueError("Track-A private recording count differs from successful run")
    by_call = {item.call_id: item for item in observations}
    if len(by_call) != len(observations) or set(by_call) != {
        item.call_id for item in run.completed
    }:
        raise ValueError("Track-A private recording does not exactly cover completed calls")
    call_by_id = {item.call_id: item for item in batch.calls}
    arm_by_request = _arm_index(suite, arm_configs)
    for summary in run.completed:
        call = call_by_id[summary.call_id]
        observation = by_call[summary.call_id]
        case, arm, execution = arm_by_request[call.model_request_sha256]
        receipt_file = _bound_file(root, summary.receipt)
        receipt = TrackADecisionExecutionReceipt.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
        _verify_receipt_replay(
            root=root,
            batch_file=batch_file,
            batch=batch,
            config_file=config_file,
            config=config,
            budget_file=budget_file,
            budget=budget,
            call=call,
            case=case,
            arm=arm,
            execution=execution,
            receipt_file=receipt_file,
            receipt=receipt,
            observation=observation,
        )
        if (
            receipt.receipt_sha256 != summary.receipt_sha256
            or observation.observation_sha256 != summary.observation_sha256
            or receipt.usage.total_tokens != summary.total_tokens
            or abs(receipt.usage.cost_usd - summary.cost_usd) > 1e-12
        ):
            raise ValueError("Track-A completed-call summary does not replay")
    return batch_file, batch, suite, config, observations


def _verify_receipt_replay(
    *,
    root: Path,
    batch_file: Path,
    batch: TrackADecisionBatch,
    config_file: Path,
    config: TrackADecisionBackendConfig,
    budget_file: Path,
    budget: TrackADecisionExecutionBudget,
    call: TrackADecisionCall,
    case: TrackASuiteCaseRecord,
    arm: TrackASuiteArmRecord,
    execution: TrackAArmExecutionConfig,
    receipt_file: Path,
    receipt: TrackADecisionExecutionReceipt,
    observation: TrackADecisionObservation,
) -> None:
    if (
        _bound_file(root, receipt.batch) != batch_file
        or receipt.batch_sha256 != batch.batch_sha256
        or _bound_file(root, receipt.backend_config) != config_file
        or receipt.backend_config_sha256 != config.config_sha256
        or _bound_file(root, receipt.execution_budget) != budget_file
        or receipt.execution_budget_sha256 != budget.budget_sha256
        or receipt.call_id != call.call_id
        or receipt.model_request_sha256 != call.model_request_sha256
    ):
        raise ValueError("Track-A receipt control bindings do not replay")
    if (
        receipt.provider != config.provider
        or receipt.requested_model != config.model
        or receipt.model_revision != config.model_revision
        or receipt.model_identity_sha256 != config.model_identity_sha256
        or receipt.parameter_profile_sha256 != batch.parameter_profile_sha256
    ):
        raise ValueError("Track-A receipt model identity or parameters drifted")
    http_file = _bound_file(root, receipt.http_request)
    expected_http = _canonical_json_bytes(_provider_payload(execution.model_visible_request))
    if http_file != _bound_file(root, call.http_request) or http_file.read_bytes() != expected_http:
        raise ValueError("Track-A receipt HTTP request does not replay")
    _require_arm_hidden(expected_http)
    raw_http = _bound_file(root, receipt.raw_http_body)
    raw_response = _bound_file(root, receipt.raw_response)
    provider = _parse_provider_response(raw_http.read_bytes(), config)
    decision = TrackARawDecision.model_validate_json(provider.content)
    if (
        provider.provider_model != receipt.provider_reported_model
        or provider.provider_request_id != receipt.provider_request_id
        or provider.content.encode("utf-8") != raw_response.read_bytes()
        or _review_usage(provider.usage, config.pricing) != receipt.usage
    ):
        raise ValueError("Track-A provider response or usage does not replay")
    if (
        observation.call_id != call.call_id
        or observation.target_id != case.target_id
        or observation.target_source_group_id != case.target_source_group_id
        or observation.condition != arm.condition
        or observation.model_request_sha256 != call.model_request_sha256
        or observation.selected_action_id != decision.selected_action_id
        or observation.abstained != decision.abstained
        or observation.confidence != decision.confidence
        or observation.rationale != decision.rationale
        or observation.provider != config.provider
        or observation.model != config.model
        or observation.recorded_at != receipt.completed_at
        or _bound_file(root, observation.execution_receipt) != receipt_file
    ):
        raise ValueError("Track-A observation differs from its execution evidence")
    if observation.execution_receipt_sha256 != receipt.receipt_sha256:
        raise ValueError("Track-A observation receipt hash differs")
    if (
        receipt.usage.input_tokens != call.input_token_count
        or receipt.usage.output_tokens > budget.per_call.max_output_tokens
        or receipt.usage.total_tokens > budget.per_call.max_total_tokens
        or receipt.usage.cost_usd > budget.per_call.max_cost_usd + 1e-12
    ):
        raise ValueError("Track-A receipt exceeds or differs from frozen call budgets")


def _materialize_blind_study(
    *,
    root: Path,
    target: Path,
    suite_file: Path,
    suite: TrackAPilotSuiteManifest,
    config: TrackADecisionBackendConfig,
    observations: tuple[TrackADecisionObservation, ...],
    receipts: dict[str, Path],
    study_id: str,
    reviewer_assignments: tuple[str, str],
    randomization_seed: int,
    protocol_file: Path,
    rubric_file: Path,
    interface_file: Path,
    analysis_file: Path,
) -> tuple[
    HumanOutcomeStudyManifest,
    HumanBlindKey,
    TreatmentGenerationLedger,
    dict[str, Path],
]:
    arm_configs = _verify_suite(root, suite_file, suite)
    by_identity = {(item.target_id, item.condition): item for item in observations}
    expected = {(case.target_id, condition) for case in suite.cases for condition in _CONDITIONS}
    if set(by_identity) != expected:
        raise ValueError("Track-A bridge requires one observation per eligible arm")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        blinding_secret = secrets.token_hex(32)
        output_bindings: dict[tuple[str, TasteStudyCondition], BlindedOutputBinding] = {}
        generations: dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord] = {}
        cases = {item.target_id: item for item in suite.cases}
        profile_sha = _canonical_sha256(
            {
                "protocol": _sha256(protocol_file),
                "rubric": _sha256(rubric_file),
                "interface": _sha256(interface_file),
                "maximum_input_tokens": suite.context_budget.maximum_input_tokens,
                "maximum_output_tokens": suite.sampling.maximum_output_tokens,
                "reviewer_kind": "ai",
            }
        )
        for identity, observation in sorted(by_identity.items()):
            target_id, condition = identity
            case = cases[target_id]
            study_condition = _study_condition(condition)
            arm = next(item for item in case.arms if item.condition == condition)
            output_identity = _canonical_sha256(
                [study_id, target_id, condition, randomization_seed, blinding_secret]
            )
            output_id = f"blind-{output_identity[:24]}"
            relative = Path("reviewer") / "outputs" / f"{output_id}.json"
            description = _selected_action_description(
                case,
                arm_configs,
                observation.selected_action_id,
            )
            artifact = BlindedDecisionArtifact(
                output_id=output_id,
                case_id=target_id,
                selected_action_id=observation.selected_action_id,
                selected_action_description=description,
                rationale=observation.rationale,
                confidence=observation.confidence,
            )
            _write_json(workspace / relative, artifact.model_dump(mode="json"))
            output = _human_workspace_binding(root, target, workspace, relative)
            output_bindings[(target_id, study_condition)] = BlindedOutputBinding(
                **output.model_dump(mode="python"),
                output_id=output_id,
                presentation_profile_sha256=profile_sha,
                context_budget_tokens=suite.context_budget.maximum_input_tokens,
                maximum_output_tokens=suite.sampling.maximum_output_tokens,
            )
            receipt_file = receipts[observation.call_id]
            generation_identity = _canonical_sha256([study_id, observation.observation_sha256])
            generations[(target_id, study_condition)] = TreatmentGenerationRecord.create(
                record_id=f"generation-{generation_identity[:24]}",
                case_id=target_id,
                source_group=case.target_source_group_id,
                condition=study_condition,
                seed=suite.sampling.seed,
                candidate_order="declared",
                benchmark_request_fingerprint=observation.model_request_sha256,
                treatment_construction_receipt_sha256=arm.execution_config.semantic_sha256,
                provider=config.provider,
                model=config.model,
                execution_trace=_human_binding(root, receipt_file),
                output=output,
                generated_at=observation.recorded_at,
            )
        created_at = max(datetime.now(UTC), *(item.recorded_at for item in observations))
        accepted_file = _bound_suite_root_file(
            root,
            suite.accepted_abstraction_set.locator,
            suite.accepted_abstraction_set.file_sha256,
        )
        ledger = TreatmentGenerationLedger.create(
            ledger_id=f"ledger-{_canonical_sha256([study_id, randomization_seed])[:24]}",
            study_id=study_id,
            project_id=suite.project_id,
            benchmark_suite=_human_binding(root, suite_file),
            benchmark_suite_semantic_sha256=suite.manifest_sha256,
            reference_treatment_manifest=_human_binding(root, accepted_file),
            reference_treatment_manifest_semantic_sha256=(
                suite.accepted_abstraction_set.semantic_sha256
            ),
            entries=tuple(generations.values()),
            created_at=created_at,
        )
        comparisons, key_entries = _blind_comparisons(
            suite=suite,
            study_id=study_id,
            assignments=reviewer_assignments,
            randomization_seed=randomization_seed,
            blinding_secret=blinding_secret,
            outputs=output_bindings,
            generations=generations,
        )
        draft = HumanOutcomeStudyManifest(
            schema_version="1.2",
            study_id=study_id,
            project_id=suite.project_id,
            protocol=_human_binding(root, protocol_file),
            rubric=_human_binding(root, rubric_file),
            interface=_human_binding(root, interface_file),
            study_scope="pilot",
            preference_analysis_contract=_human_binding(root, analysis_file),
            treatment_commitment=HumanStudyTreatmentCommitment(
                benchmark_suite_file_sha256=_sha256(suite_file),
                benchmark_suite_semantic_sha256=suite.manifest_sha256,
                reference_treatment_manifest_file_sha256=_sha256(accepted_file),
                reference_treatment_manifest_semantic_sha256=(
                    suite.accepted_abstraction_set.semantic_sha256
                ),
                generation_ledger_sha256=ledger.ledger_sha256,
            ),
            blind_key_sha256="0" * 64,
            comparisons=comparisons,
        )
        key = HumanBlindKey(
            study_id=study_id,
            assignment_sha256=draft.assignment_sha256,
            created_at=created_at,
            entries=key_entries,
        )
        payload = draft.model_dump(
            mode="python",
            exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"},
        )
        study = HumanOutcomeStudyManifest(**payload, blind_key_sha256=key.blind_key_sha256)
        paths = {
            "study": workspace / "public" / "study.json",
            "blind_key": workspace / "private" / "blind-key.json",
            "ledger": workspace / "private" / "generation-ledger.json",
            "secret": workspace / "private" / "blinding-secret.json",
        }
        _write_json(
            paths["study"],
            study.model_dump(mode="json", exclude={"assignment_sha256", "study_sha256"}),
        )
        _write_json(
            paths["blind_key"],
            key.model_dump(mode="json", exclude={"blind_key_sha256"}),
        )
        _write_json(paths["ledger"], ledger.model_dump(mode="json"))
        _write_json(
            paths["secret"],
            {
                "schema_version": "1.0",
                "study_id": study_id,
                "randomization_seed": randomization_seed,
                "blinding_secret": blinding_secret,
                "reviewer_kind": "ai",
                "not_human_review": True,
            },
        )
        final_paths = {name: target / path.relative_to(workspace) for name, path in paths.items()}
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return study, key, ledger, final_paths


def _blind_comparisons(
    *,
    suite: TrackAPilotSuiteManifest,
    study_id: str,
    assignments: tuple[str, str],
    randomization_seed: int,
    blinding_secret: str,
    outputs: dict[tuple[str, TasteStudyCondition], BlindedOutputBinding],
    generations: dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord],
) -> tuple[tuple[BlindedHumanComparison, ...], tuple[HumanBlindKeyEntry, ...]]:
    contrasts = (
        (
            TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            TasteStudyCondition.SAME_SOURCE_RAW_RAG,
        ),
        (
            TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
        ),
    )
    comparisons: list[BlindedHumanComparison] = []
    keys: list[HumanBlindKeyEntry] = []
    for case in suite.cases:
        for hypothesis, comparator in contrasts:
            treatment = TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
            flip = (
                int(
                    _canonical_sha256(
                        [
                            study_id,
                            case.target_id,
                            hypothesis.value,
                            randomization_seed,
                            blinding_secret,
                        ]
                    ),
                    16,
                )
                % 2
            )
            first = (treatment, comparator) if flip == 0 else (comparator, treatment)
            for reviewer_index, (x_condition, y_condition) in enumerate(
                (first, tuple(reversed(first)))
            ):
                comparison_identity = _canonical_sha256(
                    [study_id, case.target_id, hypothesis.value, reviewer_index]
                )
                comparison_id = f"comparison-{comparison_identity[:24]}"
                comparisons.append(
                    BlindedHumanComparison(
                        comparison_id=comparison_id,
                        hypothesis=hypothesis,
                        case_id=case.target_id,
                        source_group=case.target_source_group_id,
                        reviewer_identity_sha256=assignments[reviewer_index],
                        x_output=outputs[(case.target_id, x_condition)],
                        y_output=outputs[(case.target_id, y_condition)],
                    )
                )
                keys.append(
                    HumanBlindKeyEntry(
                        comparison_id=comparison_id,
                        x_condition=x_condition,
                        y_condition=y_condition,
                        x_generation_trace_sha256=generations[
                            (case.target_id, x_condition)
                        ].record_sha256,
                        y_generation_trace_sha256=generations[
                            (case.target_id, y_condition)
                        ].record_sha256,
                    )
                )
    return tuple(comparisons), tuple(keys)


def _materialize_ai_preference_pack(
    *,
    root: Path,
    target: Path,
    suite_file: Path,
    suite: TrackAPilotSuiteManifest,
    study_file: Path,
    study: HumanOutcomeStudyManifest,
    ai_protocol_file: Path,
    observations: tuple[TrackADecisionObservation, ...],
) -> AIPreferenceRequestPack:
    del observations
    protocol = load_ai_blind_preference_protocol(ai_protocol_file)
    if protocol.study_id != study.study_id:
        raise ValueError("AI preference protocol binds another Track-A study")
    if _bound_ai_file(root, protocol.benchmark_suite) != suite_file:
        raise ValueError("AI preference protocol does not bind the Track-A suite")
    assignments = {item.reviewer_identity_sha256 for item in study.comparisons}
    expected_assignments = {item.assignment_identity_sha256 for item in protocol.primary_reviewers}
    if assignments != expected_assignments:
        raise ValueError("AI preference assignments differ from the Track-A blind study")
    cases = {item.target_id: item for item in suite.cases}
    arm_configs = _verify_suite(root, suite_file, suite)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        requests: list[AIPreferencePrimaryRequest] = []
        bindings: list[AIPreferenceFileBinding] = []
        for reviewer in protocol.primary_reviewers:
            selected = [
                item
                for item in study.comparisons
                if item.reviewer_identity_sha256 == reviewer.assignment_identity_sha256
            ]
            request = AIPreferencePrimaryRequest(
                request_id=f"request-{reviewer.role}-{study.study_sha256[:20]}",
                study_id=study.study_id,
                study_sha256=study.study_sha256,
                protocol_sha256=protocol.protocol_sha256,
                reviewer=reviewer,
                primary_question=protocol.primary_question,
                decision_standards=protocol.decision_standards,
                tie_rule=protocol.tie_rule,
                cannot_assess_rule=protocol.cannot_assess_rule,
                maximum_rationale_characters=protocol.maximum_rationale_characters,
                items=tuple(
                    _ai_request_item(
                        root,
                        comparison,
                        cases[comparison.case_id],
                        arm_configs,
                        ordinal,
                    )
                    for ordinal, comparison in enumerate(selected, 1)
                ),
            )
            relative = Path("requests") / f"{reviewer.role}.json"
            _write_json(
                workspace / relative,
                request.model_dump(mode="json", exclude={"request_sha256"}),
            )
            requests.append(request)
            bindings.append(_ai_workspace_binding(root, target, workspace, relative))
        pack = AIPreferenceRequestPack(
            pack_id=f"ai-preference-pack-{study.study_sha256[:20]}",
            study_id=study.study_id,
            study_sha256=study.study_sha256,
            study=_ai_binding(root, study_file),
            benchmark_suite=_ai_binding(root, suite_file),
            benchmark_suite_semantic_sha256=suite.manifest_sha256,
            protocol=_ai_binding(root, ai_protocol_file),
            protocol_sha256=protocol.protocol_sha256,
            primary_requests=tuple(bindings),  # type: ignore[arg-type]
            primary_request_sha256s=tuple(  # type: ignore[arg-type]
                item.request_sha256 for item in requests
            ),
            primary_reviewer_identity_sha256s=tuple(  # type: ignore[arg-type]
                item.reviewer.identity_sha256 for item in requests
            ),
            adjudicator_identity_sha256=protocol.adjudicator.identity_sha256,
            comparison_count=len(study.comparisons),
        )
        _write_json(
            workspace / "PACK.json",
            pack.model_dump(mode="json", exclude={"pack_sha256"}),
        )
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return pack


def _ai_request_item(
    root: Path,
    comparison: BlindedHumanComparison,
    case: TrackASuiteCaseRecord,
    arm_configs: dict[str, TrackAArmExecutionConfig],
    ordinal: int,
) -> AIPreferenceRequestItem:
    target_prompt = _case_target_prompt(case, arm_configs)
    context = "\n\n".join(
        item
        for item in (
            target_prompt.reviewed_abstract,
            target_prompt.predecision_review_context,
        )
        if item
    )
    return AIPreferenceRequestItem(
        ordinal=ordinal,
        comparison_id=comparison.comparison_id,
        hypothesis=comparison.hypothesis,
        case_id=case.target_id,
        source_group=case.target_source_group_id,
        case_context=context,
        task=case.decision_family,
        stage="natural-source-decision",
        output_x=_ai_visible_decision(root, comparison.x_output),
        output_y=_ai_visible_decision(root, comparison.y_output),
    )


def _ai_visible_decision(
    root: Path,
    binding: BlindedOutputBinding,
) -> AIPreferenceVisibleDecision:
    path = _regular_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("Track-A blinded output differs from its study binding")
    artifact = BlindedDecisionArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    return AIPreferenceVisibleDecision(
        output_id=artifact.output_id,
        selected_action_id=artifact.selected_action_id,
        selected_action_description=artifact.selected_action_description,
        rationale=artifact.rationale,
        confidence=artifact.confidence,
        output_sha256=binding.sha256,
    )


def _case_target_prompt(
    case: TrackASuiteCaseRecord,
    arm_configs: dict[str, TrackAArmExecutionConfig],
) -> TrackATargetPrompt:
    prompts = tuple(
        arm_configs[arm.model_request_sha256].model_visible_request.target_prompt
        for arm in case.arms
    )
    if len(set(_canonical_sha256(item.model_dump(mode="json")) for item in prompts)) != 1:
        raise ValueError("Track-A case target prompts drifted")
    return prompts[0]


def _selected_action_description(
    case: TrackASuiteCaseRecord,
    arm_configs: dict[str, TrackAArmExecutionConfig],
    selected_action_id: str,
) -> str:
    if selected_action_id == "abstain":
        return "The decision model abstained from the fixed candidate pair."
    prompt = _case_target_prompt(case, arm_configs)
    try:
        return next(
            item.text for item in prompt.candidate_actions if item.action_id == selected_action_id
        )
    except StopIteration as exc:
        raise ValueError("Track-A observation selected an unknown candidate") from exc


def _study_condition(condition: str) -> TasteStudyCondition:
    return {
        "raw-source-rag": TasteStudyCondition.SAME_SOURCE_RAW_RAG,
        "abstracted-matched-taste": TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        "abstracted-mismatched-taste": (TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE),
    }[condition]


def _parameter_profile_sha256(
    suite: TrackAPilotSuiteManifest,
    config: TrackADecisionBackendConfig,
) -> str:
    return _canonical_sha256(
        {
            "model_identity_sha256": config.model_identity_sha256,
            "suite_spec_sha256": suite.suite_spec.semantic_sha256,
            "sampling": suite.sampling.model_dump(mode="json"),
            "api_style": "openai-compatible-chat-completions",
            "response_format": "json_object",
        }
    )


def _provider_payload(request: TrackAModelVisibleRequest) -> dict[str, object]:
    user = {
        "target_prompt": request.target_prompt.model_dump(mode="json"),
        "precedent_representation": request.precedent_representation,
        "precedent_content": request.precedent_content,
        "output_schema": request.output_schema,
    }
    return {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.system_instruction},
            {
                "role": "user",
                "content": json.dumps(
                    user,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "seed": request.sampling.seed,
        "temperature": request.sampling.temperature,
        "top_p": request.sampling.top_p,
        "max_tokens": request.sampling.maximum_output_tokens,
    }


def _parse_provider_response(
    raw_body: bytes,
    config: TrackADecisionBackendConfig,
) -> _ProviderResponse:
    payload = _json_object(raw_body, "Track-A provider response")
    request_id = payload.get("id")
    provider_model = payload.get("model", config.model)
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("Track-A provider response lacks a request ID")
    if not isinstance(provider_model, str) or provider_model not in {
        config.model,
        config.model_revision,
    }:
        raise ValueError("Track-A provider response reports another model")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("Track-A provider response requires exactly one choice")
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
        raise ValueError("Track-A provider response is not a completed message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Track-A provider response lacks decision JSON")
    _json_object(content.encode("utf-8"), "Track-A decision content")
    if not isinstance(usage, dict):
        raise ValueError("Track-A provider response lacks usage telemetry")
    return _ProviderResponse(
        provider_model=provider_model,
        provider_request_id=request_id,
        content=content,
        usage=usage,
    )


def _review_usage(raw: dict[str, object], pricing: ModelCostProvenance) -> AIReviewUsage:
    input_tokens = _token_alias(raw, ("prompt_tokens", "input_tokens"), "input")
    output_tokens = _token_alias(raw, ("completion_tokens", "output_tokens"), "output")
    reported_total = raw.get("total_tokens")
    if reported_total is not None and (
        type(reported_total) is not int or reported_total != input_tokens + output_tokens
    ):
        raise ValueError("Track-A provider total token usage conflicts")
    cached_values: list[int] = []
    for name in ("prompt_tokens_details", "input_tokens_details"):
        details = raw.get(name)
        if isinstance(details, dict) and "cached_tokens" in details:
            value = details["cached_tokens"]
            if type(value) is not int or value < 0:
                raise ValueError("Track-A cached token usage is invalid")
            cached_values.append(value)
    for name in ("prompt_cache_hit_tokens", "cache_read_input_tokens"):
        value = raw.get(name)
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError("Track-A cached token usage is invalid")
            cached_values.append(value)
    if len(set(cached_values)) > 1:
        raise ValueError("Track-A cached token aliases conflict")
    cached = cached_values[0] if cached_values else 0
    if cached > input_tokens:
        raise ValueError("Track-A cached tokens exceed input tokens")
    pricing_sha = _canonical_sha256(pricing.model_dump(mode="json"))
    million = Decimal(1_000_000)
    cached_rate = pricing.cached_input_usd_per_million_tokens
    cached_priced = cached if cached_rate is not None else 0
    cost = (
        Decimal(input_tokens - cached_priced)
        * Decimal(str(pricing.input_usd_per_million_tokens))
        / million
        + Decimal(cached_priced)
        * Decimal(str(cached_rate or pricing.input_usd_per_million_tokens))
        / million
        + Decimal(output_tokens) * Decimal(str(pricing.output_usd_per_million_tokens)) / million
    )
    cost_usd = float(cost)
    if not math.isfinite(cost_usd):
        raise ValueError("Track-A calculated cost is not finite")
    usage_payload = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached,
    }
    cost_payload = {**usage_payload, "cost_usd": cost_usd, "pricing_sha256": pricing_sha}
    return AIReviewUsage(
        **usage_payload,
        cost_usd=cost_usd,
        pricing_sha256=pricing_sha,
        usage_sha256=_canonical_sha256(usage_payload),
        cost_sha256=_canonical_sha256(cost_payload),
    )


def _token_alias(raw: dict[str, object], aliases: tuple[str, ...], label: str) -> int:
    values = [raw[name] for name in aliases if name in raw]
    if not values or any(type(value) is not int or value < 0 for value in values):
        raise ValueError(f"Track-A {label} token usage is absent or invalid")
    if len(set(values)) != 1:
        raise ValueError(f"Track-A {label} token aliases conflict")
    return values[0]  # type: ignore[return-value]


def _maximum_cost(
    pricing: ModelCostProvenance,
    budget: TrackADecisionCallBudget,
) -> float:
    input_rate = max(
        pricing.input_usd_per_million_tokens,
        pricing.cached_input_usd_per_million_tokens
        if pricing.cached_input_usd_per_million_tokens is not None
        else pricing.input_usd_per_million_tokens,
    )
    return float(
        Decimal(budget.max_input_tokens) * Decimal(str(input_rate)) / Decimal(1_000_000)
        + Decimal(budget.max_output_tokens)
        * Decimal(str(pricing.output_usd_per_million_tokens))
        / Decimal(1_000_000)
    )


def _require_call_within_budget(
    payload: bytes,
    input_tokens: int,
    suite: TrackAPilotSuiteManifest,
    budget: TrackADecisionCallBudget,
) -> None:
    if len(payload) > suite.context_budget.maximum_request_bytes:
        raise ValueError("Track-A provider request exceeds suite byte budget")
    if len(payload) > budget.max_request_bytes:
        raise ValueError("Track-A provider request exceeds execution byte budget")
    if input_tokens > suite.context_budget.maximum_input_tokens:
        raise ValueError("Track-A measured input exceeds suite token budget")
    if input_tokens > budget.max_input_tokens:
        raise ValueError("Track-A measured input exceeds execution token budget")
    if suite.sampling.maximum_output_tokens > budget.max_output_tokens:
        raise ValueError("Track-A suite output ceiling exceeds execution budget")


def _require_arm_hidden(payload: bytes) -> None:
    lowered = payload.lower()
    leaked = [item.decode("ascii") for item in _FORBIDDEN_PROVIDER_LABELS if item in lowered]
    if leaked:
        raise ValueError(
            "Track-A provider-visible request leaks controller arm labels: " + ", ".join(leaked)
        )


def _load_observations(path: Path) -> tuple[TrackADecisionObservation, ...]:
    observations: list[TrackADecisionObservation] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Track-A private recording must be UTF-8 JSONL") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            observations.append(TrackADecisionObservation.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Track-A recording line {line_number} is invalid") from exc
    if not observations:
        raise ValueError("Track-A private recording is empty")
    return tuple(observations)


def _verify_tokenizer_snapshot(config: TrackATokenizerMaterializationConfig) -> Path:
    declared = Path(config.local_snapshot.path)
    if declared.is_symlink():
        raise ValueError("Track-A tokenizer snapshot cannot be a symlink")
    snapshot = declared.resolve(strict=True)
    if snapshot != declared or not snapshot.is_dir():
        raise ValueError("Track-A tokenizer snapshot path drifted or is not a directory")
    observed_total = 0
    for asset in config.local_snapshot.files:
        relative = PurePosixPath(asset.path)
        candidate = snapshot.joinpath(*relative.parts)
        cursor = candidate
        while cursor != snapshot:
            if cursor.is_symlink():
                raise ValueError("Track-A tokenizer assets cannot traverse symlinks")
            cursor = cursor.parent
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(snapshot)
        except ValueError as exc:
            raise ValueError("Track-A tokenizer asset escapes its snapshot") from exc
        if not resolved.is_file() or resolved.stat().st_size != asset.bytes:
            raise ValueError("Track-A tokenizer asset size differs from its config")
        if _sha256(resolved) != asset.sha256:
            raise ValueError("Track-A tokenizer asset hash differs from its config")
        observed_total += resolved.stat().st_size
    if observed_total != config.local_snapshot.payload_bytes:
        raise ValueError("Track-A tokenizer snapshot observed byte total drifted")
    return snapshot


def _load_pinned_fast_tokenizer(
    config: TrackATokenizerMaterializationConfig,
    snapshot: Path,
):
    try:
        import transformers
        from transformers import PreTrainedTokenizerFast
    except ImportError as exc:
        raise RuntimeError(
            "Track-A token materialization requires the local-gpu transformers extra"
        ) from exc
    if transformers.__version__ != config.loading.library_revision:
        raise ValueError("Track-A installed transformers version differs from its pin")
    tokenizer_metadata_file = snapshot / "tokenizer_config.json"
    metadata = _json_object(
        tokenizer_metadata_file.read_bytes(),
        "Track-A official tokenizer_config.json",
    )
    if metadata.get("tokenizer_class") != "TokenizersBackend":
        raise ValueError("Track-A official tokenizer metadata class drifted")
    eos_token = metadata.get("eos_token")
    pad_token = metadata.get("pad_token")
    special_tokens = metadata.get("extra_special_tokens")
    model_max_length = metadata.get("model_max_length")
    if (
        not isinstance(eos_token, str)
        or not isinstance(pad_token, str)
        or not isinstance(special_tokens, list)
        or not special_tokens
        or not all(isinstance(item, str) and item for item in special_tokens)
        or not isinstance(model_max_length, int)
        or model_max_length <= 0
    ):
        raise ValueError("Track-A official tokenizer metadata is incomplete")
    chat_template = (snapshot / config.loading.chat_template_file).read_text(encoding="utf-8")
    if not chat_template:
        raise ValueError("Track-A official chat template is empty")
    # Direct tokenizer-file construction is deliberate: no AutoTokenizer and no
    # dynamic model code can run, even though upstream metadata names a newer class.
    return PreTrainedTokenizerFast(
        tokenizer_file=str(snapshot / config.loading.tokenizer_file),
        chat_template=chat_template,
        eos_token=eos_token,
        pad_token=pad_token,
        additional_special_tokens=special_tokens,
        model_max_length=model_max_length,
    )


def _load_mapping(path: Path, label: str) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return payload


def _json_object(raw: bytes, label: str) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value!r}")


def _regular_file(root: Path, path: str | Path) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink():
        raise ValueError("Track-A inputs cannot be symlinks")
    resolved = source.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Track-A inputs must stay inside the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Track-A input is not a bounded regular file")
    return resolved


def _bound_file(root: Path, binding: TrackADecisionFileBinding) -> Path:
    path = _regular_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("Track-A file binding hash mismatch")
    return path


def _bound_ai_file(root: Path, binding: AIPreferenceFileBinding) -> Path:
    path = _regular_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("Track-A AI preference file binding hash mismatch")
    return path


def _bound_suite_root_file(root: Path, locator: str, expected_sha256: str) -> Path:
    path = _regular_file(root, locator)
    if _sha256(path) != expected_sha256:
        raise ValueError("Track-A suite root binding hash mismatch")
    return path


def _bound_suite_relative_file(base: Path, locator: str, expected_sha256: str) -> Path:
    relative = PurePosixPath(locator)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Track-A suite-relative binding is unsafe")
    candidate = base.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise ValueError("Track-A suite-relative file cannot be a symlink")
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(base.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("Track-A suite-relative file escapes the suite directory") from exc
    if not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Track-A suite-relative input is not a bounded file")
    if _sha256(path) != expected_sha256:
        raise ValueError("Track-A suite-relative binding hash mismatch")
    return path


def _new_target(root: Path, path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Track-A output must stay inside the evidence root") from exc
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _binding(root: Path, path: Path) -> TrackADecisionFileBinding:
    return TrackADecisionFileBinding(
        path=path.relative_to(root).as_posix(),
        sha256=_sha256(path),
    )


def _human_binding(root: Path, path: Path) -> HumanStudyFileBinding:
    return HumanStudyFileBinding(
        path=path.relative_to(root).as_posix(),
        sha256=_sha256(path),
    )


def _ai_binding(root: Path, path: Path) -> AIPreferenceFileBinding:
    return AIPreferenceFileBinding(
        path=path.relative_to(root).as_posix(),
        sha256=_sha256(path),
    )


def _workspace_binding(
    root: Path,
    target: Path,
    workspace: Path,
    relative: Path,
) -> TrackADecisionFileBinding:
    return TrackADecisionFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=_sha256(workspace / relative),
    )


def _human_workspace_binding(
    root: Path,
    target: Path,
    workspace: Path,
    relative: Path,
) -> HumanStudyFileBinding:
    return HumanStudyFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=_sha256(workspace / relative),
    )


def _ai_workspace_binding(
    root: Path,
    target: Path,
    workspace: Path,
    relative: Path,
) -> AIPreferenceFileBinding:
    return AIPreferenceFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=_sha256(workspace / relative),
    )


def _write_failure(
    target: Path,
    error: BaseException,
    batch: TrackADecisionBatch,
    completed: list[TrackADecisionCompletedCall],
    attempted_call_id: str | None,
) -> None:
    evidence = [
        {
            "path": path.relative_to(target).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(target.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.name != "FAILED.json"
    ]
    _write_json(
        target / "FAILED.json",
        {
            "schema_version": "1.0",
            "error_type": type(error).__name__,
            "message": "Track-A batch stopped terminally without retry or resampling.",
            "planned_case_count": batch.planned_case_count,
            "eligible_case_count": batch.eligible_case_count,
            "fully_executed_case_count": len(completed) // 3,
            "planned_call_count": batch.planned_call_count,
            "eligible_call_count": batch.eligible_call_count,
            "executed_call_count": len(completed),
            "failed_or_interrupted_call_id": attempted_call_id,
            "partial_case_call_count": len(completed) % 3,
            "completed_call_ids": [item.call_id for item in completed],
            "preserved_evidence": evidence,
            "admissible_recording_emitted": False,
            "automatic_retry_performed": False,
            "replacement_or_resample_call_performed": False,
            "same_output_directory_reusable": False,
        },
    )


def _require_disjoint_bridge_outputs(*paths: Path) -> None:
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError("Track-A bridge output paths must be disjoint")


def _write_json(path: Path, payload: object) -> None:
    _write_bytes(
        path,
        (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
    )


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "TrackAAIPreferenceBridgeReport",
    "TrackADecisionBackendConfig",
    "TrackADecisionBatch",
    "TrackADecisionCall",
    "TrackADecisionCallBudget",
    "TrackADecisionCompletedCall",
    "TrackADecisionExecutionBudget",
    "TrackADecisionExecutionReceipt",
    "TrackADecisionFileBinding",
    "TrackADecisionObservation",
    "TrackADecisionPreparation",
    "TrackADecisionRun",
    "TrackAInputTokenCount",
    "TrackAInputTokenManifest",
    "TrackAInputTokenTrace",
    "TrackARawDecision",
    "TrackATokenManifestMaterialization",
    "TrackATokenizerAssetAttestation",
    "TrackATokenizerMaterializationConfig",
    "TrackATokenizerTemplateArguments",
    "bridge_track_a_run_to_ai_preference",
    "execute_track_a_decision_batch",
    "load_track_a_decision_backend_config",
    "load_track_a_decision_batch",
    "load_track_a_decision_budget",
    "load_track_a_decision_run",
    "load_track_a_input_token_manifest",
    "load_track_a_tokenizer_materialization_config",
    "materialize_track_a_input_token_manifest",
    "prepare_track_a_decision_batch",
]

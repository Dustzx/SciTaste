"""Bounded execution, adjudication, and analysis for AI-only H1/H2 panels."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.evaluation.ai_preference_panel import (
    AIAdjudicationRequest,
    AIBlindPreference,
    AINormalizedPreferenceRow,
    AIPreferenceDisposition,
    AIPreferenceFileBinding,
    AIPreferenceModelIdentity,
    AIPreferencePrimaryRequest,
    AIPreferenceRequestPack,
    AIRawPreferenceResponse,
    AIReviewExecutionReceipt,
    AIReviewUsage,
    LockedAIPreferenceReviewSet,
    load_ai_preference_request_pack,
)
from scitaste.evaluation.human_outcomes import (
    HumanBlindKey,
    HumanOutcomeStudyManifest,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    load_human_outcome_study,
)
from scitaste.model_nodes.models import ModelCostProvenance

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 256 * 1_048_576
_PRIVATE_NAMES = {"private", "blind-key.json", "generation-ledger.json", "blinding-secret.json"}


class AIPreferenceCallBudget(BaseModel):
    model_config = _CONFIG

    max_request_bytes: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    max_latency_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def total_is_bounded(self) -> AIPreferenceCallBudget:
        if self.max_total_tokens > self.max_input_tokens + self.max_output_tokens:
            raise ValueError("AI preference per-call total exceeds input plus output ceilings")
        return self


class AIPreferenceExecutionBudget(BaseModel):
    """One immutable call-count and resource envelope."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    budget_id: str = Field(pattern=_ID)
    phase: Literal["primary", "adjudicator"]
    maximum_calls: Literal[1, 2]
    per_call: AIPreferenceCallBudget
    max_total_tokens: int = Field(gt=0)
    max_total_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    max_retries: Literal[0] = 0
    successful_identity_called_at_most_once: Literal[True] = True
    failed_call_automatically_retried: Literal[False] = False

    @model_validator(mode="after")
    def phase_call_count_matches(self) -> AIPreferenceExecutionBudget:
        expected = 2 if self.phase == "primary" else 1
        if self.maximum_calls != expected:
            raise ValueError("AI preference execution call ceiling must equal its phase size")
        if self.per_call.max_total_tokens * expected > self.max_total_tokens:
            raise ValueError("AI preference reserved calls exceed the total token ceiling")
        if self.per_call.max_cost_usd * expected > self.max_total_cost_usd + 1e-12:
            raise ValueError("AI preference reserved calls exceed the total cost ceiling")
        return self

    @computed_field
    @property
    def budget_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"budget_sha256"}))


class AIPreferenceBackendConfig(BaseModel):
    """Secret-free OpenAI-compatible or local handoff configuration."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    config_id: str = Field(pattern=_ID)
    mode: Literal["openai-compatible", "local-execution-request"]
    provider: str = Field(min_length=1, max_length=200)
    base_url: str | None = None
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    live_enabled: bool = False
    timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    max_retries: Literal[0] = 0
    max_output_tokens: int = Field(gt=0)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    pricing: ModelCostProvenance
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def configuration_is_secret_free_and_coherent(self) -> AIPreferenceBackendConfig:
        if self.extra_headers:
            raise ValueError("AI preference backend forbids configured extra headers")
        if self.extra_body:
            raise ValueError("AI preference backend forbids configured extra body fields")
        if self.mode == "openai-compatible":
            if not self.live_enabled or self.base_url is None or self.api_key_env is None:
                raise ValueError("live AI preference backend requires URL, env key, and opt-in")
            parsed = urlparse(self.base_url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
                raise ValueError("AI preference endpoint must use HTTPS except localhost")
            if not parsed.hostname or parsed.username or parsed.password or parsed.query:
                raise ValueError("AI preference endpoint cannot contain credentials or a query")
        else:
            if self.live_enabled or self.base_url is not None or self.api_key_env is not None:
                raise ValueError("local execution request cannot enable network credentials")
        return self

    @computed_field
    @property
    def identity_sha256(self) -> str:
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
            self.model_dump(mode="json", exclude={"config_sha256", "identity_sha256"})
        )


@dataclass(frozen=True)
class AIPreferenceHTTPResponse:
    status_code: int
    raw_body: bytes


class AIPreferenceHTTPTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
    ) -> AIPreferenceHTTPResponse: ...


class HttpxAIPreferenceTransport:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
    ) -> AIPreferenceHTTPResponse:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, content=content)
        return AIPreferenceHTTPResponse(status_code=response.status_code, raw_body=response.content)


class AIPreferenceExecutionItem(BaseModel):
    model_config = _CONFIG

    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    raw_http_body_sha256: str = Field(pattern=_SHA256)
    raw_response_sha256: str = Field(pattern=_SHA256)
    execution_receipt_sha256: str = Field(pattern=_SHA256)
    usage_sha256: str = Field(pattern=_SHA256)
    cost_sha256: str = Field(pattern=_SHA256)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)


class AIPreferenceExecutionRun(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    execution_id: str = Field(pattern=_ID)
    phase: Literal["primary", "adjudicator"]
    source_request_sha256: str = Field(pattern=_SHA256)
    budget_sha256: str = Field(pattern=_SHA256)
    budget_file_sha256: str = Field(pattern=_SHA256)
    completed: tuple[AIPreferenceExecutionItem, ...] = Field(min_length=1, max_length=2)
    call_count: int = Field(gt=0, le=2)
    total_tokens: int = Field(ge=0)
    total_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    completed_at: datetime
    max_retries: Literal[0] = 0
    successful_identity_called_at_most_once: Literal[True] = True
    failed_call_automatically_retried: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def run_is_complete(self) -> AIPreferenceExecutionRun:
        if self.completed_at.utcoffset() is None:
            raise ValueError("AI preference execution timestamp must include a timezone")
        expected = 2 if self.phase == "primary" else 1
        if self.call_count != expected:
            raise ValueError("AI preference successful run does not contain its exact phase calls")
        if self.call_count != len(self.completed):
            raise ValueError("AI preference call count differs from completed identities")
        if len({item.reviewer_identity_sha256 for item in self.completed}) != self.call_count:
            raise ValueError("AI preference execution repeats a successful identity")
        if self.total_tokens != sum(
            item.input_tokens + item.output_tokens for item in self.completed
        ):
            raise ValueError("AI preference execution total token count mismatch")
        if abs(self.total_cost_usd - sum(item.cost_usd for item in self.completed)) > 1e-12:
            raise ValueError("AI preference execution total cost mismatch")
        return self

    @computed_field
    @property
    def run_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"run_sha256"}))


class AILocalExecutionRequest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request: AIPreferenceFileBinding
    request_sha256: str = Field(pattern=_SHA256)
    backend_config: AIPreferenceFileBinding
    backend_config_sha256: str = Field(pattern=_SHA256)
    budget: AIPreferenceFileBinding
    budget_sha256: str = Field(pattern=_SHA256)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    network_call_performed: Literal[False] = False
    local_model_loaded: Literal[False] = False
    authorizes_local_execution: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True


class AIRawAdjudicationItem(BaseModel):
    model_config = _CONFIG

    dispute_id: str = Field(pattern=_ID)
    response: Literal["X", "tie", "Y", "cannot-assess"]
    rationale: str = Field(min_length=1, max_length=40_000)
    missingness_reason_code: str | None = Field(default=None, pattern=_ID)

    @model_validator(mode="after")
    def missingness_matches(self) -> AIRawAdjudicationItem:
        if (self.response == "cannot-assess") != (self.missingness_reason_code is not None):
            raise ValueError("AI adjudicator cannot-assess requires exactly one reason")
        return self


class AIRawAdjudicationResponse(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    response_schema: Literal["scitaste-ai-adjudication-response-v1"]
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    responses: tuple[AIRawAdjudicationItem, ...] = Field(min_length=1, max_length=100_000)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def dispute_ids_are_unique(self) -> AIRawAdjudicationResponse:
        _require_unique((item.dispute_id for item in self.responses), "AI adjudicator disputes")
        return self


class AIFinalPreferenceBlock(BaseModel):
    model_config = _CONFIG

    block_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    primary_row_sha256s: tuple[str, str]
    resolution_source: Literal["primary-ai-agreement", "ai-adjudicator"]
    disposition: AIPreferenceDisposition
    selected_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    tie: bool
    adjudicator_response_sha256: str | None = Field(default=None, pattern=_SHA256)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    block_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def block_is_consistent_and_self_hashed(self) -> AIFinalPreferenceBlock:
        if self.tie and self.selected_output_sha256 is not None:
            raise ValueError("AI final tie cannot select one output")
        if self.disposition is AIPreferenceDisposition.CANNOT_ASSESS and (
            self.tie or self.selected_output_sha256 is not None
        ):
            raise ValueError("unassessable AI block cannot contain a preference")
        if self.disposition is AIPreferenceDisposition.COMPLETED and (
            not self.tie and self.selected_output_sha256 is None
        ):
            raise ValueError("completed non-tie AI block must select an output")
        if (self.resolution_source == "ai-adjudicator") != (
            self.adjudicator_response_sha256 is not None
        ):
            raise ValueError("AI final resolution source and adjudicator evidence disagree")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"block_sha256"}))
        if self.block_sha256 != expected:
            raise ValueError("AI final preference block hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AIFinalPreferenceBlock:
        payload = dict(values)
        payload.pop("block_sha256", None)
        unsigned = cls.model_construct(block_sha256="0" * 64, **payload)
        return cls(
            **payload,
            block_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"block_sha256"})
            ),
        )


class LockedAIFinalPreferenceReviewSet(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    final_lock_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    primary_review_set: AIPreferenceFileBinding
    primary_review_set_sha256: str = Field(pattern=_SHA256)
    blocks: tuple[AIFinalPreferenceBlock, ...] = Field(min_length=2, max_length=100_000)
    adjudicator_request: AIPreferenceFileBinding | None = None
    adjudicator_raw_response: AIPreferenceFileBinding | None = None
    adjudicator_execution_receipt: AIPreferenceFileBinding | None = None
    locked_at: datetime
    all_disputes_resolved_or_explicitly_unassessable: Literal[True] = True
    operational_review_gate_satisfied: Literal[True] = True
    condition_identity_hidden_until_final_lock: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False
    human_consent_obtained: Literal[False] = False

    @model_validator(mode="after")
    def final_lock_is_coherent(self) -> LockedAIFinalPreferenceReviewSet:
        if self.locked_at.utcoffset() is None:
            raise ValueError("AI final review lock timestamp must include a timezone")
        bindings = (
            self.adjudicator_request,
            self.adjudicator_raw_response,
            self.adjudicator_execution_receipt,
        )
        if any(item is None for item in bindings) and any(item is not None for item in bindings):
            raise ValueError("AI adjudication evidence must be entirely present or absent")
        _require_unique((item.block_id for item in self.blocks), "AI final block IDs")
        _require_unique(
            ((item.hypothesis, item.case_id) for item in self.blocks),
            "AI final hypothesis/case blocks",
        )
        return self

    @computed_field
    @property
    def final_review_set_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"final_review_set_sha256"}))


class AIConditionFileBinding(BaseModel):
    """Post-lock binding that may intentionally address committed private evidence."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> AIConditionFileBinding:
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("AI condition-opening binding must be relative")
        return self


class AIPairedAnalysisRow(BaseModel):
    model_config = _CONFIG

    block_sha256: str = Field(pattern=_SHA256)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    treatment_condition: Literal["matched-abstracted-taste"] = "matched-abstracted-taste"
    comparator_condition: TasteStudyCondition
    preferred_condition: TasteStudyCondition | None
    treatment_preference_score: float | None = Field(default=None, ge=0, le=1)
    disposition: AIPreferenceDisposition


class AIPairedAnalysisInput(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    analysis_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    final_review_set: AIPreferenceFileBinding
    final_review_set_sha256: str = Field(pattern=_SHA256)
    blind_key: AIConditionFileBinding
    blind_key_sha256: str = Field(pattern=_SHA256)
    opened_at: datetime
    rows: tuple[AIPairedAnalysisRow, ...] = Field(min_length=2, max_length=100_000)
    condition_mapping_opened_after_final_ai_lock: Literal[True] = True
    endpoint_kind: Literal["ai-only-paired-preference"] = "ai-only-paired-preference"
    human_or_expert_endpoint: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def opening_is_temporally_valid(self) -> AIPairedAnalysisInput:
        if self.opened_at.utcoffset() is None:
            raise ValueError("AI paired analysis opening timestamp must include a timezone")
        return self

    @computed_field
    @property
    def analysis_input_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"analysis_input_sha256"}))


class AIHypothesisPreferenceResult(BaseModel):
    model_config = _CONFIG

    hypothesis: TasteMechanismHypothesis
    comparator_condition: TasteStudyCondition
    assessable_count: int = Field(ge=0)
    treatment_win_count: int = Field(ge=0)
    comparator_win_count: int = Field(ge=0)
    tie_count: int = Field(ge=0)
    cannot_assess_count: int = Field(ge=0)
    treatment_preference_rate: float | None = Field(default=None, ge=0, le=1)


class AIPairedAnalysisResult(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    analysis_id: str = Field(pattern=_ID)
    analysis_input_sha256: str = Field(pattern=_SHA256)
    hypothesis_results: tuple[AIHypothesisPreferenceResult, AIHypothesisPreferenceResult]
    source_group_count: int = Field(gt=0)
    endpoint_kind: Literal["ai-only-paired-preference"] = "ai-only-paired-preference"
    human_or_expert_endpoint: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    descriptive_only: Literal[True] = True
    operational_review_gate_satisfied: Literal[True] = True

    @computed_field
    @property
    def result_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))


def load_ai_preference_backend_config(path: str | Path) -> AIPreferenceBackendConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI preference backend config must be a mapping")
    return AIPreferenceBackendConfig.model_validate(payload)


def load_ai_preference_execution_budget(path: str | Path) -> AIPreferenceExecutionBudget:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI preference execution budget must be a mapping")
    return AIPreferenceExecutionBudget.model_validate(payload)


def execute_ai_preference_primary_panel(
    *,
    evidence_root: str | Path,
    request_pack_path_or_dir: str | Path,
    backend_config_paths: tuple[str | Path, str | Path],
    budget_path: str | Path,
    output_dir: str | Path,
    allow_live: bool = False,
    transports: dict[str, AIPreferenceHTTPTransport] | None = None,
) -> AIPreferenceExecutionRun:
    """Execute exactly two primary calls under one pre-reserved total envelope."""

    root = Path(evidence_root).resolve(strict=True)
    pack_path = _resolve_pack(root, request_pack_path_or_dir)
    pack = load_ai_preference_request_pack(pack_path)
    _bound_public_file(root, pack.study)
    _bound_public_file(root, pack.benchmark_suite)
    _bound_public_file(root, pack.protocol)
    budget_file = _regular_public_file(root, budget_path)
    budget_file_sha256 = _sha256(budget_file)
    budget = load_ai_preference_execution_budget(budget_file)
    if budget.phase != "primary":
        raise ValueError("AI primary execution requires a primary budget")
    requests = _load_primary_requests(pack, root)
    configs = _load_execution_configs(root, backend_config_paths)
    if set(configs) != set(requests):
        raise ValueError("AI primary backend configs do not cover the two request identities")
    if not allow_live:
        raise ValueError("AI primary execution requires --allow-live")
    _preauthorize_online_calls(requests, configs, budget)
    _require_environment_keys(config for _, config in configs.values())
    target = _new_public_target(root, output_dir)
    target.mkdir(parents=True, exist_ok=False)
    completed: list[AIPreferenceExecutionItem] = []
    try:
        for reviewer_id in sorted(requests):
            completed.append(
                _execute_online_request(
                    root=root,
                    output_root=target,
                    request_file=requests[reviewer_id][0],
                    request=requests[reviewer_id][1],
                    reviewer=requests[reviewer_id][1].reviewer,
                    config_file=configs[reviewer_id][0],
                    config=configs[reviewer_id][1],
                    budget=budget.per_call,
                    response_kind="primary",
                    transport=(transports or {}).get(reviewer_id),
                )
            )
        if _sha256(budget_file) != budget_file_sha256:
            raise ValueError("AI primary execution budget changed during provider calls")
        run = _execution_run(
            execution_id=f"ai-primary-{pack.pack_sha256[:20]}",
            phase="primary",
            source_request_sha256=pack.pack_sha256,
            budget=budget,
            budget_file_sha256=budget_file_sha256,
            completed=completed,
        )
        _write_json(target / "RUN.json", run.model_dump(mode="json", exclude={"run_sha256"}))
    except BaseException as exc:
        _write_failure(target, exc, completed)
        raise
    return run


def execute_ai_preference_adjudicator(
    *,
    evidence_root: str | Path,
    adjudicator_request_path: str | Path,
    backend_config_path: str | Path,
    budget_path: str | Path,
    output_dir: str | Path,
    allow_live: bool = False,
    transport: AIPreferenceHTTPTransport | None = None,
) -> AIPreferenceExecutionRun | AILocalExecutionRequest:
    """Execute one third-identity call or emit a non-authorizing local handoff."""

    root = Path(evidence_root).resolve(strict=True)
    request_file = _regular_public_file(root, adjudicator_request_path)
    request = AIAdjudicationRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
    config_file = _regular_public_file(root, backend_config_path)
    config = load_ai_preference_backend_config(config_file)
    budget_file = _regular_public_file(root, budget_path)
    budget_file_sha256 = _sha256(budget_file)
    budget = load_ai_preference_execution_budget(budget_file)
    if budget.phase != "adjudicator":
        raise ValueError("AI adjudicator execution requires an adjudicator budget")
    _verify_backend_identity(request.adjudicator, config)
    target = _new_public_target(root, output_dir)
    if config.mode == "local-execution-request":
        if config.max_output_tokens > budget.per_call.max_output_tokens:
            raise ValueError("local AI request output envelope exceeds its budget")
        if (
            len(_canonical_json_bytes(request.model_dump(mode="json")))
            > budget.per_call.max_request_bytes
        ):
            raise ValueError("local AI request bytes exceed its budget")
        target.mkdir(parents=True, exist_ok=False)
        handoff = AILocalExecutionRequest(
            request=_binding(root, request_file),
            request_sha256=request.request_sha256,
            backend_config=_binding(root, config_file),
            backend_config_sha256=config.config_sha256,
            budget=_binding(root, budget_file),
            budget_sha256=budget.budget_sha256,
            reviewer_identity_sha256=config.identity_sha256,
        )
        _write_json(target / "LOCAL_EXECUTION_REQUEST.json", handoff.model_dump(mode="json"))
        return handoff
    if not allow_live:
        raise ValueError("online AI adjudicator execution requires --allow-live")
    _preauthorize_online_call(request, config, budget.per_call)
    _require_environment_keys((config,))
    target.mkdir(parents=True, exist_ok=False)
    try:
        item = _execute_online_request(
            root=root,
            output_root=target,
            request_file=request_file,
            request=request,
            reviewer=request.adjudicator,
            config_file=config_file,
            config=config,
            budget=budget.per_call,
            response_kind="adjudicator",
            transport=transport,
        )
        if _sha256(budget_file) != budget_file_sha256:
            raise ValueError("AI adjudicator execution budget changed during provider call")
        run = _execution_run(
            execution_id=f"ai-adjudicator-{request.request_sha256[:20]}",
            phase="adjudicator",
            source_request_sha256=request.request_sha256,
            budget=budget,
            budget_file_sha256=budget_file_sha256,
            completed=[item],
        )
        _write_json(target / "RUN.json", run.model_dump(mode="json", exclude={"run_sha256"}))
    except BaseException as exc:
        _write_failure(target, exc, [])
        raise
    return run


def finalize_ai_preference_reviews(
    *,
    evidence_root: str | Path,
    primary_review_set_path: str | Path,
    output_path: str | Path,
    adjudicator_request_path: str | Path | None = None,
    adjudicator_raw_response_path: str | Path | None = None,
    adjudicator_execution_receipt_path: str | Path | None = None,
    locked_at: datetime | None = None,
) -> LockedAIFinalPreferenceReviewSet:
    """Import disputed-only adjudication and lock one AI-only outcome per block."""

    root = Path(evidence_root).resolve(strict=True)
    primary_file = _regular_public_file(root, primary_review_set_path)
    primary = LockedAIPreferenceReviewSet.model_validate_json(
        primary_file.read_text(encoding="utf-8")
    )
    _verify_primary_lock_bindings(root, primary)
    supplied = (
        adjudicator_request_path,
        adjudicator_raw_response_path,
        adjudicator_execution_receipt_path,
    )
    if bool(primary.disputes) != all(item is not None for item in supplied):
        raise ValueError("AI adjudication evidence is required exactly when disputes exist")
    if any(item is not None for item in supplied) and not all(
        item is not None for item in supplied
    ):
        raise ValueError("AI adjudication import requires request, raw response, and receipt")
    adjudication: dict[str, AIRawAdjudicationItem] = {}
    request_binding = raw_binding = receipt_binding = None
    request = None
    response_file_sha = None
    timestamp = locked_at or datetime.now(UTC)
    if primary.disputes:
        assert all(item is not None for item in supplied)
        request_file = _regular_public_file(root, adjudicator_request_path)  # type: ignore[arg-type]
        raw_file = _regular_public_file(root, adjudicator_raw_response_path)  # type: ignore[arg-type]
        receipt_file = _regular_public_file(  # type: ignore[arg-type]
            root, adjudicator_execution_receipt_path
        )
        request = AIAdjudicationRequest.model_validate_json(
            request_file.read_text(encoding="utf-8")
        )
        response = AIRawAdjudicationResponse.model_validate_json(
            raw_file.read_text(encoding="utf-8")
        )
        receipt = AIReviewExecutionReceipt.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
        _verify_adjudication_import(
            root, primary, request_file, request, raw_file, response, receipt
        )
        if timestamp < receipt.completed_at:
            raise ValueError("AI final lock cannot precede adjudicator completion")
        adjudication = {item.dispute_id: item for item in response.responses}
        request_binding = _binding(root, request_file)
        raw_binding = _binding(root, raw_file)
        receipt_binding = _binding(root, receipt_file)
        response_file_sha = _sha256(raw_file)
    blocks = _final_blocks(primary, request, adjudication, response_file_sha)
    final_identity = _canonical_sha256([primary.review_set_sha256, timestamp.isoformat()])
    final = LockedAIFinalPreferenceReviewSet(
        final_lock_id=f"ai-final-{final_identity[:24]}",
        study_id=primary.study_id,
        study_sha256=primary.study_sha256,
        primary_review_set=_binding(root, primary_file),
        primary_review_set_sha256=primary.review_set_sha256,
        blocks=blocks,
        adjudicator_request=request_binding,
        adjudicator_raw_response=raw_binding,
        adjudicator_execution_receipt=receipt_binding,
        locked_at=timestamp,
    )
    output = _new_public_file(root, output_path)
    _write_json(
        output,
        final.model_dump(mode="json", exclude={"final_review_set_sha256"}),
    )
    return final


def analyze_ai_paired_preferences(
    *,
    evidence_root: str | Path,
    study_path: str | Path,
    final_review_set_path: str | Path,
    blind_key_path: str | Path,
    analysis_input_path: str | Path,
    result_path: str | Path,
    opened_at: datetime | None = None,
) -> tuple[AIPairedAnalysisInput, AIPairedAnalysisResult]:
    """Open the committed condition map after final AI lock and compute descriptive H1/H2."""

    root = Path(evidence_root).resolve(strict=True)
    study_file = _regular_public_file(root, study_path)
    final_file = _regular_public_file(root, final_review_set_path)
    study = load_human_outcome_study(study_file)
    final = LockedAIFinalPreferenceReviewSet.model_validate_json(
        final_file.read_text(encoding="utf-8")
    )
    _verify_final_public_chain(root, study, final)
    timestamp = opened_at or datetime.now(UTC)
    if timestamp <= final.locked_at:
        raise ValueError("AI condition mapping may open only after the final AI lock")
    # This is deliberately the first private-path read in the AI analysis path.
    key_file = _regular_condition_file(root, blind_key_path)
    key = HumanBlindKey.model_validate_json(key_file.read_text(encoding="utf-8"))
    if (
        key.blind_key_sha256 != study.blind_key_sha256
        or key.study_id != study.study_id
        or key.assignment_sha256 != study.assignment_sha256
    ):
        raise ValueError("AI paired analysis blind key does not match the public commitment")
    if key.created_at > final.locked_at:
        raise ValueError("AI paired analysis condition map was not committed before final lock")
    rows = _unblind_final_blocks(study, final, key)
    analysis_identity = _canonical_sha256([final.final_review_set_sha256, key.blind_key_sha256])
    analysis = AIPairedAnalysisInput(
        analysis_id=f"ai-paired-{analysis_identity[:24]}",
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        final_review_set=_binding(root, final_file),
        final_review_set_sha256=final.final_review_set_sha256,
        blind_key=AIConditionFileBinding(
            path=key_file.relative_to(root).as_posix(), sha256=_sha256(key_file)
        ),
        blind_key_sha256=key.blind_key_sha256,
        opened_at=timestamp,
        rows=rows,
    )
    result = _analyze_rows(analysis)
    analysis_target = _new_public_file(root, analysis_input_path)
    result_target = _new_public_file(root, result_path)
    _write_json(
        analysis_target,
        analysis.model_dump(mode="json", exclude={"analysis_input_sha256"}),
    )
    _write_json(result_target, result.model_dump(mode="json", exclude={"result_sha256"}))
    return analysis, result


def _execute_online_request(
    *,
    root: Path,
    output_root: Path,
    request_file: Path,
    request: AIPreferencePrimaryRequest | AIAdjudicationRequest,
    reviewer: AIPreferenceModelIdentity,
    config_file: Path,
    config: AIPreferenceBackendConfig,
    budget: AIPreferenceCallBudget,
    response_kind: Literal["primary", "adjudicator"],
    transport: AIPreferenceHTTPTransport | None,
) -> AIPreferenceExecutionItem:
    _verify_backend_identity(reviewer, config)
    request_file_sha256 = _sha256(request_file)
    config_file_sha256 = _sha256(config_file)
    api_key = os.getenv(config.api_key_env or "")
    if api_key is None or not api_key.strip():
        raise RuntimeError(f"missing API key environment variable {config.api_key_env}")
    directory = output_root / reviewer.reviewer_id
    directory.mkdir(parents=True, exist_ok=False)
    payload = _chat_payload(request, config)
    payload_bytes = _canonical_json_bytes(payload)
    if len(payload_bytes) > budget.max_request_bytes:
        raise ValueError("AI preference HTTP request exceeds its byte ceiling")
    http_request = directory / "http-request.json"
    _write_bytes(http_request, payload_bytes)
    endpoint = f"{(config.base_url or '').rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
        **config.extra_headers,
    }
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    response = (transport or HttpxAIPreferenceTransport()).post(
        endpoint,
        headers=headers,
        content=payload_bytes,
        timeout=config.timeout_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    completed_at = datetime.now(UTC)
    raw_http = directory / "provider-response.body"
    _write_bytes(raw_http, response.raw_body)
    if response.status_code < 200 or response.status_code >= 300:
        raise ValueError(f"AI preference provider returned HTTP {response.status_code}")
    envelope = _json_object(response.raw_body, "provider HTTP response")
    provider_model, provider_request_id, content, usage = _parse_provider_envelope(envelope, config)
    if provider_model not in {config.model, config.model_revision}:
        raise ValueError("AI preference provider returned another model identity")
    raw_response = directory / "raw-response.json"
    _write_bytes(raw_response, content.encode("utf-8"))
    if response_kind == "primary":
        parsed = AIRawPreferenceResponse.model_validate_json(content)
        if (
            parsed.reviewer_id != reviewer.reviewer_id
            or parsed.reviewer_identity_sha256 != reviewer.identity_sha256
            or parsed.request_sha256 != request.request_sha256
        ):
            raise ValueError("AI primary provider content binds another request or identity")
    else:
        parsed = AIRawAdjudicationResponse.model_validate_json(content)
        if (
            parsed.reviewer_id != reviewer.reviewer_id
            or parsed.reviewer_identity_sha256 != reviewer.identity_sha256
            or parsed.request_sha256 != request.request_sha256
        ):
            raise ValueError("AI adjudicator content binds another request or identity")
    review_usage = _review_usage(usage, config.pricing)
    if (
        review_usage.input_tokens > budget.max_input_tokens
        or review_usage.output_tokens > budget.max_output_tokens
        or review_usage.total_tokens > budget.max_total_tokens
        or review_usage.cost_usd > budget.max_cost_usd
        or latency_ms > budget.max_latency_ms
    ):
        raise ValueError("AI preference provider telemetry exceeds its per-call ceiling")
    if _sha256(request_file) != request_file_sha256:
        raise ValueError("AI preference request changed during provider execution")
    if _sha256(config_file) != config_file_sha256:
        raise ValueError("AI preference backend config changed during provider execution")
    receipt = AIReviewExecutionReceipt(
        invocation_id=f"invoke-{reviewer.reviewer_id}-{request.request_sha256[:16]}",
        reviewer_id=reviewer.reviewer_id,
        provider=config.provider,
        model=config.model,
        model_revision=config.model_revision,
        reviewer_identity_sha256=reviewer.identity_sha256,
        backend_config=_binding(root, config_file),
        request=_binding(root, request_file),
        request_sha256=request.request_sha256,
        http_request=_binding(root, http_request),
        raw_http_body=_binding(root, raw_http),
        raw_response=_binding(root, raw_response),
        provider_request_id=provider_request_id,
        started_at=started_at,
        completed_at=completed_at,
        http_status=response.status_code,
        usage=review_usage,
    )
    receipt_file = directory / "RECEIPT.json"
    _write_json(receipt_file, receipt.model_dump(mode="json"))
    return AIPreferenceExecutionItem(
        reviewer_id=reviewer.reviewer_id,
        reviewer_identity_sha256=reviewer.identity_sha256,
        request_sha256=request.request_sha256,
        raw_http_body_sha256=_sha256(raw_http),
        raw_response_sha256=_sha256(raw_response),
        execution_receipt_sha256=_sha256(receipt_file),
        usage_sha256=review_usage.usage_sha256,
        cost_sha256=review_usage.cost_sha256,
        input_tokens=review_usage.input_tokens,
        output_tokens=review_usage.output_tokens,
        cost_usd=review_usage.cost_usd,
    )


def _chat_payload(
    request: AIPreferencePrimaryRequest | AIAdjudicationRequest,
    config: AIPreferenceBackendConfig,
) -> dict[str, JsonValue]:
    response_kind = request.required_response_schema
    system = (
        "You are one independent AI scientific-preference assessor, not a human or expert "
        "participant. Conditions and other reviewers' outputs are hidden. Return exactly one "
        f"JSON object following {response_kind}; do not use Markdown fences."
    )
    user = json.dumps(
        request.model_dump(mode="json", exclude={"request_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload: dict[str, JsonValue] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": config.max_output_tokens,
        "temperature": config.temperature,
    }
    payload.update(config.extra_body)
    return payload


def _parse_provider_envelope(
    payload: dict[str, JsonValue], config: AIPreferenceBackendConfig
) -> tuple[str, str, str, dict[str, JsonValue]]:
    request_id = payload.get("id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("AI preference provider response lacks a request ID")
    provider_model = payload.get("model", config.model)
    if not isinstance(provider_model, str) or not provider_model:
        raise ValueError("AI preference provider response lacks model identity")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("AI preference provider response requires exactly one choice")
    choice = choices[0]
    if choice.get("finish_reason") != "stop" or not isinstance(choice.get("message"), dict):
        raise ValueError("AI preference provider response is not a completed message")
    content = choice["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI preference provider response has no JSON content")
    _json_object(content.encode("utf-8"), "provider message content")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("AI preference provider response lacks usage telemetry")
    return provider_model, request_id, content, usage


def _review_usage(raw: dict[str, JsonValue], pricing: ModelCostProvenance) -> AIReviewUsage:
    input_tokens = _token_alias(raw, ("prompt_tokens", "input_tokens"), "input")
    output_tokens = _token_alias(raw, ("completion_tokens", "output_tokens"), "output")
    reported_total = raw.get("total_tokens")
    if reported_total is not None and (
        type(reported_total) is not int or reported_total != input_tokens + output_tokens
    ):
        raise ValueError("AI preference provider total token usage conflicts")
    cached_values: list[int] = []
    for name in ("prompt_tokens_details", "input_tokens_details"):
        details = raw.get(name)
        if isinstance(details, dict) and "cached_tokens" in details:
            value = details["cached_tokens"]
            if type(value) is not int or value < 0:
                raise ValueError("AI preference cached token usage is invalid")
            cached_values.append(value)
    for name in ("prompt_cache_hit_tokens", "cache_read_input_tokens"):
        value = raw.get(name)
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError("AI preference cached token usage is invalid")
            cached_values.append(value)
    if len(set(cached_values)) > 1:
        raise ValueError("AI preference cached token aliases conflict")
    cached = cached_values[0] if cached_values else 0
    if cached > input_tokens:
        raise ValueError("AI preference cached tokens exceed input tokens")
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
        raise ValueError("AI preference calculated cost is not finite")
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


def _token_alias(raw: dict[str, JsonValue], aliases: tuple[str, ...], label: str) -> int:
    values = [raw[name] for name in aliases if name in raw]
    if not values or any(type(value) is not int or value < 0 for value in values):
        raise ValueError(f"AI preference {label} token usage is absent or invalid")
    if len(set(values)) != 1:
        raise ValueError(f"AI preference {label} token aliases conflict")
    return values[0]  # type: ignore[return-value]


def _preauthorize_online_calls(
    requests: dict[str, tuple[Path, AIPreferencePrimaryRequest]],
    configs: dict[str, tuple[Path, AIPreferenceBackendConfig]],
    budget: AIPreferenceExecutionBudget,
) -> None:
    if len(requests) != budget.maximum_calls:
        raise ValueError("AI primary request count differs from the call ceiling")
    reserved_cost = 0.0
    for reviewer_id, (_, request) in requests.items():
        config = configs[reviewer_id][1]
        _verify_backend_identity(request.reviewer, config)
        _preauthorize_online_call(request, config, budget.per_call)
        reserved_cost += _maximum_cost(config.pricing, budget.per_call)
    if reserved_cost > budget.max_total_cost_usd + 1e-12:
        raise ValueError("AI primary maximum priced cost exceeds the total ceiling")


def _preauthorize_online_call(
    request: AIPreferencePrimaryRequest | AIAdjudicationRequest,
    config: AIPreferenceBackendConfig,
    budget: AIPreferenceCallBudget,
) -> None:
    if config.mode != "openai-compatible" or config.max_retries != 0:
        raise ValueError("AI online execution requires an OpenAI-compatible zero-retry config")
    if config.max_output_tokens > budget.max_output_tokens:
        raise ValueError("AI backend output ceiling exceeds the per-call budget")
    if config.timeout_seconds * 1000 > budget.max_latency_ms:
        raise ValueError("AI backend timeout exceeds the per-call budget")
    if _maximum_cost(config.pricing, budget) > budget.max_cost_usd + 1e-12:
        raise ValueError("AI maximum priced call exceeds the per-call cost ceiling")
    if len(_canonical_json_bytes(_chat_payload(request, config))) > budget.max_request_bytes:
        raise ValueError("AI rendered request exceeds the per-call byte ceiling")


def _maximum_cost(pricing: ModelCostProvenance, budget: AIPreferenceCallBudget) -> float:
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


def _verify_backend_identity(
    identity: AIPreferenceModelIdentity, config: AIPreferenceBackendConfig
) -> None:
    if (identity.provider, identity.model, identity.model_revision) != (
        config.provider,
        config.model,
        config.model_revision,
    ) or identity.identity_sha256 != config.identity_sha256:
        raise ValueError("AI backend configuration differs from the protocol identity")


def _require_environment_keys(configs) -> None:  # type: ignore[no-untyped-def]
    for config in configs:
        if config.mode != "openai-compatible":
            raise ValueError("AI primary panel requires online backend configs")
        key = os.getenv(config.api_key_env or "")
        if key is None or not key.strip():
            raise RuntimeError(f"missing API key environment variable {config.api_key_env}")


def _load_execution_configs(
    root: Path, paths: tuple[str | Path, str | Path]
) -> dict[str, tuple[Path, AIPreferenceBackendConfig]]:
    result: dict[str, tuple[Path, AIPreferenceBackendConfig]] = {}
    for path in paths:
        file = _regular_public_file(root, path)
        config = load_ai_preference_backend_config(file)
        if config.identity_sha256 in result:
            raise ValueError("AI primary backend configs duplicate a model identity")
        result[config.identity_sha256] = (file, config)
    return result


def _load_primary_requests(
    pack: AIPreferenceRequestPack, root: Path
) -> dict[str, tuple[Path, AIPreferencePrimaryRequest]]:
    result: dict[str, tuple[Path, AIPreferencePrimaryRequest]] = {}
    for binding, expected in zip(pack.primary_requests, pack.primary_request_sha256s, strict=True):
        file = _bound_public_file(root, binding)
        request = AIPreferencePrimaryRequest.model_validate_json(file.read_text(encoding="utf-8"))
        if request.request_sha256 != expected:
            raise ValueError("AI primary request hash mismatch")
        result[request.reviewer.identity_sha256] = (file, request)
    return result


def _execution_run(
    *,
    execution_id: str,
    phase: Literal["primary", "adjudicator"],
    source_request_sha256: str,
    budget: AIPreferenceExecutionBudget,
    budget_file_sha256: str,
    completed: list[AIPreferenceExecutionItem],
) -> AIPreferenceExecutionRun:
    total_tokens = sum(item.input_tokens + item.output_tokens for item in completed)
    total_cost = sum(item.cost_usd for item in completed)
    if (
        len(completed) > budget.maximum_calls
        or total_tokens > budget.max_total_tokens
        or total_cost > budget.max_total_cost_usd
    ):
        raise ValueError("AI preference completed run exceeds its total budget")
    return AIPreferenceExecutionRun(
        execution_id=execution_id,
        phase=phase,
        source_request_sha256=source_request_sha256,
        budget_sha256=budget.budget_sha256,
        budget_file_sha256=budget_file_sha256,
        completed=tuple(completed),
        call_count=len(completed),
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        completed_at=datetime.now(UTC),
    )


def _verify_adjudication_import(
    root: Path,
    primary: LockedAIPreferenceReviewSet,
    request_file: Path,
    request: AIAdjudicationRequest,
    raw_file: Path,
    response: AIRawAdjudicationResponse,
    receipt: AIReviewExecutionReceipt,
) -> None:
    if request.locked_primary_review_set_sha256 != primary.review_set_sha256:
        raise ValueError("AI adjudicator request binds another primary lock")
    dispute_ids = {item.dispute_id for item in primary.disputes}
    if {item.dispute_id for item in request.items} != dispute_ids:
        raise ValueError("AI adjudicator request is not exactly the disputed-only set")
    if {item.dispute_id for item in response.responses} != dispute_ids:
        raise ValueError("AI adjudicator response is not exactly the disputed-only set")
    if (
        response.reviewer_id != request.adjudicator.reviewer_id
        or response.reviewer_identity_sha256 != request.adjudicator.identity_sha256
        or response.request_sha256 != request.request_sha256
        or receipt.reviewer_id != request.adjudicator.reviewer_id
        or receipt.reviewer_identity_sha256 != request.adjudicator.identity_sha256
        or receipt.request_sha256 != request.request_sha256
        or (receipt.provider, receipt.model, receipt.model_revision)
        != (
            request.adjudicator.provider,
            request.adjudicator.model,
            request.adjudicator.model_revision,
        )
    ):
        raise ValueError("AI adjudicator response or receipt identity mismatch")
    _verify_execution_receipt_replay(
        root=root,
        request_file=request_file,
        request=request,
        raw_response_file=raw_file,
        receipt=receipt,
    )


def _final_blocks(
    primary: LockedAIPreferenceReviewSet,
    request: AIAdjudicationRequest | None,
    adjudication: dict[str, AIRawAdjudicationItem],
    adjudicator_response_sha256: str | None,
) -> tuple[AIFinalPreferenceBlock, ...]:
    grouped: dict[tuple[TasteMechanismHypothesis, str], list[AINormalizedPreferenceRow]] = (
        defaultdict(list)
    )
    disputes = {(item.hypothesis, item.case_id): item for item in primary.disputes}
    request_items = {} if request is None else {item.dispute_id: item for item in request.items}
    for row in primary.normalized_rows:
        grouped[(row.hypothesis, row.case_id)].append(row)
    blocks: list[AIFinalPreferenceBlock] = []
    for key, pair in sorted(grouped.items(), key=lambda item: str(item[0])):
        ordered = sorted(pair, key=lambda item: item.row_id)
        block_identity = _canonical_sha256([item.row_sha256 for item in ordered])
        dispute = disputes.get(key)
        if dispute is None:
            first = ordered[0]
            blocks.append(
                AIFinalPreferenceBlock.create(
                    block_id=f"ai-block-{block_identity[:24]}",
                    hypothesis=first.hypothesis,
                    case_id=first.case_id,
                    source_group=first.source_group,
                    primary_row_sha256s=tuple(  # type: ignore[arg-type]
                        item.row_sha256 for item in ordered
                    ),
                    resolution_source="primary-ai-agreement",
                    disposition=AIPreferenceDisposition.COMPLETED,
                    selected_output_sha256=first.selected_output_sha256,
                    tie=first.blinded_preference is AIBlindPreference.TIE,
                    adjudicator_response_sha256=None,
                )
            )
            continue
        raw = adjudication[dispute.dispute_id]
        request_item = request_items[dispute.dispute_id]
        preference = None if raw.response == "cannot-assess" else AIBlindPreference(raw.response)
        selected = (
            request_item.output_x.output_sha256
            if preference is AIBlindPreference.X
            else (
                request_item.output_y.output_sha256 if preference is AIBlindPreference.Y else None
            )
        )
        blocks.append(
            AIFinalPreferenceBlock.create(
                block_id=f"ai-block-{block_identity[:24]}",
                hypothesis=dispute.hypothesis,
                case_id=dispute.case_id,
                source_group=dispute.source_group,
                primary_row_sha256s=tuple(  # type: ignore[arg-type]
                    item.row_sha256 for item in ordered
                ),
                resolution_source="ai-adjudicator",
                disposition=(
                    AIPreferenceDisposition.CANNOT_ASSESS
                    if preference is None
                    else AIPreferenceDisposition.COMPLETED
                ),
                selected_output_sha256=selected,
                tie=preference is AIBlindPreference.TIE,
                adjudicator_response_sha256=adjudicator_response_sha256,
            )
        )
    return tuple(blocks)


def _verify_final_public_chain(
    root: Path,
    study: HumanOutcomeStudyManifest,
    final: LockedAIFinalPreferenceReviewSet,
) -> None:
    if final.study_id != study.study_id or final.study_sha256 != study.study_sha256:
        raise ValueError("AI final review set binds another public study")
    primary_file = _bound_public_file(root, final.primary_review_set)
    primary = LockedAIPreferenceReviewSet.model_validate_json(
        primary_file.read_text(encoding="utf-8")
    )
    _verify_primary_lock_bindings(root, primary)
    if primary.study_id != final.study_id or primary.study_sha256 != final.study_sha256:
        raise ValueError("AI final review set and primary lock bind different studies")
    if primary.review_set_sha256 != final.primary_review_set_sha256:
        raise ValueError("AI final review set primary lock hash mismatch")
    if final.locked_at < primary.locked_at:
        raise ValueError("AI final review lock precedes its primary lock")
    request = None
    adjudication: dict[str, AIRawAdjudicationItem] = {}
    response_file_sha = None
    if primary.disputes:
        if (
            final.adjudicator_request is None
            or final.adjudicator_raw_response is None
            or final.adjudicator_execution_receipt is None
        ):
            raise ValueError("AI final review set omits required adjudicator evidence")
        request_file = _bound_public_file(root, final.adjudicator_request)
        raw_file = _bound_public_file(root, final.adjudicator_raw_response)
        receipt_file = _bound_public_file(root, final.adjudicator_execution_receipt)
        request = AIAdjudicationRequest.model_validate_json(
            request_file.read_text(encoding="utf-8")
        )
        response = AIRawAdjudicationResponse.model_validate_json(
            raw_file.read_text(encoding="utf-8")
        )
        receipt = AIReviewExecutionReceipt.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
        _verify_adjudication_import(
            root, primary, request_file, request, raw_file, response, receipt
        )
        if final.locked_at < receipt.completed_at:
            raise ValueError("AI final review lock precedes adjudicator completion")
        adjudication = {item.dispute_id: item for item in response.responses}
        response_file_sha = _sha256(raw_file)
    elif any(
        item is not None
        for item in (
            final.adjudicator_request,
            final.adjudicator_raw_response,
            final.adjudicator_execution_receipt,
        )
    ):
        raise ValueError("AI final review set includes adjudication without a dispute")
    replayed = _final_blocks(primary, request, adjudication, response_file_sha)
    if replayed != final.blocks:
        raise ValueError("AI final preference blocks do not replay from their public evidence")


def _verify_primary_lock_bindings(root: Path, primary: LockedAIPreferenceReviewSet) -> None:
    raw_files = {_bound_public_file(root, item) for item in primary.raw_responses}
    receipt_files = {_bound_public_file(root, item) for item in primary.execution_receipts}
    if len(raw_files) != 2 or len(receipt_files) != 2:
        raise ValueError("AI primary lock requires two distinct raw responses and receipts")
    observed_raw: set[Path] = set()
    reviewer_identities: set[str] = set()
    for receipt_file in receipt_files:
        receipt = AIReviewExecutionReceipt.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
        raw = _bound_public_file(root, receipt.raw_response)
        if raw not in raw_files:
            raise ValueError("AI primary lock receipt binds an unlisted raw response")
        observed_raw.add(raw)
        request_file = _bound_public_file(root, receipt.request)
        request = AIPreferencePrimaryRequest.model_validate_json(
            request_file.read_text(encoding="utf-8")
        )
        _verify_execution_receipt_replay(
            root=root,
            request_file=request_file,
            request=request,
            raw_response_file=raw,
            receipt=receipt,
        )
        reviewer_identities.add(receipt.reviewer_identity_sha256)
    if observed_raw != raw_files:
        raise ValueError("AI primary lock receipts do not cover both raw responses")
    if len(reviewer_identities) != 2:
        raise ValueError("AI primary lock does not contain two distinct reviewer identities")


def _verify_execution_receipt_replay(
    *,
    root: Path,
    request_file: Path,
    request: AIPreferencePrimaryRequest | AIAdjudicationRequest,
    raw_response_file: Path,
    receipt: AIReviewExecutionReceipt,
) -> None:
    if _bound_public_file(root, receipt.request) != request_file:
        raise ValueError("AI execution receipt binds another request file")
    if _bound_public_file(root, receipt.raw_response) != raw_response_file:
        raise ValueError("AI execution receipt binds another extracted response file")
    config_file = _bound_public_file(root, receipt.backend_config)
    config = load_ai_preference_backend_config(config_file)
    reviewer = (
        request.reviewer if isinstance(request, AIPreferencePrimaryRequest) else request.adjudicator
    )
    _verify_backend_identity(reviewer, config)
    if (
        receipt.reviewer_id != reviewer.reviewer_id
        or receipt.reviewer_identity_sha256 != reviewer.identity_sha256
        or receipt.request_sha256 != request.request_sha256
        or (receipt.provider, receipt.model, receipt.model_revision)
        != (config.provider, config.model, config.model_revision)
    ):
        raise ValueError("AI execution receipt identity does not replay")
    http_request_file = _bound_public_file(root, receipt.http_request)
    if http_request_file.read_bytes() != _canonical_json_bytes(_chat_payload(request, config)):
        raise ValueError("AI execution HTTP request does not replay exactly")
    raw_http_file = _bound_public_file(root, receipt.raw_http_body)
    envelope = _json_object(raw_http_file.read_bytes(), "provider HTTP response replay")
    provider_model, provider_request_id, content, usage = _parse_provider_envelope(envelope, config)
    if provider_model not in {config.model, config.model_revision}:
        raise ValueError("AI execution replay observes another provider model")
    if provider_request_id != receipt.provider_request_id:
        raise ValueError("AI execution provider request ID does not replay")
    if content.encode("utf-8") != raw_response_file.read_bytes():
        raise ValueError("AI extracted response does not replay from the raw HTTP body")
    if _review_usage(usage, config.pricing) != receipt.usage:
        raise ValueError("AI execution usage or cost does not replay")
    if receipt.http_status < 200 or receipt.http_status >= 300:
        raise ValueError("AI execution receipt does not report successful HTTP completion")


def _unblind_final_blocks(
    study: HumanOutcomeStudyManifest,
    final: LockedAIFinalPreferenceReviewSet,
    key: HumanBlindKey,
) -> tuple[AIPairedAnalysisRow, ...]:
    comparisons = {item.comparison_id: item for item in study.comparisons}
    key_entries = {item.comparison_id: item for item in key.entries}
    if set(key_entries) != set(comparisons):
        raise ValueError("AI paired analysis condition map does not cover the public study")
    by_block: dict[tuple[TasteMechanismHypothesis, str], list[str]] = defaultdict(list)
    for comparison in study.comparisons:
        by_block[(comparison.hypothesis, comparison.case_id)].append(comparison.comparison_id)
    if any(len(items) != 1 for items in by_block.values()):
        raise ValueError("AI paired analysis requires one comparison per hypothesis/case block")
    blocks = {(item.hypothesis, item.case_id): item for item in final.blocks}
    if set(blocks) != set(by_block):
        raise ValueError("AI final review blocks do not cover the public study")
    rows: list[AIPairedAnalysisRow] = []
    for identity, block in sorted(blocks.items(), key=lambda item: str(item[0])):
        comparison_id = by_block[identity][0]
        comparison = comparisons[comparison_id]
        entry = key_entries[comparison_id]
        expected_conditions = (
            {
                TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            }
            if block.hypothesis is TasteMechanismHypothesis.H1_TASTE_ABSTRACTION
            else {
                TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
            }
        )
        if {entry.x_condition, entry.y_condition} != expected_conditions:
            raise ValueError("AI paired analysis condition map violates its H1/H2 contrast")
        output_condition = {
            comparison.x_output.sha256: entry.x_condition,
            comparison.y_output.sha256: entry.y_condition,
        }
        preferred = (
            None
            if block.selected_output_sha256 is None
            else output_condition[block.selected_output_sha256]
        )
        comparator = (
            TasteStudyCondition.SAME_SOURCE_RAW_RAG
            if block.hypothesis is TasteMechanismHypothesis.H1_TASTE_ABSTRACTION
            else TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE
        )
        score = (
            None
            if block.disposition is AIPreferenceDisposition.CANNOT_ASSESS
            else (
                0.5
                if block.tie
                else (1.0 if preferred is TasteStudyCondition.MATCHED_ABSTRACTED_TASTE else 0.0)
            )
        )
        rows.append(
            AIPairedAnalysisRow(
                block_sha256=block.block_sha256,
                hypothesis=block.hypothesis,
                case_id=block.case_id,
                source_group=block.source_group,
                comparator_condition=comparator,
                preferred_condition=preferred,
                treatment_preference_score=score,
                disposition=block.disposition,
            )
        )
    return tuple(rows)


def _analyze_rows(analysis: AIPairedAnalysisInput) -> AIPairedAnalysisResult:
    results: list[AIHypothesisPreferenceResult] = []
    for hypothesis in TasteMechanismHypothesis:
        rows = [item for item in analysis.rows if item.hypothesis is hypothesis]
        assessable = [item for item in rows if item.treatment_preference_score is not None]
        comparator = (
            TasteStudyCondition.SAME_SOURCE_RAW_RAG
            if hypothesis is TasteMechanismHypothesis.H1_TASTE_ABSTRACTION
            else TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE
        )
        results.append(
            AIHypothesisPreferenceResult(
                hypothesis=hypothesis,
                comparator_condition=comparator,
                assessable_count=len(assessable),
                treatment_win_count=sum(
                    item.treatment_preference_score == 1 for item in assessable
                ),
                comparator_win_count=sum(
                    item.treatment_preference_score == 0 for item in assessable
                ),
                tie_count=sum(item.treatment_preference_score == 0.5 for item in assessable),
                cannot_assess_count=len(rows) - len(assessable),
                treatment_preference_rate=(
                    None
                    if not assessable
                    else sum(item.treatment_preference_score or 0 for item in assessable)
                    / len(assessable)
                ),
            )
        )
    return AIPairedAnalysisResult(
        analysis_id=analysis.analysis_id,
        analysis_input_sha256=analysis.analysis_input_sha256,
        hypothesis_results=tuple(results),  # type: ignore[arg-type]
        source_group_count=len({item.source_group for item in analysis.rows}),
    )


def _load_mapping(path: Path, label: str) -> dict[str, JsonValue]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a mapping")
    return payload  # type: ignore[return-value]


def _json_object(raw: bytes, label: str) -> dict[str, JsonValue]:
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value!r}")


def _resolve_pack(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        path = path / "PACK.json"
    return _regular_public_file(root, path)


def _regular_public_file(root: Path, path: str | Path) -> Path:
    file = _regular_file(root, path)
    relative = file.relative_to(root)
    if any(part.lower() in _PRIVATE_NAMES for part in relative.parts):
        raise ValueError("AI preference execution cannot read private condition evidence")
    return file


def _regular_condition_file(root: Path, path: str | Path) -> Path:
    return _regular_file(root, path)


def _regular_file(root: Path, path: str | Path) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink():
        raise ValueError("AI preference execution inputs cannot be symlinks")
    resolved = source.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "AI preference execution inputs must stay inside the evidence root"
        ) from exc
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("AI preference execution input is not a bounded regular file")
    return resolved


def _bound_public_file(root: Path, binding: AIPreferenceFileBinding) -> Path:
    path = _regular_public_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("AI preference execution file binding mismatch")
    return path


def _new_public_target(root: Path, output: str | Path) -> Path:
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI preference execution output must stay inside evidence root") from exc
    if any(part.lower() in _PRIVATE_NAMES for part in relative.parts):
        raise ValueError("AI preference execution output cannot enter private study storage")
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _new_public_file(root: Path, output: str | Path) -> Path:
    target = _new_public_target(root, output)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _binding(root: Path, path: Path) -> AIPreferenceFileBinding:
    return AIPreferenceFileBinding(path=path.relative_to(root).as_posix(), sha256=_sha256(path))


def _write_failure(
    target: Path, error: BaseException, completed: list[AIPreferenceExecutionItem]
) -> None:
    payload = {
        "schema_version": "1.0",
        "error_type": type(error).__name__,
        "message": (
            "AI preference execution stopped without retry; caller exception retained separately."
        ),
        "completed_reviewer_identity_sha256s": [
            item.reviewer_identity_sha256 for item in completed
        ],
        "automatic_retry_performed": False,
        "same_output_directory_reusable": False,
        "reviewer_kind": "ai",
        "not_human_review": True,
    }
    _write_json(target / "FAILED.json", payload)


def _write_json(path: Path, payload: object) -> None:
    content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    _write_bytes(path, content.encode("utf-8"))


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


def _require_unique(values, label: str) -> None:  # type: ignore[no-untyped-def]
    items = list(values)
    if len(items) != len(set(items)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "AIConditionFileBinding",
    "AIFinalPreferenceBlock",
    "AIHypothesisPreferenceResult",
    "AILocalExecutionRequest",
    "AIPairedAnalysisInput",
    "AIPairedAnalysisResult",
    "AIPairedAnalysisRow",
    "AIPreferenceBackendConfig",
    "AIPreferenceCallBudget",
    "AIPreferenceExecutionBudget",
    "AIPreferenceExecutionItem",
    "AIPreferenceExecutionRun",
    "AIPreferenceHTTPResponse",
    "AIPreferenceHTTPTransport",
    "AIRawAdjudicationResponse",
    "HttpxAIPreferenceTransport",
    "LockedAIFinalPreferenceReviewSet",
    "analyze_ai_paired_preferences",
    "execute_ai_preference_adjudicator",
    "execute_ai_preference_primary_panel",
    "finalize_ai_preference_reviews",
    "load_ai_preference_backend_config",
    "load_ai_preference_execution_budget",
]

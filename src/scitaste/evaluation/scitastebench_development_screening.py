"""Outcome-blind model screening for SciTasteBench v4 development cases."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.benchmark.models import BenchmarkDecisionContextFamily
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.project.models import content_sha256, validate_project_id
from scitaste.taste.decision_families import ScientificTasteDecisionFamily

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_FILE_BYTES = 64 * 1024 * 1024
_NODE_NAME = "scitastebench-caseability-screen"


class ScreenFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> ScreenFileBinding:
        _validate_locator(self.locator)
        return self


class SciTasteBenchDevelopmentScreenConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    project_id: str
    intake_manifest: ScreenFileBinding
    screening_items: ScreenFileBinding
    profile: ScreenFileBinding
    backend_config: ScreenFileBinding
    admitted_prior_track_a_role: Literal["unused"] = "unused"
    batch_size: int = Field(default=8, ge=1, le=12)
    seed: int = Field(default=2027, ge=0)
    automatic_retry_permitted: Literal[False] = False
    target_outcomes_visible: Literal[False] = False
    formal_split_access_authorized: Literal[False] = False

    @model_validator(mode="after")
    def config_is_closed(self) -> SciTasteBenchDevelopmentScreenConfig:
        validate_project_id(self.project_id)
        return self


class CaseabilityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CaseabilityExclusion(StrEnum):
    INSUFFICIENT_CONTEXT = "insufficient-context"
    GENERIC_REVIEW_REQUEST = "generic-review-request"
    NOT_ACTIONABLE = "not-actionable"
    OUTCOME_REQUIRED = "outcome-required"
    NOT_SCIENTIFIC_JUDGMENT = "not-scientific-judgment"
    IDENTITY_OR_MEMORIZATION_RISK = "identity-or-memorization-risk"
    OTHER = "other"


class DevelopmentCaseabilityDecision(BaseModel):
    """One model proposal; it cannot admit a benchmark case by itself."""

    model_config = _CONFIG

    intake_candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    eligible: bool
    decision_context_family: BenchmarkDecisionContextFamily | None = None
    taste_judgment_family: ScientificTasteDecisionFamily | None = None
    atomic_decision_question: str | None = Field(default=None, max_length=500)
    ambiguity: CaseabilityLevel | None = None
    decision_leverage: CaseabilityLevel | None = None
    memorization_risk: CaseabilityLevel | None = None
    exclusion_codes: tuple[CaseabilityExclusion, ...] = ()
    rationale: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def eligibility_fields_are_atomic(self) -> DevelopmentCaseabilityDecision:
        details = (
            self.decision_context_family,
            self.taste_judgment_family,
            self.atomic_decision_question,
            self.ambiguity,
            self.decision_leverage,
            self.memorization_risk,
        )
        if self.eligible:
            if any(value is None for value in details):
                raise ValueError("eligible caseability decision lacks required fields")
            if self.exclusion_codes:
                raise ValueError("eligible caseability decision cannot carry exclusions")
        else:
            if any(value is not None for value in details):
                raise ValueError("excluded caseability decision cannot carry case fields")
            if not self.exclusion_codes:
                raise ValueError("excluded caseability decision requires an exclusion code")
        if len(self.exclusion_codes) != len(set(self.exclusion_codes)):
            raise ValueError("caseability exclusion codes must be unique")
        return self


class DevelopmentCaseabilityBatchOutput(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    batch_id: str = Field(pattern=_ID)
    decisions: tuple[DevelopmentCaseabilityDecision, ...] = Field(min_length=1, max_length=12)
    target_outcomes_used: Literal[False] = False
    benchmark_admission_claimed: Literal[False] = False


class DevelopmentScreenCandidate(BaseModel):
    model_config = _CONFIG

    intake_candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: str = Field(pattern=_ID)
    article_title: str
    reviewed_abstract: str
    predecision_review_context: str
    source_projection_sha256: str = Field(pattern=_SHA256)


class DevelopmentScreenBatchPlan(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0)
    batch_id: str = Field(pattern=_ID)
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    request: ScreenFileBinding
    request_fingerprint: str = Field(pattern=_SHA256)


class DevelopmentScreenPlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    project_id: str
    prepared_at: datetime
    config: ScreenFileBinding
    intake_manifest: ScreenFileBinding
    screening_items: ScreenFileBinding
    profile: ScreenFileBinding
    profile_id: str = Field(pattern=_ID)
    profile_fingerprint: str = Field(pattern=_SHA256)
    backend_config: ScreenFileBinding
    provider: str
    model: str
    candidate_count: int = Field(gt=0)
    batch_size: int = Field(ge=1, le=12)
    batches: tuple[DevelopmentScreenBatchPlan, ...] = Field(min_length=1)
    outcome_fields_exposed: Literal[False] = False
    prior_track_a_groups_excluded: Literal[True] = True
    automatic_retry_permitted: Literal[False] = False
    model_calls_performed: Literal[False] = False

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))

    @model_validator(mode="after")
    def plan_is_complete(self) -> DevelopmentScreenPlan:
        validate_project_id(self.project_id)
        if self.prepared_at.utcoffset() is None:
            raise ValueError("development screen preparation time must be timezone-aware")
        if tuple(item.ordinal for item in self.batches) != tuple(range(1, len(self.batches) + 1)):
            raise ValueError("development screen batch ordinals must be contiguous")
        candidates = [value for batch in self.batches for value in batch.candidate_ids]
        groups = [value for batch in self.batches for value in batch.source_group_ids]
        if len(candidates) != self.candidate_count or len(candidates) != len(set(candidates)):
            raise ValueError("development screen plan candidate population differs")
        if len(groups) != self.candidate_count or len(groups) != len(set(groups)):
            raise ValueError("development screen plan source groups differ")
        return self


class DevelopmentScreenBatchReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    batch_id: str = Field(pattern=_ID)
    completed_at: datetime
    outcome: Literal["accepted", "rejected", "failed"]
    request_fingerprint: str = Field(pattern=_SHA256)
    response: ScreenFileBinding | None = None
    raw_response: ScreenFileBinding | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    failure_code: str | None = None
    failure_detail: str | None = Field(default=None, max_length=1_000)
    retry_permitted: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> DevelopmentScreenBatchReceipt:
        if self.completed_at.utcoffset() is None:
            raise ValueError("development screen completion time must be timezone-aware")
        if self.outcome == "accepted":
            if self.response is None or self.raw_response is None or self.failure_code is not None:
                raise ValueError("accepted development screen receipt is incomplete")
        elif self.failure_code is None:
            raise ValueError("non-accepted development screen receipt lacks a failure code")
        return self


class DevelopmentScreenRunSummary(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    finalized_at: datetime
    batch_count: int = Field(gt=0)
    terminal_batch_count: int = Field(ge=0)
    accepted_batch_count: int = Field(ge=0)
    rejected_batch_count: int = Field(ge=0)
    failed_batch_count: int = Field(ge=0)
    accepted_decision_count: int = Field(ge=0)
    eligible_decision_count: int = Field(ge=0)
    context_family_counts: dict[str, int]
    judgment_family_counts: dict[str, int]
    domain_counts: dict[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    complete: bool
    ready_for_allocation: bool
    model_calls_performed: bool
    target_outcomes_used: Literal[False] = False
    formal_split_opened: Literal[False] = False


class DevelopmentScreenIdentityCorrection(BaseModel):
    model_config = _CONFIG

    batch_id: str = Field(pattern=_ID)
    position: int = Field(gt=0, le=12)
    field: Literal["intake_candidate_id", "source_group_id"]
    observed_value: str
    canonical_value: str
    edit_distance: int = Field(gt=0, le=256)
    canonicalization_basis: Literal["candidate-id-bijection"] = "candidate-id-bijection"


class DevelopmentNormalizedDecision(BaseModel):
    model_config = _CONFIG

    batch_id: str = Field(pattern=_ID)
    position: int = Field(gt=0, le=12)
    original_receipt_outcome: Literal["accepted", "rejected"]
    identity_correction_count: int = Field(ge=0, le=2)
    decision: DevelopmentCaseabilityDecision


class DevelopmentScreenNormalizationManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    normalized_at: datetime
    source_batch_count: int = Field(gt=0)
    source_accepted_batch_count: int = Field(ge=0)
    source_rejected_batch_count: int = Field(ge=0)
    normalized_decision_count: int = Field(gt=0)
    eligible_decision_count: int = Field(ge=0)
    identity_correction_count: int = Field(ge=0)
    envelope_field_removal_count: int = Field(default=0, ge=0)
    ineligible_field_nullification_count: int = Field(default=0, ge=0)
    semantic_field_change_count: Literal[0] = 0
    corrections: tuple[DevelopmentScreenIdentityCorrection, ...]
    context_family_counts: dict[str, int]
    judgment_family_counts: dict[str, int]
    domain_counts: dict[str, int]
    decisions: ScreenFileBinding
    all_batches_normalized: bool
    ready_for_allocation: bool
    model_calls_performed: Literal[False] = False
    target_outcomes_used: Literal[False] = False
    formal_split_opened: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def normalization_is_consistent(self) -> DevelopmentScreenNormalizationManifest:
        if self.normalized_at.utcoffset() is None:
            raise ValueError("screen normalization time must be timezone-aware")
        if len(self.corrections) != self.identity_correction_count:
            raise ValueError("screen normalization correction count differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        legacy_expected = content_sha256(
            self.model_dump(
                mode="json",
                exclude={
                    "manifest_sha256",
                    "envelope_field_removal_count",
                    "ineligible_field_nullification_count",
                },
            )
        )
        if self.manifest_sha256 not in {expected, legacy_expected}:
            raise ValueError("screen normalization manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DevelopmentScreenNormalizationManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


def prepare_scitastebench_development_screen(
    *,
    config_path: str | Path,
    locator_root: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> DevelopmentScreenPlan:
    """Freeze outcome-blind batches and model requests without making a call."""

    root = Path(locator_root).resolve(strict=True)
    config_file = _within(root, config_path)
    config = SciTasteBenchDevelopmentScreenConfig.model_validate(
        yaml.safe_load(_bounded_bytes(config_file))
    )
    intake_path = _require_binding(root, config.intake_manifest)
    intake = json.loads(_bounded_bytes(intake_path))
    if intake.get("project_id") != config.project_id:
        raise ValueError("development screen intake belongs to another project")
    if intake.get("outcome_fields_exposed_to_screen") is True:
        raise ValueError("development screen intake exposed hidden outcomes")
    items_path = _require_binding(root, config.screening_items)
    rows = _load_screen_candidates(items_path, role=config.admitted_prior_track_a_role)
    if not rows:
        raise ValueError("development screen has no source-disjoint candidates")

    profile_path = _require_binding(root, config.profile)
    profile = load_model_node_profile(profile_path)
    if _NODE_NAME not in profile.allowed_node_names or not profile.live_execution_permitted:
        raise ValueError("development screen profile does not permit the live screening node")
    backend_path = _require_binding(root, config.backend_config)
    backend = load_structured_openai_compatible_config(backend_path)
    if not backend.live_enabled or backend.max_retries != 0:
        raise ValueError("development screen backend must be live with zero retries")
    if not backend.pricing_confirmed or backend.pricing is None:
        raise ValueError("development screen backend lacks pricing provenance")
    if (backend.provider, backend.model) != (profile.provider, profile.model):
        raise ValueError("development screen backend and profile identities differ")

    ranked = sorted(
        rows,
        key=lambda item: hashlib.sha256(
            f"{config.screen_id}:{item.source_group_id}".encode()
        ).hexdigest(),
    )
    chunks = [
        ranked[index : index + config.batch_size]
        for index in range(0, len(ranked), config.batch_size)
    ]
    if len(chunks) > profile.cumulative_project.max_invocations:
        raise ValueError("development screen exceeds the profile invocation ceiling")

    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"development screen output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        requests_dir = temporary / "requests"
        requests_dir.mkdir()
        plans: list[DevelopmentScreenBatchPlan] = []
        policy_fingerprint = content_sha256(
            {
                "screen_id": config.screen_id,
                "profile_fingerprint": profile.fingerprint,
                "prompt_version": "scitastebench-caseability-screen-v1",
            }
        )
        for ordinal, chunk in enumerate(chunks, 1):
            batch_id = f"{config.screen_id}-batch-{ordinal:02d}"
            request = _screen_request(
                batch_id=batch_id,
                candidates=chunk,
                profile=profile,
                policy_fingerprint=policy_fingerprint,
                seed=config.seed + ordinal - 1,
            )
            relative = Path("requests") / f"{ordinal:02d}.json"
            request_path = temporary / relative
            _write_json(request_path, request.model_dump(mode="json", exclude_computed_fields=True))
            plans.append(
                DevelopmentScreenBatchPlan(
                    ordinal=ordinal,
                    batch_id=batch_id,
                    candidate_ids=tuple(item.intake_candidate_id for item in chunk),
                    source_group_ids=tuple(item.source_group_id for item in chunk),
                    request=ScreenFileBinding(
                        locator=relative.as_posix(), sha256=_sha256_file(request_path)
                    ),
                    request_fingerprint=request.fingerprint,
                )
            )
        plan = DevelopmentScreenPlan(
            screen_id=config.screen_id,
            project_id=config.project_id,
            prepared_at=prepared_at or datetime.now(UTC),
            config=_binding(config_file, root),
            intake_manifest=config.intake_manifest,
            screening_items=config.screening_items,
            profile=config.profile,
            profile_id=profile.profile_id,
            profile_fingerprint=profile.fingerprint,
            backend_config=config.backend_config,
            provider=profile.provider,
            model=profile.model,
            candidate_count=len(ranked),
            batch_size=config.batch_size,
            batches=tuple(plans),
        )
        _write_json(temporary / "PLAN.json", plan.model_dump(mode="json"))
        os.replace(temporary, target)
    except BaseException:
        _cleanup_temporary(temporary)
        raise
    return plan


def execute_scitastebench_development_screen(
    *,
    screen_dir: str | Path,
    locator_root: str | Path,
    allow_live: bool,
) -> DevelopmentScreenRunSummary:
    """Execute each frozen batch at most once and retain every terminal result."""

    if not allow_live:
        raise ValueError("development screening requires explicit --allow-live")
    root = Path(locator_root).resolve(strict=True)
    directory = _within(root, screen_dir)
    plan = _load_plan(directory / "PLAN.json")
    profile = load_model_node_profile(_require_binding(root, plan.profile))
    backend_config = load_structured_openai_compatible_config(
        _require_binding(root, plan.backend_config)
    )
    if profile.fingerprint != plan.profile_fingerprint:
        raise ValueError("development screen profile fingerprint drifted")
    if not backend_config.live_enabled or backend_config.max_retries != 0:
        raise ValueError("development screen backend is not eligible for live execution")
    backend = StructuredOpenAICompatibleBackend(backend_config)
    receipts_dir = directory / "receipts"
    responses_dir = directory / "responses"
    attempts_dir = directory / "attempts"
    receipts_dir.mkdir(exist_ok=True)
    responses_dir.mkdir(exist_ok=True)
    attempts_dir.mkdir(exist_ok=True)

    for batch in plan.batches:
        receipt_path = receipts_dir / f"{batch.ordinal:02d}.json"
        if receipt_path.exists():
            _load_receipt(receipt_path, plan=plan, batch=batch)
            continue
        request_path = directory / PurePosixPath(batch.request.locator)
        if _sha256_file(request_path) != batch.request.sha256:
            raise ValueError("development screen request bytes drifted")
        request = StructuredModelRequest.model_validate_json(_bounded_bytes(request_path))
        if request.fingerprint != batch.request_fingerprint:
            raise ValueError("development screen request fingerprint drifted")
        attempt_path = attempts_dir / f"{batch.ordinal:02d}.json"
        if attempt_path.exists():
            receipt = _failed_receipt(
                plan=plan,
                batch=batch,
                code="ambiguous-prior-attempt",
                detail=(
                    "A prior live attempt began without publishing a terminal receipt; "
                    "retry is forbidden."
                ),
            )
            _write_json(receipt_path, receipt.model_dump(mode="json"))
            break
        _write_json(
            attempt_path,
            {
                "screen_id": plan.screen_id,
                "plan_sha256": plan.plan_sha256,
                "batch_id": batch.batch_id,
                "started_at": datetime.now(UTC).isoformat(),
                "request_fingerprint": request.fingerprint,
                "retry_permitted": False,
            },
        )
        try:
            response = backend.complete(request)
        except Exception as exc:
            receipt = _failed_receipt(
                plan=plan,
                batch=batch,
                code="provider-or-transport-failure",
                detail=f"{type(exc).__name__}: {exc}"[:1_000],
            )
            _write_json(receipt_path, receipt.model_dump(mode="json"))
            break

        raw_path = responses_dir / f"{batch.ordinal:02d}-provider.json"
        raw = response.raw_response or ""
        _atomic_write(raw_path, raw)
        package_path = responses_dir / f"{batch.ordinal:02d}-screen.json"
        try:
            if response.backend != plan.provider or response.model != plan.model:
                raise ValueError("provider response identity differs from the frozen plan")
            if response.tool_calls:
                raise ValueError("development screen rejects provider tool calls")
            package = DevelopmentCaseabilityBatchOutput.model_validate(response.output_payload)
            _validate_batch_output(package, batch=batch)
            _validate_telemetry(response, profile=profile)
            _atomic_write(package_path, package.model_dump_json(indent=2) + "\n")
            receipt = DevelopmentScreenBatchReceipt(
                screen_id=plan.screen_id,
                plan_sha256=plan.plan_sha256,
                batch_id=batch.batch_id,
                completed_at=datetime.now(UTC),
                outcome="accepted",
                request_fingerprint=batch.request_fingerprint,
                response=_binding(package_path, directory),
                raw_response=_binding(raw_path, directory),
                provider=response.backend,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
            )
        except Exception as exc:
            receipt = DevelopmentScreenBatchReceipt(
                screen_id=plan.screen_id,
                plan_sha256=plan.plan_sha256,
                batch_id=batch.batch_id,
                completed_at=datetime.now(UTC),
                outcome="rejected",
                request_fingerprint=batch.request_fingerprint,
                raw_response=_binding(raw_path, directory),
                provider=response.backend,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
                failure_code="invalid-screen-response",
                failure_detail=f"{type(exc).__name__}: {exc}"[:1_000],
            )
        _write_json(receipt_path, receipt.model_dump(mode="json"))
        summary = _summarize(directory, plan=plan)
        _validate_cumulative_budget(summary, profile=profile)

    summary = _summarize(directory, plan=plan)
    _validate_cumulative_budget(summary, profile=profile)
    _write_json(directory / "SUMMARY.json", summary.model_dump(mode="json"))
    return summary


def normalize_scitastebench_development_screen(
    *,
    screen_dir: str | Path,
    locator_root: str | Path,
    normalized_at: datetime | None = None,
) -> DevelopmentScreenNormalizationManifest:
    """Bind model semantics to deterministic positional identities for every batch."""

    root = Path(locator_root).resolve(strict=True)
    directory = _within(root, screen_dir)
    plan = _load_plan(directory / "PLAN.json")
    target = directory / "normalization"
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"development screen normalization already exists: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=".normalization.", dir=directory))
    try:
        records: list[DevelopmentNormalizedDecision] = []
        corrections: list[DevelopmentScreenIdentityCorrection] = []
        domains_by_candidate: dict[str, str] = {}
        envelope_field_removals = 0
        ineligible_field_nullifications = 0
        accepted_batches = 0
        rejected_batches = 0
        for batch in plan.batches:
            receipt_path = directory / "receipts" / f"{batch.ordinal:02d}.json"
            receipt = _load_receipt(receipt_path, plan=plan, batch=batch)
            if receipt.outcome not in {"accepted", "rejected"}:
                raise ValueError("cannot normalize a provider-failed development screen batch")
            accepted_batches += receipt.outcome == "accepted"
            rejected_batches += receipt.outcome == "rejected"
            request = StructuredModelRequest.model_validate_json(
                _bounded_bytes(directory / PurePosixPath(batch.request.locator))
            )
            raw_candidates = request.input_payload.get("candidates")
            if not isinstance(raw_candidates, list) or len(raw_candidates) != len(
                batch.candidate_ids
            ):
                raise ValueError("development screen request candidates differ from the plan")
            candidates: list[dict[str, JsonValue]] = []
            for raw_candidate in raw_candidates:
                if not isinstance(raw_candidate, dict):
                    raise ValueError("development screen request candidate is malformed")
                candidates.append(raw_candidate)
                domains_by_candidate[str(raw_candidate["intake_candidate_id"])] = str(
                    raw_candidate["domain"]
                )
            provider_path = directory / "responses" / f"{batch.ordinal:02d}-provider.json"
            output, removals, nullifications = _provider_batch_output(provider_path)
            envelope_field_removals += removals
            ineligible_field_nullifications += nullifications
            if output.batch_id != batch.batch_id or len(output.decisions) != len(candidates):
                raise ValueError("development screen provider batch identity or length differs")
            expected_candidate_ids = [str(item["intake_candidate_id"]) for item in candidates]
            for position, (decision, candidate) in enumerate(
                zip(output.decisions, candidates, strict=True), 1
            ):
                expected_candidate = str(candidate["intake_candidate_id"])
                expected_group = str(candidate["source_group_id"])
                matched_position = _unique_identity_position(
                    decision.intake_candidate_id,
                    expected_candidate_ids,
                    maximum=2,
                )
                if matched_position != position - 1:
                    raise ValueError(
                        "development screen candidate identity does not preserve input order"
                    )
                item_corrections: list[DevelopmentScreenIdentityCorrection] = []
                for field, observed, expected in (
                    (
                        "intake_candidate_id",
                        decision.intake_candidate_id,
                        expected_candidate,
                    ),
                    (
                        "source_group_id",
                        decision.source_group_id,
                        expected_group,
                    ),
                ):
                    if observed == expected:
                        continue
                    distance = _edit_distance(observed, expected)
                    item_corrections.append(
                        DevelopmentScreenIdentityCorrection(
                            batch_id=batch.batch_id,
                            position=position,
                            field=field,
                            observed_value=observed,
                            canonical_value=expected,
                            edit_distance=distance,
                        )
                    )
                canonical = DevelopmentCaseabilityDecision.model_validate(
                    {
                        **decision.model_dump(mode="json"),
                        "intake_candidate_id": expected_candidate,
                        "source_group_id": expected_group,
                    }
                )
                corrections.extend(item_corrections)
                records.append(
                    DevelopmentNormalizedDecision(
                        batch_id=batch.batch_id,
                        position=position,
                        original_receipt_outcome=receipt.outcome,
                        identity_correction_count=len(item_corrections),
                        decision=canonical,
                    )
                )
        decisions_path = temporary / "NORMALIZED_DECISIONS.jsonl"
        _atomic_write(
            decisions_path,
            "".join(item.model_dump_json() + "\n" for item in records),
        )
        eligible = [item.decision for item in records if item.decision.eligible]
        contexts = Counter(
            item.decision_context_family.value
            for item in eligible
            if item.decision_context_family is not None
        )
        judgments = Counter(
            item.taste_judgment_family.value
            for item in eligible
            if item.taste_judgment_family is not None
        )
        domains = Counter(domains_by_candidate[item.intake_candidate_id] for item in eligible)
        complete = len(records) == plan.candidate_count
        ready = (
            complete
            and all(contexts[item.value] >= 6 for item in BenchmarkDecisionContextFamily)
            and set(judgments) == {item.value for item in ScientificTasteDecisionFamily}
            and len(domains) >= 3
        )
        manifest = DevelopmentScreenNormalizationManifest.create(
            screen_id=plan.screen_id,
            plan_sha256=plan.plan_sha256,
            normalized_at=normalized_at or datetime.now(UTC),
            source_batch_count=len(plan.batches),
            source_accepted_batch_count=accepted_batches,
            source_rejected_batch_count=rejected_batches,
            normalized_decision_count=len(records),
            eligible_decision_count=len(eligible),
            identity_correction_count=len(corrections),
            envelope_field_removal_count=envelope_field_removals,
            ineligible_field_nullification_count=ineligible_field_nullifications,
            corrections=tuple(corrections),
            context_family_counts=dict(sorted(contexts.items())),
            judgment_family_counts=dict(sorted(judgments.items())),
            domain_counts=dict(sorted(domains.items())),
            decisions=_binding(decisions_path, temporary),
            all_batches_normalized=complete,
            ready_for_allocation=ready,
        )
        _write_json(temporary / "NORMALIZATION.json", manifest.model_dump(mode="json"))
        os.replace(temporary, target)
    except BaseException:
        _cleanup_temporary(temporary)
        raise
    return manifest


def _screen_request(
    *,
    batch_id: str,
    candidates: list[DevelopmentScreenCandidate],
    profile: object,
    policy_fingerprint: str,
    seed: int,
) -> StructuredModelRequest:
    from scitaste.model_nodes.profiles import ModelNodeProfile

    assert isinstance(profile, ModelNodeProfile)
    return StructuredModelRequest(
        request_id=batch_id,
        node_name=_NODE_NAME,
        stage="benchmark-development-screening",
        state_snapshot_id=content_sha256([item.source_projection_sha256 for item in candidates]),
        expected_backend=profile.provider,
        expected_model=profile.model,
        policy_id="scitastebench-caseability-screen-v1",
        policy_fingerprint=policy_fingerprint,
        system_instruction=(
            "Screen outcome-blind natural research material for fixed-choice Scientific Taste "
            "cases. Use only the visible abstract and predecision review context. Never infer, "
            "retrieve, or reconstruct the paper's later response, revision, recommendation, or "
            "outcome. The reviewer comment is context, not a gold answer. Mark eligible only when "
            "the visible state supports one concrete consequential research decision with at "
            "least two plausible actions and a neutral question answerable without hidden "
            "outcomes. Classify where the decision occurs using exactly one decision-context "
            "family and what scientific judgment it exercises using exactly one Taste family. "
            "The atomic question must not imply a preferred action. Ambiguity measures how "
            "plausible the competing actions are; decision leverage measures the likely effect "
            "on scientific validity or resource use; memorization risk measures whether visible "
            "content could identify a known public outcome. Exclude generic requests, missing "
            "decision states, outcome-dependent cases, and non-scientific/style-only comments. "
            "Return decisions in the exact input order and return only the requested JSON object."
        ),
        input_payload={
            "batch_id": batch_id,
            "decision_context_families": [item.value for item in BenchmarkDecisionContextFamily],
            "taste_judgment_families": [item.value for item in ScientificTasteDecisionFamily],
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "forbidden_information": [
                "observed recommendation",
                "author response",
                "revised abstract",
                "later review",
                "publication outcome",
            ],
        },
        output_schema=DevelopmentCaseabilityBatchOutput.model_json_schema(mode="serialization"),
        seed=seed,
        prompt_version="scitastebench-caseability-screen-v1",
        profile_id=profile.profile_id,
        profile_fingerprint=profile.fingerprint,
        generation_envelope=profile.generation,
        admission_budget=profile.admission,
        cumulative_project_budget=profile.cumulative_project,
    )


def _load_screen_candidates(path: Path, *, role: str) -> list[DevelopmentScreenCandidate]:
    candidates: list[DevelopmentScreenCandidate] = []
    for line in _bounded_bytes(path).decode("utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("outcome_fields_exposed") is not False:
            raise ValueError("development screening item does not prove outcome isolation")
        if item.get("prior_track_a_role") != role:
            continue
        candidates.append(
            DevelopmentScreenCandidate.model_validate(
                {
                    "intake_candidate_id": item.get("intake_candidate_id"),
                    "source_group_id": item.get("source_group_id"),
                    "domain": item.get("domain"),
                    "article_title": item.get("article_title"),
                    "reviewed_abstract": item.get("reviewed_abstract"),
                    "predecision_review_context": item.get("predecision_review_context"),
                    "source_projection_sha256": item.get("source_projection_sha256"),
                }
            )
        )
    groups = [item.source_group_id for item in candidates]
    if len(groups) != len(set(groups)):
        raise ValueError("development screen candidates repeat source groups")
    return candidates


def _validate_batch_output(
    output: DevelopmentCaseabilityBatchOutput,
    *,
    batch: DevelopmentScreenBatchPlan,
) -> None:
    if output.batch_id != batch.batch_id:
        raise ValueError("development screen response names another batch")
    if tuple(item.intake_candidate_id for item in output.decisions) != batch.candidate_ids:
        raise ValueError("development screen response candidate order or coverage differs")
    if tuple(item.source_group_id for item in output.decisions) != batch.source_group_ids:
        raise ValueError("development screen response source-group order or coverage differs")


def _validate_telemetry(response: object, *, profile: object) -> None:
    from scitaste.model_nodes.models import StructuredModelResponse
    from scitaste.model_nodes.profiles import ModelNodeProfile

    assert isinstance(response, StructuredModelResponse)
    assert isinstance(profile, ModelNodeProfile)
    cost = response.usage.cost_usd
    total = response.usage.input_tokens + response.usage.output_tokens
    budget = profile.admission
    if cost is None:
        raise ValueError("development screen response lacks cost telemetry")
    if (
        response.usage.input_tokens > budget.max_input_tokens
        or response.usage.output_tokens > budget.max_output_tokens
        or total > budget.max_total_tokens
        or cost > budget.max_response_cost_usd
        or response.latency_ms > budget.max_latency_ms
    ):
        raise ValueError("development screen response exceeds its per-call budget")


def _summarize(directory: Path, *, plan: DevelopmentScreenPlan) -> DevelopmentScreenRunSummary:
    receipts: list[DevelopmentScreenBatchReceipt] = []
    decisions: list[DevelopmentCaseabilityDecision] = []
    for batch in plan.batches:
        path = directory / "receipts" / f"{batch.ordinal:02d}.json"
        if not path.exists():
            continue
        receipt = _load_receipt(path, plan=plan, batch=batch)
        receipts.append(receipt)
        if receipt.outcome == "accepted":
            assert receipt.response is not None
            package = DevelopmentCaseabilityBatchOutput.model_validate_json(
                _bounded_bytes(directory / PurePosixPath(receipt.response.locator))
            )
            decisions.extend(package.decisions)
    contexts = Counter(
        item.decision_context_family.value
        for item in decisions
        if item.eligible and item.decision_context_family is not None
    )
    judgments = Counter(
        item.taste_judgment_family.value
        for item in decisions
        if item.eligible and item.taste_judgment_family is not None
    )
    candidate_domains: dict[str, str] = {}
    for request_batch in plan.batches:
        request = StructuredModelRequest.model_validate_json(
            _bounded_bytes(directory / PurePosixPath(request_batch.request.locator))
        )
        raw_candidates = request.input_payload.get("candidates")
        if isinstance(raw_candidates, list):
            for raw in raw_candidates:
                if isinstance(raw, dict):
                    candidate_domains[str(raw["intake_candidate_id"])] = str(raw["domain"])
    domains = Counter(
        candidate_domains[item.intake_candidate_id] for item in decisions if item.eligible
    )
    complete = len(receipts) == len(plan.batches)
    accepted = sum(item.outcome == "accepted" for item in receipts)
    rejected = sum(item.outcome == "rejected" for item in receipts)
    failed = sum(item.outcome == "failed" for item in receipts)
    eligible = sum(item.eligible for item in decisions)
    ready = (
        complete
        and rejected == 0
        and failed == 0
        and eligible >= 36
        and set(contexts) == {item.value for item in BenchmarkDecisionContextFamily}
        and set(judgments) == {item.value for item in ScientificTasteDecisionFamily}
        and len(domains) >= 3
    )
    return DevelopmentScreenRunSummary(
        screen_id=plan.screen_id,
        plan_sha256=plan.plan_sha256,
        finalized_at=datetime.now(UTC),
        batch_count=len(plan.batches),
        terminal_batch_count=len(receipts),
        accepted_batch_count=accepted,
        rejected_batch_count=rejected,
        failed_batch_count=failed,
        accepted_decision_count=len(decisions),
        eligible_decision_count=eligible,
        context_family_counts=dict(sorted(contexts.items())),
        judgment_family_counts=dict(sorted(judgments.items())),
        domain_counts=dict(sorted(domains.items())),
        input_tokens=sum(item.input_tokens for item in receipts),
        output_tokens=sum(item.output_tokens for item in receipts),
        cost_usd=sum(item.cost_usd or 0.0 for item in receipts),
        complete=complete,
        ready_for_allocation=ready,
        model_calls_performed=bool(receipts),
    )


def _validate_cumulative_budget(summary: DevelopmentScreenRunSummary, *, profile: object) -> None:
    from scitaste.model_nodes.profiles import ModelNodeProfile

    assert isinstance(profile, ModelNodeProfile)
    budget = profile.cumulative_project
    if (
        summary.terminal_batch_count > budget.max_invocations
        or summary.input_tokens + summary.output_tokens > budget.max_total_tokens
        or summary.cost_usd > budget.max_api_cost_usd
    ):
        raise ValueError("development screen exceeded its cumulative budget")


def _failed_receipt(
    *,
    plan: DevelopmentScreenPlan,
    batch: DevelopmentScreenBatchPlan,
    code: str,
    detail: str,
) -> DevelopmentScreenBatchReceipt:
    return DevelopmentScreenBatchReceipt(
        screen_id=plan.screen_id,
        plan_sha256=plan.plan_sha256,
        batch_id=batch.batch_id,
        completed_at=datetime.now(UTC),
        outcome="failed",
        request_fingerprint=batch.request_fingerprint,
        failure_code=code,
        failure_detail=detail,
    )


def _load_receipt(
    path: Path,
    *,
    plan: DevelopmentScreenPlan,
    batch: DevelopmentScreenBatchPlan,
) -> DevelopmentScreenBatchReceipt:
    receipt = DevelopmentScreenBatchReceipt.model_validate_json(_bounded_bytes(path))
    if (
        receipt.screen_id != plan.screen_id
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.batch_id != batch.batch_id
        or receipt.request_fingerprint != batch.request_fingerprint
    ):
        raise ValueError("development screen receipt differs from the frozen plan")
    return receipt


def _provider_batch_output(
    path: Path,
) -> tuple[DevelopmentCaseabilityBatchOutput, int, int]:
    payload = json.loads(_bounded_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError("provider response root is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("provider response must have exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ValueError("provider response message is malformed")
    content = choice["message"].get("content")
    if not isinstance(content, str):
        raise ValueError("provider response content is not text")
    output = json.loads(content)
    if not isinstance(output, dict) or not isinstance(output.get("decisions"), list):
        raise ValueError("provider screen content is not a decision object")
    envelope_fields = {"source_projection_sha256"}
    permitted = set(DevelopmentCaseabilityDecision.model_fields)
    removals = 0
    nullifications = 0
    normalized_decisions: list[dict[str, object]] = []
    for raw_decision in output["decisions"]:
        if not isinstance(raw_decision, dict):
            raise ValueError("provider screen decision is not an object")
        unknown = set(raw_decision) - permitted
        if not unknown <= envelope_fields:
            raise ValueError("provider screen decision contains an unknown semantic field")
        normalized = {key: value for key, value in raw_decision.items() if key in permitted}
        removals += len(unknown)
        if normalized.get("eligible") is True:
            normalized.setdefault("exclusion_codes", [])
        elif normalized.get("eligible") is False:
            for field in (
                "decision_context_family",
                "taste_judgment_family",
                "atomic_decision_question",
                "ambiguity",
                "decision_leverage",
                "memorization_risk",
            ):
                if normalized.get(field) is not None:
                    nullifications += 1
                normalized[field] = None
        normalized_decisions.append(normalized)
    output["decisions"] = normalized_decisions
    return DevelopmentCaseabilityBatchOutput.model_validate(output), removals, nullifications


def _bounded_edit_distance(left: str, right: str, *, maximum: int) -> int | None:
    if abs(len(left) - len(right)) > maximum:
        return None
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, 1):
        current = [left_index]
        row_minimum = left_index
        for right_index, right_character in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
            row_minimum = min(row_minimum, current[-1])
        if row_minimum > maximum:
            return None
        previous = current
    return previous[-1] if previous[-1] <= maximum else None


def _edit_distance(left: str, right: str) -> int:
    distance = _bounded_edit_distance(left, right, maximum=max(len(left), len(right)))
    assert distance is not None
    return distance


def _unique_identity_position(
    observed: str,
    expected: list[str],
    *,
    maximum: int,
) -> int:
    distances = [
        _bounded_edit_distance(observed, candidate, maximum=maximum) for candidate in expected
    ]
    matches = [
        (index, distance) for index, distance in enumerate(distances) if distance is not None
    ]
    if not matches:
        raise ValueError("development screen candidate identity has no bounded canonical match")
    best = min(distance for _, distance in matches)
    winners = [index for index, distance in matches if distance == best]
    if len(winners) != 1:
        raise ValueError("development screen candidate identity match is ambiguous")
    return winners[0]


def _load_plan(path: Path) -> DevelopmentScreenPlan:
    payload = json.loads(_bounded_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError("development screen plan root is not an object")
    observed_sha256 = payload.pop("plan_sha256", None)
    plan = DevelopmentScreenPlan.model_validate(payload)
    if observed_sha256 != plan.plan_sha256:
        raise ValueError("development screen plan hash mismatch")
    return plan


def _require_binding(root: Path, binding: ScreenFileBinding) -> Path:
    path = _within(root, binding.locator)
    if _sha256_file(path) != binding.sha256:
        raise ValueError(f"development screen binding drifted: {binding.locator}")
    return path


def _binding(path: Path, root: Path) -> ScreenFileBinding:
    return ScreenFileBinding(
        locator=path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix(),
        sha256=_sha256_file(path),
    )


def _within(root: Path, locator: str | Path) -> Path:
    candidate = Path(locator)
    if not candidate.is_absolute():
        _validate_locator(candidate.as_posix())
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("development screen path escapes locator root") from exc
    return resolved


def _validate_locator(locator: str) -> None:
    path = PurePosixPath(locator)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("development screen locator must be safe and relative")


def _bounded_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"development screen input is not a regular file: {path}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(f"development screen input exceeds {_MAX_FILE_BYTES} bytes: {path}")
    return path.read_bytes()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_bounded_bytes(path)).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
    )


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _cleanup_temporary(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


__all__ = [
    "DevelopmentCaseabilityBatchOutput",
    "DevelopmentCaseabilityDecision",
    "DevelopmentScreenNormalizationManifest",
    "DevelopmentScreenPlan",
    "DevelopmentScreenRunSummary",
    "SciTasteBenchDevelopmentScreenConfig",
    "execute_scitastebench_development_screen",
    "normalize_scitastebench_development_screen",
    "prepare_scitastebench_development_screen",
]

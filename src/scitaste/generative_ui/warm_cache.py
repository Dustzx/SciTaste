"""Project-owned, explicitly authorized cache for model-authored fixed entry points."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.generative_ui.generation import WorkspaceGenerationRequest
from scitaste.generative_ui.intent import QuickIntentCatalog, QuickIntentRequest
from scitaste.generative_ui.planner import PlannerMode
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    decide_verification_route,
)
from scitaste.project.models import content_sha256, validate_project_id

if TYPE_CHECKING:
    from scitaste.generative_ui.application import GenerativeUIApplication

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_POLICY_BYTES = 64 * 1024
_MAX_INDEX_BYTES = 2 * 1024 * 1024


class ModelWarmCachePolicy(BaseModel):
    """Bound one owner authorization to one project, provider, model, and budget."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: SafeIdentifier
    project_id: ProjectIdentifier
    expected_provider: str = Field(min_length=1, max_length=128)
    expected_model: str = Field(min_length=1, max_length=128)
    quick_intent_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)
    cache_ttl_hours: int = Field(default=24, ge=1, le=720)
    max_provider_calls: int = Field(ge=1, le=32)
    max_input_tokens_per_call: int = Field(ge=1, le=1_000_000)
    max_output_tokens_per_call: int = Field(ge=1, le=32_000)
    max_response_cost_usd: float = Field(ge=0, le=100, allow_inf_nan=False)
    max_total_tokens: int = Field(ge=1, le=10_000_000)
    max_total_cost_usd: float = Field(ge=0, le=1_000, allow_inf_nan=False)
    owner_authorized: bool = False
    authorized_by: str | None = Field(default=None, min_length=1, max_length=200)
    authorized_at: datetime | None = None
    authorization_expires_at: datetime | None = None

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))

    @model_validator(mode="after")
    def policy_is_bounded_and_explicit(self) -> ModelWarmCachePolicy:
        if len(self.quick_intent_ids) != len(set(self.quick_intent_ids)):
            raise ValueError("warm-cache quick intent IDs must be unique")
        if self.max_provider_calls < len(self.quick_intent_ids):
            raise ValueError("warm-cache call budget cannot cover its selected quick intents")
        per_call_tokens = self.max_input_tokens_per_call + self.max_output_tokens_per_call
        required_calls = len(self.quick_intent_ids)
        if self.max_total_tokens < required_calls * per_call_tokens:
            raise ValueError("warm-cache token budget cannot cover its selected quick intents")
        if self.max_total_tokens > self.max_provider_calls * per_call_tokens:
            raise ValueError("warm-cache total token budget exceeds its per-call envelope")
        if self.max_total_cost_usd < required_calls * self.max_response_cost_usd:
            raise ValueError("warm-cache cost budget cannot cover its selected quick intents")
        if self.max_total_cost_usd > self.max_provider_calls * self.max_response_cost_usd:
            raise ValueError("warm-cache total cost budget exceeds its per-call envelope")
        approval = (self.authorized_by, self.authorized_at, self.authorization_expires_at)
        if self.owner_authorized:
            if any(item is None for item in approval):
                raise ValueError("authorized warm cache requires owner identity and time bounds")
            assert self.authorized_at is not None
            assert self.authorization_expires_at is not None
            if not _aware(self.authorized_at) or not _aware(self.authorization_expires_at):
                raise ValueError("warm-cache authorization timestamps must include a timezone")
            if self.authorization_expires_at <= self.authorized_at:
                raise ValueError("warm-cache authorization expiry must follow authorization")
        elif any(item is not None for item in approval):
            raise ValueError("inactive warm-cache policy cannot claim owner authorization")
        return self


class ModelWarmCacheAttempt(BaseModel):
    """One provider-call budget debit, including failed or rejected responses."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    quick_intent_id: SafeIdentifier
    intent_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    attempted_at: datetime
    status: Literal["model_generated", "provider_unavailable"]
    reason_code: SafeIdentifier
    generation_id: SafeIdentifier | None = None
    document_sha256: Sha256 | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    budgeted_tokens: int = Field(ge=0)
    budgeted_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    entry_expires_at: datetime | None = None

    @model_validator(mode="after")
    def attempt_is_atomic(self) -> ModelWarmCacheAttempt:
        if not _aware(self.attempted_at):
            raise ValueError("warm-cache attempt time must include a timezone")
        telemetry = (self.input_tokens, self.output_tokens, self.cost_usd, self.latency_ms)
        identity = (self.generation_id, self.document_sha256, self.entry_expires_at)
        if self.status == "model_generated":
            if any(item is None for item in telemetry) or any(item is None for item in identity):
                raise ValueError(
                    "model-generated warm-cache attempt requires identity and telemetry"
                )
            assert self.entry_expires_at is not None
            if not _aware(self.entry_expires_at) or self.entry_expires_at <= self.attempted_at:
                raise ValueError("warm-cache entry expiry is invalid")
            assert self.input_tokens is not None and self.output_tokens is not None
            assert self.cost_usd is not None
            if self.budgeted_tokens != self.input_tokens + self.output_tokens:
                raise ValueError("successful warm-cache token debit differs from telemetry")
            if self.budgeted_cost_usd != self.cost_usd:
                raise ValueError("successful warm-cache cost debit differs from telemetry")
        elif any(item is not None for item in (*telemetry, *identity)):
            raise ValueError("unavailable warm-cache attempt cannot claim generated output")
        return self


class ModelWarmCacheIndex(BaseModel):
    """Mutable pointer index; generated documents remain immutable in the archive."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    policy_id: SafeIdentifier
    policy_fingerprint: Sha256
    expected_provider: str = Field(min_length=1, max_length=128)
    expected_model: str = Field(min_length=1, max_length=128)
    quick_intent_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)
    max_provider_calls: int = Field(ge=1, le=32)
    max_total_tokens: int = Field(ge=1, le=10_000_000)
    max_total_cost_usd: float = Field(ge=0, le=1_000, allow_inf_nan=False)
    catalog_fingerprint: Sha256
    current_snapshot_revision: int = Field(ge=0)
    current_snapshot_sha256: Sha256
    attempts: tuple[ModelWarmCacheAttempt, ...] = Field(default=(), max_length=32)
    updated_at: datetime
    index_sha256: Sha256

    @property
    def fingerprint(self) -> str:
        return self.index_sha256

    @model_validator(mode="after")
    def index_hash_matches(self) -> ModelWarmCacheIndex:
        if not _aware(self.updated_at):
            raise ValueError("warm-cache index time must include a timezone")
        if len(self.quick_intent_ids) != len(set(self.quick_intent_ids)):
            raise ValueError("warm-cache index quick intent IDs must be unique")
        if len(self.attempts) > self.max_provider_calls:
            raise ValueError("warm-cache index exceeds its provider-call budget")
        if sum(item.budgeted_tokens for item in self.attempts) > self.max_total_tokens:
            raise ValueError("warm-cache index exceeds its token budget")
        if sum(item.budgeted_cost_usd for item in self.attempts) > self.max_total_cost_usd + 1e-12:
            raise ValueError("warm-cache index exceeds its cost budget")
        expected = content_sha256(self.model_dump(mode="json", exclude={"index_sha256"}))
        if self.index_sha256 != expected:
            raise ValueError("warm-cache index hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ModelWarmCacheIndex:
        payload = {"schema_version": "1.0", **values}
        payload.pop("index_sha256", None)
        unsigned = cls.model_construct(index_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"index_sha256"}))
        return cls(**payload, index_sha256=digest)


class ModelWarmCacheEntryView(BaseModel):
    model_config = _CONFIG

    quick_intent_id: SafeIdentifier
    generation_id: SafeIdentifier
    intent_fingerprint: Sha256
    document_sha256: Sha256
    entry_expires_at: datetime
    provider: str
    model: str


class CachedWorkspaceStartRequest(BaseModel):
    """Select one exact fresh cached model page as a conversation's first turn."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    quick_catalog_fingerprint: Sha256
    quick_intent_id: SafeIdentifier
    intent_fingerprint: Sha256
    generation_id: SafeIdentifier
    document_sha256: Sha256
    entry_expires_at: datetime

    @model_validator(mode="after")
    def expiry_is_timezone_aware(self) -> CachedWorkspaceStartRequest:
        if not _aware(self.entry_expires_at):
            raise ValueError("cached workspace expiry must include a timezone")
        return self


class ModelWarmCacheStatus(BaseModel):
    """Safe receiver projection for fixed model-authored project entry points."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    catalog_fingerprint: Sha256
    status: Literal["not_configured", "fresh", "partial", "stale", "exhausted"]
    policy_id: SafeIdentifier | None = None
    policy_fingerprint: Sha256 | None = None
    expected_entry_count: int = Field(default=0, ge=0, le=8)
    fresh_entries: tuple[ModelWarmCacheEntryView, ...] = Field(default=(), max_length=8)
    provider_calls_consumed: int = Field(default=0, ge=0, le=32)
    budgeted_tokens_consumed: int = Field(default=0, ge=0)
    budgeted_cost_usd_consumed: float = Field(default=0, ge=0, allow_inf_nan=False)
    execution_authority: Literal["none"] = "none"

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ModelWarmCacheRunReport(BaseModel):
    """Result of one bounded proactive generation pass."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    policy_id: SafeIdentifier
    policy_fingerprint: Sha256
    verification: VerificationDecision
    owner_authorization_satisfied: Literal[True] = True
    new_provider_calls: int = Field(ge=0, le=32)
    new_model_generations: int = Field(ge=0, le=8)
    status: ModelWarmCacheStatus
    external_action_performed: bool
    execution_authority: Literal["bounded-model-generation-only"] = "bounded-model-generation-only"


class ModelWarmCacheStore:
    """Persist one integrity-checked warm-cache index inside its project."""

    def __init__(self, projects_root: Path) -> None:
        self._projects_root = projects_root

    def load(self, project_id: str) -> ModelWarmCacheIndex | None:
        path = self._path(project_id, create=False)
        if not path.exists():
            return None
        return ModelWarmCacheIndex.model_validate_json(_read_regular(path, _MAX_INDEX_BYTES))

    def store(self, index: ModelWarmCacheIndex) -> None:
        path = self._path(index.project_id, create=True)
        payload = _canonical_bytes(index.model_dump(mode="json"))
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            os.close(descriptor)
            if temporary.exists():
                temporary.unlink()

    def _path(self, project_id: str, *, create: bool) -> Path:
        validate_project_id(project_id)
        root = self._projects_root.resolve(strict=True)
        project = self._projects_root / project_id
        if project.is_symlink():
            raise ValueError("warm-cache project cannot be a symbolic link")
        resolved = project.resolve(strict=True)
        resolved.relative_to(root)
        directory = resolved / ".generative-ui" / "warm-cache"
        if directory.is_symlink():
            raise ValueError("warm-cache directory cannot be a symbolic link")
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory / "index.json"


class ModelWarmCacheService:
    """Generate selected fixed project pages without weakening ordinary chat flexibility."""

    def __init__(
        self,
        application: GenerativeUIApplication,
        policy: ModelWarmCachePolicy,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._application = application
        self.policy = ModelWarmCachePolicy.model_validate(
            policy.model_dump(mode="json", exclude={"fingerprint"})
        )
        self._store = ModelWarmCacheStore(application.outputs_root / "projects")
        self._now = now or (lambda: datetime.now(UTC))

    def warm(self) -> ModelWarmCacheRunReport:
        now = self._now()
        if not _aware(now):
            raise ValueError("warm-cache clock must include a timezone")
        if not self.policy.owner_authorized:
            raise ValueError("warm-cache model calls require explicit owner authorization")
        assert self.policy.authorization_expires_at is not None
        if now >= self.policy.authorization_expires_at:
            raise ValueError("warm-cache owner authorization has expired")
        identity = self._application.planner_identity
        planner_policy = self._application.model_planner_policy
        if (
            identity.implementation != "structured-model-v1"
            or identity.backend != self.policy.expected_provider
            or identity.model != self.policy.expected_model
            or planner_policy is None
        ):
            raise ValueError("warm-cache policy and active model planner identity differ")
        if (
            planner_policy.max_input_tokens > self.policy.max_input_tokens_per_call
            or planner_policy.max_output_tokens > self.policy.max_output_tokens_per_call
            or planner_policy.max_response_cost_usd > self.policy.max_response_cost_usd
        ):
            raise ValueError("active model planner exceeds warm-cache per-call bounds")

        catalog = self._application.quick_intents(self.policy.project_id)
        descriptors = {item.quick_intent_id: item for item in catalog.intents}
        missing = set(self.policy.quick_intent_ids) - set(descriptors)
        if missing:
            raise ValueError("warm-cache policy selects an unavailable quick intent")
        previous = self._store.load(self.policy.project_id)
        attempts = list(previous.attempts) if _same_policy(previous, self.policy) else []
        consumed_calls = len(attempts)
        consumed_tokens = sum(item.budgeted_tokens for item in attempts)
        consumed_cost = sum(item.budgeted_cost_usd for item in attempts)
        current_successes = {
            item.quick_intent_id: item
            for item in attempts
            if item.status == "model_generated"
            and item.snapshot_sha256 == catalog.snapshot.snapshot_sha256
            and item.entry_expires_at is not None
            and item.entry_expires_at > now
        }
        new_calls = 0
        new_generations = 0
        for quick_intent_id in self.policy.quick_intent_ids:
            if quick_intent_id in current_successes:
                continue
            if consumed_calls >= self.policy.max_provider_calls:
                break
            remaining_tokens = self.policy.max_total_tokens - consumed_tokens
            remaining_cost = self.policy.max_total_cost_usd - consumed_cost
            per_call_tokens = (
                self.policy.max_input_tokens_per_call + self.policy.max_output_tokens_per_call
            )
            if remaining_tokens < per_call_tokens or (
                remaining_cost + 1e-12 < self.policy.max_response_cost_usd
            ):
                break
            descriptor = descriptors[quick_intent_id]
            document = self._application.generate_workspace(
                self.policy.project_id,
                WorkspaceGenerationRequest(
                    quick_catalog_fingerprint=catalog.fingerprint,
                    intent_request=QuickIntentRequest(
                        project_id=self.policy.project_id,
                        snapshot_revision=catalog.snapshot.snapshot_revision,
                        snapshot_sha256=catalog.snapshot.snapshot_sha256,
                        quick_intent_id=quick_intent_id,
                    ),
                ),
            )
            new_calls += 1
            consumed_calls += 1
            provenance = document.planning.provenance if document.planning is not None else None
            generated = (
                document.status == "generated"
                and document.renderer is not None
                and provenance is not None
                and provenance.mode is PlannerMode.MODEL_ASSISTED
                and provenance.planner.backend == self.policy.expected_provider
                and provenance.planner.model == self.policy.expected_model
                and provenance.input_tokens is not None
                and provenance.output_tokens is not None
                and provenance.cost_usd is not None
                and provenance.latency_ms is not None
            )
            if generated:
                assert document.renderer is not None and provenance is not None
                attempt = ModelWarmCacheAttempt(
                    quick_intent_id=quick_intent_id,
                    intent_fingerprint=descriptor.intent_fingerprint,
                    snapshot_revision=catalog.snapshot.snapshot_revision,
                    snapshot_sha256=catalog.snapshot.snapshot_sha256,
                    attempted_at=now,
                    status="model_generated",
                    reason_code=document.reason_code,
                    generation_id=document.renderer.surface_id,
                    document_sha256=content_sha256(document.model_dump(mode="json")),
                    input_tokens=provenance.input_tokens,
                    output_tokens=provenance.output_tokens,
                    cost_usd=provenance.cost_usd,
                    latency_ms=provenance.latency_ms,
                    budgeted_tokens=provenance.input_tokens + provenance.output_tokens,
                    budgeted_cost_usd=provenance.cost_usd,
                    entry_expires_at=now + timedelta(hours=self.policy.cache_ttl_hours),
                )
                new_generations += 1
                current_successes[quick_intent_id] = attempt
            else:
                attempt = ModelWarmCacheAttempt(
                    quick_intent_id=quick_intent_id,
                    intent_fingerprint=descriptor.intent_fingerprint,
                    snapshot_revision=catalog.snapshot.snapshot_revision,
                    snapshot_sha256=catalog.snapshot.snapshot_sha256,
                    attempted_at=now,
                    status="provider_unavailable",
                    reason_code=document.reason_code,
                    budgeted_tokens=per_call_tokens,
                    budgeted_cost_usd=self.policy.max_response_cost_usd,
                )
            attempts.append(attempt)
            consumed_tokens += attempt.budgeted_tokens
            consumed_cost += attempt.budgeted_cost_usd

        index = ModelWarmCacheIndex.create(
            project_id=self.policy.project_id,
            policy_id=self.policy.policy_id,
            policy_fingerprint=self.policy.fingerprint,
            expected_provider=self.policy.expected_provider,
            expected_model=self.policy.expected_model,
            quick_intent_ids=self.policy.quick_intent_ids,
            max_provider_calls=self.policy.max_provider_calls,
            max_total_tokens=self.policy.max_total_tokens,
            max_total_cost_usd=self.policy.max_total_cost_usd,
            catalog_fingerprint=catalog.fingerprint,
            current_snapshot_revision=catalog.snapshot.snapshot_revision,
            current_snapshot_sha256=catalog.snapshot.snapshot_sha256,
            attempts=tuple(attempts),
            updated_at=now,
        )
        self._store.store(index)
        status = model_warm_cache_status(
            catalog,
            index,
            policy=self.policy,
            now=now,
        )
        return ModelWarmCacheRunReport(
            project_id=self.policy.project_id,
            policy_id=self.policy.policy_id,
            policy_fingerprint=self.policy.fingerprint,
            verification=model_warm_cache_verification(self.policy),
            owner_authorization_satisfied=True,
            new_provider_calls=new_calls,
            new_model_generations=new_generations,
            status=status,
            external_action_performed=new_calls > 0,
        )


def model_warm_cache_verification(policy: ModelWarmCachePolicy) -> VerificationDecision:
    """Route only the paid provider action; cache reads themselves need no precheck."""

    action = VerificationDecisionInput(
        action_id=f"warm-cache-{policy.policy_id}",
        reversibility=ActionReversibility.COSTLY_TO_REVERSE,
        effects=(
            ActionEffect.NETWORK_READ,
            ActionEffect.FILESYSTEM_WRITE,
            ActionEffect.SECRET_ACCESS,
            ActionEffect.PAID_COMPUTE,
            ActionEffect.DECLARED_OWNER_BOUNDARY,
        ),
        evidence_state="current",
        semantic_uncertainty="low",
        failure_probability=0.05,
        failure_impact_units=30,
        targeted_check_cost_units=1,
        targeted_detection_probability=0.8,
        full_preflight_cost_units=4,
        full_preflight_detection_probability=0.95,
    )
    return decide_verification_route(action)


def model_warm_cache_status(
    catalog: QuickIntentCatalog,
    index: ModelWarmCacheIndex | None,
    *,
    policy: ModelWarmCachePolicy | None = None,
    now: datetime | None = None,
) -> ModelWarmCacheStatus:
    now = now or datetime.now(UTC)
    if index is None:
        return ModelWarmCacheStatus(
            project_id=catalog.snapshot.project_id,
            snapshot_revision=catalog.snapshot.snapshot_revision,
            snapshot_sha256=catalog.snapshot.snapshot_sha256,
            catalog_fingerprint=catalog.fingerprint,
            status="not_configured",
        )
    current = (
        index.current_snapshot_sha256 == catalog.snapshot.snapshot_sha256
        and index.catalog_fingerprint == catalog.fingerprint
    )
    selected_ids = (
        set(policy.quick_intent_ids) if policy is not None else set(index.quick_intent_ids)
    )
    descriptor_map = {item.quick_intent_id: item for item in catalog.intents}
    fresh: list[ModelWarmCacheEntryView] = []
    if current:
        for attempt in index.attempts:
            descriptor = descriptor_map.get(attempt.quick_intent_id)
            if (
                descriptor is None
                or attempt.quick_intent_id not in selected_ids
                or attempt.status != "model_generated"
                or attempt.snapshot_sha256 != catalog.snapshot.snapshot_sha256
                or attempt.intent_fingerprint != descriptor.intent_fingerprint
                or attempt.entry_expires_at is None
                or attempt.entry_expires_at <= now
                or attempt.generation_id is None
            ):
                continue
            fresh.append(
                ModelWarmCacheEntryView(
                    quick_intent_id=attempt.quick_intent_id,
                    generation_id=attempt.generation_id,
                    intent_fingerprint=attempt.intent_fingerprint,
                    document_sha256=attempt.document_sha256,
                    entry_expires_at=attempt.entry_expires_at,
                    provider=index.expected_provider,
                    model=index.expected_model,
                )
            )
    consumed_calls = len(index.attempts)
    if not current:
        state: Literal["fresh", "partial", "stale", "exhausted"] = "stale"
    elif consumed_calls >= index.max_provider_calls and len(fresh) < len(selected_ids):
        state = "exhausted"
    elif len(fresh) == len(selected_ids) and selected_ids:
        state = "fresh"
    else:
        state = "partial"
    return ModelWarmCacheStatus(
        project_id=catalog.snapshot.project_id,
        snapshot_revision=catalog.snapshot.snapshot_revision,
        snapshot_sha256=catalog.snapshot.snapshot_sha256,
        catalog_fingerprint=catalog.fingerprint,
        status=state,
        policy_id=index.policy_id,
        policy_fingerprint=index.policy_fingerprint,
        expected_entry_count=len(selected_ids),
        fresh_entries=tuple(fresh),
        provider_calls_consumed=consumed_calls,
        budgeted_tokens_consumed=sum(item.budgeted_tokens for item in index.attempts),
        budgeted_cost_usd_consumed=sum(item.budgeted_cost_usd for item in index.attempts),
    )


def load_model_warm_cache_policy(path: Path) -> ModelWarmCachePolicy:
    payload = yaml.safe_load(_read_regular(path, _MAX_POLICY_BYTES).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("warm-cache policy must be a YAML object")
    return ModelWarmCachePolicy.model_validate(payload)


def _same_policy(
    index: ModelWarmCacheIndex | None,
    policy: ModelWarmCachePolicy,
) -> bool:
    return bool(
        index is not None
        and index.project_id == policy.project_id
        and index.policy_id == policy.policy_id
        and index.policy_fingerprint == policy.fingerprint
        and index.expected_provider == policy.expected_provider
        and index.expected_model == policy.expected_model
        and index.quick_intent_ids == policy.quick_intent_ids
        and index.max_provider_calls == policy.max_provider_calls
        and index.max_total_tokens == policy.max_total_tokens
        and index.max_total_cost_usd == policy.max_total_cost_usd
    )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _read_regular(path: Path, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise ValueError("warm-cache file cannot be a symbolic link")
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("warm-cache file must be regular")
        if metadata.st_size > max_bytes:
            raise ValueError("warm-cache file is too large")
        data = os.read(descriptor, max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("warm-cache file is too large")
        return data
    finally:
        os.close(descriptor)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "CachedWorkspaceStartRequest",
    "ModelWarmCacheAttempt",
    "ModelWarmCacheEntryView",
    "ModelWarmCacheIndex",
    "ModelWarmCachePolicy",
    "ModelWarmCacheRunReport",
    "ModelWarmCacheService",
    "ModelWarmCacheStatus",
    "ModelWarmCacheStore",
    "load_model_warm_cache_policy",
    "model_warm_cache_status",
    "model_warm_cache_verification",
]

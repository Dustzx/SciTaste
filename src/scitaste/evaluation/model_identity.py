"""No-run identity controls for mutable hosted models used in formal studies.

Hosted APIs commonly expose a stable callable name while changing the model
behind that name.  Treating every rolling alias as unusable is impractical;
treating the alias as an immutable checkpoint is scientifically misleading.
This module defines the middle ground: an exact, time-bounded model stratum
bracketed by identity-only sentinels, with mandatory split-on-drift semantics.

Loading or inspecting a protocol never performs a network request.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256, validate_project_id
from scitaste.resources import ApiModelDefinition, ObservationStatus

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PROTOCOL_BYTES = 1_048_576


class ApiIdentityMode(StrEnum):
    """Evidence available for identifying one hosted-model stratum."""

    OFFICIAL_REVISION_PLUS_TEMPORAL_WINDOW = "official_revision_plus_temporal_window"
    TEMPORAL_WINDOW_ONLY = "temporal_window_only"


class ApiIdentityWindowKind(StrEnum):
    CONFORMANCE = "conformance"
    FORMAL = "formal"


class ApiIdentityCallRole(StrEnum):
    START_SENTINEL = "start_sentinel"
    PERIODIC_SENTINEL = "periodic_sentinel"
    WORKLOAD = "workload"
    END_SENTINEL = "end_sentinel"


class ApiIdentityCandidatePolicy(BaseModel):
    model_config = _CONFIG

    resource_id: str = Field(pattern=_ID)
    identity_mode: ApiIdentityMode
    official_revision: str | None = Field(default=None, min_length=1, max_length=200)
    maximum_formal_window_hours: int = Field(gt=0, le=24)
    returned_identity_policy: Literal["declared_allowlist"] = "declared_allowlist"
    allowed_returned_model_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    official_catalog_rechecked_at_window_open: Literal[True] = True
    official_catalog_rechecked_at_window_close: Literal[True] = True
    start_sentinel_required: Literal[True] = True
    end_sentinel_required: Literal[True] = True
    sentinel_after_maximum_calls: int = Field(gt=0, le=100)
    pilot_and_formal_windows_are_distinct: Literal[True] = True

    @model_validator(mode="after")
    def revision_matches_identity_mode(self) -> ApiIdentityCandidatePolicy:
        if len(self.allowed_returned_model_ids) != len(set(self.allowed_returned_model_ids)):
            raise ValueError("allowed returned API model IDs must be unique")
        has_revision = self.official_revision is not None
        requires_revision = (
            self.identity_mode is ApiIdentityMode.OFFICIAL_REVISION_PLUS_TEMPORAL_WINDOW
        )
        if has_revision != requires_revision:
            raise ValueError("official revision must be present only for revision-backed mode")
        return self


class ApiIdentitySentinel(BaseModel):
    model_config = _CONFIG

    purpose: Literal["identity_only_no_task_data"] = "identity_only_no_task_data"
    system_message: str = Field(min_length=1, max_length=500)
    user_message: str = Field(min_length=1, max_length=500)
    response_format: Literal["json_object"] = "json_object"
    max_output_tokens: int = Field(gt=0, le=128)
    task_or_benchmark_content_allowed: Literal[False] = False


class ApiIdentityProtocol(BaseModel):
    """Human-authored protocol; it specifies controls but opens no API window."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    sentinel: ApiIdentitySentinel
    candidate_policies: tuple[ApiIdentityCandidatePolicy, ...] = Field(
        min_length=1, max_length=10
    )
    capture_fields: tuple[str, ...] = Field(min_length=12, max_length=30)
    retain_raw_request: Literal[True] = True
    retain_raw_response: Literal[True] = True
    missing_identity_action: Literal["abort_window"] = "abort_window"
    drift_action: Literal["close_window_and_open_new_stratum"] = (
        "close_window_and_open_new_stratum"
    )
    cross_window_pooling: Literal[False] = False
    cross_revision_pooling: Literal[False] = False
    cross_provider_pooling: Literal[False] = False
    candidate_selected_before_formal_outcomes: Literal[True] = True
    conformance_data_excluded_from_formal_tests: Literal[True] = True
    authorizes_api_calls: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def protocol_is_closed(self) -> ApiIdentityProtocol:
        validate_project_id(self.project_id)
        resource_ids = [item.resource_id for item in self.candidate_policies]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("API identity candidate resource IDs must be unique")
        required_capture = {
            "provider_id",
            "endpoint",
            "interface",
            "requested_model_id",
            "returned_model",
            "official_revision",
            "provider_request_id",
            "request_started_at_utc",
            "response_completed_at_utc",
            "request_sha256",
            "response_sha256",
            "http_status",
            "input_tokens",
            "output_tokens",
        }
        if len(self.capture_fields) != len(set(self.capture_fields)):
            raise ValueError("API identity capture fields must be unique")
        missing = required_capture - set(self.capture_fields)
        if missing:
            raise ValueError(
                "API identity protocol omits required capture fields: "
                + ", ".join(sorted(missing))
            )
        return self

    def policy(self, resource_id: str) -> ApiIdentityCandidatePolicy:
        try:
            return next(
                item for item in self.candidate_policies if item.resource_id == resource_id
            )
        except StopIteration as exc:
            raise ValueError(f"API identity protocol omits {resource_id!r}") from exc

    @property
    def sentinel_template_sha256(self) -> str:
        return content_sha256(self.sentinel.model_dump(mode="json"))


class ApiIdentityProtocolInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)
    protocol: ApiIdentityProtocol
    external_action_performed: Literal[False] = False


class ApiIdentityCandidateQualification(BaseModel):
    """Static launch-gate projection; never claims a live attestation occurred."""

    model_config = _CONFIG

    resource_id: str = Field(pattern=_ID)
    identity_mode: ApiIdentityMode
    official_revision: str | None = Field(default=None, max_length=200)
    rolling_alias: bool
    temporal_protocol_defined: Literal[True] = True
    authenticated_identity_attested: bool
    pricing_verified: bool
    pilot_proposal_ready: bool
    formal_identity_ready: Literal[False] = False
    blocker_codes: tuple[str, ...]

    @model_validator(mode="after")
    def readiness_is_derived(self) -> ApiIdentityCandidateQualification:
        expected = self.pricing_verified and self.temporal_protocol_defined
        if self.pilot_proposal_ready != expected:
            raise ValueError("API identity pilot-proposal readiness differs from evidence")
        if self.formal_identity_ready:
            raise ValueError("a static protocol cannot open a formal identity window")
        return self


class ApiIdentityCallReceipt(BaseModel):
    """One retained provider call; callers construct it only from real receipts."""

    model_config = _CONFIG

    sequence: int = Field(ge=1)
    role: ApiIdentityCallRole
    provider_id: str = Field(pattern=_ID)
    endpoint: str = Field(min_length=1, max_length=2_000)
    interface: Literal["openai-chat-completions", "openai-responses"]
    requested_model_id: str = Field(min_length=1, max_length=200)
    returned_model: str = Field(min_length=1, max_length=200)
    provider_request_id: str = Field(min_length=1, max_length=500)
    request_started_at_utc: datetime
    response_completed_at_utc: datetime
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    raw_request_ref: str = Field(min_length=1, max_length=1_000)
    raw_response_ref: str = Field(min_length=1, max_length=1_000)
    http_status: int = Field(ge=100, le=599)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    sentinel_template_sha256: str | None = Field(default=None, pattern=_SHA256)
    task_or_benchmark_content_present: bool

    @model_validator(mode="after")
    def receipt_is_temporally_and_semantically_closed(self) -> ApiIdentityCallReceipt:
        if (
            self.request_started_at_utc.tzinfo is None
            or self.response_completed_at_utc.tzinfo is None
            or self.response_completed_at_utc < self.request_started_at_utc
        ):
            raise ValueError("API identity call timestamps must be aware and ordered")
        for locator in (self.raw_request_ref, self.raw_response_ref):
            pure = PurePosixPath(locator)
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise ValueError("API identity raw artifact locators must be relative POSIX paths")
        is_sentinel = self.role is not ApiIdentityCallRole.WORKLOAD
        if is_sentinel:
            if self.sentinel_template_sha256 is None:
                raise ValueError("identity sentinels require the exact template hash")
            if self.task_or_benchmark_content_present:
                raise ValueError("identity sentinels cannot contain task or benchmark content")
        elif self.sentinel_template_sha256 is not None:
            raise ValueError("workload calls cannot claim an identity-sentinel template")
        return self


class ApiIdentityWindowAttestation(BaseModel):
    """Closed receipt set for one approved API window."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    window_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    protocol_id: str = Field(pattern=_ID)
    protocol_semantic_sha256: str = Field(pattern=_SHA256)
    resource_id: str = Field(pattern=_ID)
    kind: ApiIdentityWindowKind
    opened_at_utc: datetime
    closed_at_utc: datetime
    official_catalog_open_sha256: str = Field(pattern=_SHA256)
    official_catalog_close_sha256: str = Field(pattern=_SHA256)
    official_revision_at_open: str | None = Field(default=None, max_length=200)
    official_revision_at_close: str | None = Field(default=None, max_length=200)
    execution_approval_sha256: str = Field(pattern=_SHA256)
    approval_recorded_before_open: Literal[True] = True
    prior_conformance_window_id: str | None = Field(default=None, pattern=_ID)
    candidate_selection_sha256: str | None = Field(default=None, pattern=_SHA256)
    candidate_selected_at_utc: datetime | None = None
    calls: tuple[ApiIdentityCallReceipt, ...] = Field(min_length=2, max_length=10_000)
    attestation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def window_is_closed_and_self_hashed(self) -> ApiIdentityWindowAttestation:
        validate_project_id(self.project_id)
        if (
            self.opened_at_utc.tzinfo is None
            or self.closed_at_utc.tzinfo is None
            or self.closed_at_utc < self.opened_at_utc
        ):
            raise ValueError("API identity window timestamps must be aware and ordered")
        sequences = [item.sequence for item in self.calls]
        if sequences != list(range(1, len(self.calls) + 1)):
            raise ValueError("API identity call sequence must be contiguous and ordered")
        formal_fields = (
            self.prior_conformance_window_id,
            self.candidate_selection_sha256,
            self.candidate_selected_at_utc,
        )
        if self.kind is ApiIdentityWindowKind.FORMAL:
            if any(item is None for item in formal_fields):
                raise ValueError("formal identity windows require prior selection provenance")
            if self.candidate_selected_at_utc >= self.opened_at_utc:
                raise ValueError("formal model selection must precede the identity window")
        elif any(item is not None for item in formal_fields):
            raise ValueError("conformance windows cannot carry formal selection provenance")
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"attestation_sha256"})
        )
        if self.attestation_sha256 != expected:
            raise ValueError("API identity window attestation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ApiIdentityWindowAttestation:
        payload = {"schema_version": "1.0", **values}
        payload.pop("attestation_sha256", None)
        unsigned = cls.model_construct(attestation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            attestation_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"attestation_sha256"})
            ),
        )


class ApiIdentityWindowReport(BaseModel):
    """Admission result for one window; it is identity evidence, not efficacy evidence."""

    model_config = _CONFIG

    window_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    kind: ApiIdentityWindowKind
    attestation_sha256: str = Field(pattern=_SHA256)
    identity_stratum_sha256: str = Field(pattern=_SHA256)
    call_count: int = Field(ge=2)
    sentinel_count: int = Field(ge=2)
    returned_model_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    duration_seconds: float = Field(ge=0)
    admitted: bool
    formal_use_eligible: bool
    blocker_codes: tuple[str, ...]
    cross_window_pooling_allowed: Literal[False] = False
    scientific_effectiveness_established: Literal[False] = False

    @model_validator(mode="after")
    def report_readiness_matches_blockers(self) -> ApiIdentityWindowReport:
        if self.admitted != (not self.blocker_codes):
            raise ValueError("API identity window admission differs from blockers")
        if self.formal_use_eligible != (
            self.admitted and self.kind is ApiIdentityWindowKind.FORMAL
        ):
            raise ValueError("formal API identity eligibility differs from window evidence")
        return self


def load_api_identity_protocol(path: str | Path) -> ApiIdentityProtocolInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("API identity protocol must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_PROTOCOL_BYTES:
        raise ValueError("API identity protocol must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("API identity protocol must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("API identity protocol must contain a YAML mapping")
    protocol = ApiIdentityProtocol.model_validate(payload)
    return ApiIdentityProtocolInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        semantic_sha256=content_sha256(protocol.model_dump(mode="json")),
        protocol=protocol,
    )


def qualify_api_identity_candidate(
    resource: ApiModelDefinition,
    policy: ApiIdentityCandidatePolicy,
) -> ApiIdentityCandidateQualification:
    """Check whether identity and price facts can support a bounded pilot proposal."""

    if policy.resource_id != resource.resource_id:
        raise ValueError("API identity policy and resource differ")
    if not resource.rolling_alias:
        raise ValueError("temporal API identity protocol is only for rolling aliases")
    if resource.model_id not in policy.allowed_returned_model_ids:
        raise ValueError("callable API model ID is absent from the returned-identity allowlist")
    if (
        policy.identity_mode is ApiIdentityMode.OFFICIAL_REVISION_PLUS_TEMPORAL_WINDOW
        and policy.official_revision != resource.model_revision
    ):
        raise ValueError("official API revision differs from the resource catalog")
    if (
        policy.official_revision is not None
        and policy.official_revision not in policy.allowed_returned_model_ids
    ):
        raise ValueError("official API revision is absent from the identity allowlist")
    pricing_verified = (
        resource.pricing is not None
        and resource.pricing.status is ObservationStatus.VERIFIED
    )
    authenticated = resource.availability is ObservationStatus.VERIFIED
    blockers = []
    if not authenticated:
        blockers.append("authenticated_identity_attestation_not_observed")
    if not pricing_verified:
        blockers.append("pricing_ceiling_not_verified")
    blockers.append("formal_identity_window_not_open")
    return ApiIdentityCandidateQualification(
        resource_id=resource.resource_id,
        identity_mode=policy.identity_mode,
        official_revision=policy.official_revision,
        rolling_alias=resource.rolling_alias,
        authenticated_identity_attested=authenticated,
        pricing_verified=pricing_verified,
        pilot_proposal_ready=pricing_verified,
        blocker_codes=tuple(blockers),
    )


def inspect_api_identity_window(
    attestation: ApiIdentityWindowAttestation,
    *,
    protocol_inspection: ApiIdentityProtocolInspection,
    resource: ApiModelDefinition,
) -> ApiIdentityWindowReport:
    """Admit one closed window or return exact, non-waivable identity blockers."""

    protocol = protocol_inspection.protocol
    policy = protocol.policy(attestation.resource_id)
    blockers: list[str] = []
    if attestation.project_id != protocol.project_id:
        blockers.append("project_identity_mismatch")
    if attestation.protocol_id != protocol.protocol_id or (
        attestation.protocol_semantic_sha256 != protocol_inspection.semantic_sha256
    ):
        blockers.append("protocol_identity_mismatch")
    if attestation.resource_id != resource.resource_id:
        blockers.append("resource_identity_mismatch")
    duration_seconds = (
        attestation.closed_at_utc - attestation.opened_at_utc
    ).total_seconds()
    if duration_seconds > policy.maximum_formal_window_hours * 3_600:
        blockers.append("identity_window_duration_exceeded")
    if policy.official_revision is not None:
        if (
            attestation.official_revision_at_open != policy.official_revision
            or attestation.official_revision_at_close != policy.official_revision
        ):
            blockers.append("official_revision_drift")
    elif (
        attestation.official_revision_at_open is not None
        or attestation.official_revision_at_close is not None
    ):
        blockers.append("undisclosed_revision_must_not_be_invented")
    if attestation.calls[0].role is not ApiIdentityCallRole.START_SENTINEL:
        blockers.append("start_sentinel_missing")
    if attestation.calls[-1].role is not ApiIdentityCallRole.END_SENTINEL:
        blockers.append("end_sentinel_missing")
    if any(
        attestation.calls[0].response_completed_at_utc > item.request_started_at_utc
        for item in attestation.calls[1:]
    ):
        blockers.append("start_sentinel_does_not_precede_calls")
    if any(
        attestation.calls[-1].request_started_at_utc < item.response_completed_at_utc
        for item in attestation.calls[:-1]
    ):
        blockers.append("end_sentinel_does_not_follow_calls")

    expected_sentinel = protocol.sentinel_template_sha256
    workload_since_sentinel = 0
    returned_models: list[str] = []
    request_ids: list[str] = []
    for call in attestation.calls:
        if (
            call.request_started_at_utc < attestation.opened_at_utc
            or call.response_completed_at_utc > attestation.closed_at_utc
        ):
            blockers.append("call_outside_identity_window")
        if (
            call.provider_id != resource.provider_id
            or call.endpoint != resource.endpoint
            or call.interface != resource.interface
        ):
            blockers.append("provider_interface_drift")
        if call.requested_model_id != resource.model_id:
            blockers.append("requested_model_drift")
        if call.returned_model not in policy.allowed_returned_model_ids:
            blockers.append("returned_model_not_allowed")
        if not 200 <= call.http_status < 300:
            blockers.append("provider_call_failed")
        if call.role is ApiIdentityCallRole.WORKLOAD:
            workload_since_sentinel += 1
            if workload_since_sentinel > policy.sentinel_after_maximum_calls:
                blockers.append("periodic_sentinel_interval_exceeded")
        else:
            if call.sentinel_template_sha256 != expected_sentinel:
                blockers.append("sentinel_template_drift")
            workload_since_sentinel = 0
        returned_models.append(call.returned_model)
        request_ids.append(call.provider_request_id)
    if len(request_ids) != len(set(request_ids)):
        blockers.append("provider_request_id_reused")

    unique_returned = tuple(dict.fromkeys(returned_models))
    blockers = list(dict.fromkeys(blockers))
    stratum_payload = {
        "protocol_semantic_sha256": protocol_inspection.semantic_sha256,
        "resource_id": resource.resource_id,
        "provider_id": resource.provider_id,
        "endpoint": resource.endpoint,
        "interface": resource.interface,
        "requested_model_id": resource.model_id,
        "official_revision": policy.official_revision,
        "window_id": attestation.window_id,
        "opened_at_utc": attestation.opened_at_utc.isoformat(),
        "closed_at_utc": attestation.closed_at_utc.isoformat(),
        "returned_model_ids": unique_returned,
        "official_catalog_open_sha256": attestation.official_catalog_open_sha256,
        "official_catalog_close_sha256": attestation.official_catalog_close_sha256,
    }
    admitted = not blockers
    return ApiIdentityWindowReport(
        window_id=attestation.window_id,
        resource_id=attestation.resource_id,
        kind=attestation.kind,
        attestation_sha256=attestation.attestation_sha256,
        identity_stratum_sha256=content_sha256(stratum_payload),
        call_count=len(attestation.calls),
        sentinel_count=sum(
            item.role is not ApiIdentityCallRole.WORKLOAD for item in attestation.calls
        ),
        returned_model_ids=unique_returned,
        duration_seconds=duration_seconds,
        admitted=admitted,
        formal_use_eligible=admitted and attestation.kind is ApiIdentityWindowKind.FORMAL,
        blocker_codes=tuple(blockers),
    )


__all__ = [
    "ApiIdentityCallReceipt",
    "ApiIdentityCallRole",
    "ApiIdentityCandidatePolicy",
    "ApiIdentityCandidateQualification",
    "ApiIdentityMode",
    "ApiIdentityProtocol",
    "ApiIdentityProtocolInspection",
    "ApiIdentitySentinel",
    "ApiIdentityWindowAttestation",
    "ApiIdentityWindowKind",
    "ApiIdentityWindowReport",
    "inspect_api_identity_window",
    "load_api_identity_protocol",
    "qualify_api_identity_candidate",
]

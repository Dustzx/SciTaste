"""Fail-closed provider execution for prospective decision segmentation.

This layer deliberately sits outside the legacy segmentation normalizers.  A
provider returns only task outputs; a trusted runner, rather than the model,
records the input-firewall and identity evidence used to interpret them.
Loading or inspecting any object in this module performs no network action.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.evaluation.model_identity import (
    ApiIdentityCallReceipt,
    ApiIdentityCallRole,
    ApiIdentityProtocolInspection,
    load_api_identity_protocol,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationProspectiveProtocol,
    TasteSourceSegmentationProtocolInspection,
    TasteSourceSegmentationRequestPack,
    TasteSourceSegmentationRequestPacket,
    inspect_taste_source_segmentation_protocol,
    load_taste_source_segmentation_request_pack,
    load_taste_source_segmentation_request_packet,
)
from scitaste.resources import ApiModelDefinition

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_AUTHORIZATION_BYTES = 2 * 1_048_576
_MAX_PACKET_BYTES = 64 * 1_048_576
_MAX_RESPONSE_BYTES = 16 * 1_048_576


class SegmentationExecutionFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationExecutionFileBinding:
        _safe_locator(self.locator)
        return self


class SegmentationExecutionPackBinding(SegmentationExecutionFileBinding):
    pack_sha256: str = Field(pattern=_SHA256)


class SegmentationExecutionRunnerBinding(SegmentationExecutionFileBinding):
    git_commit: str = Field(pattern=_COMMIT)
    cli_locator: str = Field(min_length=1, max_length=2_000)
    cli_file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def cli_locator_is_safe(self) -> SegmentationExecutionRunnerBinding:
        _safe_locator(self.cli_locator)
        return self


class SegmentationExecutionPriceCeiling(BaseModel):
    """Conservative liability bound, not a claim about the provider invoice."""

    model_config = _CONFIG

    currency: Literal["USD"] = "USD"
    maximum_input_usd_per_million_tokens: float = Field(gt=0, allow_inf_nan=False)
    maximum_output_usd_per_million_tokens: float = Field(gt=0, allow_inf_nan=False)
    maximum_total_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    basis: Literal["owner-approved-conservative-liability-ceiling"]
    pricing_source_url: str = Field(min_length=1, max_length=2_000)
    pricing_observed_at: datetime
    exact_provider_invoice_claimed: Literal[False] = False

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> SegmentationExecutionPriceCeiling:
        if self.pricing_observed_at.utcoffset() is None:
            raise ValueError("Segmentation price observation time must include a timezone")
        return self


class SegmentationExecutionLimits(BaseModel):
    model_config = _CONFIG

    maximum_provider_requests: int = Field(gt=0, le=100)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    retry_count: Literal[0] = 0
    timeout_seconds_per_request: float = Field(gt=0, le=600, allow_inf_nan=False)
    maximum_raw_response_bytes: int = Field(gt=0, le=_MAX_RESPONSE_BYTES)


class SegmentationExecutionAuthority(BaseModel):
    model_config = _CONFIG

    api_calls_authorized: Literal[True] = True
    prospective_calibration_authorized: Literal[True] = True
    scaled_execution_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_effectiveness_claim_authorized: Literal[False] = False
    human_review_claim_authorized: Literal[False] = False


class TasteSourceSegmentationExecutionAuthorization(BaseModel):
    """Content-addressed owner approval for exactly one calibration run."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    authorization_id: str = Field(pattern=_ID)
    run_id: str = Field(pattern=_ID)
    one_time_nonce: str = Field(pattern=_ID)
    execution_ledger_locator: str = Field(min_length=1, max_length=2_000)
    project_id: str = Field(pattern=_ID)
    authorized_by: str = Field(min_length=1, max_length=200)
    approval_origin: Literal["project-owner-conversation"]
    approval_evidence_sha256: str = Field(pattern=_SHA256)
    authorized_at: datetime
    expires_at: datetime
    protocol: SegmentationExecutionFileBinding
    freeze_receipt: SegmentationExecutionFileBinding
    request_pack: SegmentationExecutionPackBinding
    provider_resource: SegmentationExecutionFileBinding
    identity_protocol: SegmentationExecutionFileBinding
    runner: SegmentationExecutionRunnerBinding
    requested_provider: str = Field(pattern=_ID)
    requested_model: str = Field(min_length=1, max_length=500)
    credential_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    execution_scope: Literal["prospective-segmentation-calibration-only"]
    price_ceiling: SegmentationExecutionPriceCeiling
    limits: SegmentationExecutionLimits
    authority: SegmentationExecutionAuthority
    authorization_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def authorization_is_closed(self) -> TasteSourceSegmentationExecutionAuthorization:
        if (
            self.authorized_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.authorized_at
        ):
            raise ValueError("Segmentation execution authorization window is invalid")
        _safe_locator(self.execution_ledger_locator)
        expected = _canonical_sha256(
            self.model_dump(mode="json", exclude={"authorization_sha256"})
        )
        if self.authorization_sha256 != expected:
            raise ValueError("Segmentation execution authorization hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceSegmentationExecutionAuthorization:
        payload = {"schema_version": "1.0", **values}
        payload.pop("authorization_sha256", None)
        unsigned = cls.model_construct(authorization_sha256="0" * 64, **payload)
        return cls(
            **payload,
            authorization_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"authorization_sha256"})
            ),
        )


class TasteSourceSegmentationExecutionInspection(BaseModel):
    model_config = _CONFIG

    authorization_path: Path
    authorization_file_sha256: str = Field(pattern=_SHA256)
    authorization: TasteSourceSegmentationExecutionAuthorization
    protocol: TasteSourceSegmentationProtocolInspection
    request_pack: TasteSourceSegmentationRequestPack
    identity_protocol: ApiIdentityProtocolInspection
    provider_resource: ApiModelDefinition
    packet_count: int = Field(gt=0)
    unique_item_count: int = Field(gt=0)
    runner_git_binding_verified: Literal[True] = True
    payload_firewall_verified: Literal[True] = True
    authorization_candidate_validated: Literal[True] = True
    execution_ready: Literal[False] = False
    external_action_performed: Literal[False] = False


class SegmentationProviderSegment(BaseModel):
    model_config = _CONFIG

    verbatim_decision_text: str = Field(min_length=8, max_length=16_000)
    primary_decision_family: Literal[
        "idea", "experiment", "evidence", "writing", "review", "visual", "cannot-assess"
    ]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]


class SegmentationProviderItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segments: tuple[SegmentationProviderSegment, ...] = Field(min_length=1, max_length=128)
    residual_decision_bearing_text_possible: bool


class SegmentationProviderOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationProviderItem, ...] = Field(min_length=1)


class SegmentationInputFirewallReceipt(BaseModel):
    """Runner observation about bytes sent; it is not a model attestation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    packet_id: str = Field(pattern=_ID)
    packet_sha256: str = Field(pattern=_SHA256)
    raw_request_ref: str = Field(min_length=1, max_length=1_000)
    raw_request_sha256: str = Field(pattern=_SHA256)
    request_persisted_before_provider_contact: Literal[True] = True
    structured_source_identity_fields_absent: Literal[True] = True
    explicit_outcome_fields_absent: Literal[True] = True
    other_segmenter_output_absent: Literal[True] = True
    provider_tools_absent: Literal[True] = True
    outbound_endpoint_allowlisted: Literal[True] = True
    parametric_source_recognition_ruled_out: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationInputFirewallReceipt:
        _safe_locator(self.raw_request_ref)
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class SegmentationProviderCallReceipt(BaseModel):
    model_config = _CONFIG

    call: ApiIdentityCallReceipt
    packet_id: str | None = Field(default=None, pattern=_ID)
    packet_sha256: str | None = Field(default=None, pattern=_SHA256)
    raw_provider_response_sha256: str = Field(pattern=_SHA256)
    output_object_sha256: str = Field(pattern=_SHA256)
    maximum_estimated_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    retry_count: Literal[0] = 0
    response_schema_verified: Literal[True] = True
    assigned_item_set_verified: Literal[True] = True
    verbatim_spans_verified: Literal[True] = True

    @model_validator(mode="after")
    def role_matches_packet(self) -> SegmentationProviderCallReceipt:
        workload = self.call.role is ApiIdentityCallRole.WORKLOAD
        if workload != (self.packet_id is not None and self.packet_sha256 is not None):
            raise ValueError("Segmentation workload receipt packet binding is inconsistent")
        return self


class ProviderHTTPResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    headers: dict[str, str]
    content: bytes = Field(max_length=_MAX_RESPONSE_BYTES)


class ProviderHTTPTransport(Protocol):
    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout_seconds: float,
        maximum_response_bytes: int,
    ) -> ProviderHTTPResponse: ...


class LiveProviderHTTPTransport:
    """One-attempt byte-preserving HTTP transport."""

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout_seconds: float,
        maximum_response_bytes: int,
    ) -> ProviderHTTPResponse:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers=headers, content=content) as response:
                chunks: list[bytes] = []
                observed = 0
                for chunk in response.iter_bytes():
                    observed += len(chunk)
                    if observed > maximum_response_bytes:
                        raise ValueError("Segmentation provider response exceeds its byte ceiling")
                    chunks.append(chunk)
                return ProviderHTTPResponse(
                    status_code=response.status_code,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    content=b"".join(chunks),
                )


def inspect_taste_source_segmentation_execution_authorization(
    *,
    authorization_path: str | Path,
    locator_root: str | Path,
    now: datetime | None = None,
) -> TasteSourceSegmentationExecutionInspection:
    """Verify exact execution authority without reading credentials or using the network."""

    root = Path(locator_root).resolve(strict=True)
    source = _bounded_file(Path(authorization_path), _MAX_AUTHORIZATION_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Segmentation execution authorization must contain a YAML mapping")
    authorization = TasteSourceSegmentationExecutionAuthorization.model_validate(payload)
    observed_now = now or datetime.now().astimezone()
    if observed_now.utcoffset() is None or not (
        authorization.authorized_at <= observed_now <= authorization.expires_at
    ):
        raise ValueError("Segmentation execution authorization is outside its validity window")

    protocol_path = _bound_path(root, authorization.protocol)
    freeze_path = _bound_path(root, authorization.freeze_receipt)
    protocol = inspect_taste_source_segmentation_protocol(
        protocol_path=protocol_path,
        freeze_receipt_path=freeze_path,
        locator_root=root,
    )
    if (
        protocol.protocol.schema_version != "1.1"
        or protocol.protocol.adjudication_input_firewall is None
    ):
        raise ValueError(
            "Live segmentation execution requires a separately frozen adjudication firewall"
        )
    pack_path = _bound_path(root, authorization.request_pack)
    pack = load_taste_source_segmentation_request_pack(pack_path)
    if pack.pack_sha256 != authorization.request_pack.pack_sha256:
        raise ValueError("Segmentation execution request-pack semantic hash drifted")
    if (
        pack.project_id != authorization.project_id
        or pack.protocol_file_sha256 != protocol.protocol_file_sha256
        or pack.freeze_receipt_file_sha256 != protocol.freeze_receipt_file_sha256
        or pack.sample_sha256 != protocol.sample.sample_sha256
    ):
        raise ValueError("Segmentation execution pack differs from the frozen protocol")

    resource_path = _bound_path(root, authorization.provider_resource)
    resource_payload = yaml.safe_load(resource_path.read_text(encoding="utf-8"))
    if not isinstance(resource_payload, dict):
        raise ValueError("Segmentation provider resource must contain a YAML mapping")
    resource = ApiModelDefinition.model_validate(resource_payload.get("resource"))
    identity_path = _bound_path(root, authorization.identity_protocol)
    identity = load_api_identity_protocol(identity_path)
    condition = protocol.protocol.model_condition
    if (
        authorization.requested_provider != condition.provider_id
        or authorization.requested_model != condition.requested_model_id
        or resource.provider_id != condition.provider_id
        or resource.resource_id != condition.resource_id
        or resource.model_id != condition.requested_model_id
        or resource.credential_env != authorization.credential_env
        or identity.file_sha256 != condition.identity_protocol_file_sha256
        or resource.interface != "openai-chat-completions"
    ):
        raise ValueError("Segmentation execution provider identity drifted")

    runner_path = _bound_path(root, authorization.runner)
    cli_path = _bounded_file(
        root / _safe_locator(authorization.runner.cli_locator),
        _MAX_PACKET_BYTES,
    )
    if _sha256_file(cli_path) != authorization.runner.cli_file_sha256:
        raise ValueError("Segmentation execution CLI binding drifted")
    if (
        _git_blob_sha256(root, authorization.runner.git_commit, authorization.runner.locator)
        != authorization.runner.file_sha256
        or _git_blob_sha256(root, authorization.runner.git_commit, authorization.runner.cli_locator)
        != authorization.runner.cli_file_sha256
        or _sha256_file(runner_path) != authorization.runner.file_sha256
    ):
        raise ValueError("Segmentation execution runner Git binding drifted")

    limits = authorization.limits
    frozen_budget = protocol.protocol.budget
    maximum_priced_cost = (
        limits.maximum_input_tokens
        * authorization.price_ceiling.maximum_input_usd_per_million_tokens
        + limits.maximum_output_tokens
        * authorization.price_ceiling.maximum_output_usd_per_million_tokens
    ) / 1_000_000
    if (
        limits.maximum_provider_requests != frozen_budget.maximum_provider_requests
        or limits.maximum_input_tokens != frozen_budget.maximum_input_tokens
        or limits.maximum_output_tokens != frozen_budget.maximum_output_tokens
        or authorization.price_ceiling.maximum_total_cost_usd
        > frozen_budget.maximum_api_cost_usd
        or limits.retry_count != protocol.protocol.generation.retry_count
        or pack.request_count != protocol.protocol.generation.segmenter_total_requests
        or maximum_priced_cost
        > authorization.price_ceiling.maximum_total_cost_usd
    ):
        raise ValueError("Segmentation execution limits exceed the frozen protocol")
    price_age_seconds = (
        authorization.authorized_at - authorization.price_ceiling.pricing_observed_at
    ).total_seconds()
    if price_age_seconds < 0 or price_age_seconds > 24 * 3_600:
        raise ValueError("Segmentation execution price ceiling is not contemporaneous")

    pack_root = pack_path.parent
    rubric_path = _bounded_file(
        root / _safe_locator(protocol.protocol.segmentation_rubric.locator),
        _MAX_PACKET_BYTES,
    )
    frozen_rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    if not isinstance(frozen_rubric, dict):
        raise ValueError("Segmentation rubric must contain a YAML mapping")
    packets = []
    for binding in pack.requests:
        packet = load_taste_source_segmentation_request_packet(pack_root / binding.locator)
        if (
            packet.protocol_id != protocol.protocol.protocol_id
            or packet.requested_provider != authorization.requested_provider
            or packet.requested_model != authorization.requested_model
            or packet.rubric_file_sha256
            != protocol.protocol.segmentation_rubric.file_sha256
            or packet.rubric != frozen_rubric
            or packet.shard_count != protocol.protocol.generation.segmenter_shards
            or len(packet.items) != protocol.protocol.generation.items_per_shard
            or packet.provider_tools_allowed
            or packet.provider_contact_performed
        ):
            raise ValueError("Segmentation execution packet differs from the frozen plan")
        packets.append(packet)
    expected_pairs = {
        (slot, shard)
        for slot in ("segmenter-a", "segmenter-b")
        for shard in range(1, protocol.protocol.generation.segmenter_shards + 1)
    }
    if {(item.segmenter_slot, item.shard_index) for item in packets} != expected_pairs:
        raise ValueError("Segmentation execution packet coverage drifted")
    return TasteSourceSegmentationExecutionInspection(
        authorization_path=source,
        authorization_file_sha256=_sha256_file(source),
        authorization=authorization,
        protocol=protocol,
        request_pack=pack,
        identity_protocol=identity,
        provider_resource=resource,
        packet_count=len(packets),
        unique_item_count=pack.unique_item_count,
    )


def build_segmentation_provider_request(
    packet: TasteSourceSegmentationRequestPacket,
    *,
    protocol: TasteSourceSegmentationProspectiveProtocol,
) -> dict[str, JsonValue]:
    """Build the exact structured provider payload from one frozen packet."""

    user_payload = {
        "rubric": packet.rubric,
        "items": [item.model_dump(mode="json") for item in packet.items],
        "output_contract": packet.output_contract,
    }
    return {
        "model": packet.requested_model,
        "messages": [
            {"role": "system", "content": packet.system_instruction},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": protocol.generation.thinking},
        "reasoning_effort": protocol.generation.reasoning_effort,
        "temperature": protocol.generation.temperature,
        "max_tokens": protocol.generation.maximum_output_tokens_per_call,
        "stream": False,
    }


def validate_segmentation_provider_output(
    raw_text: str,
    *,
    packet: TasteSourceSegmentationRequestPacket,
) -> SegmentationProviderOutput:
    """Validate exact item coverage and verbatim spans for one provider response."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        raise ValueError("Segmentation provider output must be a bare JSON object")
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Segmentation provider output is not valid JSON") from error
    output = SegmentationProviderOutput.model_validate(payload)
    expected = {(item.campaign_token, item.review_item_id): item for item in packet.items}
    observed = [(item.campaign_token, item.review_item_id) for item in output.items]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ValueError("Segmentation provider output item coverage drifted")
    for item in output.items:
        source = expected[(item.campaign_token, item.review_item_id)].review_comment
        intervals: list[tuple[int, int]] = []
        for segment in item.segments:
            start = source.find(segment.verbatim_decision_text)
            if start < 0 or source.find(segment.verbatim_decision_text, start + 1) >= 0:
                raise ValueError("Segmentation provider span is absent or non-unique")
            intervals.append((start, start + len(segment.verbatim_decision_text)))
        ordered = sorted(intervals)
        if any(first[1] > second[0] for first, second in pairwise(ordered)):
            raise ValueError("Segmentation provider spans overlap")
    return output


def verify_persisted_segmentation_provider_request(
    raw: bytes,
    *,
    packet: TasteSourceSegmentationRequestPacket,
    protocol: TasteSourceSegmentationProspectiveProtocol,
    raw_request_ref: str,
) -> SegmentationInputFirewallReceipt:
    """Reparse exact outbound bytes and issue a runner-owned firewall receipt."""

    expected = build_segmentation_provider_request(packet, protocol=protocol)
    try:
        observed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Persisted segmentation request is not JSON") from error
    if observed != expected:
        raise ValueError("Persisted segmentation request differs from its frozen packet")
    forbidden_keys = {
        "article_title",
        "author_response",
        "later_revision",
        "observed_recommendation",
        "publisher_subject",
        "source_identity",
        "private_item_map",
        "population_outcome",
        "tools",
        "tool_choice",
    }
    if _recursive_keys(observed) & forbidden_keys:
        raise ValueError("Persisted segmentation request violates its input firewall")
    if set(observed) != {
        "max_tokens",
        "messages",
        "model",
        "reasoning_effort",
        "response_format",
        "stream",
        "temperature",
        "thinking",
    }:
        raise ValueError("Persisted segmentation provider root fields drifted")
    return SegmentationInputFirewallReceipt(
        packet_id=packet.packet_id,
        packet_sha256=packet.packet_sha256,
        raw_request_ref=raw_request_ref,
        raw_request_sha256=hashlib.sha256(raw).hexdigest(),
    )


def extract_openai_chat_response(
    response: ProviderHTTPResponse,
) -> tuple[str, str, str, int, int, dict[str, JsonValue]]:
    """Extract the response text and mandatory runtime identity fields."""

    if not 200 <= response.status_code < 300:
        raise ValueError(f"Segmentation provider returned HTTP {response.status_code}")
    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Segmentation provider response is not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Segmentation provider response root must be an object")
    try:
        choice = payload["choices"][0]
        text = choice["message"]["content"]
        finish_reason = choice["finish_reason"]
        returned_model = payload["model"]
        provider_request_id = payload.get("request_id") or payload["id"]
        usage = payload["usage"]
        if not isinstance(usage, dict):
            raise TypeError("usage must be an object")
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Segmentation provider response lacks required receipt fields") from error
    if not isinstance(text, str) or not isinstance(returned_model, str) or not isinstance(
        provider_request_id, str
    ):
        raise ValueError("Segmentation provider identity fields are invalid")
    if finish_reason != "stop":
        raise ValueError("Segmentation provider response did not finish normally")
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise ValueError("Segmentation provider usage fields are invalid")
    return (
        text,
        returned_model,
        provider_request_id,
        input_tokens,
        output_tokens,
        payload,
    )


def persist_exact_provider_request(path: str | Path, payload: dict[str, JsonValue]) -> bytes:
    """Persist canonical request bytes and return the same bytes for transport."""

    raw = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    _atomic_bytes(Path(path), raw)
    return raw


def load_taste_source_segmentation_execution_authorization(
    path: str | Path,
) -> TasteSourceSegmentationExecutionAuthorization:
    source = _bounded_file(Path(path), _MAX_AUTHORIZATION_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Segmentation execution authorization must contain a YAML mapping")
    return TasteSourceSegmentationExecutionAuthorization.model_validate(payload)


def save_taste_source_segmentation_execution_authorization(
    authorization: TasteSourceSegmentationExecutionAuthorization,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                authorization.model_dump(mode="json"),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _bound_path(root: Path, binding: SegmentationExecutionFileBinding) -> Path:
    path = _bounded_file(root / _safe_locator(binding.locator), _MAX_PACKET_BYTES)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("Segmentation execution binding escapes its root") from error
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError("Segmentation execution file binding drifted")
    return path


def _bounded_file(path: Path, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Segmentation execution input must be a regular non-symlink file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("Segmentation execution input exceeds its byte ceiling")
    return path.resolve(strict=True)


def _safe_locator(locator: str) -> PurePosixPath:
    candidate = PurePosixPath(locator)
    if (
        "\\" in locator
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Segmentation execution locator is unsafe")
    return candidate


def _git_blob_sha256(root: Path, commit: str, locator: str) -> str:
    _safe_locator(locator)
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{locator}"],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise ValueError("Segmentation execution Git blob is unavailable")
    return hashlib.sha256(result.stdout).hexdigest()


def _atomic_bytes(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for child in value.values()
            for nested in _recursive_keys(child)
        }
    if isinstance(value, list):
        return {nested for child in value for nested in _recursive_keys(child)}
    return set()


__all__ = [
    "LiveProviderHTTPTransport",
    "ProviderHTTPResponse",
    "ProviderHTTPTransport",
    "SegmentationExecutionAuthority",
    "SegmentationExecutionFileBinding",
    "SegmentationExecutionLimits",
    "SegmentationExecutionPackBinding",
    "SegmentationExecutionPriceCeiling",
    "SegmentationExecutionRunnerBinding",
    "SegmentationInputFirewallReceipt",
    "SegmentationProviderCallReceipt",
    "SegmentationProviderItem",
    "SegmentationProviderOutput",
    "SegmentationProviderSegment",
    "TasteSourceSegmentationExecutionAuthorization",
    "TasteSourceSegmentationExecutionInspection",
    "build_segmentation_provider_request",
    "extract_openai_chat_response",
    "inspect_taste_source_segmentation_execution_authorization",
    "load_taste_source_segmentation_execution_authorization",
    "persist_exact_provider_request",
    "save_taste_source_segmentation_execution_authorization",
    "validate_segmentation_provider_output",
    "verify_persisted_segmentation_provider_request",
]

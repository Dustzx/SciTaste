from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    ApiIdentityCallReceipt,
    ApiIdentityCallRole,
    ApiIdentityMode,
    ApiIdentityProtocol,
    ApiIdentityWindowAttestation,
    ApiIdentityWindowKind,
    inspect_api_identity_window,
    load_api_identity_protocol,
    qualify_api_identity_candidate,
)
from scitaste.resources import load_compute_resource_catalog

_ROOT = Path(__file__).resolve().parents[2]
_PROTOCOL = _ROOT / "configs/evaluation/model_identity/iclr2027_api_identity_v1.yaml"
_CATALOG = _ROOT / "configs/resources/compute_catalog_v4.yaml"
_PROTOCOL_V2 = _ROOT / "configs/evaluation/model_identity/iclr2027_api_identity_v2.yaml"
_CATALOG_V5 = _ROOT / "configs/resources/compute_catalog_v5.yaml"
_SHA = "a" * 64


def _call(
    *,
    sequence: int,
    role: ApiIdentityCallRole,
    started: datetime,
    returned_model: str = "deepseek-v4-flash",
) -> ApiIdentityCallReceipt:
    protocol = load_api_identity_protocol(_PROTOCOL).protocol
    return ApiIdentityCallReceipt(
        sequence=sequence,
        role=role,
        provider_id="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        interface="openai-chat-completions",
        requested_model_id="deepseek-v4-flash",
        returned_model=returned_model,
        provider_request_id=f"request-{sequence}",
        request_started_at_utc=started,
        response_completed_at_utc=started + timedelta(seconds=2),
        request_sha256=f"{sequence:064x}",
        response_sha256=f"{sequence + 10:064x}",
        raw_request_ref=f"calls/{sequence}/request.json",
        raw_response_ref=f"calls/{sequence}/response.json",
        http_status=200,
        input_tokens=8,
        output_tokens=8,
        sentinel_template_sha256=(
            None if role is ApiIdentityCallRole.WORKLOAD else protocol.sentinel_template_sha256
        ),
        task_or_benchmark_content_present=role is ApiIdentityCallRole.WORKLOAD,
    )


def _window(*, returned_model: str = "deepseek-v4-flash") -> ApiIdentityWindowAttestation:
    inspection = load_api_identity_protocol(_PROTOCOL)
    opened = datetime(2026, 9, 12, 5, tzinfo=UTC)
    return ApiIdentityWindowAttestation.create(
        window_id="deepseek-conformance-window-v1",
        project_id="scitaste-self-development",
        protocol_id=inspection.protocol.protocol_id,
        protocol_semantic_sha256=inspection.semantic_sha256,
        resource_id="deepseek-v4-flash",
        kind=ApiIdentityWindowKind.CONFORMANCE,
        opened_at_utc=opened,
        closed_at_utc=opened + timedelta(minutes=10),
        official_catalog_open_sha256=_SHA,
        official_catalog_close_sha256=_SHA,
        official_revision_at_open="DeepSeek-V4-Flash-0731",
        official_revision_at_close="DeepSeek-V4-Flash-0731",
        execution_approval_sha256=_SHA,
        calls=(
            _call(sequence=1, role=ApiIdentityCallRole.START_SENTINEL, started=opened),
            _call(
                sequence=2,
                role=ApiIdentityCallRole.WORKLOAD,
                started=opened + timedelta(minutes=2),
                returned_model=returned_model,
            ),
            _call(
                sequence=3,
                role=ApiIdentityCallRole.END_SENTINEL,
                started=opened + timedelta(minutes=9),
            ),
        ),
    )


def test_temporal_identity_protocol_separates_revision_backed_and_window_only_models() -> None:
    inspection = load_api_identity_protocol(_PROTOCOL)
    protocol = inspection.protocol
    catalog = load_compute_resource_catalog(_CATALOG).catalog

    deepseek = qualify_api_identity_candidate(
        catalog.resource("deepseek-v4-flash"),
        protocol.policy("deepseek-v4-flash"),
    )
    zhipu = qualify_api_identity_candidate(
        catalog.resource("zhipu-glm53-flash"),
        protocol.policy("zhipu-glm53-flash"),
    )

    assert deepseek.identity_mode is ApiIdentityMode.OFFICIAL_REVISION_PLUS_TEMPORAL_WINDOW
    assert deepseek.official_revision == "DeepSeek-V4-Flash-0731"
    assert deepseek.pilot_proposal_ready is True
    assert deepseek.formal_identity_ready is False
    assert zhipu.identity_mode is ApiIdentityMode.TEMPORAL_WINDOW_ONLY
    assert zhipu.official_revision is None
    assert zhipu.pilot_proposal_ready is False
    assert zhipu.formal_identity_ready is False
    assert protocol.cross_window_pooling is False
    assert protocol.cross_revision_pooling is False
    assert protocol.cross_provider_pooling is False
    assert protocol.sentinel.task_or_benchmark_content_allowed is False
    assert inspection.external_action_performed is False


def test_current_protocol_uses_official_deepseek_v41_identity() -> None:
    inspection = load_api_identity_protocol(_PROTOCOL_V2)
    catalog = load_compute_resource_catalog(_CATALOG_V5).catalog
    deepseek = qualify_api_identity_candidate(
        catalog.resource("deepseek-v41-flash"),
        inspection.protocol.policy("deepseek-v41-flash"),
    )

    assert inspection.protocol.protocol_id == "iclr2027-api-identity-v2"
    assert deepseek.identity_mode is ApiIdentityMode.OFFICIAL_REVISION_PLUS_TEMPORAL_WINDOW
    assert deepseek.official_revision == "DeepSeek-V4.1-Flash"
    assert deepseek.pilot_proposal_ready is True
    assert deepseek.formal_identity_ready is False
    assert inspection.protocol.policy("deepseek-v41-flash").allowed_returned_model_ids == (
        "deepseek-flash",
        "DeepSeek-V4.1-Flash",
    )


def test_identity_protocol_rejects_missing_provenance_capture() -> None:
    protocol = load_api_identity_protocol(_PROTOCOL).protocol
    payload = protocol.model_dump(mode="json")
    payload["capture_fields"].remove("returned_model")

    with pytest.raises(ValidationError, match="omits required capture fields"):
        ApiIdentityProtocol.model_validate(payload)


def test_revision_backed_policy_rejects_catalog_drift() -> None:
    protocol = load_api_identity_protocol(_PROTOCOL).protocol
    resource = load_compute_resource_catalog(_CATALOG).catalog.resource("deepseek-v4-flash")
    drifted = resource.model_copy(update={"model_revision": "DeepSeek-V4-Flash-new"})

    with pytest.raises(ValueError, match="revision differs"):
        qualify_api_identity_candidate(drifted, protocol.policy(resource.resource_id))


def test_closed_conformance_window_is_admitted_as_identity_not_effectiveness() -> None:
    inspection = load_api_identity_protocol(_PROTOCOL)
    resource = load_compute_resource_catalog(_CATALOG).catalog.resource("deepseek-v4-flash")

    report = inspect_api_identity_window(
        _window(), protocol_inspection=inspection, resource=resource
    )

    assert report.admitted is True
    assert report.formal_use_eligible is False
    assert report.blocker_codes == ()
    assert report.sentinel_count == 2
    assert report.scientific_effectiveness_established is False
    assert report.cross_window_pooling_allowed is False


def test_unannounced_returned_identity_blocks_the_whole_window() -> None:
    inspection = load_api_identity_protocol(_PROTOCOL)
    resource = load_compute_resource_catalog(_CATALOG).catalog.resource("deepseek-v4-flash")

    report = inspect_api_identity_window(
        _window(returned_model="unannounced-model"),
        protocol_inspection=inspection,
        resource=resource,
    )

    assert report.admitted is False
    assert report.formal_use_eligible is False
    assert report.blocker_codes == ("returned_model_not_allowed",)

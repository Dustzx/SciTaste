from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation.taste_source_segmentation_execution import (
    SegmentationExecutionAuthority,
    SegmentationExecutionFileBinding,
    SegmentationExecutionLimits,
    SegmentationExecutionPackBinding,
    SegmentationExecutionPriceCeiling,
    SegmentationExecutionRunnerBinding,
    TasteSourceSegmentationExecutionAuthorization,
    build_segmentation_provider_request,
    persist_exact_provider_request,
    validate_segmentation_provider_output,
    verify_persisted_segmentation_provider_request,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationProspectiveProtocol,
    inspect_taste_source_segmentation_protocol,
    load_taste_source_segmentation_request_packet,
)

_ROOT = Path(__file__).resolve().parents[2]
_PACK = (
    _ROOT
    / "outputs/projects/scitaste-self-development/evaluations/decision-segmentation-v1"
    / "prospective-v1/request-pack-v3"
)
_SHA = "a" * 64


def _protocol():
    return inspect_taste_source_segmentation_protocol(
        protocol_path=(
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_protocol_v1.yaml"
        ),
        freeze_receipt_path=(
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_freeze_v1.yaml"
        ),
        locator_root=_ROOT,
    ).protocol


def _packet():
    return load_taste_source_segmentation_request_packet(
        _PACK
        / "requests/scitastebench-segmentation-prospective-requests-v3-segmenter-a-shard-01.json"
    )


def _authorization() -> TasteSourceSegmentationExecutionAuthorization:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    return TasteSourceSegmentationExecutionAuthorization.create(
        authorization_id="segmentation-calibration-execution-v1",
        run_id="segmentation-calibration-run-v1",
        one_time_nonce="nonce-20260915-v1",
        execution_ledger_locator="outputs/segmentation-calibration-run-v1/LEDGER.json",
        project_id="scitaste-self-development",
        authorized_by="project-owner",
        approval_origin="project-owner-conversation",
        approval_evidence_sha256=_SHA,
        authorized_at=now,
        expires_at=now + timedelta(hours=12),
        protocol=SegmentationExecutionFileBinding(locator="protocol.yaml", file_sha256=_SHA),
        freeze_receipt=SegmentationExecutionFileBinding(
            locator="freeze.yaml", file_sha256=_SHA
        ),
        request_pack=SegmentationExecutionPackBinding(
            locator="REQUEST_PACK.json", file_sha256=_SHA, pack_sha256=_SHA
        ),
        provider_resource=SegmentationExecutionFileBinding(
            locator="provider.yaml", file_sha256=_SHA
        ),
        identity_protocol=SegmentationExecutionFileBinding(
            locator="identity.yaml", file_sha256=_SHA
        ),
        runner=SegmentationExecutionRunnerBinding(
            locator="src/runner.py",
            file_sha256=_SHA,
            git_commit="b" * 40,
            cli_locator="src/cli.py",
            cli_file_sha256=_SHA,
        ),
        requested_provider="zhipu",
        requested_model="glm-5.3-flash",
        credential_env="ZAI_API_KEY",
        execution_scope="prospective-segmentation-calibration-only",
        price_ceiling=SegmentationExecutionPriceCeiling(
            maximum_input_usd_per_million_tokens=2,
            maximum_output_usd_per_million_tokens=8,
            maximum_total_cost_usd=10,
            basis="owner-approved-conservative-liability-ceiling",
            pricing_source_url="https://example.com/pricing",
            pricing_observed_at=now,
        ),
        limits=SegmentationExecutionLimits(
            maximum_provider_requests=14,
            maximum_input_tokens=300_000,
            maximum_output_tokens=120_000,
            timeout_seconds_per_request=180,
            maximum_raw_response_bytes=8 * 1_048_576,
        ),
        authority=SegmentationExecutionAuthority(),
    )


def test_authorization_is_self_hashed_and_cannot_overclaim() -> None:
    authorization = _authorization()
    payload = authorization.model_dump(mode="json")

    assert len(authorization.authorization_sha256) == 64
    assert authorization.authority.prospective_calibration_authorized is True
    assert authorization.authority.scaled_execution_authorized is False
    assert authorization.authority.human_review_claim_authorized is False

    payload["requested_model"] = "another-model"
    with pytest.raises(ValidationError, match="authorization hash mismatch"):
        TasteSourceSegmentationExecutionAuthorization.model_validate(payload)


def test_live_protocol_requires_a_distinct_disputed_only_adjudication_firewall() -> None:
    payload = _protocol().model_dump(mode="json", exclude_none=True, by_alias=True)
    payload["schema_version"] = "1.1"
    with pytest.raises(ValidationError, match="requires a separate adjudication firewall"):
        TasteSourceSegmentationProspectiveProtocol.model_validate(payload)

    payload["adjudication_input_firewall"] = {
        "allowed": [
            "frozen adjudication rubric",
            "assigned disputed item abstract and review comment",
            "typed agreement blockers",
            "two anonymous segmenter candidates in hash-randomized order",
            "opaque campaign and review item identifiers",
        ],
        "forbidden": [
            "private item map",
            "publisher or source identity",
            "recommendation",
            "author response",
            "later revision",
            "population outcome",
            "non-disputed items",
            "segmenter slot identities",
            "arbitrary tools",
            "web search",
        ],
        "disputed_items_only": True,
        "exact_agreement_items_copied_deterministically": True,
        "candidate_order_anonymized_and_hash_randomized": True,
        "no_provider_tools_exposed": True,
        "explicit_source_identity_withheld": True,
        "explicit_outcome_fields_withheld": True,
        "parametric_source_recognition_ruled_out": False,
        "boundary_statement": "Only disputed items and anonymous candidates reach AI C.",
    }
    upgraded = TasteSourceSegmentationProspectiveProtocol.model_validate(payload)
    assert upgraded.adjudication_input_firewall is not None
    assert upgraded.adjudication_input_firewall.disputed_items_only is True


def test_exact_request_bytes_are_persisted_before_transport(tmp_path: Path) -> None:
    packet = _packet()
    payload = build_segmentation_provider_request(
        packet,
        protocol=_protocol(),
    )
    target = tmp_path / "request.json"
    raw = persist_exact_provider_request(target, payload)

    assert target.read_bytes() == raw
    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(target.read_bytes()).hexdigest()
    provider_text = raw.decode()
    for forbidden in (
        "article_title",
        "author_response",
        "later_revision",
        "observed_recommendation",
        "publisher_subject",
        "source_identity",
        '"tools"',
    ):
        assert forbidden not in provider_text
    assert packet.project_id not in provider_text
    assert packet.protocol_id not in provider_text
    receipt = verify_persisted_segmentation_provider_request(
        raw,
        packet=packet,
        protocol=_protocol(),
        raw_request_ref="calls/segmenter-a-01/request.json",
    )
    assert receipt.request_persisted_before_provider_contact is True
    assert receipt.provider_tools_absent is True
    assert receipt.not_human_review is True


def test_provider_output_requires_exact_item_set_and_unique_verbatim_spans() -> None:
    packet = _packet()
    items = [
        {
            "campaign_token": item.campaign_token,
            "review_item_id": item.review_item_id,
            "segments": [
                {
                    "verbatim_decision_text": item.review_comment,
                    "primary_decision_family": "experiment",
                    "atomic_decision_statement": "Test the requested experimental decision.",
                    "rationale": "The exact comment requests an experimental change.",
                    "uncertainty": "low",
                }
            ],
            "residual_decision_bearing_text_possible": False,
        }
        for item in packet.items
    ]
    raw = json.dumps({"items": items}, ensure_ascii=False)

    output = validate_segmentation_provider_output(raw, packet=packet)
    assert len(output.items) == len(packet.items)

    with pytest.raises(ValueError, match="coverage drifted"):
        validate_segmentation_provider_output(
            json.dumps({"items": items[:-1]}, ensure_ascii=False),
            packet=packet,
        )
    items[0]["segments"][0]["verbatim_decision_text"] = "not present in the source"
    with pytest.raises(ValueError, match="absent or non-unique"):
        validate_segmentation_provider_output(
            json.dumps({"items": items}, ensure_ascii=False),
            packet=packet,
        )

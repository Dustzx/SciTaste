from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.taste_source_segmentation_execution import (
    SegmentationExecutionAuthority,
    SegmentationExecutionFileBinding,
    SegmentationExecutionLimits,
    SegmentationExecutionPackBinding,
    SegmentationExecutionPriceCeiling,
    SegmentationExecutionRunnerBinding,
    TasteSourceSegmentationExecutionAuthorization,
    build_segmentation_adjudication_request,
    build_segmentation_provider_request,
    persist_exact_provider_request,
    validate_adjudication_provider_output,
    validate_segmentation_provider_output,
    verify_persisted_segmentation_provider_request,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationProspectiveProtocol,
    TasteSourceSegmentationRequestItem,
    TasteSourceSegmentationRequestPacket,
    inspect_taste_source_segmentation_protocol,
    load_taste_source_segmentation_request_packet,
    taste_source_comment_unit_offsets,
    taste_source_evidence_unit_table_sha256,
    unitize_taste_source_comment,
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


def _v3_protocol():
    payload = yaml.safe_load(
        (
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_protocol_v3.yaml"
        ).read_text(encoding="utf-8")
    )
    return TasteSourceSegmentationProspectiveProtocol.model_validate(payload)


def _v4_protocol():
    payload = yaml.safe_load(
        (
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_protocol_v3.yaml"
        ).read_text(encoding="utf-8")
    )
    payload["schema_version"] = "1.3"
    payload.pop("span_reconstruction")
    payload["evidence_unit_selection"] = {
        "unitizer_algorithm": "unicode-word-punctuation-v1",
        "token_pattern": r"\w+|[^\w\s]",
        "unit_id_format": "u%04d",
        "unit_text_source": "original-review-comment",
        "source_offsets_exposed_to_provider": False,
        "model_returns_source_text": False,
        "reconstructed_text_source": "original-review-comment-slice",
        "unique_text_match_required": False,
        "normalization_allowed": False,
        "fuzzy_matching_allowed": False,
        "insertion_or_deletion_repair_allowed": False,
        "overlapping_ranges_allowed": False,
    }
    payload["input_firewall"]["allowed"].append(
        "deterministic source evidence-unit table"
    )
    payload["adjudication_input_firewall"]["allowed"].append(
        "deterministic source evidence-unit table"
    )
    return TasteSourceSegmentationProspectiveProtocol.model_validate(payload)


def _anchored_packet() -> TasteSourceSegmentationRequestPacket:
    source = "Compare A-B with A-B. Also preserve *quoted* spacing around (x, y)."
    return TasteSourceSegmentationRequestPacket(
        schema_version="1.1",
        packet_id="anchored-packet-v1",
        project_id="scitaste-self-development",
        protocol_id="anchored-protocol-v1",
        sample_sha256=_SHA,
        sample_manifest_file_sha256=_SHA,
        rubric_file_sha256=_SHA,
        segmenter_slot="segmenter-a",
        shard_index=1,
        shard_count=1,
        requested_provider="zhipu",
        requested_model="glm-5.3-flash",
        system_instruction="Select only evidence unit identifiers.",
        rubric={"rubric_id": "anchored-v1"},
        items=(
            TasteSourceSegmentationRequestItem(
                campaign_token="campaign-opaque",
                review_item_id="item-opaque",
                reviewed_abstract="A test abstract.",
                review_comment=source,
                evidence_units=unitize_taste_source_comment(source),
                evidence_unit_table_sha256=taste_source_evidence_unit_table_sha256(source),
            ),
        ),
        output_contract={"type": "object"},
    )


def _authorization() -> TasteSourceSegmentationExecutionAuthorization:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    return TasteSourceSegmentationExecutionAuthorization.create(
        authorization_id="segmentation-calibration-execution-v1",
        run_id="segmentation-calibration-run-v1",
        one_time_nonce="nonce-20260915-v1",
        execution_ledger_locator="outputs/segmentation-calibration-run-v1/LEDGER.json",
        run_output_locator="outputs/segmentation-calibration-run-v1/run",
        project_id="scitaste-self-development",
        authorized_by="project-owner",
        approval_origin="project-owner-conversation",
        approval_evidence_sha256=_SHA,
        authorized_at=now,
        expires_at=now + timedelta(hours=12),
        protocol=SegmentationExecutionFileBinding(locator="protocol.yaml", file_sha256=_SHA),
        freeze_receipt=SegmentationExecutionFileBinding(locator="freeze.yaml", file_sha256=_SHA),
        request_pack=SegmentationExecutionPackBinding(
            locator="REQUEST_PACK.json", file_sha256=_SHA, pack_sha256=_SHA
        ),
        provider_resource=SegmentationExecutionFileBinding(
            locator="provider.yaml", file_sha256=_SHA
        ),
        official_catalog_snapshot=SegmentationExecutionFileBinding(
            locator="catalog.md", file_sha256=_SHA
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
            input_cache_miss_cny_per_million_tokens=0.8,
            input_cache_hit_cny_per_million_tokens=0.23,
            output_cny_per_million_tokens=2.8,
            maximum_estimated_cost_cny=0.576,
            owner_maximum_liability_usd=10,
            basis="official-point-in-time-price-plus-owner-liability-ceiling",
            pricing_source_url="https://example.com/pricing",
            pricing_observed_at=now,
            pricing_snapshot=SegmentationExecutionFileBinding(
                locator="pricing.md", file_sha256=_SHA
            ),
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

    payload["input_firewall"]["allowed"][0] = "frozen segmentation rubric"
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
        '"evidence_units"',
        '"evidence_unit_table_sha256"',
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


def test_v3_reconstructs_only_unique_equal_length_typography_changes() -> None:
    packet = _packet()
    target = next(item for item in packet.items if "“" in item.review_comment)
    source_span = target.review_comment[
        target.review_comment.index("“") : target.review_comment.index("”") + 1
    ]
    reported_span = source_span.translate({0x201C: 0x22, 0x201D: 0x22})
    items = []
    for item in packet.items:
        span = reported_span if item == target else item.review_comment
        items.append(
            {
                "campaign_token": item.campaign_token,
                "review_item_id": item.review_item_id,
                "segments": [
                    {
                        "reported_decision_text": span,
                        "primary_decision_family": "experiment",
                        "atomic_decision_statement": "Test the requested decision.",
                        "rationale": "Use the source-bound locator candidate.",
                        "uncertainty": "low",
                    }
                ],
                "residual_decision_bearing_text_possible": False,
            }
        )
    raw = json.dumps({"items": items}, ensure_ascii=False)
    output = validate_segmentation_provider_output(
        raw,
        packet=packet,
        protocol=_v3_protocol(),
    )
    restored = next(item for item in output.items if item.review_item_id == target.review_item_id)
    assert restored.segments[0].verbatim_decision_text == source_span

    items_forbidden = json.loads(raw)["items"]
    changed = next(
        item for item in items_forbidden if item["review_item_id"] == target.review_item_id
    )
    changed["segments"][0]["reported_decision_text"] = reported_span.replace(" ", "-", 1)
    with pytest.raises(ValueError, match="normalized span is absent"):
        validate_segmentation_provider_output(
            json.dumps({"items": items_forbidden}, ensure_ascii=False),
            packet=packet,
            protocol=_v3_protocol(),
        )


def test_v4_selects_source_units_without_copying_or_searching_text() -> None:
    packet = _anchored_packet()
    source = packet.items[0].review_comment
    rows = taste_source_comment_unit_offsets(source)
    second_a_start = [row[0] for row in rows if row[1] == "A"][1]
    second_b_end = [row[0] for row in rows if row[1] == "B"][1]
    quoted_start = next(row[0] for row in rows if row[1] == "*" and row[2] > 20)
    quoted_end = [row[0] for row in rows if row[1] == "*" and row[2] > 20][1]
    raw = json.dumps(
        {
            "items": [
                {
                    "campaign_token": "campaign-opaque",
                    "review_item_id": "item-opaque",
                    "segments": [
                        {
                            "start_unit_id": second_a_start,
                            "end_unit_id": second_b_end,
                            "primary_decision_family": "experiment",
                            "atomic_decision_statement": "Compare against the second condition.",
                            "rationale": "The selected surface units identify the comparison.",
                            "uncertainty": "low",
                        },
                        {
                            "start_unit_id": quoted_start,
                            "end_unit_id": quoted_end,
                            "primary_decision_family": "writing",
                            "atomic_decision_statement": "Preserve the emphasized term.",
                            "rationale": "The Markdown markers belong to the source evidence.",
                            "uncertainty": "low",
                        },
                    ],
                    "residual_decision_bearing_text_possible": False,
                }
            ]
        }
    )

    output = validate_segmentation_provider_output(
        raw,
        packet=packet,
        protocol=_v4_protocol(),
    )
    assert [segment.verbatim_decision_text for segment in output.items[0].segments] == [
        "A-B",
        "*quoted*",
    ]
    assert output.items[0].segments[0].start_char == source.rfind("A-B")
    request = build_segmentation_provider_request(packet, protocol=_v4_protocol())
    user_payload = json.loads(request["messages"][1]["content"])
    assert "start_char" not in request["messages"][1]["content"]
    assert "end_char" not in request["messages"][1]["content"]
    assert user_payload["items"][0]["evidence_units"][0] == {
        "unit_id": "u0001",
        "surface": "Compare",
    }


def test_v4_rejects_unknown_reversed_and_overlapping_unit_ranges() -> None:
    packet = _anchored_packet()
    base_segment = {
        "start_unit_id": "u0001",
        "end_unit_id": "u0003",
        "primary_decision_family": "experiment",
        "atomic_decision_statement": "Test one decision.",
        "rationale": "The units express one request.",
        "uncertainty": "low",
    }

    def payload(segments: list[dict[str, object]]) -> str:
        return json.dumps(
            {
                "items": [
                    {
                        "campaign_token": "campaign-opaque",
                        "review_item_id": "item-opaque",
                        "segments": segments,
                        "residual_decision_bearing_text_possible": False,
                    }
                ]
            }
        )

    unknown = {**base_segment, "start_unit_id": "u9999"}
    with pytest.raises(ValueError, match="unknown evidence-unit"):
        validate_segmentation_provider_output(
            payload([unknown]), packet=packet, protocol=_v4_protocol()
        )
    reversed_range = {**base_segment, "start_unit_id": "u0003", "end_unit_id": "u0001"}
    with pytest.raises(ValueError, match="range is reversed"):
        validate_segmentation_provider_output(
            payload([reversed_range]), packet=packet, protocol=_v4_protocol()
        )
    overlap = {**base_segment, "start_unit_id": "u0002", "end_unit_id": "u0004"}
    with pytest.raises(ValueError, match="ranges overlap"):
        validate_segmentation_provider_output(
            payload([base_segment, overlap]), packet=packet, protocol=_v4_protocol()
        )
    later = {**base_segment, "start_unit_id": "u0005", "end_unit_id": "u0007"}
    with pytest.raises(ValueError, match="out of order"):
        validate_segmentation_provider_output(
            payload([later, base_segment]), packet=packet, protocol=_v4_protocol()
        )


def test_v4_requires_anchor_scope_on_both_provider_firewalls() -> None:
    payload = yaml.safe_load(
        (
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_protocol_v4.yaml"
        ).read_text(encoding="utf-8")
    )
    payload["adjudication_input_firewall"]["allowed"].remove(
        "deterministic source evidence-unit table"
    )
    with pytest.raises(ValidationError, match="evidence-unit scope differs"):
        TasteSourceSegmentationProspectiveProtocol.model_validate(payload)


def test_v4_adjudicator_can_reselect_units_without_returning_source_text() -> None:
    packet = _anchored_packet()
    item = packet.items[0]
    visible = {
        "campaign_token": item.campaign_token,
        "review_item_id": item.review_item_id,
        "reviewed_abstract": item.reviewed_abstract,
        "review_comment": item.review_comment,
        "evidence_units": [unit.model_dump(mode="json") for unit in item.evidence_units or ()],
        "source_blocker_codes": ["span-boundary-disagreement"],
        "candidates": {
            "candidate-left": {"segments": [], "residual_decision_bearing_text_possible": True},
            "candidate-right": {"segments": [], "residual_decision_bearing_text_possible": True},
        },
    }
    request = build_segmentation_adjudication_request(
        protocol=_v4_protocol(),
        rubric={"rubric_id": "anchored-adjudication-v1"},
        items=[visible],
    )
    contract = json.loads(request["messages"][1]["content"])["output_contract"]
    segment_contract = contract["properties"]["items"]["items"]["properties"][
        "segments"
    ]["items"]
    assert "start_unit_id" in segment_contract["required"]
    assert "verbatim_decision_text" not in segment_contract["properties"]

    raw = json.dumps(
        {
            "items": [
                {
                    "campaign_token": item.campaign_token,
                    "review_item_id": item.review_item_id,
                    "segments": [
                        {
                            "start_unit_id": "u0001",
                            "end_unit_id": "u0005",
                            "primary_decision_family": "experiment",
                            "atomic_decision_statement": "Compare both conditions.",
                            "rationale": "The adjudicator selected a corrected anchor range.",
                            "uncertainty": "low",
                        }
                    ],
                    "residual_decision_bearing_text_possible": False,
                    "resolution_rationale": "This range contains the complete comparison.",
                }
            ]
        }
    )
    resolved = validate_adjudication_provider_output(
        raw,
        expected_items={(item.campaign_token, item.review_item_id): item.review_comment},
        protocol=_v4_protocol(),
    )
    assert resolved.items[0].segments[0].verbatim_decision_text == "Compare A-B with"


def test_anchored_firewall_checks_keys_inside_serialized_user_content(
    tmp_path: Path,
) -> None:
    packet = _anchored_packet().model_copy(
        update={"output_contract": {"type": "object", "start_char": 0}}
    )
    request = build_segmentation_provider_request(packet, protocol=_v4_protocol())
    raw = persist_exact_provider_request(tmp_path / "anchored-request.json", request)
    with pytest.raises(ValueError, match="violates its input firewall"):
        verify_persisted_segmentation_provider_request(
            raw,
            packet=packet,
            protocol=_v4_protocol(),
            raw_request_ref="calls/anchored-request.json",
        )

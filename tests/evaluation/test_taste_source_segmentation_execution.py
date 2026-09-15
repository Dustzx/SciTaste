from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.model_identity import ApiIdentityCallReceipt, ApiIdentityCallRole
from scitaste.evaluation.taste_source_segmentation import (
    TasteSourceSegmentationAgreementItem,
    _normalize_raw_segments,
    load_taste_source_segmentation_sample_manifest,
)
from scitaste.evaluation.taste_source_segmentation_execution import (
    SegmentationExecutionAuthority,
    SegmentationExecutionFileBinding,
    SegmentationExecutionLimits,
    SegmentationExecutionPackBinding,
    SegmentationExecutionPriceCeiling,
    SegmentationExecutionRunnerBinding,
    SegmentationProviderCallReceipt,
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
    assess_taste_source_segmentation_validation_reserve,
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
    local_campaigns = (
        _ROOT
        / "outputs/projects/scitaste-self-development/evaluations/acquisitions"
        / "aries-review-edit-population-v1/derived/taste-source-review-v1/CAMPAIGN.json",
        _ROOT
        / "outputs/projects/scitaste-self-development/evaluations/reviews"
        / "f1000-multidomain-taste-source-review-v1/CAMPAIGN.json",
    )
    if any(not path.exists() for path in local_campaigns):
        pytest.skip("local generated segmentation campaign fixtures are unavailable")
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
    packet_path = (
        _PACK
        / "requests/scitastebench-segmentation-prospective-requests-v3-segmenter-a-shard-01.json"
    )
    if not packet_path.exists():
        pytest.skip("local generated segmentation request fixture is unavailable")
    return load_taste_source_segmentation_request_packet(packet_path)


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
    payload["input_firewall"]["allowed"].append("deterministic source evidence-unit table")
    payload["adjudication_input_firewall"]["allowed"].append(
        "deterministic source evidence-unit table"
    )
    return TasteSourceSegmentationProspectiveProtocol.model_validate(payload)


def _v15_protocol():
    payload = _v4_protocol().model_dump(mode="json", exclude_none=True, by_alias=True)
    payload["schema_version"] = "1.5"
    payload["sample"].update(
        {
            "prior_source_groups_excluded": 20,
            "source_group_disjoint": True,
            "maximum_items_per_source_group": 1,
            "per_campaign_eligible_source_group_counts": {
                "aries-taste-source-review-v1": 12,
                "f1000-multidomain-taste-source-review-v1": 12,
            },
            "per_campaign_sampling_fraction_micros": {
                "aries-taste-source-review-v1": 1_000_000,
                "f1000-multidomain-taste-source-review-v1": 1_000_000,
            },
            "uncertainty_estimand": ("descriptive-calibration-superpopulation-work-model"),
        }
    )
    payload["evidence_unit_selection"].update(
        {
            "system_instruction_sha256": _SHA,
            "output_contract_sha256": _SHA,
            "range_contract": "trigger-plus-shared-context-v1",
            "zero_decision_allowed": True,
            "maximum_context_ranges_per_decision": 8,
            "trigger_ranges_overlapping_allowed": False,
            "context_ranges_may_overlap_across_decisions": True,
            "context_may_overlap_another_decision_trigger": True,
        }
    )
    payload["integrity_gate"] = {"locator": "integrity.yaml", "file_sha256": _SHA}
    payload["authority_gate"] = {"locator": "authority.yaml", "file_sha256": _SHA}
    payload["model_condition"].update(
        {
            "identity_claim_scope": ("provider-reported-rolling-alias-envelope-continuity-only"),
            "backend_revision_identified": False,
        }
    )
    payload["metrics"].update(
        {
            "decision_presence_agreement": {
                "role": "reported-primary-diagnostic",
                "pass_threshold": 0.8,
            },
            "exact_trigger_context_set_agreement": {
                "role": "reported-diagnostic",
                "threshold": None,
            },
            "source_group_uncertainty": {
                "unit": "source_group_id",
                "estimator": "campaign-stratified-source-group-bootstrap-v1",
                "estimand": "descriptive-calibration-superpopulation-work-model",
                "scale_gate_role": "diagnostic-only",
                "campaign_weighting": "equal-by-design",
                "confidence_level": 0.95,
                "replicates": 10000,
                "random_seed": 2026091506,
            },
        }
    )
    payload["scale_gate"].update(
        {
            "calibration_only_no_direct_scale": True,
            "independent_source_group_validation_required": True,
            "new_source_groups_required_for_validation": True,
        }
    )
    return TasteSourceSegmentationProspectiveProtocol.model_validate(payload)


def test_v6_sample_cannot_consume_its_independent_validation_groups():
    protocol_payload = yaml.safe_load(
        (
            _ROOT
            / "configs/evaluation/ai_review/scitastebench_segmentation_prospective_protocol_v6.yaml"
        ).read_text(encoding="utf-8")
    )
    protocol = TasteSourceSegmentationProspectiveProtocol.model_validate(protocol_payload)
    sample = load_taste_source_segmentation_sample_manifest(_ROOT / protocol.sample.locator).sample

    audit = assess_taste_source_segmentation_validation_reserve(protocol, sample)

    assert audit.ready_for_provider_contact is False
    assert audit.selected_source_group_counts == {
        "aries-taste-source-review-v1": 10,
        "f1000-multidomain-taste-source-review-v1": 10,
    }
    assert audit.remaining_source_group_counts == {
        "aries-taste-source-review-v1": 3,
        "f1000-multidomain-taste-source-review-v1": 0,
    }
    assert len(audit.blocker_codes) == 2


def _anchored_packet(
    schema_version: Literal["1.1", "1.2"] = "1.1",
) -> TasteSourceSegmentationRequestPacket:
    source = "Compare A-B with A-B. Also preserve *quoted* spacing around (x, y)."
    return TasteSourceSegmentationRequestPacket(
        schema_version=schema_version,
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
        approval_evidence=SegmentationExecutionFileBinding(
            locator="owner-approval.yaml", file_sha256=_SHA
        ),
        authorized_at=now,
        expires_at=now + timedelta(hours=12),
        protocol=SegmentationExecutionFileBinding(locator="protocol.yaml", file_sha256=_SHA),
        freeze_receipt=SegmentationExecutionFileBinding(locator="freeze.yaml", file_sha256=_SHA),
        request_pack=SegmentationExecutionPackBinding(
            locator="REQUEST_PACK.json", file_sha256=_SHA, pack_sha256=_SHA
        ),
        routing_amendment=SegmentationExecutionFileBinding(
            locator="routing-amendment.yaml", file_sha256=_SHA
        ),
        precontact_audit_seal=SegmentationExecutionFileBinding(
            locator="precontact-seal.yaml", file_sha256=_SHA
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
            runtime_modules=tuple(
                SegmentationExecutionFileBinding(locator=locator, file_sha256=_SHA)
                for locator in (
                    "src/scitaste/evaluation/taste_source_segmentation.py",
                    "src/scitaste/evaluation/taste_source_segmentation_protocol.py",
                    "src/scitaste/evaluation/taste_source_segmentation_post_audit.py",
                    "src/scitaste/evaluation/model_identity.py",
                    "src/scitaste/project/models.py",
                    "src/scitaste/resources/__init__.py",
                    "src/scitaste/resources/registry.py",
                )
            ),
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

    incomplete = authorization.model_dump(mode="json")
    incomplete["runner"]["runtime_modules"][-1] = incomplete["runner"]["runtime_modules"][0]
    with pytest.raises(ValidationError, match="runtime-module manifest is incomplete"):
        TasteSourceSegmentationExecutionAuthorization.model_validate(incomplete)

    wrong_approval = authorization.model_dump(mode="json")
    wrong_approval["approval_evidence"]["file_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="owner-approval evidence hash differs"):
        TasteSourceSegmentationExecutionAuthorization.model_validate(wrong_approval)


def test_decision_boundary_routing_does_not_adjudicate_free_text_differences() -> None:
    item = TasteSourceSegmentationAgreementItem(
        campaign_id="campaign-v1",
        review_item_id="review-v1",
        review_item_sha256=_SHA,
        routing_contract="decision-boundary-only-v2",
        segmenter_a_count=1,
        segmenter_b_count=1,
        exact_span_agreement_count=1,
        exact_span_family_agreement_count=1,
        overlap_span_agreement_count=1,
        overlap_span_family_agreement_count=1,
        family_disagreement_segment_ids=(),
        context_disagreement_segment_ids=(),
        semantic_disagreement_segment_ids=("segment-v1",),
        no_decision_rationale_disagreement=True,
        segmenter_a_unmatched_segment_ids=(),
        segmenter_b_unmatched_segment_ids=(),
        residual_decision_bearing_text_possible=False,
        blocker_codes=(),
        requires_adjudication=False,
        exact_span_route_passed=True,
    )

    assert item.semantic_disagreement_segment_ids == ("segment-v1",)
    assert item.no_decision_rationale_disagreement is True
    assert item.blocker_codes == ()
    assert item.requires_adjudication is False


def test_legacy_routing_still_adjudicates_free_text_differences() -> None:
    with pytest.raises(ValidationError, match="routing blockers"):
        TasteSourceSegmentationAgreementItem(
            campaign_id="campaign-v1",
            review_item_id="review-v1",
            review_item_sha256=_SHA,
            segmenter_a_count=1,
            segmenter_b_count=1,
            exact_span_agreement_count=1,
            exact_span_family_agreement_count=1,
            overlap_span_agreement_count=1,
            overlap_span_family_agreement_count=1,
            family_disagreement_segment_ids=(),
            semantic_disagreement_segment_ids=("segment-v1",),
            segmenter_a_unmatched_segment_ids=(),
            segmenter_b_unmatched_segment_ids=(),
            residual_decision_bearing_text_possible=False,
            blocker_codes=(),
            requires_adjudication=False,
            exact_span_route_passed=True,
        )


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


def test_v15_accepts_zero_decisions_only_with_a_rationale() -> None:
    packet = _anchored_packet("1.2")
    item = {
        "campaign_token": "campaign-opaque",
        "review_item_id": "item-opaque",
        "segments": [],
        "no_decision_rationale": "The comment contains no actionable requested change.",
        "residual_decision_bearing_text_possible": False,
    }
    output = validate_segmentation_provider_output(
        json.dumps({"items": [item]}),
        packet=packet,
        protocol=_v15_protocol(),
    )
    assert output.items[0].segments == ()
    assert output.items[0].no_decision_rationale == item["no_decision_rationale"]

    item.pop("no_decision_rationale")
    with pytest.raises(ValidationError, match="no_decision_rationale"):
        validate_segmentation_provider_output(
            json.dumps({"items": [item]}),
            packet=packet,
            protocol=_v15_protocol(),
        )


def test_v15_preserves_shared_context_separately_from_ordered_triggers() -> None:
    packet = _anchored_packet("1.2")
    rows = taste_source_comment_unit_offsets(packet.items[0].review_comment)
    unit_by_surface = {}
    for unit_id, surface, _, _ in rows:
        unit_by_surface.setdefault(surface, []).append(unit_id)
    shared_context = {
        "start_unit_id": unit_by_surface["A"][0],
        "end_unit_id": unit_by_surface["B"][0],
    }
    segments = [
        {
            "trigger_range": {
                "start_unit_id": unit_by_surface["Compare"][0],
                "end_unit_id": unit_by_surface["Compare"][0],
            },
            "context_ranges": [shared_context],
            "primary_decision_family": "experiment",
            "atomic_decision_statement": "Compare the stated conditions.",
            "rationale": "The trigger requests a comparison.",
            "uncertainty": "low",
        },
        {
            "trigger_range": {
                "start_unit_id": unit_by_surface["preserve"][0],
                "end_unit_id": unit_by_surface["preserve"][0],
            },
            "context_ranges": [shared_context],
            "primary_decision_family": "writing",
            "atomic_decision_statement": "Preserve the marked wording.",
            "rationale": "The trigger requests preservation.",
            "uncertainty": "low",
        },
    ]
    raw = json.dumps(
        {
            "items": [
                {
                    "campaign_token": "campaign-opaque",
                    "review_item_id": "item-opaque",
                    "segments": segments,
                    "no_decision_rationale": None,
                    "residual_decision_bearing_text_possible": False,
                }
            ]
        }
    )
    output = validate_segmentation_provider_output(
        raw,
        packet=packet,
        protocol=_v15_protocol(),
    )
    assert [segment.verbatim_decision_text for segment in output.items[0].segments] == [
        "Compare",
        "preserve",
    ]
    assert [
        segment.context_ranges[0].verbatim_context_text for segment in output.items[0].segments
    ] == ["A-B", "A-B"]

    segments[0]["context_ranges"] = [segments[0]["trigger_range"]]
    overlapping_payload = json.loads(raw)
    overlapping_payload["items"][0]["segments"] = segments
    with pytest.raises(ValueError, match="context overlaps its decision trigger"):
        validate_segmentation_provider_output(
            json.dumps(overlapping_payload),
            packet=packet,
            protocol=_v15_protocol(),
        )


def test_v15_rejects_legacy_packet_and_adjacent_context_units() -> None:
    legacy_packet = _anchored_packet()
    empty_item = {
        "campaign_token": "campaign-opaque",
        "review_item_id": "item-opaque",
        "segments": [],
        "no_decision_rationale": "No actionable requested change is present.",
        "residual_decision_bearing_text_possible": False,
    }
    with pytest.raises(ValueError, match="protocol and request-packet schemas differ"):
        validate_segmentation_provider_output(
            json.dumps({"items": [empty_item]}),
            packet=legacy_packet,
            protocol=_v15_protocol(),
        )

    packet = _anchored_packet("1.2")
    rows = taste_source_comment_unit_offsets(packet.items[0].review_comment)
    adjacent_context = [
        {"start_unit_id": rows[1][0], "end_unit_id": rows[1][0]},
        {"start_unit_id": rows[2][0], "end_unit_id": rows[2][0]},
    ]
    payload = {
        "items": [
            {
                "campaign_token": "campaign-opaque",
                "review_item_id": "item-opaque",
                "segments": [
                    {
                        "trigger_range": {
                            "start_unit_id": rows[-2][0],
                            "end_unit_id": rows[-2][0],
                        },
                        "context_ranges": adjacent_context,
                        "primary_decision_family": "experiment",
                        "atomic_decision_statement": "Compare the stated conditions.",
                        "rationale": "The trigger requests a comparison.",
                        "uncertainty": "low",
                    }
                ],
                "no_decision_rationale": None,
                "residual_decision_bearing_text_possible": False,
            }
        ]
    }
    with pytest.raises(ValueError, match="evidence-unit ranges overlap or are adjacent"):
        validate_segmentation_provider_output(
            json.dumps(payload),
            packet=packet,
            protocol=_v15_protocol(),
        )


def test_v15_call_receipt_requires_anchored_item_receipts_and_clean_sentinel() -> None:
    timestamp = datetime(2026, 9, 15, tzinfo=UTC)

    def identity_call(role: ApiIdentityCallRole) -> ApiIdentityCallReceipt:
        workload = role is ApiIdentityCallRole.WORKLOAD
        return ApiIdentityCallReceipt(
            sequence=1,
            role=role,
            provider_id="zhipu",
            endpoint="https://example.invalid/chat",
            interface="openai-chat-completions",
            requested_model_id="glm-5.3-flash",
            returned_model="glm-5.3-flash",
            provider_request_id="provider-task-1",
            request_started_at_utc=timestamp,
            response_completed_at_utc=timestamp,
            request_sha256=_SHA,
            response_sha256=_SHA,
            raw_request_ref="calls/request.json",
            raw_response_ref="calls/response.json",
            http_status=200,
            input_tokens=1,
            output_tokens=1,
            sentinel_template_sha256=None if workload else _SHA,
            task_or_benchmark_content_present=workload,
        )

    with pytest.raises(ValueError, match="item receipts are incomplete"):
        SegmentationProviderCallReceipt(
            schema_version="1.1",
            call=identity_call(ApiIdentityCallRole.WORKLOAD),
            packet_id="packet-v1",
            packet_sha256=_SHA,
            client_request_id="request-1",
            echoed_request_id="request-1",
            provider_task_id="provider-task-1",
            raw_provider_response_sha256=_SHA,
            output_object_sha256=_SHA,
            cached_input_tokens=0,
            total_tokens=2,
            estimated_cost_cny=0.0,
            assigned_item_count=1,
            verbatim_spans_verified=None,
            anchor_ranges_verified=True,
        )

    sentinel = SegmentationProviderCallReceipt(
        schema_version="1.1",
        call=identity_call(ApiIdentityCallRole.START_SENTINEL),
        client_request_id="request-1",
        echoed_request_id="request-1",
        provider_task_id="provider-task-1",
        raw_provider_response_sha256=_SHA,
        output_object_sha256=_SHA,
        cached_input_tokens=0,
        total_tokens=2,
        estimated_cost_cny=0.0,
        verbatim_spans_verified=None,
        identity_sentinel_output_verified=True,
    )
    assert sentinel.anchor_ranges_verified is None


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
    segment_contract = contract["properties"]["items"]["items"]["properties"]["segments"]["items"]
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


def test_legacy_normalization_uses_trusted_offsets_for_repeated_anchor_text() -> None:
    source = "Compare A-B with A-B."
    start = source.rfind("A-B")
    segments = _normalize_raw_segments(
        raw_segments=[
            {
                "verbatim_decision_text": "A-B",
                "start_char": start,
                "end_char": start + 3,
                "primary_decision_family": "experiment",
                "atomic_decision_statement": "Compare the second condition.",
                "rationale": "The trusted anchor offsets select the second occurrence.",
                "uncertainty": "low",
            }
        ],
        campaign_id="campaign-opaque",
        review_item_id="item-opaque",
        review_comment=source,
    )
    assert segments[0].start_char == start
    without_offsets = [
        {
            key: value
            for key, value in {
                "verbatim_decision_text": "A-B",
                "primary_decision_family": "experiment",
                "atomic_decision_statement": "Compare the second condition.",
                "rationale": "The locator is duplicated.",
                "uncertainty": "low",
            }.items()
        }
    ]
    with pytest.raises(ValueError, match="occur exactly once"):
        _normalize_raw_segments(
            raw_segments=without_offsets,
            campaign_id="campaign-opaque",
            review_item_id="item-opaque",
            review_comment=source,
        )

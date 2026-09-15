from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scitaste.evaluation.taste_source_segmentation_post_audit as post_audit
from scitaste.evaluation.taste_source_segmentation_post_audit import (
    PostAuditArtifactBinding,
    TasteSourceIntegrityReviewReceipt,
    TasteSourceSegmentationIntegrityAuditReport,
    load_taste_source_integrity_inventory,
    normalize_taste_source_integrity_inventory,
    save_taste_source_integrity_inventory,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationRequestBinding,
    TasteSourceSegmentationRequestItem,
    TasteSourceSegmentationRequestPack,
    TasteSourceSegmentationRequestPacket,
    load_segmentation_post_audit_gate,
    load_taste_source_segmentation_request_pack,
    taste_source_evidence_unit_table_sha256,
    unitize_taste_source_comment,
)

_SHA = "a" * 64
_FORBIDDEN = (
    "article_title",
    "author_response",
    "later_revision",
    "observed_recommendation",
    "publisher_subject",
    "source_identity",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _build_request_pack(root: Path) -> Path:
    comment = "Add a larger control group."
    item = TasteSourceSegmentationRequestItem(
        campaign_token="campaign-opaque",
        review_item_id="item-opaque",
        reviewed_abstract="A synthetic abstract.",
        review_comment=comment,
        evidence_units=unitize_taste_source_comment(comment),
        evidence_unit_table_sha256=taste_source_evidence_unit_table_sha256(comment),
    )
    bindings = []
    for slot in ("segmenter-a", "segmenter-b"):
        packet = TasteSourceSegmentationRequestPacket(
            schema_version="1.2",
            packet_id=f"synthetic-{slot}",
            project_id="synthetic-project",
            protocol_id="synthetic-protocol",
            sample_sha256=_SHA,
            sample_manifest_file_sha256=_SHA,
            rubric_file_sha256=_SHA,
            segmenter_slot=slot,
            shard_index=1,
            shard_count=1,
            requested_provider="offline",
            requested_model="synthetic-model",
            system_instruction="Use the supplied evidence-unit identifiers.",
            rubric={"rubric_id": "synthetic-rubric"},
            items=(item,),
            output_contract={"type": "object"},
        )
        relative = Path("requests") / f"{slot}.json"
        packet_path = root / relative
        _write_json(packet_path, packet.model_dump(mode="json"))
        bindings.append(
            TasteSourceSegmentationRequestBinding(
                locator=relative.as_posix(),
                file_sha256=_sha256(packet_path),
                packet_sha256=packet.packet_sha256,
                segmenter_slot=slot,
                shard_index=1,
                item_count=1,
            )
        )
    pack = TasteSourceSegmentationRequestPack(
        schema_version="1.2",
        pack_id="synthetic-pack",
        project_id="synthetic-project",
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
        protocol_file_sha256=_SHA,
        freeze_receipt_file_sha256=_SHA,
        sample_sha256=_SHA,
        requests=tuple(bindings),
        unique_item_count=1,
        request_count=2,
        input_field_names=(
            "campaign_token",
            "review_item_id",
            "reviewed_abstract",
            "review_comment",
            "evidence_units",
            "evidence_unit_table_sha256",
        ),
        forbidden_source_field_names=_FORBIDDEN,
    )
    path = root / "REQUEST_PACK.json"
    _write_json(path, pack.model_dump(mode="json"))
    return path


def test_sealed_inventory_normalization_and_hash_round_trip(tmp_path: Path) -> None:
    pack_path = _build_request_pack(tmp_path)
    gate_path = tmp_path / "integrity-gate.yaml"
    source_gate = (
        Path(__file__).resolve().parents[2]
        / "configs/evaluation/ai_review/scitastebench_segmentation_integrity_gate_v1.yaml"
    )
    gate_path.write_bytes(source_gate.read_bytes())
    raw_path = tmp_path / "RAW_INVENTORY.json"
    _write_json(
        raw_path,
        {
            "items": [
                {
                    "campaign_token": "campaign-opaque",
                    "review_item_id": "item-opaque",
                    "decisions": [
                        {
                            "trigger_range": {
                                "start_unit_id": "u0001",
                                "end_unit_id": "u0006",
                            },
                            "context_ranges": [],
                            "primary_decision_family": "experiment",
                            "atomic_decision_statement": "Increase the control group.",
                            "rationale": "This is an actionable experimental change.",
                            "uncertainty": "low",
                        }
                    ],
                    "no_decision_rationale": None,
                    "residual_decision_bearing_text_possible": False,
                }
            ]
        },
    )
    gate = load_segmentation_post_audit_gate(gate_path)
    pack = load_taste_source_segmentation_request_pack(pack_path)
    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    receipt = TasteSourceIntegrityReviewReceipt(
        receipt_id="synthetic-review-receipt",
        project_id="synthetic-project",
        completed_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
        gate=PostAuditArtifactBinding(
            locator="integrity-gate.yaml",
            file_sha256=_sha256(gate_path),
            semantic_sha256=_canonical_sha256(gate.gate.model_dump(mode="json")),
        ),
        request_pack=PostAuditArtifactBinding(
            locator="REQUEST_PACK.json",
            file_sha256=_sha256(pack_path),
            semantic_sha256=pack.pack_sha256,
        ),
        raw_output=PostAuditArtifactBinding(
            locator="RAW_INVENTORY.json",
            file_sha256=_sha256(raw_path),
            semantic_sha256=_canonical_sha256(raw_payload),
        ),
        invocation_id="synthetic-ai-d-invocation",
        runtime_surface="codex-subagent",
        model_identifier="nonhuman-review-agent",
        assigned_unique_item_count=1,
        reviewed_unique_item_count=1,
        decision_count=1,
        structural_serialization_correction_performed=False,
    )
    receipt_path = tmp_path / "REVIEW_RECEIPT.yaml"
    receipt_payload = receipt.model_dump(mode="json")
    _write_json(receipt_path, receipt_payload)
    unhashed_receipt_path = tmp_path / "UNHASHED_REVIEW_RECEIPT.yaml"
    receipt_payload.pop("receipt_sha256")
    _write_json(unhashed_receipt_path, receipt_payload)
    with pytest.raises(ValueError, match="review-receipt semantic hash mismatch"):
        post_audit.load_taste_source_integrity_review_receipt(unhashed_receipt_path)

    inventory = normalize_taste_source_integrity_inventory(
        raw_inventory_path=raw_path,
        request_pack_path=pack_path,
        gate_path=gate_path,
        review_receipt_path=receipt_path,
        inventory_id="synthetic-inventory",
        locator_root=tmp_path,
    )

    assert inventory.items[0].decisions[0].verbatim_decision_text == ("Add a larger control group.")
    assert inventory.not_human_review is True
    assert inventory.formal_evidence_eligible is False
    saved = save_taste_source_integrity_inventory(inventory, tmp_path / "SEALED_INVENTORY.json")
    assert load_taste_source_integrity_inventory(saved) == inventory
    replayed, replayed_pack, replayed_items = post_audit._verify_and_replay_inventory(
        inventory_path=saved,
        request_pack_path=pack_path,
        locator_root=tmp_path,
    )
    assert replayed == inventory
    assert replayed_pack.pack_sha256 == pack.pack_sha256
    assert len(replayed_items) == 1

    original_pack_bytes = pack_path.read_bytes()
    pack_payload = json.loads(original_pack_bytes)
    pack_path.write_text(json.dumps(pack_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="request-pack binding drifted"):
        post_audit._verify_and_replay_inventory(
            inventory_path=saved,
            request_pack_path=pack_path,
            locator_root=tmp_path,
        )
    pack_path.write_bytes(original_pack_bytes)

    with pytest.raises(ValueError, match="not sealed before calibration"):
        post_audit._require_inventory_precedes_calibration(
            inventory, datetime(2026, 9, 15, 11, tzinfo=UTC)
        )

    raw_payload["items"][0]["decisions"][0]["rationale"] = "Tampered after sealing."
    _write_json(raw_path, raw_payload)
    with pytest.raises(ValueError, match="receipt differs from exact sealed inputs"):
        normalize_taste_source_integrity_inventory(
            raw_inventory_path=raw_path,
            request_pack_path=pack_path,
            gate_path=gate_path,
            review_receipt_path=receipt_path,
            inventory_id="synthetic-inventory",
            locator_root=tmp_path,
        )
    with pytest.raises(ValueError, match="receipt differs from exact sealed inputs"):
        post_audit._verify_and_replay_inventory(
            inventory_path=saved,
            request_pack_path=pack_path,
            locator_root=tmp_path,
        )

    payload = json.loads(saved.read_text(encoding="utf-8"))
    payload["items"][0]["residual_decision_bearing_text_possible"] = True
    saved.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"residual count drifted|semantic hash mismatch"):
        load_taste_source_integrity_inventory(saved)


def test_integrity_report_cannot_turn_blocker_into_pass() -> None:
    common = {
        "schema_version": "1.0",
        "report_id": "synthetic-report",
        "project_id": "synthetic-project",
        "compiled_at": datetime(2026, 9, 15, 12, tzinfo=UTC),
        "calibration_receipt": {
            "locator": "calibration.json",
            "file_sha256": _SHA,
            "semantic_sha256": _SHA,
        },
        "gate": {
            "locator": "gate.yaml",
            "file_sha256": _SHA,
            "semantic_sha256": _SHA,
        },
        "inventory": {
            "locator": "inventory.json",
            "file_sha256": _SHA,
            "semantic_sha256": _SHA,
        },
        "resolution": {
            "locator": "resolution.json",
            "file_sha256": _SHA,
            "semantic_sha256": _SHA,
        },
        "invocation_id": "synthetic-ai-d-invocation",
        "items": [
            {
                "campaign_id": "campaign-one",
                "review_item_id": "item-one",
                "inventory_decision_count": 1,
                "final_decision_count": 0,
                "blocker_codes": ["missed-actionable-decision"],
            }
        ],
        "blocker_codes": ["missed-actionable-decision"],
        "decision": "pass",
    }
    with pytest.raises(ValueError, match="deterministic blockers"):
        TasteSourceSegmentationIntegrityAuditReport.model_validate(common)


def test_locator_resolution_rejects_ancestor_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "artifact.json").write_text("{}", encoding="utf-8")
    (root / "escaped").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes its root"):
        post_audit._resolve_locator(root.resolve(), "escaped/artifact.json")

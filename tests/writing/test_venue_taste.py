from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.writing.venue_taste import (
    PaperArchetype,
    VenueWritingTasteContext,
    VenueWritingTasteProfile,
    build_venue_writing_taste_context,
    inspect_venue_writing_taste,
    require_venue_taste_matches_template,
    write_venue_writing_taste_context,
)

_ROOT = Path(__file__).parents[2]
_ICLR_PROFILE = _ROOT / "configs/writing/venues/iclr-2027/taste.yaml"


def _profile(tmp_path: Path) -> Path:
    provenance = tmp_path / "provenance.yaml"
    provenance.write_text("source: bounded test fixture\n", encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "profile_id": "test-venue-writing-taste-v1",
        "venue_id": "test-venue",
        "venue_name": "Test Venue",
        "effective_from": "2026-09-09",
        "profile_status": "advisory",
        "promotion_decision": "accepted",
        "immutable_core_dimensions": [
            "scientific_integrity",
            "claim_calibration",
            "precision_and_scope",
        ],
        "sources": [
            {
                "source_id": "test-official-guide",
                "source_kind": "official-guidance",
                "locator": "https://example.test/reviewer-guide",
                "retrieved_on": "2026-09-09",
                "local_path": "provenance.yaml",
                "expected_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
                "support_scope": ["test-only venue criterion"],
            }
        ],
        "principles": [
            {
                "principle_id": "test-question-visible",
                "name": "Question visible",
                "maturity": "advisory",
                "dimensions": ["narrative_focus"],
                "instruction": "Make the bounded test question visible.",
                "diagnostic_questions": ["Is the test question visible?"],
                "source_ids": ["test-official-guide"],
                "submission_gate": False,
            }
        ],
        "archetype_overlays": [
            {
                "archetype": "empirical-system",
                "narrative_duties": ["Separate component and system claims."],
                "evidence_duties": ["Expose end-to-end evidence."],
                "principle_ids": ["test-question-visible"],
            }
        ],
        "submission_eligibility_authority": False,
        "scientific_quality_established": False,
    }
    path = tmp_path / "taste.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_iclr_profile_is_content_bound_and_keeps_candidate_rules_advisory() -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)

    assert inspection.profile.profile_id == "iclr-2027-writing-taste-v1"
    assert len(inspection.profile.principles) == 20
    assert set(inspection.source_sha256) == {
        "iclr-reviewer-guide",
        "iclr-award-corpus",
        "writing-methods",
    }
    assert inspection.profile.submission_eligibility_authority is False
    assert inspection.profile.scientific_quality_established is False
    assert inspection.profile.promotion_decision == "hold"
    assert all(not item.submission_gate for item in inspection.profile.principles)
    corpus_principles = [
        item for item in inspection.profile.principles if "iclr-award-corpus" in item.source_ids
    ]
    assert corpus_principles
    assert all(item.maturity.value == "candidate" for item in corpus_principles)


def test_colocated_and_legacy_iclr_submission_configs_do_not_drift() -> None:
    legacy = yaml.safe_load(
        (_ROOT / "configs/writing/iclr2027_submission_v1.yaml").read_text(encoding="utf-8")
    )
    colocated = yaml.safe_load(
        (_ROOT / "configs/writing/venues/iclr-2027/submission.yaml").read_text(encoding="utf-8")
    )

    assert colocated == legacy


def test_context_selects_archetype_guidance_without_universal_quotas(tmp_path: Path) -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)
    markdown = "# Abstract\nWe present an evidence-bound system.\n"

    context = build_venue_writing_taste_context(
        markdown,
        inspection=inspection,
        paper_archetype=PaperArchetype.EMPIRICAL_SYSTEM,
    )

    applied = {item.principle_id for item in context.applied_principles}
    assert "wt-r09-world-interface" in applied
    assert "wt-r13-proof-chain" not in applied
    assert context.narrative_duties
    assert context.evidence_duties
    assert context.submission_eligibility_authority is False
    assert context.scientific_quality_established is False
    assert any("candidate guidance" in item for item in context.unresolved_conditions)
    assert all("at least" not in item.instruction.casefold() for item in context.applied_principles)

    path = write_venue_writing_taste_context(context, tmp_path / "context.json")
    reloaded = VenueWritingTasteContext.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded == context


def test_unspecified_archetype_omits_conditional_guidance_explicitly() -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)

    context = build_venue_writing_taste_context("# Abstract\nBounded.\n", inspection=inspection)

    assert context.paper_archetype is PaperArchetype.UNSPECIFIED
    assert "wt-r09-world-interface" in context.omitted_conditional_principle_ids
    assert context.narrative_duties == ()
    assert any("archetype is unspecified" in item for item in context.unresolved_conditions)


def test_profile_rejects_unknown_source_and_core_override() -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)
    payload = inspection.profile.model_dump(mode="json")
    payload["immutable_core_dimensions"] = [
        "scientific_integrity",
        "narrative_focus",
        "venue_fit",
    ]

    with pytest.raises(ValidationError) as exc_info:
        VenueWritingTasteProfile.model_validate(payload)

    assert "cannot override integrity" in str(exc_info.value)

    payload = inspection.profile.model_dump(mode="json")
    payload["principles"][0]["source_ids"] = ["unknown-source"]
    with pytest.raises(ValidationError, match="unknown source"):
        VenueWritingTasteProfile.model_validate(payload)


def test_context_and_template_venue_must_match() -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)

    with pytest.raises(ValueError, match="does not match submission template"):
        require_venue_taste_matches_template(inspection, venue_id="another-venue")


def test_context_hash_detects_tampering() -> None:
    inspection = inspect_venue_writing_taste(_ICLR_PROFILE)
    context = build_venue_writing_taste_context("# Abstract\nBounded.\n", inspection=inspection)
    payload = json.loads(context.model_dump_json())
    payload["venue_name"] = "Changed Venue"

    with pytest.raises(ValidationError, match="context hash mismatch"):
        VenueWritingTasteContext.model_validate(payload)


def test_profile_inspection_rejects_local_provenance_drift(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    (tmp_path / "provenance.yaml").write_text("source: changed fixture\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source hash mismatch"):
        inspect_venue_writing_taste(profile)

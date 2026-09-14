from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    TasteSourcePopulationReleasePolicy,
    TasteSourceReleaseMode,
    TasteSourceRightsScope,
    load_taste_source_release_governance,
)


def test_internal_release_governance_does_not_claim_public_authority() -> None:
    inspection = load_taste_source_release_governance(
        Path("configs/evaluation/human_review/scitastebench_source_release_governance_v2.yaml")
    )

    assert inspection.policy.internal_ai_screening_allowed is True
    assert inspection.policy.public_release_authorized is False
    assert {item.release_mode for item in inspection.policy.populations} == {
        TasteSourceReleaseMode.CONTROLLED_INTERNAL_ONLY
    }


def test_attributable_and_deidentified_release_claims_cannot_be_mixed() -> None:
    with pytest.raises(ValidationError, match="cannot claim de-identification"):
        TasteSourcePopulationReleasePolicy(
            campaign_id="example-campaign",
            item_count=1,
            release_mode=TasteSourceReleaseMode.ATTRIBUTABLE_PUBLIC_SOURCE,
            rights_scope=TasteSourceRightsScope.PER_ITEM_CONTENT,
            content_license_identifiers=("CC-BY-4.0",),
            public_reader_access_verified=True,
            source_attribution_preserved=True,
            exact_source_text_permitted=True,
            private_derivation_map_bound=True,
            redaction_manifest_bound=False,
            reidentification_screen_passed=False,
            rationale="The deliberately invalid fixture mixes release modes.",
        )

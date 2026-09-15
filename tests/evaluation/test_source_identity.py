from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation.source_identity import (
    CanonicalSourceIdentity,
    CanonicalSourceIdentityRegistry,
    canonical_f1000_source_group_id,
    canonical_openreview_source_group_id,
    load_canonical_source_identity_registry,
    save_canonical_source_identity_registry,
)


def test_f1000_identity_is_stable_across_doi_forms_and_versions() -> None:
    expected = canonical_f1000_source_group_id("10.12688/f1000research.12345")

    assert canonical_f1000_source_group_id("10.12688/F1000Research.12345.v1") == expected
    assert (
        canonical_f1000_source_group_id("https://doi.org/10.12688/f1000research.12345.7")
        == expected
    )
    assert expected.startswith("f1000-work-")


def test_openreview_identity_is_stable_without_case_folding() -> None:
    expected = canonical_openreview_source_group_id("ab7lBP7Fb60")

    assert canonical_openreview_source_group_id("  ab7lBP7Fb60  ") == expected
    assert canonical_openreview_source_group_id("AB7lBP7Fb60") != expected
    assert expected.startswith("openreview-forum-")


def test_private_registry_resolves_legacy_alias_without_raw_identifier(
    tmp_path: Path,
) -> None:
    entry = CanonicalSourceIdentity.create(
        namespace="f1000-work-v1",
        source_identifier="10.12688/f1000research.12345.v2",
        legacy_source_group_ids=("f1000-group-legacy",),
    )
    registry = CanonicalSourceIdentityRegistry.create(
        registry_id="formal-source-identities-v1",
        entries=(entry,),
    )
    path = save_canonical_source_identity_registry(registry, tmp_path / "registry.json")
    loaded = load_canonical_source_identity_registry(path)

    assert loaded.resolve("f1000-group-legacy") == entry.canonical_source_group_id
    assert loaded.resolve(entry.canonical_source_group_id) == entry.canonical_source_group_id
    assert "10.12688" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="absent"):
        loaded.resolve("unknown-group")


def test_registry_rejects_alias_collision() -> None:
    left = CanonicalSourceIdentity.create(
        namespace="f1000-work-v1",
        source_identifier="10.12688/f1000research.1",
        legacy_source_group_ids=("legacy-group",),
    )
    right = CanonicalSourceIdentity.create(
        namespace="f1000-work-v1",
        source_identifier="10.12688/f1000research.2",
        legacy_source_group_ids=("legacy-group",),
    )

    with pytest.raises(ValidationError, match="multiple works"):
        CanonicalSourceIdentityRegistry.create(
            registry_id="collision-v1",
            entries=(left, right),
        )


def test_registry_loader_rejects_hash_drift(tmp_path: Path) -> None:
    entry = CanonicalSourceIdentity.create(
        namespace="openreview-forum-v1",
        source_identifier="forumABC123",
    )
    registry = CanonicalSourceIdentityRegistry.create(
        registry_id="forum-identities-v1",
        entries=(entry,),
    )
    payload = registry.model_dump(mode="json")
    payload["registry_id"] = "changed-v1"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="hash mismatch"):
        load_canonical_source_identity_registry(path)

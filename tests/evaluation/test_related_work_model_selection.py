from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.related_work_model_selection import (
    RelatedWorkModelCatalog,
    load_related_work_model_catalog,
    summarize_related_work_model_catalog,
)

CATALOG = Path(
    "configs/evaluation/model_selection/scitaste_iclr27_related_work_candidates_v1.yaml"
)


def _payload() -> dict[str, object]:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_catalog_is_idea_and_related_work_first() -> None:
    catalog, digest = load_related_work_model_catalog(CATALOG)
    summary = summarize_related_work_model_catalog(catalog, catalog_sha256=digest)

    assert catalog.selection_order[-1] == "use-resource-cost-and-throughput-only-as-tiebreakers"
    assert summary.direct_neighbor_count == 2
    assert summary.model_family_count >= 8
    assert "scijudge-4b-2605-external" in summary.candidates_by_plane["taste-impact-judge"]
    assert "mlrc-locpoint-task-model" in summary.candidates_by_plane["benchmark-task-model"]
    assert summary.formal_model_selected is False
    assert summary.unresolved_access_candidates


def test_catalog_rejects_inventory_first_selection() -> None:
    payload = _payload()
    order = payload["selection_order"]
    order[0], order[-1] = order[-1], order[0]

    with pytest.raises(ValidationError, match="resource preference"):
        RelatedWorkModelCatalog.model_validate(payload)


def test_catalog_rejects_impact_model_as_peer_reviewer() -> None:
    payload = _payload()
    payload["candidates"][0]["planes"].append("paper-reviewer")

    with pytest.raises(ValidationError, match="impact prediction"):
        RelatedWorkModelCatalog.model_validate(payload)

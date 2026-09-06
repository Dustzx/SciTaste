from __future__ import annotations

import pytest
from pydantic import ValidationError

from scitaste.project.models import content_sha256
from scitaste.state.research_state import EvidenceItem, ScientificClaim
from scitaste.writing.evidence_projection import WritingEvidenceProjection


def test_projection_is_self_hashed_and_replicate_derived() -> None:
    payload = _projection_payload()
    projection = WritingEvidenceProjection(
        **payload,
        record_sha256=content_sha256(payload),
    )

    assert projection.primary_value == pytest.approx(0.1)
    assert projection.primary_dispersion == 0.0


def test_projection_rejects_content_changed_after_hashing() -> None:
    payload = _projection_payload()
    serialized = {
        **payload,
        "record_sha256": content_sha256(payload),
        "source_decision_id": "dec-replaced",
    }

    with pytest.raises(ValidationError, match="projection hash mismatch"):
        WritingEvidenceProjection.model_validate(serialized)


def test_projection_rejects_aggregate_that_is_not_replicate_mean() -> None:
    payload = _projection_payload()
    payload["primary_values"] = [0.1, 0.1, 0.2]

    with pytest.raises(ValidationError, match="not the replicate mean"):
        WritingEvidenceProjection(
            **payload,
            record_sha256=content_sha256(payload),
        )


def _projection_payload() -> dict[str, object]:
    evidence = EvidenceItem(
        evidence_id="evidence-res-measured-claim-measured",
        source_type="experiment",
        evidence_type="matched held-out benchmark",
        experiment_id="experiment-measured",
        observation="Measured correct pivot delta across three replicates.",
        supports_claim_ids=["claim-measured"],
        confidence=0.9,
        stability=1.0,
    )
    claim = ScientificClaim(
        claim_id="claim-measured",
        text="Conflict-aware ranking improves correct pivots under matched compute.",
        claim_type="performance",
        strength="moderate",
        required_evidence_types=["matched held-out benchmark"],
        supporting_evidence_ids=[evidence.evidence_id],
        status="supported",
    )
    return {
        "schema_version": "1.0",
        "project_id": "measured-project",
        "source_state_locator": "stages/evidence/research_state.json",
        "source_state_sha256": "1" * 64,
        "source_decision_id": "dec-measured",
        "source_action_id": "action-measured",
        "execution_record_locator": "native_execution/records/000001-a.json",
        "execution_record_sha256": "2" * 64,
        "metrics_artifact_locator": "native_execution/artifacts/a/metrics.json",
        "metrics_artifact_sha256": "3" * 64,
        "result_basis": "sandbox-measured-replicates",
        "result_id": "res-measured",
        "experiment_id": "experiment-measured",
        "claim": claim.model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
        "relation": "supports",
        "observation": evidence.observation,
        "metrics": {"correct_pivot_delta": 0.1},
        "primary_metric": "correct_pivot_delta",
        "primary_value": 0.1,
        "replicate_ids": ["seed-7", "seed-19", "seed-31"],
        "primary_values": [0.1, 0.1, 0.1],
        "primary_dispersion": 0.0,
        "reproducible": True,
        "stability": 1.0,
        "statistical_uncertainty": 0.0,
        "metric_derivation": "arithmetic-mean-of-validated-replicates",
    }

import hashlib
import json

import pytest

from scitaste.review.evidence_projection import scientific_confirmation_view


def fixture():
    return {
        "status": "completed",
        "executed_frozen_source": True,
        "formal_evidence_eligible": False,
        "result": {
            "task_id": "sensor-drift-probability-transfer",
            "primary_method": "a",
            "primary_scores": {"batch6": 0.2, "batch7": 0.3},
            "scores": [
                {
                    "method": method,
                    "context": context,
                    "status": "scored",
                    "prediction_sha256": f"{method}-{context}",
                    "output_failure": None,
                    "metrics": {
                        "multiclass_brier": score,
                        "class_recall": [0.2, None, 0.0],
                        "declared_failure_fraction": 0.0,
                        "self_reported_cpu_seconds": score * 2,
                    },
                }
                for method in ("a", "b")
                for context, score in (("batch6", 0.2), ("batch7", 0.3))
            ],
        },
    }


def test_lossless_score_and_metric_reconstruction():
    original = fixture()
    raw = json.dumps(original).encode()
    packed, version = scientific_confirmation_view(raw)
    visible = json.loads(packed)
    result = visible["result"]
    recovered = []
    for values in result["scores"]:
        row = dict(zip(result["score_columns"], values, strict=True))
        row.update(result["score_constant_fields"])
        metrics = dict(zip(result["metric_columns"], row["metrics"], strict=True))
        metrics.update(result["metric_constant_fields"])
        row["metrics"] = metrics
        recovered.append(row)
    assert recovered == original["result"]["scores"]
    assert result["primary_scores"] == original["result"]["primary_scores"]
    assert visible["formal_evidence_eligible"] is False
    assert result["review_projection"]["omitted_fields"] == []
    assert version == "lossless-sensor-score-columns.v1"


@pytest.mark.parametrize("corruption", ("not-executed", "unequal-metric-schema"))
def test_unknown_or_incomplete_projection_fails_closed(corruption):
    original = fixture()
    if corruption == "not-executed":
        original["executed_frozen_source"] = False
    else:
        original["result"]["scores"][1]["metrics"].pop("class_recall")
    with pytest.raises(ValueError, match="Unrecognized"):
        scientific_confirmation_view(json.dumps(original).encode())


def test_pending_review_preserves_exact_old_display_and_rejects_changed_evidence(tmp_path):
    from scitaste.review.evidence_projection import compact_json_evidence
    from scitaste.review.lifecycle_review import unchanged_retained_evidence

    raw = json.dumps(fixture(), indent=2).encode()
    artifact = tmp_path / "confirmation.json"
    artifact.write_bytes(raw)
    metadata = {"sha256": hashlib.sha256(raw).hexdigest(), "original_utf8_bytes": len(raw)}
    old = {
        "confirmation.json": {
            **metadata,
            "text": compact_json_evidence(raw).decode(),
            "projection": "lossless-json-whitespace-compaction.v1; every field/token retained",
        }
    }
    packed, projection = scientific_confirmation_view(raw)
    new = {"confirmation.json": {**metadata, "text": packed.decode(), "projection": projection}}
    assert unchanged_retained_evidence(tmp_path, old, new)
    old["confirmation.json"]["text"] += " "
    assert not unchanged_retained_evidence(tmp_path, old, new)
    old["confirmation.json"]["text"] = compact_json_evidence(raw).decode()
    artifact.write_bytes(raw.replace(b"0.2", b"0.9", 1))
    assert not unchanged_retained_evidence(tmp_path, old, new)

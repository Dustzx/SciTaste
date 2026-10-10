import json

import pytest

from scitaste.writing.paper_cycle import recover_bounded_review


def receipt(path, blocker):
    path.mkdir()
    (path / "RESULT.json").write_text(
        json.dumps(
            {
                "outcome": "rejected",
                "blockers": [blocker],
                "result": {
                    "node_name": "venue-paper-review",
                    "request": {"expected_backend": "assistant-session"},
                },
            }
        )
    )


def test_unchanged_advice_reuses_validation_without_replacing_rejection(tmp_path, monkeypatch):
    destination = tmp_path / "review"
    receipt(destination, "project revision changed while the model-node backend was running")
    original = (destination / "RESULT.json").read_bytes()
    calls = []
    monkeypatch.setattr(
        "scitaste.review.recover_lifecycle.recover", lambda **kwargs: calls.append(kwargs)
    )
    assert recover_bounded_review(tmp_path, "review-id", destination)
    assert calls == [{"project": tmp_path, "review_id": "review-id", "output": destination}]
    assert (destination / "RESULT.json").read_bytes() == original


def test_semantic_rejection_is_not_recoverable(tmp_path, monkeypatch):
    destination = tmp_path / "review"
    receipt(destination, "invented evidence identifier")
    monkeypatch.setattr(
        "scitaste.review.recover_lifecycle.recover",
        lambda **kwargs: pytest.fail("Semantic rejection must remain fail-closed"),
    )
    assert not recover_bounded_review(tmp_path, "review-id", destination)


def test_changed_bound_input_propagates_recovery_failure(tmp_path, monkeypatch):
    destination = tmp_path / "review"
    receipt(destination, "output token budget exceeded")

    def changed(**kwargs):
        raise ValueError("Reviewed paper artifact changed")

    monkeypatch.setattr("scitaste.review.recover_lifecycle.recover", changed)
    with pytest.raises(ValueError, match="artifact changed"):
        recover_bounded_review(tmp_path, "review-id", destination)

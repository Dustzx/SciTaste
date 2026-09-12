from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scitaste.evaluation import (
    BlindedHumanComparison,
    BlindedOutputBinding,
    HumanBlindKey,
    HumanBlindKeyEntry,
    HumanBlindOpening,
    HumanOutcomeStudyManifest,
    HumanPairwisePreference,
    HumanStudyFileBinding,
    LockedHumanOutcomeReview,
    LockedHumanReviewSet,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    inspect_human_outcome_study,
)

SHA = "1" * 64


def test_h1_h2_reviews_lock_before_unblinding(tmp_path: Path) -> None:
    study, key = _study(tmp_path)
    reviews = _reviews(study)

    blinded = inspect_human_outcome_study(study, evidence_root=tmp_path, reviews=reviews)

    assert blinded.ready_to_open_blind_key is True
    assert blinded.ready_for_primary_analysis is False
    assert blinded.outcomes == ()

    opening = HumanBlindOpening(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=key,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )
    report = inspect_human_outcome_study(
        study,
        evidence_root=tmp_path,
        reviews=reviews,
        opening=opening,
    )

    assert report.ready_for_primary_analysis is True
    assert report.h1_contrast_verified is True
    assert report.h2_contrast_verified is True
    assert report.shared_triplet_identity_verified is True
    assert len(report.outcomes) == 4
    assert [item.preferred_condition for item in report.outcomes] == [
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
    ]


def test_changed_blind_key_cannot_relabel_locked_reviews(tmp_path: Path) -> None:
    study, key = _study(tmp_path)
    reviews = _reviews(study)
    changed_entries = list(key.entries)
    first = changed_entries[0]
    changed_entries[0] = first.model_copy(
        update={
            "x_condition": TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            "y_condition": TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        }
    )
    changed = key.model_copy(update={"entries": tuple(changed_entries)})
    opening = HumanBlindOpening(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=changed,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )

    report = inspect_human_outcome_study(
        study,
        evidence_root=tmp_path,
        reviews=reviews,
        opening=opening,
    )

    assert report.blind_key_commitment_verified is False
    assert report.shared_triplet_identity_verified is False
    assert report.ready_for_primary_analysis is False


def _study(tmp_path: Path) -> tuple[HumanOutcomeStudyManifest, HumanBlindKey]:
    bindings = {}
    for name in ("protocol", "rubric", "interface", "matched", "raw", "mismatched"):
        path = tmp_path / f"{name}.txt"
        path.write_text(name + "\n", encoding="utf-8")
        bindings[name] = HumanStudyFileBinding(
            path=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def output(name: str, label: str) -> BlindedOutputBinding:
        source = bindings[name]
        return BlindedOutputBinding(
            path=source.path,
            sha256=source.sha256,
            output_id=label,
            presentation_profile_sha256=SHA,
            context_budget_tokens=8_192,
            maximum_output_tokens=1_024,
        )

    reviewers = ("2" * 64, "3" * 64)
    comparisons = (
        BlindedHumanComparison(
            comparison_id="h1-review-one",
            hypothesis=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[0],
            x_output=output("matched", "x-h1-one"),
            y_output=output("raw", "y-h1-one"),
        ),
        BlindedHumanComparison(
            comparison_id="h1-review-two",
            hypothesis=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[1],
            x_output=output("raw", "x-h1-two"),
            y_output=output("matched", "y-h1-two"),
        ),
        BlindedHumanComparison(
            comparison_id="h2-review-one",
            hypothesis=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[0],
            x_output=output("matched", "x-h2-one"),
            y_output=output("mismatched", "y-h2-one"),
        ),
        BlindedHumanComparison(
            comparison_id="h2-review-two",
            hypothesis=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[1],
            x_output=output("mismatched", "x-h2-two"),
            y_output=output("matched", "y-h2-two"),
        ),
    )
    draft = HumanOutcomeStudyManifest(
        study_id="human-study-one",
        project_id="project-one",
        protocol=bindings["protocol"],
        rubric=bindings["rubric"],
        interface=bindings["interface"],
        blind_key_sha256="0" * 64,
        comparisons=comparisons,
    )
    key = HumanBlindKey(
        study_id=draft.study_id,
        assignment_sha256=draft.assignment_sha256,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        entries=(
            _key("h1-review-one", "matched", "raw"),
            _key("h1-review-two", "raw", "matched"),
            _key("h2-review-one", "matched", "mismatched"),
            _key("h2-review-two", "mismatched", "matched"),
        ),
    )
    payload = draft.model_dump(
        mode="python", exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"}
    )
    return (
        HumanOutcomeStudyManifest(**payload, blind_key_sha256=key.blind_key_sha256),
        key,
    )


def _key(comparison_id: str, x: str, y: str) -> HumanBlindKeyEntry:
    conditions = {
        "matched": TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        "raw": TasteStudyCondition.SAME_SOURCE_RAW_RAG,
        "mismatched": TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
    }
    traces = {"matched": "4" * 64, "raw": "5" * 64, "mismatched": "6" * 64}
    return HumanBlindKeyEntry(
        comparison_id=comparison_id,
        x_condition=conditions[x],
        y_condition=conditions[y],
        x_generation_trace_sha256=traces[x],
        y_generation_trace_sha256=traces[y],
    )


def _reviews(study: HumanOutcomeStudyManifest) -> LockedHumanReviewSet:
    locked_at = datetime(2026, 9, 12, 2, tzinfo=UTC)
    preferences = {
        "h1-review-one": HumanPairwisePreference.X,
        "h1-review-two": HumanPairwisePreference.Y,
        "h2-review-one": HumanPairwisePreference.X,
        "h2-review-two": HumanPairwisePreference.Y,
    }
    return LockedHumanReviewSet(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        reviews=tuple(
            LockedHumanOutcomeReview(
                review_id=f"review-{index}",
                comparison_id=item.comparison_id,
                study_sha256=study.study_sha256,
                reviewer_identity_sha256=item.reviewer_identity_sha256,
                preference=preferences[item.comparison_id],
                rationale="The preferred decision is better calibrated to the visible evidence.",
                locked_at=locked_at,
            )
            for index, item in enumerate(study.comparisons, start=1)
        ),
        locked_at=locked_at,
    )

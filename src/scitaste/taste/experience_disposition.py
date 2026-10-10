"""Shared conservative routing of observations; never silently admits Taste."""

from scitaste.taste.attribution_feedback import load_attribution_feedback
from scitaste.taste.episodes import TasteCreditDirection


def disposition_for_candidate(candidate, *, review_bytes=None):
    if review_bytes is not None:
        feedback = load_attribution_feedback(review_bytes, candidate)
        disposition = {"accept": "pending-admission", "reject": "rejected"}.get(
            feedback.verdict, "abstained"
        )
        return disposition, "bound-ai-review: " + feedback.rationale
    if candidate.credit_assignments and all(
        credit.direction == TasteCreditDirection.NOT_ATTRIBUTABLE
        for credit in candidate.credit_assignments
    ):
        return "abstained", (
            "Observation-only candidate explicitly assigns no attributable credit; "
            "retain measured experience without learning an action preference. "
            "This is a conservative routing decision, not scientific review."
        )
    return "pending-attribution-review", (
        "Proposed directional credit has no bound review; do not admit it."
    )

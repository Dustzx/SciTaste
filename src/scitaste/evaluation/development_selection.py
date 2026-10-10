"""Development-use eligibility is distinct from held-out Taste-learning provenance."""

# These are explicit existing split labels, not a substring heuristic that could
# accidentally admit a formal-test split. Extend when adding a documented split.
_DEVELOPMENT_SPLITS = {
    "development",
    "development-view-source-disjoint-from-taste-training",
}


def development_task_eligible(task, *, study_scope):
    values = task if isinstance(task, dict) else task.model_dump(mode="json")
    return study_scope == "pilot" and values["split"] in _DEVELOPMENT_SPLITS

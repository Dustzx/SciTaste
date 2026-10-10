"""Keep separately assigned recovery confirmation out of original result paths."""

import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.project.models import validate_relative_locator


def confirmation_directory(project: Path, campaign: Path, arm: str, assignment):
    parent = campaign.resolve(strict=True).parent
    locator = assignment.get("confirmation") if isinstance(assignment, dict) else None
    if locator is None:
        return parent / "confirmation" / arm
    validate_relative_locator(locator, field_name="confirmation assignment")
    path = (project.resolve(strict=True) / locator).resolve()
    path.relative_to(parent)
    if path == parent:
        raise ValueError("Confirmation must have its own directory")
    return path


def native_confirmation_source(project: Path, campaign: Path, run: Path, assignment):
    """Resolve only an explicitly assigned, exact Native continuation ancestor.

    Reporting recovery may inherit an existing confirmation, never execute it
    again or turn an unrelated run's measurements into the current one's evidence.
    """
    target = (project / assignment.get("confirmation_source_run", assignment["run"])).resolve(
        strict=True
    )
    target.relative_to(project / "evaluations")
    cursor = run
    seen = set()
    while cursor != target:
        if cursor in seen or len(seen) >= 8:
            raise ValueError("Invalid or excessive Native confirmation ancestry")
        seen.add(cursor)
        launch = json.loads((cursor / "CONTRACT.json").read_bytes())
        lineage = launch.get("continuation") or {}
        ancestor = Path(lineage.get("parent", "")).resolve(strict=True)
        ancestor.relative_to(project / "evaluations")
        previous = json.loads((ancestor / "CONTRACT.json").read_bytes())
        if (
            verified_asset(project, launch["plan"]["campaign"]) != campaign
            or verified_asset(project, previous["plan"]["campaign"]) != campaign
            or launch["plan_sha256"] != previous["plan_sha256"]
            or launch.get("development_taste") != previous.get("development_taste")
            or launch.get("taste_context") != previous.get("taste_context")
            or lineage.get("parent_result_sha256") != digest(ancestor / "RESULT.json")
            or not lineage.get("recovery_excluded_from_original_run_score")
            or lineage.get("inherited_duration_seconds", 0) <= 0
        ):
            raise ValueError("Native confirmation inheritance lacks unchanged task/clock lineage")
        cursor = ancestor
    if target != run:
        release = (
            confirmation_directory(project, campaign, "scitaste-native", assignment) / "release"
        )
        frozen = json.loads((release / "RELEASE.json").read_bytes())["frozen_source"]
        for name, expected in frozen.items():
            path = run / "workspace/submission" / name
            path.resolve(strict=True).relative_to(run / "workspace/submission")
            if path.is_symlink() or digest(path) != expected:
                raise ValueError("A reporting continuation changed confirmed scientific source")
    return target

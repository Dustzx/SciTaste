"""Import real family reviews and refresh a non-activated project policy snapshot."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.models import validate_entry_id
from scitaste.project.research_artifact import register_artifact
from scitaste.taste.ai_attribution import save_ai_reviewed_episode_json
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    LifecycleTastePolicyConfig,
    LifecycleTastePolicyUpdateMode,
)
from scitaste.taste.family_review import (
    compile_scientific_decision_family_assignment,
    scientific_decision_family_review_from_runtime,
)
from scitaste.taste.project_policy import (
    load_project_taste_policy_corpus,
    materialize_project_taste_policy_refresh,
    seal_project_taste_policy_corpus,
)


def persist(value, path):
    """Resume only from identical retained artifacts; do not replace reviews."""
    if path.exists():
        if json.loads(path.read_text()) != value.model_dump(mode="json"):
            raise ValueError(f"Retained policy-refresh artifact changed: {path.name}")
    else:
        save_ai_reviewed_episode_json(value, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "episode", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--family-review-run", action="append", required=True)
    parser.add_argument("--adjudicator-run")
    parser.add_argument("--existing-corpus", type=Path)
    args = parser.parse_args()
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    args.episode.resolve(strict=True).relative_to(root)
    validate_entry_id(output.name, field_name="policy refresh identity")
    if len(args.family_review_run) != 2:
        raise ValueError("Exactly two primary family-review runs required")
    runtime = ProjectRuntime(root.parent.parent)
    episode = AdmittedTasteEpisode.model_validate_json(args.episode.read_bytes())
    if episode.candidate.project_id != root.name:
        raise ValueError("Episode belongs to another project")
    review_sources = [(run, "primary") for run in args.family_review_run]
    if args.adjudicator_run:
        review_sources.append((args.adjudicator_run, "adjudicator"))
    reviews = []
    for run_id, role in review_sources:
        validate_entry_id(run_id, field_name="review run identity")
        contract_path = (root / "evaluations" / run_id / "CONTRACT.json").resolve(strict=True)
        contract_path.relative_to(root)
        contract = json.loads(contract_path.read_text())
        review = scientific_decision_family_review_from_runtime(
            runtime,
            episode,
            project_id=root.name,
            run_id=run_id,
            invocation_id=contract["invocation_id"],
            reviewer_id=run_id,
            role=role,
        )
        reviews.append(review)
    assignment = compile_scientific_decision_family_assignment(
        episode,
        tuple(reviews),
        assignment_id=output.name + "-family",
    )
    output.mkdir(parents=True, exist_ok=True)
    for index, review in enumerate(reviews):
        persist(review, output / f"FAMILY_REVIEW_{index + 1}.json")
    assignment_path = output / "ASSIGNMENT.json"
    persist(assignment, assignment_path)
    episode_paths, assignment_paths = [args.episode], [assignment_path]
    if args.existing_corpus:
        args.existing_corpus.resolve(strict=True).relative_to(root)
        previous = load_project_taste_policy_corpus(args.existing_corpus)
        if previous.project_id != root.name:
            raise ValueError("Previous corpus belongs to another project")
        for item in previous.episodes:
            if item.admission_id == episode.admission_id:
                raise ValueError("New episode is already present in previous corpus")
            for locator, expected, paths in (
                (item.admission_locator, item.admission_artifact_sha256, episode_paths),
                (item.assignment_locator, item.assignment_artifact_sha256, assignment_paths),
            ):
                path = (root / locator).resolve(strict=True)
                path.relative_to(root)
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("Previous corpus artifact changed")
                paths.append(path)
    target = output / "policy"
    if not target.exists():
        snapshot = runtime.open(root.name)
        corpus = seal_project_taste_policy_corpus(
            runtime,
            project_id=root.name,
            corpus_id=output.name + "-corpus",
            episode_paths=tuple(episode_paths),
            assignment_paths=tuple(assignment_paths),
            expected_project_revision=snapshot.revision,
        )
        idea = inspect_current_idea_revision(runtime, root.name)
        config = LifecycleTastePolicyConfig(
            policy_id=output.name + "-config",
            idea_revision=idea.current_binding,
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        )
        materialize_project_taste_policy_refresh(
            runtime,
            corpus,
            config,
            refresh_id=output.name,
            policy_id=output.name + "-policy",
            expected_project_revision=snapshot.revision,
            output_directory=target,
        )
    else:
        corpus = json.loads((target / "CORPUS_MANIFEST.json").read_text())
        expected_episodes = {
            str(path.resolve().relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in episode_paths
        }
        if {
            row["admission_locator"]: row["admission_artifact_sha256"] for row in corpus["episodes"]
        } != expected_episodes:
            raise ValueError("Existing refresh belongs to another episode population")
        new_row = next(
            row for row in corpus["episodes"] if row["admission_id"] == episode.admission_id
        )
        if new_row["assignment_sha256"] != assignment.assignment_sha256:
            raise ValueError("Existing refresh belongs to another family assignment")
    register_artifact(
        project=root,
        artifact=target / "REFRESH.json",
        run_id=output.name,
        provider="deterministic-policy-fit",
        model="family-conditioned-policy",
        condition="reviewed-experience-policy-refresh",
        status="refreshed-not-activated",
    )
    readiness = json.loads((target / "READINESS.json").read_text())
    print(
        json.dumps(
            {
                "status": "policy-snapshot-created-not-activated",
                "decision_family": assignment.decision_family.value,
                "policy_application_ready": readiness["policy_application_ready"],
                "reason_codes": readiness["reason_codes"],
                "new_api_calls": 0,
                "new_gpu_experiments": 0,
            }
        )
    )


if __name__ == "__main__":
    main()

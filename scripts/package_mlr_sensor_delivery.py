"""Render an actual upstream MLR paper; do not create a shared scientific writer."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.benchmark.open_research import digest
from scitaste.project.models import PaperManifest, validate_entry_id
from scitaste.project.research_artifact import register_artifact
from scitaste.project.runtime import ProjectRuntime


def package(project, run, paper_id):
    validate_entry_id(paper_id, field_name="paper directory")
    project, run = project.resolve(strict=True), run.resolve(strict=True)
    run.relative_to(project / "evaluations")
    result = json.loads((run / "RESULT.json").read_text())
    contract = json.loads((run / "CONTRACT.json").read_text())
    if result["status"] != "native-paper-delivered" or not result["submission_unchanged"]:
        raise ValueError("No complete, unchanged-source upstream paper delivery")
    original = Path(contract["original_run"]).resolve(strict=True)
    original.relative_to(project / "evaluations")
    for name, expected in contract["original_bindings"].items():
        if digest(original / name) != expected:
            raise ValueError("Original failure artifact changed")
    for name, expected in contract["original_submission"].items():
        if digest(run / "workspace/submission" / name) != expected:
            raise ValueError("Frozen source changed during delivery")
    source = (run / result["paper"]).resolve(strict=True)
    source.relative_to(run / "workspace/results")
    target = project / "papers" / paper_id
    manifest_path = target / "MANIFEST.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text())
        if existing["upstream_source_sha256"] != digest(source):
            raise ValueError("Existing bundle has a different upstream manuscript")
        for name, expected in existing["artifact_sha256"].items():
            if digest(target / name) != expected:
                raise ValueError("Existing rendered bundle changed")
        return target
    if target.exists() and any(target.iterdir()):
        raise ValueError("Retain incomplete rendering; use an explicit recovery directory")
    paths = materialize_manuscript(
        markdown_path=source,
        target_dir=target,
        asset_roots=(source.parent,),
        evidence_audited=False,
    )
    if digest(target / "main.md") != digest(source):
        raise ValueError("Rendering must not edit the upstream manuscript")
    run_id = run.name + "-delivery"
    register_artifact(
        project=project,
        artifact=run / "RESULT.json",
        provider="mlr-agent-native",
        model="session-supplied-backbone-unverified",
        condition="separately-charged-native-delivery-continuation",
        status=result["status"],
        run_id=run_id,
    )
    manifest = PaperManifest(
        paper_id=paper_id,
        project_id=project.name,
        title=source.read_text().splitlines()[0].lstrip("# "),
        date=datetime.now(UTC).date(),
        provider="mlr-agent-native",
        model="session-supplied-backbone-unverified",
        condition="separately-charged-native-delivery-continuation",
        task="sensor-drift-probability-transfer",
        seed=0,
        seed_semantics="registration placeholder; not a provider or experiment seed",
        stage=17,
        status="native-recovery-manuscript-rendered",
        source_run=run_id,
        evidence_scope="Actual unchanged upstream MLR writer; original first-paper failure "
        "preserved; delivery continuation separately charged; no native post-paper review "
        "or independent reproduction, formal admission or publication approval",
        publication_ready=False,
        files={
            f"artifact-{i}": path.relative_to(target).as_posix() for i, path in enumerate(paths)
        },
        upstream_source=source.relative_to(project).as_posix(),
        upstream_source_sha256=digest(source),
        artifact_sha256={path.relative_to(target).as_posix(): digest(path) for path in paths},
        original_failure_replaced=False,
        native_post_paper_review_revision_available=False,
        extra_model_calls_for_packaging=0,
    )
    runtime = ProjectRuntime(project.parent.parent)
    runtime.register_paper(
        project.name,
        manifest,
        directory_name=paper_id,
        expected_revision=runtime.open(project.name).manifest.revision,
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--paper-id", required=True)
    args = parser.parse_args()
    print(package(args.project, args.run, args.paper_id))

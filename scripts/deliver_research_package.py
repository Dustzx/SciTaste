"""Render and register a hash-bound package revision without selecting the main paper."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project.research_artifact import register_artifact


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--publish-project-documents", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    package = args.package.resolve(strict=True)
    package.relative_to(project / "evaluations")
    complete = json.loads((package / "synthesis/COMPLETE.json").read_text())
    if complete["evidence_sha256"] != digest(package / "FINAL_REPORT.json"):
        raise ValueError("Evidence no longer matches the completed synthesis")
    revision = package / "synthesis/REVISION.md"
    receipt = json.loads((package / "synthesis/REVISION_RECEIPT.json").read_text())
    if revision.read_text() != receipt["output_payload"]["markdown"] + "\n":
        raise ValueError("Revision differs from the retained model response")
    target = project / "papers" / f"{package.name}-research-report"
    if target.exists():
        raise FileExistsError("Preserve existing report delivery")
    files = materialize_manuscript(
        markdown_path=revision, target_dir=target, evidence_audited=False
    )
    delivery = target / "DELIVERY.json"
    retain_json(
        delivery,
        {
            "package": package.relative_to(project).as_posix(),
            "evidence_sha256": complete["evidence_sha256"],
            "revision_receipt_sha256": digest(package / "synthesis/REVISION_RECEIPT.json"),
            "artifacts": {p.relative_to(project).as_posix(): digest(p) for p in files},
            "scientific_approval": False,
            "formal_evidence_eligible": False,
            "main_paper_replaced": False,
            "scope": "Development research report candidate; not a submission manuscript",
        },
    )
    revision_number = register_artifact(
        project=project,
        artifact=delivery,
        provider=receipt["backend"],
        model=receipt["model"],
        condition="research-package-report-review-revision",
        status="report-candidate-delivered",
        run_id=target.name,
    )
    print(json.dumps({"delivery": str(delivery), "project_revision": revision_number}))
    if args.publish_project_documents:
        from scitaste.project.package_progress import publish_package_progress

        print(json.dumps(publish_package_progress(project, package)))


if __name__ == "__main__":
    main()

import hashlib
import json

import pytest

from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.project.documents import INDEX, load_documents, publish_documents
from scitaste.project.package_progress import publish_package_progress


def test_delivery_projection_is_idempotent_and_rejects_drift(tmp_path):
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="package-demo",
            title="Demo",
            research_direction="Research",
            target_domain="research",
            status="active",
        )
    )
    project = runtime.projects_root / "package-demo"
    package = project / "evaluations/package-one"
    paper = project / "papers/package-one-research-report"

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    evidence_sha = write(
        package / "FINAL_REPORT.json",
        {
            "task": {},
            "formal_evidence_eligible": False,
            "result_sha256": {},
            "package_type": "single-system-scientific-followup",
            "total_session_responses": 6,
            "provider_api_calls": 0,
            "rows": [
                {
                    "arm": "native",
                    "attempts": [
                        {
                            "status": "SUCCEEDED",
                            "primary_value": 0.07,
                            "execution_seconds": 10,
                            "cost_complete": True,
                            "replica_receipts": 10,
                        }
                    ],
                }
            ],
        },
    )
    write(package / "PLAN.json", {})
    write(
        package / "synthesis/COMPLETE.json",
        {
            "evidence_sha256": evidence_sha,
            "stages_completed": 3,
        },
    )
    receipt_sha = write(
        package / "synthesis/REVISION_RECEIPT.json",
        {
            "output_payload": {"markdown": "Revised report"},
        },
    )
    write(package / "synthesis/REVISION.md", "Revised report\n")
    write(package / "synthesis/REVIEW.md", "Review")
    artifacts = {
        f"papers/{paper.name}/{name}": write(paper / name, "test fixture")
        for name in ("main.pdf", "main.tex")
    }
    write(
        paper / "DELIVERY.json",
        {
            "package": "evaluations/package-one",
            "evidence_sha256": evidence_sha,
            "revision_receipt_sha256": receipt_sha,
            "artifacts": artifacts,
            "formal_evidence_eligible": False,
            "main_paper_replaced": False,
        },
    )
    before = load_documents(project)
    publish_package_progress(project, package)
    current = load_documents(project)
    assert "0.07" in current.summary
    assert current.phases[0] == before.phases[0]
    raw = (project / INDEX).read_bytes()
    revision = runtime.open(project.name).revision
    publish_package_progress(project, package)
    assert (project / INDEX).read_bytes() == raw
    assert runtime.open(project.name).revision == revision
    with pytest.raises(ValueError, match="changed during publication"):
        publish_documents(runtime, current, expected_index_sha256="stale")
    write(paper / "main.pdf", "changed")
    with pytest.raises(ValueError, match="artifact changed"):
        publish_package_progress(project, package)
    assert (project / INDEX).read_bytes() == raw

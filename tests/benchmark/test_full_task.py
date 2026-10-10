from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.benchmark.full_task import (
    STAGES,
    FullResearchTask,
    FullTaskOutcome,
    FullTaskSuite,
    ProvenanceReceipt,
    TaskArtifact,
    TaskBudget,
    audit_full_task_release,
    export_public_full_task_suite,
)


def _artifact(root: Path, name: str, role: str, content: str | None = None) -> dict:
    data = (content or f"test-only fixture bytes for {name}").encode()
    (root / name).write_bytes(data)
    return {
        "artifact_id": name,
        "path": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "role": role,
    }


def _receipt(root: Path, name: str, subject: str, scope: str, hashes: list[str]) -> dict:
    receipt = ProvenanceReceipt(
        subject_id=subject,
        scope=scope,
        status="verified",
        reviewer_id="test-reviewer",
        evidence_locator="test-only independent-review fixture",
        bound_artifact_sha256=hashes,
    )
    role = "rights_receipt" if scope == "redistribution_rights" else "verification_receipt"
    return _artifact(root, name, role, receipt.model_dump_json())


def _suite(root: Path) -> FullTaskSuite:
    source = _artifact(root, "source.txt", "source")
    problem = _artifact(root, "problem.md", "problem")
    implementation = _artifact(root, "implementation.py", "implementation")
    environment = _artifact(root, "environment.lock", "environment")
    framework_source = _artifact(root, "framework-source.txt", "framework_source")
    scorer = _artifact(root, "private-scorer.py", "scorer")
    reference = _artifact(root, "private-reference.json", "hidden_reference")
    verification = _receipt(root, "source-check.json", "family-a", "source", [source["sha256"]])
    rights = _receipt(root, "rights.json", "family-a", "redistribution_rights", [source["sha256"]])
    treatments = []
    receipts = []
    for framework, role in (
        ("external", "primary_external_framework"),
        ("scitaste", "primary_scitaste"),
    ):
        receipt = _receipt(
            root,
            f"{framework}-check.json",
            f"{framework}@pinned-revision",
            "implementation",
            [a["sha256"] for a in (framework_source, implementation, environment)],
        )
        receipts.append(receipt)
        treatments.append(
            {
                "treatment_id": framework,
                "comparison_role": role,
                "implementation": {
                    "framework_id": framework,
                    "repository_url": f"https://example.org/{framework}",
                    "revision": "pinned-revision",
                    "source_artifact_id": framework_source["artifact_id"],
                    "implementation_artifact_id": implementation["artifact_id"],
                    "environment_artifact_id": environment["artifact_id"],
                    "verification_receipt_id": receipt["artifact_id"],
                    "origin": "real_source",
                    "entrypoint": "python implementation.py",
                },
            }
        )
    task = FullResearchTask(
        task_id="research-a",
        title="Test fixture, not actual benchmark data",
        domain="test",
        split="formal",
        source_families=[
            {
                "family_id": "family-a",
                "source_locator": "https://example.org/source-a",
                "source_artifact_ids": [source["artifact_id"]],
                "exposure": "held_out",
                "rights": "redistributable",
                "license_or_permission": "fixture-only permission",
                "rights_receipt_id": rights["artifact_id"],
                "verification": "source_verified",
                "verification_receipt_id": verification["artifact_id"],
            }
        ],
        agent_visible_artifacts=[source, problem, implementation, environment, framework_source],
        scorer_private_artifacts=[scorer, reference, verification, rights, *receipts],
        budget={
            "experimental_subject": "training_free",
            "wall_seconds": 120,
            "cpu_seconds": 240,
            "memory_gib": 2,
            "gpu_count": 0,
            "gpu_seconds": 0,
            "gpu_memory_gib": 0,
            "model_tokens": 1000,
            "model_calls": 10,
            "experiment_count": 2,
            "monetary_usd": 0,
            "subject_training_steps": 0,
        },
        deliverables={stage: f"required {stage} evidence" for stage in STAGES},
        treatments=treatments,
        primary_endpoint="registered full-task assessment",
        scorer_artifact_id=scorer["artifact_id"],
        scoring_protocol_artifact_id=reference["artifact_id"],
    )
    return FullTaskSuite(suite_id="test-suite", tasks=[task])


def _changed(suite: FullTaskSuite, mutate) -> FullTaskSuite:
    data = suite.model_dump(mode="json")
    mutate(data)
    return FullTaskSuite.model_validate(data)


def test_release_requires_bytes_and_does_not_certify_scientific_quality(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    assert not audit_full_task_release(suite).ready
    audit = audit_full_task_release(suite, tmp_path)
    assert audit.ready, audit.blockers
    assert audit.scientific_quality_certified is False
    (tmp_path / "source.txt").write_text("tampered")
    assert any("digest_mismatch" in b for b in audit_full_task_release(suite, tmp_path).blockers)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exposure", "development_exposed"),
        ("exposure", "unknown"),
        ("verification", "proxy_only"),
        ("verification", "unverified"),
        ("rights", "unresolved"),
        ("rights", "authorized_local_only"),
        ("verification_receipt_id", None),
        ("rights_receipt_id", None),
    ],
)
def test_release_rejects_unqualified_sources(tmp_path: Path, field: str, value: str | None) -> None:
    suite = _changed(
        _suite(tmp_path), lambda d: d["tasks"][0]["source_families"][0].update({field: value})
    )
    assert not audit_full_task_release(suite, tmp_path).ready
    with pytest.raises(ValueError, match="release blocked"):
        export_public_full_task_suite(suite, tmp_path)


def test_source_family_and_content_development_overlap(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    for update in (
        {"development_family_ids": ["family-a"]},
        {"development_source_sha256": [suite.tasks[0].agent_visible_artifacts[0].sha256]},
    ):
        changed = _changed(suite, lambda d, update=update: d.update(update))
        assert not audit_full_task_release(changed, tmp_path).ready


def test_lineage_exposure_is_transitive(tmp_path: Path) -> None:
    suite = _suite(tmp_path)

    def mutate(data):
        task = data["tasks"][0]
        original = task["source_families"][0]
        original["upstream_family_ids"] = ["parent"]
        task["source_families"].extend(
            [
                {**original, "family_id": "parent", "upstream_family_ids": ["grandparent"]},
                {**original, "family_id": "grandparent", "upstream_family_ids": []},
            ]
        )
        data["development_family_ids"] = ["grandparent"]

    audit = audit_full_task_release(_changed(suite, mutate), tmp_path)
    assert "research-a: exposed_or_unknown_family:family-a" in audit.blockers


def test_receipts_must_bind_real_sources_and_implementation(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    changed = _changed(
        suite,
        lambda d: d["tasks"][0]["treatments"][0]["implementation"].update({"origin": "proxy"}),
    )
    assert any("not_real_source" in b for b in audit_full_task_release(changed, tmp_path).blockers)
    changed = _changed(
        suite,
        lambda d: d["tasks"][0]["treatments"][0]["implementation"].update(
            {"revision": "different-source-revision"}
        ),
    )
    assert any(
        "unbound_or_unverified" in b for b in audit_full_task_release(changed, tmp_path).blockers
    )


@pytest.mark.parametrize("alias", ["path", "sha256"])
def test_public_private_aliases_block_release(tmp_path: Path, alias: str) -> None:
    suite = _changed(
        _suite(tmp_path),
        lambda d: d["tasks"][0]["agent_visible_artifacts"][0].update(
            {alias: d["tasks"][0]["scorer_private_artifacts"][0][alias]}
        ),
    )
    assert "public_private_artifact_overlap" in audit_full_task_release(suite, tmp_path).blockers


def test_public_export_omits_private_paths_digests_and_receipts(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    payload = json.dumps(export_public_full_task_suite(suite, tmp_path))
    for artifact in suite.tasks[0].scorer_private_artifacts:
        assert artifact.path not in payload
        assert artifact.sha256 not in payload
    assert "scorer_private_artifacts" not in payload
    assert "verification_receipt_id" not in payload


def test_no_gpu_and_training_subject_budgets_are_distinct(tmp_path: Path) -> None:
    budget = _suite(tmp_path).tasks[0].budget.model_dump()
    assert TaskBudget.model_validate(budget).gpu_count == 0
    budget.update(experimental_subject="training_based", subject_training_steps=100)
    assert TaskBudget.model_validate(budget).controller_adaptation == "training_free"
    budget.update(gpu_seconds=1)
    with pytest.raises(ValidationError, match="no-GPU"):
        TaskBudget.model_validate(budget)


def test_internal_ablation_cannot_replace_external_primary(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    with pytest.raises(ValidationError, match="requires external-framework"):
        _changed(
            suite,
            lambda d: d["tasks"][0]["treatments"][0].update(
                {"comparison_role": "internal_ablation", "ablates_treatment_id": "scitaste"}
            ),
        )


def test_unfinished_and_failed_outcomes_never_impute_zero() -> None:
    fields = {"task_id": "task", "treatment_id": "scitaste", "run_id": "run"}
    assert FullTaskOutcome(**fields, status="unfinished").score is None
    assert FullTaskOutcome(**fields, status="failed", reason="timeout").score is None
    with pytest.raises(ValidationError, match="cannot have a score"):
        FullTaskOutcome(**fields, status="failed", reason="timeout", score=0)
    with pytest.raises(ValidationError, match="actual experiment evidence"):
        FullTaskOutcome(**fields, status="scored", score=0)


def test_real_zero_score_requires_complete_stage_evidence(tmp_path: Path) -> None:
    roles = ("problem", "execution_trace", "paper", "feedback", "revision")
    evidence = [
        {"stage": stage, "artifact": _artifact(tmp_path, f"{stage}.txt", role)}
        for stage, role in zip(STAGES, roles, strict=True)
    ]
    outcome = FullTaskOutcome(
        task_id="task",
        treatment_id="scitaste",
        run_id="run",
        status="scored",
        lifecycle_status="complete",
        score_scope="full_task",
        score=0,
        stage_evidence=evidence,
        score_receipt=_artifact(tmp_path, "score.json", "score_receipt"),
    )
    assert outcome.score == 0
    data = outcome.model_dump()
    data["stage_evidence"] = data["stage_evidence"][:-1]
    with pytest.raises(ValidationError, match="all stages"):
        FullTaskOutcome.model_validate(data)


def test_endpoint_score_survives_incomplete_paper_lifecycle(tmp_path: Path) -> None:
    outcome = FullTaskOutcome(
        task_id="task",
        treatment_id="scitaste",
        run_id="run",
        status="scored",
        score=0.75,
        stage_evidence=[
            {"stage": "problem", "artifact": _artifact(tmp_path, "problem.md", "problem")},
            {
                "stage": "experiment",
                "artifact": _artifact(tmp_path, "trace.json", "execution_trace"),
            },
        ],
        score_receipt=_artifact(tmp_path, "score.json", "score_receipt"),
    )
    assert outcome.lifecycle_status == "incomplete"
    assert outcome.score_scope == "experimental_endpoint"
    assert outcome.score == 0.75
    assert outcome.observed_usage.model_tokens is None
    assert outcome.observed_usage.monetary_usd is None
    assert outcome.observed_usage.model_calls is None
    with pytest.raises(ValidationError, match="complete lifecycle"):
        FullTaskOutcome.model_validate({**outcome.model_dump(), "score_scope": "full_task"})


def test_reused_framework_code_does_not_taint_scientific_task_families(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    framework = next(
        a for a in suite.tasks[0].agent_visible_artifacts if a.role == "framework_source"
    )
    suite = _changed(
        suite,
        lambda d: d.update(
            {
                "development_source_sha256": [framework.sha256],
                "development_family_ids": ["reused-scitaste-code"],
            }
        ),
    )
    audit = audit_full_task_release(suite, tmp_path)
    assert audit.ready, audit.blockers


@pytest.mark.parametrize(
    "role", ["execution_trace", "paper", "feedback", "revision", "score_receipt"]
)
def test_results_cannot_enter_initial_public_requests(tmp_path: Path, role: str) -> None:
    suite = _suite(tmp_path)
    result = _artifact(tmp_path, "forbidden-result.txt", role)
    suite = _changed(suite, lambda d: d["tasks"][0]["agent_visible_artifacts"].append(result))
    audit = audit_full_task_release(suite, tmp_path)
    assert "research-a: non_request_role_exposed:forbidden-result.txt" in audit.blockers
    with pytest.raises(ValueError, match="release blocked"):
        export_public_full_task_suite(suite, tmp_path)


@pytest.mark.parametrize("path", ["../secret", "/secret", "folder/../secret", "a\\b", "a//b"])
def test_artifact_paths_cannot_escape_root(path: str) -> None:
    with pytest.raises(ValidationError, match="canonical relative"):
        TaskArtifact(artifact_id="a", path=path, sha256="0" * 64, role="source")


def test_symlink_escape_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    suite = _suite(root)
    outside = tmp_path / "outside"
    outside.write_text("outside source")
    (root / "source.txt").unlink()
    (root / "source.txt").symlink_to(outside)
    assert any("escapes_root" in b for b in audit_full_task_release(suite, root).blockers)

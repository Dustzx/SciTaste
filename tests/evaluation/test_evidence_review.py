from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    inspect_evidence_review_package,
    load_evidence_review_package,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "configs/evaluation/programs/iclr2027_evidence_review_package_v1.yaml"
LIFECYCLE_PACKAGE = (
    ROOT
    / "configs/evaluation/programs/iclr2027_lifecycle_evidence_review_package_v2.yaml"
)


def test_repository_review_package_is_exact_but_never_execution_ready() -> None:
    inspection = load_evidence_review_package(PACKAGE)

    report = inspect_evidence_review_package(inspection, workspace_root=ROOT)

    assert report.scientifically_coherent is True
    assert report.exact_bindings_verified is True
    assert report.source_proposal_coverage_complete is True
    assert report.method_proposal_coverage_complete is True
    assert report.ready_for_owner_review is True
    assert report.ready_for_experiment is False
    assert report.requested_metadata_item_count == 21
    assert report.maximum_requested_metadata_bytes == 8 * 1024 * 1024
    assert report.unresolved_experiment_blocker_count == 14
    assert report.findings == ()
    assert report.authorizes_download is False
    assert report.authorizes_repository_checkout is False
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False
    assert report.authorizes_human_recruitment is False
    assert report.authorizes_execution is False
    statuses = {item.system_id: item for item in report.method_statuses}
    assert statuses["agent-laboratory"].proposal_viable is True
    assert statuses["deep-scientist"].proposal_viable is True
    assert statuses["ai-researcher"].proposal_viable is False
    assert statuses["ai-researcher"].resource_gate_blockers == ("blocked_gate:code_license",)
    assert all(not item.ready_for_adapter_implementation for item in statuses.values())


def test_lifecycle_review_package_is_exact_but_does_not_inherit_authority() -> None:
    inspection = load_evidence_review_package(LIFECYCLE_PACKAGE)

    report = inspect_evidence_review_package(inspection, workspace_root=ROOT)

    assert report.scientifically_coherent is True
    assert report.exact_bindings_verified is True
    assert report.source_proposal_coverage_complete is True
    assert report.method_proposal_coverage_complete is True
    assert report.ready_for_owner_review is True
    assert report.ready_for_experiment is False
    assert report.findings == ()
    assert report.authorizes_execution is False


def test_review_package_fails_closed_on_bound_file_drift() -> None:
    inspection = load_evidence_review_package(PACKAGE)
    first = inspection.package.source_proposals[0]
    drifted = first.model_copy(update={"file_sha256": "0" * 64})
    package = inspection.package.model_copy(
        update={"source_proposals": (drifted, *inspection.package.source_proposals[1:])}
    )

    report = inspect_evidence_review_package(
        inspection.model_copy(update={"package": package}),
        workspace_root=ROOT,
    )

    assert report.exact_bindings_verified is False
    assert report.ready_for_owner_review is False
    assert any(item.code.endswith("file-hash-mismatch") for item in report.findings)


def test_review_report_rejects_forged_readiness_and_totals() -> None:
    inspection = load_evidence_review_package(PACKAGE)
    report = inspect_evidence_review_package(inspection, workspace_root=ROOT)
    payload = report.model_dump(mode="json")
    payload["ready_for_owner_review"] = False
    with pytest.raises(ValidationError, match="owner-review readiness"):
        type(report).model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["maximum_requested_metadata_bytes"] -= 1
    with pytest.raises(ValidationError, match="byte ceiling"):
        type(report).model_validate(payload)


def test_evidence_review_cli_exposes_bounded_owner_decision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        [
            "evaluation",
            "evidence-review",
            "--manifest",
            str(PACKAGE),
            "--workspace-root",
            str(ROOT),
            "--require-owner-review-ready",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready_for_owner_review"] is True
    assert payload["ready_for_experiment"] is False
    assert payload["requested_metadata_item_count"] == 21
    assert payload["authorizes_execution"] is False
    assert payload["no_external_action_performed"] is True

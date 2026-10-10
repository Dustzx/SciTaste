"""Bind one Native paper's public confirmation receipts, never private labels."""

import json
from pathlib import Path

from scitaste.benchmark.confirmation_binding import (
    confirmation_directory,
    native_confirmation_source,
)
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def native_confirmation_evidence(project: Path, source: Path, destination: Path):
    """Return bounded own-arm evidence; do not rescore or promote development data."""
    root = project.resolve(strict=True)
    source = source.resolve(strict=True)
    source.relative_to(root / "evaluations")
    origin = source / "CONTRACT.json"
    launch = json.loads(origin.read_text())
    binding = launch.get("plan", {}).get("campaign")
    if not binding:
        return ()
    campaign = verified_asset(root, binding)
    contract = json.loads(campaign.read_text())
    if not contract.get("pack") or not contract.get("researcher_assets"):
        return ()
    assignments = json.loads((campaign.parent / "ASSIGNMENTS.json").read_text())
    assignment = assignments.get("scitaste-native")
    locator = assignment.get("run") if isinstance(assignment, dict) else assignment
    declared = source / "CONFIRMATION_ASSIGNMENT.json"
    if declared.is_file():
        descriptor = json.loads(declared.read_bytes())
        registry = verified_asset(root, descriptor["assignments"])
        registry.relative_to(campaign.parent)
        if (
            descriptor["campaign_sha256"] != digest(campaign)
            or descriptor["source_contract_sha256"] != digest(origin)
            or descriptor["original_assignments_sha256"]
            != digest(campaign.parent / "ASSIGNMENTS.json")
            or descriptor.get("original_failure_replaced") is not False
        ):
            raise ValueError("Explicit Native recovery confirmation assignment changed")
        assignment = json.loads(registry.read_bytes())["scitaste-native"]
        if assignment["run"] != source.relative_to(root).as_posix():
            raise ValueError("Native recovery assignment belongs to a different report run")
        evidence_source = native_confirmation_source(root, campaign, source, assignment)
        origin = evidence_source / "CONTRACT.json"
        locator = evidence_source.relative_to(root).as_posix()
    elif locator != source.relative_to(root).as_posix():
        # An explicitly assigned startup recovery may own the only confirmation.
        # Do not infer this from a similar directory name or replace the original
        # failed assignment. Every descriptor preimage must remain exact.
        recovery_path = source / "STARTUP_RECOVERY_BINDING.json"
        if not recovery_path.is_file():
            raise ValueError("Paper confirmation belongs to a different Native run")
        recovery = json.loads(recovery_path.read_text())
        failure_path = campaign.parent / "STARTUP_FAILURE.json"
        assignment_path = campaign.parent / "RECOVERY_ASSIGNMENTS.json"
        failure = json.loads(failure_path.read_text())
        if (
            recovery.get("campaign_sha256") != digest(campaign)
            or recovery.get("source_contract_sha256") != digest(origin)
            or recovery.get("original_assignments_sha256")
            != digest(campaign.parent / "ASSIGNMENTS.json")
            or recovery.get("recovery_assignments_sha256") != digest(assignment_path)
            or recovery.get("startup_failure_sha256") != digest(failure_path)
            or failure.get("status") != "pre-model-startup-failed"
            or failure.get("consumed_model_responses") != 0
            or failure.get("research_actions") != 0
            or failure.get("original_run") != locator
        ):
            raise ValueError("Startup recovery assignment binding changed")
        assignment = json.loads(assignment_path.read_text()).get("scitaste-native")
        locator = assignment.get("run") if isinstance(assignment, dict) else assignment
        if locator != source.relative_to(root).as_posix():
            raise ValueError("Recovery confirmation belongs to a different Native run")
    owned = confirmation_directory(root, campaign, "scitaste-native", assignment)
    receipt = owned / "RESULT.json"
    if not receipt.is_file():
        return ()
    feedback = json.loads(receipt.read_text())
    if feedback.get("arm") != "scitaste-native":
        raise ValueError("Paper confirmation belongs to a different arm")
    executed = feedback.get("executed_frozen_source", False)
    files = [receipt]
    if executed:
        execution_path = owned / "EXECUTION_CONTRACT.json"
        execution = json.loads(execution_path.read_text())
        inference_path = owned / "INFERENCE_RESULT.json"
        inference = json.loads(inference_path.read_text())
        if (
            feedback.get("status") != "completed"
            or execution.get("campaign_sha256") != digest(campaign)
            or execution.get("source_run") != locator
            or execution.get("source_contract_sha256") != digest(origin)
            or feedback.get("execution_contract_sha256") != digest(execution_path)
            or feedback.get("inference_result_sha256") != digest(inference_path)
            or inference.get("execution_contract_sha256") != digest(execution_path)
            or inference.get("release_sha256") != digest(owned / "release/RELEASE.json")
            or inference.get("return_code") != 0
        ):
            raise ValueError("Paper confirmation receipt binding changed")
        before_scoring = inference.get("before_private_scoring", False)
        if inference.get("pre_score_inference_sha256"):
            joint_path = owned / "execution/INFERENCE_RESULT.json"
            joint = json.loads(joint_path.read_text())
            before_scoring = bool(
                digest(joint_path) == inference["pre_score_inference_sha256"]
                and joint.get("before_private_scoring")
                and joint.get("budget_isolation_verified")
                and joint.get("return_code") == 0
                and joint.get("release_sha256") == inference["release_sha256"]
                and joint.get("output_sha256") == inference.get("output_sha256")
            )
        if not before_scoring:
            raise ValueError("Paper confirmation has no bound pre-scoring execution")
        release = owned / "release"
        frozen = (release / "frozen_submission").resolve(strict=True)
        for name, expected in json.loads((release / "RELEASE.json").read_text())[
            "frozen_source"
        ].items():
            path = frozen / name
            path.resolve(strict=True).relative_to(frozen)
            if path.is_symlink() or digest(path) != expected:
                raise ValueError("Paper confirmation source changed after freeze")
        prediction_root = (owned / "execution/predictions").resolve(strict=True)
        for name, expected in inference["output_sha256"].items():
            path = prediction_root / name
            resolved = path.resolve(strict=True)
            resolved.relative_to(prediction_root)
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                raise ValueError("Paper confirmation prediction changed")
        files.append(inference_path)
    # Scoring alone cannot attest execution; service receipts can. Neither grants
    # scientific approval, venue readiness, statistical superiority or learning.
    summary = {
        "schema_version": "1.0",
        "scope": "own-arm public confirmation provenance for paper review and revision",
        "campaign_sha256": digest(campaign),
        "source_run": locator,
        "source_contract_sha256": digest(origin),
        "status": feedback["status"],
        "executed_frozen_source": executed,
        "formal_evidence_eligible": False,
        "scientific_approval": False,
        "scope_instructions": (
            "A successful bound service execution verifies the frozen procedure. "
            "A score-only source_execution_verified=false flag does not negate that receipt. "
            "Formal admission and scientific quality remain separate; do not infer "
            "superiority, novelty, cross-task transfer or venue readiness from execution. "
            "Use the attached result for measurements and retain negative findings."
        ),
        "receipts": {path.relative_to(root).as_posix(): digest(path) for path in files},
    }
    destination = destination.resolve()
    destination.relative_to(root / "evaluations")
    destination.parent.mkdir(parents=True, exist_ok=True)
    retain_json(destination, summary)
    return (*files, destination)

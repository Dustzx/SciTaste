#!/usr/bin/env python3
"""Roll admitted episodes into a collision-free successor policy and E2 handoff.

This deterministic operator is for the narrow case where an earlier append-only
activation campaign published the successor policy identity while a later,
already-reviewed cohort was still running.  It never re-reviews, retries, or
selects episodes: every policy-eligible episode in the supplied review-complete
state is appended to the exact finalized predecessor corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from scitaste.evaluation.adaptive_policy_activation import (
    ActivationFileBinding,
    AdaptivePolicyActivationCampaignState,
    AdaptivePolicyActivationFinalizationResult,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_state,
    save_adaptive_policy_activation_artifact,
)
from scitaste.evaluation.adaptive_policy_e2_handoff import (
    materialize_adaptive_policy_e2_successor,
)
from scitaste.evaluation.h4_state_probe import (
    H4FrozenStateProbeContract,
    inspect_h4_state_probe_manipulation,
    save_h4_state_probe_contract,
    save_h4_state_probe_report,
)
from scitaste.project.idea_revision import (
    idea_scientific_contract_sha256,
    inspect_current_idea_revision,
)
from scitaste.project.models import content_sha256
from scitaste.project.runtime import ProjectRuntime
from scitaste.state.resources import ResourceBudget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.episode_learning import LifecycleTastePolicyConfig
from scitaste.taste.intervention import lifecycle_policy_training_corpus_sha256
from scitaste.taste.project_policy import (
    ProjectTastePolicyReadiness,
    load_project_taste_policy_corpus,
    materialize_project_taste_policy_refresh,
    save_project_taste_policy_corpus,
    seal_project_taste_policy_corpus,
)


def execute(args: argparse.Namespace) -> dict[str, object]:
    workspace = args.workspace_root.resolve(strict=True)
    outputs_root = args.outputs_root.resolve(strict=True)
    output_dir = args.output_directory.resolve()
    e2_output_dir = args.e2_output_directory.resolve()
    for target in (output_dir, e2_output_dir):
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)

    manifest, _ = load_adaptive_policy_activation_manifest(args.manifest)
    base_state = load_adaptive_policy_activation_state(args.base_state)
    evidence_state = load_adaptive_policy_activation_state(args.evidence_state)
    if base_state.status != "finalized" or base_state.finalization is None:
        raise ValueError("roll-forward base must be one exact finalized activation state")
    if evidence_state.status != "review-complete" or evidence_state.finalization is not None:
        raise ValueError("roll-forward evidence must be one exact review-complete state")
    if (
        base_state.project_id != manifest.project_id
        or evidence_state.project_id != manifest.project_id
        or evidence_state.campaign_id != manifest.campaign_id
        or base_state.finalization.target_e2_manifest_id
        != manifest.activation_gate.target_e2_manifest_id
        or base_state.finalization.target_e2_manifest_sha256
        != manifest.activation_gate.target_e2_manifest.sha256
    ):
        raise ValueError("roll-forward states do not share the approved project and E2 target")

    eligible = tuple(
        item for item in evidence_state.review_evidence if item.status == "policy-eligible"
    )
    if len(eligible) != evidence_state.admitted_episode_count or not eligible:
        raise ValueError("roll-forward state has inconsistent or empty admitted evidence")
    if any(
        item.assigned_family is not ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
        or item.admission is None
        or item.family_assignment is None
        for item in eligible
    ):
        raise ValueError("roll-forward admits only reviewed adaptive-allocation episodes")

    runtime = ProjectRuntime(outputs_root)
    snapshot = runtime.open(manifest.project_id)
    project_root = runtime.projects_root / manifest.project_id
    idea = inspect_current_idea_revision(runtime, manifest.project_id).current_binding
    if idea is None:
        raise ValueError("roll-forward current Idea is unavailable")

    base = base_state.finalization
    predecessor_corpus = load_project_taste_policy_corpus(
        _bound_path(workspace, base.corpus.locator)
    )
    predecessor_config = LifecycleTastePolicyConfig.model_validate_json(
        _bound_path(workspace, base.policy_config.locator).read_bytes(), strict=True
    )
    episode_paths = [project_root / item.admission_locator for item in predecessor_corpus.episodes]
    assignment_paths = [
        project_root / item.assignment_locator for item in predecessor_corpus.episodes
    ]
    for item in eligible:
        assert item.admission is not None
        assert item.family_assignment is not None
        episode_paths.append(_bound_path(workspace, item.admission.locator))
        assignment_paths.append(_bound_path(workspace, item.family_assignment.locator))

    successor_id = args.successor_policy_id
    corpus_id = f"{successor_id}-corpus"
    corpus_path = project_root / "taste" / "policy" / "corpora" / f"{corpus_id}.json"
    config_path = project_root / "taste" / "policy" / "inputs" / f"{successor_id}.json"
    refresh_dir = project_root / "taste" / "policy" / "refreshes" / f"{successor_id}-refresh"
    for target in (corpus_path, config_path, refresh_dir):
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)

    corpus = seal_project_taste_policy_corpus(
        runtime,
        project_id=manifest.project_id,
        corpus_id=corpus_id,
        episode_paths=tuple(episode_paths),
        assignment_paths=tuple(assignment_paths),
        expected_project_revision=snapshot.revision,
    )
    save_project_taste_policy_corpus(corpus, corpus_path)
    config = predecessor_config.model_copy(
        update={
            "policy_id": f"{successor_id}-base",
            "idea_revision": idea,
            "minimum_feature_support": manifest.policy_refresh.minimum_feature_support,
            "allow_cross_domain": manifest.policy_refresh.allow_cross_domain,
        }
    )
    config = LifecycleTastePolicyConfig.model_validate(config.model_dump(mode="python"))
    save_adaptive_policy_activation_artifact(config, config_path)
    materialize_project_taste_policy_refresh(
        runtime,
        corpus,
        config,
        refresh_id=f"{successor_id}-refresh",
        policy_id=successor_id,
        expected_project_revision=runtime.open(manifest.project_id).revision,
        output_directory=refresh_dir,
    )
    policy_path = refresh_dir / "POLICY.json"
    readiness_path = refresh_dir / "READINESS.json"
    refresh_path = refresh_dir / "REFRESH.json"
    policy = FamilyConditionedLifecycleTastePolicy.model_validate_json(
        policy_path.read_bytes(), strict=True
    )
    readiness = ProjectTastePolicyReadiness.model_validate_json(
        readiness_path.read_bytes(), strict=True
    )
    adaptive = next(
        item
        for item in readiness.families
        if item.decision_family is ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
    )

    output_dir.mkdir(parents=True)
    contract_binding = None
    report_binding = None
    probe_status = "not-run-insufficient-support"
    if adaptive.adaptive_head_ready:
        head = policy.require_head(ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION)
        controller = TasteController(
            seed=manifest.activation_gate.state_probe_seed,
            mode=TasteMode.INTRINSIC,
            critics_enabled=False,
            lifecycle_policy=head,
            lifecycle_policy_weight=0.0,
        )
        contract = H4FrozenStateProbeContract.create(
            contract_id=f"{manifest.campaign_id}-{successor_id}-rollforward-probe",
            project_id=manifest.project_id,
            evaluation_id=manifest.activation_gate.target_e2_manifest_id,
            evaluation_bundle_sha256=manifest.activation_gate.target_e2_manifest.sha256,
            plan_sha256=evidence_state.plan_sha256,
            lifecycle_policy_sha256=head.policy_sha256,
            policy_training_corpus_sha256=lifecycle_policy_training_corpus_sha256(head),
            idea_scientific_contract_sha256=idea_scientific_contract_sha256(idea),
            controller_backbone_sha256=controller.intervention_backbone_sha256,
            maximum_failed_experiments=(
                manifest.activation_gate.state_probe_maximum_failed_experiments
            ),
            seed=manifest.activation_gate.state_probe_seed,
            resource_budget=ResourceBudget(
                max_experiments=manifest.activation_gate.state_probe_maximum_experiments
            ),
            research_direction=manifest.activation_gate.state_probe_research_direction,
            target_domain=manifest.activation_gate.target_domain,
            target_venue=manifest.activation_gate.target_venue,
        )
        report = inspect_h4_state_probe_manipulation(
            contract,
            head,
            current_idea_revision=idea,
        )
        contract_path = output_dir / "H4_STATE_PROBE_CONTRACT.json"
        report_path = output_dir / "H4_STATE_PROBE_REPORT.json"
        save_h4_state_probe_contract(contract, contract_path)
        save_h4_state_probe_report(report, report_path)
        contract_binding = _binding(workspace, contract_path)
        report_binding = _binding(workspace, report_path)
        probe_status = "passed" if report.passed else "failed"

    ready = adaptive.adaptive_head_ready and probe_status == "passed"
    result = AdaptivePolicyActivationFinalizationResult.create(
        campaign_id=manifest.campaign_id,
        project_id=manifest.project_id,
        plan_sha256=evidence_state.plan_sha256,
        preceding_state_sha256=evidence_state.state_sha256,
        successor_policy_id=successor_id,
        target_e2_manifest_id=manifest.activation_gate.target_e2_manifest_id,
        target_e2_manifest_sha256=manifest.activation_gate.target_e2_manifest.sha256,
        activation_episode_count=evidence_state.admitted_episode_count,
        total_corpus_episode_count=len(corpus.episodes),
        corpus=_binding(workspace, corpus_path),
        policy_config=_binding(workspace, config_path),
        refresh_receipt=_binding(workspace, refresh_path),
        policy=_binding(workspace, policy_path),
        readiness=_binding(workspace, readiness_path),
        state_probe_contract=contract_binding,
        state_probe_report=report_binding,
        adaptive_family_support_sufficient=adaptive.support_sufficient,
        adaptive_head_ready=adaptive.adaptive_head_ready,
        policy_refresh_status=("ready" if adaptive.adaptive_head_ready else "insufficient-support"),
        target_domain_state_probe_status=probe_status,
        activation_ready_for_e2_development=ready,
    )
    result_path = output_dir / "FINALIZATION.json"
    state_path = output_dir / "FINALIZED_STATE.json"
    save_adaptive_policy_activation_artifact(result, result_path)
    finalized = _finalized_state(evidence_state, result)
    save_adaptive_policy_activation_artifact(finalized, state_path)

    handoff = None
    if ready:
        predecessor = _bound_path(workspace, manifest.activation_gate.target_e2_manifest.locator)
        _, inspection, receipt, manifest_path = materialize_adaptive_policy_e2_successor(
            manifest,
            result,
            finalized,
            predecessor_manifest_path=predecessor,
            output_directory=e2_output_dir,
            workspace_root=workspace,
            outputs_root=outputs_root,
            implementation_commit=args.implementation_commit,
            successor_manifest_id=args.successor_manifest_id,
        )
        handoff = {
            "manifest": manifest_path.relative_to(workspace).as_posix(),
            "manifest_sha256": receipt.successor_manifest_sha256,
            "receipt_sha256": receipt.receipt_sha256,
            "ready": inspection.ready_for_development_static_handoff,
        }

    receipt_payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "adaptive-policy-collision-rollforward",
        "campaign_id": manifest.campaign_id,
        "base_state_sha256": base_state.state_sha256,
        "evidence_state_sha256": evidence_state.state_sha256,
        "successor_policy_id": successor_id,
        "eligible_result_sha256s": [item.result_sha256 for item in eligible],
        "finalization_result_sha256": result.result_sha256,
        "finalized_state_sha256": finalized.state_sha256,
        "e2_handoff": handoff,
        "no_model_calls_performed": True,
        "no_api_calls_performed": True,
        "no_gpu_work_performed": True,
    }
    receipt_payload["receipt_sha256"] = content_sha256(receipt_payload)
    _write_json(receipt_payload, output_dir / "ROLLFORWARD.json")
    return receipt_payload


def _finalized_state(
    state: AdaptivePolicyActivationCampaignState,
    result: AdaptivePolicyActivationFinalizationResult,
) -> AdaptivePolicyActivationCampaignState:
    payload = state.model_dump(
        mode="python",
        exclude={
            "state_sha256",
            "tasks",
            "terminal_evidence",
            "review_evidence",
            "finalization",
        },
    )
    payload.update(
        {
            "tasks": state.tasks,
            "terminal_evidence": state.terminal_evidence,
            "review_evidence": state.review_evidence,
            "sequence": state.sequence + 1,
            "status": "finalized",
            "policy_refresh_status": result.policy_refresh_status,
            "target_domain_state_probe_status": result.target_domain_state_probe_status,
            "finalization": result,
        }
    )
    unsigned = AdaptivePolicyActivationCampaignState.model_construct(
        state_sha256="0" * 64, **payload
    )
    return AdaptivePolicyActivationCampaignState(
        **payload,
        state_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"state_sha256"})),
    )


def _bound_path(root: Path, locator: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        raise ValueError(f"roll-forward input cannot be a symlink: {locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"roll-forward input escapes workspace or is not a file: {locator}")
    return resolved


def _binding(workspace: Path, path: Path) -> ActivationFileBinding:
    resolved = path.resolve(strict=True)
    return ActivationFileBinding(
        locator=resolved.relative_to(workspace).as_posix(),
        sha256=_sha256(resolved),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(payload: dict[str, object], path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-state", type=Path, required=True)
    parser.add_argument("--evidence-state", type=Path, required=True)
    parser.add_argument("--successor-policy-id", required=True)
    parser.add_argument("--successor-manifest-id", default=None)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--e2-output-directory", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    return parser


def main() -> None:
    print(json.dumps(execute(build_parser().parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

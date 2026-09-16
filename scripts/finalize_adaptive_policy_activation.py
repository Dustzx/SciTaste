#!/usr/bin/env python3
"""Refresh the declared successor policy and run its target-domain state probe."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from scitaste.evaluation.adaptive_policy_activation import (
    ActivationFileBinding,
    AdaptivePolicyActivationFinalizationResult,
    complete_adaptive_policy_activation_finalization,
    inspect_adaptive_policy_activation,
    load_adaptive_policy_activation_approval,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_no_run_plan,
    load_adaptive_policy_activation_state,
    save_adaptive_policy_activation_artifact,
    validate_adaptive_policy_activation_finalization_authority,
    validate_adaptive_policy_activation_idea_binding,
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


def execute(args: argparse.Namespace):
    for output in (args.result_output, args.state_output):
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
    workspace = args.workspace_root.resolve(strict=True)
    outputs_root = args.outputs_root.resolve(strict=True)
    manifest, manifest_file_sha256 = load_adaptive_policy_activation_manifest(args.manifest)
    plan = load_adaptive_policy_activation_no_run_plan(args.plan)
    approval = load_adaptive_policy_activation_approval(args.approval)
    state = load_adaptive_policy_activation_state(args.state)
    inspection = inspect_adaptive_policy_activation(
        manifest,
        manifest_file_sha256=manifest_file_sha256,
        workspace_root=workspace,
    )
    if (
        not inspection.ready_for_owner_approval
        or inspection.manifest_file_sha256 != plan.manifest_file_sha256
        or inspection.manifest_fingerprint != plan.manifest_fingerprint
        or inspection.idea_revision_id != plan.idea_revision_id
        or inspection.idea_scientific_contract_sha256 != plan.idea_scientific_contract_sha256
    ):
        raise ValueError("activation finalization static or Idea binding changed")
    validate_adaptive_policy_activation_finalization_authority(manifest, plan, approval, state)
    validate_adaptive_policy_activation_idea_binding(plan, outputs_root=outputs_root)

    runtime = ProjectRuntime(outputs_root)
    snapshot = runtime.open(manifest.project_id)
    project_root = runtime.projects_root / manifest.project_id
    idea = inspect_current_idea_revision(runtime, manifest.project_id).current_binding
    if idea is None:
        raise ValueError("activation finalization current Idea is unavailable")

    predecessor_policy_path = _bound_path(workspace, manifest.predecessor.family_policy.locator)
    predecessor_corpus_path = predecessor_policy_path.parent / "CORPUS_MANIFEST.json"
    predecessor_config_path = predecessor_policy_path.parent / "POLICY_CONFIG.json"
    predecessor_corpus = load_project_taste_policy_corpus(predecessor_corpus_path)
    predecessor_config = LifecycleTastePolicyConfig.model_validate_json(
        predecessor_config_path.read_bytes(), strict=True
    )
    episode_paths = [project_root / item.admission_locator for item in predecessor_corpus.episodes]
    assignment_paths = [
        project_root / item.assignment_locator for item in predecessor_corpus.episodes
    ]
    for item in state.review_evidence:
        if item.status != "policy-eligible":
            continue
        if item.admission is None or item.family_assignment is None:
            raise ValueError("eligible activation review lacks policy artifacts")
        episode_paths.append(_bound_path(workspace, item.admission.locator))
        assignment_paths.append(_bound_path(workspace, item.family_assignment.locator))

    # Activation campaigns are append-only.  Binding the corpus name to the
    # declared successor policy prevents a completed campaign from occupying a
    # fixed global filename needed by every later campaign.
    corpus_id = f"{manifest.policy_refresh.successor_policy_id}-corpus"
    corpus = seal_project_taste_policy_corpus(
        runtime,
        project_id=manifest.project_id,
        corpus_id=corpus_id,
        episode_paths=tuple(episode_paths),
        assignment_paths=tuple(assignment_paths),
        expected_project_revision=snapshot.revision,
    )
    corpus_path = project_root / "taste" / "policy" / "corpora" / f"{corpus_id}.json"
    config_path = (
        project_root
        / "taste"
        / "policy"
        / "inputs"
        / f"{manifest.policy_refresh.successor_policy_id}.json"
    )
    refresh_dir = (
        project_root
        / "taste"
        / "policy"
        / "refreshes"
        / f"{manifest.policy_refresh.successor_policy_id}-refresh"
    )
    for target in (corpus_path, config_path, refresh_dir):
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
    save_project_taste_policy_corpus(corpus, corpus_path)
    config = predecessor_config.model_copy(
        update={
            "policy_id": f"{manifest.policy_refresh.successor_policy_id}-base",
            "idea_revision": idea,
            "minimum_feature_support": manifest.policy_refresh.minimum_feature_support,
            "allow_cross_domain": manifest.policy_refresh.allow_cross_domain,
        }
    )
    config = LifecycleTastePolicyConfig.model_validate(config.model_dump(mode="python"))
    save_adaptive_policy_activation_artifact(config, config_path)
    refresh = materialize_project_taste_policy_refresh(
        runtime,
        corpus,
        config,
        refresh_id=f"{manifest.policy_refresh.successor_policy_id}-refresh",
        policy_id=manifest.policy_refresh.successor_policy_id,
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

    activation_root = (
        project_root / "evaluations" / "taste-policy-activation" / manifest.campaign_id
    )
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
            contract_id=f"{manifest.campaign_id}-h4-state-probe",
            project_id=manifest.project_id,
            evaluation_id=manifest.activation_gate.target_e2_manifest_id,
            evaluation_bundle_sha256=manifest.activation_gate.target_e2_manifest.sha256,
            plan_sha256=plan.plan_sha256,
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
        contract_path = activation_root / "H4_STATE_PROBE_CONTRACT.json"
        report_path = activation_root / "H4_STATE_PROBE_REPORT.json"
        save_h4_state_probe_contract(contract, contract_path)
        save_h4_state_probe_report(report, report_path)
        contract_binding = _binding(workspace, contract_path)
        report_binding = _binding(workspace, report_path)
        probe_status = "passed" if report.passed else "failed"

    policy_status = "ready" if adaptive.adaptive_head_ready else "insufficient-support"
    result = AdaptivePolicyActivationFinalizationResult.create(
        campaign_id=manifest.campaign_id,
        project_id=manifest.project_id,
        plan_sha256=plan.plan_sha256,
        preceding_state_sha256=state.state_sha256,
        successor_policy_id=manifest.policy_refresh.successor_policy_id,
        target_e2_manifest_id=manifest.activation_gate.target_e2_manifest_id,
        target_e2_manifest_sha256=manifest.activation_gate.target_e2_manifest.sha256,
        activation_episode_count=state.admitted_episode_count,
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
        policy_refresh_status=policy_status,
        target_domain_state_probe_status=probe_status,
        activation_ready_for_e2_development=(
            adaptive.adaptive_head_ready and probe_status == "passed"
        ),
    )
    save_adaptive_policy_activation_artifact(result, args.result_output)
    finalized = complete_adaptive_policy_activation_finalization(
        manifest,
        plan,
        approval,
        state,
        result,
        workspace_root=workspace,
    )
    save_adaptive_policy_activation_artifact(finalized, args.state_output)
    return result, finalized, refresh


def _bound_path(root: Path, locator: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        raise ValueError(f"activation input cannot be a symlink: {locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"activation input escapes workspace or is not a file: {locator}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    return parser


def main() -> None:
    result, state, refresh = execute(build_parser().parse_args())
    print(
        json.dumps(
            {
                "status": state.status,
                "policy_id": result.successor_policy_id,
                "policy_sha256": refresh.policy_sha256,
                "policy_refresh_status": result.policy_refresh_status,
                "target_domain_state_probe_status": (result.target_domain_state_probe_status),
                "activation_ready_for_e2_development": (result.activation_ready_for_e2_development),
                "result_sha256": result.result_sha256,
                "state_sha256": state.state_sha256,
                "external_execution_performed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

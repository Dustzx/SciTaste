#!/usr/bin/env python3
"""Reproject a frozen adaptive policy after a state-adapter semantics upgrade.

This operator does not add, remove, re-review, or resample scientific episodes.
It changes only the predeclared application semantics, freezes a new policy
identity, runs the outcome-blind target-domain probe, and materializes an E2
successor only when that probe passes.
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
    state = load_adaptive_policy_activation_state(args.state)
    if state.status != "finalized" or state.finalization is None:
        raise ValueError("policy reprojection requires one exact finalized activation state")
    if state.project_id != manifest.project_id or state.campaign_id != manifest.campaign_id:
        raise ValueError("policy reprojection manifest and state differ")
    previous = state.finalization
    if previous.policy_refresh_status != "ready":
        raise ValueError("policy reprojection requires a fitted predecessor policy")

    runtime = ProjectRuntime(outputs_root)
    project_root = runtime.projects_root / manifest.project_id
    idea = inspect_current_idea_revision(runtime, manifest.project_id).current_binding
    if idea is None:
        raise ValueError("policy reprojection current Idea is unavailable")
    corpus = load_project_taste_policy_corpus(_bound_path(workspace, previous.corpus))
    old_config = LifecycleTastePolicyConfig.model_validate_json(
        _bound_path(workspace, previous.policy_config).read_bytes(), strict=True
    )

    successor_id = args.successor_policy_id
    config_path = project_root / "taste" / "policy" / "inputs" / f"{successor_id}.json"
    refresh_dir = project_root / "taste" / "policy" / "refreshes" / f"{successor_id}-refresh"
    for target in (config_path, refresh_dir):
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
    config = old_config.model_copy(
        update={
            "policy_id": f"{successor_id}-base",
            "idea_revision": idea,
            "feature_precedence": "rich-decision-context-first-v2",
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
    if not adaptive.adaptive_head_ready:
        raise ValueError("reprojected adaptive policy head is not ready")

    head = policy.require_head(ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION)
    controller = TasteController(
        seed=manifest.activation_gate.state_probe_seed,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        lifecycle_policy=head,
        lifecycle_policy_weight=0.0,
    )
    contract = H4FrozenStateProbeContract.create(
        contract_id=f"{manifest.campaign_id}-{successor_id}-reprojection-probe",
        project_id=manifest.project_id,
        evaluation_id=manifest.activation_gate.target_e2_manifest_id,
        evaluation_bundle_sha256=manifest.activation_gate.target_e2_manifest.sha256,
        plan_sha256=state.plan_sha256,
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
    if not report.passed:
        raise ValueError("reprojected target-domain state probe did not pass")

    output_dir.mkdir(parents=True)
    contract_path = output_dir / "H4_STATE_PROBE_CONTRACT.json"
    report_path = output_dir / "H4_STATE_PROBE_REPORT.json"
    save_h4_state_probe_contract(contract, contract_path)
    save_h4_state_probe_report(report, report_path)
    result = AdaptivePolicyActivationFinalizationResult.create(
        campaign_id=manifest.campaign_id,
        project_id=manifest.project_id,
        plan_sha256=state.plan_sha256,
        preceding_state_sha256=state.state_sha256,
        successor_policy_id=successor_id,
        target_e2_manifest_id=manifest.activation_gate.target_e2_manifest_id,
        target_e2_manifest_sha256=manifest.activation_gate.target_e2_manifest.sha256,
        activation_episode_count=state.admitted_episode_count,
        total_corpus_episode_count=len(corpus.episodes),
        corpus=previous.corpus,
        policy_config=_binding(workspace, config_path),
        refresh_receipt=_binding(workspace, refresh_dir / "REFRESH.json"),
        policy=_binding(workspace, policy_path),
        readiness=_binding(workspace, readiness_path),
        state_probe_contract=_binding(workspace, contract_path),
        state_probe_report=_binding(workspace, report_path),
        adaptive_family_support_sufficient=adaptive.support_sufficient,
        adaptive_head_ready=adaptive.adaptive_head_ready,
        policy_refresh_status="ready",
        target_domain_state_probe_status="passed",
        activation_ready_for_e2_development=True,
    )
    reprojected_state = _reprojected_state(state, result)
    save_adaptive_policy_activation_artifact(result, output_dir / "FINALIZATION.json")
    save_adaptive_policy_activation_artifact(
        reprojected_state, output_dir / "FINALIZED_STATE.json"
    )

    _, inspection, handoff, manifest_path = materialize_adaptive_policy_e2_successor(
        manifest,
        result,
        reprojected_state,
        predecessor_manifest_path=_bound_path(
            workspace, manifest.activation_gate.target_e2_manifest
        ),
        output_directory=e2_output_dir,
        workspace_root=workspace,
        outputs_root=outputs_root,
        implementation_commit=args.implementation_commit,
        successor_manifest_id=args.successor_manifest_id,
    )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "adaptive-policy-state-reprojection",
        "campaign_id": manifest.campaign_id,
        "predecessor_policy_id": previous.successor_policy_id,
        "successor_policy_id": successor_id,
        "training_corpus_sha256": lifecycle_policy_training_corpus_sha256(head),
        "feature_precedence": config.feature_precedence,
        "probe_report_sha256": report.report_sha256,
        "probe_passed": report.passed,
        "e2_manifest": manifest_path.relative_to(workspace).as_posix(),
        "e2_manifest_sha256": handoff.successor_manifest_sha256,
        "e2_static_handoff_ready": inspection.ready_for_development_static_handoff,
        "no_episode_selection_performed": True,
        "no_model_calls_performed": True,
        "no_api_calls_performed": True,
        "no_gpu_work_performed": True,
        "no_hidden_scores_opened": True,
    }
    payload["receipt_sha256"] = content_sha256(payload)
    _write_json(payload, output_dir / "REPROJECTION.json")
    return payload


def _reprojected_state(
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
            "policy_refresh_status": "ready",
            "target_domain_state_probe_status": "passed",
            "finalization": result,
        }
    )
    unsigned = AdaptivePolicyActivationCampaignState.model_construct(
        state_sha256="0" * 64, **payload
    )
    return AdaptivePolicyActivationCampaignState(
        **payload,
        state_sha256=content_sha256(
            unsigned.model_dump(mode="json", exclude={"state_sha256"})
        ),
    )


def _bound_path(root: Path, binding: ActivationFileBinding) -> Path:
    candidate = root.joinpath(*PurePosixPath(binding.locator).parts)
    if candidate.is_symlink():
        raise ValueError(f"policy reprojection binding cannot be a symlink: {binding.locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"policy reprojection binding escapes workspace: {binding.locator}")
    if _sha256(resolved) != binding.sha256:
        raise ValueError(f"policy reprojection binding hash changed: {binding.locator}")
    return resolved


def _binding(root: Path, path: Path) -> ActivationFileBinding:
    resolved = path.resolve(strict=True)
    return ActivationFileBinding(
        locator=resolved.relative_to(root).as_posix(),
        sha256=_sha256(resolved),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--successor-policy-id", required=True)
    parser.add_argument("--successor-manifest-id", required=True)
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

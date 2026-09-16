#!/usr/bin/env python3
"""Run one issued adaptive-allocation review chain and advance campaign state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from time import monotonic

from scitaste.backends.local_transformers import load_local_transformers_config
from scitaste.evaluation.adaptive_policy_activation import (
    ActivationFileBinding,
    AdaptivePolicyActivationReviewResult,
    complete_adaptive_policy_activation_review,
    inspect_adaptive_policy_activation,
    load_adaptive_policy_activation_approval,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_no_run_plan,
    load_adaptive_policy_activation_review_permit,
    load_adaptive_policy_activation_state,
    save_adaptive_policy_activation_artifact,
    validate_adaptive_policy_activation_idea_binding,
    validate_adaptive_policy_activation_review_authority,
)
from scitaste.evaluation.evidence_review import load_evidence_review_package
from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.openai_compatible import (
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.project.idea_revision import inspect_current_idea_revision
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.ai_attribution import (
    ai_review_authority_sha256,
    build_ai_taste_attribution_review_material,
    build_ai_taste_attribution_runtime_config,
    materialize_ai_taste_attribution_review,
    save_ai_reviewed_episode_json,
    save_runtime_config,
)
from scitaste.taste.episode_learning import (
    TasteAttributionReviewRole,
    admit_taste_episode,
    inspect_taste_episode_admission,
    load_ai_taste_review_panel_contract,
)
from scitaste.taste.episodes import TasteEpisodeCandidate
from scitaste.taste.family_review import (
    build_scientific_decision_family_review_material,
    build_scientific_decision_family_runtime_config,
    compile_scientific_decision_family_assignment,
    scientific_decision_family_review_from_runtime,
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
    permit = load_adaptive_policy_activation_review_permit(args.permit)
    review_mode = manifest.review_and_admission.attribution_primary_models[0].execution_mode
    if review_mode == "local" and not args.allow_local:
        raise ValueError("activation local review requires explicit --allow-local")
    if review_mode == "live" and not args.allow_live:
        raise ValueError("activation live review requires explicit --allow-live")
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
        raise ValueError("activation review static or Idea binding changed after approval")
    validate_adaptive_policy_activation_review_authority(
        manifest,
        plan,
        approval,
        state,
        permit,
        workspace_root=workspace,
    )
    validate_adaptive_policy_activation_idea_binding(plan, outputs_root=outputs_root)

    project_runtime = ProjectRuntime(outputs_root)
    project_root = project_runtime.projects_root / permit.project_id
    run_root = project_root / "runs" / permit.run_id
    candidate_path = _bound_path(workspace, permit.candidate.locator)
    candidate = TasteEpisodeCandidate.model_validate_json(candidate_path.read_bytes(), strict=True)
    review_root = (
        project_root
        / "runs"
        / permit.run_id
        / "adaptive_policy_activation"
        / "reviews"
        / candidate.candidate_id
    )
    if review_root.exists() or review_root.is_symlink():
        raise FileExistsError(
            f"activation review evidence already exists and cannot be rerun: {review_root}"
        )
    # The candidate and trajectory were already charged by the task permit.
    # Review accounting owns only the fresh, candidate-scoped evidence tree;
    # scanning the whole long-lived project would both double-count prior runs
    # and make unrelated historical reference symlinks block local review.
    initial_review_bytes = 0
    contract_path = _bound_path(workspace, manifest.review_and_admission.review_contract.locator)
    authority_path = _bound_path(
        workspace, manifest.review_and_admission.review_authority_package.locator
    )
    contract = load_ai_taste_review_panel_contract(contract_path)
    authority = load_evidence_review_package(authority_path)
    authority_sha256 = ai_review_authority_sha256(
        authority,
        panel_contract=contract,
        workspace_root=workspace,
    )
    idea = inspect_current_idea_revision(project_runtime, permit.project_id).current_binding
    if idea is None:
        raise ValueError("activation review current Idea is unavailable")

    attempted = 0
    local_seconds = 0.0
    live_input_tokens = 0
    live_output_tokens = 0
    live_cost_usd = 0.0
    attribution_reviews = []
    attribution_bindings: list[ActivationFileBinding] = []
    family_reviews = []
    family_bindings: list[ActivationFileBinding] = []
    admission = None
    admission_binding = None
    assignment = None
    assignment_binding = None
    terminal_status = "runtime-failure"
    failure_reason: str | None = None

    try:
        for panel_index, model in enumerate(
            manifest.review_and_admission.attribution_primary_models, start=1
        ):
            model_slug = _slug(model.model_id)
            campaign_code = hashlib.sha256(manifest.campaign_id.encode()).hexdigest()[:10]
            invocation_id = (
                f"activation-{campaign_code}-{permit.ordinal:02d}-attribution-{model_slug}"
            )
            output_dir = review_root / "attribution" / model_slug
            config_path = review_root / "runtime_configs" / f"attribution-{model_slug}.json"
            profile, backend = _review_runtime_inputs(workspace, model)
            material = build_ai_taste_attribution_review_material(
                project_runtime,
                candidate,
                evidence_root=run_root,
                current_idea_revision=idea,
                # Both primary reviewers must see the exact same frozen packet.
                # Reviewer diversity comes from the independently configured
                # models, not from changing the evidence projection.
                seed=0,
                evidence_projection_mode="interactive-trajectory-compact-v1",
            )
            config = build_ai_taste_attribution_runtime_config(
                material,
                profile=profile,
                backend_config=backend,
            )
            save_runtime_config(config, config_path)
            attempted += 1
            started = monotonic()
            facade_result = _execute_runtime_config(
                project_runtime,
                permit.run_id,
                invocation_id,
                config,
                profile,
                review_mode=review_mode,
            )
            local_seconds += monotonic() - started
            if review_mode == "live":
                live_input_tokens += facade_result.receipt.telemetry.input_tokens
                live_output_tokens += facade_result.receipt.telemetry.output_tokens
                live_cost_usd += float(facade_result.receipt.telemetry.cost_usd or 0.0)
            if facade_result.receipt.outcome is not RuntimeOutcome.ACCEPTED:
                if (
                    review_mode == "live"
                    and facade_result.receipt.telemetry.input_tokens == 0
                    and facade_result.receipt.telemetry.output_tokens == 0
                ):
                    live_input_tokens = permit.maximum_live_total_tokens
                    live_output_tokens = 0
                    live_cost_usd = permit.maximum_live_cost_usd
                raise RuntimeError(
                    f"attribution generation {panel_index} ended "
                    f"{facade_result.receipt.outcome.value}"
                )
            review, review_path = materialize_ai_taste_attribution_review(
                project_runtime,
                candidate,
                project_id=permit.project_id,
                run_id=permit.run_id,
                invocation_id=invocation_id,
                review_id=f"activation-{permit.ordinal:02d}-attribution-{model_slug}",
                reviewer_id=f"activation-{model_slug}-attribution",
                role=TasteAttributionReviewRole.PRIMARY,
                panel_contract=contract,
                evidence_root=run_root,
                output_directory=output_dir.relative_to(run_root).as_posix(),
            )
            attribution_reviews.append(review)
            attribution_bindings.append(_binding(workspace, review_path))

        admission_report = inspect_taste_episode_admission(
            candidate,
            tuple(attribution_reviews),
            evidence_root=run_root,
            current_idea_revision=idea,
            ai_review_contract=contract,
            expected_ai_review_contract_sha256=authority_sha256,
        )
        if not admission_report.ready_for_policy_training:
            terminal_status = "attribution-panel-not-admitted"
        else:
            admission = admit_taste_episode(
                candidate,
                tuple(attribution_reviews),
                admission_id=f"activation-{permit.ordinal:02d}-{candidate.candidate_id}",
                evidence_root=run_root,
                current_idea_revision=idea,
                ai_review_contract=contract,
                expected_ai_review_contract_sha256=authority_sha256,
            )
            admission_path = review_root / "ADMISSION.json"
            save_ai_reviewed_episode_json(admission, admission_path)
            admission_binding = _binding(workspace, admission_path)

        if admission is not None:
            for panel_index, model in enumerate(
                manifest.review_and_admission.attribution_primary_models, start=1
            ):
                model_slug = _slug(model.model_id)
                invocation_id = (
                    f"activation-{campaign_code}-{permit.ordinal:02d}-family-{model_slug}"
                )
                output_dir = review_root / "family" / model_slug
                config_path = review_root / "runtime_configs" / f"family-{model_slug}.json"
                profile, backend = _review_runtime_inputs(workspace, model)
                material = build_scientific_decision_family_review_material(
                    project_runtime,
                    admission,
                    current_idea_revision=idea,
                )
                config = build_scientific_decision_family_runtime_config(
                    material,
                    profile=profile,
                    backend_config=backend,
                )
                save_runtime_config(config, config_path)
                attempted += 1
                started = monotonic()
                facade_result = _execute_runtime_config(
                    project_runtime,
                    permit.run_id,
                    invocation_id,
                    config,
                    profile,
                    review_mode=review_mode,
                )
                local_seconds += monotonic() - started
                if review_mode == "live":
                    live_input_tokens += facade_result.receipt.telemetry.input_tokens
                    live_output_tokens += facade_result.receipt.telemetry.output_tokens
                    live_cost_usd += float(facade_result.receipt.telemetry.cost_usd or 0.0)
                if facade_result.receipt.outcome is not RuntimeOutcome.ACCEPTED:
                    if (
                        review_mode == "live"
                        and facade_result.receipt.telemetry.input_tokens == 0
                        and facade_result.receipt.telemetry.output_tokens == 0
                    ):
                        live_input_tokens = permit.maximum_live_total_tokens
                        live_output_tokens = 0
                        live_cost_usd = permit.maximum_live_cost_usd
                    raise RuntimeError(
                        f"family generation {panel_index} ended "
                        f"{facade_result.receipt.outcome.value}"
                    )
                family_review = scientific_decision_family_review_from_runtime(
                    project_runtime,
                    admission,
                    project_id=permit.project_id,
                    run_id=permit.run_id,
                    invocation_id=invocation_id,
                    reviewer_id=f"activation-{model_slug}-family",
                    role="primary",
                )
                family_path = output_dir / "REVIEW.json"
                save_ai_reviewed_episode_json(family_review, family_path)
                family_reviews.append(family_review)
                family_bindings.append(_binding(workspace, family_path))
            if len({item.decision_family for item in family_reviews}) != 1:
                terminal_status = "family-panel-unresolved"
            else:
                assignment = compile_scientific_decision_family_assignment(
                    admission,
                    tuple(family_reviews),
                    assignment_id=f"activation-{permit.ordinal:02d}-family",
                )
                assignment_path = review_root / "FAMILY_ASSIGNMENT.json"
                save_ai_reviewed_episode_json(assignment, assignment_path)
                assignment_binding = _binding(workspace, assignment_path)
                terminal_status = "policy-eligible"
    except Exception as exc:
        if attempted == 0:
            raise
        terminal_status = "runtime-failure"
        failure_reason = f"{type(exc).__name__}: {exc}"[:2000]

    if attempted == 0:
        raise RuntimeError("activation review produced no local generation attempt")
    local_gpu_hours = local_seconds / 3600.0 if review_mode == "local" else 0.0
    new_disk_bytes = max(0, _tree_bytes(review_root) - initial_review_bytes)
    result = AdaptivePolicyActivationReviewResult.create(
        schema_version=manifest.schema_version,
        permit_sha256=permit.permit_sha256,
        task_id=permit.task_id,
        run_id=permit.run_id,
        candidate_sha256=permit.candidate_sha256,
        status=terminal_status,
        local_generation_count=attempted if review_mode == "local" else 0,
        local_gpu_hours=local_gpu_hours,
        live_generation_count=attempted if review_mode == "live" else 0,
        live_input_tokens=live_input_tokens,
        live_output_tokens=live_output_tokens,
        live_cost_usd=live_cost_usd,
        new_disk_bytes=new_disk_bytes,
        attribution_reviews=tuple(attribution_bindings),
        admission=admission_binding,
        family_reviews=tuple(family_bindings),
        family_assignment=assignment_binding,
        assigned_family=None if assignment is None else assignment.decision_family,
        failure_reason=failure_reason,
    )
    save_adaptive_policy_activation_artifact(result, args.result_output)
    advanced = complete_adaptive_policy_activation_review(
        manifest,
        plan,
        approval,
        state,
        permit,
        result,
        workspace_root=workspace,
    )
    save_adaptive_policy_activation_artifact(advanced, args.state_output)
    return result, advanced


def _review_runtime_inputs(workspace: Path, model):
    profile_set = load_model_node_profile_set(_bound_path(workspace, model.profile_set.locator))
    try:
        profile = profile_set.profiles[model.profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown activation review profile {model.profile_id!r}") from exc
    backend_path = _bound_path(workspace, model.backend.locator)
    backend = (
        load_local_transformers_config(backend_path)
        if model.execution_mode == "local"
        else load_structured_openai_compatible_config(backend_path)
    )
    return profile, backend


def _execute_runtime_config(
    runtime,
    run_id,
    invocation_id,
    config,
    profile,
    *,
    review_mode,
):
    request = ModelNodeFacadeRequest(
        project_id=config.state_projection.project_id,
        run_id=run_id,
        invocation_id=invocation_id,
        request_id=config.request_id,
        expected_project_revision=runtime.open(config.state_projection.project_id).revision,
        node_name=config.node_name,
        node_input=config.node_input,
        state_projection=config.state_projection,
        trigger=config.trigger,
        profile=profile,
        policy=config.policy,
        backend_mode=config.backend_mode,
        seed=config.seed,
    )
    facade = ModelNodeFacade(ModelNodeRuntime(runtime, node_types=first_party_node_types()))
    return facade.execute(
        request,
        backend=config.build_backend(invocation_id),
        allow_local=review_mode == "local",
        allow_live=review_mode == "live",
    )


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
    locator = resolved.relative_to(workspace).as_posix()
    return ActivationFileBinding(locator=locator, sha256=_sha256(resolved))


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"activation project evidence cannot contain a symlink: {path}")
        if path.is_file():
            total += path.stat().st_size
    return total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    return parser


def main() -> None:
    result, state = execute(build_parser().parse_args())
    print(
        json.dumps(
            {
                "status": result.status,
                "task_id": result.task_id,
                "local_generation_count": result.local_generation_count,
                "local_gpu_hours": result.local_gpu_hours,
                "result_sha256": result.result_sha256,
                "state_status": state.status,
                "state_sha256": state.state_sha256,
                "next_review_task_id": state.next_review_task_id,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run one strong closed-model review chain from the action-diverse corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

import yaml

from scitaste.evaluation.action_diverse_taste_development import (
    ActionDiverseCurationReceipt,
    load_action_diverse_curation_plan,
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
from scitaste.project.models import content_sha256
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

_MAX_MANIFEST_BYTES = 2 * 1_048_576
_MAX_BOUND_BYTES = 64 * 1_048_576


def execute(args: argparse.Namespace) -> dict[str, object]:
    if not args.allow_live:
        raise ValueError("strong review requires explicit --allow-live")
    if args.result_output.exists() or args.result_output.is_symlink():
        raise FileExistsError(args.result_output)
    workspace = args.workspace_root.resolve(strict=True)
    outputs_root = args.outputs_root.resolve(strict=True)
    manifest_path = _bounded(args.manifest, _MAX_MANIFEST_BYTES)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise ValueError("invalid strong-review manifest")
    project_id = str(manifest["project_id"])
    campaign_id = str(manifest["review_campaign_id"])
    campaign_code = f"sr-{hashlib.sha256(campaign_id.encode()).hexdigest()[:10]}"
    candidate_count = int(manifest["candidate_count"])
    if not 1 <= args.ordinal <= candidate_count:
        raise ValueError("strong-review ordinal is outside the frozen corpus")
    if int(manifest["maximum_provider_retries"]) != 0:
        raise ValueError("strong-review campaign must prohibit provider retries")

    plan_path = _bound(workspace, manifest["curation_plan"])
    receipt_path = _bound(workspace, manifest["curation_receipt"])
    plan = load_action_diverse_curation_plan(plan_path)
    receipt = ActionDiverseCurationReceipt.model_validate_json(
        receipt_path.read_bytes(), strict=True
    )
    if (
        plan.plan_sha256 != manifest["curation_plan"]["artifact_sha256"]
        or receipt.receipt_sha256 != manifest["curation_receipt"]["artifact_sha256"]
        or receipt.plan_sha256 != plan.plan_sha256
        or len(receipt.candidates) != candidate_count
    ):
        raise ValueError("strong-review curation binding differs")

    candidate_binding = receipt.candidates[args.ordinal - 1]
    candidate_path = _bound(workspace, candidate_binding.candidate.model_dump(mode="json"))
    candidate = TasteEpisodeCandidate.model_validate_json(
        candidate_path.read_bytes(), strict=True
    )
    if candidate.candidate_sha256 != candidate_binding.candidate_sha256:
        raise ValueError("strong-review candidate semantic hash differs")

    runtime = ProjectRuntime(outputs_root)
    idea = inspect_current_idea_revision(runtime, project_id).current_binding
    if idea is None:
        raise ValueError("strong-review current Idea is unavailable")
    project_root = runtime.projects_root / project_id
    run_root = project_root / "runs" / candidate_binding.run_id
    review_root = (
        run_root
        / "interactive_development"
        / str(manifest["output_stage"])
        / f"candidate-{args.ordinal:02d}"
    )
    if review_root.exists() or review_root.is_symlink():
        raise FileExistsError(review_root)

    profile_set_path = _bound(workspace, manifest["profile_set"])
    profile_set = load_model_node_profile_set(profile_set_path)
    reviewers: list[tuple[dict[str, object], object, object]] = []
    for reviewer in manifest["reviewers"]:
        profile = profile_set.profiles[str(reviewer["profile_id"])]
        backend = load_structured_openai_compatible_config(
            _bound(workspace, reviewer["backend"])
        )
        if (profile.provider, profile.model) != (
            str(reviewer["provider"]),
            str(reviewer["model"]),
        ) or (backend.provider, backend.model) != (profile.provider, profile.model):
            raise ValueError("strong-review model identity differs from its frozen profile")
        if backend.max_retries != 0:
            raise ValueError("strong-review backend permits provider retries")
        reviewers.append((reviewer, profile, backend))
    if len(reviewers) != 2 or len({item[1].model for item in reviewers}) != 2:
        raise ValueError("strong-review panel requires two distinct models")

    contract = load_ai_taste_review_panel_contract(
        _bound(workspace, manifest["review_contract"])
    )
    authority = load_evidence_review_package(
        _bound(workspace, manifest["review_authority_package"])
    )
    authority_sha256 = ai_review_authority_sha256(
        authority,
        panel_contract=contract,
        workspace_root=workspace,
    )
    result: dict[str, object] = {
        "schema_version": "1.0",
        "review_campaign_id": campaign_id,
        "project_id": project_id,
        "ordinal": args.ordinal,
        "curation_plan_sha256": plan.plan_sha256,
        "curation_receipt_sha256": receipt.receipt_sha256,
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": candidate.candidate_sha256,
        "action_type": candidate_binding.action_type,
        "status": "runtime-failure",
        "attempted_generations": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "attribution_reviews": [],
        "admission": None,
        "family_reviews": [],
        "family_assignment": None,
        "assigned_family": None,
        "failure_reason": None,
        "formal_evidence": False,
        "effect_claim_authorized": False,
    }
    try:
        attribution_reviews = []
        for reviewer, profile, backend in reviewers:
            reviewer_id = str(reviewer["reviewer_id"])
            invocation_id = (
                f"{campaign_code}-{args.ordinal:02d}-attribution-{_slug(reviewer_id)}"
            )
            material = build_ai_taste_attribution_review_material(
                runtime,
                candidate,
                evidence_root=run_root,
                current_idea_revision=idea,
                seed=int(manifest["attribution_seed"]),
                evidence_projection_mode=str(manifest["evidence_projection_mode"]),
            )
            config = build_ai_taste_attribution_runtime_config(
                material,
                profile=profile,
                backend_config=backend,
            )
            config_path = review_root / "runtime_configs" / f"attribution-{reviewer_id}.json"
            save_runtime_config(config, config_path)
            facade_result = _execute_runtime_config(
                runtime,
                candidate_binding.run_id,
                invocation_id,
                config,
                profile,
            )
            _accumulate(result, facade_result.receipt)
            if facade_result.receipt.outcome is not RuntimeOutcome.ACCEPTED:
                raise RuntimeError(
                    f"attribution generation {reviewer_id} ended "
                    f"{facade_result.receipt.outcome.value}"
                )
            output_dir = review_root / "attribution" / reviewer_id
            review, review_path = materialize_ai_taste_attribution_review(
                runtime,
                candidate,
                project_id=project_id,
                run_id=candidate_binding.run_id,
                invocation_id=invocation_id,
                review_id=(
                    f"{campaign_code}-{args.ordinal:02d}-attribution-{reviewer_id}"
                ),
                reviewer_id=f"{campaign_code}-{reviewer_id}-attribution",
                role=TasteAttributionReviewRole.PRIMARY,
                panel_contract=contract,
                evidence_root=run_root,
                output_directory=output_dir.relative_to(run_root).as_posix(),
            )
            attribution_reviews.append(review)
            result["attribution_reviews"].append(_file_binding(workspace, review_path))

        admission_report = inspect_taste_episode_admission(
            candidate,
            tuple(attribution_reviews),
            evidence_root=run_root,
            current_idea_revision=idea,
            ai_review_contract=contract,
            expected_ai_review_contract_sha256=authority_sha256,
        )
        if not admission_report.ready_for_policy_training:
            result["status"] = "attribution-panel-not-admitted"
        else:
            admission = admit_taste_episode(
                candidate,
                tuple(attribution_reviews),
                admission_id=(
                    f"{campaign_code}-{args.ordinal:02d}-{candidate.candidate_id}"
                ),
                evidence_root=run_root,
                current_idea_revision=idea,
                ai_review_contract=contract,
                expected_ai_review_contract_sha256=authority_sha256,
            )
            admission_path = review_root / "ADMISSION.json"
            save_ai_reviewed_episode_json(admission, admission_path)
            result["admission"] = _file_binding(workspace, admission_path)

            family_reviews = []
            for reviewer, profile, backend in reviewers:
                reviewer_id = str(reviewer["reviewer_id"])
                invocation_id = (
                    f"{campaign_code}-{args.ordinal:02d}-family-{_slug(reviewer_id)}"
                )
                material = build_scientific_decision_family_review_material(
                    runtime,
                    admission,
                    current_idea_revision=idea,
                )
                config = build_scientific_decision_family_runtime_config(
                    material,
                    profile=profile,
                    backend_config=backend,
                )
                config_path = review_root / "runtime_configs" / f"family-{reviewer_id}.json"
                save_runtime_config(config, config_path)
                facade_result = _execute_runtime_config(
                    runtime,
                    candidate_binding.run_id,
                    invocation_id,
                    config,
                    profile,
                )
                _accumulate(result, facade_result.receipt)
                if facade_result.receipt.outcome is not RuntimeOutcome.ACCEPTED:
                    raise RuntimeError(
                        f"family generation {reviewer_id} ended "
                        f"{facade_result.receipt.outcome.value}"
                    )
                family_review = scientific_decision_family_review_from_runtime(
                    runtime,
                    admission,
                    project_id=project_id,
                    run_id=candidate_binding.run_id,
                    invocation_id=invocation_id,
                    reviewer_id=f"{campaign_code}-{reviewer_id}-family",
                    role="primary",
                )
                family_path = review_root / "family" / reviewer_id / "REVIEW.json"
                save_ai_reviewed_episode_json(family_review, family_path)
                family_reviews.append(family_review)
                result["family_reviews"].append(_file_binding(workspace, family_path))
            if len({item.decision_family for item in family_reviews}) != 1:
                result["status"] = "family-panel-unresolved"
            else:
                assignment = compile_scientific_decision_family_assignment(
                    admission,
                    tuple(family_reviews),
                    assignment_id=f"{campaign_code}-{args.ordinal:02d}-family",
                )
                assignment_path = review_root / "FAMILY_ASSIGNMENT.json"
                save_ai_reviewed_episode_json(assignment, assignment_path)
                result["family_assignment"] = _file_binding(workspace, assignment_path)
                result["assigned_family"] = assignment.decision_family.value
                result["status"] = "policy-eligible"
    except Exception as exc:
        result["failure_reason"] = f"{type(exc).__name__}: {exc}"[:2000]

    result["result_sha256"] = content_sha256(result)
    args.result_output.parent.mkdir(parents=True, exist_ok=True)
    with args.result_output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return result


def _execute_runtime_config(runtime, run_id, invocation_id, config, profile):
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
        allow_live=True,
    )


def _accumulate(result: dict[str, object], receipt) -> None:
    result["attempted_generations"] = int(result["attempted_generations"]) + 1
    result["input_tokens"] = int(result["input_tokens"]) + receipt.telemetry.input_tokens
    result["output_tokens"] = int(result["output_tokens"]) + receipt.telemetry.output_tokens
    result["cost_usd"] = float(result["cost_usd"]) + float(
        receipt.telemetry.cost_usd or 0.0
    )


def _file_binding(workspace: Path, path: Path) -> dict[str, str]:
    source = path.resolve(strict=True)
    if not source.is_relative_to(workspace):
        raise ValueError("strong-review artifact escapes workspace")
    return {
        "locator": source.relative_to(workspace).as_posix(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def _bound(workspace: Path, binding: dict[str, object]) -> Path:
    locator = str(binding["locator"])
    pure = PurePosixPath(locator)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != locator:
        raise ValueError(f"unsafe strong-review locator: {locator}")
    path = _bounded(workspace.joinpath(*pure.parts), _MAX_BOUND_BYTES)
    if hashlib.sha256(path.read_bytes()).hexdigest() != str(binding["sha256"]):
        raise ValueError(f"strong-review binding changed: {locator}")
    return path


def _bounded(path: str | Path, maximum_bytes: int) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"strong-review input must be a regular file: {source}")
    if not 1 <= source.stat().st_size <= maximum_bytes:
        raise ValueError(f"strong-review input exceeds its byte ceiling: {source}")
    return source


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ordinal", required=True, type=int)
    parser.add_argument("--result-output", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--allow-live", action="store_true")
    return parser


def main() -> None:
    result = execute(build_parser().parse_args())
    print(
        f"ordinal={result['ordinal']} status={result['status']} "
        f"generations={result['attempted_generations']} "
        f"tokens={int(result['input_tokens']) + int(result['output_tokens'])} "
        f"cost_usd={float(result['cost_usd']):.6f}"
    )


if __name__ == "__main__":
    main()

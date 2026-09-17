#!/usr/bin/env python3
"""Build a real natural-decision SciTasteBench development suite.

This is a deadline-oriented development runner, not a formal-release compiler.
It keeps action construction outcome-blind, obtains two independent AI proxy
labels after the action set is frozen, and cross-fits Taste precedents by source
group.  Generated artifacts stay under ignored project outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.benchmark.models import (
    BenchmarkCase,
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    BenchmarkLabelAuthority,
    BenchmarkSuite,
)
from scitaste.evaluation.scitastebench_development_intake import (
    DevelopmentOutcomeVaultRecord,
    DevelopmentScreeningItem,
)
from scitaste.evaluation.scitastebench_development_panel import (
    DevelopmentPanelDecisionRecord,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.intrinsic import TasteTask

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ActionOption(BaseModel):
    model_config = _CONFIG

    action_type: MetaAction
    description: str = Field(min_length=1, max_length=800)
    role: str = Field(min_length=1, max_length=120)


class ActionPair(BaseModel):
    model_config = _CONFIG

    position: int = Field(gt=0, le=12)
    option_a: ActionOption
    option_b: ActionOption


class ActionBatch(BaseModel):
    model_config = _CONFIG

    batch_id: str
    decisions: tuple[ActionPair, ...] = Field(min_length=1, max_length=12)
    target_outcomes_used: Literal[False] = False


class UtilityLabel(BaseModel):
    model_config = _CONFIG

    position: int = Field(gt=0, le=12)
    preferred_option: Literal["option-a", "option-b"]
    confidence: float = Field(ge=0.5, le=1.0)
    transferable_principle: str = Field(min_length=1, max_length=700)
    rationale: str = Field(min_length=1, max_length=700)


class UtilityBatch(BaseModel):
    model_config = _CONFIG

    batch_id: str
    decisions: tuple[UtilityLabel, ...] = Field(min_length=1, max_length=12)
    source_outcomes_used: Literal[True] = True
    human_or_expert_label_claimed: Literal[False] = False


def _read_jsonl(path: Path, model: type[BaseModel]) -> dict[str, BaseModel]:
    rows: dict[str, BaseModel] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = model.model_validate_json(line)
        key = str(
            getattr(item, "intake_candidate_id", None)
            or getattr(item, "source_group_id", None)
        )
        rows[key] = item
    return rows


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()


def _batch(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _call(
    *,
    backend: StructuredOpenAICompatibleBackend,
    request_id: str,
    node_name: str,
    instruction: str,
    payload: dict[str, object],
    schema: dict[str, object],
    output_dir: Path,
    seed: int,
) -> dict[str, object]:
    policy_fingerprint = hashlib.sha256(instruction.encode()).hexdigest()
    request = StructuredModelRequest(
        request_id=request_id,
        node_name=node_name,
        stage="benchmark-development",
        state_snapshot_id=content_sha256(payload),
        expected_backend=backend.name,
        expected_model=backend.model,
        policy_id=f"{node_name}-v1",
        policy_fingerprint=policy_fingerprint,
        system_instruction=instruction,
        input_payload=payload,
        output_schema=schema,
        seed=seed,
        prompt_version=f"{node_name}-v1",
    )
    _write_json(output_dir / "request.json", request.model_dump(mode="json"))
    response = backend.complete(request)
    _write_json(output_dir / "response.json", response.model_dump(mode="json"))
    if response.backend != backend.name or response.model != backend.model:
        raise ValueError("provider identity differs from the frozen backend")
    if response.tool_calls:
        raise ValueError("benchmark development calls may not propose tools")
    if not isinstance(response.output_payload, dict):
        raise ValueError("benchmark development response is not an object")
    return response.output_payload


def _visible_payload(
    item: DevelopmentScreeningItem,
    record: DevelopmentPanelDecisionRecord,
) -> dict[str, object]:
    assert record.final_decision is not None
    return {
        "article_title": item.article_title,
        "reviewed_abstract": item.reviewed_abstract,
        "predecision_review_context": item.predecision_review_context,
        "atomic_decision_question": record.final_decision.atomic_decision_question,
        "decision_context_family": record.final_decision.decision_context_family.value,
        "taste_judgment_family": record.final_decision.taste_judgment_family.value,
    }


def _action_instruction() -> str:
    return (
        "Construct exactly two plausible, consequential actions for each outcome-hidden "
        "scientific decision. The alternatives must answer the atomic question, be feasible "
        "from the visible state, differ scientifically rather than stylistically, and avoid "
        "embedding a preferred answer. Use only the allowed MetaAction enum. Return positions "
        "in exact input order. You never see or infer author responses, revisions, later "
        "recommendations, or publication outcomes. Return only the requested JSON object."
    )


def _label_instruction() -> str:
    return (
        "Act as an independent AI proxy labeler for natural scientific decisions. The two "
        "actions were frozen before you received the later source outcome. Select the action "
        "better supported by the observed response, revision, and recommendation while noting "
        "that observed author behavior is a noisy natural proxy, not truth. Low-information "
        "outcomes require confidence near 0.5. Distill one transferable decision principle "
        "that excludes task-specific names and does not mention option identifiers. Return "
        "positions in exact input order. Do not claim human or expert authority. Return only "
        "the requested JSON object."
    )


def _task_and_stage(context_family: str) -> tuple[TasteTask, str]:
    if context_family in {"problem-and-idea-value", "hypothesis-and-falsifiability"}:
        return TasteTask.IDEA, "DISCOVERY"
    if context_family == "experiment-design-and-confound-control":
        return TasteTask.EXPERIMENT, "EXPERIMENT"
    if context_family == "evidence-interpretation-and-contradiction":
        return TasteTask.EVIDENCE, "EVIDENCE"
    if context_family == "resource-allocation-pivot-continue-or-stop":
        return TasteTask.EXPERIMENT, "ADAPTATION"
    return TasteTask.REVIEW, "REVIEW"


def _select_release(
    candidates: list[str],
    records: dict[str, DevelopmentPanelDecisionRecord],
    *,
    release_size: int,
) -> list[str]:
    by_context: dict[str, list[str]] = defaultdict(list)
    for candidate_id in candidates:
        decision = records[candidate_id].final_decision
        assert decision is not None and decision.decision_context_family is not None
        by_context[decision.decision_context_family.value].append(candidate_id)
    selected: list[str] = []
    for family in sorted(by_context):
        ranked = sorted(by_context[family], key=lambda value: _rank("release", value))
        selected.extend(ranked[:6])
    remaining = sorted(set(candidates) - set(selected), key=lambda value: _rank("fill", value))
    selected.extend(remaining[: max(0, release_size - len(selected))])
    return sorted(selected[:release_size], key=lambda value: _rank("order", value))


def _precedent_for(
    target_id: str,
    release: list[str],
    records: dict[str, DevelopmentPanelDecisionRecord],
    *,
    matched: bool,
) -> str:
    target = records[target_id]
    target_decision = target.final_decision
    assert target_decision is not None and target_decision.taste_judgment_family is not None
    candidates = []
    for candidate_id in release:
        if candidate_id == target_id:
            continue
        decision = records[candidate_id].final_decision
        assert decision is not None and decision.taste_judgment_family is not None
        same = decision.taste_judgment_family == target_decision.taste_judgment_family
        if same != matched:
            continue
        cross_domain = records[candidate_id].domain != target.domain
        candidates.append(
            (
                not cross_domain,
                _rank(f"precedent:{target_id}", candidate_id),
                candidate_id,
            )
        )
    if not candidates:
        raise ValueError(f"no {'matched' if matched else 'mismatched'} precedent for {target_id}")
    return min(candidates)[2]


def _manifest_release_ids(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("release_case_ids")
    if not isinstance(values, list) or not values or not all(
        isinstance(item, str) and item for item in values
    ):
        raise ValueError(f"release manifest {path} has no valid release_case_ids")
    if len(values) != len(set(values)):
        raise ValueError(f"release manifest {path} repeats case IDs")
    return tuple(values)


def run(args: argparse.Namespace) -> None:
    root = args.locator_root.resolve(strict=True)
    output = args.output
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)

    screens = _read_jsonl(root / args.screening_items, DevelopmentScreeningItem)
    panel_rows = _read_jsonl(root / args.panel_decisions, DevelopmentPanelDecisionRecord)
    records = {
        candidate_id: row
        for candidate_id, row in panel_rows.items()
        if isinstance(row, DevelopmentPanelDecisionRecord)
        and row.final_decision is not None
        and row.final_decision.eligible
    }
    vault_root = json.loads((root / args.outcome_vault).read_text(encoding="utf-8"))
    outcomes = {
        item["intake_candidate_id"]: DevelopmentOutcomeVaultRecord.model_validate(item)
        for item in vault_root["records"]
    }
    candidate_ids = sorted(records, key=lambda value: _rank("construction", value))
    _write_json(
        output / "PLAN.json",
        {
            "schema_version": "1.0",
            "run_id": args.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "candidate_count": len(candidate_ids),
            "release_size": args.release_size,
            "screening_items_sha256": _sha(root / args.screening_items),
            "panel_decisions_sha256": _sha(root / args.panel_decisions),
            "outcome_vault_sha256": _sha(root / args.outcome_vault),
            "action_construction_outcome_blind": True,
            "label_reviewer_kind": "ai",
            "not_human_review": True,
            "formal_evidence_eligible": False,
        },
    )
    deepseek = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(root / args.action_backend)
    )
    glm = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(root / args.label_backend_a)
    )
    qwen = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(root / args.label_backend_b)
    )

    actions: dict[str, ActionPair] = {}

    def reuse_actions(
        reuse_locator: Path,
        source_candidates: list[str],
        source_batch_size: int,
    ) -> list[dict[str, object]]:
        reuse_root = root / reuse_locator
        reused_batches = _batch(source_candidates, source_batch_size)
        reuse_records = []
        for ordinal, candidate_batch in enumerate(reused_batches, 1):
            response_path = reuse_root / "action-construction" / f"{ordinal:02d}" / "response.json"
            if not response_path.exists():
                continue
            response = json.loads(response_path.read_text(encoding="utf-8"))
            result = ActionBatch.model_validate(response["output_payload"])
            observed_positions: set[int] = set()
            for decision in result.decisions:
                if decision.position in observed_positions or not 1 <= decision.position <= len(
                    candidate_batch
                ):
                    raise ValueError("reused action batch positions differ")
                observed_positions.add(decision.position)
                actions[candidate_batch[decision.position - 1]] = decision
            reuse_records.append(
                {
                    "ordinal": ordinal,
                    "response": str(response_path.relative_to(root)),
                    "response_sha256": _sha(response_path),
                    "candidate_count": len(candidate_batch),
                    "accepted_position_count": len(observed_positions),
                }
            )
        return reuse_records

    reuse_records: list[dict[str, object]] = []
    if args.reuse_action_output is not None:
        reuse_records.extend(
            reuse_actions(
                args.reuse_action_output,
                candidate_ids,
                args.reuse_action_batch_size,
            )
        )
    if args.reuse_pending_action_output is not None:
        source_pending = [item for item in candidate_ids if item not in actions]
        reuse_records.extend(
            reuse_actions(
                args.reuse_pending_action_output,
                source_pending,
                args.reuse_pending_action_batch_size,
            )
        )
    if args.reuse_pending_2_action_output is not None:
        source_pending = [item for item in candidate_ids if item not in actions]
        reuse_records.extend(
            reuse_actions(
                args.reuse_pending_2_action_output,
                source_pending,
                args.reuse_pending_2_action_batch_size,
            )
        )
    if reuse_records:
        _write_json(output / "REUSED_ACTION_BATCHES.json", {"batches": reuse_records})
    pending_action_ids = [item for item in candidate_ids if item not in actions]
    action_batches = _batch(pending_action_ids, args.action_batch_size)
    for ordinal, candidate_batch in enumerate(action_batches, 1):
        batch_id = f"{args.run_id}-actions-{ordinal:02d}"
        items = [
            {"position": position, **_visible_payload(screens[candidate_id], records[candidate_id])}
            for position, candidate_id in enumerate(candidate_batch, 1)
        ]
        payload = _call(
            backend=deepseek,
            request_id=batch_id,
            node_name="scitastebench-action-construction",
            instruction=_action_instruction(),
            payload={"batch_id": batch_id, "items": items, "target_outcomes_visible": False},
            schema=ActionBatch.model_json_schema(mode="serialization"),
            output_dir=output / "action-construction" / f"{ordinal:02d}",
            seed=args.seed + ordinal,
        )
        result = ActionBatch.model_validate(payload)
        positions = [item.position for item in result.decisions]
        if (
            result.batch_id != batch_id
            or len(positions) != len(set(positions))
            or any(position < 1 or position > len(candidate_batch) for position in positions)
        ):
            raise ValueError("action-construction batch order differs")
        for decision in result.decisions:
            actions[candidate_batch[decision.position - 1]] = decision
    missing_actions = [item for item in candidate_ids if item not in actions]
    if missing_actions:
        _write_json(
            output / "ACTION_CONSTRUCTION_INCOMPLETE.json",
            {
                "missing_candidate_ids": missing_actions,
                "missing_count": len(missing_actions),
                "continuation_requires_new_version": True,
            },
        )
        raise ValueError(f"action construction is missing {len(missing_actions)} cases")

    def label_with(
        backend: StructuredOpenAICompatibleBackend,
        reviewer: str,
    ) -> dict[str, UtilityLabel]:
        labels: dict[str, UtilityLabel] = {}
        if args.reuse_label_output is not None:
            reuse_root = root / args.reuse_label_output / reviewer
            for ordinal, candidate_batch in enumerate(
                _batch(candidate_ids, args.label_batch_size), 1
            ):
                response_path = reuse_root / f"{ordinal:02d}" / "response.json"
                response = json.loads(response_path.read_text(encoding="utf-8"))
                result = UtilityBatch.model_validate(response["output_payload"])
                if tuple(item.position for item in result.decisions) != tuple(
                    range(1, len(candidate_batch) + 1)
                ):
                    raise ValueError("reused utility-label batch order differs")
                labels.update(zip(candidate_batch, result.decisions, strict=True))
            return labels
        for ordinal, candidate_batch in enumerate(_batch(candidate_ids, args.label_batch_size), 1):
            batch_id = f"{args.run_id}-{reviewer}-{ordinal:02d}"
            items = []
            for position, candidate_id in enumerate(candidate_batch, 1):
                outcome = outcomes[candidate_id]
                items.append(
                    {
                        "position": position,
                        "visible_decision": _visible_payload(
                            screens[candidate_id], records[candidate_id]
                        ),
                        "frozen_actions": actions[candidate_id].model_dump(
                            mode="json", exclude={"position"}
                        ),
                        "scoring_only_outcome": {
                            "observed_recommendation": outcome.observed_recommendation,
                            "outcome_payload": outcome.outcome_payload,
                        },
                    }
                )
            payload = _call(
                backend=backend,
                request_id=batch_id,
                node_name="scitastebench-natural-utility-label",
                instruction=_label_instruction(),
                payload={"batch_id": batch_id, "items": items},
                schema=UtilityBatch.model_json_schema(mode="serialization"),
                output_dir=output / reviewer / f"{ordinal:02d}",
                seed=args.seed + 100 + ordinal,
            )
            result = UtilityBatch.model_validate(payload)
            if result.batch_id != batch_id or tuple(
                item.position for item in result.decisions
            ) != tuple(range(1, len(candidate_batch) + 1)):
                raise ValueError("utility-label batch order differs")
            labels.update(zip(candidate_batch, result.decisions, strict=True))
        return labels

    labels_a = label_with(glm, "utility-primary-a")
    labels_b = label_with(qwen, "utility-primary-b")
    agreed = [
        candidate_id
        for candidate_id in candidate_ids
        if labels_a[candidate_id].preferred_option == labels_b[candidate_id].preferred_option
    ]
    agreement_family_counts = Counter(
        records[item].final_decision.taste_judgment_family.value
        for item in agreed
        if records[item].final_decision is not None
    )
    precedent_capable = [
        item
        for item in agreed
        if records[item].final_decision is not None
        and agreement_family_counts[
            records[item].final_decision.taste_judgment_family.value
        ]
        >= 2
    ]
    excluded_release: tuple[str, ...] = ()
    excluded_manifest_sha256: str | None = None
    if args.exclude_release_manifest is not None:
        excluded_path = root / args.exclude_release_manifest
        excluded_release = _manifest_release_ids(excluded_path)
        excluded_manifest_sha256 = _sha(excluded_path)

    fixed_precedents: tuple[str, ...] = ()
    fixed_precedent_manifest_sha256: str | None = None
    if args.fixed_precedent_manifest is not None:
        precedent_path = root / args.fixed_precedent_manifest
        fixed_precedents = _manifest_release_ids(precedent_path)
        fixed_precedent_manifest_sha256 = _sha(precedent_path)
        unknown = sorted(set(fixed_precedents) - set(agreed))
        if unknown:
            raise ValueError("fixed precedents are not dual-AI agreements: " + ",".join(unknown))
    precedent_pool = list(fixed_precedents) if fixed_precedents else precedent_capable

    if args.release_policy == "coverage":
        if len(precedent_capable) < args.release_size:
            raise ValueError(
                f"only {len(precedent_capable)} precedent-capable dual-AI agreements are "
                f"available for {args.release_size} cases"
            )
        release = _select_release(precedent_capable, records, release_size=args.release_size)
        unsupported_confirmation_ids: list[str] = []
    else:
        excluded = set(excluded_release)
        eligible_remaining = [item for item in agreed if item not in excluded]
        supported_families = {
            records[item].final_decision.taste_judgment_family
            for item in precedent_pool
            if records[item].final_decision is not None
        }
        release = [
            item
            for item in eligible_remaining
            if records[item].final_decision is not None
            and records[item].final_decision.taste_judgment_family in supported_families
        ]
        unsupported_confirmation_ids = sorted(set(eligible_remaining) - set(release))
        release = sorted(release, key=lambda value: _rank("confirmation-order", value))
        if args.release_size and len(release) != args.release_size:
            raise ValueError(
                f"remaining-agreements produced {len(release)} cases, expected "
                f"{args.release_size}"
            )

    release_source_groups = {records[item].source_group_id for item in release}
    precedent_source_groups = {records[item].source_group_id for item in precedent_pool}
    source_group_overlap = sorted(release_source_groups & precedent_source_groups)
    if source_group_overlap:
        raise ValueError("target and precedent source groups overlap")

    annotation_payload = {
        "run_id": args.run_id,
        "reviewers": [
            {"provider": glm.name, "model": glm.model},
            {"provider": qwen.name, "model": qwen.model},
        ],
        "candidate_count": len(candidate_ids),
        "agreement_count": len(agreed),
        "precedent_capable_agreement_count": len(precedent_capable),
        "release_case_ids": release,
        "reviewer_kind": "ai",
        "not_human_review": True,
        "human_validity_claim_allowed": False,
        "release_policy": args.release_policy,
        "excluded_release_manifest_sha256": excluded_manifest_sha256,
        "fixed_precedent_manifest_sha256": fixed_precedent_manifest_sha256,
        "fixed_precedent_case_count": len(fixed_precedents),
        "target_precedent_source_group_overlap_count": len(source_group_overlap),
        "unsupported_confirmation_case_ids": unsupported_confirmation_ids,
        "labels_frozen_before_confirmation_split_opened": bool(excluded_release),
    }
    annotation_hash = content_sha256(annotation_payload)
    _write_json(
        output / "ANNOTATION_MANIFEST.json",
        {**annotation_payload, "sha256": annotation_hash},
    )

    cases: list[BenchmarkCase] = []
    for candidate_id in release:
        screen = screens[candidate_id]
        record = records[candidate_id]
        decision = record.final_decision
        assert decision is not None
        pair = actions[candidate_id]
        label_a = labels_a[candidate_id]
        label_b = labels_b[candidate_id]
        matched_id = _precedent_for(candidate_id, precedent_pool, records, matched=True)
        mismatched_id = _precedent_for(candidate_id, precedent_pool, records, matched=False)
        matched_screen = screens[matched_id]
        matched_outcome = outcomes[matched_id]
        preferred_option = label_a.preferred_option
        confidence = (label_a.confidence + label_b.confidence) / 2
        option_ids = {
            "option-a": f"{candidate_id}-a",
            "option-b": f"{candidate_id}-b",
        }
        preferred_id = option_ids[preferred_option]
        other_id = option_ids[
            "option-b" if preferred_option == "option-a" else "option-a"
        ]
        task, stage = _task_and_stage(decision.decision_context_family.value)
        source_payload = _visible_payload(screen, record)
        source_sha = content_sha256(source_payload)
        utility_hash = content_sha256(
            {
                "candidate_id": candidate_id,
                "outcome_sha256": outcomes[candidate_id].record_sha256,
                "primary_a": label_a.model_dump(mode="json"),
                "primary_b": label_b.model_dump(mode="json"),
            }
        )
        cases.append(
            BenchmarkCase(
                case_id=f"natural-{candidate_id}",
                task=task,
                decision_context_family=decision.decision_context_family,
                taste_judgment_family=decision.taste_judgment_family,
                stage=stage,
                domain=record.domain,
                venue="natural-review-record",
                publication_year=2026,
                decision_context=(
                    f"Article context:\n{screen.reviewed_abstract}\n\n"
                    f"Pre-decision review context:\n{screen.predecision_review_context}\n\n"
                    f"Decision:\n{decision.atomic_decision_question}"
                ),
                candidate_actions=[
                    ResearchAction(
                        action_id=option_ids["option-a"],
                        type=pair.option_a.action_type,
                        description=pair.option_a.description,
                    ),
                    ResearchAction(
                        action_id=option_ids["option-b"],
                        type=pair.option_b.action_type,
                        description=pair.option_b.description,
                    ),
                ],
                action_roles={
                    option_ids["option-a"]: pair.option_a.role,
                    option_ids["option-b"]: pair.option_b.role,
                },
                preferred_action_id=preferred_id,
                wrong_level_action_ids=[],
                expert_distribution={preferred_id: confidence, other_id: 1.0 - confidence},
                label_authority=BenchmarkLabelAuthority.AI_PANEL_PROXY,
                action_utilities={preferred_id: 1.0, other_id: 0.0},
                utility_contract_sha256=utility_hash,
                knowledge_context=(
                    f"Prior source abstract:\n{matched_screen.reviewed_abstract}\n\n"
                    f"Prior decision context:\n{matched_screen.predecision_review_context}\n\n"
                    f"Observed later record:\n"
                    f"{json.dumps(matched_outcome.outcome_payload, ensure_ascii=False)}"
                ),
                knowledge_evidence_ids=(f"raw-{matched_id}",),
                taste_principle=labels_a[matched_id].transferable_principle,
                taste_precedent_ids=(f"taste-{matched_id}",),
                taste_precedent_source_group_ids=(records[matched_id].source_group_id,),
                placebo_taste_principle=labels_a[mismatched_id].transferable_principle,
                placebo_precedent_ids=(f"taste-{mismatched_id}",),
                placebo_precedent_source_group_ids=(
                    records[mismatched_id].source_group_id,
                ),
                source_group_id=record.source_group_id,
                source_ref=f"scitastebench-development-intake/{candidate_id}",
                source_sha256=source_sha,
                primary_label_count=2,
                primary_label_agreement=1.0,
                annotation_manifest_sha256=annotation_hash,
                prompt_version="scitastebench-natural-development-v1",
                headline_eligible=True,
                self_referential=False,
            )
        )
    suite = BenchmarkSuite(
        suite_id=args.suite_id,
        version="2.0",
        description=(
            "Natural source-group-disjoint scientific decisions with dual-AI proxy labels; "
            f"split policy={args.release_policy}; not formal effectiveness evidence."
        ),
        evidence_tier=BenchmarkEvidenceTier.NATURAL_PILOT,
        annotation_manifest_sha256=annotation_hash,
        conditions=[
            BenchmarkCondition.BASE,
            BenchmarkCondition.KNOWLEDGE_RAG,
            BenchmarkCondition.TASTE_LIBRARY,
            BenchmarkCondition.TASTE_PLACEBO,
            BenchmarkCondition.FULL_SCITASTE,
        ],
        cases=cases,
    )
    suite_path = output / "SUITE.yaml"
    suite_path.write_text(
        yaml.safe_dump(
            suite.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    summary = {
        "run_id": args.run_id,
        "candidate_count": len(candidate_ids),
        "dual_ai_agreement_count": len(agreed),
        "release_case_count": len(release),
        "context_family_counts": dict(
            sorted(
                Counter(
                    records[item].final_decision.decision_context_family.value
                    for item in release
                    if records[item].final_decision is not None
                ).items()
            )
        ),
        "taste_family_counts": dict(
            sorted(
                Counter(
                    records[item].final_decision.taste_judgment_family.value
                    for item in release
                    if records[item].final_decision is not None
                ).items()
            )
        ),
        "domain_counts": dict(sorted(Counter(records[item].domain for item in release).items())),
        "suite_sha256": suite.sha256,
        "suite_path": str(suite_path),
        "formal_evidence_eligible": False,
        "not_human_review": True,
    }
    _write_json(output / "SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locator-root", type=Path, default=Path("."))
    parser.add_argument("--run-id", default="scitastebench-natural-development-v1")
    parser.add_argument("--suite-id", default="scitastebench-natural-development-v1")
    parser.add_argument(
        "--screening-items",
        type=Path,
        default=Path(
            "outputs/projects/scitaste-self-development/evaluations/"
            "scitastebench-four-layer-development-intake-v1/SCREENING_ITEMS.jsonl"
        ),
    )
    parser.add_argument(
        "--outcome-vault",
        type=Path,
        default=Path(
            "outputs/projects/scitaste-self-development/evaluations/"
            "scitastebench-four-layer-development-intake-v1/OUTCOME_VAULT.json"
        ),
    )
    parser.add_argument(
        "--panel-decisions",
        type=Path,
        default=Path(
            "outputs/projects/scitaste-self-development/evaluations/"
            "scitastebench-four-layer-development-panel-v3/normalization/"
            "FINAL_DECISIONS.jsonl"
        ),
    )
    parser.add_argument(
        "--action-backend",
        type=Path,
        default=Path("configs/model_nodes/deepseek_v41flash.scitastebench_live_20260917.yaml"),
    )
    parser.add_argument(
        "--label-backend-a",
        type=Path,
        default=Path("configs/model_nodes/zhipu_glm53_flash.scitastebench_live_20260916.yaml"),
    )
    parser.add_argument(
        "--label-backend-b",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "outputs/projects/scitaste-self-development/evaluations/"
            "scitastebench-natural-development-v1"
        ),
    )
    parser.add_argument("--release-size", type=int, default=36)
    parser.add_argument(
        "--release-policy",
        choices=("coverage", "remaining-agreements"),
        default="coverage",
    )
    parser.add_argument("--exclude-release-manifest", type=Path, default=None)
    parser.add_argument("--fixed-precedent-manifest", type=Path, default=None)
    parser.add_argument("--action-batch-size", type=int, default=8)
    parser.add_argument("--reuse-action-output", type=Path, default=None)
    parser.add_argument("--reuse-action-batch-size", type=int, default=8)
    parser.add_argument("--reuse-pending-action-output", type=Path, default=None)
    parser.add_argument("--reuse-pending-action-batch-size", type=int, default=4)
    parser.add_argument("--reuse-pending-2-action-output", type=Path, default=None)
    parser.add_argument("--reuse-pending-2-action-batch-size", type=int, default=4)
    parser.add_argument("--reuse-label-output", type=Path, default=None)
    parser.add_argument("--label-batch-size", type=int, default=6)
    parser.add_argument("--seed", type=int, default=6027)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())

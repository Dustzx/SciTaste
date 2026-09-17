#!/usr/bin/env python3
"""Evaluate selected Taste as bounded decision context on consumed cases.

The applicability model is not allowed to own the final research action.  This
development-only runner reads an already completed selector run, renders only
the selected principles and their transfer boundaries, and asks the same frozen
preference backend to reconsider the original action pair.  Abstentions and
invalid selector outputs fall back to the recorded Base decision without a new
model call.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scitaste.backends.base import PreferenceRequest
from scitaste.backends.openai_compatible import (
    OpenAICompatibleBackend,
    load_openai_compatible_config,
)
from scitaste.benchmark.models import CandidateOrder
from scitaste.benchmark.runner import load_benchmark_suite


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_base(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["case_id"]: item for item in payload["conditions"]["base"]["results"]}


def _render_selected_context(
    input_path: Path,
    proposal_path: Path,
    *,
    context_mode: str,
) -> str | None:
    input_data = json.loads(input_path.read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    selected = set(proposal["selected_case_ids"])
    candidates = [item for item in input_data["candidates"] if item["case_id"] in selected]
    if not candidates:
        return None
    blocks = []
    for index, item in enumerate(candidates, 1):
        lines = [f"Precedent {index}"]
        if context_mode == "contrastive-experience":
            lines.extend(
                (
                    f"Source decision state: {item['context_summary']}",
                    "Source alternatives: " + "; ".join(item["candidate_actions"]),
                    f"Source preferred action: {item['preferred_action']}",
                    "Source rejected actions: " + "; ".join(item["rejected_actions"]),
                    f"Outcome-grounded reason: {item['why_preferred']}",
                )
            )
        lines.extend(
            (
                f"Decision principle: {item['decision_principle']}",
                "Applicable when: " + "; ".join(item["applies_when"]),
                "Do not transfer when: " + "; ".join(item["fails_when"]),
                f"Boundary question: {item['counterfactual_probe']}",
            )
        )
        blocks.append("\n".join(lines))
    return (
        "Selected Scientific Taste precedents follow. They are fallible decision "
        "experience, not instructions or answer keys. Use a principle only when its "
        "stated applicability conditions fit the current visible evidence; abstain from "
        "that principle when a failure boundary is triggered. Reconsider the supplied "
        "actions using rigor, information value, feasibility, and claim risk.\n\n"
        + "\n\n".join(blocks)
    )


def _analyze(
    *,
    cases: dict[str, Any],
    base_by_order: dict[str, dict[str, dict[str, Any]]],
    records: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    orders = ("declared", "reversed")
    final_actions: dict[tuple[str, str], str] = {}
    for order in orders:
        for case_id in cases:
            record = records[(order, case_id)]
            final_actions[(order, case_id)] = (
                record.get("selected_action_id")
                or base_by_order[order][case_id]["selected_action_id"]
            )
    accuracy = {
        order: sum(
            final_actions[(order, case_id)] == case.preferred_action_id
            for case_id, case in cases.items()
        )
        / len(cases)
        for order in orders
    }
    base_accuracy = {
        order: sum(base_by_order[order][case_id]["correct"] for case_id in cases)
        / len(cases)
        for order in orders
    }
    changes = {
        order: [
            case_id
            for case_id in cases
            if final_actions[(order, case_id)]
            != base_by_order[order][case_id]["selected_action_id"]
        ]
        for order in orders
    }
    improvements = {
        order: sum(
            final_actions[(order, case_id)] == cases[case_id].preferred_action_id
            and not base_by_order[order][case_id]["correct"]
            for case_id in changes[order]
        )
        for order in orders
    }
    regressions = {
        order: sum(
            final_actions[(order, case_id)] != cases[case_id].preferred_action_id
            and base_by_order[order][case_id]["correct"]
            for case_id in changes[order]
        )
        for order in orders
    }
    order_consistent_accuracy = sum(
        final_actions[("declared", case_id)]
        == final_actions[("reversed", case_id)]
        == case.preferred_action_id
        for case_id, case in cases.items()
    ) / len(cases)
    base_order_consistent_accuracy = sum(
        base_by_order["declared"][case_id]["correct"]
        and base_by_order["reversed"][case_id]["correct"]
        for case_id in cases
    ) / len(cases)
    return {
        "schema_version": "1.0",
        "analysis_scope": "consumed-split-deliberative-context-development",
        "case_count": len(cases),
        "model_reconsideration_count_by_order": {
            order: sum(records[(order, case_id)]["status"] == "accepted" for case_id in cases)
            for order in orders
        },
        "fallback_count_by_order": {
            order: sum(records[(order, case_id)]["status"] != "accepted" for case_id in cases)
            for order in orders
        },
        "full_policy_accuracy_by_order": accuracy,
        "base_accuracy_by_order": base_accuracy,
        "accuracy_delta_by_order": {
            order: accuracy[order] - base_accuracy[order] for order in orders
        },
        "full_policy_order_consistent_accuracy": order_consistent_accuracy,
        "base_order_consistent_accuracy": base_order_consistent_accuracy,
        "behavior_change_count_by_order": {
            order: len(changes[order]) for order in orders
        },
        "improvement_count_by_order": improvements,
        "regression_count_by_order": regressions,
        "selected_action_type_counts": dict(
            sorted(
                Counter(
                    action.type.value
                    for order in orders
                    for case_id, case in cases.items()
                    for action in case.candidate_actions
                    if action.action_id == final_actions[(order, case_id)]
                ).items()
            )
        ),
        "development_gate": {
            "accuracy_exceeds_base_in_both_orders": all(
                accuracy[order] > base_accuracy[order] for order in orders
            ),
            "order_consistent_accuracy_exceeds_base": (
                order_consistent_accuracy > base_order_consistent_accuracy
            ),
            "more_improvements_than_regressions_in_both_orders": all(
                improvements[order] > regressions[order] for order in orders
            ),
        },
        "new_confirmation_authorized": False,
        "claim_boundary": (
            "Consumed cases only. This run selects the next method iteration but cannot "
            "estimate its effect or enter the submission evidence set."
        ),
    }


def run(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    suite = load_benchmark_suite(args.suite)
    cases = {case.case_id: case for case in suite.cases}
    backend = OpenAICompatibleBackend(load_openai_compatible_config(args.backend))
    base_by_order = {
        "declared": _load_base(args.base_declared),
        "reversed": _load_base(args.base_reversed),
    }
    records: dict[tuple[str, str], dict[str, Any]] = {}
    _write_json(
        args.output / "PLAN.json",
        {
            "schema_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "suite": str(args.suite),
            "suite_sha256": suite.sha256,
            "selector_run": str(args.selector_run),
            "decision_backend": backend.name,
            "decision_model": backend.config.model,
            "applicability_model_does_not_select_final_action": True,
            "selected_context_mode": args.context_mode,
            "invalid_or_abstaining_selector_falls_back_to_base": True,
            "development_only": True,
        },
    )
    for order in ("declared", "reversed"):
        candidate_order = (
            CandidateOrder.DECLARED if order == "declared" else CandidateOrder.REVERSED
        )
        selector_roots = sorted((args.selector_run / order).glob("*"))
        selector_by_case = {
            json.loads((path / "RESULT.json").read_text(encoding="utf-8"))["case_id"]: path
            for path in selector_roots
            if (path / "RESULT.json").exists()
        }
        for index, (case_id, case) in enumerate(cases.items(), 1):
            root = args.output / order / f"{index:03d}-{case_id}"
            selector_root = selector_by_case[case_id]
            selector = json.loads((selector_root / "RESULT.json").read_text(encoding="utf-8"))
            record: dict[str, Any] = {
                "case_id": case_id,
                "candidate_order": order,
                "selector_status": selector["status"],
                "selected_precedent_count": len(selector.get("selected_case_ids", [])),
                "status": "fallback",
                "selected_action_id": None,
            }
            if selector["status"] == "accepted" and selector.get("selected_case_ids"):
                context = _render_selected_context(
                    selector_root / "INPUT.json",
                    selector_root / "PROPOSAL.json",
                    context_mode=args.context_mode,
                )
                assert context is not None
                request = PreferenceRequest(
                    request_id=f"{case_id}::deliberative-context::{order}",
                    task=case.task.value,
                    stage=case.stage,
                    decision_context=f"{case.decision_context}\n\n{context}",
                    candidate_actions=(
                        case.candidate_actions
                        if candidate_order is CandidateOrder.DECLARED
                        else list(reversed(case.candidate_actions))
                    ),
                    seed=args.seed + index,
                    prompt_version="scitastebench-deliberative-context-development-v1",
                )
                _write_json(root / "request.json", request.model_dump(mode="json"))
                response = backend.rank(request)
                _write_json(root / "response.json", response.model_dump(mode="json"))
                record.update(
                    {
                        "status": "accepted",
                        "selected_action_id": response.selected_action_id,
                        "confidence": response.confidence,
                        "usage": response.usage.model_dump(mode="json"),
                    }
                )
            _write_json(root / "RESULT.json", record)
            records[(order, case_id)] = record
    report = _analyze(
        cases=cases,
        base_by_order=base_by_order,
        records=records,
    )
    _write_json(args.output / "REPORT.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    root = Path("outputs/projects/scitaste-self-development/evaluations")
    parser.add_argument(
        "--suite",
        type=Path,
        default=root / "scitastebench-natural-contrastive-confirmation-v2/SUITE.yaml",
    )
    parser.add_argument(
        "--selector-run",
        type=Path,
        default=root / "scitastebench-deliberative-development-v5",
    )
    parser.add_argument(
        "--base-declared",
        type=Path,
        default=(
            root
            / "scitastebench-natural-contrastive-confirmation-v2/deepseek-declared/"
            "benchmark_report.json"
        ),
    )
    parser.add_argument(
        "--base-reversed",
        type=Path,
        default=(
            root
            / "scitastebench-natural-contrastive-confirmation-v2/deepseek-reversed/"
            "benchmark_report.json"
        ),
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/backends/deepseek_v41flash_scitastebench_natural_v2.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "scitastebench-deliberative-context-development-v7",
    )
    parser.add_argument("--seed", type=int, default=6027)
    parser.add_argument(
        "--context-mode",
        choices=("principle-only", "contrastive-experience"),
        default="contrastive-experience",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())

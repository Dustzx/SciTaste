"""Synthetic FlowGen aggregate projection and actual local DOM acceptance.

All source/summary/ledger fixtures live in a temporary root. Browser responses
are intercepted; no real experiment input, answer, prediction or call is read.
"""

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import progress_board as board
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def main():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="flowgen-projection-check-") as temp:
        root = Path(temp)
        report = root / "report"
        study = root / "outputs/projects/fastresearch-cvpr2027/research"
        screen = study / "diagram/runs" / board.DIAGRAM_RUNS["cvpr_flowgen_screen.py"]
        comparison = study / "diagram/runs" / board.DIAGRAM_RUNS["cvpr_flowgen_diagnostic.py"]
        resources = {
            "physical_attempts": 16,
            "successful_settled": 16,
            "run_conservative_cny": 0.1,
            "project_conservative_cny": 0.2,
            "blocking_unresolved": 0,
            "retry_unknown_count": 0,
        }
        for name, value in [
            ("STATUS_BOARD.json", {"projects": [], "axes": []}),
            ("sources.json", {"projects": {}}),
            ("EXPERIENCE_POOL.json", {"entries": []}),
        ]:
            write(report / name, value)
        write(
            study / "PORTFOLIO.json",
            {
                "branches": [],
                "cpu_candidates": [
                    {
                        "id": "FR-DIAGRAM",
                        "name": "FlowGen candidate",
                        "evidence_summary": "Synthetic source-only development",
                        "next_action": "Root decision only",
                    }
                ],
                "gates": [],
            },
        )
        write(
            screen / "PROTOCOL.json",
            {
                "kind": board.DIAGRAM_SCREEN_KIND,
                "run_id": screen.name,
                "model": "synthetic",
                "N": 16,
                "request_digests": {"PRIVATE_SAMPLE_ID": "SECRET"},
                "private_inputs": "SECRET",
            },
        )
        write(
            screen / "STATUS.json",
            {
                "kind": board.DIAGRAM_SCREEN_KIND,
                "run_id": screen.name,
                "status": "completed_scored",
                "pid": 123,
                "completed_calls": 16,
                "resources": resources,
                "updated_at": "2026-10-12T12:00:00+08:00",
            },
        )
        screen_summary = {
            "kind": board.DIAGRAM_SCREEN_KIND,
            "run_id": screen.name,
            "status": "complete",
            "direct": {"N": 16, "correct": 7, "invalid": 0, "answer": "SECRET"},
            "saturated": False,
            "engineering_valid": True,
            "resources": resources,
            "new_method": False,
            "publication_ready": False,
            "private_answers": "SECRET",
        }
        write(screen / "SUMMARY.json", screen_summary)
        write(
            screen / "ROOT_READOUT_DECISION.json",
            {
                "decision": "preserve historical readout",
                "next_action": "review comparison",
                "private_predictions": "SECRET",
            },
        )
        comparison_resources = {
            **resources,
            "physical_attempts": 12,
            "successful_settled": 12,
            "run_conservative_cny": 0.12,
            "reused_direct_physical_attempts": 16,
            "reused_direct_conservative_cny": 0.1,
            "family_conservative_cny": 0.22,
        }
        write(
            comparison / "PROTOCOL.json",
            {
                "kind": board.DIAGRAM_COMPARISON_KIND,
                "run_id": comparison.name,
                "model": "synthetic",
                "N": 16,
                "direct_anchor": {
                    "run_id": screen.name,
                    "N": 16,
                    "reused_physical_calls": 16,
                    "prior_development_score_exposed": True,
                    "answer_mapping": "SECRET",
                },
                "request_digests": {"PRIVATE_SAMPLE_ID": "SECRET"},
            },
        )
        write(
            comparison / "STATUS.json",
            {
                "kind": board.DIAGRAM_COMPARISON_KIND,
                "run_id": comparison.name,
                "status": "running",
                "pid": 123,
                "completed_calls": 12,
                "panel_records": 12,
                "resources": comparison_resources,
                "updated_at": "2026-10-12T12:01:00+08:00",
                "private_response": "SECRET",
            },
        )
        write(comparison / "PARTIAL_SUMMARY.json", {"correct": 16, "private_answers": "SECRET"})
        # Never create any benchmark data. Sentinels catch accidental generic
        # PRED/private/frozen-slot reads and prevent silent future regressions.
        original_read = board.read
        reads = []

        def guarded_read(path, default=None):
            path = Path(path)
            reads.append(path)
            if path.is_relative_to(study / "diagram"):
                assert path.name not in {
                    "PREDICTIONS.json",
                    "calls.jsonl",
                    "TARGETS.json",
                    "PARTIAL_SUMMARY.json",
                }
                assert not path.name.startswith(("PRIVATE", "ALL_"))
            return original_read(path, default)

        ledger = {
            "cap_cny": 300,
            "conservative_total_cny": 0.22,
            "unresolved_reserved_cny": 0,
            "attempts": {},
        }
        for run, count in ((screen, 16), (comparison, 12)):
            for i in range(count):
                ledger["attempts"][run.name + str(i)] = {
                    "run_id": run.name,
                    "status": "settled",
                    "cost_cny": 0.001,
                }
        write(study / "API_LEDGER.json", ledger)
        with (
            patch.object(board, "ROOT", root),
            patch.object(board, "REPORT", report),
            patch.object(board, "read", guarded_read),
            patch.object(board, "alive", lambda pid, run_id: run_id == comparison.name),
        ):
            data = board.snapshot()
            runs = {r["name"]: r for r in data["experiments"]}
            check(
                "diagram glob and CPU candidate without promoting branch",
                len(runs) == 2
                and not data["portfolio"]["branches"]
                and data["diagram_candidate"]["current_run"] == comparison.name,
            )
            current = runs[comparison.name]
            completed = runs[screen.name]
            check(
                "running STATUS projects12/112 and128panel without fake scores",
                current["status"] == "running"
                and current["live"]
                and current["completed"] == 12
                and current["planned"] == 112
                and current["logical_panel_calls_including_reused_direct"] == 128
                and current["summary"] is None
                and len(current["arms"]) == 5
                and all(a["score"] is None for a in current["arms"]),
            )
            check(
                "screen single full16 arm and historical root adjudication retained",
                completed["summary"]["direct"]["correct"] == 7
                and len(completed["arms"]) == 1
                and completed["planned"] == 16
                and completed["summary"]["root_readout_decision"]["decision"]
                == "preserve historical readout",
            )
            check(
                "no private predictions calls frozen slots targets or partial summaries read",
                all(
                    p.name
                    not in {
                        "PREDICTIONS.json",
                        "calls.jsonl",
                        "TARGETS.json",
                        "PARTIAL_SUMMARY.json",
                    }
                    for p in reads
                ),
            )
            serialized = json.dumps(data)
            check(
                "snapshot strips sampleIDs answers and unknown nested payloads",
                "SECRET" not in serialized and "PRIVATE_SAMPLE_ID" not in serialized,
            )
            for run in (screen, comparison):
                doc = board.source_document("run." + run.name + ".protocol")
                check(
                    "safe protocol attachment " + run.name,
                    doc["projection"] == "aggregate_allowlist"
                    and "request_digests" not in doc["content"]
                    and "SECRET" not in doc["content"],
                )
            check(
                "running comparison summary/partial not indexed",
                "run." + comparison.name not in board.sources()
                and "run." + comparison.name + ".partial" not in board.sources(),
            )
            private = comparison / "PRIVATE_PREPARED.json"
            write(private, {"messages": "SECRET"})
            with patch.object(board, "sources", lambda: {"malicious": private}):
                check(
                    "explicitly indexed private still denied",
                    board.source_document("malicious") is None,
                )
            full_resources = {
                **comparison_resources,
                "physical_attempts": 112,
                "successful_settled": 112,
                "run_conservative_cny": 1.12,
                "family_conservative_cny": 1.22,
            }
            full = {
                "kind": board.DIAGRAM_COMPARISON_KIND,
                "run_id": comparison.name,
                "status": "complete",
                "N_each": 16,
                "arms": {
                    a: {"N": 16, "correct": n, "invalid": 0}
                    for a, n in zip(board.DIAGRAM_ARMS, (7, 6, 8, 9, 15))
                },
                "learned_request_counts": dict.fromkeys(board.DIAGRAM_ARMS[1:4], 16),
                "resources": full_resources,
                "paired": {
                    "textflow_mermaid_vs_direct": {
                        "N": 16,
                        "wins": 3,
                        "losses": 1,
                        "net": 2,
                        "private_answer": "SECRET",
                    }
                },
                "semantic_acquisition_repair_proposal_eligible": True,
                "new_method": False,
                "publication_ready": False,
            }
            for label, mutate in [
                ("missing arm", lambda x: x["arms"].pop("gold_diagnostic")),
                ("short denominator", lambda x: x["arms"]["learned_high"].update(N=15)),
                ("insufficient receipts", lambda x: x["resources"].update(successful_settled=111)),
            ]:
                bad = copy.deepcopy(full)
                mutate(bad)
                write(comparison / "SUMMARY.json", bad)
                check(
                    "incomplete comparison withheld " + label,
                    board.diagram_summary(comparison) is None,
                )
            write(comparison / "SUMMARY.json", full)
            safe = board.diagram_summary(comparison)
            check(
                "full fiveN16 scorer aggregate certifies80terminal and strong comparator fields",
                safe["terminal_solver_slots"] == 80
                and len(safe["arms"]) == 5
                and "SECRET" not in json.dumps(safe),
            )
            check(
                "summary cannot overwrite source running state",
                board.diagram_experiment(
                    comparison,
                    original_read(comparison / "STATUS.json"),
                    original_read(comparison / "PROTOCOL.json"),
                )["status"]
                == "running",
            )
            status = original_read(comparison / "STATUS.json")
            status.update(
                status="completed_scored",
                completed_calls=112,
                panel_records=128,
                resources=full_resources,
            )
            write(comparison / "STATUS.json", status)
            complete_data = board.snapshot()
            check(
                "shared physical/fee namespaces distinguish112new16borrowed128family",
                safe["resources"]["physical_attempts"] == 112
                and safe["resources"]["reused_direct_physical_attempts"] == 16
                and abs(
                    safe["resources"]["family_conservative_cny"]
                    - safe["resources"]["run_conservative_cny"]
                    - 0.1
                )
                < 1e-9,
            )

        # Match the real no--run-id command contract, not a substring or PID.
        original_bytes = Path.read_bytes

        def proc_bytes(path):
            return (
                b"python\0/scripts/cvpr_flowgen_diagnostic.py\0--operation\0run\0"
                if str(path) == "/proc/123/cmdline"
                else original_bytes(path)
            )

        with patch.object(Path, "read_bytes", proc_bytes):
            check(
                "fixed script/run identity recognizes live comparison",
                board.alive(123, comparison.name),
            )
            check("fixed identity rejects unrelated screen run", not board.alive(123, screen.name))

        errors, writes, outbound = [], [], []
        with sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda req: writes.append(req.url) if req.method != "GET" else None)
            page.on(
                "request",
                lambda req: outbound.append(req.url) if not req.url.startswith(BASE) else None,
            )
            projected = [data]
            page.route(
                "**/assets/training-free-evidence.js",
                lambda route: route.fulfill(
                    path=str(ROOT / "web/assets/training-free-evidence.js")
                ),
            )
            page.route("**/api/progress", lambda route: route.fulfill(json=projected[0]))
            page.goto(BASE + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch")
            expect(page.locator("[data-tf-diagram-candidate]")).to_be_visible()
            check(
                "overview candidate visible while formal candidate count remainszero",
                page.locator('[data-tf-stat="1"]').inner_text() == "0"
                and page.locator('[data-tf-branch="FR-DIAGRAM"]').count() == 0,
            )
            page.goto(
                BASE
                + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=results&branch=FR-DIAGRAM&run="
                + comparison.name
            )
            expect(page.locator("[data-tf-diagram-pending]")).to_be_visible()
            check(
                "live DOM new/borrowed/panel progress and no partial accuracy",
                "12 / 112" in page.locator(".tf-run").inner_text()
                and "复用 direct16" in page.locator(".tf-run").inner_text()
                and page.locator("[data-tf-diagram-results]").count() == 0,
            )
            pending_complete = copy.deepcopy(data)
            next(r for r in pending_complete["experiments"] if r["name"] == comparison.name)[
                "status"
            ] = "completed_scored"
            projected[0] = pending_complete
            page.reload()
            expect(page.locator("[data-tf-diagram-pending]")).to_be_visible()
            check(
                "source completion without valid aggregate not called CPU scoring complete",
                "源状态完成 · 完整汇总待核" in page.locator(".tf-run").inner_text()
                and "开发CPU评分完成" not in page.locator(".tf-run").inner_text(),
            )
            projected[0] = complete_data
            page.reload()
            expect(page.locator("[data-tf-diagram-results]")).to_be_visible()
            check(
                "complete DOM shows all five arms and paired counts without scientific promotion",
                page.locator("[data-tf-arm]").count() == 5
                and page.locator("[data-tf-diagram-paired] tbody tr").count() == 1
                and "没有新方法或自动扩批结论"
                in page.locator("[data-tf-diagram-gate]").inner_text(),
            )
            page.goto(
                BASE
                + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=results&branch=FR-DIAGRAM&run="
                + screen.name
            )
            expect(page.locator("[data-tf-diagram-results]")).to_be_visible()
            check(
                "screen DOM full16singlearm and history root retained",
                page.locator("[data-tf-arm]").count() == 1
                and "43.75%" in page.locator("[data-tf-diagram-results]").inner_text()
                and "preserve historical readout"
                in page.locator("[data-tf-diagram-root]").inner_text(),
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(BASE + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch")
            expect(page.locator("[data-tf-diagram-candidate]")).to_be_visible()
            check(
                "mobile candidate no document overflow",
                page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
            )
            browser.close()
        check(
            "browser no errors writes or externalrequests",
            not errors and not writes and not outbound,
        )
    result = {
        "status": "passed",
        "N_checks": len(checks),
        "checks": checks,
        "real_model_api_calls": 0,
        "real_experiment_inputs_targets_predictions_read": 0,
    }
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports/flowgen_safe_ui_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

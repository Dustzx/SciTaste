"""Incremental synthetic uniform-solver projection and DOM checks; zero model calls."""

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

    with tempfile.TemporaryDirectory(prefix="uniform-projection-check-") as temp:
        root = Path(temp)
        report = root / "report"
        study = root / "outputs/projects/fastresearch-cvpr2027/research"
        runs = study / "diagram/runs"
        uniform = runs / board.DIAGRAM_RUNS["cvpr_textflow_solver_control.py"]
        comparison = runs / board.DIAGRAM_RUNS["cvpr_flowgen_diagnostic.py"]
        unknown = runs / "unknown_future_tool_kind"
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
                "gates": [],
                "cpu_candidates": [
                    {
                        "id": "FR-DIAGRAM",
                        "name": "FlowGen candidate",
                        "current_action": "Current action wins",
                        "next_action": "Stale source preparation",
                        "evidence_summary": "Complete historical development",
                    }
                ],
            },
        )
        protocol = {
            "kind": board.DIAGRAM_UNIFORM_KIND,
            "run_id": uniform.name,
            "N": 16,
            "model": "synthetic",
            "interpretation": "Common solver engineering control",
            "family_max_physical_attempts": 192,
            "max_new_physical_attempts": 48,
            "request_digests": {"PRIVATE_ID": "SECRET"},
            "private_inputs": "SECRET",
        }
        resources = {
            "physical_attempts": 5,
            "successful_settled": 5,
            "run_conservative_cny": 0.01,
            "family_conservative_cny": 0.31,
            "project_conservative_cny": 64.31,
        }
        status = {
            "kind": board.DIAGRAM_UNIFORM_KIND,
            "run_id": uniform.name,
            "status": "running",
            "pid": 123,
            "completed_calls": 5,
            "updated_at": "2026-10-12T13:00:00+08:00",
            "resources": resources,
            "private_answer": "SECRET",
        }
        write(uniform / "PROTOCOL.json", protocol)
        write(uniform / "STATUS.json", status)
        write(unknown / "PROTOCOL.json", {"kind": "future_tool_kind", "run_id": unknown.name})
        write(unknown / "STATUS.json", {"status": "running"})
        write(unknown / "SUMMARY.json", {"private_answers": "SECRET"})
        write(unknown / "PRIVATE_PREPARED.json", {"private_answers": "SECRET"})
        comparison_resources = {
            "physical_attempts": 112,
            "successful_settled": 112,
            "blocking_unresolved": 0,
            "run_conservative_cny": 0.26,
            "reused_direct_physical_attempts": 16,
            "reused_direct_conservative_cny": 0.04,
            "family_conservative_cny": 0.30,
            "project_conservative_cny": 64.30,
        }
        scores = {
            arm: {"N": 16, "correct": n, "invalid": inv}
            for arm, n, inv in zip(board.DIAGRAM_ARMS, (7, 7, 10, 2, 14), (0, 0, 0, 3, 0))
        }
        write(
            comparison / "PROTOCOL.json",
            {"kind": board.DIAGRAM_COMPARISON_KIND, "run_id": comparison.name},
        )
        write(
            comparison / "STATUS.json",
            {
                "status": "completed_scored",
                "completed_calls": 112,
                "panel_records": 128,
                "updated_at": "2026-10-12T12:00:00+08:00",
                "resources": comparison_resources,
            },
        )
        write(
            comparison / "SUMMARY.json",
            {
                "kind": board.DIAGRAM_COMPARISON_KIND,
                "run_id": comparison.name,
                "status": "complete",
                "N_each": 16,
                "arms": scores,
                "resources": comparison_resources,
                "learned_request_counts": dict.fromkeys(board.DIAGRAM_ARMS[1:4], 16),
                "semantic_acquisition_repair_proposal_eligible": False,
            },
        )
        write(
            comparison / "ROOT_READOUT_DECISION.json",
            {
                "decision": "Engineering gate failed preserve original readout",
                "supported": ["Strong JSON10/16", "Original envelope invalid3"],
                "unknown": ["Safe tools not run", "Independent confirmation absent"],
                "next_action": {
                    "uniform_solver_control": "All16 exact representations",
                    "safe_tools": "Pure bounded tools remain conditional",
                    "new_method_proposal_or_expansion_authorized_by_this_readout": False,
                    "private_payload": "SECRET",
                },
                "private_raw": "SECRET",
            },
        )
        attempts = {
            f"{uniform.name}-{i}": {"run_id": uniform.name, "status": "settled", "cost_cny": 0.002}
            for i in range(5)
        }
        write(study / "API_LEDGER.json", {"cap_cny": 300, "attempts": attempts})
        original_read = board.read
        reads = []

        def guarded_read(path, default=None):
            path = Path(path)
            if path.is_relative_to(runs):
                reads.append(path)
                assert path.name in {
                    "PROTOCOL.json",
                    "STATUS.json",
                    "SUMMARY.json",
                    "ROOT_READOUT_DECISION.json",
                }
                assert not (path.parent == unknown and path.name == "SUMMARY.json")
            return original_read(path, default)

        with (
            patch.object(board, "ROOT", root),
            patch.object(board, "REPORT", report),
            patch.object(board, "read", guarded_read),
            patch.object(board, "alive", lambda pid, run_id: run_id == uniform.name),
        ):
            pending = board.snapshot()
            run = next(x for x in pending["experiments"] if x["name"] == uniform.name)
            check(
                "new kind projects5/16 live single arm no borrowed calls",
                run["live"]
                and run["completed"] == 5
                and run["planned"] == 16
                and run["reused_direct_records"] == 0
                and len(run["arms"]) == 1
                and run["arms"][0]["score"] is None
                and run["summary"] is None,
            )
            check(
                "unknown kind not inferred or privately read",
                all(x["name"] != unknown.name for x in pending["experiments"]),
            )
            check(
                "candidate current_action supersedes stale next_action no scientific branch",
                pending["diagram_candidate"]["next_action"] == "Current action wins"
                and not pending["portfolio"]["branches"],
            )
            safe_root = next(x for x in pending["experiments"] if x["name"] == comparison.name)[
                "summary"
            ]["root_readout_decision"]
            check(
                "root supported unknown and only fixed next_action fields projected",
                safe_root["supported"][0] == "Strong JSON10/16"
                and len(safe_root["unknown"]) == 2
                and len(safe_root["next_action"]) == 3
                and safe_root["next_action"][
                    "new_method_proposal_or_expansion_authorized_by_this_readout"
                ]
                is False,
            )
            doc = board.source_document("run." + uniform.name + ".protocol")
            check(
                "uniform protocol attachment excludes request hashes and private fields",
                doc["projection"] == "aggregate_allowlist"
                and "request_digests" not in doc["content"]
                and "SECRET" not in doc["content"],
            )
            check(
                "snapshot excludes nested private sentinels",
                "SECRET" not in json.dumps(pending) and "PRIVATE_ID" not in json.dumps(pending),
            )
            private = unknown / "PRIVATE_PREPARED.json"
            with patch.object(board, "sources", lambda: {"bad": private}):
                check(
                    "unknown explicitly indexed private endpoint denied",
                    board.source_document("bad") is None,
                )
            full = {
                "kind": board.DIAGRAM_UNIFORM_KIND,
                "run_id": uniform.name,
                "status": "complete",
                "N": 16,
                "uniform_solver": {"N": 16, "correct": 9, "invalid": 0, "answer": "SECRET"},
                "reference_arms": {k: v for k, v in scores.items() if k != "textflow_mermaid"},
                "original_textflow_solver": scores["textflow_mermaid"],
                "paired_uniform_vs_direct": {
                    "N": 16,
                    "wins": 3,
                    "losses": 1,
                    "net": 2,
                    "answer": "SECRET",
                },
                "paired_uniform_vs_highJSON": {"N": 16, "wins": 1, "losses": 2, "net": -1},
                "prompt_contract_engineering_valid": True,
                "oracle_minus_strongest_deployable": 4,
                "resources": {
                    **resources,
                    "physical_attempts": 16,
                    "successful_settled": 16,
                    "run_conservative_cny": 0.04,
                    "family_conservative_cny": 0.34,
                    "project_conservative_cny": 64.34,
                },
                "new_method": False,
                "confirmation_evaluated": False,
                "publication_ready": False,
                "private_answers": "SECRET",
            }
            mutations = [
                ("N15", lambda x: x.update(N=15)),
                ("metricN15", lambda x: x["uniform_solver"].update(N=15)),
                ("missingreference", lambda x: x["reference_arms"].pop("gold_diagnostic")),
                ("originalN15", lambda x: x["original_textflow_solver"].update(N=15)),
                ("receipts15", lambda x: x["resources"].update(successful_settled=15)),
                ("badpair", lambda x: x["paired_uniform_vs_direct"].update(net=4)),
            ]
            for name, mutate in mutations:
                bad = copy.deepcopy(full)
                mutate(bad)
                write(uniform / "SUMMARY.json", bad)
                check("incomplete uniform withheld " + name, board.diagram_summary(uniform) is None)
            write(uniform / "SUMMARY.json", full)
            safe = board.diagram_summary(uniform)
            check(
                "full16 and all historical denominators stripped to aggregate",
                safe["terminal_solver_slots"] == 16
                and len(safe["reference_arms"]) == 4
                and safe["original_textflow_solver"]["invalid"] == 3
                and "SECRET" not in json.dumps(safe)
                and "blocking_unresolved" not in safe["resources"],
            )
            check(
                "full summary retains source running state",
                board.diagram_experiment(uniform, status, protocol)["status"] == "running",
            )
            status.update(
                status="completed_scored", completed_calls=16, resources=full["resources"]
            )
            write(uniform / "STATUS.json", status)
            attempts = {
                f"{uniform.name}-{i}": {
                    "run_id": uniform.name,
                    "status": "settled",
                    "cost_cny": 0.0025,
                }
                for i in range(16)
            }
            write(study / "API_LEDGER.json", {"cap_cny": 300, "attempts": attempts})
            completed = board.snapshot()
            check(
                "uniform charges new16 and family separately no repeated historical calls",
                next(x for x in completed["experiments"] if x["name"] == uniform.name)["resources"][
                    "family_conservative_cny"
                ]
                == 0.34,
            )

        original_bytes = Path.read_bytes

        def proc_bytes(path):
            return (
                b"python\0/scripts/cvpr_textflow_solver_control.py\0--operation\0run\0"
                if str(path) == "/proc/123/cmdline"
                else original_bytes(path)
            )

        with patch.object(Path, "read_bytes", proc_bytes):
            check("exact uniform script run identity live", board.alive(123, uniform.name))
            check("uniform process not comparison identity", not board.alive(123, comparison.name))

        errors, writes, outbound = [], [], []
        with sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda req: writes.append(req.url) if req.method != "GET" else None)
            page.on(
                "request",
                lambda req: outbound.append(req.url) if not req.url.startswith(BASE) else None,
            )
            projected = [pending]
            page.route(
                "**/assets/training-free-evidence.js",
                lambda route: route.fulfill(
                    path=str(ROOT / "web/assets/training-free-evidence.js")
                ),
            )
            page.route("**/api/progress", lambda route: route.fulfill(json=projected[0]))
            page.goto(BASE + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch")
            expect(page.locator("[data-tf-diagram-action]")).to_contain_text("Current action wins")
            check(
                "overview DOM current action dynamic without stale text",
                "Stale source preparation"
                not in page.locator("[data-tf-diagram-candidate]").inner_text(),
            )
            url = (
                BASE
                + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=results&branch=FR-DIAGRAM&run="
            )
            page.goto(url + uniform.name)
            expect(page.locator("[data-tf-diagram-pending]")).to_be_visible()
            check(
                "pending DOM16newsolver no image inference or128panel",
                "5 / 16" in page.locator(".tf-run").inner_text()
                and "无新提取" in page.locator(".tf-run").inner_text()
                and "128" not in page.locator("[data-tf-diagram-pipeline]").inner_text(),
            )
            projected[0] = completed
            page.reload()
            expect(page.locator("[data-tf-diagram-results]")).to_be_visible()
            check(
                "uniform DOM one new arm five historical references two full pairs",
                page.locator("[data-tf-arm]").count() == 1
                and page.locator("[data-tf-reference-arm]").count() == 5
                and page.locator("[data-tf-diagram-paired] tbody tr").count() == 2
                and "原成绩保留" in page.locator("[data-tf-diagram-references]").inner_text(),
            )
            check(
                "uniform DOM costs no scientific promotion",
                "¥0.04" in page.locator("[data-tf-diagram-pipeline]").inner_text()
                and "¥0.34" in page.locator("[data-tf-diagram-pipeline]").inner_text()
                and "没有新方法或自动扩批结论"
                in page.locator("[data-tf-diagram-gate]").inner_text(),
            )
            page.goto(url + comparison.name)
            expect(page.locator("[data-tf-diagram-root-supported]")).to_be_visible()
            check(
                "historical comparison root supported unknown and nested next action readable",
                page.locator("[data-tf-arm]").count() == 5
                and "Strong JSON10/16"
                in page.locator("[data-tf-diagram-root-supported]").inner_text()
                and "Safe tools not run"
                in page.locator("[data-tf-diagram-root-unknown]").inner_text()
                and "未授权" in page.locator("[data-tf-diagram-root-next]").inner_text()
                and "[object Object]" not in page.locator("[data-tf-diagram-root]").inner_text(),
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(url + uniform.name)
            expect(page.locator("[data-tf-diagram-references]")).to_be_visible()
            check(
                "mobile uniform and reference tables do not overflow document",
                page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
            )
            browser.close()
        check(
            "browser no pageerrors writes or outbound requests",
            not errors and not writes and not outbound,
        )
        check(
            "all diagram reads restricted to safe files",
            all(
                p.name
                in {"PROTOCOL.json", "STATUS.json", "SUMMARY.json", "ROOT_READOUT_DECISION.json"}
                for p in reads
            ),
        )
    receipt = {
        "status": "passed",
        "N_checks": len(checks),
        "checks": checks,
        "real_model_api_calls": 0,
        "real_inputs_targets_predictions_read": 0,
        "scope": "Incremental uniform-solver + historical root safe projection/DOM fixtures only.",
    }
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports/textflow_uniform_ui_validation.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

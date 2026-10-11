#!/usr/bin/env python3
"""Synthetic read-only ZoomBench workspace projection and optional browser checks."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import progress_board as b  # noqa: E402 -- Load workspace scripts from their explicit root.

checks = []


def check(n, v):
    assert v, n
    checks.append(n)


original_read = b.read
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    study = root / "outputs/projects/fastresearch-cvpr2027/research"
    run = study / "vps/runs/fixture_zoom"
    run.mkdir(parents=True)
    report = root / "report"
    report.mkdir()
    b.ROOT = root
    b.REPORT = report

    def put(p, v):
        p.write_text(json.dumps(v))

    put(report / "STATUS_BOARD.json", {"projects": [], "axes": []})
    put(report / "sources.json", {"projects": {}})
    put(report / "EXPERIENCE_POOL.json", {"entries": []})
    protocol = {
        "kind": b.ZOOMBENCH_KIND,
        "model": "qwen3.6-27b",
        "N": 32,
        "solver_max_tokens": 8192,
        "judge_max_tokens": 2048,
        "request_digests": {"secret-id": "secret"},
        "targets_contract_sha256": "secret",
    }
    status = {
        "kind": b.ZOOMBENCH_KIND,
        "status": "solver_running",
        "pid": 0,
        "model": "qwen3.6-27b",
        "planned_samples": 32,
        "completed_solver_records": 5,
        "completed_judge_calls": 0,
        "resources": {
            "physical_attempts": 5,
            "successful_settled": 5,
            "new_unresolved": 0,
            "phase_conservative_cny": 0.05,
        },
        "private": "secret",
    }
    put(run / "PROTOCOL.json", protocol)
    put(run / "STATUS.json", status)
    put(run / "PARTIAL_SUMMARY.json", {"secret": "must not read"})
    reads = []

    def safe_read(path, default=None):
        assert not any(
            x in path.name.lower()
            for x in [
                "predictions",
                "calls.jsonl",
                "judge_requests",
                "targets",
                "score_inputs",
                "input_manifest",
                "partial_summary",
            ]
        ), str(path)
        reads.append(path.name)
        return original_read(path, default)

    b.read = safe_read

    def get():
        return b.snapshot()

    d = get()
    r = d["experiments"][0]
    check(
        "discovers_vps_run",
        r["branch_id"] == "FR-ZOOMBENCH" and r["diagnostic_kind"] == b.ZOOMBENCH_KIND,
    )
    check(
        "solver_judge_progress_distinct",
        r["completed_solver_records"] == 5
        and r["completed_judge_calls"] == 0
        and r["planned"] == 32,
    )
    check("no_incomplete_scores", r["summary"] is None and r["arms"] == [])
    check(
        "not_formal_branch",
        d["portfolio"].get("branches", []) == []
        and d["zoombench_candidate"]["role"] == "high_resolution_baseline_candidate",
    )
    check("64_logical_ceiling", r["max_logical_calls"] == 64)
    check(
        "protocol_safe_source",
        json.loads(b.source_document("run.fixture_zoom.protocol")["content"])
        == {
            k: v
            for k, v in protocol.items()
            if k not in ["request_digests", "targets_contract_sha256"]
        },
    )
    check(
        "status_safe_source",
        "private" not in b.source_document("run.fixture_zoom.status")["content"],
    )
    check("partial_unindexed", "run.fixture_zoom.partial" not in b.sources())
    summary = {
        "status": "complete",
        "kind": "zoombench_common_backbone_judge_all",
        "run_id": "fixture_zoom",
        "model": "qwen3.6-27b",
        "full_denominator": {"N": 31, "correct": 19, "accuracy": 19 / 31},
        "typed_full_denominator": {"MCQ": {"N": 16}, "OQ": {"N": 16}},
        "resources": {"blocking_unresolved": 0, "physical_attempts": 64, "successful_settled": 64},
        "judge_resources": {"logical_terminal_records": 32, "requested_judges": 32},
        "decision": {
            "coverage_gate_passed": True,
            "saturated": False,
            "solver_valid": 32,
            "judge_valid": 32,
            "next_action": "headroom_exists_review_mechanism_and_matched_controls",
        },
        "private_targets": "secret",
    }
    put(run / "SUMMARY.json", summary)
    check(
        "reject31_fullN",
        get()["experiments"][0]["summary"] is None and "run.fixture_zoom" not in b.sources(),
    )
    summary["full_denominator"] = {
        "N": 32,
        "correct": 19,
        "accuracy": 19 / 32,
        "coverage_counts": {"judge_yes": 19, "judge_no": 13},
    }
    summary["judge_resources"]["logical_terminal_records"] = 31
    put(run / "SUMMARY.json", summary)
    check("reject31_terminal", get()["experiments"][0]["summary"] is None)
    summary["judge_resources"]["logical_terminal_records"] = 32
    summary["typed_full_denominator"]["OQ"]["N"] = 15
    put(run / "SUMMARY.json", summary)
    check("reject_type_denominator_mismatch", get()["experiments"][0]["summary"] is None)
    summary["typed_full_denominator"]["OQ"]["N"] = 16
    summary["typed_full_denominator"]["MCQ"].update(correct=9, accuracy=9 / 16)
    summary["typed_full_denominator"]["OQ"].update(correct=10, accuracy=10 / 16)
    put(run / "SUMMARY.json", summary)
    d = get()
    check("accept_complete32_only", d["experiments"][0]["summary"]["full_denominator"]["N"] == 32)
    summary["resources"]["blocking_unresolved"] = 1
    put(run / "SUMMARY.json", summary)
    check("unreconciled_ledger_blocks_summary", get()["experiments"][0]["summary"] is None)
    summary["resources"]["blocking_unresolved"] = 0
    put(run / "SUMMARY.json", summary)
    check(
        "complete_summary_redacted",
        "private_targets" not in b.source_document("run.fixture_zoom")["content"],
    )
    with patch.object(
        Path,
        "read_bytes",
        return_value=b"python\0scripts/cvpr_zoombench_headroom.py\0--run-id\0fixture_zoom\0",
    ):
        check("alive_matches_run", b.alive(123, "fixture_zoom"))
        check("alive_rejects_other_run", not b.alive(123, "other"))
    check("zero_raw_reads", not any("RECEIPTS" in p or "PRIVATE" in p for p in reads))
    # Synthetic progress snapshot for the focused read-only browser; no local research sampled.
    status.update(status="judge_running", completed_solver_records=32, completed_judge_calls=7)
    put(run / "STATUS.json", status)
    (run / "SUMMARY.json").unlink()
    pending = get()
    pending["experiments"][0]["live"] = True
    pending["portfolio"]["observed_runtime"]["live_jobs"] = 1
    put(run / "SUMMARY.json", summary)
    status.update(status="completed_scored", completed_judge_calls=32)
    put(run / "STATUS.json", status)
    complete = get()
    protocol.update(
        kind=b.ZOOMBENCH_HIGHRES_KIND, vl_high_resolution_images=True, max_pixels_set=False
    )
    put(run / "PROTOCOL.json", protocol)
    highres = get()
    check(
        "highres_family_separate_label",
        highres["experiments"][0]["diagnostic_kind"] == b.ZOOMBENCH_HIGHRES_KIND
        and highres["experiments"][0]["high_resolution_control"] is True
        and "16M" in highres["experiments"][0]["title"],
    )
    check(
        "highres_protocol_parameter_visible",
        json.loads(b.source_document("run.fixture_zoom.protocol")["content"])[
            "vl_high_resolution_images"
        ]
        is True,
    )
    with patch.object(
        Path,
        "read_bytes",
        return_value=b"python\0scripts/cvpr_zoombench_highres_control.py\0--run-id\0fixture_zoom\0",
    ):
        check("highres_alive_exact_run", b.alive(123, "fixture_zoom") and not b.alive(123, "other"))
print(
    json.dumps(
        {
            "projection_checks": len(checks),
            "passed": checks,
            "scope": (
                "CPU synthetic aggregates only; no API, GT, image, "
                "private judge request or partial summary reads"
            ),
        }
    )
)

if "--url" in sys.argv:
    from playwright.sync_api import expect, sync_playwright

    url = sys.argv[sys.argv.index("--url") + 1]
    errors = []
    writes = []
    data = pending
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: writes.append(req.url) if req.method != "GET" else None)
        page.route("**/api/progress", lambda route: route.fulfill(json=data))
        page.route(
            "**/api/experiments/fastresearch/projects/fastresearch-cvpr2027/plan",
            lambda route: route.fulfill(json={}),
        )
        page.goto(
            url
            + "/#/experiments/fastresearch-cvpr2027"
            + "?origin=fastresearch&view=results&run=fixture_zoom"
        )
        card = page.locator('[data-tf-run="fixture_zoom"]')
        expect(card).to_have_count(1, timeout=30000)
        check(
            "browser_pending_solver32_judge7",
            "原图求解 32 / 32" in card.inner_text()
            and "Judge成功响应 7 / 32上限" in card.inner_text(),
        )
        check(
            "browser_pending_no_scores",
            card.locator("[data-tf-zoom-results]").count() == 0
            and card.locator("[data-tf-zoom-pending]").count() == 1,
        )
        data = complete
        page.reload()
        expect(card.locator("[data-tf-zoom-results]")).to_have_count(1, timeout=30000)
        check(
            "browser_complete_fullN_and_types",
            card.locator("[data-tf-zoom-results] tbody tr").count() == 3,
        )
        check(
            "browser_gate_stop_rules",
            "均须≥30" in card.inner_text()
            and "正确数≥28 / 32" in card.inner_text()
            and "单独准入" in card.inner_text(),
        )
        check(
            "browser_default_resolution_warning",
            "供应商默认 false / 2,621,440"
            in card.locator("[data-tf-zoom-resolution]").inner_text(),
        )
        data = highres
        page.reload()
        expect(card.locator("[data-tf-zoom-results]")).to_have_count(1, timeout=30000)
        check(
            "browser_highres16m_transparent_not_native",
            "当前显式 vl_high_resolution_images=true" in card.inner_text()
            and "16,777,216" in card.inner_text()
            and "不是新机制" in card.inner_text(),
        )
        page.screenshot(
            path=str(ROOT / "reports/zoombench_workspace_fixture_desktop.png"), full_page=True
        )
        page.set_viewport_size({"width": 390, "height": 844})
        check(
            "browser_mobile_no_overflow",
            page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
        )
        page.screenshot(
            path=str(ROOT / "reports/zoombench_workspace_fixture_mobile.png"), full_page=True
        )
        page.goto(url + "/#/experiments/fastresearch-cvpr2027?origin=fastresearch")
        expect(page.locator("[data-tf-zoom-candidate]")).to_have_count(1, timeout=30000)
        check(
            "browser_separate_candidate_not_formal",
            "不增加正式分支数" in page.locator("[data-tf-zoom-candidate]").inner_text()
            and page.locator("[data-tf-branch]").count() == 0,
        )
        check("browser_readonly_no_errors", not errors and not writes)
        browser.close()
    out = {
        "checks": len(checks),
        "passed": checks,
        "scope": (
            "synthetic safe aggregate projection/browser; no actual run polling, "
            "API generation, GT, images or private judge requests"
        ),
        "browser_errors": errors,
    }
    (ROOT / "reports/zoombench_workspace_validation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(out, ensure_ascii=False))

#!/usr/bin/env python3
"""Check the running local website, its file boundary, and key browser workflows.

Uses an isolated browser profile and temporary cache fixtures. Research files,
the user's bookmarks, model endpoints, and paid services are never modified.
Playwright must already be installed for the browser checks.
"""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    checks = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({"check": name, "passed": True})

    def request(path, method="GET", headers=None):
        req = urllib.request.Request(args.url + path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    original_sha = hashlib.sha256((ROOT / "data/research_registry.json").read_bytes()).hexdigest()
    status, data, headers = request("/api/state")
    check("live_state_endpoint", status == 200)
    state = json.loads(data)
    registry = state["registry"]
    check("state_matches_reviewed_local_registry", registry == json.loads((ROOT / "data/research_registry.json").read_text()))
    check("health_endpoint", json.loads(request("/api/health")[1])["ok"])
    check("conditional_etag", request("/api/state", headers={"If-None-Match": headers["ETag"]})[0] == 304)
    check("utf8_csv_export", len(list(csv.DictReader(io.StringIO(request("/downloads/scores.csv")[1].decode("utf-8-sig"))))) == len(registry["results"]))
    check("json_export", json.loads(request("/downloads/registry.json")[1])["as_of"] == registry["as_of"])
    for path in ["/.env", "/AGENTS.md", "/configs/bailian_blink_dev_v3.json", "/data/research_registry.json", "/scripts/serve_web.py", "/assets/%2e%2e/%2e%2e/README.md", "/api/document?path=../../.ssh/id_rsa"]:
        check("deny_" + path, request(path)[0] == 404)
    check("reject_http_writes", request("/api/state", method="POST")[0] == 405)
    check("allowed_document", request("/api/document?path=docs/WEB_DEPLOYMENT.md")[0] == 200)
    check("no_external_script_policy", "script-src 'self'" in headers["Content-Security-Policy"])

    # Exercise the actual server cache on a separate copy, without changing live evidence.
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("web_cache_fixture", ROOT / "scripts/serve_web.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    candidates = sorted(registry["research_candidates"], key=lambda c: c["rank"])
    check("top_five_reviewed_candidates", len(candidates) == 5 and [c["rank"] for c in candidates] == list(range(1, 6)))
    for name, mutate in [
        ("candidate_duplicate_rank_rejected", lambda d: d["research_candidates"][1].update(rank=d["research_candidates"][0]["rank"])),
        ("candidate_missing_method_rejected", lambda d: d["research_candidates"][0].update(method_ids=["MISSING"])),
        ("candidate_unrelated_score_rejected", lambda d: d["research_candidates"][0].update(result_ids=candidates[0]["result_ids"])),
        ("candidate_missing_gate_rejected", lambda d: d["research_candidates"][0].update(first_gate="")),
    ]:
        invalid = json.loads(json.dumps(registry))
        mutate(invalid)
        try:
            module.research_registry.validate(invalid)
        except ValueError:
            check(name, True)
        else:
            raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix="fastresearch-web-check-") as directory:
        fixture = Path(directory)
        paths = []
        for source in module.FILES:
            target = fixture / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            paths.append(target)
        module.ROOT = fixture
        module.FILES = paths
        module.CACHE = {}
        first = module.state()
        changed = json.loads(paths[0].read_text())
        scope = changed["scope"]
        changed["scope"] += " / temporary website cache check"
        module.research_registry.dump(paths[0], changed)
        second = module.state()
        check("local_file_updates_refresh_cache", first["etag"] != second["etag"])
        check("prior_snapshot_remains_immutable", first["payload"]["registry"]["scope"] == scope)
        title = changed["research_candidates"][0]["title"]
        changed["research_candidates"][0]["title"] += " / temporary candidate update"
        module.research_registry.dump(paths[0], changed)
        third = module.state()
        check("candidate_updates_refresh_cache", third["etag"] != second["etag"] and third["payload"]["registry"]["research_candidates"][0]["title"] != title)
        # A report-only edit must alter the /api/state ETag used by page sync.
        probe = fixture / 'report-latest.md'
        probe.write_text('current source snapshot')
        original_sources = module.progress_board.sources
        try:
            module.progress_board.sources = lambda: {'report-probe': probe}
            report_first = module.state()
            probe.write_text('updated source snapshot with new results')
            report_second = module.state()
            check('report_only_update_changes_sync_etag', report_first['etag'] != report_second['etag'])
            check('progress_revision_exposed_for_sync', report_first['payload']['service']['progress_revision'] != report_second['payload']['service']['progress_revision'])
        finally:
            module.progress_board.sources = original_sources
        changed["results"][0]["value"] = "not a score"
        module.research_registry.dump(paths[0], changed)
        try:
            module.state()
        except ValueError:
            check("invalid_new_data_not_silently_served", True)
        else:
            raise AssertionError("invalid data was accepted")

    from playwright.sync_api import sync_playwright
    browser_errors, console_errors = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.goto(args.url)
        page.wait_for_selector(".hero h1")
        check("overview_real_counts", page.locator(".stat-value").all_text_contents() == [str(len(registry[name])) for name in ["benchmarks", "results", "methods"]] + [str(len(state["inbox"]["items"]))])
        check("overview_top_five_order", page.locator("[data-candidate]").evaluate_all("rows=>rows.map(x=>x.dataset.candidate)") == [c["id"] for c in candidates])
        check("top_five_before_coverage_panels", page.evaluate("Boolean(document.querySelector('.candidate-panel').compareDocumentPosition(document.querySelector('.grid-two')) & Node.DOCUMENT_POSITION_FOLLOWING)"))
        result_index = {r["id"]: r for r in registry["results"]}
        for c in candidates:
            row = page.locator(f'[data-candidate="{c["id"]}"]')
            check("candidate_pair_" + c["id"], c["title"] in row.inner_text() and row.locator(".candidate-benchmarks a").count() == len(c["benchmark_ids"]) and row.locator(".candidate-methods button").count() == len(c["method_ids"]))
            check("candidate_scores_from_registry_" + c["id"], row.locator("[data-candidate-score]").evaluate_all("rows=>rows.map(x=>x.dataset.candidateScore)") == c["result_ids"] and all(f'{result_index[r]["value"]:g}{result_index[r]["unit"]}' in row.locator(f'[data-candidate-score="{r}"] .candidate-score').inner_text() for r in c["result_ids"]))
        page.locator(".candidate-policy summary").click()
        check("candidate_ranking_includes_negative_evidence", "BLINK" in page.locator(".candidate-policy").inner_text() and "未见稳定" in page.locator(".candidate-policy").inner_text())
        page.locator('[data-action="candidate-detail"][data-value="C01"]').first.click()
        check("candidate_detail_complete_gates", all(next(c for c in candidates if c["id"] == "C01")[key] in page.locator("#dialog-body").inner_text() for key in ["first_gate", "execution_conditions", "novelty_risk", "one_week_plan"]))
        page.locator('#dialog-body [data-action="method-detail"][data-value="M06"]').click()
        check("candidate_opens_nearest_method", page.locator("#dialog-title").inner_text() == "DeepScan")
        page.click("#dialog-close")
        page.locator('[data-candidate="C01"] [data-action="score-detail"]').first.click()
        check("candidate_opens_score_protocol", "Qwen2.5-VL-7B" in page.locator("#dialog-body").inner_text() and "外部组件训练" in page.locator("#dialog-body").inner_text())
        page.click("#dialog-close")
        page.locator('[data-candidate="C01"] .candidate-benchmarks a').first.click()
        page.locator('#main h1', has_text='HR-Bench').wait_for(state='visible')
        check("candidate_opens_benchmark", "HR-Bench" in page.locator("#main h1").inner_text())
        page.goto(args.url + "/#/documents?path=docs%2Fregistry%2FTOP_CANDIDATES.md")
        page.wait_for_selector(".document h1")
        check("candidate_generated_document", page.locator(".document h2").count() == 5 and "TestPrism" in page.locator(".document").inner_text())
        page.fill("#global-search", candidates[0]["title"])
        page.wait_for_selector('#global-results [data-action="candidate-detail"]')
        page.locator('#global-results [data-action="candidate-detail"]').first.click()
        check("candidate_topic_global_search", candidates[0]["title"] in page.locator("#dialog-title").inner_text())
        page.click("#dialog-close")
        for path in ["benchmarks", "scores", "methods", "hotspots", "ideas", "shortlist", "evidence"]:
            page.goto(args.url + "/#/" + path)
            page.wait_for_selector("#main h1")
            check("page_" + path, bool(page.locator("#main h1").inner_text()))
        page.goto(args.url + "/#/benchmarks?coverage=missing")
        page.wait_for_selector("[data-benchmark]")
        check("accepted_evidence_gap_filter", page.locator("[data-benchmark]").count() == sum(b["coverage"]["accepted_anchor_missing"] for b in registry["benchmarks"]))
        page.goto(args.url + "/#/benchmarks")
        page.wait_for_selector("[data-benchmark]")
        page.click('[data-action="page"][data-value="2"]')
        check("benchmark_pagination", page.locator("[data-benchmark]").count() == min(24, len(registry["benchmarks"])-24))
        page.goto(args.url + "/#/benchmarks/B03")
        page.wait_for_selector("[data-score]")
        page.select_option('[data-filter="subset"]', "HardBLINK Depth")
        check("hardblink_version_filter", page.locator("[data-score]").count() == min(25, sum(r["benchmark_id"] == "B03" and r["subset"] == "HardBLINK Depth" for r in registry["results"])))
        page.locator("[data-compare]").nth(0).check()
        page.locator("[data-compare]").nth(1).check()
        page.click('[data-action="compare"]')
        check("comparison_reports_unknown_sample", "未知" in page.locator("#dialog-body .note").inner_text())
        page.click("#dialog-close")
        page.locator("[data-compare]").nth(2).check()
        page.locator("[data-compare]").nth(3).check()
        page.locator("[data-compare]").nth(4).click()
        check("comparison_limited_to_four", page.locator("[data-compare]:checked").count() == 4)
        page.click('[data-action="compare"]')
        check("comparison_flags_different_models", "不同项" in page.locator("#dialog-body .note").inner_text())
        page.click("#dialog-close")
        page.click('[data-action="clear-comparison"]')
        page.locator('[data-action="score-detail"]').first.click()
        check("score_detail_exposes_budget_and_training", "推理预算" in page.locator("#dialog-body").inner_text() and "训练方式" in page.locator("#dialog-body").inner_text())
        page.click("#dialog-close")
        page.goto(args.url + "/#/methods")
        page.wait_for_selector("[data-method]")
        page.select_option('[data-filter="priority"]', "0")
        check("method_priority_filter", page.locator("[data-method]").count() == min(24, sum(m["priority"] == 0 for m in registry["methods"])))
        page.locator('[data-action="method-detail"]').first.click()
        check("method_detail_shows_nearest_neighbor", "novelty" in page.locator("#dialog-body").inner_text())
        page.click("#dialog-close")
        page.goto(args.url + "/#/benchmarks/B03")
        page.wait_for_selector("[data-score]")
        page.locator('[data-action="favorite"][data-value="benchmark:B03"]').first.click()
        page.goto(args.url + "/#/shortlist")
        page.wait_for_selector("[data-note]")
        page.locator("[data-note]").fill("核实同专家总预算与独立场景。")
        page.reload()
        page.wait_for_selector("[data-note]")
        check("bookmark_persists_reload", "BLINK" in page.locator("#main").inner_text())
        check("research_note_persists_reload", page.locator("[data-note]").input_value() == "核实同专家总预算与独立场景。")
        page.fill("#global-search", "TestHelix")
        page.wait_for_selector("#global-results button")
        page.locator("#global-results button").first.click()
        check("global_search_opens_method", "TestHelix" in page.locator("#dialog-title").inner_text())
        page.click("#dialog-close")
        page.goto(args.url + "/#/documents?path=docs%2FRESEARCH_REGISTRY.md")
        page.wait_for_selector(".document h1")
        check("markdown_document_view", page.locator(".document table").count() > 0)
        check("document_registry_download_mapping", page.locator('.document a[href="/downloads/registry.json"]').count() > 0)
        page.goto(args.url + "/#/scores?q=VERDICT")
        page.wait_for_selector("[data-score]")
        check("uncertainty_retained", "±0.48" in page.locator("[data-testid=scores-table]").inner_text())
        page.fill('[data-filter="q"]', "<script>alert(1)</script>")
        page.wait_for_selector(".empty")
        check("literal_search_no_injection", page.locator(".empty").count() == 1)
        page.goto(args.url + "/#/overview")
        page.wait_for_selector(".hero h1")
        page.screenshot(path=str(ROOT / "reports/fastresearch_web_home_desktop.png"), full_page=True)
        mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        mobile.goto(args.url)
        mobile.wait_for_selector(".hero h1")
        check("mobile_no_body_overflow", mobile.evaluate("document.documentElement.scrollWidth === innerWidth"))
        check("mobile_top_five_visible", mobile.locator("[data-candidate]").count() == 5)
        mobile.locator('[data-action="candidate-detail"][data-value="C05"]').first.click()
        check("mobile_candidate_detail_no_overflow", mobile.locator("#detail-dialog").evaluate("x=>x.scrollWidth <= x.clientWidth") and next(c for c in candidates if c["id"] == "C05")["first_gate"] in mobile.locator("#dialog-body").inner_text())
        mobile.click("#dialog-close")
        mobile.click("#menu-toggle")
        mobile.click('.nav-link[href="#/benchmarks"]')
        mobile.wait_for_selector("[data-benchmark]")
        check("mobile_navigation", not mobile.locator("#sidebar").evaluate("x=>x.classList.contains('open')"))
        mobile.goto(args.url + "/#/overview")
        mobile.wait_for_selector(".hero h1")
        mobile.screenshot(path=str(ROOT / "reports/fastresearch_web_home_mobile.png"), full_page=True)
        check("browser_no_javascript_errors", not browser_errors)
        check("browser_no_console_errors", not console_errors)
        browser.close()

    check("research_registry_unchanged", hashlib.sha256((ROOT / "data/research_registry.json").read_bytes()).hexdigest() == original_sha)
    enabled = subprocess.run(["systemctl", "--user", "is-enabled", "fastresearch-web.service"], text=True, capture_output=True)
    active = subprocess.run(["systemctl", "--user", "is-active", "fastresearch-web.service"], text=True, capture_output=True)
    check("user_service_enabled", enabled.stdout.strip() == "enabled")
    check("user_service_running", active.stdout.strip() == "active")
    verified_on = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    result = {"verified_on": verified_on, "research_as_of": registry["as_of"], "url": args.url, "checks": checks,
              "passed_checks": len(checks), "browser_errors": browser_errors, "console_errors": console_errors,
              "deployment": {"service": "fastresearch-web.service", "enabled": True, "active": True, "bind": "127.0.0.1:8765", "starts_on_user_login": True},
              "counts": {k: len(registry[k]) for k in ("benchmarks", "results", "methods", "ideas")},
              "research_registry_sha256": original_sha, "model_calls": 0,
              "screenshots": ["reports/fastresearch_web_home_desktop.png", "reports/fastresearch_web_home_mobile.png"]}
    output = ROOT / "reports" / ("fastresearch_web_validation_" + verified_on.replace("-", "") + ".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed_checks": len(checks), "url": args.url, "report": str(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

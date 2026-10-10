#!/usr/bin/env python3
"""Check source contracts, time conversion and the CCF submission interface."""
import json
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright

from sync_venues import deadline

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"


def main():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append({"check": name, "passed": True})

    def request(method="GET", headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/api/venues", method=method, headers=headers or {}), timeout=15) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    check("aoe_date_rollover", deadline("2026-11-16 23:59:59", "AoE")["utc"] == "2026-11-17T11:59:59+00:00")
    check("pacific_winter", deadline("2026-01-01 23:59:59", "PT")["utc"] == "2026-01-02T07:59:59+00:00")
    check("pacific_summer_dst", deadline("2026-07-01 23:59:59", "PT")["utc"] == "2026-07-02T06:59:59+00:00")
    check("unpublished_and_unknown_timezone_not_invented", deadline("TBD", "AoE")["utc"] is None and deadline("2026-11-16 23:59:59", "unknown")["utc"] is None)
    status, headers, body = request()
    check("catalogue_available", status == 200)
    data = json.loads(body)
    check("ab_only_ten_domains", set(data["categories"]) == {"DS", "NW", "SC", "SE", "DB", "CT", "CG", "AI", "HI", "MX"} and all(v["rank"] in {"A", "B"} for v in data["venues"]))
    check("journal_no_fabricated_submission_date", all(not v["editions"] and v["submission_url"] is None for v in data["venues"] if v["kind"] == "journal"))
    check("multidomain_journals_deduplicated", len([v for v in data["venues"] if v["abbreviation"] == "TOMM"]) == 1 and len(next(v for v in data["venues"] if v["abbreviation"] == "TOMM")["categories"]) == 2)
    check("pinned_sources_and_mirror_limitation", len(data["sources"]["conferences"]["commit"]) == 40 and "not independently verified" in data["sources"]["journals"]["access_note"])
    check("conditional_fetch", request(headers={"If-None-Match": headers["ETag"]})[0] == 304)
    check("http_catalogue_writes_denied", request("POST")[0] == 405)
    errors, outbound = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: outbound.append(req.url) if not req.url.startswith(BASE) else None)
        page.goto(BASE + "/#/program")
        expect(page.get_by_role("heading", name="投稿规划", exact=True)).to_be_visible()
        expect(page.locator(".venue-card")).to_have_count(24)
        check("unified_brand_and_five_stages", "SciTaste" in page.title() and page.locator(".research-stages > div").count() == 5 and "CVPR 研究计划" not in page.locator("#navigation").inner_text())
        page.get_by_label("类型", exact=True).select_option("journal")
        page.get_by_label("等级", exact=True).select_option("A")
        page.get_by_label("领域", exact=True).select_option("AI")
        expect(page.locator(".venue-card")).to_have_count(4)
        check("journal_filters_and_truthful_date", "TPAMI" in page.locator(".venue-grid").inner_text() and "征稿日期待核实" in page.locator(".venue-grid").inner_text())
        page.locator(".venue-card").first.locator("[data-program-save]").click()
        page.reload()
        expect(page.locator(".venue-shortlist")).to_contain_text("1")
        check("shortlist_persists", len(json.loads(page.evaluate("localStorage.getItem('scitaste.venue_shortlist')"))) == 1)
        page.goto(BASE + "/#/program?q=CVPR")
        expect(page.locator(".venue-card")).to_have_count(1)
        page.locator(".venue-card summary").click()
        expect(page.locator(".venue-timeline")).to_contain_text("北京时间")
        expect(page.locator(".venue-timeline")).to_contain_text("原记录")
        check("conference_rounds_and_original_timezones", "2027" in page.locator(".venue-card h2").inner_text())
        page.goto(BASE + "/#/program?kind=conference&window=upcoming")
        expect(page.locator(".venue-card").first).to_be_visible()
        check("upcoming_filter_excludes_past", "已截稿" not in page.locator(".venue-grid").inner_text())
        page.screenshot(path=str(ROOT / "reports/scitaste_program_desktop_20261010.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + "/#/program?q=CVPR")
        expect(page.locator(".venue-card")).to_have_count(1)
        page.locator(".venue-card summary").click()
        check("mobile_expanded_timeline_no_overflow", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        page.screenshot(path=str(ROOT / "reports/scitaste_program_mobile_20261010.png"), full_page=True)
        check("no_browser_errors_or_external_calls", not errors and not outbound)
        browser.close()
    report = {"date": datetime.now().astimezone().isoformat(), "checks": checks, "passed": True,
              "venues": len(data["venues"]), "counts": data["counts"], "model_calls": 0}
    (ROOT / "reports/scitaste_program_validation_20261010.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

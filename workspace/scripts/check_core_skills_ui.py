"""Browser integration of core skill viewing, complete handoff and downloads."""

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--skill",
        default="research-report",
        choices=["research-report", "research-paper-iteration"],
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    checks = []
    errors = []
    mutations = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "request",
            lambda r: mutations.append(r.url) if r.method not in {"GET", "HEAD"} else None,
        )
        page.goto(base + "/#/skills")
        card = page.locator('[data-core-skill="' + args.skill + '"]')
        card.wait_for(timeout=60000)
        check(
            page.locator("nav a[aria-current=page]").inner_text().strip().endswith("核心技能"),
            "core skill discoverable in platform navigation",
        )
        card.locator("a").click()
        page.locator("[data-skill-prepare]").wait_for()
        check(
            page.locator(".skill-documents details").count()
            == (3 if args.skill == "research-report" else 4),
            "full selected skill and references visible",
        )
        malicious = '<img src=x onerror="window.__skillXSS=1">'
        page.locator("#skill-project").fill("my-paper")
        page.locator("#skill-goal").fill(malicious)
        page.locator("[data-skill-prepare]").click()
        page.locator("#skill-task").wait_for(state="visible")
        value = page.locator("#skill-prompt").input_value()
        check(
            "my-paper" in value
            and json.dumps(malicious, ensure_ascii=False) in value
            and "SKILL.md" in value,
            "project goal and full skill enter task",
        )
        check(not page.evaluate("Boolean(window.__skillXSS)"), "task user content stays literal")
        check(
            "等待执行助手" in page.locator("#skill-status").inner_text(),
            "preparation not labelled execution",
        )
        with tempfile.TemporaryDirectory() as temp:
            with page.expect_download() as pending:
                page.locator("#skill-task-download").click()
            download = pending.value
            path = Path(temp) / "task.zip"
            download.save_as(path)
            archive = zipfile.ZipFile(path)
            metadata = json.loads(archive.read("TASK.json"))
            check(
                archive.read("TASK.md").decode() == value, "download is the exact prepared prompt"
            )
            manifest = json.loads(archive.read("MANIFEST.json"))
            check(
                metadata["skill_revision"] == manifest["revision"],
                "download bound to displayed skill revision",
            )
            check(
                all(
                    hashlib.sha256(archive.read(f["path"])).hexdigest() == f["sha256"]
                    for f in manifest["files"]
                ),
                "download checksums verified",
            )
        check(
            page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
            "desktop no horizontal overflow",
        )
        mobile = browser.new_page(viewport=dict(width=390, height=844))
        mobile.goto(base + "/#/skills/" + args.skill)
        mobile.locator("[data-skill-prepare]").wait_for(timeout=60000)
        check(
            mobile.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
            "mobile no horizontal overflow",
        )
        # Registered content must render as literal text even if future instructions include HTML.
        if args.skill == "research-paper-iteration":
            check(
                page.locator(".skill-workflow li").count() == 6, "paper iteration workflow visible"
            )
        with urlopen(base + "/api/skills?skill=" + args.skill) as response:
            doc = json.load(response)
        doc["documents"][0]["content"] = malicious
        page.route("**/api/skills?skill=" + args.skill, lambda route: route.fulfill(json=doc))
        page.goto(base + "/#/skills/" + args.skill)
        page.reload()
        page.locator(".skill-documents").wait_for()
        check(
            malicious in page.locator(".skill-documents").inner_text()
            and not page.evaluate("Boolean(window.__skillXSS)"),
            "instruction text escaped literally",
        )
        check(not errors and not mutations, "browser has no errors or mutating requests")
        browser.close()
    print(json.dumps(dict(passed_checks=len(checks), checks=checks, model_calls=0)))


if __name__ == "__main__":
    main()

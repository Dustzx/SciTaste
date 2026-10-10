#!/usr/bin/env python3
"""Exercise the product adapter on isolated metadata; no models or GPU jobs.

The backend uses FastResearch's owned environment. The browser uses the existing Playwright
installation in the caller's Python. Historical source projects remain read-only.
"""
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/scitaste"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_signature():
    projects = SOURCE / "outputs/projects"
    return {str(p.relative_to(SOURCE)): digest(p) for pattern in ("*/PROJECT.json", "*/runs/*/RESULT*.json", "*/.generative-ui/audits/*") for p in projects.glob(pattern) if p.is_file()}


def main():
    from playwright.sync_api import sync_playwright
    checks, errors = [], []
    def check(name, passed):
        if not passed:
            raise AssertionError(name)
        checks.append({"check": name, "passed": True})

    before = historical_signature()
    research_before = digest(ROOT / "data/research_registry.json")
    stopped = ROOT / "reports/bailian_blink_dev_v3/EXECUTION_STATUS.json"
    stopped_before = digest(stopped)
    with tempfile.TemporaryDirectory(prefix="fastresearch-product-check-") as temp:
        root = Path(temp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        code = "import sys; sys.path.insert(0,sys.argv[1]); import serve_web as w; from scitaste_bridge import ExperimentBridge; w.BRIDGE=ExperimentBridge(sys.argv[2]); sys.argv=['serve_web','--port',sys.argv[3]]; w.main()"
        log = (root / "server.log").open("w+")
        process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-c", code, str(ROOT / "scripts"), str(root), str(port)], stdout=log, stderr=log)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, method="GET", body=None, headers=None):
            encoded = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(url + path, data=encoded, method=method, headers={"Content-Type": "application/json", **(headers or {})})
            try:
                with opener.open(req, timeout=120) as response:
                    data = response.read()
                    return response.status, json.loads(data) if response.headers.get_content_type() == "application/json" else data
            except urllib.error.HTTPError as error:
                raw = error.read()
                try: data = json.loads(raw)
                except json.JSONDecodeError: data = {"error": raw.decode(errors="replace")[:500]}
                return error.code, data
        try:
            for _ in range(60):
                try:
                    if request("/api/health")[0] == 200: break
                except OSError: time.sleep(.1)
            else: raise RuntimeError("isolated backend did not start")
            status = request("/api/experiments/status")[1]
            check("no_live_model_or_gpu_transport", status["execution"] == {"live_models": False, "gpu_launch": False, "protocol_registration": True})
            auth = {"X-FastResearch-CSRF": status["csrf_token"]}
            path = "/api/experiments/fastresearch/projects"
            body = {"project_id": "adapter-fixture", "title": "Protocol fixture", "research_direction": "Check paired evidence and unknown resources"}
            check("write_requires_current_page_token", request(path, "POST", body)[0] == 403)
            check("reject_cross_origin_metadata_write", request(path, "POST", body, {**auth,"Origin":"https://example.com"})[0] == 403)
            check("reject_host_rebinding", request("/api/experiments/status", headers={"Host":"evil.invalid"})[0] == 403)
            check("research_remains_reviewed_patch_only", request("/api/state", "POST", {})[0] == 405)
            check("reject_extra_execution_authority", request(path, "POST", {**body,"command":"run-model"},auth)[0] == 400)
            check("create_metadata_project", request(path,"POST",body,auth)[0] == 201)
            check("duplicate_project_does_not_overwrite", request(path,"POST",body,auth)[0] == 409)
            check("reject_traversal_project", request(path,"POST",{**body,"project_id":"../escape"},auth)[0] == 400)
            check("legacy_metadata_write_denied", request("/api/experiments/scitaste/projects","POST",body,auth)[0] == 403)
            base = path + "/adapter-fixture"
            protocol = {"run_id":"baseline","expected_revision":0,"title":"Frozen baseline","model_id":"qwen3.8-max-0902","model_revision":"record returned model before execution","training_free":True,"baseline":"fixture @ abc123","benchmark":"CharXiv pinned","split":"dev","scorer":"fixture-v1","budget_calls":12,"budget_tokens":12000,"storage_gib":None,"vram_gib":0,"host":"API client","stop_condition":"Stop if no paired gain"}
            check("protocol_cannot_smuggle_executor", request(base+"/protocols","POST",{**protocol,"command":"run"},auth)[0] == 400)
            check("protocol_rejects_fake_measured_resource", request(base+"/protocols","POST",{**protocol,"vram_gib":True},auth)[0] == 400)
            result = request(base+"/protocols","POST",protocol,auth)
            check("register_protocol_without_execution", result[0] == 201 and result[1]["execution_authority"] == "none")
            saved = json.loads((root/"outputs/projects/adapter-fixture/runs/baseline/PROTOCOL.json").read_text())
            check("unknown_storage_preserved_not_zero", saved["storage_gib"] is None)
            check("protocol_model_scorer_and_budget_persist", all(saved[k] == protocol[k] for k in ("model_id","model_revision","baseline","scorer","split","budget_calls","budget_tokens")))
            check("stale_protocol_revision_rejected", request(base+"/protocols","POST",{**protocol,"run_id":"stale"},auth)[0] == 409)
            revision = result[1]["revision"]
            candidate = {**protocol,"run_id":"candidate","title":"Frozen candidate","expected_revision":revision}
            check("second_protocol_registered", request(base+"/protocols","POST",candidate,auth)[0] == 201)
            for view in status["views"]:
                query = "?view="+view + ("&baseline_run_id=baseline&candidate_run_id=candidate" if view == "run-comparison" else "")
                response = request(base+"/workspace"+query)
                check("native_view_"+view, response[0] == 200 and bool(response[1]["renderer"]["components"]))
                if view == "run-comparison":
                    comparison = response[1]["renderer"]["components"][0]["data"]
                    check("comparison_does_not_fabricate_completed_metrics", comparison["metrics_state"] == "unavailable" and not comparison["metrics"])
            protocols = request(base+"/protocols")[1]
            baseline = next(p for p in protocols["protocols"] if p["run_id"] == "baseline")
            binding = {"run_id":"baseline","sha256":baseline["sha256"],"expected_revision":protocols["revision"]}
            inspected = request(base+"/protocol-inspections","POST",binding,auth)
            check("hash_bound_protocol_preview", inspected[0] == 200 and inspected[1]["protocol"]["status"] == "planned")
            check("reject_stale_protocol_binding", request(base+"/protocol-inspections","POST",{**binding,"sha256":"0"*64},auth)[0] == 409)
            # Inspect an actual historical artifact without writing its audit.
            legacy_id = "scitaste-offline-full"
            legacy = "/api/experiments/scitaste/projects/"+legacy_id
            response = request(legacy+"/workspace?view=project-overview")
            check("legacy_native_read_without_source_writes", response[0] == 200)
            renderer = response[1]["renderer"]
            artifact = next(c for c in renderer["components"] if c["renderer"] == "ArtifactViewer")
            event = {"schema_version":"1.0","event_id":"fixture-"+uuid.uuid4().hex,"project_id":legacy_id,"surface_id":renderer["surface_id"],"surface_revision":renderer["surface_revision"],"surface_fingerprint":renderer["surface_fingerprint"],"snapshot_revision":renderer["snapshot"]["snapshot_revision"],"snapshot_sha256":renderer["snapshot"]["snapshot_sha256"],"event_type":"artifact_inspection_requested","artifact_ref_id":artifact["data"]["artifact_ref_id"]}
            inspection = request(legacy+"/inspections?view=project-overview","POST",event,auth)
            ref = next(r for r in renderer["snapshot"]["evidence_refs"] if r["evidence_id"] == event["artifact_ref_id"])
            check("native_hash_bound_historical_artifact", inspection[0] == 200 and inspection[1]["receipt"]["artifact_sha256"] == ref["sha256"])
            check("reject_stale_native_artifact_binding", request(legacy+"/inspections?view=project-overview","POST",{**event,"event_id":"stale-"+uuid.uuid4().hex,"snapshot_sha256":"0"*64},auth)[0] == 400)
            check("historical_audits_and_manifests_unchanged", historical_signature() == before)

            with sync_playwright() as engine:
                browser = engine.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width":1440,"height":1000})
                page.on("pageerror",lambda error: errors.append(str(error)))
                page.goto(url+"/#/resources")
                page.wait_for_selector("#main h1")
                check("resources_models_and_storage_policy_visible", "qwen3.8-max-0902" in page.locator("#main").inner_text() and "存储大小不参与" in page.locator("#main").inner_text())
                page.screenshot(path=str(ROOT/"reports/fastresearch_resources_desktop.png"),full_page=True)
                page.goto(url+"/#/methods?tf=training_free&code=verified_code")
                page.wait_for_selector("[data-method]")
                check("training_free_open_code_filter", page.locator("[data-method]").evaluate_all("x=>x.map(v=>v.dataset.method)") == ["M06","M30"])
                page.evaluate("registry.methods.find(m=>m.id==='M06').resources.storage_gib=999999; registry.methods.find(m=>m.id==='M30').resources.storage_gib=1; render()")
                check("storage_labels_do_not_change_method_order", page.locator("[data-method]").evaluate_all("x=>x.map(v=>v.dataset.method)") == ["M06","M30"])
                page.goto(url+"/#/experiments")
                page.wait_for_selector("[data-lab-project]")
                check("historical_gallery_and_owned_projects_visible", "完整研究桌面" in page.locator("#main").inner_text() and "adapter-fixture" in page.locator("#main").inner_text())
                page.goto(url+"/#/overview")
                page.wait_for_selector("[data-candidate]")
                page.locator('[data-candidate="C02"] [data-lab-action="candidate-project"]').click()
                check("candidate_prefills_project_gate", "CharXiv" in page.locator('[name="research_direction"]').input_value())
                page.locator('[name="project_id"]').fill("browser-fixture")
                page.locator("#lab-create-form button").click()
                page.wait_for_selector(".lab-provenance")
                check("candidate_to_native_workspace", "browser-fixture" in page.url and page.locator('[data-lab-component="ProjectProgressBoard"]').count() == 1)
                page.locator('[data-lab-action="protocol"]').click()
                values = {"run_id":"browser-run","title":"One-week frozen plan","model_id":"qwen3.8-max-0902","baseline":"verified-code @ abc","benchmark":"CharXiv","split":"dev","scorer":"pinned-v1","stop_condition":"No paired gain -> stop"}
                for key,value in values.items(): page.locator(f'#lab-protocol-form [name="{key}"]').fill(value)
                page.locator("#lab-protocol-form button").click()
                page.wait_for_selector('[data-lab-component="RunStageExplorer"]')
                check("browser_protocol_stays_planned", "browser-run" in page.locator("#main").inner_text() and "协议已登记" in page.locator("#main").inner_text())
                page.locator('[data-lab-action="protocol-inspect"]').first.click()
                page.wait_for_selector(".lab-artifact-text")
                check("browser_artifact_preview_inert", '"execution_authority": "none"' in page.locator(".lab-artifact-text").inner_text())
                page.click("#dialog-close")
                page.goto(url+"/#/experiments/browser-fixture?origin=fastresearch&view=conversations")
                page.wait_for_selector('[data-lab-action="conversation"]')
                page.locator('[data-lab-action="conversation"]').click()
                page.locator('#lab-conversation-form [name="question"]').fill("查看项目进度和下一步门槛")
                page.locator("#lab-conversation-form button").click()
                page.wait_for_selector('[data-lab-action="conversation-open"]')
                check("persistent_evidence_conversation", page.locator('[data-lab-action="conversation-open"]').count() == 1)
                page.locator('#main [data-lab-action="conversation-open"]').click()
                page.locator('[data-lab-action="turn-open"]').click()
                page.wait_for_function("() => document.querySelector('#dialog-title').textContent.includes('第 1 轮')")
                check("native_turn_document_opens", "第 1 轮" in page.locator("#dialog-title").inner_text())
                page.locator('#dialog-body [data-lab-action="conversation-open"]').click()
                page.locator('[data-lab-action="follow-up"]').click()
                page.locator('#lab-followup-form [name="question"]').fill("查看项目进度")
                page.locator("#lab-followup-form button").click()
                page.wait_for_selector('[data-lab-action="conversation-open"]')
                page.locator('[data-lab-action="conversation-open"]').click()
                page.wait_for_function("() => document.querySelectorAll('[data-lab-action=turn-open]').length === 2")
                check("followup_preserves_previous_turn", page.locator('[data-lab-action="turn-open"]').count() == 2)
                page.locator('[data-lab-action="rename-conversation"]').click()
                page.locator('#lab-rename-form [name="title"]').fill("图表绑定证据记录")
                page.locator("#lab-rename-form button").click()
                page.wait_for_function("() => document.querySelector('#main').textContent.includes('图表绑定证据记录')")
                check("rename_conversation_metadata", "图表绑定证据记录" in page.locator("#main").inner_text())
                page.reload(); page.wait_for_selector('[data-lab-action="conversation-open"]')
                check("conversation_survives_reload", "图表绑定证据记录" in page.locator("#main").inner_text())
                page.goto(url+"/#/experiments/adapter-fixture?origin=fastresearch&view=run-comparison")
                page.wait_for_selector("#lab-compare-form")
                page.locator('[name="baseline_run_id"]').select_option("baseline")
                page.locator('[name="candidate_run_id"]').select_option("candidate")
                page.locator("#lab-compare-form button").click()
                page.wait_for_selector('[data-lab-component="RunComparisonPanel"]')
                check("browser_native_paired_comparison", "baseline" in page.locator("#main").inner_text() and "candidate" in page.locator("#main").inner_text())
                page.screenshot(path=str(ROOT/"reports/fastresearch_experiments_desktop.png"),full_page=True)
                mobile = browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
                mobile.on("pageerror",lambda error:errors.append(str(error)))
                for route in ("resources","experiments/browser-fixture?origin=fastresearch","experiments/adapter-fixture?origin=fastresearch&view=run-comparison&baseline_run_id=baseline&candidate_run_id=candidate"):
                    mobile.goto(url+"/#/"+route)
                    mobile.wait_for_selector("#main h1")
                    check("mobile_no_page_overflow_"+route.split('?')[0], mobile.evaluate("document.documentElement.scrollWidth === innerWidth"))
                mobile.screenshot(path=str(ROOT/"reports/fastresearch_experiments_mobile.png"),full_page=True)
                check("no_product_javascript_errors",not errors)
                browser.close()
            check("historical_source_preserved", historical_signature() == before)
            check("research_registry_preserved", digest(ROOT/"data/research_registry.json") == research_before)
            check("paid_experiment_stays_stopped", digest(stopped) == stopped_before)
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            log.close()
    result = {"verified_on":"2026-10-10","passed_checks":len(checks),"checks":checks,"browser_errors":errors,"fixture_scope":"temporary projects only; no model calls or GPU execution","screenshots":["reports/fastresearch_resources_desktop.png","reports/fastresearch_experiments_desktop.png","reports/fastresearch_experiments_mobile.png"]}
    report=ROOT/"reports/fastresearch_product_validation_20261010.json"
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed_checks":len(checks),"report":str(report)},ensure_ascii=False))


if __name__ == "__main__":
    main()

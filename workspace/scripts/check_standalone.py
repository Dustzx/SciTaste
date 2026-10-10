#!/usr/bin/env python3
"""Validate the owned desktop and native contracts on isolated local projects."""
import hashlib
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from playwright.sync_api import sync_playwright
    checks, errors = [], []
    def check(name, passed):
        if not passed:
            raise AssertionError(name)
        checks.append({"check":name,"passed":True})
    stopped = ROOT / "reports/bailian_blink_dev_v3/EXECUTION_STATUS.json"
    before = {str(p):sha(p) for p in [ROOT / "data/research_registry.json", stopped]}
    probe = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-c",
        "import json,sys,scitaste,numpy,pydantic,httpx,torch; print(json.dumps({'prefix':sys.prefix,'package':scitaste.__file__,'cuda':torch.cuda.is_initialized()}))"], text=True)
    runtime = json.loads(probe)
    check("owned_runtime_prefix", Path(runtime["prefix"]).resolve() == ROOT / ".venv")
    check("owned_source_import", Path(runtime["package"]).resolve().is_relative_to(ROOT / "backend/scitaste"))
    check("import_does_not_initialize_cuda", runtime["cuda"] is False)
    safety = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-c", """
from scitaste.generative_ui.safety import validate_declarative_value
location = 'data.project_documents.reference_sha256'
assert validate_declarative_value({'evaluations/source/successor/MANIFEST.json':'a'*64}, location=location)
for value, where in [({'../escape':'a'*64},location),({'/absolute':'a'*64},location),({'https://example.com/x':'a'*64},location),({'%2e%2e/escape':'a'*64},location),({'safe.json':'invalid'},location),({'safe.json':{}},location),({'command':'a'*64},'data')]:
    try: validate_declarative_value(value,location=where)
    except ValueError: pass
    else: raise AssertionError(value)
print('passed')
"""], text=True)
    check("document_locator_hash_map_preserves_closed_data_boundary",safety.strip()=="passed")
    with tempfile.TemporaryDirectory(prefix="fastresearch-desktop-check-") as temp:
        fixture=Path(temp)
        project=fixture / "outputs/projects/fastresearch-cvpr2027"
        project.mkdir(parents=True)
        shutil.copy2(ROOT / "outputs/projects/fastresearch-cvpr2027/PROJECT.json", project / "PROJECT.json")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port=sock.getsockname()[1]
        url=f"http://127.0.0.1:{port}"
        code="import sys;sys.path.insert(0,sys.argv[1]);import serve_web as w;from scitaste_bridge import ExperimentBridge;w.BRIDGE=ExperimentBridge(sys.argv[2]);sys.argv=['serve_web','--port',sys.argv[3]];w.main()"
        log=(fixture / "server.log").open("w+")
        process=subprocess.Popen([str(ROOT / ".venv/bin/python"),"-c",code,str(ROOT / "scripts"),str(fixture),str(port)],stdout=log,stderr=log)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, method="GET", body=None, headers=None):
            data=json.dumps(body).encode() if body is not None else None
            req=urllib.request.Request(url+path,data=data,method=method,headers={"Content-Type":"application/json",**(headers or {})})
            try:
                with opener.open(req,timeout=120) as response:
                    content=response.read()
                    return response.status,json.loads(content) if response.headers.get_content_type()=="application/json" else content
            except urllib.error.HTTPError as exc:
                return exc.code,exc.read()
        try:
            for _ in range(80):
                try:
                    if request("/api/health")[0]==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError("isolated server failed to start")
            status=request("/api/experiments/status")[1]
            auth={"X-FastResearch-CSRF":status["csrf_token"]}
            check("standalone_status",status["migration"]["standalone"])
            check("native_session_bootstrap",request("/session")[0]==204)
            check("session_host_rebinding_denied",request("/session",headers={"Host":"evil.invalid"})[0]==403)
            check("native_get_cross_site_denied",request("/api/v1/projects",headers={"Sec-Fetch-Site":"cross-site"})[0]==403)
            body={"project_id":"studio-fixture","title":"Studio fixture","research_direction":"Paired visual evidence","target_venue":"CVPR 2027"}
            path="/api/v2/workspace/projects"
            check("native_write_requires_page_token",request(path,"POST",body)[0]==403)
            check("native_cross_origin_write_denied",request(path,"POST",body,{**auth,"Origin":"https://example.com"})[0]==403)
            check("native_contract_rejects_unknown_execution_field",request(path,"POST",{**body,"command":"run"},auth)[0]==400)
            check("native_project_creation",request(path,"POST",body,auth)[0]==201)
            check("native_duplicate_does_not_overwrite",request(path,"POST",body,auth)[0]==409)
            # A real legacy state: pointer retained, invalid draft unadmitted.
            subprocess.run([str(ROOT / ".venv/bin/python"),"-c",
                "import sys;from scitaste.project import ProjectRuntime,ProjectManifest;ProjectRuntime(sys.argv[1]).create(ProjectManifest(project_id='legacy-draft',title='Legacy draft',research_direction='Retain unadmitted paper warning',status='planning',current_paper='papers/unadmitted'))",
                str(fixture / "outputs")],check=True)
            response=request(path+"/legacy-draft/project-progress")
            check("legacy_unadmitted_paper_does_not_hide_project",response[0]==200)
            metadata=request("/api/experiments/fastresearch/projects/legacy-draft/metadata")[1]
            check("legacy_paper_warning_retained",bool(metadata["warnings"]))
            check("v1_project_discovery",request("/api/v1/projects")[0]==200)
            check("v2_workspace_projection",request(path+"/studio-fixture/project-progress")[0]==200)
            for operation in ("intents","warm-cache","gate-action"):
                response=request("/api/v3/generative/projects/studio-fixture/"+operation)
                check("v3_"+operation,response[0]==200)
            check("unconfigured_native_plan_is_not_fabricated",request("/api/v3/generative/projects/studio-fixture/program-revisions")[0]==400)
            check("v4_workspace_catalog",request("/api/v4/projects/studio-fixture/workspaces")[0]==200)
            for asset in ("/studio/","/studio/assets/app.js","/studio/assets/app.css","/studio/assets/locale.js","/studio/assets/locales/zh-CN.json","/assets/studio.css","/assets/studio-auth.js"):
                check("asset_"+asset,request(asset)[0]==200)
            for path in ("/studio/assets/../../AGENTS.md","/studio/assets/.env","/backend/scitaste/.env","/.venv/bin/python"):
                check("deny_"+path,request(path)[0]==404)
            with sync_playwright() as engine:
                browser=engine.chromium.launch(headless=True)
                page=browser.new_page(viewport={"width":1440,"height":1000})
                page.on("pageerror",lambda err:errors.append(str(err)))
                page.goto(url+"/#/program")
                page.wait_for_selector("[data-venue]")
                check("ccf_ab_submission_catalogue",page.locator("[data-venue]").count()==24 and "A 类期刊" in page.locator("#main").inner_text())
                check("five_stage_scitaste_positioning",page.locator(".research-stages > div").count()==5 and "Idea Research & Discovery" in page.locator("#main").inner_text())
                page.screenshot(path=str(ROOT / "reports/scitaste_submission_program.png"),full_page=True)
                page.goto(url+"/studio/#/projects/studio-fixture?lang=zh-CN")
                page.wait_for_function("() => !document.getElementById('generate-workspace').disabled")
                check("native_project_deep_link",page.locator("#project-select").input_value()=="studio-fixture")
                check("product_brand_and_home_link",page.locator(".brand-block").inner_text().lower().startswith("scitaste") and page.locator(".fastresearch-home").get_attribute("href")=="/#/overview")
                for view in ("project-overview","run-stage-explorer","paper-evidence","blockers","pending-proposals","research-landscape","project-progress"):
                    page.goto(url+f"/studio/#/projects/studio-fixture/{view}?lang=zh-CN")
                    page.wait_for_function("() => document.getElementById('workspace').getAttribute('aria-busy') === 'false' && !document.getElementById('generate-workspace').disabled")
                    check("native_browser_"+view,page.locator("#workspace").inner_text().strip()!="")
                page.locator("#intent-question").fill("查看项目进度和下一步")
                page.locator("#generate-workspace").click()
                page.wait_for_function("() => location.hash.includes('/workspaces/')",timeout=120000)
                check("native_conversation_write_through_gateway",bool(list((fixture / "outputs/projects/studio-fixture/.generative-ui").rglob("*.json"))))
                conversation=page.url
                page.reload()
                page.wait_for_function("() => !document.getElementById('generate-workspace').disabled")
                check("native_conversation_reload",page.url==conversation)
                page.screenshot(path=str(ROOT / "reports/fastresearch_studio_desktop.png"),full_page=True)
                mobile=browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
                mobile.on("pageerror",lambda err:errors.append(str(err)))
                mobile.goto(url+"/studio/#/projects/studio-fixture?lang=zh-CN")
                mobile.wait_for_function("() => !document.getElementById('generate-workspace').disabled")
                check("studio_mobile_no_overflow",mobile.evaluate("document.documentElement.scrollWidth === innerWidth"))
                mobile.screenshot(path=str(ROOT / "reports/fastresearch_studio_mobile.png"),full_page=True)
                check("no_browser_errors",not errors)
                browser.close()
            check("source_registry_and_stopped_runner_preserved",all(sha(Path(p))==v for p,v in before.items()))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            log.close()
    report=ROOT / "reports/fastresearch_standalone_validation_20261010.json"
    report.write_text(json.dumps({"verified_on":"2026-10-10","passed_checks":len(checks),"checks":checks,"browser_errors":errors,"runtime":runtime,"scope":"temporary projects; no model calls or GPU research"},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed_checks":len(checks),"report":str(report)},ensure_ascii=False))


if __name__=="__main__":
    main()

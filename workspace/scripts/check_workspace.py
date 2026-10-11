#!/usr/bin/env python3
"""Validate a fresh SciTaste workspace using temporary metadata and loopback HTTP."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = []

    def check(name, result):
        assert result, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="scitaste-fresh-") as temp:
        fixture = Path(temp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        code = (
            "import sys;sys.path.insert(0,sys.argv[1]);import serve_web as w;"
            "from scitaste_bridge import ExperimentBridge;"
            "w.BRIDGE=ExperimentBridge(sys.argv[2]);"
            "sys.argv=['serve_web','--port',sys.argv[3]];w.main()"
        )
        env = {k: v for k, v in os.environ.items()
               if not any(word in k.upper() for word in ["API_KEY", "TOKEN", "PASSWORD", "SECRET"])}
        env["SCITASTE_REPORT_ROOT"] = str(fixture / "report")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path, method="GET", body=None, headers=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}" + path, data=data, method=method,
                headers={"Content-Type": "application/json", **(headers or {})})
            try:
                response = opener.open(req, timeout=15)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                raw = response.read()
                value = json.loads(raw) if raw and response.headers.get_content_type() == "application/json" else raw
                return response.code, response.headers, value

        with (fixture / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(ROOT / "scripts"), str(fixture), str(port)],
                env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Fresh workspace exited before becoming ready")
                    try:
                        if request("/api/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Fresh workspace did not become ready")
                status = request("/api/experiments/status")[2]
                check("parent_or_nested_native_runtime_resolved", status["available"])
                check("no_live_transport", status["execution"]["live_models"] is False
                      and status["execution"]["gpu_launch"] is False)
                progress = request("/api/progress")[2]
                check("empty_report_supported", progress["projects"] == [] and progress["experiences"] == [])
                check("empty_race_supported", progress["portfolio"].get("branches", []) == [])
                check("empty_route_candidate_supported", progress.get("route_candidate") is None)
                check("empty_dossiers_supported", request("/api/research/projects")[2]["projects"] == [])
                check("empty_introductions_supported", request("/api/research/introductions")[2]["projects"] == [])
                check("empty_export_fails_cleanly", request("/api/research/export?format=zip")[0] == 400)

                _, headers, venues = request("/api/venues")
                check("ab_catalogue_available", len(venues["venues"]) >= 300
                      and all(v["rank"] in {"A", "B"} for v in venues["venues"]))
                check("catalogue_etag", request("/api/venues", headers={"If-None-Match": headers["ETag"]})[0] == 304)
                check("catalogue_read_only", request("/api/venues", "POST", {})[0] == 405)
                check("workspace_brand", b"SciTaste" in request("/")[2])
                path = "/api/experiments/fastresearch/projects"
                body = {"project_id": "fresh-fixture", "title": "Fresh workspace",
                        "research_direction": "Temporary offline metadata check"}
                check("metadata_requires_csrf", request(path, "POST", body)[0] == 403)
                auth = {"X-FastResearch-CSRF": status["csrf_token"]}
                check("native_metadata_creation", request(path, "POST", body, auth)[0] == 201)
                check("native_project_persisted", (fixture / "outputs/projects/fresh-fixture/PROJECT.json").is_file())
                check("native_resource_portfolio_optional", request(path + "/fresh-fixture/resource-portfolio")[0] == 200)

                check("no_raw_calls_created", not list(fixture.rglob("calls.jsonl")))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print(json.dumps({"passed_checks": len(checks), "checks": checks, "model_calls": 0}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Serve the local SciTaste application and explicitly allowed research files.

Research endpoints are read-only. The experiment adapter and complete research desktop use the owned SciTaste
runtime for project metadata, protocols, views, reviews and conversations.
No model transport, GPU launcher or literature promotion is enabled.
"""
import argparse
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import research_registry
import progress_board
import research_dossiers
import research_introductions
import research_export
import platform_skills
import venue_catalog
from scitaste_bridge import BRIDGE, BridgeError
from studio_gateway import StudioGateway

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
STARTED = time.time()
FILES = [ROOT / "data/research_registry.json", ROOT / "data/discovery_inbox.json",
         ROOT / "data/source_snapshots.json", ROOT / "data/change_history.jsonl"]
CACHE_LOCK = threading.Lock()
CACHE = {}
CSRF_TOKEN = secrets.token_urlsafe(32)
STUDIO = StudioGateway(lambda: BRIDGE)


def state():
    global CACHE
    doc_paths = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    document_signature = tuple((str(p.relative_to(ROOT)), p.stat().st_mtime_ns, p.stat().st_size) for p in doc_paths if p.exists())
    progress_paths = [progress_board.REPORT / p for p in ['STATUS_BOARD.json', 'EXPERIENCE_POOL.json', 'sources.json']]
    progress_paths += list(progress_board.sources().values())
    progress_paths += research_dossiers.signature_paths()
    study = ROOT / 'outputs/projects/fastresearch-cvpr2027/research'
    progress_paths += [study/'API_LEDGER.json', *study.glob('runs/*/STATUS.json'), *study.glob('runs/*/PREDICTIONS.json')]
    progress_paths += [p for run in progress_board.study_runs() for p in [run/'STATUS.json', run/'PREDICTIONS.json']]
    progress_signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (str(p), None) for p in progress_paths)
    venue_signature = (venue_catalog.CATALOGUE.stat().st_mtime_ns, venue_catalog.CATALOGUE.stat().st_size) if venue_catalog.CATALOGUE.exists() else None
    signature = (tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in FILES), document_signature, progress_signature, venue_signature)
    with CACHE_LOCK:
        if CACHE.get("signature") == signature:
            return CACHE
        registry = research_registry.read(FILES[0])
        research_registry.validate(registry)
        inbox = research_registry.read(FILES[1]) if FILES[1].exists() else {"items": [], "runs": []}
        snapshots = research_registry.read(FILES[2]) if FILES[2].exists() else {}
        history = []
        if FILES[3].exists():
            for line in FILES[3].read_text().splitlines():
                entry = json.loads(line)
                history.append({"as_of": entry["as_of"], "reason": entry["reason"],
                                "changes": [{"table": c["table"], "id": c["id"]} for c in entry["changes"]]})
        documents = [{"path": "README.md", "name": "项目入口"},
                     {"path": "docs/RESEARCH_REGISTRY.md", "name": "榜单维护工作流"}]
        documents += [{"path": str(p.relative_to(ROOT)), "name": p.stem} for p in sorted((ROOT / "docs").glob("*.md")) if p.name != "RESEARCH_REGISTRY.md"]
        payload = {"registry": registry, "inbox": inbox, "snapshots": snapshots,
                   "history": history, "documents": documents,
                   "service": {"name": "SciTaste", "read_only": True, "experiment_metadata_writable": True, "local_file_sync": True,
                               "venues_revision": hashlib.sha256(repr(venue_signature).encode()).hexdigest(),
                               "documents_revision": hashlib.sha256(repr(document_signature).encode()).hexdigest(),
                               "progress_revision": hashlib.sha256(repr(progress_signature).encode()).hexdigest()}}
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        updated = {"signature": signature, "payload": payload, "blob": blob,
                   "etag": '"' + hashlib.sha256(blob).hexdigest() + '"'}
        CACHE = updated
        return CACHE


def csv_export(registry):
    papers = {p["id"]: p for p in registry["papers"]}
    rows = []
    for score in registry["results"]:
        paper = papers[score["paper_id"]]
        row = dict(score, publication_lane=paper["lane"], venue=paper["venue"], paper_title=paper["title"])
        rows.append({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=sorted({k for row in rows for k in row}))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def allowed_document(relative):
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents:
        return None
    if path == ROOT / "README.md" or ((ROOT / "docs") in path.parents and path.suffix == ".md"):
        return path if path.is_file() else None
    if path.parent == ROOT / "reports" and re.fullmatch(r"(?:research_registry|fastresearch_web|fastresearch_product|fastresearch_standalone|fastresearch_migration)_validation_\d{8}\.json", path.name):
        return path if path.is_file() else None
    if (ROOT / "reports/research_refresh") in path.parents and path.suffix == ".json":
        return path if path.is_file() else None
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "SciTaste/1.0"

    def respond(self, body, content_type, status=200, etag=None, filename=None, head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if etag:
            self.send_header("ETag", etag)
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()
        if not head and status != 304:
            self.wfile.write(body)

    def error_json(self, status, message, head=False):
        self.respond(json.dumps({"error": message}, ensure_ascii=False).encode(), "application/json; charset=utf-8", status, head=head)

    def do_HEAD(self):
        self.get(head=True)

    def do_GET(self):
        self.get()

    def native_request(self, head=False):
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if (self.headers.get("Host", "") not in expected or
                (self.headers.get("Origin") and self.headers.get("Origin") not in {"http://" + x for x in expected}) or
                self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.error_json(403, "研究桌面仅接受本机同源访问", head)
            return
        method = "GET" if head else self.command
        try:
            if urlsplit(self.path).path == "/session":
                self.respond(b"", "text/plain", 204, head=head)
                return
            body = None
            if method != "GET":
                if not secrets.compare_digest(self.headers.get("X-FastResearch-CSRF", ""), CSRF_TOKEN):
                    self.error_json(403, "请从当前页面提交研究操作", head)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4 * 1024 * 1024:
                    self.error_json(413, "研究请求大小超限", head)
                    return
                if self.headers.get_content_type() != "application/json":
                    self.error_json(415, "研究操作必须使用 JSON", head)
                    return
                body = self.rfile.read(length)
                obj = json.loads(body, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
                if not isinstance(obj, dict):
                    raise ValueError("Expected object")
            status, mime, content = STUDIO.request(method, self.path, body)
            self.respond(content, mime, status, head=head)
        except BridgeError as exc:
            self.error_json(exc.status, exc.message, head)
        except (ValueError, TypeError):
            self.error_json(400, "研究请求字段无效", head)
        except OSError:
            self.error_json(503, "研究后端暂时不可用", head)

    def experiment_request(self, head=False):
        request = urlsplit(self.path)
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in expected or (origin and origin not in {"http://" + x for x in expected}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.error_json(403, "实验接口仅接受本机同源访问", head)
            return
        method = "GET" if head else self.command
        try:
            payload = None
            if method != "GET":
                if not secrets.compare_digest(self.headers.get("X-FastResearch-CSRF", ""), CSRF_TOKEN):
                    self.error_json(403, "请从当前页面提交实验操作", head)
                    return
                if self.headers.get_content_type() != "application/json":
                    self.error_json(415, "实验操作必须使用 JSON", head)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 128 * 1024:
                    self.error_json(413, "实验请求大小超限", head)
                    return
                payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("非有限 JSON 数值")))
                if not isinstance(payload, dict):
                    raise ValueError("实验请求必须是对象")
            values = parse_qs(request.query, keep_blank_values=True)
            if any(len(v) != 1 for v in values.values()):
                raise ValueError("实验查询字段不可重复")
            query = {k: v[0] for k, v in values.items()}
            status, body = BRIDGE.dispatch(method, unquote(request.path)[len("/api/experiments/"):], query, payload)
            if request.path == "/api/experiments/status":
                body = dict(body, csrf_token=CSRF_TOKEN)
            self.respond(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8", status, head=head)
        except BridgeError as exc:
            self.error_json(exc.status, exc.message, head)
        except FileExistsError:
            self.error_json(409, "项目或协议已存在，不覆盖已有记录", head)
        except FileNotFoundError:
            self.error_json(404, "项目或证据产物不存在", head)
        except (ValueError, TypeError, KeyError):
            self.error_json(400, "实验请求或当前证据绑定无效，请同步后核对字段", head)
        except OSError:
            self.error_json(503, "实验资料暂时不可读，请核对本机后端状态", head)

    def get(self, head=False):
        request = urlsplit(self.path)
        path = unquote(request.path)
        try:
            if re.match(r"^/api/v[1-4]/", path) or path == "/session":
                self.native_request(head)
            elif path in {"/studio", "/studio/", "/studio/index.html"} or path.startswith("/studio/assets/"):
                try:
                    mime, body = STUDIO.asset(path)
                    self.respond(body, mime, head=head)
                except FileNotFoundError:
                    self.error_json(404, "研究桌面资源不存在", head)
            elif path.startswith("/api/experiments/"):
                self.experiment_request(head)
            elif path == "/api/state":
                snapshot = state()
                if self.headers.get("If-None-Match") == snapshot["etag"]:
                    self.respond(b"", "application/json", 304, etag=snapshot["etag"], head=head)
                else:
                    self.respond(snapshot["blob"], "application/json; charset=utf-8", etag=snapshot["etag"], head=head)
            elif path == "/api/health":
                snapshot = state()
                registry = snapshot["payload"]["registry"]
                body = {"ok": True, "service": "SciTaste", "as_of": registry["as_of"],
                        "counts": {k: len(registry[k]) for k in ("benchmarks", "results", "methods", "ideas")},
                        "uptime_seconds": round(time.time() - STARTED), "data_version": snapshot["etag"].strip('"')}
                self.respond(json.dumps(body).encode(), "application/json; charset=utf-8", head=head)
            elif path == '/api/skills':
                try:
                    body, mime, filename = platform_skills.response(parse_qs(request.query))
                except KeyError:
                    self.error_json(404, '未登记该核心技能', head)
                except ValueError:
                    self.error_json(400, '技能请求或规范不完整，请使用核心技能入口', head)
                else:
                    self.respond(body, mime, filename=filename, head=head)
            elif path == '/api/venues':
                catalogue, etag = venue_catalog.snapshot()
                if self.headers.get('If-None-Match') == etag:
                    self.respond(b'', 'application/json', 304, etag=etag, head=head)
                else:
                    self.respond(json.dumps(catalogue, ensure_ascii=False).encode(), 'application/json; charset=utf-8', etag=etag, head=head)
            elif path == '/api/progress':
                self.respond(json.dumps(progress_board.snapshot(), ensure_ascii=False).encode(), 'application/json; charset=utf-8', head=head)
            elif path == '/api/research/introductions':
                self.respond(json.dumps(research_introductions.snapshot(), ensure_ascii=False).encode(), 'application/json; charset=utf-8', head=head)
            elif path == '/api/research/projects':
                self.respond(json.dumps(research_dossiers.snapshot(), ensure_ascii=False).encode(), 'application/json; charset=utf-8', head=head)
            elif path == '/api/research/export':
                query = parse_qs(request.query)
                try:
                    body, mime, filename = research_export.build(
                        project=query.get('project', ['all'])[0],
                        format=query.get('format', ['markdown'])[0])
                except ValueError:
                    self.error_json(400, '导出仅支持已审阅课题的Markdown或ZIP，请使用页面下载入口', head)
                else:
                    self.respond(body, mime, filename=filename, head=head)
            elif path == '/api/progress/source':
                key = parse_qs(request.query).get('key', [''])[0]
                doc = progress_board.source_document(key)
                if doc is None:
                    self.error_json(404, '证据未登记或不属于可读叙述/汇总来源', head)
                else:
                    self.respond(json.dumps(doc, ensure_ascii=False).encode(), 'application/json; charset=utf-8', head=head)
            elif path == "/api/document":
                relative = parse_qs(request.query).get("path", [""])[0]
                doc = allowed_document(relative)
                if not doc:
                    self.error_json(404, "资料不存在或不属于网站可读取的研究文档", head)
                else:
                    body = {"path": str(doc.relative_to(ROOT)), "content": doc.read_text(), "format": doc.suffix[1:]}
                    self.respond(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8", head=head)
            elif path in {"/downloads/scores.csv", "/downloads/registry.json"}:
                registry = state()["payload"]["registry"]
                if path.endswith(".csv"):
                    self.respond(csv_export(registry), "text/csv; charset=utf-8", filename="fastresearch-scores.csv", head=head)
                else:
                    self.respond(json.dumps(registry, ensure_ascii=False, indent=2).encode(), "application/json; charset=utf-8", filename="fastresearch-registry.json", head=head)
            elif path in {"/", "/index.html", "/favicon.ico"} or path.startswith("/assets/"):
                relative = "index.html" if path in {"/", "/index.html"} else "assets/logo.svg" if path == "/favicon.ico" else path.lstrip("/")
                asset = (WEB / relative).resolve()
                if WEB not in asset.parents or not asset.is_file():
                    self.error_json(404, "页面不存在", head)
                else:
                    mime = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
                    self.respond(asset.read_bytes(), mime + ("; charset=utf-8" if mime.startswith("text/") or mime in {"application/javascript", "image/svg+xml"} else ""), head=head)
            else:
                self.error_json(404, "页面不存在", head)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print("Research file read failed:", type(exc).__name__, str(exc), flush=True)
            self.error_json(503, "研究数据未通过读取或校验，请修复本地数据后重新同步", head)

    def do_POST(self):
        if re.match(r"^/api/v[1-4]/", urlsplit(self.path).path):
            self.native_request()
        elif urlsplit(self.path).path.startswith("/api/experiments/"):
            self.experiment_request()
        else:
            self.error_json(405, "研究资料更新使用审阅补丁流程")

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Native manifests retain config-relative locators and their sealed bytes.
    # Resolve them from the owned backend, as the original CLI/desktop does.
    if BRIDGE.source.is_dir():
        os.chdir(BRIDGE.source)
    state()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SciTaste serving at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        STUDIO.close()


if __name__ == "__main__":
    main()

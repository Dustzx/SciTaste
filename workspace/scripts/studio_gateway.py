"""Mount the complete, owned SciTaste desktop on FastResearch's local origin."""
from __future__ import annotations

import http.client
import json
import mimetypes
import secrets
import threading

ASSETS = {"app.js", "app.css", "locale.js", "locales/en.json", "locales/zh-CN.json"}


class StudioGateway:
    def __init__(self, bridge):
        self.bridge = bridge
        self.server = None
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(48)

    def start(self):
        with self.lock:
            if self.server is None:
                app = self.bridge().application("fastresearch")
                from scitaste.generative_ui.server import BearerCredential, GenerativeUIHTTPServer
                self.server = GenerativeUIHTTPServer(("127.0.0.1", 0), app, BearerCredential(self.token))
                threading.Thread(target=self.server.serve_forever, daemon=True, name="owned-research-receiver").start()
            return self.server.server_port

    def request(self, method, path, body=None):
        port = self.start()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
        try:
            connection.request(method, path, body=body, headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            })
            response = connection.getresponse()
            content = response.read(64 * 1024 * 1024 + 1)
            if len(content) > 64 * 1024 * 1024:
                raise ValueError("Native response exceeds local preview limit")
            return response.status, response.getheader("Content-Type", "application/json"), content
        finally:
            connection.close()

    def asset(self, path):
        source = self.bridge().source / "src/scitaste/generative_ui/static"
        if path in {"/studio", "/studio/", "/studio/index.html"}:
            html = (source / "index.html").read_text()
            html = html.replace("/assets/", "/studio/assets/").replace("SciTaste evidence workspace", "SciTaste · 完整研究桌面")
            html = html.replace('<link rel="stylesheet" href="/studio/assets/app.css">',
                '<link rel="stylesheet" href="/studio/assets/app.css">\n'
                '<link rel="stylesheet" href="/assets/studio.css">\n'
                '<link rel="icon" href="/assets/logo.svg" type="image/svg+xml">\n'
                '<script src="/assets/studio-auth.js"></script>')
            html = html.replace('<div class="header-controls">',
                '<div class="header-controls"><a class="fastresearch-home" href="/#/overview">← 研究总览</a>')
            html = html.replace('<body>', '<body><nav class="fast-studio-bar" aria-label="SciTaste">'
                '<a class="fast-studio-brand" href="/#/overview"><img src="/assets/logo.svg" width="28" height="28" alt="">'
                '<strong>SciTaste</strong><span>研究桌面</span></a><div>'
                '<a href="/#/program">投稿规划</a><a href="/#/experiments">实验工作台</a>'
                '<a href="/#/overview">研究总览 ↗</a></div></nav>')
            return "text/html; charset=utf-8", html.encode()
        prefix = "/studio/assets/"
        relative = path[len(prefix):] if path.startswith(prefix) else ""
        if relative not in ASSETS:
            raise FileNotFoundError(path)
        data = (source / relative).read_bytes()
        if relative.endswith(".js"):
            data = data.replace(b'"/assets/', b'"/studio/assets/').replace(b"'/assets/", b"'/studio/assets/")
        elif relative.startswith("locales/"):
            catalog = json.loads(data)
            catalog.update({"brand.eyebrow": "SciTaste · Research Studio",
                            "brand.title": "研究桌面" if "zh-CN" in relative else "Research studio",
                            "brand.summary": "从研究计划到实验、证据与论文。" if "zh-CN" in relative else "Research plans, experiments, evidence and papers."})
            data = json.dumps(catalog, ensure_ascii=False).encode()
        mime = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        return mime + "; charset=utf-8", data

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

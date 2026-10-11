"""SciTaste workspace adapter to its local research runtime.

Historical origin identifiers remain stable. Legacy-origin deep links
remain read-only compatibility references. This adapter has no executor or live model
transport; registering a protocol never executes it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "backend/scitaste"
if not (DEFAULT_SOURCE / "src/scitaste").is_dir() and (ROOT.parent / "src/scitaste").is_dir():
    DEFAULT_SOURCE = ROOT.parent
SOURCE = Path(os.environ.get("SCITASTE_SOURCE_ROOT", os.environ.get("FASTRESEARCH_SCITASTE_ROOT", str(DEFAULT_SOURCE)))).resolve()
OUTPUTS = ROOT / "outputs"
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VIEWS = {"project-progress", "project-overview", "run-stage-explorer", "paper-evidence",
         "run-comparison", "blockers", "pending-proposals", "research-landscape"}


class BridgeError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def observed_at():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


class ExperimentBridge:
    def __init__(self, root=ROOT, source=SOURCE):
        self.root, self.source = Path(root), Path(source)
        self.outputs = self.root / "outputs"
        self._apps, self._lock = {}, threading.RLock()

    def status(self):
        disk = shutil.disk_usage(self.root)
        entry = self.source / "src/scitaste/generative_ui/application.py"
        ready = entry.is_file()
        return {"available": ready, "backend": "SciTaste", "source_sha256": hashlib.sha256(entry.read_bytes()).hexdigest() if ready else None,
                "origins": [{"id": "fastresearch", "label": "SciTaste", "writable": True},
                            {"id": "scitaste", "label": "SciTaste 历史兼容入口", "writable": False, "hidden": True}],
                "migration": {"standalone": self.source == DEFAULT_SOURCE.resolve(), "desktop": "/studio/", "source": str(self.source)},
                "disk": {"total_gib": round(disk.total / 2**30, 2), "free_gib": round(disk.free / 2**30, 2), "observed_at": observed_at()},
                "execution": {"live_models": False, "gpu_launch": False, "protocol_registration": True},
                "views": sorted(VIEWS)}

    def application(self, origin):
        if origin not in {"fastresearch", "scitaste"}:
            raise BridgeError(404, "未知项目来源")
        with self._lock:
            if origin not in self._apps:
                if not (self.source / "src/scitaste").is_dir():
                    raise BridgeError(503, "SciTaste 后端尚未安装")
                path = str(self.source / "src")
                if path not in sys.path:
                    sys.path.insert(0, path)
                try:
                    from scitaste.generative_ui.application import GenerativeUIApplication
                    from scitaste.project import ProjectRuntime
                except ImportError as exc:
                    raise BridgeError(503, "实验后端需要 SciTaste 的 Python 3.12 环境；请按部署文档配置") from exc
                outputs = self.outputs if origin == "fastresearch" else self.source / "outputs"
                self._apps[origin] = GenerativeUIApplication(ProjectRuntime(outputs))
            return self._apps[origin]

    def workspace_query(self, project_id, query):
        view = query.get("view", "project-progress")
        if view not in VIEWS:
            raise BridgeError(400, "不支持的实验视图")
        allowed = {"view", "run_id", "paper_id", "baseline_run_id", "candidate_run_id"}
        if set(query) - allowed:
            raise BridgeError(400, "实验视图包含未知字段")
        result = {"project_id": project_id, "view": view}
        result.update({k: v for k, v in query.items() if k != "view" and v})
        return result

    def dispatch(self, method, tail, query, payload=None):
        if tail == "status" and method == "GET":
            return 200, self.status()
        parts = tail.strip("/").split("/")
        if len(parts) < 2 or parts[1] != "projects":
            raise BridgeError(404, "实验接口不存在")
        origin = parts[0]
        # Only registered-artifact inspection is permitted for legacy projects.
        if method != "GET" and origin == "scitaste" and (len(parts) != 4 or parts[3] != "inspections"):
            raise BridgeError(403, "SciTaste 历史项目为只读引用；请在当前研究工作台创建新项目")
        app = self.application(origin)
        if len(parts) == 2:
            if method == "GET":
                return 200, app.project_list_workspace().model_dump(mode="json")
            if method == "POST":
                return 201, app.create_project(payload).model_dump(mode="json")
        if len(parts) < 4 or not PROJECT_ID.fullmatch(parts[2]) or parts[2] in {".", ".."}:
            raise BridgeError(400, "项目 ID 无效")
        project_id, operation = parts[2], parts[3]
        if len(parts) == 4:
            if operation == "resource-portfolio" and method == "GET":
                from scitaste.project import ProjectRuntime
                from scitaste.generative_ui.project_resources import load_project_resource_portfolio
                runtime = ProjectRuntime(self.outputs if origin == "fastresearch" else self.source / "outputs")
                portfolio = load_project_resource_portfolio(runtime, project_id)
                return 200, {"project_id": project_id,
                             "resource_portfolio": portfolio.model_dump(mode="json") if portfolio else None}
            if operation == "plan" and method == "GET":
                from scitaste.project import ProjectRuntime
                snapshot = ProjectRuntime(self.outputs if origin == "fastresearch" else self.source / "outputs").open(project_id)
                extra = snapshot.manifest.model_extra or {}
                return 200, {"project_id":project_id,"revision":snapshot.revision,
                             "submission_plan":extra.get("submission_plan"),"venue_schedule":extra.get("venue_schedule"),
                             "program":extra.get("training_free_program")}
            if operation == "metadata" and method == "GET":
                from scitaste.project import ProjectRuntime
                snapshot = ProjectRuntime(self.outputs if origin == "fastresearch" else self.source / "outputs").open(project_id)
                manifest = snapshot.manifest
                return 200, {"project_id": project_id, "title": manifest.title, "research_direction": manifest.research_direction, "revision": snapshot.revision, "warnings": snapshot.warnings}
            if operation == "workspace" and method == "GET":
                workspace_query = self.workspace_query(project_id, query)
                if origin == "scitaste":
                    from scitaste.generative_ui.workspace import WorkspaceSurfaceFactory, workspace_document, validate_workspace_query
                    from scitaste.project import ProjectRuntime
                    parsed = validate_workspace_query(workspace_query)
                    surface = WorkspaceSurfaceFactory(ProjectRuntime(self.source / "outputs")).build_surface(parsed)
                    return 200, workspace_document(parsed, surface).model_dump(mode="json")
                return 200, app.current_workspace(workspace_query).model_dump(mode="json")
            if operation == "intents" and method == "GET":
                return 200, app.quick_intents(project_id).model_dump(mode="json")
            if operation == "workspaces":
                if method == "GET":
                    return 200, app.research_workspace_catalog(project_id).model_dump(mode="json")
                if method == "POST":
                    return 201, app.create_research_workspace(project_id, payload).model_dump(mode="json")
            if operation == "inspections" and method == "POST":
                return 200, self.inspect(origin, project_id, query, payload)
            if operation == "protocols" and method == "POST":
                return 201, self.register_protocol(app, project_id, payload)
            if operation == "protocols" and method == "GET":
                if origin != "fastresearch":
                    raise BridgeError(404, "历史实验协议由原有证据视图读取")
                return 200, self.protocols(project_id)
            if operation == "protocol-inspections" and method == "POST":
                if not isinstance(payload, dict) or set(payload) != {"run_id", "sha256", "expected_revision"}:
                    raise BridgeError(400, "协议预览只接受已登记 ID 与内容绑定")
                current = self.protocols(project_id)
                item = next((p for p in current["protocols"] if p["run_id"] == payload["run_id"]), None)
                if item is None:
                    raise BridgeError(404, "协议未登记")
                if current["revision"] != payload["expected_revision"] or item["sha256"] != payload["sha256"]:
                    raise BridgeError(409, "协议内容已变化，请同步后重新预览")
                return 200, item
            if operation == "events" and method == "POST":
                return 202, app.submit_workspace_event(self.workspace_query(project_id, query), payload).model_dump(mode="json")
            if operation == "decisions" and method == "POST":
                return 200, app.decide_workspace_proposal(self.workspace_query(project_id, query), payload).model_dump(mode="json")
            if operation == "gate-action" and method == "GET":
                return 200, app.current_gate_action(project_id).model_dump(mode="json")
        if operation == "workspaces" and len(parts) >= 5:
            workspace_id = parts[4]
            if len(parts) == 5 and method == "GET":
                return 200, app.research_workspace_detail(project_id, workspace_id).model_dump(mode="json")
            if len(parts) == 5 and method == "PATCH":
                return 200, app.rename_research_workspace(project_id, workspace_id, payload).model_dump(mode="json")
            if len(parts) == 6 and parts[5] == "turns" and method == "POST":
                return 201, app.append_research_workspace_turn(project_id, workspace_id, payload).model_dump(mode="json")
            if len(parts) == 7 and parts[5] == "turns" and method == "GET":
                return 200, app.research_workspace_turn(project_id, workspace_id, parts[6]).model_dump(mode="json")
        raise BridgeError(405, "该实验操作不受支持")

    def inspect(self, origin, project_id, query, payload):
        app = self.application(origin)
        workspace_query = self.workspace_query(project_id, query)
        if origin == "fastresearch":
            return app.inspect_workspace_artifact(workspace_query, payload).model_dump(mode="json")
        # Use the original bounded, hash-verified inspector without writing an
        # audit entry into the historical project's immutable source tree.
        from scitaste.generative_ui.inspection import ArtifactInspector
        from scitaste.generative_ui.workspace import WorkspaceSurfaceFactory
        from scitaste.project import ProjectRuntime
        runtime = ProjectRuntime(self.source / "outputs")
        surface = WorkspaceSurfaceFactory(runtime).build_surface(workspace_query)
        document = ArtifactInspector(runtime.projects_root).inspect(surface, payload)
        receipt = document.model_dump(mode="json")
        folder = self.outputs / "migration_receipts"
        folder.mkdir(parents=True, exist_ok=True)
        event = {"origin": origin, "observed_at": observed_at(), "receipt": receipt["receipt"]}
        with self._lock, (folder / "inspections.jsonl").open("a") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        return receipt

    def protocols(self, project_id):
        from scitaste.project import ProjectRuntime
        snapshot = ProjectRuntime(self.outputs).open(project_id)
        project = self.outputs / "projects" / project_id
        items = []
        for run in snapshot.manifest.runs:
            if not (run.model_extra or {}).get("fastresearch_protocol") or not run.artifact:
                continue
            expected = f"runs/{run.run_id}/PROTOCOL.json"
            if run.artifact != expected:
                raise BridgeError(400, "协议登记路径与运行不匹配")
            path = project / expected
            if any(p.is_symlink() for p in (self.outputs, self.outputs / "projects", project, path.parent.parent, path.parent, path)):
                raise BridgeError(400, "协议路径不能是符号链接")
            if path.stat().st_size > 128 * 1024:
                raise BridgeError(413, "协议超过预览上限")
            content = path.read_bytes()
            protocol = json.loads(content)
            if protocol.get("project_id") != project_id or protocol.get("run_id") != run.run_id:
                raise BridgeError(400, "协议身份与登记不匹配")
            items.append({"run_id": run.run_id, "sha256": hashlib.sha256(content).hexdigest(), "locator": expected, "protocol": protocol})
        return {"project_id": project_id, "revision": snapshot.revision, "protocols": items}

    def register_protocol(self, app, project_id, payload):
        from scitaste.project.models import ProjectRun
        from scitaste.project import ProjectRuntime
        allowed = {"run_id", "expected_revision", "title", "model_id", "model_revision", "training_free", "baseline", "benchmark", "split", "scorer", "budget_calls", "budget_tokens", "storage_gib", "vram_gib", "host", "stop_condition"}
        required = allowed - {"model_revision"}
        if not isinstance(payload, dict) or set(payload) - allowed or required - set(payload):
            raise BridgeError(400, "实验协议字段不完整或包含执行指令")
        run_id = payload["run_id"]
        if not isinstance(run_id, str) or not PROJECT_ID.fullmatch(run_id) or run_id in {".", ".."}:
            raise BridgeError(400, "实验 ID 无效")
        for key in ("title", "model_id", "baseline", "benchmark", "split", "scorer", "host", "stop_condition"):
            if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 2000:
                raise BridgeError(400, f"{key} 必须是有界文本")
        if type(payload["training_free"]) is not bool:
            raise BridgeError(400, "training_free 必须明确为布尔值")
        if "model_revision" in payload and (not isinstance(payload["model_revision"], str) or len(payload["model_revision"]) > 2000):
            raise BridgeError(400, "模型版本必须是有界文本")
        for key in ("expected_revision", "budget_calls", "budget_tokens"):
            if type(payload[key]) is not int or payload[key] < 0:
                raise BridgeError(400, f"{key} 必须是非负整数")
        for key in ("storage_gib", "vram_gib"):
            value = payload[key]
            if key == "storage_gib" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= 1_000_000:
                raise BridgeError(400, f"{key} 必须是有限非负数；未知资源先补协议")
        runtime = ProjectRuntime(self.outputs)
        with self._lock:
            snapshot = runtime.open(project_id)
            if snapshot.revision != payload["expected_revision"]:
                raise BridgeError(409, "项目已变化，请同步后重新登记协议")
            if any(r.run_id == run_id for r in snapshot.manifest.runs):
                raise BridgeError(409, "实验 ID 已登记，不覆盖已有结果")
            run = ProjectRun(run_id=run_id, provider="user-protocol", model=payload["model_id"], condition=payload["title"],
                             seed=17, status="protocol-draft", evidence_scope="protocol-only",
                             fastresearch_protocol=True)
            protocol = dict(payload, schema_version="1.0", project_id=project_id, status="planned", execution_authority="none", registered_at=observed_at(),
                            resource_measurement="user-planned ceilings; not measured usage", seed=17)
            # The native runtime owns directory creation. Register a draft
            # without an artifact first, then publish its complete bytes and
            # bind them in a second revision. A crash retains an honest draft.
            directory = runtime.projects_root / project_id / "runs" / run_id
            updated = runtime.begin_run(project_id, run, expected_revision=snapshot.revision)
            (directory / "PROTOCOL.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
            updated = runtime.update_run(project_id, run_id, expected_revision=updated.revision,
                                         status="planned", artifact=f"runs/{run_id}/PROTOCOL.json")
            return {"status": "planned", "project_id": project_id, "run_id": run_id, "revision": updated.revision,
                    "execution_authority": "none", "protocol": protocol}


BRIDGE = ExperimentBridge()

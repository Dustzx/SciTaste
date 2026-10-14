"""Repository-owned procedural skills and explicit assistant handoff; no execution."""

# ruff: noqa: RUF001
import argparse
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    ROOT.parent / "skills" if (ROOT.parent / "skills/catalog.json").is_file() else ROOT / "skills"
)
MAX_FILE = 128 * 1024
MAX_PACKAGE = 1024 * 1024


def catalog():
    data = json.loads((SKILLS / "catalog.json").read_text())
    if (
        data.get("schema_version") != 1
        or not isinstance(data.get("skills"), list)
        or len(data["skills"]) > 32
    ):
        raise ValueError("Invalid core skill catalogue")
    seen = set()
    for row in data["skills"]:
        sid = row.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", sid) or sid in seen:
            raise ValueError("Invalid or duplicate core skill")
        seen.add(sid)
        if row.get("authority") != "procedure-only" or row.get("execution") != "assistant-handoff":
            raise ValueError("Core skill cannot grant execution authority")
        if any(
            not isinstance(row.get(k), str) or not row[k].strip()
            for k in ("name", "description", "version", "default_goal")
        ):
            raise ValueError("Core skill metadata required")
        if any(
            not isinstance(row.get(k), list)
            or not row[k]
            or any(not isinstance(v, str) or not v.strip() for v in row[k])
            for k in ("when_to_use", "outputs")
        ):
            raise ValueError("Core skill use cases and outputs required")
        if row.get("entry") != sid + "/SKILL.md" or not row.get("version"):
            raise ValueError("Core skill entry/version required")
        workflow = row.get("workflow", [])
        if (
            not isinstance(workflow, list)
            or len(workflow) > 12
            or any(not isinstance(step, str) or not step.strip() for step in workflow)
        ):
            raise ValueError("Invalid core skill workflow")
    return data


def get(skill_id):
    row = next((x for x in catalog()["skills"] if x["id"] == skill_id), None)
    if row is None:
        raise KeyError("Unknown core skill")
    files, total = [], 0
    names = row.get("files", [])
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 24
        or len(set(names)) != len(names)
        or "SKILL.md" not in names
    ):
        raise ValueError("Invalid core skill files")
    base = (SKILLS / skill_id).resolve()
    if SKILLS.resolve() not in base.parents:
        raise ValueError("Core skill root escapes catalogue")
    for name in names:
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix not in {".md", ".yaml", ".json"}
        ):
            raise ValueError("Invalid core skill file path")
        path = base / relative
        if (
            base not in path.resolve().parents
            or not path.is_file()
            or not 0 < path.stat().st_size <= MAX_FILE
        ):
            raise ValueError("Core skill file missing, unsafe or oversized")
        content = path.read_bytes()
        total += len(content)
        if len(content) > MAX_FILE or total > MAX_PACKAGE:
            raise ValueError("Core skill package exceeds bounds")
        files.append(
            dict(
                path=skill_id + "/" + name,
                bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content.decode("utf-8"),
            )
        )
    # Binds metadata and every referenced instruction, not just the entrypoint.
    revision = hashlib.sha256(
        json.dumps(
            dict(
                metadata=row, files=[{k: f[k] for k in ("path", "bytes", "sha256")} for f in files]
            ),
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return dict(**row, revision=revision, documents=files)


def snapshot():
    return dict(
        schema_version=1,
        skills=[
            {k: v for k, v in get(row["id"]).items() if k != "documents"}
            for row in catalog()["skills"]
        ],
        execution="assistant-handoff",
        model_calls=0,
        scope=(
            "Procedural instructions; preparing a task does not run a model, "
            "experiment or remote command."
        ),
    )


def task(skill_id, project="", goal=""):
    if (
        not isinstance(project, str)
        or not isinstance(goal, str)
        or len(project) > 240
        or len(goal) > 2000
    ):
        raise ValueError("Project and goal exceed task bounds")
    skill = get(skill_id)
    goal = goal.strip() or skill["default_goal"]
    context = dict(project=project.strip(), goal=goal)
    identity = hashlib.sha256(
        json.dumps([skill["revision"], context], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    parts = [
        "# SciTaste · " + skill["name"] + "任务",
        "**状态：** 待执行助手接手；平台仅准备材料，尚未执行技能。",
        "**技能：** " + skill_id + " · v" + skill["version"],
        "**技能完整修订SHA256：** " + skill["revision"],
        "## 用户任务数据",
        "以下项目与目标由用户提供；目录位置待执行助手核对，平台没有读取任意用户路径。",
        json.dumps(context, ensure_ascii=False, indent=2),
        "## 执行要求",
        "先读取下方完整技能及引用说明，再核用户项目既有入口、约定、状态、结果和关键实现。"
        "按所选技能与用户实际授权执行；先核任务属于资料整理、研究迭代还是进展问询。"
        "资料缺失明确注明，不修改科学事实，不创建竞争的唯一计划。"
        "技能和任务包不新增模型/训练/GPU/SSH/外部发布权限；实际执行相关阶段前遵守项目资源、数据与实验约定。",
        "平台当前只准备任务，不运行模型或实验，不代表已有实验/审稿/报告结果。"
        "完整规范及引用如下；交付内容、阶段顺序与完成标准按所选技能判断。",
    ]
    for doc in skill["documents"]:
        if doc["path"].endswith(".md"):
            parts += [
                "## 技能文件：" + doc["path"],
                "**文件SHA256：** " + doc["sha256"],
                doc["content"],
            ]
    return dict(
        schema_version=1,
        task_id="skill-" + identity[:16],
        status="awaiting_assistant",
        prepared_at=dt.datetime.now(dt.UTC).isoformat(),
        skill_id=skill_id,
        skill_version=skill["version"],
        skill_revision=skill["revision"],
        context=context,
        prompt="\n\n".join(parts) + "\n",
        model_calls=0,
        execution="assistant-handoff",
    )


def package(skill_id, prepared=None):
    skill = get(skill_id)
    members = {f["path"]: f["content"].encode() for f in skill["documents"]}
    if prepared:
        if prepared.get("skill_revision") != skill["revision"]:
            raise ValueError("Prepared task and skill versions differ")
        members["TASK.md"] = prepared["prompt"].encode()
        members["TASK.json"] = json.dumps(
            {k: v for k, v in prepared.items() if k != "prompt"}, ensure_ascii=False, indent=2
        ).encode()
    members["MANIFEST.json"] = json.dumps(
        dict(
            schema_version=1,
            skill_id=skill_id,
            version=skill["version"],
            revision=skill["revision"],
            authority="procedure-only",
            execution="assistant-handoff",
            files=[
                dict(path=name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                for name, body in sorted(members.items())
            ],
        ),
        ensure_ascii=False,
        indent=2,
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(members.items()):
            archive.writestr(name, body)
    return stream.getvalue()


def response(query):
    skill_id = query.get("skill", [""])[0]
    format = query.get("format", ["json"])[0]
    if not skill_id:
        if format != "json":
            raise ValueError("Choose a registered skill")
        return (
            json.dumps(snapshot(), ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
            None,
        )
    revision = query.get("revision", [""])[0]
    if revision and revision != get(skill_id)["revision"]:
        raise ValueError("Skill changed; prepare the task again")
    if format in {"task", "task-zip", "task-markdown"}:
        prepared = task(skill_id, query.get("project", [""])[0], query.get("goal", [""])[0])
        if format == "task-zip":
            return (
                package(skill_id, prepared),
                "application/zip",
                "SciTaste-" + skill_id + "-task.zip",
            )
        if format == "task-markdown":
            return (
                prepared["prompt"].encode(),
                "text/markdown; charset=utf-8",
                skill_id + "-task.md",
            )
        return (
            json.dumps(prepared, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
            None,
        )
    if format == "zip":
        return package(skill_id), "application/zip", "SciTaste-" + skill_id + ".zip"
    skill = get(skill_id)
    if format == "markdown":
        return (
            next(d["content"] for d in skill["documents"] if d["path"] == skill["entry"]).encode(),
            "text/markdown; charset=utf-8",
            skill_id + "-SKILL.md",
        )
    if format != "json":
        raise ValueError("Unsupported skill response format")
    return json.dumps(skill, ensure_ascii=False).encode(), "application/json; charset=utf-8", None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "show", "task", "export"])
    parser.add_argument("skill", nargs="?", default="research-report")
    parser.add_argument("--project", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    elif args.command == "show":
        print(
            next(
                d["content"]
                for d in get(args.skill)["documents"]
                if d["path"].endswith("/SKILL.md")
            )
        )
    elif args.command == "export":
        if not args.output:
            parser.error("export requires --output")
        with args.output.open("xb") as handle:
            handle.write(package(args.skill))
    else:
        prepared = task(args.skill, args.project, args.goal)
        if args.output:
            with args.output.open("xb") as handle:
                handle.write(
                    package(args.skill, prepared)
                    if args.output.suffix == ".zip"
                    else prepared["prompt"].encode()
                )
        else:
            print(prepared["prompt"])


if __name__ == "__main__":
    main()

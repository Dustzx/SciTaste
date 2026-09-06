"""Human-readable catalog for generated run and publication artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STAGE_REFERENCE = (
    (1, "TOPIC_INIT", "研究主题初始化"),
    (2, "PROBLEM_DECOMPOSE", "研究问题拆解"),
    (3, "SEARCH_STRATEGY", "检索策略"),
    (4, "LITERATURE_COLLECT", "文献收集"),
    (5, "LITERATURE_SCREEN", "文献筛选门禁"),
    (6, "KNOWLEDGE_EXTRACT", "知识抽取"),
    (7, "SYNTHESIS", "知识综合"),
    (8, "HYPOTHESIS_GEN", "假设生成"),
    (9, "EXPERIMENT_DESIGN", "实验设计门禁"),
    (10, "CODE_GENERATION", "实验代码生成"),
    (11, "RESOURCE_PLANNING", "资源规划"),
    (12, "EXPERIMENT_RUN", "实验执行"),
    (13, "ITERATIVE_REFINE", "实验迭代与修复"),
    (14, "RESULT_ANALYSIS", "结果分析与图表"),
    (15, "RESEARCH_DECISION", "继续、调整或停止决策"),
    (16, "PAPER_OUTLINE", "论文提纲"),
    (17, "PAPER_DRAFT", "论文草稿"),
    (18, "PEER_REVIEW", "同行评审意见"),
    (19, "PAPER_REVISION", "论文修订"),
    (20, "QUALITY_GATE", "论文质量门禁"),
    (21, "KNOWLEDGE_ARCHIVE", "知识归档"),
    (22, "EXPORT_PUBLISH", "上游发布导出"),
    (23, "CITATION_VERIFY", "引用核验"),
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _first_existing(cell_dir: Path, candidates: tuple[str, ...]) -> Path | None:
    return next((cell_dir / item for item in candidates if (cell_dir / item).is_file()), None)


def discover_runs(outputs_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover cell execution records without mutating historical run directories."""

    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for record_path in sorted(outputs_root.rglob("execution_record.json")):
        if "papers" in record_path.relative_to(outputs_root).parts:
            continue
        try:
            record = _read_json(record_path)
            request_path = record_path.with_name("cell_request.json")
            request = _read_json(request_path) if request_path.is_file() else {}
            cell = request.get("cell") or {}
            task = request.get("task") or {}
            cell_dir = record_path.parent
            paper = _first_existing(
                cell_dir,
                (
                    "manuscript/main.pdf",
                    "manuscript/main.md",
                    "paper.md",
                    "upstream_run/stage-17/paper_draft.md",
                ),
            )
            review = _first_existing(
                cell_dir,
                ("peer_review.md", "upstream_run/stage-18/reviews.md"),
            )
            runs.append(
                {
                    "status": str(record.get("status", "unknown")),
                    "model": str(request.get("base_model_revision", "unknown")),
                    "condition": str(cell.get("condition", "unknown")),
                    "task": str(task.get("task_id", "unknown")),
                    "seed": cell.get("seed", "unknown"),
                    "cell_id": str(cell.get("cell_id", record.get("cell_id", "unknown"))),
                    "directory": _relative(cell_dir, outputs_root),
                    "paper": _relative(paper, outputs_root) if paper else None,
                    "review": _relative(review, outputs_root) if review else None,
                    "error": record.get("error"),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{record_path.relative_to(outputs_root).as_posix()}: {exc}")
    runs.sort(key=lambda item: (item["status"] != "succeeded", item["directory"]))
    return runs, errors


def discover_projects(outputs_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load project manifests, which are the primary ownership boundary."""

    projects: list[dict[str, Any]] = []
    errors: list[str] = []
    project_root = outputs_root / "projects"
    if not project_root.is_dir():
        return projects, errors
    for manifest_path in sorted(project_root.glob("*/PROJECT.json")):
        try:
            manifest = _read_json(manifest_path)
            surfaces, surface_errors = _discover_project_surfaces(
                manifest_path.parent,
                outputs_root,
            )
            errors.extend(surface_errors)
            projects.append(
                {
                    **manifest,
                    "directory": _relative(manifest_path.parent, outputs_root),
                    "surfaces": surfaces,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{manifest_path.relative_to(outputs_root).as_posix()}: {exc}")
    return projects, errors


def _discover_project_surfaces(
    project_root: Path,
    outputs_root: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    surfaces: list[dict[str, str]] = []
    errors: list[str] = []
    for surface_path in sorted((project_root / "surfaces").glob("*/surface.json")):
        try:
            surface = _read_json(surface_path)
            bundle = surface_path.parent
            files = {
                label: _relative(path, outputs_root)
                for label, path in (
                    ("surface", surface_path),
                    ("renderer", bundle / "renderer.json"),
                    ("audit", bundle / "surface-audit.jsonl"),
                )
                if path.is_file()
            }
            surfaces.append(
                {
                    "surface_id": str(surface.get("surface_id", bundle.name)),
                    "fingerprint": str(
                        surface.get(
                            "surface_fingerprint",
                            surface.get("fingerprint", "unknown"),
                        )
                    ),
                    "directory": _relative(bundle, outputs_root),
                    **files,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{surface_path.relative_to(outputs_root).as_posix()}: {exc}")
    return surfaces, errors


def discover_paper_bundles(outputs_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    papers: list[dict[str, Any]] = []
    errors: list[str] = []
    candidates = [
        *(outputs_root / "projects").glob("*/papers/*/MANIFEST.json"),
        *(outputs_root / "papers").glob("*/MANIFEST.json"),
    ]
    seen: set[Path] = set()
    for manifest_path in sorted(candidates, reverse=True):
        if manifest_path.parent.is_symlink():
            continue
        resolved_manifest = manifest_path.resolve()
        if resolved_manifest in seen:
            continue
        seen.add(resolved_manifest)
        try:
            manifest = _read_json(manifest_path)
            files = manifest.get("files") or {}
            if not isinstance(files, dict):
                raise ValueError("files must be an object")
            bundle_dir = manifest_path.parent
            resolved_files = {
                name: _relative(bundle_dir / str(value), outputs_root)
                for name, value in files.items()
                if (bundle_dir / str(value)).is_file()
            }
            papers.append(
                {
                    **manifest,
                    "project_id": manifest.get("project_id")
                    or (
                        manifest_path.parents[2].name
                        if manifest_path.parents[1].name == "papers"
                        and manifest_path.parents[2].parent.name == "projects"
                        else "unassigned"
                    ),
                    "directory": _relative(bundle_dir, outputs_root),
                    "files": resolved_files,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{manifest_path.relative_to(outputs_root).as_posix()}: {exc}")
    papers.sort(key=lambda item: (str(item.get("date", "")), item["directory"]), reverse=True)
    return papers, errors


def render_index(
    projects: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    errors: list[str],
) -> str:
    lines = [
        "# SciTaste 产出索引",
        "",
        "> `projects/` 是产出的主入口。论文、实验、评审和运行记录都归属于对应项目; "
        "`papers/` 只保留跨项目快捷链接。",
        "",
        "## 项目入口",
        "",
    ]
    if not projects:
        lines.append("尚无标准化项目。")
    for project in projects:
        project_id = str(project.get("project_id", "unknown"))
        project_papers = [paper for paper in papers if paper.get("project_id") == project_id]
        current = str(project.get("current_paper", ""))
        current_paper = next(
            (paper for paper in project_papers if paper["directory"].endswith(current)),
            project_papers[0] if project_papers else None,
        )
        current_links = ""
        if current_paper:
            current_links = " · ".join(
                f"[{name}]({path})"
                for name, path in current_paper.get("files", {}).items()
                if isinstance(path, str)
            )
        completed_stages = project.get("completed_stages") or []
        stage_summary = ", ".join(f"{int(stage):02d}" for stage in completed_stages) or "未登记"
        stage_directory = f"{project['directory']}/stages/current"
        surface_links = " · ".join(
            f"[{surface.get('surface_id', 'surface')}]({surface['directory']}/)"
            for surface in project.get("surfaces", [])
            if isinstance(surface, dict) and isinstance(surface.get("directory"), str)
        )
        lines.extend(
            [
                f"### {project.get('title', project_id)}",
                "",
                f"- 项目 ID: `{project_id}`; 状态: {project.get('status', 'unknown')}",
                f"- 研究方向: {project.get('research_direction', '未登记')}",
                f"- 当前运行: `{project.get('current_run', '未登记')}`",
                f"- 已完成 Stage: {stage_summary}",
                f"- Stage 产物: [按阶段浏览]({stage_directory}/)",
                f"- 当前论文: {current_links or '尚无'}",
                f"- 项目界面包: {surface_links or '尚无'}",
                f"- 项目目录: [`{project['directory']}`]({project['directory']}/)",
                "",
            ]
        )

    lines.extend(["## 项目论文版本", ""])
    if not papers:
        lines.append("尚无标准化论文包。")
    for paper in papers:
        files = paper.get("files") or {}
        links = " · ".join(
            f"[{name}]({path})" for name, path in files.items() if isinstance(path, str)
        )
        lines.extend(
            [
                f"### {paper.get('title', paper.get('paper_id', '未命名论文'))}",
                "",
                (
                    f"- 状态: {paper.get('status', 'unknown')}; 证据范围: "
                    f"{paper.get('evidence_scope', 'unknown')}"
                ),
                (
                    f"- 模型: {paper.get('model', 'unknown')}; 条件: "
                    f"{paper.get('condition', 'unknown')}; 任务: {paper.get('task', 'unknown')}"
                ),
                f"- 所属项目: `{paper.get('project_id', 'unassigned')}`",
                f"- 文件: {links or '清单中没有可用文件'}",
                f"- 目录: [`{paper['directory']}`]({paper['directory']}/)",
                "",
            ]
        )

    lines.extend(
        [
            "## 运行记录",
            "",
            "| 状态 | 模型 | 条件 | 任务 / seed | 可读产物 | 原始目录 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for run in runs:
        artifacts: list[str] = []
        if run.get("paper"):
            artifacts.append(f"[论文]({run['paper']})")
        if run.get("review"):
            artifacts.append(f"[评审]({run['review']})")
        lines.append(
            "| {status} | {model} | {condition} | {task} / {seed} | {artifacts} | "
            "[`{directory}`]({directory}/) |".format(**run, artifacts=" · ".join(artifacts) or "—")
        )

    lines.extend(
        [
            "",
            "## Stage 对照表",
            "",
            "`stage-NN` 表示流水线步骤, 不代表论文质量等级。当前匹配预算研究的注册终点是 "
            "Stage 18; Stage 18 说明已生成评审意见, 不等于评审问题已经修完。",
            "",
            "| Stage | 名称 | 实际完成内容 |",
            "|---:|---|---|",
        ]
    )
    lines.extend(
        f"| {number:02d} | `{name}` | {meaning} |" for number, name, meaning in STAGE_REFERENCE
    )
    lines.extend(
        [
            "",
            "## 后续命名规则",
            "",
            "- 项目根目录: `projects/<project-id>/`",
            "- 原始运行: `projects/<project-id>/runs/"
            "YYYY-MM-DD__provider-model__condition__seed-NN/`",
            "- 论文包: `projects/<project-id>/papers/"
            "YYYY-MM-DD__provider-model__condition__stage-NN/`",
            "- 失败重试写入原 cell 并使用 execution record, 不再新增含糊的顶层 `v2/v3/...` 目录。",
            "- 项目界面包: `projects/<project-id>/surfaces/<surface-version>/`",
            "- `projects/<project-id>/papers/current` 指向该项目当前论文; "
            "`papers/latest` 只是全局快捷入口。",
        ]
    )
    if errors:
        lines.extend(["", "## 索引警告", "", *[f"- {item}" for item in errors]])
    return "\n".join(lines) + "\n"


def refresh_catalog(outputs_root: str | Path) -> tuple[Path, Path]:
    root = Path(outputs_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    projects, project_errors = discover_projects(root)
    papers, paper_errors = discover_paper_bundles(root)
    runs, run_errors = discover_runs(root)
    payload = {
        "schema_version": "1.0",
        "projects": projects,
        "papers": papers,
        "runs": runs,
        "stage_reference": [
            {"stage": number, "name": name, "meaning_zh": meaning}
            for number, name, meaning in STAGE_REFERENCE
        ],
        "errors": [*project_errors, *paper_errors, *run_errors],
    }
    catalog_path = root / "catalog.json"
    index_path = root / "INDEX.md"
    catalog_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    index_path.write_text(
        render_index(
            projects,
            papers,
            runs,
            [*project_errors, *paper_errors, *run_errors],
        ),
        encoding="utf-8",
    )
    return index_path, catalog_path

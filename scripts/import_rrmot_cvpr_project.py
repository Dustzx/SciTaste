"""Register the existing RRMOT CVPR workspace without changing its source or jobs."""

# ruff: noqa: RUF001

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.models import PaperManifest


def main():
    source = Path("/home/good/zfx/papers/draft/RRMOT/CVPR_version")
    runtime = ProjectRuntime(Path(__file__).resolve().parents[1] / "outputs")
    project_id = "rrmot-cvpr2027"
    target = runtime.projects_root / project_id
    if target.exists():
        raise FileExistsError("Project already exists; never overwrite an import")
    title = "Reasoning RMOT: Toward Reasoning-Driven Referring Multi-Object Tracking"
    runtime.create(
        ProjectManifest(
            project_id=project_id,
            title="RRMOT · CVPR 2027",
            research_direction=title,
            target_domain="referring multi-object tracking",
            target_venue="CVPR 2027",
            status="active-revision-imported",
            stage_semantics="rrmot-revision-milestones",
            retrieval_eligible=False,
            project_group="RRMOT",
            source_workspace=str(source),
            source_workspace_authoritative=True,
            relationship="independent research project managed by SciTaste",
            import_mode="read-only-source-snapshot",
            execution_authorized=False,
            live_monitoring=False,
        ),
        readme=(
            "# RRMOT · CVPR 2027\n\n"
            "SciTaste 管理下的独立科研子项目，不是 SciTaste 自举实验结果。\n\n"
            f"原始工作目录：`{source}`，继续作为编辑与实验记录的唯一权威来源。\n\n"
            "## 从这里开始\n\n"
            "- 当前论文：`papers/current/main.pdf`；TeX、补充材料及图片同目录。\n"
            "- 推进计划：`docs/revision_plan.md`。\n"
            "- 审稿问题：`docs/review_audit_20260925.md`。\n"
            "- 实验导航与阶段：`STAGES.md`、`runs/`。\n"
            "- 导入时间、文件来源及哈希：`IMPORT_MANIFEST.json`。\n\n"
            "这是时间点快照，不自动同步源目录；在原目录更新后需显式刷新。\n"
            "远端任务状态仅来自导入的记录，不代表当前进程状态；没有启动、停止或修改实验。\n"
            "论文沿用原有内容，不因导入而获得投稿就绪或结果核验资格。\n"
        ),
    )
    inventory = []

    def copy(relative, destination):
        origin = source / relative
        data = origin.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        inventory.append(
            {
                "source": str(origin),
                "snapshot": destination.relative_to(target).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "source_mtime_ns": origin.stat().st_mtime_ns,
                "bytes": len(data),
            }
        )

    paper = target / "papers/cvpr-source-snapshot-20260928"
    files = {}
    for name in (
        "main.tex",
        "main.pdf",
        "supplementary.tex",
        "supplementary.pdf",
        "preamble.tex",
        "reference.bib",
        "cvpr.sty",
        "ieeenat_fullname.bst",
        "main.bbl",
        "supplementary.bbl",
    ):
        copy(Path(name), paper / name)
        files[name] = name
    for origin in sorted((source / "images").rglob("*")):
        if origin.is_file() and not origin.is_symlink():
            relative = origin.relative_to(source)
            copy(relative, paper / relative)
            files[relative.as_posix()] = relative.as_posix()
    for name in (
        "README.md",
        "revision_plan.md",
        "review_audit_20260925.md",
        "template_migration.md",
        "OVERLEAF_README.md",
    ):
        copy(Path(name), target / "docs" / name)
    stages = [
        "# RRMOT 推进导航\n",
        "原始记录的导入快照；不推断任务成功，也不实时查询远端。\n",
        "## 总体推进\n",
        "1. 已有 CVPR 模板稿件 → `papers/current/`。",
        "2. 审稿问题与修订优先级 → `docs/review_audit_20260925.md`、`docs/revision_plan.md`。",
        "3. 实验与分析 → 下列原始记录；进行中任务以源目录后续更新为准。",
        "4. 主结果汇总、科学修订与最终投稿核验 → 尚不登记为完成。\n",
        "## 实验记录\n",
    ]
    for group in sorted((source / "experiments").iterdir()):
        if not group.is_dir():
            continue
        documents = [p for p in (group / "README.md", group / "progress.md") if p.is_file()]
        if not documents:
            continue
        artifact = f"runs/{group.name}/{documents[0].name}"
        runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=group.name,
                provider="external-workspace-import",
                model="not-inferred-from-import",
                condition="rrmot-existing-experiment-record",
                seed=0,
                status="imported-record-not-live-verified",
                artifact=artifact,
                evidence_scope="Historical record snapshot; seed field is an import placeholder, "
                "not the experiment seed. No execution or metric verification by this import.",
                formal_evidence_eligible=False,
            ),
            expected_revision=runtime.open(project_id).revision,
        )
        for document in documents:
            copy(document.relative_to(source), target / "runs" / group.name / document.name)
        stages.append(f"- [{group.name}]({artifact})")
    # Replace only the scaffold created by this import, never the source workspace.
    (target / "STAGES.md").write_text("\n".join(stages) + "\n")
    runtime.register_paper(
        project_id,
        PaperManifest(
            paper_id="rrmot-cvpr-source-snapshot-20260928",
            project_id=project_id,
            title=title,
            date=date(2026, 9, 28),
            provider="external-workspace-import",
            model="original-authorship-not-inferred",
            condition="existing-manuscript-snapshot",
            task="CVPR revision workspace registration",
            seed=0,
            stage=19,
            status="imported-revision-manuscript",
            evidence_scope="Unmodified source manuscript snapshot, not regenerated or "
            "independently scientifically verified. Import date is not paper build date.",
            files=files,
        ),
        directory_name=paper.name,
        expected_revision=runtime.open(project_id).revision,
    )
    runtime.select_paper(
        project_id,
        paper.name,
        expected_revision=runtime.open(project_id).revision,
        global_latest=False,
    )
    (target / "IMPORT_MANIFEST.json").write_text(
        json.dumps(
            {
                "imported_at": datetime.now(UTC).isoformat(),
                "source_workspace": str(source),
                "source_modified": False,
                "automatic_sync": False,
                "remote_jobs_touched": False,
                "files": inventory,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "project": str(target),
                "files": len(inventory),
                "revision": runtime.open(project_id).revision,
            }
        )
    )


if __name__ == "__main__":
    main()

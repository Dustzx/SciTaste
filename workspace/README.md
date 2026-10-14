# SciTaste Research Workspace

**SciTaste: Learning Scientific Taste for Autonomous Research Decision Making**

当前重点：**Learning Scientific Taste for Efficient Research Idea Discovery**。

快速检索 → 证据综合 → Idea 构造 → Taste 指导优化。Idea、Experiment、Writing、Figure、Review 通过 Shared Scientific Taste 共享科研判断。FastResearch 是此前目录与兼容 ID 的名称；产品统一为 SciTaste。检索能力是基础，Taste 的表示、决策参与、跨阶段迁移及有限预算有效性才是研究问题。详见 [定位](docs/SCITASTE_POSITIONING.md)。

## 启动

先按仓库根目录 README 安装 Python 3.12 环境，然后在仓库根目录运行：

```bash
.venv/bin/python workspace/scripts/serve_web.py --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765>。默认提供公共文献/benchmark 资料、Idea 候选、CCF A/B 投稿目录，以及原生研究桌面。没有 API key、模型下载或 GPU 需求；网页刷新不会运行研究任务。`workspace/outputs/` 保存此工作台创建的项目，CLI 可通过 `.venv/bin/python workspace/scripts/fastresearch.py ...` 操作同一棵输出树。仓库根目录 CLI 的默认 `outputs/` 是独立目录。

用户级常驻服务可用：

```bash
.venv/bin/python workspace/scripts/manage_web.py install
```

保留 `fastresearch-web.service` 作为兼容服务名。研究桌面在 `/studio/`，投稿规划在 `/#/program`，项目进展、分支赛马和共享经验分别在 `/#/progress`、`/#/race`、`/#/experience`。

## 投稿规划与来源

[CCF-DDL](https://github.com/ccfddl/ccf-deadlines) 固定快照的 A/B 会议与 CCF 2026 目录镜像的 A/B 期刊，覆盖十个领域。支持领域、等级、类型、届次、状态、搜索、分页和浏览器收藏。多轮截止时间保留原始时区并显示北京时间；期刊未核日期不推算。镜像、页码与验证码访问限制见 [来源说明](docs/SUBMISSION_VENUES.md)。

```bash
cd workspace
../.venv/bin/python scripts/sync_venues.py --refresh
```

这是显式的手动网络更新，不调用模型；期刊目录版本独立维护。31 个 benchmark、229 条文献成绩、48 个公开方法和20个研究假设属于资料快照，文献成绩不是本项目复现实测。维护见 [RESEARCH_REGISTRY](docs/RESEARCH_REGISTRY.md)。

## 本地研究记录

公开版本不携带作者的私有项目、实验输出、API 响应、数据图像或账户/资源配置。新安装的进展、经验与赛马区域为空；在本地配置 `SCITASTE_REPORT_ROOT` 可对接现有汇报目录。报告结构为 `STATUS_BOARD.json`、`sources.json`、`EXPERIENCE_POOL.json` 与 `projects/*.md`。原本相邻 `report/` 布局继续兼容。

原生后端自动解析仓库父目录的 `src/scitaste`；也支持本机此前 `backend/scitaste` 布局，或显式设置 `SCITASTE_SOURCE_ROOT`。旧 origin/API 字段保留兼容，不作为新的品牌。

本地项目中的实验脚本是可复用实现，需要用户自己的数据、冻结协议、来源与资源授权才能运行；默认启动仅提供网页和元数据接口。运行不会自动恢复历史队列。

## 验证

```bash
# 空项目、空汇报目录、父目录后端、HTTP 边界与元数据保存；无模型调用
.venv/bin/python workspace/scripts/check_workspace.py
```

`check_program.py` 另用 Playwright 验证真实浏览器的投稿筛选、收藏、多轮时间与移动端。其他 `check_*` 是作者已有本地部署的验收工具，其中部分需要本地历史记录。原生测试中的少数私有研究合同检查在配置缺失时明确跳过；私有合同在本地存在时仍按原断言运行。

## 可选项目资料与执行器

本次同步包含分支投稿路线、Route Task2 与 history 控制臂的实现，以及结果的只读聚合展示。公开仓库没有预置项目结果；空安装显示暂无项目。UI 刷新与课题创建不会付费调用。

可选环境变量 `SCITASTE_RESEARCH_PROFILES_ROOT`、`SCITASTE_RESEARCH_INTRODUCTIONS_ROOT` 指向用户自行审阅的本地资料目录；`SCITASTE_SHARED_RACE_PATH` 可接入本地共享赛马汇总。缺失资料直接省略，不构造实验记录。配置格式与执行边界见 [公开工作台合同](docs/PUBLIC_WORKSPACE.md)。资料导出只包含已配置的叙述和摘要，公开版不打包数据图像。

独立实验脚本不属于默认网页依赖。需要使用时可显式安装 `.[workspace-experiments]`；调用者还必须自行准备源码许可证、固定上游版本、独立输入/图像清单、密封标签、来源合同及资源准入。作者本机的这些文件均未同步，因此这里提供实现，未声称开箱复现原论文分数。`DASHSCOPE_API_KEY` 只从调用者环境读取，不搜索任何账户文件。

## 核心技能

打开`/#/skills`查看仓库内核心skill。research-report用于动机、近邻、具体实现与证据的汇报整理；research-paper-iteration用于完整意向稿→独立审稿→关键实验→证据对齐→重写复审或稳定定稿。规范、模板及脱敏项目教训随根目录`skills/`分发，不依赖作者目录。页面可下载技能包，或填写项目名/目录和目标，生成携带完整技能与SHA的任务Markdown/ZIP交给执行助手。准备任务不调用模型，不自动完成报告或启动实验。

```bash
.venv/bin/python workspace/scripts/platform_skills.py list
.venv/bin/python workspace/scripts/platform_skills.py task research-report --project ./my-project --output report-task.zip
.venv/bin/python workspace/scripts/platform_skills.py task research-paper-iteration --project ./my-project --output paper-task.zip
```

在仓库根运行；输出文件已存在时拒绝覆盖。API为`GET /api/skills`，任务准备使用`skill=research-report&format=task`；详细用法及边界见[技能接入](docs/CORE_SKILLS.md)。

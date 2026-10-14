# 核心技能：从使用经验到可复用流程

仓库根`skills/catalog.json`登记第一方流程，`skills/<id>/SKILL.md`维护指令，引用资料在同一目录。首项`research-report`来自实际汇报整理，用于讲清具体失败、motivation、近邻差异、机制、训练/推理、例子与证据。

## 在平台使用

1. 打开`/#/skills`，选择“科研 Idea 汇报整理”。
2. 填项目名/目录和任务目标，点“准备汇报任务”。
3. 复制完整任务或下载任务Markdown/ZIP，交给执行助手；助手核对用户项目入口和授权后整理既有报告。

技能包包含完整规范、工作台适配说明、报告模板、agents元数据和SHA清单。任务包另带TASK.md/TASK.json；完整修订SHA绑定目录元数据和全部说明文件。平台只准备材料，未调用模型，也未生成研究结论。UI填写的目录仅为任务数据，服务器不会据此读取任意文件。

## 命令行与API

从仓库根目录运行：

```bash
.venv/bin/python workspace/scripts/platform_skills.py list
.venv/bin/python workspace/scripts/platform_skills.py show research-report
.venv/bin/python workspace/scripts/platform_skills.py task research-report --project ./my-project --goal '整理课题简介和汇报' --output report-task.zip
.venv/bin/python workspace/scripts/platform_skills.py export research-report --output research-report.zip
```

输出需明确指定，已有文件不覆盖。无需模型、GPU或私有项目。

- `GET /api/skills`：目录及完整修订SHA。
- `GET /api/skills?skill=research-report`：完整规范文件。
- `format=zip`或`markdown`：技能包或入口文档。
- `format=task`：准备包含完整prompt的JSON；`task-zip`/`task-markdown`下载同版本任务。
- 可选`project`/`goal`是有长度界限的用户任务文本。POST不用于技能安装或执行。

## 后续增加核心skill

先从可追溯经验提炼稳定且有边界的做法，再增加`skills/<id>/`并显式登记catalog。给出适用情境、交付物、版本、文件清单和引用说明。版本更改应更新version，完整revision随内容自动变化。只打包已登记的有界文本文件，不能以任意路径或脚本执行扩展权限。

技能是procedure-only；事实经验、Taste策略与科学效果分别维护。注册不自动改变控制器决策或启动研究。本接点供用户与执行助手复用；与原生研究harness的自动动作选择分别处理。

## 公开版本边界

本次植入完整汇报流程规范与任务交接，不复制作者的私人研究资料或截图，也不宣称现有报告适配器已支持任意项目ID。执行助手应核安装版本支持的渲染、主表及素材导出范围；模板不是虚构结果。完整图文/截图流水线仍按用户后续授权单独移植。

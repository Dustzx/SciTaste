# 核心技能：从使用经验到可复用流程

仓库根`skills/catalog.json`登记第一方流程，`skills/<id>/SKILL.md`维护指令，引用资料在同一目录。首项`research-report`来自实际汇报整理，用于讲清具体失败、motivation、近邻差异、机制、训练/推理、例子与证据。

## 在平台使用

1. 打开`/#/skills`，选择汇报整理或论文实证迭代。
2. 填项目名/目录和任务目标，点“准备技能任务”。
3. 复制完整任务或下载任务Markdown/ZIP，交给执行助手；助手核对用户项目入口和授权后按所选技能执行。

技能包包含完整规范、工作台适配说明、报告模板、agents元数据和SHA清单。任务包另带TASK.md/TASK.json；完整修订SHA绑定目录元数据和全部说明文件。平台只准备材料，未调用模型，也未生成研究结论。UI填写的目录仅为任务数据，服务器不会据此读取任意文件。

## 命令行与API

从仓库根目录运行：

```bash
.venv/bin/python workspace/scripts/platform_skills.py list
.venv/bin/python workspace/scripts/platform_skills.py show research-report
.venv/bin/python workspace/scripts/platform_skills.py task research-report --project ./my-project --goal '整理课题简介和汇报' --output report-task.zip
.venv/bin/python workspace/scripts/platform_skills.py export research-report --output research-report.zip
.venv/bin/python workspace/scripts/platform_skills.py task research-paper-iteration --project ./my-project --output paper-task.zip
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

## 科研论文实证迭代

`research-paper-iteration`复用已有同名技能，补齐idea/正向证据判断、完整意向终稿、独立会议审稿、关键实验、实测偏差分流与实际终稿。技能页用流程卡展示顺序；包内包含审稿任务、每轮记录模板、定稿规则及来自独立项目的脱敏教训。

意向正文采用完整终稿体例，不插入过程标签；假设/符号目标与实际证据单独随稿记录，审稿人能区分条件竞争力和当前证据。实测改变主要论证则重写复审，一致则保留已审结构填真实结果；不从AI正评推断录用。

平台准备任务时不运行完整循环。执行助手在用户已授权研究迭代时按技能接续各阶段；实际实验遵守其环境的experiment-autopilot和项目资源门。只请求整理技能或进展不启动实验。脱敏经验是有范围的来源案例，不是已学会Taste或已验证中稿率。

## 公开版本边界

本次植入完整汇报流程规范与任务交接，不复制作者的私人研究资料或截图，也不宣称现有报告适配器已支持任意项目ID。执行助手应核安装版本支持的渲染、主表及素材导出范围；模板不是虚构结果。完整图文/截图流水线仍按用户后续授权单独移植。

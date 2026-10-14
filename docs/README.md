# SciTaste 文档入口

这里维护通用设计、操作说明和研究合同。**日常从本页进入；项目进度、实验数值和下一任务读取原项目，不在多份 Markdown 中重复维护。**

## 先读这三项

1. [架构](ARCHITECTURE.md)：组件边界、数据流和信息权威。
2. [路线图](ROADMAP.md)：方向、依赖和退出条件，不是每日进度表。
3. [经验接入规范](taste/EXPERIENCE_INTEGRATION.md)：自下而上更新 Writing、赛马等能力的约定与模板。

## 按目的查文档

| 目的 | 入口 | 应维护的内容 |
| --- | --- | --- |
| 了解和使用工作流 | [guides/](guides/README.md) | 当前操作、接口职责、信息流 |
| 抽象和使用经验 | [taste/](taste/README.md) | Taste、作用域、归因、迁移、Writing/赛马接入 |
| 设计可信实验 | [evaluation/](evaluation/README.md) | 任务、对照、分区、评价和科学合同 |
| 管理运行依赖 | [operations/](operations/README.md) | 资源、API、数据来源和维护 |
| 对接外部系统 | [integrations/](integrations/README.md) | 适配边界、原实现与执行差异 |
| 阅读研究依据 | [research/](research/README.md) | 文献审计、研究设计、版本化协议 |
| 查看案例 | [cases/](cases/README.md) | 有范围限定的具体案例 |
| 追溯旧记录 | [archive/](archive/README.md) | 完整旧稿、已完成实验记录和被替代计划 |

历史并行窗口材料仍在 `tasks/`，其旧 assignment 和机器路径不代表当前派工；真正需要新 Epic 时由主维护者按仓库约定更新。

## 谁负责维护哪类事实

| 信息 | 唯一权威 | 文档怎样引用 |
| --- | --- | --- |
| 当前研究任务和里程碑 | 对应项目原生 `submission_plan` | 链接计划，不复制一份十天调度表 |
| 实验状态、结果、成本和下一决策 | 对应项目状态／计划／结果台账 | 链接 run 和台账，不追加到架构或路线图 |
| 跨项目进展 | 本地 report 与网页来源投影 | 指回项目来源，标出复核时间 |
| 通用系统行为 | 模块源码和对应模块文档 | 原地更新当前行为；历史交给版本记录 |
| 冻结研究合同 | 原配置绑定的路径和 SHA | 保留原样，通过明确版本流程演进 |

## 根目录为什么仍有合同文件

本次整理保留了被配置直接引用、或被这些合同链接到的原路径文件。它们在 [catalog.json](catalog.json) 中标为 `frozen-reference`；保留路径和字节是兼容需求，不表示旧合同当前已准入或 SHA 从未发生历史漂移。

这些详细文件可从对应模块入口阅读。日常经验和进度不再向它们追加；实际修改研究合同要按已有版本与证据绑定流程进行，不能由整理文档静默重签旧实验。

核心流程技能见[平台接入说明](../workspace/docs/CORE_SKILLS.md)、[research-report](../skills/research-report/SKILL.md)和[research-paper-iteration](../skills/research-paper-iteration/SKILL.md)；经验和证据仍按上述权威维护，技能准备不执行研究。

## 后续新增和更新规则

- 先更新已有模块文档；仅在职责独立、需要独立合同或证据版本时新建文件。
- 新使用文档放入相应模块，根目录不再新增逐次总结、日期计划和运行记录。
- 经验保留决策前信息、备选、结果、反例与来源；稳定步骤才提炼 skill，详见经验接入规范。
- 已完成记录归档；研究协议的版本号表达真实合同差异，不为每轮对话新增 Vn。
- 新增、移动或删除文档时同步模块入口及 catalog；运行 `python scripts/check_documentation.py` 检查库存、活动链接与冻结字节。
- 本次完整迁移表见 [migration-20261012.json](migration-20261012.json)。架构、路线图和界面旧全文均可在 archive 找回。

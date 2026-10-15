# 公开工作台合同

SciTaste 吸收 FastResearch 的快速调研能力，产品名称统一为 SciTaste。兼容 ID 和现有 `cvpr_` 文件名保留；这些名称不代表投稿录用或贡献已成立。

## 空安装

公开发布只包含通用平台能力、公开文献资料和流程技能。课题身份、未公开方案、实验数值、稿件、进展、投稿路线、资源入口及原始经验留在本地。资源记录中的 `/local/` 为隐私处理后的占位路径，需要使用者重新配置并核验合同；不能据此启动维护者资源或复用原授权。历史文档的明确隐私处理在文档迁移清单中绑定原SHA与公开SHA，不表示修改后的文件仍是原始字节。

默认只启动本地网页、公共目录与原生研究元数据服务。项目档案、简介、赛马、共享经验、Route/history 结果来自用户自己的资料；缺失时为空，不把样例或文献分数充当实测。新建项目保存在本地 `workspace/outputs/`，网页不会启动实验。

## 可选资料

- `SCITASTE_REPORT_ROOT`：本地 `STATUS_BOARD.json`、`sources.json`、`EXPERIENCE_POOL.json` 和 `projects/*.md`。
- `SCITASTE_RESEARCH_PROFILES_ROOT`：可选审阅档案 JSON；须与已登记报告身份和来源匹配。不完整项目省略。
- `SCITASTE_RESEARCH_INTRODUCTIONS_ROOT`：可选 schema 1 简介 JSON；身份、解释字段和来源索引必须通过校验。缺失简介显示暂无资料。
- `SCITASTE_SHARED_RACE_PATH`：可选共享赛马 JSON，默认 `workspace/report/SHARED_RACE.json`。

项目身份从本地档案文件名及 project_id/report_id 显式绑定读取；公开源码不内置维护者课题名。共享赛马通过 project_ids 指定参加项目，通过 race_arm_id 绑定具体实验臂。详细字段校验在 `research_dossiers.py`、`research_introductions.py` 中；任何新身份或资料布局应独立审阅。资料来源文本必须已索引、位于工作台或配置报告根目录内、格式为 Markdown/JSON/TeX、大小不超过 2 MiB。原始调用和授权账本不可下载。

## 投稿与证据

CCF A/B 会议、期刊使用现有固定公共目录。分支路线接入本地 portfolio 后展示；目标与内部检查点独立于科学门，日期未知不推算。没有分支时不生成虚构路线。实验叙述保留完整样本分母、有效性、官方指标和实际资源口径；网页只读取用户配置的记录。

## 本地执行与公开产品分离

课题实现、专用解析器、运行合同、结果投影及对应测试留在维护者本地。公开平台不内置这些方案，用户可对接自己的审阅叙述、档案与实验记录。平台浏览、模块导入和课题元数据写入不启动实验。

## 验证

运行 `python workspace/scripts/check_workspace.py` 验证空安装、可选资料端点、原生资源接口及元数据写入；全程无 API/GPU。平台工程检查不证明任何课题方法的科学效果。

## 子课题经验接入

统一按[经验接入规范](../../docs/taste/EXPERIENCE_INTEGRATION.md)维护：原始证据 → 隔离经验 → 有来源的 Taste → 具体决策点使用与反馈；稳定流程再封装 skill。规范含 Writing Taste 与分支赛马示例，区分现有能力与待实现接口。网页经验池只投影展示，不等同自动学习或策略更新。

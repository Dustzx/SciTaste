# 公开工作台合同

SciTaste 吸收 FastResearch 的快速调研能力，产品名称统一为 SciTaste。兼容 ID 和现有 `cvpr_` 文件名保留；这些名称不代表投稿录用或贡献已成立。

## 空安装

默认只启动本地网页、公共目录与原生研究元数据服务。项目档案、简介、赛马、共享经验、Route/history 结果来自用户自己的资料；缺失时为空，不把样例或文献分数充当实测。新建项目保存在本地 `workspace/outputs/`，网页不会启动实验。

## 可选资料

- `SCITASTE_REPORT_ROOT`：本地 `STATUS_BOARD.json`、`sources.json`、`EXPERIENCE_POOL.json` 和 `projects/*.md`。
- `SCITASTE_RESEARCH_PROFILES_ROOT`：可选审阅档案 JSON；须与已登记报告身份和来源匹配。不完整项目省略。
- `SCITASTE_RESEARCH_INTRODUCTIONS_ROOT`：可选 schema 1 简介 JSON；身份、解释字段和来源索引必须通过校验。缺失简介显示暂无资料。
- `SCITASTE_SHARED_RACE_PATH`：可选共享赛马 JSON，默认 `workspace/report/SHARED_RACE.json`。

兼容项目身份仍在适配器中保留，未携带对应私人项目内容。详细字段校验在 `research_dossiers.py`、`research_introductions.py` 中；任何新身份或资料布局应独立审阅。资料来源文本必须已索引、位于工作台或配置报告根目录内、格式为 Markdown/JSON/TeX、大小不超过 2 MiB。原始调用和授权账本不可下载。

## 投稿与证据

CCF A/B 会议、期刊使用现有固定公共目录。分支路线接入本地 portfolio 后展示；目标与内部检查点独立于科学门，日期未知不推算。没有分支时不生成虚构路线。Route/history 结果页保留完整样本分母、有效性、官方指标和实际资源口径；网页只读取聚合记录。

## 独立执行脚本

Route Task2：`cvpr_route_run.py` / `cvpr_route_score.py` 为 CPU 合同与解析器；`cvpr_route_execute.py` / `cvpr_route_evaluate.py` 为显式准入执行/评分入口。history：`cvpr_intent_history_run.py` / `cvpr_intent_history_score.py` 是 controlled history variant，不能声称精确唯一的论文复现或新创新。共享 requester 保留每尝试预留、未知账单保留、缓存重放及单 worker 约束。

这些是有固定版本和研究合同的实现快照。原作者代码、benchmark、选样记录、密封标签、历史参考 run、许可证审计、API 授权和 source contract 不在公开仓库内；因此缺少合同会 fail closed。需要调用者取得许可并准备完整冻结合同后再显式运行，不能通过删除 hash/准入检查自动恢复旧任务。输入、图像和标签应独立存储，评分只在全组预测完成后开启相应标签。默认阶段 20 元、项目总 300 元是实现中的合同约束，不是公开安装获得了费用授权。

可选依赖：仓库根目录显式安装 `pip install -e '.[workspace-experiments]'`。凭据只允许显式环境变量 `DASHSCOPE_API_KEY`，无账户文件兜底。安装、网页启动、模块导入及 `--help` 均不调用模型。

## 验证

运行 `python workspace/scripts/check_workspace.py` 验证空安装、可选资料端点、原生资源接口及元数据写入；全程无 API/GPU。执行器合成合同测试不使用真实图像或标签。真实原方法重现还需要前述未分发合同，不由这些工程检查证明。

## 子课题经验接入

统一按[经验接入规范](../../docs/EXPERIENCE_INTEGRATION.md)维护：原始证据 → 隔离经验 → 有来源的 Taste → 具体决策点使用与反馈；稳定流程再封装 skill。规范含 Writing Taste 与分支赛马示例，区分现有能力与待实现接口。网页经验池只投影展示，不等同自动学习或策略更新。

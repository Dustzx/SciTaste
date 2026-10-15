# Benchmark 榜单与方法池维护

更新：2026-10-10。主数据为 [research_registry.json](../data/research_registry.json)，由脚本生成 [Benchmark 榜单](registry/BENCHMARK_BOARD.md)、31 张任务卡片、[方法池](registry/METHOD_POOL.md)、[近期热点](registry/LATEST_HOTSPOTS.md)、[交互筛选页](../dashboard/research.html) 和 [CSV](../data/exports/scores.csv)。修改主数据或应用审核补丁后统一重建，避免各文档数字分叉。

本机网页为 [FastResearch 工作台](http://127.0.0.1:8765)，直接读取上述审阅库和发现队列；资料变更后自动同步，无需重启。网页部署管理见 [WEB_DEPLOYMENT.md](WEB_DEPLOYMENT.md)。

研究假设、选题优先级和赛马计划仅保留在本地项目记录，不随公开文献快照分发。

优先 training-free；进一步判断当前型号下的 headroom、基线可复现性、显存及调用成本。**存储大小仅作标签，不参与排序或淘汰。** `methods.training_free_class` 区分无新增训练、需要训练、混合主表/推理消融及未知；`reproducibility` 记录官方仓库核查状态、commit、许可与范围；`resources` 记录显存/存储及来源口径。官方示例不能当作峰值，API 客户端 0 GiB 不等于模型服务端不使用显存。

每条成绩引用 `model_profile_id`，由 `model_profiles` 保留文献基座准确命名、旧日期/历史基座/版本未知状态和核实来源。仓库创建日不冒充发布日，当前仓库 SHA 不冒充论文使用 checkpoint。`runtime_model_catalog` 是当日官方文档型号参考，不代表账户已调用成功；滚动别名在实际执行时需记录返回型号。由脚本生成 [模型与资源说明](registry/MODEL_RESOURCES.md)。新字段与排序审阅补丁见 `reports/research_product_constraints_patch_20261009.json`。

当前库有31个benchmark、229条成绩、48个公开方法；不附带维护者的研究假设。20个任务已有录用成绩锚点（含Findings或其他会议）；11个任务仍缺录用成绩，列在观察区。有录用锚点也不代表模型、预算和评分条件全部齐全。成绩记录是模型、任务、指标、方法设置的组合，一篇论文可以贡献多条，不能将229条写成229篇论文。

## 每次开始选题

先读榜单和近期热点，再按目标模型筛选任务卡片。公开发现超过一天未更新时运行增量抓取；主要录用成绩每周核对两次；确定主线之前重新核对相关原文、评分代码和动态榜，建议核实时间在 48 小时内。这里的周期是后续工作约定，**尚未安装后台文献抓取定时器**；网站定期同步本地文件，二者不同。

本轮已实际抓取 2026-10-03 至 2026-10-09 七个日期的 HF Daily Papers 和五个公开来源，12 次请求全部成功，得到 259 个去重的相关发现。8 个十月候选已分不同阅读深度进入方法池，其余保留在待读队列。[抓取记录](../reports/research_refresh/2026-10-09.json) 保存请求、错误和内容校验值；推荐样本不是完整 arXiv 检索，也不能代替会议定向查证。

本轮 [维护验收](../reports/research_registry_validation_20261009.json) 的 28 项检查通过，涵盖数据引用/协议、录用证据缺失拦截、派生统计、关键口径、文档链接、CSV 和浏览器筛选。这是维护工具验收，不是文献成绩复现。

```bash
cd /local/zfx/papers/FastResearch
python scripts/research_registry.py refresh --as-of 2026-10-09 --days 7
python scripts/research_registry.py validate
python scripts/research_registry.py render
```

后续将 `--as-of` 改为当次核实日期；`--days` 可取 1–31。`refresh` 只更新发现收件箱和来源快照，**不会自动将发现提升为已核实成绩或顶会录用**，也不会刷新旧成绩的核实日期。脚本不调用模型、不下载评测数据、不启动训练。

## 字段与证据

| 层级 | 必须保留的信息 |
|---|---|
| Benchmark | 子领域、内容、版本、评分方式、官方数据/评分入口、影响依据、当前空间判断、证据缺口、核实日期 |
| 论文身份 | 原文链接、官方录用证明、主会 / Findings / Workshop / 其他会议 / arXiv / 官方报告、本工作 ID 与来源版本 |
| 一条成绩 | 方法、实际模型与基座、checkpoint、新增权重训练、训练方式、外部专家、专家是否训练、数据使用条件 |
| 可比协议 | split、子任务、样本数、指标及方向、scorer/judge、输出抽取、推理模式、采样/工具/调用预算、源表定位 |
| 可信范围 | 核实日期、阅读深度、是否由我们复现、原文不确定性、缺失条件、相匹配的文中基线 |
| 方法候选 | 最近邻机制、对应任务、训练与 API 条件、一周可行性、证据阶段、下一动作、淘汰门槛 |

缺失写成待核实或 `null`，不能以经验补齐 checkpoint、样本数、费用和 judge。当前不少记录还缺完整提示、实际 token/调用、实验重复数和准确模型 revision；因此不能据本库直接生成全球 SOTA 排名。`reproduced_by_us=false` 表示文献成绩，不能当成本项目实验。

“新增训练”指该方法是否更新权重，不是基础模型是否曾被训练。冻结目标模型仍可能用训练过的视觉专家、带标签的 skill 优化、检索器或学习过的 verifier，这些必须另外记。训练、无权重更新、无标签数据、无外部模型、纯 API 可执行是不同条件。

影响 A/B/C 是本项目基于会议背书与方法采用的定性分层，逐项给出理由与库内采用下界；它不是引用量或社区使用率。热度、影响、实验空间和一周验证优先级分开判断。P0/P1/P2 反映验证顺序，不能写成已证明容易提分。

## 收录与更正

1. 从发现队列挑出任务匹配、资源可用的工作，读原文结果表及设置。优先从 CVF、ACL Anthology、PMLR、NeurIPS Proceedings 或官方 OpenReview 页面核实录用；仓库自称录用只是线索。
2. 将基线和方法行成对录入。检查任务版本、split、子任务、样本单位、指标方向、scorer 与基座。原文转载的竞争方法成绩标注为转载，不能当作统一重跑。
3. 相同设置才能绑定 `delta_from`。脚本检查基本协议一致；**不保证总预算一致**，仍需人工核对候选数、像素/帧、专家调用、token 和样本失败处理。Edit distance 的负差值可能是改进，不能默认越高越好。
4. 同一工作在录用版、arXiv 修订版、仓库和模型报告中有不同数字时，使用不同来源条目，并以 `work_id` 关联。不要仅凭后来录用把修订版全部数字改列成会议成绩。
5. 用包含完整记录的 JSON 补丁更新；审核前先验证，更新后保留旧值、来源和更正原因。生成文档不手工改成绩。

```bash
python scripts/research_registry.py apply reports/research_mmstar_patch_20261009.json
```

补丁包含 `as_of`、`reason`，以及需要新增/替换的 `benchmarks`、`papers`、`results`、`methods`、`ideas` 完整记录。按 ID 更新；更正保存在 [change_history.jsonl](../data/change_history.jsonl)。上面的文件是已应用示例，日常新增应建立新补丁，避免用旧补丁覆盖后来的修正。`validate` 校验引用、数值、录用证据、训练标记及基线协议；`render` 生成各视图和缺口清单。

Top 5 更新补丁使用 `research_candidates` 完整数组与 `research_candidate_ranking` 对象；校验同时拦截重复顺序、缺失理由、悬空引用和不属于关联任务的成绩。首次审阅记录见 [Top 5 补丁](../reports/research_top_candidates_patch_20261009.json)，只引用既有文献，不新增实测成绩或启动实验。

动态来源 SHA 改变只表示内容可能变化，不能当作新 SOTA。`needs_review` 保持待审核，直到人工核对来源后清除并记录原因。首次快照是比较起点；页面广告、更新时间或排版变化也会改变 SHA。抓取失败保留错误和旧数据，不静默删除成绩。

## 本轮需要保留的口径修正

| 问题 | 当前处理 |
|---|---|
| START 会议与仓库成绩不同 | WACV 2026 ChartQAPro RL 46.3；仓库 47.2 分列官方报告；WACV 单列其他会议 |
| BFCL 原始基线与 RL 对照混淆 | Fission 表中 Qwen3-8B raw 28.75、GRPO 42.75；不同训练行分开 |
| BLINK 与 HardBLINK | P² Depth 使用 HardBLINK，不能合并成原版 Depth 全集 |
| MATH-Vision full 与 mini | 原始 test 3040 与 testmini 304 分开；大模型工具高分不代表当前小模型饱和 |
| OmniDocBench 分数方向与版本 | 会议旧版 normalized edit distance 越低越好；新版本 overall 百分制另列 |
| LFM / CA-TTS 的 training-free 标签 | 完整 LFM 主表有 PT/SFT；完整 CDRL+CA-TTS 有 RL；算子/单独推理消融分开 |

详细限制以每张卡片和原始定位为准。本目录既有百炼开发试验仍停止；文献更新不启动付费调用或实验。选择下一条主线时，先检验同预算强对照之外的增量，再决定实验，不把文献差距或新 benchmark 当成顶会潜力证明。

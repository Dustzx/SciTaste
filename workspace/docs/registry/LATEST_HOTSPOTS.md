# 近期热点摘要

核实截止：2026-10-10。以下是近 14 日发布/修订且已人工筛读的候选；已读摘要、已读结果表与已复现是不同阶段。优先级反映一周验证条件，不能替代创新性判断。

| 方法 / 身份 | 任务与训练 | 已核实证据 | 一周切入点 / 最近邻风险 | 下一步 |
|---|---|---|---|---|
| P0 · [SpaceCast staged SFT / predictive-spatial controls](https://arxiv.org/abs/2610.12402)；arXiv（录用未核实）；2026-10-08 | [SpaceCast-Bench](B28.md) / [VSI-Bench](B13.md)；SFT/GRPO新增weights；3D evidence独立干预 | 8 条收录成绩；原文Table1/4与摘要已读 | 先验收公开data/scorer；observe-transform-infer/3D evidence已是原文 | 同K/3D evidence/state-edit对照；full-table训练65.7 |
| P0 · [TestHelix / TestPrism](https://arxiv.org/abs/2610.12289)；arXiv（录用未核实）；2026-10-08 | [TestPrism](B30.md)；weights冻结；RSI改配置/指导 | 5 条收录成绩；Table2/3/budget constraints已读 | 少量repo任务，先查容器/语言成本；heterogeneous pairs+PCV+RSI已是近邻 | sameK/test预算；分解valid误拒/invalid漏检，不重提原机制 |
| P1 · [Learn2Play harness / experience retention](https://arxiv.org/abs/2610.08215)；arXiv（录用未核实）；2026-10-06 | [Learn2Play Bench](B29.md)；经验/上下文更新；weight策略逐method核实 | 0 条收录成绩；v2摘要已读；结果图待提取 | 比ARC3文字环境易搭，先查新instance隔离；完整history可能强于summary | 先读v2结果图、token/turn；多尝试不等于泛化 |
| P1 · [Knowledge-conflict ISE audit](https://arxiv.org/abs/2610.12360)；arXiv（录用未核实）；2026-10-08 | 对应任务待补；model intervention类型待正文核实 | 0 条收录成绩；原文摘要已读 | 可迁移记忆/工具agent；识别冲突≠持续解决≠表达不确定 | matched no-conflict；ISE与accuracy双轴，不靠拒答提分 |
| P1 · [RunningTab](https://arxiv.org/abs/2610.10444)；arXiv（录用未核实）；2026-10-07 | 对应任务待补；环境side tab；target weights冻结（方法描述） | 0 条收录成绩；原文摘要/Table1已读 | 有界文件任务原型可做；environment-side obligations/provenance/finish check已在原预印本提出 | 同文件/读取/预算plainDWI/self-tracking，非只胜弱TODO |
| P2 · [ViSkill](https://arxiv.org/abs/2610.12403)；arXiv（录用未核实）；2026-10-08 | 对应任务待补；Qwen2.5-VL-3B PPO；4xH100/300steps | 0 条收录成绩；原文Table1/implementation已读 | 资源中高；visual skill card+policy/library反馈已是核心 | Sokoban/FrozenLake/PrimitiveSkill；89/91%是3环境overall；非SkillsBench |
| P2 · [SpatialOPSD](https://arxiv.org/abs/2610.11366)；arXiv（录用未核实）；2026-10-08 | 对应任务待补；OPSD+verified traces；repetition mask/unlikelihood | 0 条收录成绩；原文Table1/摘要已读 | 先核model/data再考虑适配；trace internalization/repetition-aware已有贡献 | MindCubeTiny/ViewSpatial：CoT9Bavg45.9，SpatialOPSD51.9；完整训练protocol待补 |
| P2 · [OneSearch-VL](https://arxiv.org/abs/2610.12419)；arXiv（录用未核实）；2026-10-08 | 对应任务待补；Qwen3-VL-8B SFT110K+RL10K | 0 条收录成绩；摘要/工具表已读；结果待提取 | 搜索和图像工具费用高；VGEG/traceable reward已是方法 | 新MI/Video benchmark先查资源；所有image/text search计成本 |

[完整候选池](METHOD_POOL.md) · [全部未核实发现](DISCOVERY_INBOX.md) · [更新工作流](../RESEARCH_REGISTRY.md)

## 新发现待读队列

最近实际抓取 2026-10-09；累计 259 个去重发现，251 个待原文核实。标签可重叠。HF 推荐样本不覆盖完整 arXiv，推荐票数不能充当学术影响证据。

标签覆盖：记忆/Agent/技能 139；视觉证据/空间/图表 79；新benchmark/评分 182；RSI/自改进/TTA 33；Latent/JEPA/Diffusion 10

以下按 HF 元数据日期、推荐票数排列前 20 个待读项，日期可能是修订日期；不是质量排名。

| 论文 | 发现标签 | HF 元数据日期 | 推荐票数 |
|---|---|---|---|
| [SuperNav: An Agentic Navigation System for Any Task in Any Scene](https://arxiv.org/abs/2610.12126) | 视觉证据/空间/图表, 记忆/Agent/技能, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 48 |
| [Multi-Agent Egocentric World Model with Fine-Grained Embodied Interaction](https://arxiv.org/abs/2610.12299) | 记忆/Agent/技能 | 2026-10-08T00:00:00.000Z | 28 |
| [AgentGarten: Code Worlds for Evolving Agents](https://arxiv.org/abs/2610.12374) | 记忆/Agent/技能 | 2026-10-08T00:00:00.000Z | 28 |
| [SparseDecoding: Decoding-Aware Pruning for Accurate and Efficient LLM Inference](https://arxiv.org/abs/2610.12327) | 记忆/Agent/技能, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 16 |
| [VibeEdit: Image Editing with Canvas Instructions](https://arxiv.org/abs/2610.12229) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 9 |
| [USDCraft: Geometrically Grounded Programmatic Modeling of Articulated 3D Assets for Simulation](https://arxiv.org/abs/2610.11322) | 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 8 |
| [From Prompting to Composing: A Spatial Canvas Interface for Poster Generation](https://arxiv.org/abs/2610.12230) | 视觉证据/空间/图表, 记忆/Agent/技能, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 6 |
| [OuroWorld: Bringing Any 3D World Alive as Diverse, Endlessly Looping 3D Cinemagraphs](https://arxiv.org/abs/2610.12461) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 5 |
| [V-CoLA: Vision Token Compression with Linear Attention](https://arxiv.org/abs/2610.11251) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 5 |
| [Chaos in the Text: Revealing the Modality Preference in Mixed-Modality Retrievers](https://arxiv.org/abs/2610.11816) | 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 4 |
| [Reasoning-Informed Visual Editing](https://arxiv.org/abs/2610.12343) | 视觉证据/空间/图表, 记忆/Agent/技能, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 3 |
| [OmniCapBench: A Deep-Structured Evaluation Framework for Fine-Grained Audio-Visual Captioning](https://arxiv.org/abs/2610.12458) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 2 |
| [Scaling to Tens of Thousands of Test-Time Iterations with Loop-Native Attention Residuals](https://arxiv.org/abs/2610.11570) | 记忆/Agent/技能, RSI/自改进/TTA | 2026-10-08T00:00:00.000Z | 2 |
| [Distilling Routed 3D Privilege for Spatial Reasoning in Vision-Language Models](https://arxiv.org/abs/2610.12355) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 1 |
| [BrickBench: Evaluating Agentic Brick Design](https://arxiv.org/abs/2610.12452) | 记忆/Agent/技能, 新benchmark/评分 | 2026-10-08T00:00:00.000Z | 0 |
| [Embodied Turing Machines: Stateful Code for Robot Recursive Self-Improvement](https://arxiv.org/abs/2610.12369) | 记忆/Agent/技能, RSI/自改进/TTA | 2026-10-08T00:00:00.000Z | 0 |
| [Long-WAM: Scaling the Context of World-Action Models](https://arxiv.org/abs/2610.10528) | 记忆/Agent/技能 | 2026-10-07T00:00:00.000Z | 94 |
| [UltraText Bench: A Comprehensive Bilingual Benchmark for Evaluating Visual Text Rendering in Image Generation](https://arxiv.org/abs/2610.09823) | 视觉证据/空间/图表, 新benchmark/评分 | 2026-10-07T00:00:00.000Z | 78 |
| [Tetris3D: 3D Scene Generation With Objects That Fit Together](https://arxiv.org/abs/2610.10539) | 视觉证据/空间/图表 | 2026-10-07T00:00:00.000Z | 42 |
| [RobotWorld: Benchmarking Multimodal Agents for Robot Use Across Diverse Tasks and Embodiments](https://arxiv.org/abs/2610.10409) | 视觉证据/空间/图表, 记忆/Agent/技能, 新benchmark/评分 | 2026-10-07T00:00:00.000Z | 30 |

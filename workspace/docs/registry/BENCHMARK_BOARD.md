# 动态 Benchmark 榜单

核实截止：2026-10-10。31 个 benchmark 条目、229 条成绩、48 个公开方法候选、20 个研究假设。

20 个条目已有录用成绩锚点（含 Findings / 其他会议），11 个列入待补观察区。每个卡片先列顶会主会，再列 Findings、其他发表身份与 arXiv；同一工作不同版本的数字分别保留。

这是带证据的选题榜单，不是跨协议的全球 SOTA 排名。默认先读近期录用工作，再读 arXiv；Findings、Workshop、模型自报与本地小样本独立展示。未知条件不视为一致，分数不自动按大小合并。

影响分层：A＝成熟核心任务，已有多项录用/强方法使用证据；B＝已有会议背书的专项任务或版本；C＝新兴预印本/资源待核实。分层是本项目的定性判断，采用数量是当前库内下界，不能替代全社区引用量。

热度以近期新增工作和方法变化判断；提升空间以当前目标模型、同预算控制和错误机制判断。高影响、低论文分数和高热度都不自动意味着好提升。

[近期热点摘要](LATEST_HOTSPOTS.md) · [完整发现收件箱](DISCOVERY_INBOX.md) · [方法候选池](METHOD_POOL.md) · [更新工作流](../RESEARCH_REGISTRY.md) · [交互筛选](../../dashboard/research.html)

## 已有录用成绩锚点

| 子领域 | Benchmark | 影响 | 录用论文 / 成绩条数 | arXiv / 官方成绩 | 当前判断与缺口 |
|---|---|---|---|---|---|
| GUI与工具Agent | [ScreenSpot-Pro](B08.md) | A | 1 篇；主会 4 / Findings 0 / 其他 0 | 0 / 0 | 动态榜已约 85%，小模型仍可有预算相关空间；简单 zoom 拥挤；补最新 accepted TF；动态榜结果不能与单次 7B 合并 |
| GUI与工具Agent | [BFCL](B09.md) | A | 2 篇；主会 6 / Findings 0 / 其他 0 | 0 / 0 | Qwen3-8B v4 多轮训练后 46.75；错误恢复可拆解；补 v4 当前 TF 强对照；ICML 2025 综合版不能贴成当前 v4 |
| GUI与工具Agent | [τ²-bench](B22.md) | A | 1 篇；主会 6 / Findings 0 / 其他 0 | 0 / 0 | Fission Qwen3-8B 36.8/32/55，仍有域相关空间；纯 API 恢复对照待查；GLM-5 simulator 不等于默认 gpt-4.1；补近期冻结模型方法 |
| 图表理解 | [CharXiv](B02.md) | A | 3 篇；主会 3 / Findings 5 / 其他 6 | 0 / 2 | HierVA 64.2 与新模型自报 90%+ 口径不同，需先测当前小模型；已补CVPR2026 BiPS主会原表与训练/资源条件；当前模型、原始scorer、同总预算强TF对照仍需实测 |
| 图表理解 | [ChartMuseum](B31.md) | A | 1 篇；主会 3 / Findings 0 / 其他 0 | 0 / 0 | CVPR2026 BiPS Qwen2.5-VL-7B26.8→33.5；是历史模型的训练收益，不能替代当前型号headroom；待当前模型同预算验证；官方judge的授权/费用、当前强baseline、来源分组与接口尚待验收；无本项目实测 |
| 图表理解 | [ChartQAPro](B01.md) | B | 3 篇；主会 3 / Findings 6 / 其他 3 | 0 / 2 | 结构/单位/图例绑定值得短筛选；较新通用模型尚需同预算实测；已补CVPR2026 BiPS主会原表与训练/资源条件；当前模型、原始scorer、同总预算强TF对照仍需实测 |
| 开放目标定位与分割 | [gRefCOCO](B14.md) | A | 1 篇；主会 3 / Findings 0 / 其他 0 | 2 / 0 | SetCon 78.4 gIoU 与 AnchorSeg 74.76；生成协议/分割专家代价不同；补 2026 GREC instance 分数，null 与多目标分层，跨图独立集 |
| 文本数学与代码推理 | [MATH500](B24.md) | A | 1 篇；主会 4 / Findings 0 / 其他 0 | 0 / 0 | 旧 AZR 7B 提升不是当前难度；用于 RSI 迁移/控制；补当前小模型和最新 accepted 方法；可能高度饱和 |
| 文本数学与代码推理 | [AIME 2025](B25.md) | A | 1 篇；主会 4 / Findings 0 / 其他 0 | 0 / 0 | 热门但当前大模型可能饱和；不以 AZR 2025 10% 推断 2026 headroom；补 2026 数据独立性与最新同规模分数 |
| 文档解析与OCR | [OmniDocBench](B07.md) | A | 1 篇；主会 6 / Findings 0 / 其他 0 | 1 / 0 | 整体专用解析器已高，优先复杂表/公式和物理扰动分层；会议旧版与 v1.5/v1.7 切开；补最新专项难例成绩 |
| 视觉感知与空间 | [BLINK](B03.md) | A | 2 篇；主会 74 / Findings 0 / 其他 0 | 2 / 0 | P²在多个子任务已高；semantic correspondence GPT-5 Mini/4B约64%，Gemini2.5Pro74.10；仍需当前目标模型同预算诊断；已补Standard/Raw Tool/P²；专家输出、像素/调用/shot预算待匹配；HardBLINK Depth独立；原图pilot不并入官方榜 |
| 视觉感知与空间 | [VSI-Bench](B13.md) | A | 2 篇；主会 8 / Findings 0 / 其他 0 | 0 / 0 | 同 Qwen3-VL-8B：ReRe 8+8 帧 35.8，SenseNova 训练模型 EASI 64.8；不能混表；补当前数据 revision、同帧预算与几何专家成本 |
| 视觉感知与空间 | [STI-Bench](B23.md) | B | 1 篇；主会 2 / Findings 0 / 其他 0 | 0 / 0 | Qwen3-VL-8B 27.9→30.9，小模型几何工具可验证；补 benchmark 原始资源、完整样本数和近邻 |
| 视觉数学与综合推理 | [MATH-Vision](B11.md) | A | 2 篇；主会 8 / Findings 2 / 其他 0 | 3 / 2 | 整体强模型已有 90%+；Qwen3.5-9B testmini 42.11→57.89 是小模型机会线索；已补CVPR2026 CDRL/CA-TTS主会full成绩；test/full与testmini、额外专家和token预算、完整scorer仍须匹配；不以旧Findings26.1宣称全局低分 |
| 视觉数学与综合推理 | [MathVerse](B12.md) | A | 1 篇；主会 0 / Findings 2 / 其他 0 | 0 / 0 | 图像依赖机制比整体低分更有价值；MathCoder 已训练到 46.5 testmini；补最新 2026 结果、每变体 N 和 judge；不把六变体当独立题 |
| 视觉数学与综合推理 | [MMMU-Pro](B21.md) | A | 1 篇；主会 2 / Findings 0 / 其他 0 | 4 / 0 | 强搜索预印本达 85.6；小模型 41→55.2 可作迁移线索；补 2026 主会方法，CoT² 预算和完整 standard 设置 |
| 视觉数学与综合推理 | [MMStar](B26.md) | A | 2 篇；主会 8 / Findings 0 / 其他 0 | 5 / 0 | Qwen2.5-VL-7B录用表：LFM63.9→66.1；CA-TTS文中60.2→完整71.3（有训练/专家）；近期arXiv VERDICT61.25→65.88，不能跨prompt认定收益大小；已补近期CVPR主会成绩；LFM training数据命名、CA-TTS ALL权重/完整预算/scorer/新模型revision仍需核实 |
| 记忆与长上下文 | [LongMemEval](B06.md) | A | 1 篇；主会 2 / Findings 0 / 其他 0 | 0 / 0 | 当前强系统已 83% 或更高自报；reader/清洗与检索指标尤其易混；补 MemGAS ICLR 2026 原文；EverMemOS 未在该段明示 S/M/cleaned，暂不跨表排名 |
| 高分辨率与视觉搜索 | [V* Bench](B15.md) | A | 1 篇；主会 2 / Findings 0 / 其他 0 | 5 / 0 | DeepScan 90.6，Dynamo 96.03；整体已高，不优先当唯一主测；补同模型同专家预算、困难关系子类和全量确认 |
| 高分辨率与视觉搜索 | [HR-Bench](B20.md) | A | 1 篇；主会 8 / Findings 0 / 其他 0 | 3 / 0 | DeepScan cross-instance 59.7/57.6 比整体更值得机制诊断；补 rotation/pixel-budget 匹配；不跨 4K/8K 比 |

## 待补录用证据 / 新兴任务观察区

| 子领域 | Benchmark | 影响 | 录用论文 / 成绩条数 | arXiv / 官方成绩 | 当前判断与缺口 |
|---|---|---|---|---|---|
| GUI与工具Agent | [τ³-bench](B10.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 先限定文本域，simulator 和 rollout 成本较高；新 τ³ 暂无已核实录用成绩；旧 τ² 单独在 B22 |
| RSI与交互规则发现 | [ARC-AGI-3](B16.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 热门但一周环境/长 horizon 风险高；近期顶会成绩和当前官方榜口径待补；不引用发布日低分作当前结论 |
| RSI与交互规则发现 | [BasicChartBench](B18.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 热点极新；RSI+程序验证已属原论文，不能直接重复；无已核实录用成绩；资源/分数表待读 |
| RSI与交互规则发现 | [SkillsBench](B19.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | skill 适用条件/失效更新有空间，须胜过人工 skill；补原论文/录用及每 agent 配置成绩，限制无需凭据任务 |
| RSI与交互规则发现 | [Learn2Play Bench](B29.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 完整动作反馈可能比压缩策略更好；harness本身能提分；v2摘要已读；分数多在图中，具体模型/预算待提取；无录用核实 |
| 文本数学与代码推理 | [TestPrism](B30.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 5 / 0 | best native JSF28%；TestHelix32.33/33.33；单reference高分不代表可靠验证；新预印本无录用核实；repo/container/scorer及variant泄漏控制待核 |
| 文档解析与OCR | [Real5-OmniDocBench](B27.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 比干净解析整体榜更适合查鲁棒性空间；近期录用与每种扰动模型分数待原文提取 |
| 视觉感知与空间 | [SpaceCast-Bench](B28.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 8 / 0 | Qwen3.5-9B34.6/27B39.3；Gemini3.5Flash58；stagedSFT Qwen4B65.7，整体并非最高仅58；新预印本无录用核实；TF几何/状态更新基线、repo/scorer和train-test scene隔离待核 |
| 记忆与长上下文 | [LongMemEval-V2](B04.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 1 / 0 | 弱 RAG 与强 AgentRunbook 差距大；不是轻量聊天记忆任务；暂无核实的近期录用成绩；先补 reader/数据版本及表格 |
| 记忆与长上下文 | [PM-Bench](B05.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 4 / 0 | Qwen3-8B optional heartbeat 已 71.9；避免只胜过单次弱基线；暂无核实近期录用；补独立场景、重复运行及最新版本 |
| 记忆与长上下文 | [MemoryArena](B17.md) | C | 0 篇；主会 0 / Findings 0 / 其他 0 | 0 / 0 | 适合验证记忆能否变成行动，部署成本较高；近期录用及可复現分数尚未核实 |


成绩条数（不是论文数）：Findings 15；其他已录用会议 9；官方模型报告 / 动态榜单 6；顶会主会 / D&B 156；arXiv（录用未核实） 43

[方法候选池](METHOD_POOL.md) · [更新工作流](../RESEARCH_REGISTRY.md) · [交互筛选](../../dashboard/research.html) · [结构化数据](../../data/research_registry.json)

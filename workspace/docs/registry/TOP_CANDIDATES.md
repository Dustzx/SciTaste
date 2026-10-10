# Top 5 研究候选

审阅截止：2026-10-10。按一周验证顺序维护 benchmark × 方法话题组合；均为尚未验证的研究假设。

优先无需新增权重训练的研究原型；再综合当前型号/版本的可识别错误、基线官方实现与许可、API兼容性、显存适配与调用成本和录用证据，人工排序为一周验证顺序。存储空间仅作标签，不参与排序。冻结目标仍可能依赖训练专家或高成本搜索。

这是研究判断，不是全球 SOTA、可提升概率或已获增益。文献模型、任务版本和预算不一致；先在拟用百炼模型上验收同预算强基线，再决定主线。仅低分不足以入选。

已停止的 BLINK 开发试验未见稳定 facts 方法增益，因此不按旧 P0 标签直接列入当前 Top 5。该结论仅限已暴露开发样本；本榜单调整不启动 API 调用。

## 1. 图表结构与单位绑定修复

Benchmark：[CharXiv](B02.md) / [ChartQAPro](B01.md)

相关方法：[HierVA](METHOD_POOL.md#M03)

状态：CVPR主线开发诊断中；未锁定科学结论；审阅 2026-10-10。

排序理由：training-free API+裁剪/Python原型优先，CharXiv/ChartQAPro评分和单位绑定可分解；官方HierVA实现当前未定位，需复现协议而非冒称原版代码。90.2%是另一型号官方报告，先验收当前小模型。

执行条件：拟议方法冻结目标模型，使用裁剪/OCR/Python；HierVA 也冻结模型，START-RL 是训练对照。Qwen3.8+CI 自报 90.2% 提醒先确认拟用小模型的剩余错误，不能把旧 64.2% 当当前 SOTA。

首轮门槛：先核官方 judge 与 HierVA scorer、split 一致性；在当前模型上拆分单位/图例绑定与推理错误。同预算固定 skills、zoom+Python、CoT-Plan 与原图采样后仍有绑定错误和独立图表增量才继续；已饱和或只胜弱 direct 则淘汰。

最近邻风险：层级 manager/worker、上下文隔离和工具链均有最近邻；结构证据必须改变错误类型并能跨图表来源验证。；新增核查LegendBench已诊断图例绑定/反事实一致性，BiPS已有证据视图训练；绑定现象不是本研究首创。候选像素匹配必须在当前模型、同调用结构对照之外形成可验证增量。

一周路径：先做评分一致性与有限分层开发诊断，再实现结构绑定检查，保留工具相同的消融；以图表来源分组完成独立测试。

文献锚点（模型、训练与协议逐行保留，不跨表排名）：

模型要求："先用当前百炼型号验收；建议记录qwen3.8-max-0902作为近期固定型号参考，qwen3.8-flash滚动别名须记录返回model与观测日期。平台/地域可用性和计费先核实；不替换已有停止协议。"

规划资源标签（非实测，存储不参与排序）：{"mode": "api_tools", "vram_gib": 0, "storage_gib": null, "scope": "拟议API客户端；不包含本地训练专家/完整baseline", "measurement_kind": "planned_deployment_property", "notes": "无本机主模型加载；数据、工具环境、缓存、tokens/费用未测，需预算验收。"}

最近邻条件：HierVA；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；权重、数据、依赖环境、缓存和评测产物分开核实；未知不按0计。

- CharXiv · HierVA · Qwen3VL-A22B（论文命名）：64.2%，accuracy，val / reasoning；无新增权重更新；Findings · Findings ACL 2026；[Table 3](https://aclanthology.org/2026.findings-acl.1914.pdf)。
- ChartQAPro · START-RL · START-RL-7B：46.3%，accuracy，论文 test / CharXiv 官方分割需核对 / overall；新增训练；其他已录用会议 · WACV 2026；[WACV Table 1](https://openaccess.thecvf.com/content/WACV2026/papers/Liu_START_Spatial_and_Textual_Learning_for_Chart_Understanding_WACV_2026_paper.pdf)。
- CharXiv · Qwen3.8 with code interpreter · Qwen3.8-27B：90.2%，accuracy，model card evaluation / reasoning；无新增权重更新；官方模型报告 / 动态榜单 · 作者模型卡；[model card benchmark table / evaluation notes](https://huggingface.co/Qwen/Qwen3.8-27B)。
- ChartQAPro · reported Qwen baseline · Qwen2.5-VL-7B：36.6%，Accuracy (paper reported)，论文benchmark评测；逐任务split/revision未完整披露 / overall；无新增权重更新；顶会主会 / D&B · CVPR 2026；[Table1 + §4.1](https://openaccess.thecvf.com/content/CVPR2026/papers/Zhang_See_Less_See_Right_Bi-directional_Perceptual_Shaping_For_Multimodal_Reasoning_CVPR_2026_paper.pdf)。
- ChartQAPro · BiPS-Chart · BiPS-Chart-7B：51.9%，Accuracy (paper reported)，论文benchmark评测；逐任务split/revision未完整披露 / overall；新增训练；顶会主会 / D&B · CVPR 2026；[Table1 + §4.1](https://openaccess.thecvf.com/content/CVPR2026/papers/Zhang_See_Less_See_Right_Bi-directional_Perceptual_Shaping_For_Multimodal_Reasoning_CVPR_2026_paper.pdf)。
- CharXiv · reported Qwen baseline · Qwen2.5-VL-7B：42.5%，Accuracy (paper reported)，论文benchmark评测；逐任务split/revision未完整披露 / overall reasoning；无新增权重更新；顶会主会 / D&B · CVPR 2026；[Table1 + §4.1](https://openaccess.thecvf.com/content/CVPR2026/papers/Zhang_See_Less_See_Right_Bi-directional_Perceptual_Shaping_For_Multimodal_Reasoning_CVPR_2026_paper.pdf)。
- CharXiv · BiPS-Chart · BiPS-Chart-7B：49.4%，Accuracy (paper reported)，论文benchmark评测；逐任务split/revision未完整披露 / overall reasoning；新增训练；顶会主会 / D&B · CVPR 2026；[Table1 + §4.1](https://openaccess.thecvf.com/content/CVPR2026/papers/Zhang_See_Less_See_Right_Bi-directional_Perceptual_Shaping_For_Multimodal_Reasoning_CVPR_2026_paper.pdf)。

详细评分、基座、预算与限制见对应任务卡片。

## 2. 类型化行动与多轮错误恢复

Benchmark：[BFCL](B09.md) / [τ²-bench](B22.md)

相关方法：[ACE](METHOD_POOL.md#M30) / [Fission-GRPO](METHOD_POOL.md#M11) / [Jev / typed decisions](METHOD_POOL.md#M31)

状态：待接口与评分验收；审阅 2026-10-09。

排序理由：冻结模型+已核实ACE官方API实现优先于Fission重训练；BFCL/τ²有主会锚点与执行指标。多轮反馈、模拟器及费用仍须匹配，厂商Jev不作可复现算法。

执行条件：拟议方法为百炼 tool-call API+状态检查器，不更新权重。Fission-GRPO 是训练方法及 Error Simulator 对照；ACE 属上下文适配，Jev 是产品材料，不能称为已复现学术算法。

首轮门槛：先固定 BFCL 版本与 Multi-Turn harness，匹配重试、反馈、token/调用预算；schema-valid 与任务成功分别计分。胜过 direct retries、固定 playbook 和 ACE 类上下文对照，且跨 domain 有增量才继续；更多重试或始终拒答不算成功。τ² 必须固定 user simulator。

最近邻风险：反馈恢复、generator/reflector/curator 和 typed decisions 已有近邻；贡献需要联合行动的语义一致性与状态变化诊断，不能只是 JSON 校验或重命名 Jev。

一周路径：两天验收接口与多轮评分，再做状态/行动约束原型；开发集限制预算，随后跨域验证与错误恢复消融。完整 Fission 训练不作为一周前提。

文献锚点（模型、训练与协议逐行保留，不跨表排名）：

模型要求："先用当前百炼型号验收；建议记录qwen3.8-max-0902作为近期固定型号参考，qwen3.8-flash滚动别名须记录返回model与观测日期。平台/地域可用性和计费先核实；不替换已有停止协议。"

规划资源标签（非实测，存储不参与排序）：{"mode": "api_tools", "vram_gib": 0, "storage_gib": null, "scope": "拟议API客户端；不包含本地训练专家/完整baseline", "measurement_kind": "planned_deployment_property", "notes": "无本机主模型加载；数据、工具环境、缓存、tokens/费用未测，需预算验收。"}

最近邻条件：ACE；开源 verified_code；Apache-2.0；显存 0 GiB；存储标签 待核；API-only client；deployment_property；API客户端本机无需加载模型，云端显存不透明；多角色/多轮calls、tokens、费用和反馈存储另记。

最近邻条件：Fission-GRPO；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；权重、数据、依赖环境、缓存和评测产物分开核实；未知不按0计。

最近邻条件：Jev / typed decisions；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；权重、数据、依赖环境、缓存和评测产物分开核实；未知不按0计。

- BFCL · Base · Qwen3-8B Base：28.75%，accuracy，Multi-Turn / Overall；无新增权重更新；顶会主会 / D&B · ACL 2026；[ACL Table 1](https://aclanthology.org/2026.acl-long.1880.pdf)。
- BFCL · Dr.GRPO · Qwen3-8B Dr.GRPO：44.88%，accuracy，Multi-Turn / Overall；新增训练；顶会主会 / D&B · ACL 2026；[ACL Table 1](https://aclanthology.org/2026.acl-long.1880.pdf)。
- BFCL · Fission-GRPO · Qwen3-8B Fission-GRPO：46.75%，accuracy，Multi-Turn / Overall；新增训练；顶会主会 / D&B · ACL 2026；[ACL Table 1](https://aclanthology.org/2026.acl-long.1880.pdf)。

详细评分、基座、预算与限制见对应任务卡片。

## 3. 干预后的空间状态与证据更新

Benchmark：[SpaceCast-Bench](B28.md) / [VSI-Bench](B13.md)

相关方法：[SpaceCast staged SFT / predictive-spatial controls](METHOD_POOL.md#M38) / [ReRe](METHOD_POOL.md#M05)

状态：新热点 · 先验收评分；审阅 2026-10-09。

排序理由：提高到3：官方benchmark代码/scorer已公开且支持API，评测客户端本机无需GPU。保留新任务低分线索，但SFT 65.7%与其训练资源单列，近期型号同预算CoT基线尚需验收。

执行条件：先做百炼视觉 API 的冻结诊断与状态表原型。SpaceCast 65.7% 为新增训练的 staged SFT；ReRe 需要 VGGT 几何专家，非纯 API。公开数据、scorer、3D 工具与同帧预算先验收。

首轮门槛：先比同帧/调用预算 CoT、显式状态表、3D evidence 与 ReRe 类重读；在独立场景上区分已观察与干预后推断。只有状态失效更新有增量才继续；重述 observe-transform-infer 或低分仍无法纠错则淘汰。

最近邻风险：observe-transform-infer、3D evidence 和 staged SFT 已在原文；需要新失效现象及针对性的冻结推理修复，不能拿训练 65.7% 当 training-free 成绩。

一周路径：资源验收后用有限开发场景定位状态失效，再做预测状态更新和同预算消融；通过门槛才扩展独立场景与 VSI 迁移。

文献锚点（模型、训练与协议逐行保留，不跨表排名）：

模型要求："先用当前百炼型号验收；建议记录qwen3.8-max-0902作为近期固定型号参考，qwen3.8-flash滚动别名须记录返回model与观测日期。平台/地域可用性和计费先核实；不替换已有停止协议。"

规划资源标签（非实测，存储不参与排序）：{"mode": "api_tools", "vram_gib": 0, "storage_gib": null, "scope": "拟议API客户端；不包含本地训练专家/完整baseline", "measurement_kind": "planned_deployment_property", "notes": "无本机主模型加载；数据、工具环境、缓存、tokens/费用未测，需预算验收。"}

最近邻条件：SpaceCast staged SFT / predictive-spatial controls；开源 partial；Apache-2.0；显存 0 GiB；存储标签 待核；SpaceCast API evaluation client only; not staged SFT；deployment_property；官方API评测客户端不需本机GPU；首次运行会下载数据。SFT资源、checkpoint、数据磁盘大小未核实，不能以0代替完整方法资源。

最近邻条件：ReRe；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；权重、数据、依赖环境、缓存和评测产物分开核实；未知不按0计。

- SpaceCast-Bench · benchmark-author baseline · Qwen3.5-9B：34.6%，accuracy，evaluation / overall；无新增权重更新；arXiv（录用未核实） · arXiv 2026-10（录用未核实）；[Table1 overall](https://arxiv.org/html/2610.12402v1)。
- SpaceCast-Bench · benchmark-author baseline · Gemini3.5-Flash：58%，accuracy，evaluation / overall；无新增权重更新；arXiv（录用未核实） · arXiv 2026-10（录用未核实）；[Table1 overall](https://arxiv.org/html/2610.12402v1)。
- SpaceCast-Bench · Staged SFT · Qwen3-VL-4B Staged SFT：65.7%，accuracy，evaluation / overall；新增训练；arXiv（录用未核实） · arXiv 2026-10（录用未核实）；[Table4 / §4.4](https://arxiv.org/html/2610.12402v1)。

详细评分、基座、预算与限制见对应任务卡片。

## 4. 高分辨率跨实例证据绑定

Benchmark：[HR-Bench](B20.md) / [V* Bench](B15.md)

相关方法：[DeepScan](METHOD_POOL.md#M06) / [Workspace Sandbox](METHOD_POOL.md#M02)

状态：待开发验证；审阅 2026-10-09。

排序理由：保留CVPR主会和cross-instance机制价值，但下调到4：DeepScan官方两卡显存示例约10.94/16.90GiB，当前共享10GiB配置不能承诺完整基线；API原型仍待验证。

执行条件：拟议方法冻结百炼视觉模型，配 Python 裁剪与证据记录。DeepScan 对照需要已训练 BLIP/LangSAM 专家和本地 GPU；专家与同像素/调用预算必须另外核实。

首轮门槛：先验收 4K/8K 评分与图像分组。只有当前模型在 cross-instance 上仍有可重复错误，且同调用、token、像素预算下胜过原图投票、append-only、裁剪及可复现专家对照，才保留。收益仅来自更多图块或 V* 整体高分则停止。

最近邻风险：DeepScan 的 scan/refocus 和 Sandbox 的 workspace 已存在；需要证据绑定或失效更新带来独立增量。PGS 原图采样控制迁移到此任务，不冒称原文已测 HR-Bench。

一周路径：前两天做 scorer 与错误归因；第三至五天实现绑定/失效更新及同预算对照；通过门槛后做独立图像组与消融，V* 仅作迁移任务。

文献锚点（模型、训练与协议逐行保留，不跨表排名）：

模型要求："先用当前百炼型号验收；建议记录qwen3.8-max-0902作为近期固定型号参考，qwen3.8-flash滚动别名须记录返回model与观测日期。平台/地域可用性和计费先核实；不替换已有停止协议。"

规划资源标签（非实测，存储不参与排序）：{"mode": "api_tools", "vram_gib": 0, "storage_gib": null, "scope": "拟议API客户端；不包含本地训练专家/完整baseline", "measurement_kind": "planned_deployment_property", "notes": "拟议API原型本机显存0；完整DeepScan显存另见官方两卡示例，基础权重存储仅作标签，额外专家/环境/数据体积待测。"}

最近邻条件：DeepScan；开源 verified_code；Apache-2.0；显存 16.9014 GiB；存储标签 15.4454 GiB；README 2x4090 example; storage is only current Qwen2.5-VL-7B weight files；official_example；官方示例两卡分别11199/17307MiB，非实测峰值或最低要求；7B权重约15.45GiB，另需专家权重、3环境、数据及缓存，完整磁盘未知。共享10GiB卡限不能直接承诺复现。

最近邻条件：Workspace Sandbox；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；权重、数据、依赖环境、缓存和评测产物分开核实；未知不按0计。

- HR-Bench · DeepScan · Qwen2.5-VL-7B：59.7%，accuracy，evaluation / 4K cross-instance；无新增权重更新；顶会主会 / D&B · CVPR 2026；[CVPR Table 1](https://openaccess.thecvf.com/content/CVPR2026/papers/Li_DeepScan_A_Training-Free_Framework_for_Visually_Grounded_Reasoning_in_Large_CVPR_2026_paper.pdf)。
- HR-Bench · DeepScan · Qwen2.5-VL-7B：57.6%，accuracy，evaluation / 8K cross-instance；无新增权重更新；顶会主会 / D&B · CVPR 2026；[CVPR Table 1](https://openaccess.thecvf.com/content/CVPR2026/papers/Li_DeepScan_A_Training-Free_Framework_for_Visually_Grounded_Reasoning_in_Large_CVPR_2026_paper.pdf)。
- HR-Bench · Workspace sandbox · Qwen3.5-9B：78.13%，accuracy，val/eval / 4K rotated options；无新增权重更新；arXiv（录用未核实） · 录用未核实；[arXiv Table 1 / setup](https://arxiv.org/abs/2609.24362)。

详细评分、基座、预算与限制见对应任务卡片。

## 5. 行为不变量测试与验证器 RSI

Benchmark：[TestPrism](B30.md)

相关方法：[TestHelix / TestPrism](METHOD_POOL.md#M42)

状态：新热点 · 先验收资源；审阅 2026-10-09。

排序理由：仍有验证器/RSI价值，但移至5：官方实现当前未定位，附录单任务上限48calls、500K输入/100K输出tokens；training-free不代表低推理成本。

执行条件：代码模型 API+隔离代码执行环境；RSI 只更新配置/指导，不训练权重。先核仓库、容器、语言依赖与时间成本；隐藏 validity panel 仅用于最终 evaluator，不提供给生成器或 RSI。

首轮门槛：在同 K=3、执行次数和修复预算下对照原生 agent、固定指导、无 RSI 与 TestHelix/PCV；分别观察有效误拒和错误漏检，并跨仓库/语言验证。若收益来自看见隐藏 panel 或只是更多测试，停止。

最近邻风险：异质 test/repair pairs、PCV 与 RSI 已是 TestHelix 方法；需证明行为不变量覆盖能解决最近邻未解决的失效，不重新提交原组合。

一周路径：先做一组容器/评分验收与失效分类，再实现行为不变量覆盖选择；开发集配置优化与隐藏评测严格隔离，验证两类错误和跨语言迁移。

文献锚点（模型、训练与协议逐行保留，不跨表排名）：

模型要求："先用当前百炼型号验收；建议记录qwen3.8-max-0902作为近期固定型号参考，qwen3.8-flash滚动别名须记录返回model与观测日期。平台/地域可用性和计费先核实；不替换已有停止协议。"

规划资源标签（非实测，存储不参与排序）：{"mode": "api_tools", "vram_gib": 0, "storage_gib": null, "scope": "拟议API客户端；不包含本地训练专家/完整baseline", "measurement_kind": "planned_deployment_property", "notes": "无本机主模型加载；数据、工具环境、缓存、tokens/费用未测，需预算验收。"}

最近邻条件：TestHelix / TestPrism；开源 not_located；许可待核；显存 待核；存储标签 待核；complete baseline；unknown；官方附录任务上限48次调用、500K输入/100K输出tokens，受公开任务deadline约束；容器磁盘和实际成本未披露，原生agent不与这些上限等预算。

- TestPrism · TestHelix K3+PCV+RSI · GPT 5.6 sol：32.33%，Joint Success Function，evaluation / overall；无新增权重更新；arXiv（录用未核实） · arXiv 2026-10（录用未核实）；[Table3 K3+PCV+RSI; Appendix constraints](https://arxiv.org/html/2610.12289v1)。
- TestPrism · TestHelix K3+PCV+RSI · Kimi K3：33.33%，Joint Success Function，evaluation / overall；无新增权重更新；arXiv（录用未核实） · arXiv 2026-10（录用未核实）；[Table3 K3+PCV+RSI; Appendix constraints](https://arxiv.org/html/2610.12289v1)。

详细评分、基座、预算与限制见对应任务卡片。

# SciTaste 投稿规划

`/#/program` 是跨方向的 CCF A/B 会议与期刊目录。具体课题的交付计划继续在项目研究桌面维护；CVPR 是可选目标之一。

当前快照包含 189 个会议（A 58、B 131）及 148 个去重期刊（A 37、B 111），覆盖十个领域。期刊原目录有 150 条分领域记录；TOMM、DKE 等重复归类合并为同一卡片，保留全部来源页码。

会议来自 [CCF-DDL](https://github.com/ccfddl/ccf-deadlines) 的固定提交 `a00ffce713b5c21447b91779eea2271850b6bc83`，记录每个源文件 SHA-256。期刊来自同一仓库镜像的 CCF 第七版（2026）PDF，SHA-256 为 `271b630b576bf8a4f802e767f5694caded93680e22b3a19bef7902591c45c1d3`。CCF 官方 HTML/PDF 返回验证码，因此尚未独立验证官方文件与镜像逐字节一致；这一限制同时展示在页面中。

`data/journal_catalog_2026.json` 保留原页、行、目录链接及三处经 PDF 图像核对的文字提取修正。期刊目录链接常为 DBLP，不当作投稿门户；没有已核实征稿日期的期刊显示待核实。会议等级遵循对应 CCF-DDL 快照，期刊等级遵循独立的 2026 PDF 目录版本。

```bash
# 手动更新会议快照，无模型调用
python scripts/sync_venues.py --refresh

# 使用已下载的固定提交重建
python scripts/sync_venues.py --source cache/venue_sources/ccfddl \
  --commit a00ffce713b5c21447b91779eea2271850b6bc83
```

更新先构造完整快照，再原子替换 `data/submission_venues.json`；下载失败保留原快照。网页读取本地快照及 ETag，不访问外部来源，也没有自动网络更新定时器。会议更新不悄悄改写期刊目录版本。

时间保留上游原文、原时区和 UTC，界面显示北京时间。AoE 为 UTC−12；PT 使用洛杉矶时区并处理夏令时；未知时区、TBD 和解析失败保留空值，不推算下一届。各轮论文、摘要、回复、决定日期分别展示；社区记录在正式投稿前仍须核会议官网。

支持类型、A/B、领域、状态、会议届次、关键词与分页。星标保存于当前浏览器的 `scitaste.venue_shortlist`，不是服务端项目目标绑定。

来源许可见 [CCF-DDL LICENSE](licenses/ccf-deadlines-LICENSE)。这里只发布目录元数据与来源标识，不重分发 CCF PDF 或论文。

#!/usr/bin/env python3
"""Curated research registry: validate, render, discover, and apply reviewed patches.

Public discovery never promotes an unverified score or conference acceptance.
No model inference, credentials, dataset download, or training is performed.
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import math
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research_registry.json"
LANES = {"accepted_main": "顶会主会 / D&B", "accepted_findings": "Findings",
         "accepted_workshop": "Workshop", "accepted_other": "其他已录用会议", "accepted_journal": "已发表期刊", "arxiv": "arXiv（录用未核实）",
         "official_report": "官方模型报告 / 动态榜单", "own_pilot": "本地开发试验"}
STATUS = {"active": "成绩已收录", "watch": "观察 / 证据待补"}


def read(path):
    return json.loads(path.read_text())


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def coverage_for(benchmark_id, d):
    papers = {p["id"]: p for p in d["papers"]}
    rows = [r for r in d["results"] if r["benchmark_id"] == benchmark_id]
    counts = Counter(papers[r["paper_id"]]["lane"] for r in rows)
    accepted = sorted({r["paper_id"] for r in rows if papers[r["paper_id"]]["lane"].startswith("accepted_")})
    return dict({k: counts[k] for k in LANES}, accepted_anchor_missing=not bool(accepted), this_is_curated_lower_bound=True), accepted


def validate(d):
    errors = []
    idx = {}
    for table in ("benchmarks", "papers", "results", "methods", "ideas", "research_candidates", "model_profiles"):
        rows = d.get(table, [])
        ids = [x["id"] for x in rows]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate ID in {table}")
        idx[table] = {x["id"]: x for x in rows}
    for p in d["papers"]:
        if p["lane"] not in LANES:
            errors.append(f"unknown lane: {p['id']}")
        if p["lane"].startswith("accepted_") and not p.get("acceptance_url"):
            errors.append(f"acceptance evidence missing: {p['id']}")
    for profile in d.get("model_profiles", []):
        if profile.get("recency_status") not in {"historical_backbone", "historical_snapshot", "version_unknown"} or not profile.get("reported_label"):
            errors.append(f"model version provenance invalid: {profile['id']}")
        value = profile.get("weight_storage_gib")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            errors.append(f"model storage label invalid: {profile['id']}")
    model_catalog = d.get("runtime_model_catalog", [])
    if len({m["id"] for m in model_catalog}) != len(model_catalog):
        errors.append("duplicate current model ID")
    for model in model_catalog:
        if model.get("kind") not in {"dated_model_id", "rolling_alias", "named_checkpoint"} or not model.get("source_url") or model.get("checked_on", "") > d["as_of"]:
            errors.append(f"current model catalog provenance invalid: {model['id']}")
    required = ("id", "benchmark_id", "paper_id", "method", "base_model", "model",
                "target_weight_update", "version", "split", "subset", "n", "metric", "value",
                "unit", "direction", "scorer", "budget", "source_url", "locator", "verified_on",
                "evidence", "comparison_group", "protocol_notes", "training_recipe",
                "external_components", "trained_external_components")
    for r in d["results"]:
        for key in required:
            if key not in r:
                errors.append(f"missing {key}: {r['id']}")
        if r.get("benchmark_id") not in idx["benchmarks"] or r.get("paper_id") not in idx["papers"]:
            errors.append(f"broken reference: {r['id']}")
        value = r.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"score must be numeric, no placeholders: {r['id']}")
        elif not math.isfinite(value):
            errors.append(f"score must be finite: {r['id']}")
        elif r.get("unit") == "%" and not 0 <= value <= 100:
            errors.append(f"invalid percentage: {r['id']}")
        if r.get("target_weight_update") not in {"yes", "no", "unknown", "not_applicable"}:
            errors.append(f"training flag invalid: {r['id']}")
        if r.get("direction") not in {"higher", "lower"}:
            errors.append(f"metric direction invalid: {r['id']}")
        for reference in ("delta_from", "tool_matched_control"):
            if not r.get(reference):
                continue
            base = idx["results"].get(r[reference])
            if not base or base["comparison_group"] != r["comparison_group"]:
                errors.append(f"unmatched {reference}: {r['id']}")
            elif any(base[k] != r[k] for k in ("benchmark_id", "version", "split", "subset", "metric", "base_model", "scorer", "unit", "direction", "n")):
                errors.append(f"incompatible {reference}: {r['id']}")
            elif reference == "tool_matched_control" and base["external_components"] != r["external_components"]:
                errors.append(f"different experts for tool control: {r['id']}")
        if r.get("verified_on", "") > d["as_of"]:
            errors.append(f"verification after registry date: {r['id']}")
        if "model_profiles" in d and r.get("model_profile_id") not in idx["model_profiles"]:
            errors.append(f"missing model provenance: {r['id']}")
    for m in d["methods"]:
        if m["paper_id"] not in idx["papers"] or any(x not in idx["benchmarks"] for x in m["benchmark_ids"]):
            errors.append(f"broken method reference: {m['id']}")
        if m.get("priority") not in {0, 1, 2}:
            errors.append(f"method priority invalid: {m['id']}")
        if "training_free_class" in m and m["training_free_class"] not in {"training_free", "requires_training", "mixed", "unknown"}:
            errors.append(f"invalid training-free class: {m['id']}")
        for key in ("storage_gib", "vram_gib"):
            value = m.get("resources", {}).get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                errors.append(f"invalid method {key}: {m['id']}")
        if m.get("reproducibility", {}).get("status") == "verified_code" and not m["reproducibility"].get("url"):
            errors.append(f"verified code requires source URL: {m['id']}")
    candidates = d.get("research_candidates", [])
    if "research_candidates" in d:
        if len(candidates) != 5 or sorted(c.get("rank", 0) for c in candidates) != list(range(1, 6)):
            errors.append("research candidates require exactly five unique ranks 1–5")
        ranking = d.get("research_candidate_ranking", {})
        if not ranking.get("criteria") or not ranking.get("limitations"):
            errors.append("research candidate ranking rationale missing")
        for c in candidates:
            for key in ("title", "ranking_reason", "first_gate", "execution_conditions", "novelty_risk", "one_week_plan", "status", "reviewed_on"):
                if not isinstance(c.get(key), str) or not c[key].strip():
                    errors.append(f"candidate {key} missing: {c['id']}")
            for field, table in (("benchmark_ids", "benchmarks"), ("method_ids", "methods"), ("idea_ids", "ideas"), ("result_ids", "results")):
                refs = c.get(field, [])
                if not isinstance(refs, list) or not refs or any(r not in idx[table] for r in refs):
                    errors.append(f"broken candidate {field}: {c['id']}")
            if any(r not in idx["methods"] for r in c.get("control_method_ids", [])):
                errors.append(f"broken candidate controls: {c['id']}")
            if any(idx["results"][r]["benchmark_id"] not in c.get("benchmark_ids", []) for r in c.get("result_ids", []) if r in idx["results"]):
                errors.append(f"candidate evidence belongs to another benchmark: {c['id']}")
            if c.get("reviewed_on", "") > d["as_of"]:
                errors.append(f"candidate review after registry date: {c['id']}")
    if not errors:
        for b in d["benchmarks"]:
            coverage, accepted = coverage_for(b["id"], d)
            if b.get("coverage") != coverage or b.get("verified_accepted_paper_ids") != accepted:
                errors.append(f"stale derived coverage: {b['id']}; apply a reviewed patch to synchronize")
    if errors:
        raise ValueError("\n".join(errors))
    return idx


def cell(s):
    return str(s if s is not None else "未披露").replace("|", "\\|").replace("\n", " ")


def link(title, url):
    return f"[{cell(title)}]({url})"


def benchmark_counts(b, d, idx):
    rows = [r for r in d["results"] if r["benchmark_id"] == b["id"]]
    counts = Counter(idx["papers"][r["paper_id"]]["lane"] for r in rows)
    accepted = sum(v for k, v in counts.items() if k.startswith("accepted_"))
    return rows, counts, accepted


def score_row(r, idx):
    p = idx["papers"][r["paper_id"]]
    train = {"yes": "有", "no": "无新增", "unknown": "待核实", "not_applicable": "不适用"}[r["target_weight_update"]]
    expert = "; ".join(r.get("external_components", [])) or "无 / 未披露（见备注）"
    delta = ""
    if r.get("delta_from"):
        base = idx["results"][r["delta_from"]]
        delta = f"（较文中基线 {r['value'] - base['value']:+.2f}，预算须另核对）"
    if r.get("tool_matched_control"):
        control = idx["results"][r["tool_matched_control"]]
        delta += f"；同专家 Raw Tool {control['value']:g}{control['unit']}，差值 {r['value']-control['value']:+.2f}（总预算待核）"
    uncertainty = r.get("uncertainty") or {}
    pm = f"±{uncertainty['reported_plus_minus']:g}" if uncertainty.get("reported_plus_minus") is not None else ""
    cells = [f"{p['venue']} · {r['method']}", f"{r['value']:g}{pm}{r['unit']} {delta}",
             f"{r['model']}；基座 {r['base_model']}", f"{train}；{r.get('training_recipe', '未披露')}",
             f"{r['version']} / {r['split']} / {r['subset']}；N={r.get('n') or '未披露'}；{r['metric']}",
             f"{r['budget']}；外部：{expert}",
             f"{r['scorer']}；{r['protocol_notes']}",
             f"{link(r['locator'], r['source_url'])}；{r['evidence']}；核实 {r['verified_on']}"]
    return "| " + " | ".join(cell(x) for x in cells) + " |"


def render(d):
    idx = validate(d)
    out = ROOT / "docs/registry"
    out.mkdir(parents=True, exist_ok=True)
    counts = Counter(idx["papers"][r["paper_id"]]["lane"] for r in d["results"])
    anchors = sum(bool(benchmark_counts(b, d, idx)[2]) for b in d["benchmarks"])
    head = ["# 动态 Benchmark 榜单", "", f"核实截止：{d['as_of']}。{len(d['benchmarks'])} 个 benchmark 条目、{len(d['results'])} 条成绩、{len(d['methods'])} 个公开方法候选、{len(d['ideas'])} 个研究假设。", "",
            f"{anchors} 个条目已有录用成绩锚点（含 Findings / 其他会议），{len(d['benchmarks']) - anchors} 个列入待补观察区。每个卡片先列顶会主会，再列 Findings、其他发表身份与 arXiv；同一工作不同版本的数字分别保留。", "",
            "这是带证据的选题榜单，不是跨协议的全球 SOTA 排名。默认先读近期录用工作，再读 arXiv；Findings、Workshop、模型自报与本地小样本独立展示。未知条件不视为一致，分数不自动按大小合并。", "",
            "影响分层：A＝成熟核心任务，已有多项录用/强方法使用证据；B＝已有会议背书的专项任务或版本；C＝新兴预印本/资源待核实。分层是本项目的定性判断，采用数量是当前库内下界，不能替代全社区引用量。", "",
            "热度以近期新增工作和方法变化判断；提升空间以当前目标模型、同预算控制和错误机制判断。高影响、低论文分数和高热度都不自动意味着好提升。", "",
            "[近期热点摘要](LATEST_HOTSPOTS.md) · [完整发现收件箱](DISCOVERY_INBOX.md) · [方法候选池](METHOD_POOL.md) · [更新工作流](../RESEARCH_REGISTRY.md) · [交互筛选](../../dashboard/research.html)", ""]
    gaps = []
    board_groups = {True: [], False: []}
    for b in sorted(d["benchmarks"], key=lambda b: (b["subfield"], b["influence_tier"], b["id"])):
        rows, c, accepted = benchmark_counts(b, d, idx)
        accepted_papers = {r["paper_id"] for r in rows if idx["papers"][r["paper_id"]]["lane"].startswith("accepted_")}
        board_groups[bool(accepted)].append(f"| {cell(b['subfield'])} | [{b['name']}]({b['id']}.md) | {b['influence_tier']} | {len(accepted_papers)} 篇；主会 {c['accepted_main']} / Findings {c['accepted_findings']} / 其他 {accepted-c['accepted_main']-c['accepted_findings']} | {c['arxiv']} / {c['official_report']} | {cell(b['headroom'])}；{cell(b['gap'])} |")
        page = [f"# {b['name']}", "", f"子领域：{b['subfield']}。影响层：{b['influence_tier']}。状态：{STATUS[b['status']]}。核实：{b['verified_on']}。", "",
                f"影响依据（定性）：{b['influence_reason']}", "", f"内容与评分：{b['description']}。{b['evaluation']}", "",
                f"库内采用证据：{len(accepted_papers)} 篇录用论文、{accepted} 条录用成绩（非全社区统计）。近期热度：{b.get('heat', '尚未量化')}。", "",
                f"入口：{link('官方资源', b['official_url'])}。{link('出处/版本依据', b['source_url'])}", "",
                f"当前提升判断：{b['headroom']}", "", f"缺口与更新优先级：{b['gap']}", ""]
        for lane, title in LANES.items():
            group = [r for r in rows if idx["papers"][r["paper_id"]]["lane"] == lane]
            if lane in {"accepted_main", "accepted_findings", "arxiv"} or group:
                page += [f"## {title}", ""]
                if not group:
                    page += ["尚未收录核实后的成绩；这不等于没有论文使用该任务。", ""]
                else:
                    page += ["| 论文 / 方法 | 成绩 | 实际模型 / 基座 | 方法新增训练 | 版本 / 子任务 / 样本 / 指标 | 推理预算与外部模型 | 评分及可比限制 | 原始证据 |", "|---|---|---|---|---|---|---|---|"]
                    page += [score_row(r, idx) for r in group]
                    page += [""]
        mids = [m for m in d["methods"] if b["id"] in m["benchmark_ids"]]
        page += ["## 相关方法候选", "", ", ".join(f"[{m['name']}](METHOD_POOL.md#{m['id']})" for m in mids) or "待补", ""]
        (out / (b["id"] + ".md")).write_text("\n".join(page))
        if not accepted or b["gap"]:
            gaps.append({"benchmark_id": b["id"], "accepted_results": accepted, "accepted_anchor_missing": not bool(accepted), "gap": b["gap"]})
    for present, title in ((True, "已有录用成绩锚点"), (False, "待补录用证据 / 新兴任务观察区")):
        head += [f"## {title}", "", "| 子领域 | Benchmark | 影响 | 录用论文 / 成绩条数 | arXiv / 官方成绩 | 当前判断与缺口 |", "|---|---|---|---|---|---|"]
        head += board_groups[present] + [""]
    head += ["", "成绩条数（不是论文数）：" + "；".join(f"{LANES[k]} {v}" for k, v in counts.items()), "",
             "[方法候选池](METHOD_POOL.md) · [更新工作流](../RESEARCH_REGISTRY.md) · [交互筛选](../../dashboard/research.html) · [结构化数据](../../data/research_registry.json)", ""]
    (out / "BENCHMARK_BOARD.md").write_text("\n".join(head))
    pool = ["# 方法候选池", "", f"核实截止：{d['as_of']}。公开方法与我们的 idea 分开维护；候选不等于复现成功，也不代表 novelty 已成立。", "",
            "默认 training-free 优先；存储仅作标签，不影响排序。资源口径区分 API 客户端、官方示例与完整基线，未知值不当作零。", "",
            "| 方法 | 领域 / 阶段 | 发表身份 | 训练 / 接口 | 开源与资源标签 | 成绩证据 | 一周可执行性 / 最近邻风险 | 下一步与停止门槛 |", "|---|---|---|---|---|---|---|---|"]
    tf_order = {"training_free": 0, "mixed": 1, "unknown": 2, "requires_training": 3}
    for m in sorted(d["methods"], key=lambda m: (tf_order.get(m.get("training_free_class"), 2), m["priority"], m["id"])):
        p = idx["papers"][m["paper_id"]]
        nr = sum(r["paper_id"] == p["id"] for r in d["results"])
        pool.append("| " + " | ".join(cell(x) for x in [f"<a id='{m['id']}'></a>{link(m['name'],p['url'])}",
          f"{m['subfield']}；P{m['priority']} / {m['stage']}", f"{LANES[p['lane']]} · {p['venue']}",
          f"{m.get('training_free_class', 'unknown')}；{m['training']}；{m['api_compatibility']}", resource_summary(m), f"{nr} 条；{', '.join(m['benchmark_ids']) or '待补'}；{m['evidence_depth']}",
          f"{m['one_week']}；{m['novelty_risk']}", m["next_action"]]) + " |")
    pool += ["", "## 本项目 Idea（未验证假设）", "", "| ID | 假设 | 相关公开方法 / benchmark | 验证与淘汰条件 |", "|---|---|---|---|"]
    for i in d["ideas"]:
        pool.append("| " + " | ".join(cell(x) for x in [i["id"], i["hypothesis"], i["neighbors"], i["gate"]]) + " |")
    (out / "METHOD_POOL.md").write_text("\n".join(pool) + "\n")
    render_candidates(d, idx, out)
    render_resources(d, out)
    export = ROOT / "data/exports"
    export.mkdir(parents=True, exist_ok=True)
    flat = []
    for r in d["results"]:
        p = idx["papers"][r["paper_id"]]
        row = dict(r, publication_lane=p["lane"], venue=p["venue"], paper_title=p["title"])
        flat.append({k: json.dumps(v, ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    fields = sorted({k for r in flat for k in r})
    with (export / "scores.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(flat)
    dump(export / "coverage_gaps.json", gaps)
    dashboard(d, idx)
    discovery_views(d, idx)
    return {"benchmarks": len(d["benchmarks"]), "papers": len(d["papers"]), "results": len(d["results"]), "methods": len(d["methods"]), "lanes": counts}


def dashboard(d, idx):
    rows = []
    lane_order = {k: i for i, k in enumerate(LANES)}
    for r in sorted(d["results"], key=lambda r: (lane_order[idx["papers"][r["paper_id"]]["lane"]], r["benchmark_id"])):
        b, p = idx["benchmarks"][r["benchmark_id"]], idx["papers"][r["paper_id"]]
        control = idx["results"].get(r.get("tool_matched_control"))
        control_note = f"Raw Tool {control['value']:g}{control['unit']}；差值 {r['value']-control['value']:+.2f}（总预算待核）" if control else ""
        uncertainty = r.get("uncertainty") or {}
        uncertainty_note = f"±{uncertainty['reported_plus_minus']:g}；{uncertainty.get('type', '误差类型待核')}" if uncertainty.get("reported_plus_minus") is not None else ""
        rows.append(dict(r, benchmark=b["name"], subfield=b["subfield"], influence=b["influence_tier"], lane=LANES[p["lane"]], venue=p["venue"], acceptance_url=p.get("acceptance_url"), control_note=control_note, uncertainty_note=uncertainty_note))
    methods = []
    for m in sorted(d["methods"], key=lambda m: (m["priority"], m["id"])):
        p = idx["papers"][m["paper_id"]]
        methods.append(dict(m, lane=LANES[p["lane"]], venue=p["venue"], url=p["url"], repository_url=p.get("repository_url"),
                            benchmarks=" / ".join(idx["benchmarks"][x]["name"] for x in m["benchmark_ids"]) or "待补对应任务",
                            score_count=sum(r["paper_id"] == m["paper_id"] for r in rows)))
    payload = json.dumps({"scores": rows, "methods": methods}, ensure_ascii=False).replace("<", "\\u003c")
    template = """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastResearch 研究榜单</title><style>body{font:15px system-ui;margin:24px;color:#173046;background:#f6f8fc}h1{font-size:25px}select,input{padding:9px;margin:5px;border:1px solid #bbc9d4;border-radius:5px;max-width:95%}table{border-collapse:collapse;width:100%;min-width:1050px;background:white}th,td{padding:12px;border-bottom:1px solid #e0e6ed;text-align:left;vertical-align:top;min-width:140px;max-width:350px}th{position:sticky;top:0;background:#dce8f3}small{color:#52697b}a{color:#1357a0}.scroll{overflow:auto;max-height:72vh}button{padding:9px 18px;margin:4px;border:1px solid #bbc9d4;border-radius:6px;cursor:pointer;background:white}button.active{background:#173f68;color:white}.note{padding:12px;border-left:4px solid #6b90b2;background:#eaf0f7}td .score{font-size:18px;font-weight:600}select{max-width:280px}#search{min-width:240px}</style>
<h1>FastResearch：Benchmark 与方法证据</h1><p>核实截止 __DATE__ · __COUNTS__。</p>
<p class="note">先读近期录用工作，再核对模型、任务版本与预算。影响 A/B/C 是有依据的定性判断；未知条件不视为一致。发现收件箱与已核实成绩分开维护。</p>
<p><a href="../docs/registry/BENCHMARK_BOARD.md">Benchmark 卡片</a> · <a href="../docs/registry/LATEST_HOTSPOTS.md">近期热点</a> · <a href="../docs/registry/METHOD_POOL.md">方法全文</a> · <a href="../docs/RESEARCH_REGISTRY.md">更新工作流</a> · <a href="../data/exports/scores.csv">CSV</a></p>
<div><button id="scoresTab" class="active" onclick="switchView('scores')">Benchmark 成绩</button><button id="methodsTab" onclick="switchView('methods')">方法候选池</button><button id="reset" onclick="resetFilters()">重置筛选</button></div>
<div id="filters"></div><input id="search" placeholder="搜索方法、模型、任务、协议" size="38"><p id="count"></p>
<div class="scroll"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>const data=__DATA__;let view='scores';let fields=[];
const config={scores:[['subfield','子领域'],['influence','影响'],['benchmark','Benchmark'],['lane','发表状态'],['target_weight_update','新增权重训练'],['metric','指标'],['subset','子任务']],methods:[['subfield','子领域'],['lane','发表状态'],['priority','一周验证优先级'],['stage','候选阶段']]};
const labels={target_weight_update:{no:'无新增权重更新',yes:'有新增权重更新',unknown:'待核实',not_applicable:'不适用'},priority:{0:'P0：优先核查',1:'P1：条件候选',2:'P2：资源或证据待补'}};
const e=s=>String(s??'未披露').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function switchView(v){view=v;fields=config[v];document.querySelector('#filters').innerHTML='';document.querySelector('#search').value='';for(const [key,label] of fields){const s=document.createElement('select');s.id=key;s.setAttribute('aria-label',label);s.innerHTML='<option value="">'+label+'：全部</option>'+[...new Set(data[v].map(r=>r[key]))].sort().map(x=>'<option value="'+e(x)+'">'+e(labels[key]?.[x]??x)+'</option>').join('');s.onchange=draw;document.querySelector('#filters').append(s)}document.querySelector('#scoresTab').classList.toggle('active',v==='scores');document.querySelector('#methodsTab').classList.toggle('active',v==='methods');draw()}
function resetFilters(){for(const [k] of fields)document.getElementById(k).value='';document.querySelector('#search').value='';draw()}
function draw(){const q=document.querySelector('#search').value.toLowerCase();const a=data[view].filter(r=>fields.every(([k])=>!document.getElementById(k).value||String(r[k])===document.getElementById(k).value)&&JSON.stringify(r).toLowerCase().includes(q));document.querySelector('#count').textContent=a.length+' / '+data[view].length+' 条符合；'+(view==='scores'?'录用成绩先展示；未披露预算不视为匹配':'P0/P1/P2 表示验证顺序，不代表 novelty 已成立');const scoreHeaders=['子领域 / 影响','Benchmark / 协议','发表 / 方法','成绩 / 指标','模型 / 新增训练','预算 / 外部组件 / 原文'];const methodHeaders=['方法 / 发表','领域 / 优先级','训练 / 接口','Benchmarks / 证据','一周可执行性 / 最近邻','下一步与门槛'];document.querySelector('#head').innerHTML='<tr>'+(view==='scores'?scoreHeaders:methodHeaders).map(x=>'<th>'+e(x)+'</th>').join('')+'</tr>';document.querySelector('#body').innerHTML=a.map(r=>view==='scores'?`<tr><td>${e(r.subfield)} / ${e(r.influence)}</td><td><a href="../docs/registry/${e(r.benchmark_id)}.md">${e(r.benchmark)}</a><br><small>${e(r.version)} / ${e(r.split)} / ${e(r.subset)} / N=${e(r.n)}<br>${e(r.scorer)}</small></td><td>${e(r.lane)} · ${e(r.venue)}<br>${e(r.method)}${r.acceptance_url?'<br><a href="'+e(r.acceptance_url)+'" target="_blank" rel="noopener">录用证据</a>':''}</td><td><span class="score">${e(r.value)}${e(r.unit)}</span><br><small>${e(r.metric)} ${r.direction==='higher'?'↑':'↓'}<br>${e(r.uncertainty_note)}<br>${e(r.control_note)}</small></td><td>${e(r.model)}<br><small>基座 ${e(r.base_model)}<br>${e(labels.target_weight_update[r.target_weight_update])}；${e(r.training_recipe)}</small></td><td>${e(r.budget)}<br><small>外部：${e(r.external_components.join(' / ')||'无 / 未披露（见备注）')}<br>${e(r.protocol_notes)}</small><br><a href="${e(r.source_url)}" target="_blank" rel="noopener">${e(r.locator)}</a> · ${e(r.verified_on)}</td></tr>`:`<tr><td><a href="${e(r.url)}" target="_blank" rel="noopener">${e(r.id)} · ${e(r.name)}</a><br><small>${e(r.lane)} · ${e(r.venue)}</small></td><td>${e(r.subfield)} · P${e(r.priority)}<br><small>${e(r.stage)}</small></td><td>${e(r.training)}<br><small>${e(r.api_compatibility)}</small></td><td>${e(r.benchmarks)}<br><small>${e(r.score_count)} 条成绩；${e(r.evidence_depth)}</small></td><td>${e(r.one_week)}<br><small>${e(r.novelty_risk)}</small></td><td>${e(r.next_action)}${r.repository_url?'<br><a href="'+e(r.repository_url)+'" target="_blank" rel="noopener">仓库</a>':''}<br><small>核实 ${e(r.verified_on)}</small></td></tr>`).join('')}
document.querySelector('#search').oninput=draw;switchView('scores');</script></html>"""
    template = template.replace("__DATE__", html.escape(d["as_of"])).replace("__COUNTS__", f"{len(d['benchmarks'])} benchmark / {len(rows)} 成绩 / {len(d['methods'])} 方法").replace("__DATA__", payload)
    p = ROOT / "dashboard/research.html"; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(template)


def discovery_views(d, idx):
    """Render curated recent methods and a separate, unpromoted discovery queue."""
    out = ROOT / "docs/registry"
    cutoff = str(dt.date.fromisoformat(d["as_of"]) - dt.timedelta(days=14))
    recent = [m for m in d["methods"] if cutoff <= (idx["papers"][m["paper_id"]].get("published_on") or "") <= d["as_of"]]
    lines = ["# 近期热点摘要", "", f"核实截止：{d['as_of']}。以下是近 14 日发布/修订且已人工筛读的候选；已读摘要、已读结果表与已复现是不同阶段。优先级反映一周验证条件，不能替代创新性判断。", "",
             "| 方法 / 身份 | 任务与训练 | 已核实证据 | 一周切入点 / 最近邻风险 | 下一步 |", "|---|---|---|---|---|"]
    for m in sorted(recent, key=lambda x: (x["priority"], x["id"])):
        p = idx["papers"][m["paper_id"]]
        bs = " / ".join(link(idx["benchmarks"][b]["name"], b + ".md") for b in m["benchmark_ids"])
        nr = sum(r["paper_id"] == p["id"] for r in d["results"])
        values = [f"P{m['priority']} · {link(m['name'], p['url'])}；{LANES[p['lane']]}；{p['published_on']}",
                  f"{bs or '对应任务待补'}；{m['training']}", f"{nr} 条收录成绩；{m['evidence_depth']}",
                  f"{m['one_week']}；{m['novelty_risk']}", m["next_action"]]
        lines.append("| " + " | ".join(cell(x) for x in values) + " |")
    lines += ["", "[完整候选池](METHOD_POOL.md) · [全部未核实发现](DISCOVERY_INBOX.md) · [更新工作流](../RESEARCH_REGISTRY.md)", ""]
    inbox_path = ROOT / "data/discovery_inbox.json"
    if inbox_path.exists():
        inbox = read(inbox_path)
        states = Counter(x["state"] for x in inbox["items"])
        counts = Counter(topic for x in inbox["items"] for topic in x["topics"])
        lines += ["## 新发现待读队列", "", f"最近实际抓取 {inbox['as_of']}；累计 {len(inbox['items'])} 个去重发现，{states['needs_primary_read']} 个待原文核实。标签可重叠。HF 推荐样本不覆盖完整 arXiv，推荐票数不能充当学术影响证据。", "",
                  "标签覆盖：" + "；".join(f"{k} {v}" for k, v in counts.items()), "",
                  "以下按 HF 元数据日期、推荐票数排列前 20 个待读项，日期可能是修订日期；不是质量排名。", "",
                  "| 论文 | 发现标签 | HF 元数据日期 | 推荐票数 |", "|---|---|---|---|"]
        pending = [x for x in inbox["items"] if x["state"] == "needs_primary_read"]
        ordered = sorted(pending, key=lambda x: (x.get("paper_published_at") or "", x.get("hf_upvotes") or 0), reverse=True)
        for x in ordered[:20]:
            lines.append(f"| {link(x['title'], x['url'])} | {cell(', '.join(x['topics']))} | {cell(x.get('paper_published_at'))} | {cell(x.get('hf_upvotes'))} |")
        full = ["# 热点发现收件箱", "", f"最近实际抓取：{inbox['as_of']}。{len(inbox['items'])} 个去重发现；只记录发现，不自动录入成绩或录用身份。HF 日期可能是修订，首见是本项目发现日期；两者都不冒充初次投稿日期。", "",
                "状态：needs_primary_read＝尚未核实原文；curated＝已进入候选池，具体阅读深度见候选池。HF Daily Papers 是推荐样本，不能代表完整 arXiv；需结合会议定向检索。", "",
                "| 论文 | 标签 | 首见 / HF 元数据日期 | 状态 / 核实条目 |", "|---|---|---|---|"]
        lookup = {p.get("arxiv_id"): p for p in d["papers"] if p.get("arxiv_id")}
        for x in sorted(inbox["items"], key=lambda x: (x.get("paper_published_at") or "", x.get("hf_upvotes") or 0), reverse=True):
            p = lookup.get(x["arxiv_id"])
            extra = f"；{LANES[p['lane']]}；{sum(r['paper_id'] == p['id'] for r in d['results'])} 条成绩" if p else "；成绩/录用未核实"
            full.append(f"| {link(x['title'], x['url'])} | {cell(', '.join(x['topics']))} | {x['first_seen']} / {cell(x.get('paper_published_at'))} | {cell(x['state'] + extra)} |")
        (out / "DISCOVERY_INBOX.md").write_text("\n".join(full) + "\n")
    (out / "LATEST_HOTSPOTS.md").write_text("\n".join(lines) + "\n")


def refresh(args, d):
    """Daily Papers and watched primary URLs, bounded public read-only requests."""
    as_of = dt.date.fromisoformat(args.as_of)
    feeds = read(ROOT / "configs/research_watch.json")
    inbox_path = ROOT / "data/discovery_inbox.json"
    inbox = read(inbox_path) if inbox_path.exists() else {"items": [], "runs": []}
    known = {x["arxiv_id"]: x for x in inbox["items"]}
    tracked = {p.get("arxiv_id") for p in d["papers"] if p.get("arxiv_id")}
    run = {"as_of": args.as_of, "days": args.days, "requests": [], "new_items": 0, "promotion": "none; manual primary-source verification required"}
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "FastResearch-LiteratureRegistry/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read(8_000_000)
    for days in range(args.days):
        date = str(as_of - dt.timedelta(days=days))
        url = f"https://huggingface.co/api/daily_papers?date={date}&limit=100&sort=publishedAt"
        try:
            blob = get(url); entries = json.loads(blob)
            if not isinstance(entries, list):
                raise ValueError("unexpected feed shape")
            for entry in entries:
                p = entry.get("paper", entry); pid = p.get("id")
                if not pid:
                    continue
                title, abstract = p.get("title", ""), p.get("summary", "")
                matches = [topic["name"] for topic in feeds["topics"] if any(word.lower() in (title + " " + abstract).lower() for word in topic["keywords"])]
                if not matches:
                    continue
                item = known.get(pid)
                if item is None:
                    item = {"arxiv_id": pid, "title": title, "url": f"https://arxiv.org/abs/{pid}", "first_seen": args.as_of,
                            "paper_published_at": p.get("publishedAt"), "topics": matches,
                            "state": "tracked" if pid in tracked else "needs_primary_read", "score_status": "not_extracted", "acceptance_status": "not_verified"}
                    inbox["items"].append(item); known[pid] = item; run["new_items"] += 1
                item["last_seen"] = args.as_of
                item["feed_dates"] = sorted(set(item.get("feed_dates", []) + [date]))
                item["hf_upvotes"] = p.get("upvotes")
            run["requests"].append({"url": url, "status": "ok", "entries": len(entries), "sha256": hashlib.sha256(blob).hexdigest()})
        except Exception as e:
            run["requests"].append({"url": url, "status": "error", "message": str(e)[:200]})
        time.sleep(.3)
    snap_path = ROOT / "data/source_snapshots.json"
    snapshots = read(snap_path) if snap_path.exists() else {}
    for source in feeds["sources"]:
        if args.feeds_only:
            break
        try:
            blob = get(source["url"]); sha = hashlib.sha256(blob).hexdigest()
            old = snapshots.get(source["id"], {}).get("sha256")
            cache = ROOT / "cache/research_sources" / (source["id"] + ".bin"); cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(blob)
            needs_review = snapshots.get(source["id"], {}).get("needs_review", False) or (old is not None and old != sha)
            snapshots[source["id"]] = {"url": source["url"], "checked_on": args.as_of, "sha256": sha, "changed": old is not None and old != sha, "bytes": len(blob), "needs_review": needs_review}
            run["requests"].append(dict(id=source["id"], **snapshots[source["id"]], status="ok"))
        except Exception as e:
            run["requests"].append({"id": source["id"], "url": source["url"], "status": "error", "message": str(e)[:200]})
    inbox["runs"].append(run); inbox["as_of"] = args.as_of
    dump(inbox_path, inbox); dump(snap_path, snapshots)
    dump(ROOT / "reports/research_refresh" / f"{args.as_of}.json", run)
    discovery_views(d, validate(d))
    return {"new_items": run["new_items"], "inbox_items": len(inbox["items"]), "requests_ok": sum(r["status"] == "ok" for r in run["requests"]), "requests_failed": sum(r["status"] != "ok" for r in run["requests"])}


def resource_summary(m):
    r, code = m.get("resources", {}), m.get("reproducibility", {})
    def size(key):
        return "待核" if r.get(key) is None else f"{r[key]:g} GiB"
    return f"开源 {code.get('status', 'unknown')}；{code.get('license') or '许可待核'}；显存 {size('vram_gib')}；存储标签 {size('storage_gib')}；{r.get('scope', '范围待核')}；{r.get('measurement_kind', 'unknown')}；{r.get('notes', '')}"


def render_resources(d, out):
    lines = ["# 模型、开源与资源条件", "", f"核实截止：{d['as_of']}。模型命名保留文献原样；当前官方型号文档不代表账户调用已经通过。存储仅作标签，不参与排序。", "", "## 当前 API 型号参考", "", "| 型号 | 命名类型 | 核查日 | 官方来源 | 条件 |", "|---|---|---|---|---|"]
    for m in d.get("runtime_model_catalog", []):
        lines.append("| " + " | ".join(cell(v) for v in [m["id"], m["kind"], m["checked_on"], link("官方文档", m["source_url"]), m["notes"]]) + " |")
    lines += ["", "## 文献模型时效", "", "| 文献基座命名 | 时效状态 | 发布日 | 权重存储标签 | 核查说明 |", "|---|---|---|---|---|"]
    for m in d.get("model_profiles", []):
        lines.append("| " + " | ".join(cell(v) for v in [m["reported_label"], m["recency_status"], m.get("release_on") or "待核", f"{m['weight_storage_gib']:g} GiB（仅权重）" if m.get("weight_storage_gib") is not None else "待核", m["notes"]]) + " |")
    lines += ["", "## 基线实现与资源", "", "完整方法详情见 [候选池](METHOD_POOL.md)。未知不当作零；API 客户端 0 GiB 不表示服务端模型不消耗显存；官方示例不是峰值或最低要求。", ""]
    for m in d["methods"]:
        if m.get("reproducibility", {}).get("verified_on"):
            code = m["reproducibility"]
            lines += [f"### {m['name']}", "", resource_summary(m), "", f"代码：{link(code.get('commit') or '版本待核', code['url'])}；核查 {code['verified_on']}。{code['notes']}", ""]
    (out / "MODEL_RESOURCES.md").write_text("\n".join(lines) + "\n")


def render_candidates(d, idx, out):
    if "research_candidates" not in d:
        return
    policy = d["research_candidate_ranking"]
    lines = ["# Top 5 研究候选", "", f"审阅截止：{d['as_of']}。按一周验证顺序维护 benchmark × 方法话题组合；均为尚未验证的研究假设。", "", policy["criteria"], "", policy["limitations"], "", policy.get("negative_evidence", ""), ""]
    for c in sorted(d["research_candidates"], key=lambda c: c["rank"]):
        lines += [f"## {c['rank']}. {c['title']}", "", "Benchmark：" + " / ".join(link(idx["benchmarks"][b]["name"], b + ".md") for b in c["benchmark_ids"]), "", "相关方法：" + " / ".join(link(idx["methods"][m]["name"], "METHOD_POOL.md#" + m) for m in c["method_ids"]), "", f"状态：{c['status']}；审阅 {c['reviewed_on']}。", "", "排序理由：" + c["ranking_reason"], "", "执行条件：" + c["execution_conditions"], "", "首轮门槛：" + c["first_gate"], "", "最近邻风险：" + c["novelty_risk"], "", "一周路径：" + c["one_week_plan"], "", "文献锚点（模型、训练与协议逐行保留，不跨表排名）：", ""]
        lines += ["模型要求：" + json.dumps(c.get("model_requirement", {}), ensure_ascii=False), "", "规划资源标签（非实测，存储不参与排序）：" + json.dumps(c.get("resource_profile", {}), ensure_ascii=False), ""]
        for mid in c["method_ids"]:
            lines += ["最近邻条件：" + idx["methods"][mid]["name"] + "；" + resource_summary(idx["methods"][mid]), ""]
        for rid in c["result_ids"]:
            r = idx["results"][rid]; p = idx["papers"][r["paper_id"]]
            training = {"yes": "新增训练", "no": "无新增权重更新", "unknown": "训练待核实", "not_applicable": "不适用"}[r["target_weight_update"]]
            lines.append(f"- {idx['benchmarks'][r['benchmark_id']]['name']} · {r['method']} · {r['model']}：{r['value']:g}{r['unit']}，{r['metric']}，{r['split']} / {r['subset']}；{training}；{LANES[p['lane']]} · {p['venue']}；{link(r['locator'], r['source_url'])}。")
        lines += ["", "详细评分、基座、预算与限制见对应任务卡片。", ""]
    (out / "TOP_CANDIDATES.md").write_text("\n".join(lines) + "\n")


def apply(path, d):
    patch = read(path)
    updated = json.loads(json.dumps(d))
    changes = []
    for table in ("benchmarks", "papers", "results", "methods", "ideas"):
        for item in patch.get(table, []):
            current = next((x for x in updated[table] if x["id"] == item["id"]), None)
            if current != item:
                changes.append({"table": table, "id": item["id"], "before": current, "after": item})
                if current:
                    updated[table][updated[table].index(current)] = item
                else:
                    updated[table].append(item)
    for key in ("scope", "schema_version", "source_audit", "maintenance", "research_candidates", "research_candidate_ranking", "model_profiles", "runtime_model_catalog"):
        if key in patch and updated.get(key) != patch[key]:
            changes.append({"table": "metadata", "id": key, "before": updated.get(key), "after": patch[key]})
            updated[key] = patch[key]
    for b in updated["benchmarks"]:
        coverage, accepted = coverage_for(b["id"], updated)
        if b.get("coverage") != coverage or b.get("verified_accepted_paper_ids") != accepted:
            changes.append({"table": "derived_coverage", "id": b["id"],
                            "before": {"coverage": b.get("coverage"), "verified_accepted_paper_ids": b.get("verified_accepted_paper_ids")},
                            "after": {"coverage": coverage, "verified_accepted_paper_ids": accepted}})
            b["coverage"] = coverage
            b["verified_accepted_paper_ids"] = accepted
    updated["as_of"] = patch["as_of"]
    validate(updated)
    if changes:
        log = ROOT / "data/change_history.jsonl"
        with log.open("a") as f:
            f.write(json.dumps({"as_of": patch["as_of"], "reason": patch["reason"], "changes": changes}, ensure_ascii=False) + "\n")
    dump(DATA, updated)
    return render(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate"); sub.add_parser("render")
    r = sub.add_parser("refresh"); r.add_argument("--as-of", required=True); r.add_argument("--days", type=int, default=7); r.add_argument("--feeds-only", action="store_true")
    a = sub.add_parser("apply"); a.add_argument("patch", type=Path)
    args = parser.parse_args(); d = read(DATA)
    if args.command == "validate":
        validate(d); result = {"valid": True, "results": len(d["results"])}
    elif args.command == "render":
        result = render(d)
    elif args.command == "refresh":
        if not 1 <= args.days <= 31:
            parser.error("--days must be in [1,31]")
        result = refresh(args, d)
    else:
        result = apply(args.patch, d)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

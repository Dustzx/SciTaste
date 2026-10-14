'use strict';

const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '未披露').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const lanes = {accepted_main:'顶会主会 / D&B',accepted_findings:'Findings',accepted_workshop:'Workshop',accepted_other:'其他录用会议',accepted_journal:'期刊',arxiv:'arXiv · 录用未核实',official_report:'官方报告 / 动态榜',own_pilot:'本地开发试验'};
const laneOrder = Object.keys(lanes);
const trainLabels = {yes:'新增训练',no:'无新增权重更新',unknown:'训练待核实',not_applicable:'不适用'};
const tfLabels = {training_free:'Training-free',requires_training:'需要训练',mixed:'训练 / TF 消融并存',unknown:'训练条件待核'};
const codeLabels = {verified_code:'源码已核实',partial:'部分代码已核实',listed_unverified:'源码链接待复核',not_located:'官方实现待定位',commercial_only:'产品接口'};
const recencyLabels = {historical_backbone:'历史基座 · 当前空间待测',historical_snapshot:'旧日期型号',version_unknown:'准确版本待核'};
const resourceText = (m) => { const r=m.resources || {}; return `存储 ${r.storage_gib == null ? '待核' : number(r.storage_gib)+' GiB'} · 显存 ${r.vram_gib == null ? '待核' : number(r.vram_gib)+' GiB'}${r.measurement_kind === 'official_example' ? '（官方示例）' : r.measurement_kind === 'deployment_property' ? '（客户端）' : ''}`; };
const stateLabels = {curated:'已进入候选池',tracked:'已跟踪',needs_primary_read:'待原文核实'};
let app, registry, indexes, dataVersion, toastTimer, filterTimer, comparison = new Set(), syncRunning = false;
let bookmarks = {}, notes = {};
try { bookmarks = JSON.parse(localStorage.getItem('fastresearch.bookmarks') || '{}'); notes = JSON.parse(localStorage.getItem('fastresearch.notes') || '{}'); } catch (_) {}
const params = () => new URLSearchParams(location.hash.split('?')[1] || '');
const route = () => (location.hash.split('?')[0].replace(/^#\/?/, '') || 'overview').split('/');
const href = (page, values = {}) => '#/' + page + (Object.keys(values).length ? '?' + new URLSearchParams(values) : '');
const match = (value, query) => JSON.stringify(value).toLowerCase().includes(query.toLowerCase());
const tag = (text, style = '') => `<span class="tag ${esc(style)}">${esc(text)}</span>`;
const empty = (title, description, action = '') => `<div class="empty"><div class="empty-icon" aria-hidden="true">◇</div><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
const pageTitle = (title, subtitle, actions = '') => `<div class="page-title"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ''}</div>`;
const button = (text, action, value = '', style = '') => `<button class="button ${style}" data-action="${esc(action)}" data-value="${esc(value)}">${esc(text)}</button>`;
const external = (url, text, style = '') => /^https?:\/\//i.test(url || '') ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" class="${esc(style)}">${esc(text)} ↗</a>` : `<span class="muted">${esc(text)}：待补</span>`;
const favorite = (type, id) => `<button class="icon-button ${bookmarks[type + ':' + id] ? 'saved' : ''}" data-action="favorite" data-value="${esc(type + ':' + id)}" aria-label="${bookmarks[type + ':' + id] ? '移出研究清单' : '加入研究清单'}" aria-pressed="${Boolean(bookmarks[type + ':' + id])}" title="${bookmarks[type + ':' + id] ? '移出研究清单' : '加入研究清单'}">${bookmarks[type + ':' + id] ? '★' : '☆'}</button>`;
const detailField = (label, value, full = false, html = false) => `<div class="${full ? 'full' : ''}"><div class="info-label">${esc(label)}</div><div class="info-value">${html ? value : esc(value)}</div></div>`;
const number = value => value == null ? '未披露' : Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US', {maximumFractionDigits: 4}) : String(value);
const scoreText = row => `${number(row.value)}${row.uncertainty?.reported_plus_minus != null ? '±' + row.uncertainty.reported_plus_minus : ''}${row.unit || ''}`;
const acceptedCount = b => Object.entries(b.coverage).filter(([k]) => k.startsWith('accepted_') && k !== 'accepted_anchor_missing').reduce((n, [,v]) => n + Number(v), 0);
const allResults = benchmark => registry.results.filter(r => !benchmark || r.benchmark_id === benchmark);
const recentMethods = () => registry.methods.filter(m => {
  const date = indexes.papers[m.paper_id]?.published_on;
  return date && date.length === 10 && date <= registry.as_of && (Date.parse(registry.as_of) - Date.parse(date)) <= 14 * 86400000;
}).sort((a,b) => a.priority-b.priority || a.id.localeCompare(b.id));
const sortedScores = rows => [...rows].sort((a,b) => laneOrder.indexOf(indexes.papers[a.paper_id].lane)-laneOrder.indexOf(indexes.papers[b.paper_id].lane) || b.verified_on.localeCompare(a.verified_on) || a.benchmark_id.localeCompare(b.benchmark_id));
const countMainBenchmarks = () => registry.benchmarks.filter(b => b.coverage.accepted_main > 0).length;
const countAcceptedBenchmarks = () => registry.benchmarks.filter(b => !b.coverage.accepted_anchor_missing).length;

function toast(text) {
  $('#toast').textContent = text; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3500);
}

function buildIndexes() {
  indexes = {};
  for (const name of ['benchmarks','papers','results','methods','ideas','research_candidates','model_profiles']) indexes[name] = Object.fromEntries((registry[name] || []).map(x => [x.id,x]));
  for (const id of comparison) if (!indexes.results[id]) comparison.delete(id);
}

function navigation() {
  const current = route()[0];
  const nav = [['overview','◫','研究总览',''],['progress','↗','研究进展',''],['experience','◎','共享经验池',''],['skills','✧','核心技能',''],['race','⇄','分支赛马',''],['benchmarks','▦','Benchmark',registry.benchmarks.length],['scores','≋','文献成绩',registry.results.length],['methods','⌘','方法候选池',registry.methods.length],['resources','▤','模型与资源',''],['experiments','⚗','实验工作台',''],['program','◈','投稿规划',''],['hotspots','↗','近期热点',app.inbox.items.length],['ideas','◇','研究 Idea',registry.ideas.length],['shortlist','☆','研究清单',Object.values(bookmarks).filter(Boolean).length],['evidence','⌁','证据与维护','']];
  $('#navigation').innerHTML = nav.map(([path,symbol,text,count]) => `<a href="#/${path}" class="nav-link ${current === path ? 'active' : ''}" ${current === path ? 'aria-current="page"' : ''}><span class="nav-symbol" aria-hidden="true">${symbol}</span>${text}${count !== '' ? `<span class="nav-count">${count}</span>` : ''}</a>`).join('') + '<a class="nav-link" href="/studio/#/?lang=zh-CN"><span class="nav-symbol">▣</span>完整研究桌面</a>';
  $('#breadcrumb').textContent = nav.find(x => x[0] === current)?.[2] || '研究文档';
  $('#sidebar-date').textContent = '核实截止 ' + registry.as_of;
}

async function sync(manual = false) {
  if (syncRunning) return;
  syncRunning = true; $('#sync-button').disabled = true; $('#sync-icon').classList.add('spinning');
  try {
    const response = await fetch('/api/state', {cache:'no-cache'});
    if (!response.ok) throw new Error((await response.json()).error || '资料服务不可用');
    const payload = await response.json();
    const changed = dataVersion !== response.headers.get('ETag');
    app = payload; registry = app.registry; dataVersion = response.headers.get('ETag'); buildIndexes();
    if (changed || manual) await render();
    $('#footer-status').classList.remove('status-error');
    $('#footer-status').textContent = `核实 ${registry.as_of} · 本地资料已同步`;
    if (manual) toast(changed ? '已载入本地最新资料' : '资料已同步，当前没有新的本地更改');
  } catch (error) {
    $('#footer-status').textContent = '资料同步失败'; $('#footer-status').classList.add('status-error');
    if (!registry) $('#main').innerHTML = empty('暂时无法读取资料', error.message, button('重新连接','sync'));
    toast(error.message);
  } finally { syncRunning = false; $('#sync-button').disabled = false; $('#sync-icon').classList.remove('spinning'); }
}

function selectFilter(name, label, values, selected) {
  const pairs = values.map(x => Array.isArray(x) ? x : [x,x]);
  return `<select data-filter="${esc(name)}" aria-label="${esc(label)}"><option value="">${esc(label)}：全部</option>${pairs.map(([v,t]) => `<option value="${esc(v)}" ${String(selected ?? '') === String(v) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
}

function searchFilter(value, placeholder = '搜索名称、模型或协议') {
  return `<input type="search" data-filter="q" value="${esc(value || '')}" placeholder="${esc(placeholder)}" aria-label="页面搜索">`;
}

function filters(html) { return `<div class="toolbar">${html}${button('重置','reset-filters')}</div>`; }

function setFilter(key, value) {
  const p = params(); value ? p.set(key,value) : p.delete(key); if (key !== 'page') p.delete('page');
  const prefix = location.hash.split('?')[0] || '#/overview';
  history.replaceState(null, '', prefix + (p.size ? '?' + p.toString() : ''));
  render();
}

function paginate(rows, renderRows, limit = 24) {
  const max = Math.max(1,Math.ceil(rows.length/limit));
  const page = Math.max(1,Math.min(Number(params().get('page')) || 1,max));
  const content = renderRows(rows.slice((page-1)*limit,page*limit));
  return content + (rows.length > limit ? `<div class="pagination"><span>${rows.length} 条 · 每页 ${limit} 条</span><button class="button button-small" data-action="page" data-value="${page-1}" ${page === 1 ? 'disabled' : ''}>上一页</button>${page} / ${max}<button class="button button-small" data-action="page" data-value="${page+1}" ${page === max ? 'disabled' : ''}>下一页</button></div>` : '');
}

function benchmarkCard(b) {
  const accepted = acceptedCount(b);
  return `<article class="card" data-benchmark="${esc(b.id)}"><div class="card-top"><span class="card-id">${esc(b.id)}</span><div class="actions">${tag('影响 ' + b.influence_tier,b.influence_tier.toLowerCase())}${favorite('benchmark',b.id)}</div></div><h3><a href="#/benchmarks/${esc(b.id)}">${esc(b.name)}</a></h3><span class="subfield">${esc(b.subfield)}</span><p class="description clamp-two">${esc(b.description)}</p><div class="tags">${b.coverage.accepted_main ? tag('主会 ' + b.coverage.accepted_main,'green') : accepted ? tag('其他录用 ' + accepted,'blue') : tag('录用证据待补','amber')}${b.coverage.arxiv ? tag('arXiv ' + b.coverage.arxiv,'purple') : ''}${b.coverage.official_report ? tag('官方报告 ' + b.coverage.official_report) : ''}</div><div class="card-label">当前空间与条件</div><div class="card-line clamp-two">${esc(b.headroom)}</div><div class="card-foot"><span>${esc(b.verified_on)} 核实</span><a href="#/benchmarks/${esc(b.id)}">查看证据 →</a></div></article>`;
}

function methodCard(m) {
  const paper = indexes.papers[m.paper_id];
  const n = registry.results.filter(r => r.paper_id === m.paper_id).length;
  return `<article class="card" data-method="${esc(m.id)}"><div class="card-top"><div class="actions">${tag('P' + m.priority,'priority ' + (m.priority === 0 ? 'green' : 'blue'))}<span class="card-id">${esc(m.id)}</span></div>${favorite('method',m.id)}</div><h3><button class="row-button" data-action="method-detail" data-value="${esc(m.id)}">${esc(m.name)}</button></h3><div class="subfield">${esc(m.subfield)} · ${esc(paper.venue)}</div><div class="tags">${tag(tfLabels[m.training_free_class] || '训练条件待核',m.training_free_class === 'training_free' ? 'green':'amber')}${tag(codeLabels[m.reproducibility?.status] || '开源待核','blue')}${tag(lanes[paper.lane],paper.lane.startsWith('accepted_') ? 'green' : 'purple')}</div><div class="card-label">训练与接口</div><div class="card-line clamp-two">${esc(m.training)}；${esc(m.api_compatibility)}</div><div class="card-label">资源条件</div><div class="card-line">${esc(resourceText(m))}</div><div class="card-label">一周可行性 / 最近邻</div><div class="card-line clamp-two">${esc(m.one_week)}；${esc(m.novelty_risk)}</div><div class="card-foot"><span>${n} 条成绩 · ${m.benchmark_ids.length} 个任务</span><button class="row-button" data-action="method-detail" data-value="${esc(m.id)}">展开候选 →</button></div></article>`;
}

function candidateEvidence(c) {
  return c.result_ids.map(id => {
    const r = indexes.results[id], p = indexes.papers[r.paper_id];
    const base = indexes.results[r.delta_from], model = indexes.model_profiles[r.model_profile_id];
    return `<div class="candidate-evidence-item" data-candidate-score="${esc(id)}"><div class="candidate-score-top"><span>${esc(r.method)}</span><button class="row-button candidate-score" data-action="score-detail" data-value="${esc(id)}" aria-label="查看${esc(r.method)}的成绩协议">${base ? esc(scoreText(base)) + ' → ' : ''}${esc(scoreText(r))}</button></div><div class="candidate-protocol">${esc(r.model)} · ${esc(indexes.benchmarks[r.benchmark_id].name)}<br>${esc(r.version)} / ${esc(r.split)} / ${esc(r.subset)} · ${esc(r.metric)}</div><div class="tags">${tag(p.venue,p.lane === 'accepted_main' ? 'green' : p.lane === 'arxiv' ? 'purple' : 'blue')}${tag(trainLabels[r.target_weight_update],r.target_weight_update === 'yes' ? 'amber' : '')}${r.external_components.length ? tag('含外部组件') : ''}${model ? tag(recencyLabels[model.recency_status],'outline') : ''}</div></div>`;
  }).join('');
}

function topCandidates() {
  const candidates = [...(registry.research_candidates || [])].sort((a,b) => a.rank-b.rank);
  if (!candidates.length) return '';
  const policy = registry.research_candidate_ranking;
  return `<section class="panel candidate-panel" aria-labelledby="candidate-heading"><div class="section-head"><div><div class="eyebrow">BENCHMARK × METHOD TOPIC</div><h2 id="candidate-heading">Top 5 研究候选</h2><p>一周验证优先顺序 · 每项配对任务与方法话题 · 审阅 ${esc(policy.reviewed_on)}</p></div><a href="${href('documents',{path:'docs/registry/TOP_CANDIDATES.md'})}">完整选题依据 ↗</a></div><details class="candidate-policy"><summary>排序依据与已知负证据 · 均为待验证假设</summary><p>${esc(policy.criteria)}</p><p>${esc(policy.limitations)}</p><p>${esc(policy.negative_evidence)}</p></details><div class="candidate-list">${candidates.map(c => `<article class="candidate-row" data-candidate="${esc(c.id)}" data-rank="${c.rank}"><div class="candidate-rank" aria-label="优先顺序 ${c.rank}">${String(c.rank).padStart(2,'0')}</div><div class="candidate-topic"><div class="info-label">BENCHMARK</div><div class="candidate-benchmarks">${c.benchmark_ids.map((id,i) => `<a href="#/benchmarks/${esc(id)}" class="${i ? 'secondary-benchmark' : ''}">${esc(indexes.benchmarks[id].name)}${i ? ' · 迁移' : ''}</a>`).join('')}</div><div class="info-label">拟议方法话题</div><h3><button class="row-button" data-action="candidate-detail" data-value="${esc(c.id)}">${esc(c.title)}</button></h3><div class="tags">${tag(c.status,'amber')}${c.training_free ? tag('TF 原型优先','green') : ''}${tag('影响 ' + indexes.benchmarks[c.benchmark_ids[0]].influence_tier)}</div><div class="candidate-methods"><span>最近邻</span>${c.method_ids.map(id => `<button class="row-button" data-action="method-detail" data-value="${esc(id)}">${esc(indexes.methods[id].name)}</button><small class="candidate-code">${esc(codeLabels[indexes.methods[id].reproducibility?.status] || '开源待核')} · ${esc(resourceText(indexes.methods[id]))}</small>`).join('')}</div><div class="candidate-resource">原型：API 客户端显存 0 GiB · 存储待测（标签）</div><div class="candidate-actions">${button('选题详情 →','candidate-detail',c.id,'button-small')}<button class="button button-small" data-lab-action="candidate-project" data-value="${esc(c.id)}">建立课题</button>${favorite('idea',c.idea_ids[0])}</div></div><div class="candidate-evidence"><div class="info-label">文献成绩锚点 · 点击核查协议</div>${candidateEvidence(c)}</div><div class="candidate-decision"><div class="info-label">为何优先验证</div><p>${esc(c.ranking_reason)}</p><div class="info-label">首轮通过 / 淘汰门槛</div><p class="clamp-three">${esc(c.first_gate)}</p><div class="info-label">训练与执行条件</div><p class="clamp-three">${esc(c.execution_conditions)}</p></div></article>`).join('')}</div><div class="candidate-footnote">成绩为既有文献记录，未经我们复现；箭头仅表示文中基线与方法，总推理预算仍须核对。影响层级与一周验证顺序分别判断。</div></section>`;
}

function overview() {
  const mainCount = countMainBenchmarks(), accepted = countAcceptedBenchmarks();
  const fields = [...new Set(registry.benchmarks.map(b => b.subfield))].map(field => {
    const bs = registry.benchmarks.filter(b => b.subfield === field);
    return {field,total:bs.length,main:bs.filter(b => b.coverage.accepted_main).length,other:bs.filter(b => !b.coverage.accepted_main && !b.coverage.accepted_anchor_missing).length};
  }).sort((a,b) => b.total-a.total).slice(0,7);
  const recent = recentMethods().slice(0,4);
  const gaps = registry.benchmarks.filter(b => b.coverage.accepted_anchor_missing).sort((a,b) => b.id.localeCompare(a.id)).slice(0,5);
  return `<div class="hero"><div><div class="eyebrow">SCITASTE / RESEARCH WORKSPACE</div><h1>先看任务与成绩，再选择方法。</h1><p>从近期录用论文、预印本与公开榜单中定位研究空间。保留模型、训练和协议条件，让每个选题都有可核查的依据。</p><div class="actions"><a class="button primary" href="#/benchmarks">浏览 Benchmark →</a><a class="button" href="#/hotspots">查看近期热点</a></div><div class="hero-date">资料核实截止 ${esc(registry.as_of)} · ${accepted} 个任务已有录用成绩锚点</div></div><div class="hero-mark" aria-hidden="true"><svg viewBox="0 0 170 120"><rect x="8" y="40" width="34" height="56" rx="7" fill="#c4e5d8"/><rect x="53" y="24" width="34" height="72" rx="7" fill="#90cdb7"/><rect x="98" y="6" width="34" height="90" rx="7" fill="#3b9e80"/><path d="M8 109h143" stroke="#cee1d8"/><circle cx="144" cy="21" r="15" fill="#fff"/><path d="m136 21 5 5 9-10" stroke="#3c9b7f" stroke-width="3" fill="none" stroke-linecap="round"/></svg></div></div>
    <div class="stats">${[[registry.benchmarks.length,'Benchmark','▦',`${mainCount} 个任务有顶会主会成绩`],[registry.results.length,'成绩记录','≋','录用 / arXiv / 官方报告分列'],[registry.methods.length,'方法候选','⌘',`${registry.ideas.length} 个研究假设独立维护`],[app.inbox.items.length,'近期发现','↗',`${recentMethods().length} 个十月方法已筛读`]].map(([n,t,s,f]) => `<div class="stat"><div class="stat-top">${esc(t)}<span class="stat-symbol">${s}</span></div><div class="stat-value">${n}</div><div class="stat-bottom">${esc(f)}</div></div>`).join('')}</div>
    ${topCandidates()}
    <div class="grid-two"><section class="panel"><div class="section-head"><div><h2>子领域与证据覆盖</h2><p>库内采用证据，不能替代社区影响量</p></div><a href="#/benchmarks">全部任务 ↗</a></div><div class="coverage-legend"><span><i class="legend-dot"></i>主会锚点</span><span><i class="legend-dot secondary"></i>其他录用</span><span><i class="legend-dot pending"></i>待补证据</span></div>${fields.map(f => `<button class="field-row" data-action="field-route" data-value="${esc(f.field)}" aria-label="查看${esc(f.field)}"><span class="field-label">${esc(f.field)}</span><span class="field-bar"><span class="field-fill" data-width="${f.main/f.total*100}"></span><span class="field-fill other" data-width="${f.other/f.total*100}"></span></span><span class="field-count">${f.main+f.other}/${f.total}</span></button>`).join('')}<div class="mini-stats"><div><strong>${mainCount}</strong><span>主会成绩任务</span></div><div><strong>${accepted-mainCount}</strong><span>其他录用任务</span></div><div><strong>${registry.benchmarks.length-accepted}</strong><span>录用证据待补</span></div></div></section>
    <section class="panel"><div class="section-head"><div><h2>近期方法动向</h2><p>已人工筛读，按一周验证条件排序</p></div><a href="#/hotspots">查看全部 ↗</a></div>${recent.map(m => `<div class="hotspot-mini"><div class="hotspot-top"><h3><button class="row-button" data-action="method-detail" data-value="${esc(m.id)}">${esc(m.name)}</button></h3>${tag('P'+m.priority,'priority ' + (m.priority ? 'blue':'green'))}</div><p class="clamp-two">${esc(m.one_week)}；${esc(m.novelty_risk)}</p><div class="tags">${tag('arXiv · 录用未核实','purple')}${tag(m.subfield)}</div></div>`).join('')}</section></div>
    <section class="panel"><div class="section-head"><div><h2>新任务与证据缺口</h2><p>新热点先核资源和评分，不凭低分直接判断好提升</p></div><a href="${href('benchmarks',{coverage:'missing'})}">${registry.benchmarks.length-accepted} 个待补任务 →</a></div><div class="table-wrap"><table class="research-table"><thead><tr><th>Benchmark</th><th>子领域</th><th>当前条件</th><th>资料状态</th></tr></thead><tbody>${gaps.map(b => `<tr><td><strong><a href="#/benchmarks/${b.id}">${esc(b.name)}</a></strong><small>${esc(b.id)}</small></td><td>${esc(b.subfield)}</td><td>${esc(b.headroom)}</td><td>${tag('录用证据待补','amber')}<small>${esc(b.verified_on)}</small></td></tr>`).join('')}</tbody></table></div></section>`;
}

function benchmarkList() {
  const p = params(), q = p.get('q') || '';
  const rows = registry.benchmarks.filter(b => (!p.get('field') || b.subfield === p.get('field')) && (!p.get('influence') || b.influence_tier === p.get('influence')) && (!p.get('coverage') || (p.get('coverage') === 'main' ? b.coverage.accepted_main > 0 : p.get('coverage') === 'accepted' ? !b.coverage.accepted_anchor_missing : b.coverage.accepted_anchor_missing)) && match(b,q))
    .sort((a,b) => Number(!b.coverage.accepted_anchor_missing)-Number(!a.coverage.accepted_anchor_missing) || Number(Boolean(b.coverage.accepted_main))-Number(Boolean(a.coverage.accepted_main)) || a.influence_tier.localeCompare(b.influence_tier) || a.subfield.localeCompare(b.subfield,'zh'));
  return pageTitle('Benchmark 榜单','按子领域、影响与录用证据筛选；点击任务查看具体成绩。',`<a href="/downloads/registry.json" class="button">导出数据 ↓</a>`)
    + filters(searchFilter(q,'搜索任务名称、内容或条件') + selectFilter('field','子领域',[...new Set(registry.benchmarks.map(b => b.subfield))],p.get('field')) + selectFilter('influence','影响层',[['A','A · 成熟核心任务'],['B','B · 已有背书的专项任务'],['C','C · 新兴 / 待核资源']],p.get('influence')) + selectFilter('coverage','证据',[['main','已有顶会主会成绩'],['accepted','已有任意录用成绩'],['missing','录用证据待补']],p.get('coverage')))
    + `<div class="result-info"><span>${rows.length} / ${registry.benchmarks.length} 个任务</span><span>录用锚点优先 · 影响是定性分层</span></div>`
    + (rows.length ? paginate(rows,items => `<div class="cards">${items.map(benchmarkCard).join('')}</div>`) : empty('没有匹配的任务','调整筛选条件，或检查当前任务是否仍在观察区。',button('清除筛选','reset-filters')));
}

function scoreTable(rows) {
  if (!rows.length) return empty('暂无核实后的成绩','尚未收录不等于没有工作使用；未知条件继续保留为缺口。');
  return paginate(rows,items => `<div class="table-wrap"><table class="research-table" data-testid="scores-table"><thead><tr><th class="select-col"><span aria-label="选择成绩对照">☷</span></th><th>论文 / 方法</th><th>模型 / 新增训练</th><th>成绩</th><th>任务 / 版本</th><th>证据</th></tr></thead><tbody>${items.map(r => {
    const paper = indexes.papers[r.paper_id], b = indexes.benchmarks[r.benchmark_id];
    return `<tr data-score="${esc(r.id)}"><td class="select-col"><input type="checkbox" data-compare="${esc(r.id)}" ${comparison.has(r.id) ? 'checked' : ''} aria-label="选择${esc(r.method)} ${esc(r.model)}进行对照"></td><td><strong><button class="row-button" data-action="score-detail" data-value="${esc(r.id)}">${esc(r.method)}</button></strong><small>${esc(paper.venue)}</small>${tag(lanes[paper.lane],paper.lane.startsWith('accepted_') ? 'green' : paper.lane === 'arxiv' ? 'purple' : '')}</td><td><strong>${esc(r.model)}</strong><small>基座 ${esc(r.base_model)}</small><small>${esc(recencyLabels[indexes.model_profiles[r.model_profile_id]?.recency_status] || "准确版本待核")}</small>${tag(trainLabels[r.target_weight_update],r.target_weight_update === 'yes' ? 'amber' : r.target_weight_update === 'no' ? 'blue' : '')}${r.external_components.length ? `<small>外部：${esc(r.external_components.join(' / '))}</small>` : ''}</td><td><strong class="score-value">${esc(scoreText(r))}</strong><small>${esc(r.metric)} ${r.direction === 'higher' ? '↑' : '↓'}</small>${r.tool_matched_control ? `<small>同专家 Raw Tool<br>${esc(scoreText(indexes.results[r.tool_matched_control]))} · 总预算待核</small>` : ''}</td><td><strong><a href="#/benchmarks/${esc(b.id)}">${esc(b.name)}</a></strong><small>${esc(r.version)}<br>${esc(r.split)} / ${esc(r.subset)}<br>N=${esc(number(r.n))}</small></td><td>${external(r.source_url,r.locator)}<small>核实 ${esc(r.verified_on)}</small><button class="row-button" data-action="score-detail" data-value="${esc(r.id)}">查看完整协议 →</button></td></tr>`;
  }).join('')}</tbody></table></div>`,25);
}

function scoreFilters(benchmark = '') {
  const p = params(), rows = allResults(benchmark);
  return filters(searchFilter(p.get('q'),'搜索方法、模型、预算或原文') + (!benchmark ? selectFilter('benchmark','Benchmark',registry.benchmarks.map(b => [b.id,b.name]),p.get('benchmark')) : '')
    + selectFilter('lane','发表身份',laneOrder.filter(k => rows.some(r => indexes.papers[r.paper_id].lane === k)).map(k => [k,lanes[k]]),p.get('lane'))
    + selectFilter('training','新增训练',Object.entries(trainLabels),p.get('training'))
    + selectFilter('subset','子任务',[...new Set(rows.map(r => r.subset))],p.get('subset'))
    + selectFilter('metric','指标',[...new Set(rows.map(r => r.metric))],p.get('metric')));
}

function filteredScores(benchmark = '') {
  const p = params();
  return sortedScores(allResults(benchmark).filter(r => (!p.get('benchmark') || r.benchmark_id === p.get('benchmark')) && (!p.get('lane') || indexes.papers[r.paper_id].lane === p.get('lane')) && (!p.get('training') || r.target_weight_update === p.get('training')) && (!p.get('subset') || r.subset === p.get('subset')) && (!p.get('metric') || r.metric === p.get('metric')) && match({...r,paper:indexes.papers[r.paper_id],benchmark:indexes.benchmarks[r.benchmark_id].name},p.get('q') || '')));
}

function scoresPage() {
  const rows = filteredScores();
  return pageTitle('近期论文与成绩','录用成绩先展示，模型报告和 arXiv 保留各自身份。',`<a class="button" href="/downloads/scores.csv">导出全部成绩 ↓</a>`)
    + `<div class="note">不同版本、模型、split、指标与预算不能直接混排。勾选 2–4 条记录可以对照协议；文献成绩尚未由我们复现。</div>`
    + scoreFilters() + `<div class="result-info"><span>${rows.length} / ${registry.results.length} 条成绩</span><span>顺序按发表身份，不按跨协议分数排名</span></div>` + scoreTable(rows);
}

function benchmarkDetail(id) {
  const b = indexes.benchmarks[id];
  if (!b) return notFound();
  const rows = filteredScores(id), p = params();
  const methods = registry.methods.filter(m => m.benchmark_ids.includes(id));
  const isMethods = p.get('tab') === 'methods';
  return `<a class="back-link" href="#/benchmarks">← 返回 Benchmark</a>` + pageTitle(b.name,b.subfield,`${favorite('benchmark',id)}${external(b.official_url,'官方资源','button')}`)
    + `<div class="detail-intro"><section class="panel"><div class="tags">${tag('影响 ' + b.influence_tier,b.influence_tier.toLowerCase())}${tag(b.coverage.accepted_anchor_missing ? '录用锚点待补' : '已有录用锚点',b.coverage.accepted_anchor_missing ? 'amber' : 'green')}${tag('核实 ' + b.verified_on)}</div><h2>内容与评分</h2><p>${esc(b.description)}</p><div class="info-value">${esc(b.evaluation)}</div><div class="evidence-counts"><div><strong>${b.coverage.accepted_main}</strong><span>主会成绩</span></div><div><strong>${acceptedCount(b)-b.coverage.accepted_main}</strong><span>其他录用</span></div><div><strong>${b.coverage.arxiv}</strong><span>arXiv 成绩</span></div><div><strong>${b.coverage.official_report}</strong><span>官方报告</span></div></div></section><section class="panel"><div class="info-label">影响依据</div><div class="info-value">${esc(b.influence_reason)}</div><div class="info-label card-label">当前提升判断</div><div class="info-value">${esc(b.headroom)}</div><div class="info-label card-label">证据缺口 / 下一步</div><div class="info-value">${esc(b.gap)}</div></section></div>
    <div class="tabs"><button class="tab ${!isMethods ? 'active' : ''}" data-action="tab" data-value="scores">文献成绩 <small>${allResults(id).length}</small></button><button class="tab ${isMethods ? 'active' : ''}" data-action="tab" data-value="methods">相关方法 <small>${methods.length}</small></button><a class="tab" href="${href('documents',{path:'docs/registry/' + id + '.md'})}">完整研究卡片 ↗</a></div>`
    + (isMethods ? `<div class="cards">${methods.map(methodCard).join('')}</div>` : scoreFilters(id) + `<div class="result-info"><span>${rows.length} 条成绩符合</span><span>↑ 越高越好 · ↓ 越低越好</span></div>` + scoreTable(rows));
}

function methodsPage() {
  const p = params();
  const tfOrder = {training_free:0,mixed:1,unknown:2,requires_training:3};
  const rows = registry.methods.filter(m => (!p.get('priority') || String(m.priority) === p.get('priority')) && (!p.get('field') || m.subfield === p.get('field')) && (!p.get('lane') || indexes.papers[m.paper_id].lane === p.get('lane')) && (!p.get('tf') || m.training_free_class === p.get('tf')) && (!p.get('code') || m.reproducibility?.status === p.get('code')) && match({...m,paper:indexes.papers[m.paper_id]},p.get('q') || '')).sort((a,b) => (tfOrder[a.training_free_class] ?? 2)-(tfOrder[b.training_free_class] ?? 2) || a.priority-b.priority || a.id.localeCompare(b.id));
  return pageTitle('方法候选池','从任务、资源和最近邻出发，安排一周可完成的验证。')
    + `<div class="note">默认优先展示 Training-free 方法，再按 P0/P1/P2 排列。模型时效、开源与显存条件需逐项核对；存储大小仅作标签，不参与排序。目标模型冻结、无标签优化、无外部模型和纯 API 可用是不同条件。</div>`
    + filters(searchFilter(p.get('q'),'搜索方法、训练、API条件或最近邻') + selectFilter('tf','训练条件',Object.entries(tfLabels),p.get('tf')) + selectFilter('code','开源核实',Object.entries(codeLabels),p.get('code')) + selectFilter('priority','验证优先级',[['0','P0 · 优先核查'],['1','P1 · 条件候选'],['2','P2 · 资源或证据待补']],p.get('priority')) + selectFilter('field','子领域',[...new Set(registry.methods.map(m => m.subfield))],p.get('field')) + selectFilter('lane','发表身份',laneOrder.map(k => [k,lanes[k]]),p.get('lane')))
    + `<div class="result-info"><span>${rows.length} / ${registry.methods.length} 个公开方法</span><span>研究假设在 Idea 页面独立展示</span></div>`
    + (rows.length ? paginate(rows,items => `<div class="cards">${items.map(methodCard).join('')}</div>`) : empty('没有匹配的方法','调整关键词或发表身份。',button('清除筛选','reset-filters')));
}

function hotspotsPage() {
  const p = params(), recent = recentMethods();
  const topicCounts = {};
  for (const item of app.inbox.items) for (const topic of item.topics) topicCounts[topic] = (topicCounts[topic] || 0)+1;
  const items = app.inbox.items.filter(x => (!p.get('topic') || x.topics.includes(p.get('topic'))) && (!p.get('state') || x.state === p.get('state')) && match(x,p.get('q') || '')).sort((a,b) => (b.paper_published_at || '').localeCompare(a.paper_published_at || '') || (b.hf_upvotes || 0)-(a.hf_upvotes || 0));
  const list = paginate(items,rows => rows.map(x => `<article class="list-item" data-discovery="${esc(x.arxiv_id)}"><div class="list-content"><h3>${external(x.url,x.title)}</h3><div class="tags">${tag(stateLabels[x.state] || x.state,x.state === 'curated' ? 'green' : 'amber')}${x.topics.map(t => tag(t)).join('')}</div><p>HF 日期 ${esc((x.paper_published_at || '').slice(0,10) || '待补')} · 本项目首见 ${esc(x.first_seen)} · ${x.state === 'curated' ? '阅读深度与成绩见方法候选池' : '成绩、录用身份未核实'}</p></div><div class="list-meta"><strong>${esc(x.hf_upvotes ?? '—')}</strong>推荐票数<div>${favorite('paper',x.arxiv_id)}</div></div></article>`).join(''),20);
  return pageTitle('近期热点与发现','公开发现先进入待读队列，再经原文核实进入候选池。')
    + `<div class="section-head"><div><h2>近 14 日已筛读候选</h2><p>${recent.length} 项 · 摘要、结果表和复现是不同证据阶段</p></div></div><div class="cards">${recent.map(methodCard).join('')}</div>`
    + `<div class="divider"></div><div class="section-head"><div><h2>发现收件箱</h2><p>最近实际抓取 ${esc(app.inbox.as_of || '暂无')} · 标签可以重叠</p></div><a href="${href('evidence')}">抓取与维护记录 ↗</a></div>`
    + `<div class="note warning">HF Daily Papers 是推荐样本，不覆盖全部 arXiv。HF 元数据日期可能是修订日期，推荐票数不是学术影响。发现不会自动变成顶会录用或新成绩。</div>`
    + filters(searchFilter(p.get('q'),'搜索论文标题、主题或 arXiv ID') + selectFilter('topic','主题',Object.entries(topicCounts).map(([k,n]) => [k,k + ' · ' + n]),p.get('topic')) + selectFilter('state','阅读阶段',Object.entries(stateLabels),p.get('state')))
    + `<div class="result-info"><span>${items.length} / ${app.inbox.items.length} 个发现</span><span>按 HF 日期及推荐票数排列，非质量排名</span></div>` + (items.length ? list : empty('没有匹配的发现','扩大主题或清除筛选条件。',button('清除筛选','reset-filters')));
}

function ideaCard(i) {
  return `<article class="card idea-card"><div class="card-top"><span class="card-id">${esc(i.id)}</span><div class="actions">${tag('未验证假设','amber')}${favorite('idea',i.id)}</div></div><h3>${esc(i.hypothesis)}</h3><div class="card-label">最近邻与相关任务</div><div class="card-line">${esc(i.neighbors)}</div><div class="card-label">验证与淘汰条件</div><div class="card-line">${esc(i.gate)}</div><div class="card-foot"><span>需形成同预算增量证据</span><button class="row-button" data-action="idea-detail" data-value="${esc(i.id)}">展开假设 →</button></div></article>`;
}

function ideasPage() {
  const p = params(), rows = registry.ideas.filter(i => match(i,p.get('q') || ''));
  return pageTitle('研究 Idea','公开方法之外的候选假设，每个保留验证与淘汰门槛。')
    + `<div class="note warning">以下全部是未验证的研究假设。相似方法需继续查近邻；是否具备顶会潜力取决于区别、实测证据与独立验证。</div>`
    + filters(searchFilter(p.get('q'),'搜索研究方向、最近邻或验证门槛'))
    + `<div class="result-info"><span>${rows.length} / ${registry.ideas.length} 个候选假设</span></div>`
    + (rows.length ? `<div class="cards">${rows.map(ideaCard).join('')}</div>` : empty('没有匹配的 Idea','试试更宽的关键词。',button('清除筛选','reset-filters')));
}

function shortlistPage() {
  const groups = {benchmark:[],method:[],idea:[],paper:[]};
  for (const [key,saved] of Object.entries(bookmarks)) {
    if (!saved) continue;
    const [type,id] = key.split(':');
    const value = type === 'paper' ? app.inbox.items.find(x => x.arxiv_id === id) : indexes[{benchmark:'benchmarks',method:'methods',idea:'ideas'}[type]]?.[id];
    if (groups[type] && value) groups[type].push({value,key});
  }
  const total = Object.values(groups).reduce((n,g) => n+g.length,0);
  let content = pageTitle('研究清单','收藏值得继续核查的任务、方法和假设，记录下一步。') + `<div class="note">清单与备注仅保存在此浏览器，审阅库中的原始成绩和研究结论保持独立。</div>`;
  if (!total) return content + empty('把值得验证的线索留在这里','点击任务、方法、论文或 Idea 上的 ☆ 加入清单。',`<a class="button primary" href="#/benchmarks">浏览 Benchmark</a>`);
  for (const [type,title] of [['benchmark','Benchmark'],['method','方法候选'],['idea','研究假设'],['paper','待读论文']]) {
    if (!groups[type].length) continue;
    content += `<div class="section-head"><h2>${title} <span class="count-text">${groups[type].length}</span></h2></div><div class="cards">` + groups[type].map(({value:x,key}) => {
      const name = x.name || x.hypothesis || x.title;
      const desc = x.headroom || x.next_action || x.gate || x.topics.join(' / ');
      const titleLink = type === 'benchmark' ? `<a href="#/benchmarks/${x.id}">${esc(name)}</a>` : type === 'method' ? `<button class="row-button" data-action="method-detail" data-value="${x.id}">${esc(name)}</button>` : type === 'paper' ? external(x.url,name) : esc(name);
      return `<article class="card"><div class="card-top"><span class="card-id">${esc(x.id || x.arxiv_id)}</span>${favorite(type,x.id || x.arxiv_id)}</div><h3>${titleLink}</h3><p class="description">${esc(desc)}</p><label class="info-label" for="note-${esc(key)}">下一步备注</label><textarea id="note-${esc(key)}" class="favorite-note" data-note="${esc(key)}" placeholder="需要核实的条件、强对照或停止门槛…">${esc(notes[key] || '')}</textarea></article>`;
    }).join('') + '</div><div class="divider"></div>';
  }
  return content;
}

function evidencePage() {
  const lastRun = app.inbox.runs.at(-1);
  const ok = lastRun?.requests.filter(r => r.status === 'ok').length || 0;
  const errors = lastRun?.requests.filter(r => r.status !== 'ok').length || 0;
  const snapshots = Object.entries(app.snapshots);
  const command = `# 在 SciTaste workspace 目录运行\npython scripts/research_registry.py refresh --as-of ${registry.as_of} --days 7\npython scripts/research_registry.py validate\npython scripts/research_registry.py render`;
  return pageTitle('证据与维护','查看来源快照、原始定位、更正记录与增量更新工作流。',`<a href="${href('documents',{path:'docs/RESEARCH_REGISTRY.md'})}" class="button">完整维护说明 →</a>`)
    + `<div class="stats">${[[countMainBenchmarks(),'主会成绩任务','录用身份有官方出处'],[registry.benchmarks.filter(b => b.coverage.accepted_anchor_missing).length,'录用证据待补','保持观察，不补造分数'],[`${ok}/${lastRun?.requests.length || 0}`,'最近抓取成功',`${lastRun?.as_of || '暂无'} · ${errors} 个失败`],[app.history.length,'更正批次','保留原始值与修改原因']].map(([v,t,desc]) => `<div class="stat"><div class="stat-top">${esc(t)}</div><div class="stat-value">${esc(v)}</div><div class="stat-bottom">${esc(desc)}</div></div>`).join('')}</div>
    <div class="grid-two"><section class="panel"><div class="section-head"><div><h2>更新已有资料</h2><p>公开抓取仅发现线索，成绩仍需原文审核</p></div>${button('复制命令','copy-update')}</div><pre class="code-block">${esc(command)}</pre><p class="muted"><small>将日期改为当次核实日期。审核补丁由 apply 命令更新；网站每分钟检查本地文件，可随时点击“同步资料”。</small></p><div class="note">当前没有后台文献抓取定时器。网站服务只读本地资料，不启动模型调用或实验。</div></section><section class="panel"><div class="section-head"><div><h2>证据口径</h2><p>影响、热度、实验空间分别判断</p></div></div><div class="info-label">录用身份</div><div class="info-value">主会、Findings、Workshop、其他会议、arXiv、模型报告与本地试验独立展示。</div><div class="card-label">关键可比条件</div><div class="info-value">模型、版本、split、子任务、样本、指标、judge、数据使用与推理预算。未知字段不自动匹配。</div><div class="card-label">训练范围</div><div class="info-value">目标权重、外部专家和带标签优化分别记录。方法冻结不等于无训练数据，也不等于纯 API 可用。</div></section></div>
    <section class="panel source-list"><div class="section-head"><div><h2>公开来源快照</h2><p>内容 SHA 变化只是复核线索，不自动判定成绩变化</p></div></div>${snapshots.map(([id,s]) => `<article class="list-item"><div class="list-content"><h3>${external(s.url,id)}</h3><div class="source-hash">SHA256 ${esc(s.sha256)}</div><p>最近检查 ${esc(s.checked_on)} · ${number(s.bytes)} bytes</p></div><div class="list-meta">${tag(s.needs_review ? '变化待复核' : s.changed ? '来源有变化' : '已建立快照',s.needs_review ? 'amber' : 'green')}</div></article>`).join('')}</section><div class="divider"></div>
    <section class="panel"><div class="section-head"><div><h2>审阅与更正记录</h2><p>按照记录 ID 更新，保留更正原因</p></div></div>${[...app.history].reverse().map(h => `<div class="history-row"><div class="history-date">${esc(h.as_of)}</div><div class="history-content">${esc(h.reason)}<small>${h.changes.length} 项更改 · ${[...new Set(h.changes.map(c => c.table))].map(esc).join(' / ')}</small></div></div>`).join('')}</section><div class="divider"></div><section class="panel"><div class="section-head"><h2>研究文档</h2></div><div class="actions">${app.documents.map(d => `<a class="button button-small" href="${href('documents',{path:d.path})}">${esc(d.name)}</a>`).join('')}</div></section>`;
}

function inlineMarkdown(text, docPath) {
  const tokens = [];
  const token = html => { tokens.push(html); return '\u0001' + (tokens.length-1) + '\u0002'; };
  let raw = text.replace(/`([^`]+)`/g, (_,code) => token('<code>' + esc(code) + '</code>'));
  raw = raw.replace(/\[([^\]]+)\]\(([^\s)]+)\)/g, (_,label,url) => {
    if (/^https?:\/\//.test(url)) return token(external(url,label));
    if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//')) return token(esc(label));
    const target = new URL(url, 'http://fastresearch.local/' + docPath);
    const path = target.pathname.replace(/^\//,'');
    const pages = {'docs/registry/BENCHMARK_BOARD.md':'benchmarks','docs/registry/METHOD_POOL.md':'methods','docs/registry/LATEST_HOTSPOTS.md':'hotspots','docs/registry/DISCOVERY_INBOX.md':'hotspots','dashboard/research.html':'scores'};
    const cards = path.match(/^docs\/registry\/(B\d{2})\.md$/);
    const downloads = {'data/research_registry.json':'/downloads/registry.json','data/exports/scores.csv':'/downloads/scores.csv'};
    const destination = downloads[path] || (cards ? href('benchmarks/' + cards[1]) : pages[path] ? href(pages[path]) : href('documents',{path}));
    return token(`<a href="${esc(destination)}">${esc(label)}</a>`);
  });
  return esc(raw).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\u0001(\d+)\u0002/g, (_,n) => tokens[Number(n)]);
}

function markdown(content, docPath) {
  const lines = content.split('\n'); let output = '', i = 0;
  const cells = line => line.replace(/\\\|/g,'\u0003').trim().replace(/^\||\|$/g,'').split('|').map(x => x.trim().replace(/\u0003/g,'|'));
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith('```')) { const code = []; i++; while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]); output += '<pre><code>' + esc(code.join('\n')) + '</code></pre>'; i++; continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)/);
    if (heading) { const level = heading[1].length; output += `<h${level}>${inlineMarkdown(heading[2],docPath)}</h${level}>`; i++; continue; }
    if (line.includes('|') && /^[\s|:-]+$/.test(lines[i+1] || '') && (lines[i+1] || '').includes('---')) {
      output += '<div class="table-wrap"><table><thead><tr>' + cells(line).map(c => '<th>' + inlineMarkdown(c,docPath) + '</th>').join('') + '</tr></thead><tbody>'; i+=2;
      while (i < lines.length && lines[i].trim().startsWith('|')) output += '<tr>' + cells(lines[i++]).map(c => '<td>' + inlineMarkdown(c,docPath) + '</td>').join('') + '</tr>';
      output += '</tbody></table></div>'; continue;
    }
    if (/^\s*[-*]\s+/.test(line)) { output += '<ul>'; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) output += '<li>' + inlineMarkdown(lines[i++].replace(/^\s*[-*]\s+/,''),docPath) + '</li>'; output += '</ul>'; continue; }
    if (/^\d+\.\s+/.test(line)) { output += '<ol>'; while (i < lines.length && /^\d+\.\s+/.test(lines[i])) output += '<li>' + inlineMarkdown(lines[i++].replace(/^\d+\.\s+/,''),docPath) + '</li>'; output += '</ol>'; continue; }
    if (line.startsWith('>')) { output += '<blockquote>' + inlineMarkdown(line.replace(/^>\s*/,''),docPath) + '</blockquote>'; i++; continue; }
    output += '<p>' + inlineMarkdown(line,docPath) + '</p>'; i++;
  }
  return output;
}

async function documentsPage() {
  const path = params().get('path') || 'docs/RESEARCH_REGISTRY.md';
  const response = await fetch('/api/document?' + new URLSearchParams({path}));
  const body = await response.json();
  if (!response.ok) return pageTitle('研究文档','') + empty('资料未开放或不存在',body.error,`<a class="button" href="#/evidence">返回证据与维护</a>`);
  return `<a href="#/evidence" class="back-link">← 返回证据与维护</a><div class="document">${body.format === 'json' ? '<pre><code>' + esc(body.content) + '</code></pre>' : markdown(body.content,path)}</div>`;
}

function notFound() { return pageTitle('页面不存在','') + empty('暂未找到这条研究资料','通过导航或搜索返回现有任务与方法。',`<a class="button primary" href="#/overview">返回总览</a>`); }

let renderSequence = 0;
async function render() {
  if (!registry) return;
  const sequence = ++renderSequence, [page,id] = route();
  const active = document.activeElement;
  const restore = active?.dataset?.filter ? {key:active.dataset.filter,start:active.selectionStart,end:active.selectionEnd} : null;
  let html;
  navigation();
  if (['experiments','resources'].includes(page)) $('#main').innerHTML = '<div class="loading"><span class="loader"></span>正在读取项目证据…</div>';
  switch (page) {
    case 'overview': html = `<section class="panel program-entry"><div><div class="eyebrow">SCITASTE / IDEA RESEARCH & DISCOVERY</div><h2>用科学判断构造值得研究的 Idea</h2><p>快速检索 → 证据综合 → Idea 构造 → Taste 指导优化。共享判断与经验逐步贯穿实验、写作、图表和评审。</p></div><div class="actions"><a class="button primary" href="#/program">选择投稿目标 →</a><a class="button" href="/studio/#/?lang=zh-CN">完整研究桌面 ↗</a></div></section>` + overview(); break;
    case 'skills': html = await SciTasteSkills.render(id); break;
    case 'program': html = await SciTasteProgram.render(params()); break;
    case 'progress': html = await FastResearchProgress.progress(params()); break;
    case 'experience': html = await FastResearchProgress.experience(params()); break;
    case 'race': html = await FastResearchProgress.race(params()); break;
    case 'benchmarks': html = id ? benchmarkDetail(id) : benchmarkList(); break;
    case 'scores': html = scoresPage(); break;
    case 'methods': html = methodsPage(); break;
    case 'hotspots': html = hotspotsPage(); break;
    case 'ideas': html = ideasPage(); break;
    case 'shortlist': html = shortlistPage(); break;
    case 'evidence': html = evidencePage(); break;
    case 'resources': html = await FastResearchLab.resources(); break;
    case 'experiments': html = await FastResearchLab.render(id,params()); break;
    case 'documents': html = await documentsPage(); break;
    default: html = notFound();
  }
  if (sequence !== renderSequence) return;
  $('#main').innerHTML = html;
  for (const bar of document.querySelectorAll('[data-width]')) bar.style.width = Math.max(0,Math.min(100,Number(bar.dataset.width))) + '%';
  if (restore) {
    const next = [...document.querySelectorAll('[data-filter]')].find(x => x.dataset.filter === restore.key);
    next?.focus({preventScroll:true});
    if (next && restore.start != null) { try { next.setSelectionRange(restore.start,restore.end); } catch (_) {} }
  }
  updateCompareBar();
  document.title = ($('#main h1')?.textContent || '研究工作台') + ' · SciTaste';
}

function dialog(title, body) {
  $('#dialog-title').textContent = title; $('#dialog-body').innerHTML = body;
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
}

function scoreDetail(id) {
  const r = indexes.results[id]; if (!r) return;
  const paper = indexes.papers[r.paper_id], b = indexes.benchmarks[r.benchmark_id], profile = indexes.model_profiles[r.model_profile_id] || {};
  let base = '';
  if (r.delta_from) { const row = indexes.results[r.delta_from]; base += `<div class="note">文中基线 ${esc(scoreText(row))} → ${esc(scoreText(r))}，差值 ${(r.value-row.value).toFixed(2)}。相同任务字段不保证推理总预算相同。</div>`; }
  if (r.tool_matched_control) { const control = indexes.results[r.tool_matched_control]; base += `<div class="note success">同专家 Raw Tool：${esc(scoreText(control))}。当前方法差值 ${(r.value-control.value).toFixed(2)}；工具类型一致，总 token / 调用预算仍待核。</div>`; }
  dialog(r.method + ' · ' + b.name, `<div class="tags">${tag(lanes[paper.lane],paper.lane.startsWith('accepted_') ? 'green' : 'purple')}${tag(paper.venue)}${tag('文献成绩 · 未由我们复现','outline')}</div><div class="stat-value">${esc(scoreText(r))}<span class="score-unit"> ${r.direction === 'higher' ? '↑' : '↓'}</span></div>${base}<div class="detail-grid">`
    + detailField('实际模型',r.model) + detailField('基座',r.base_model) + detailField('模型 checkpoint',r.model_checkpoint) + detailField('新增权重训练',trainLabels[r.target_weight_update])
    + detailField('型号时效',recencyLabels[profile.recency_status] || '版本待核') + detailField('时效核查说明',profile.notes || '缺少可核实的精确版本',true)
    + detailField('权重存储标签',profile.weight_storage_gib == null ? '未披露 / 待测' : number(profile.weight_storage_gib)+' GiB · 当前仓库权重；不含数据、缓存与工具')
    + detailField('训练方式',r.training_recipe,true) + detailField('外部组件',r.external_components.join(' / ') || '无 / 未披露，见备注') + detailField('外部组件训练',r.trained_external_components)
    + detailField('版本 / split',r.version + ' / ' + r.split) + detailField('子任务 / 样本',r.subset + ' / N=' + number(r.n)) + detailField('指标',r.metric + ' / ' + (r.direction === 'higher' ? '越高越好' : '越低越好')) + detailField('scorer / judge',r.scorer)
    + detailField('推理预算',r.budget,true) + detailField('数据使用',r.data_access,true) + detailField('推理模式',r.thinking_mode) + detailField('输出协议',r.output_protocol)
    + detailField('可比限制',r.protocol_notes,true) + detailField('核实范围',r.evidence + '；' + r.verified_on,true) + (r.uncertainty ? detailField('原文误差',JSON.stringify(r.uncertainty),true) : '')
    + `</div><div class="dialog-actions">${external(r.source_url,r.locator,'button primary')}${external(paper.acceptance_url,'录用出处','button')}<a class="button" href="#/benchmarks/${b.id}" data-close-dialog>任务详情</a></div>`);
}

function methodDetail(id) {
  const m = indexes.methods[id]; if (!m) return;
  const p = indexes.papers[m.paper_id], rows = registry.results.filter(r => r.paper_id === p.id);
  dialog(m.name, `<div class="tags">${tag('P'+m.priority,'priority green')}${tag(lanes[p.lane],p.lane.startsWith('accepted_') ? 'green' : 'purple')}${tag(p.venue)}${favorite('method',id)}</div><div class="divider"></div><div class="detail-grid">`
    + detailField('领域 / 阶段',m.subfield + ' / ' + m.stage) + detailField('证据深度',m.evidence_depth) + detailField('训练条件',m.training,true) + detailField('API 与实现条件',m.api_compatibility,true)
    + detailField('训练类别',tfLabels[m.training_free_class] || '待核') + detailField('开源核实',codeLabels[m.reproducibility?.status] || '待核')
    + detailField('代码版本与许可',[m.reproducibility?.commit || 'commit 未核',m.reproducibility?.license || '许可未核',m.reproducibility?.verified_on || '日期未核'].join(' / '),true)
    + detailField('开源范围',m.reproducibility?.notes || '待核',true) + detailField('显存与存储标签',resourceText(m),true)
    + detailField('资源口径',[m.resources?.scope,m.resources?.measurement_kind,m.resources?.notes].filter(Boolean).join('；') || '未披露 / 待测',true)
    + detailField('一周可执行性',m.one_week,true) + detailField('最近邻与 novelty 风险',m.novelty_risk,true) + detailField('下一步 / 停止门槛',m.next_action,true)
    + detailField('关联任务',m.benchmark_ids.length ? m.benchmark_ids.map(b => `<a href="#/benchmarks/${b}" data-close-dialog>${esc(indexes.benchmarks[b].name)}</a>`).join(' / ') : '对应任务与资源待补',true,true)
    + detailField('论文',p.title,true) + detailField('核实日期',m.verified_on) + detailField('库内成绩',rows.length + ' 条')
    + `</div>${rows.length ? `<div class="note">代表记录：${rows.slice(0,5).map(r => `${esc(indexes.benchmarks[r.benchmark_id].name)} ${esc(r.method)} ${esc(scoreText(r))}`).join('；')}。完整结果与协议见任务卡片。</div>` : ''}<div class="dialog-actions">${external(p.url,'原论文','button primary')}${external(p.repository_url,'官方仓库','button')}${external(p.acceptance_url,'录用出处','button')}</div>`);
}

function candidateDetail(id) {
  const c = indexes.research_candidates[id]; if (!c) return;
  const methods = ids => ids.map(id => `<button class="row-button" data-action="method-detail" data-value="${esc(id)}">${esc(indexes.methods[id].name)}</button>`).join(' / ');
  dialog('Top ' + c.rank + ' · ' + c.title, `<div class="tags">${tag(c.status,'amber')}${tag('研究假设 · 增益未验证','outline')}${tag('审阅 ' + c.reviewed_on)}</div><div class="divider"></div><div class="detail-grid">`
    + detailField('Benchmark 与影响',c.benchmark_ids.map(id => `<a href="#/benchmarks/${esc(id)}" data-close-dialog>${esc(indexes.benchmarks[id].name)}</a> · 影响 ${esc(indexes.benchmarks[id].influence_tier)}`).join(' / '),true,true)
    + detailField('为什么排在这里',c.ranking_reason,true) + detailField('训练、API 与实现条件',c.execution_conditions,true)
    + detailField('当前模型选择与版本',JSON.stringify(c.model_requirement || {}),true)
    + detailField('规划资源标签',JSON.stringify(c.resource_profile || {})+'；存储不参与排序，规划数值不是实测',true)
    + detailField('首轮通过 / 淘汰门槛',c.first_gate,true) + detailField('最近邻与 novelty 风险',c.novelty_risk,true) + detailField('一周验证路径',c.one_week_plan,true)
    + detailField('最近邻方法',methods(c.method_ids),true,true) + (c.control_method_ids.length ? detailField('额外强对照',methods(c.control_method_ids),true,true) : '')
    + detailField('研究假设',c.idea_ids.map(id => `<button class="row-button" data-action="idea-detail" data-value="${esc(id)}">${esc(indexes.ideas[id].hypothesis)}</button>`).join(' / '),true,true)
    + `</div><div class="divider"></div><h3>文献成绩与协议入口</h3>${candidateEvidence(c)}<div class="note">${esc(registry.research_candidate_ranking.limitations)}</div>`);
}

function ideaDetail(id) {
  const i = indexes.ideas[id]; if (!i) return;
  dialog(i.hypothesis, `${tag('未验证假设','amber')}${favorite('idea',id)}<div class="divider"></div><div class="detail-grid">${detailField('最近邻与任务',i.neighbors,true)}${detailField('验证与淘汰条件',i.gate,true)}</div><div class="note warning">需要继续查最近邻，并在同预算强对照与独立图像/场景上验证。不能将当前假设写成已确认贡献。</div>`);
}

function updateCompareBar() {
  $('#compare-bar').hidden = comparison.size === 0;
  $('#compare-bar').innerHTML = `<span>已选择 ${comparison.size} 条成绩 · 最多 4 条</span><button class="button button-small" data-action="compare" ${comparison.size < 2 ? 'disabled' : ''}>对照协议 →</button><button class="icon-button" data-action="clear-comparison" aria-label="清空成绩对照">×</button>`;
}

function compareScores() {
  const rows = [...comparison].map(id => indexes.results[id]);
  const keys = ['benchmark_id','version','split','subset','metric','base_model','scorer','unit','direction','n'];
  const missing = value => value == null || /未披露|待核|unknown|未全|未明确/i.test(String(value));
  const different = keys.filter(k => rows.some(r => r[k] !== rows[0][k]));
  const unknown = keys.filter(k => rows.some(r => missing(r[k])));
  let note;
  if (different.length) note = `<div class="note warning">协议存在不同项：${different.map(esc).join(' / ')}。仅做条件对照，不能直接把分数差当作方法增益。</div>`;
  else if (unknown.length) note = `<div class="note warning">已记录字段一致，但 ${unknown.map(esc).join(' / ')} 仍有未知条件。不能确认完全可比，总预算另需核查。</div>`;
  else note = `<div class="note success">已记录的任务、模型与评分字段一致。推理总预算、样本失败处理和实际数据使用仍需人工核实。</div>`;
  const fields = [['成绩',r => scoreText(r)],['发表',r => lanes[indexes.papers[r.paper_id].lane] + ' / ' + indexes.papers[r.paper_id].venue],['模型',r => r.model],['基座',r => r.base_model],['版本',r => r.version],['split / 子任务',r => r.split + ' / ' + r.subset],['指标',r => r.metric + ' ' + (r.direction === 'higher' ? '↑' : '↓')],['N',r => number(r.n)],['评分',r => r.scorer],['训练',r => trainLabels[r.target_weight_update] + ' / ' + r.training_recipe],['外部组件',r => r.external_components.join(' / ') || '无 / 未披露'],['预算',r => r.budget],['数据使用',r => r.data_access],['限制',r => r.protocol_notes]];
  dialog('成绩与协议对照', note + `<div class="table-wrap"><table class="compare-table"><thead><tr><th>条件</th>${rows.map(r => `<th>${esc(r.method)}<br><small>${esc(indexes.benchmarks[r.benchmark_id].name)}</small></th>`).join('')}</tr></thead><tbody>${fields.map(([label,get]) => `<tr><th>${esc(label)}</th>${rows.map(r => `<td>${esc(get(r))}</td>`).join('')}</tr>`).join('')}<tr><th>原文</th>${rows.map(r => `<td>${external(r.source_url,r.locator)}</td>`).join('')}</tr></tbody></table></div>`);
}

function globalSearch(value) {
  const q = value.trim(), box = $('#global-results');
  if (!q || !registry) { box.hidden = true; return; }
  const matches = [];
  for (const b of registry.benchmarks) if (match({name:b.name,id:b.id,field:b.subfield,desc:b.description},q)) matches.push({name:b.name,type:'Benchmark · ' + b.subfield,page:'benchmarks/' + b.id});
  for (const m of registry.methods) if (match(m,q)) matches.push({name:m.name,type:'方法候选 · P' + m.priority,action:'method-detail',id:m.id});
  for (const c of registry.research_candidates || []) if (match(c,q)) matches.push({name:c.title,type:'Top ' + c.rank + ' · 研究候选',action:'candidate-detail',id:c.id});
  for (const i of registry.ideas) if (match(i,q)) matches.push({name:i.hypothesis,type:'未验证研究假设',action:'idea-detail',id:i.id});
  for (const r of registry.results) if (match({model:r.model,method:r.method,base:r.base_model},q)) matches.push({name:r.method + ' · ' + r.model,type:indexes.benchmarks[r.benchmark_id].name + ' · ' + scoreText(r),action:'score-detail',id:r.id});
  box.innerHTML = matches.slice(0,14).map(x => x.page ? `<a class="search-result" href="#/${esc(x.page)}">${esc(x.name)}<span>${esc(x.type)}</span></a>` : `<button class="search-result" data-action="${x.action}" data-value="${esc(x.id)}">${esc(x.name)}<span>${esc(x.type)}</span></button>`).join('') || '<div class="search-result muted">没有匹配的资料</div>';
  box.hidden = false;
}

function saveLocal() {
  try { localStorage.setItem('fastresearch.bookmarks',JSON.stringify(bookmarks)); localStorage.setItem('fastresearch.notes',JSON.stringify(notes)); return true; }
  catch (_) { toast('浏览器存储不可用，当前清单未能持久保存'); return false; }
}

document.addEventListener('click', async event => {
  if (event.target.closest('.skip-link')) { event.preventDefault(); $('#main').focus(); $('#main').scrollIntoView(); return; }
  const element = event.target.closest('[data-action]');
  if (event.target.closest('[data-close-dialog]')) $('#detail-dialog').close();
  if (event.target.closest('#global-results')) $('#global-results').hidden = true;
  if (!event.target.closest('.global-search')) $('#global-results').hidden = true;
  if (!element) return;
  const {action,value} = element.dataset;
  switch (action) {
    case 'sync': sync(true); break;
    case 'favorite': {
      bookmarks[value] = !bookmarks[value]; saveLocal();
      document.querySelectorAll('[data-action="favorite"]').forEach(b => { if (b.dataset.value === value) { b.classList.toggle('saved',Boolean(bookmarks[value])); b.textContent = bookmarks[value] ? '★' : '☆'; b.setAttribute('aria-pressed',Boolean(bookmarks[value])); b.setAttribute('aria-label',bookmarks[value] ? '移出研究清单' : '加入研究清单'); } });
      navigation(); if (route()[0] === 'shortlist') render(); toast(bookmarks[value] ? '已加入研究清单' : '已移出研究清单'); break;
    }
    case 'method-detail': methodDetail(value); break;
    case 'candidate-detail': candidateDetail(value); break;
    case 'score-detail': scoreDetail(value); break;
    case 'idea-detail': ideaDetail(value); break;
    case 'field-route': location.hash = href('benchmarks',{field:value}); break;
    case 'reset-filters': history.replaceState(null,'',location.hash.split('?')[0]); render(); break;
    case 'page': setFilter('page',value); window.scrollTo({top:0,behavior:'smooth'}); break;
    case 'tab': setFilter('tab',value); break;
    case 'compare': compareScores(); break;
    case 'clear-comparison': comparison.clear(); document.querySelectorAll('[data-compare]').forEach(x => x.checked=false); updateCompareBar(); break;
    case 'copy-update': {
      const command = `# 在 SciTaste workspace 目录运行\npython scripts/research_registry.py refresh --as-of ${registry.as_of} --days 7\npython scripts/research_registry.py validate\npython scripts/research_registry.py render`;
      try { await navigator.clipboard.writeText(command); toast('更新命令已复制，请按当次核实日期修改'); } catch (_) { toast('无法访问剪贴板，请从页面选择并复制命令'); }
      break;
    }
  }
});

document.addEventListener('change',event => {
  if (event.target.dataset.filter) setFilter(event.target.dataset.filter,event.target.value);
  if (event.target.dataset.compare) {
    const id = event.target.dataset.compare;
    if (event.target.checked) {
      if (comparison.size === 4) { event.target.checked=false; toast('一次最多对照 4 条记录'); return; }
      comparison.add(id);
    } else comparison.delete(id);
    updateCompareBar();
  }
});

document.addEventListener('input',event => {
  if (event.target.dataset.filter && event.target.tagName === 'INPUT') { clearTimeout(filterTimer); const key = event.target.dataset.filter, value = event.target.value; filterTimer = setTimeout(() => setFilter(key,value),180); }
  if (event.target.dataset.note) { notes[event.target.dataset.note] = event.target.value; saveLocal(); }
});

$('#global-search').addEventListener('input',event => globalSearch(event.target.value));
$('#global-search').addEventListener('focus',event => globalSearch(event.target.value));
$('#global-search').addEventListener('keydown',event => { if (event.key === 'Enter') { const first = $('#global-results a, #global-results button'); first?.click(); } });
$('#sync-button').addEventListener('click',() => sync(true));
$('#dialog-close').addEventListener('click',() => $('#detail-dialog').close());
$('#detail-dialog').addEventListener('click',event => { if (event.target === $('#detail-dialog')) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
function closeNavigation() { $('#sidebar').classList.remove('open'); $('#nav-backdrop').classList.remove('open'); $('#menu-toggle').setAttribute('aria-expanded','false'); }
$('#menu-toggle').addEventListener('click',() => { const open = $('#sidebar').classList.toggle('open'); $('#nav-backdrop').classList.toggle('open',open); $('#menu-toggle').setAttribute('aria-expanded',String(open)); });
$('#nav-backdrop').addEventListener('click',closeNavigation);
window.addEventListener('hashchange',() => { closeNavigation(); if ($('#detail-dialog').open) $('#detail-dialog').close(); $('#global-results').hidden=true; render(); window.scrollTo(0,0); });
document.addEventListener('keydown',event => {
  if (event.key === 'Escape') { $('#global-results').hidden=true; closeNavigation(); }
  if ((event.key === '/' || ((event.ctrlKey || event.metaKey) && event.key === 'k')) && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !$('#detail-dialog').open) { event.preventDefault(); $('#global-search').focus(); }
});
setInterval(() => { if (!document.hidden && !$('#detail-dialog').open) sync(); },60000);
sync();

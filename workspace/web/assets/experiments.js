'use strict';

// Product views use the validated SciTaste receiver data. Model text and artifact
// contents are always inert; no generated HTML, commands or callbacks are run.
window.FastResearchLab = (() => {
  let status, current, renderEpoch = 0, projects = [];
  const viewLabels = {'project-progress':'项目进度','project-overview':'项目记录','run-stage-explorer':'实验与阶段','run-comparison':'实验对照','paper-evidence':'论文与证据','blockers':'阻塞与失败','pending-proposals':'待处理提案','research-landscape':'相关研究','resources':'资源配置','plan':'研究计划','conversations':'研究对话'};
  const componentLabels = {ProjectProgressBoard:'研究进度',ProjectSummaryCard:'项目记录',RunHealth:'运行状态',PaperPreview:'论文预览',ArtifactViewer:'研究产物',RunStageExplorer:'实验与阶段',RunComparisonPanel:'指标与运行条件',EvidenceInventory:'证据条目',EvidenceGraph:'证据关系',BlockerList:'阻塞与失败',PendingProposalList:'待处理提案',ResearchLandscape:'相关研究'};
  const names = {title:'标题',status:'状态',reported_status:'登记状态',observed_state:'证据状态',run_id:'实验 ID',run_ref_id:'运行证据',model_name:'模型',model:'模型',provider:'模型来源',condition:'方法条件',evidence_scope:'证据范围',seed:'种子',stage:'阶段',stage_number:'阶段',stage_id:'阶段 ID',name:'名称',label:'名称',reason:'原因',reason_code:'状态原因',reason_codes:'状态原因',warnings:'核查提示',metric:'指标',value:'数值',baseline:'基线',candidate:'候选',baseline_value:'基线成绩',candidate_value:'候选成绩',comparable:'可比',resource_id:'资源 ID',metrics_state:'指标可用性',metrics_reason_code:'指标说明',role:'角色',availability:'可用性',paper_id:'论文 ID',state:'证据状态',source_locator:'来源记录',model_id:'模型型号',current:'当前选择',summary:'摘要',research_direction:'研究方向',counts:'记录计数',budget:'预算',resources:'资源',target_venue:'目标会议',next_gate:'下一门槛',publication_ready:'可投稿判定',completed:'已完成',total:'总计'};
  const stateNames = {planning:'规划中',planned:'协议已登记',active:'进行中',complete:'已完成',completed:'已完成',blocked:'阻塞',failed:'失败',draft:'草案',unavailable:'不可用',available:'可用',not_started:'未开始',unknown:'待核实',generated:'视图已整理',no_matching_evidence:'缺少匹配证据',clarification_required:'需要明确对象','protocol-only':'协议记录','no-registered-comparable-metrics':'未登记可比指标',protocol_only:'协议记录',none:'无',false:'否',true:'是'};
  const route = (project='', values={}) => '#/experiments' + (project ? '/' + encodeURIComponent(project) : '') + (Object.keys(values).length ? '?' + new URLSearchParams(values) : '');
  const labButton = (label, action, value='', style='') => `<button class="button ${style}" data-lab-action="${esc(action)}" data-value="${esc(value)}">${esc(label)}</button>`;
  const translated = value => value == null ? '未记录' : stateNames[String(value)] || String(value);
  const rawText = value => value == null ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : translated(value);

  async function api(path, options={}) {
    if (options.method && options.method !== 'GET' && !status) await loadStatus();
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(),120000);
    try {
      const response = await fetch('/api/experiments/' + path, {cache:'no-cache', ...options, signal:controller.signal,
        headers:{'Content-Type':'application/json', ...(status && options.method && options.method !== 'GET' ? {'X-FastResearch-CSRF':status.csrf_token} : {}), ...options.headers}});
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || '实验服务暂时不可用');
      return body;
    } catch (error) { if (error.name === 'AbortError') throw new Error('项目证据读取超时，请稍后手动同步；当前记录未改变'); throw error; }
    finally { clearTimeout(timer); }
  }
  async function loadStatus() { status = await api('status'); return status; }
  const basePath = context => `${context.origin}/projects/${encodeURIComponent(context.project)}`;

  function recordTable(items) {
    if (!items?.length) return `<p class="lab-muted">暂无已登记记录。</p>`;
    const keys = [...new Set(items.flatMap(row=>Object.keys(row)))].filter(k=>!k.endsWith('_ref_ids') && !k.endsWith('_ref_id') && !['support_ref_ids','sha256'].includes(k)).slice(0,9);
    return `<div class="table-wrap"><table class="research-table lab-record-table"><thead><tr>${keys.map(k=>`<th>${esc(names[k] || k)}</th>`).join('')}</tr></thead><tbody>${items.slice(0,30).map(item=>`<tr>${keys.map(k=>`<td>${esc(rawText(item[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${items.length > 30 ? `<p class="lab-muted">显示前 30 / ${items.length} 条；完整记录在下方字段视图中保留。</p>` : ''}`;
  }
  function fields(data, depth=0) {
    if (data == null) return `<span class="lab-muted">未记录</span>`;
    if (typeof data !== 'object') return `<span>${esc(translated(data))}</span>`;
    if (Array.isArray(data)) {
      if (!data.length) return `<span class="lab-muted">暂无记录</span>`;
      if (data.every(x=>x && typeof x === 'object' && !Array.isArray(x))) return recordTable(data);
      return `<div class="tags">${data.slice(0,40).map(x=>tag(typeof x==='object' ? rawText(x) : translated(x))).join('')}</div>`;
    }
    return `<div class="lab-fields">${Object.entries(data).filter(([k])=>!['project_ref_id','support_ref_ids','summary_ref_ids','focus_ref_ids'].includes(k)).map(([key,value])=> {
      if (value && typeof value === 'object') return `<details class="lab-object" ${depth===0 && ['runs','stages','metrics','items','phases','recent_activity'].includes(key) ? 'open' : ''}><summary>${esc(names[key] || key)}${Array.isArray(value) ? ' · ' + value.length : ''}</summary>${depth>2 ? `<pre class="code-block">${esc(JSON.stringify(value,null,2))}</pre>` : fields(value,depth+1)}</details>`;
      return `<div class="lab-field"><span>${esc(names[key] || key)}</span><div>${esc(translated(value))}</div></div>`;
    }).join('')}</div>`;
  }
  function progressBoard(data, pane) {
    if (pane==='resources') return `<div class="note">项目绑定与历史观测来自 SciTaste 证据。本机实时磁盘信息见<a href="#/resources">模型与资源</a>；历史 GPU 观测不代表当前可用配额。</div>${fields(data.resource_portfolio || {状态:'项目尚未绑定资源'})}`;
    if (pane==='plan') return `${fields(data.evidence_program || {研究方向:data.focus,下一门槛:data.next_gate,说明:'当前项目没有已登记的科学阶段计划'})}${data.project_documents ? fields(data.project_documents) : ''}`;
    const counters=Object.entries(data.counts || {}).filter(([,v])=>typeof v==='number').slice(0,4);
    return `${counters.length ? `<div class="lab-stats">${counters.map(([k,v])=>`<div><strong>${v}</strong><span>${esc(names[k] || k)}</span></div>`).join('')}</div>` : ''}<div class="lab-focus"><div><div class="eyebrow">CURRENT RESEARCH</div><h3>${esc(data.focus || '研究方向待补')}</h3><p>${esc(data.next_gate || '下一门槛待补')}</p></div>${tag(translated(data.project_status),'green')}</div>${data.evidence_program ? `<h3>登记的科学计划</h3>${fields(data.evidence_program)}` : ''}${data.recent_activity?.length ? `<h3>运行与迭代记录</h3>${recordTable(data.recent_activity)}` : ''}${data.milestones?.length ? `<h3>里程碑记录</h3>${recordTable(data.milestones)}` : ''}${data.resource_portfolio ? `<details class="lab-object"><summary>项目资源绑定</summary>${fields(data.resource_portfolio)}</details>` : ''}<div class="note">阶段进度与结果范围来自已登记证据；记录数量、工程完成或协议登记不等于科学效果或投稿达标。</div>`;
  }
  function component(c, pane) {
    if (pane==='resources' || pane==='plan') {
      if (c.renderer!=='ProjectProgressBoard') return '';
    }
    let content;
    if (c.renderer==='ProjectProgressBoard') content=progressBoard(c.data,pane);
    else if (c.renderer==='EvidenceGraph') content=`<div class="lab-evidence-nodes">${(c.data.nodes || []).slice(0,40).map(n=>`<div class="lab-evidence-node"><span>${esc(n.kind)}</span>${esc(n.label)}</div>`).join('')}</div><details class="lab-object"><summary>证据关系</summary>${recordTable(c.data.edges || [])}</details>`;
    else content=fields(c.data);
    return `<section class="panel lab-component" data-lab-component="${esc(c.renderer)}"><div class="section-head"><h2>${esc(componentLabels[c.renderer] || c.title)}</h2></div>${content}<details class="lab-object"><summary>完整字段与原始证据</summary><pre class="code-block">${esc(JSON.stringify(c.data,null,2))}</pre></details></section>`;
  }
  function listSelections(renderer) {
    const runs=new Map(), papers=new Map();
    const visit=value=> {
      if (!value || typeof value!=='object') return;
      if (value.run_id) runs.set(value.run_id,value);
      if (value.paper_id) papers.set(value.paper_id,value);
      for (const child of Object.values(value)) if (typeof child==='object') { if (Array.isArray(child)) child.forEach(visit); else visit(child); }
    };
    renderer.components.forEach(c=>visit(c.data));
    return {runs:[...runs.values()],papers:[...papers.values()]};
  }

  async function gallery() {
    await window.ProjectEvidence.cards();
    const responses=await Promise.allSettled(['fastresearch'].map(async origin=>({origin,body:await api(origin+'/projects')})));
    projects=[]; const failures=[];
    for (const [i,r] of responses.entries()) {
      if (r.status==='fulfilled') projects.push(...r.value.body.projects.map(p=>({...p,origin:r.value.origin})));
      else failures.push((i ? 'SciTaste' : 'SciTaste') + '：' + r.reason.message);
    }
    projects.sort((a,b)=>Number(b.project_id==='voa')-Number(a.project_id==='voa'));
    return pageTitle('实验工作台','从研究候选建立课题，维护协议、运行、证据与研究对话。',labButton('新建课题','create-project','','primary'))
      + `<div class="lab-banner"><div><div class="eyebrow">SCITASTE / SCIENTIFIC WORKSPACE</div><h2>从实验到论文，完整研究工作区。</h2><p>Idea 调研与已有实验、论文产物共享同一研究工作区。完整桌面提供研究计划、资源配置、评审与修订；本页保留快捷证据入口。</p></div><div class="actions"><a class="button primary" href="/studio/#/?lang=zh-CN">打开完整研究桌面 →</a><a class="button" href="#/program">CCF A/B · 投稿规划</a></div></div>`
      + (failures.length ? `<div class="note warning">${esc(failures.join('；'))}</div>` : '')
      + ['fastresearch'].map(origin=>`<div class="section-head"><h2>我的课题 · 含已迁移项目</h2><span class="count-text">${projects.filter(p=>p.origin===origin).length} 项</span></div><div class="cards lab-projects"><button class="card lab-create-card" data-lab-action="create-project"><span>＋</span><h3>创建研究课题</h3><p>选择目标、benchmark 与验证门槛</p></button>${projects.filter(p=>p.origin===origin).map(p=>window.ProjectEvidence.card(p) || `<article class="card" data-lab-project="${esc(p.project_id)}"><div class="card-top">${tag(translated(p.status),p.status==='complete' ? 'green' : 'blue')}<span class="card-id">r${p.revision}</span></div><h3><a href="${route(p.project_id,{origin})}">${esc(p.title || p.project_id)}</a></h3><p class="description clamp-three">${esc(p.research_direction)}</p><div class="tags">${p.target_venue ? tag(p.target_venue) : ''}${tag(p.run_count+' 个运行记录')}${tag(p.paper_count+' 个论文记录')}</div><div class="card-foot"><span>${esc(p.project_id)}</span><a href="${route(p.project_id,{origin})}">打开课题 →</a></div></article>`).join('')}</div><div class="divider"></div>`).join('');
  }

  async function projectPage(project, p, epoch) {
    if (project==='voa' && (p.get('origin') || 'fastresearch')==='fastresearch') {
      current=null;
      return window.ProjectEvidence.render(p);
    }
    const origin=p.get('origin') || 'fastresearch', pane=p.get('view') || 'project-progress';
    const backendView=['resources','plan','conversations'].includes(pane) ? 'project-progress' : pane;
    const query={view:backendView};
    for (const k of ['run_id','paper_id','baseline_run_id','candidate_run_id']) if (p.get(k)) query[k]=p.get(k);
    const context={origin,project,query,pane};
    const path=basePath(context);
    if (backendView==='run-comparison' && (!query.baseline_run_id || !query.candidate_run_id)) {
      const doc=await api(path+'/workspace?view=run-stage-explorer');
      if (epoch!==renderEpoch) return '';
      current={...context,doc,query:{view:'run-stage-explorer'}};
      const selections=listSelections(doc.renderer);
      return pageTitle('实验对照','选择同项目基线与候选；未知协议保留为待核，不自动合并。') + projectNav(project,origin,pane) + `<section class="panel"><form id="lab-compare-form" class="lab-form"><label>基线<select name="baseline_run_id" required>${selections.runs.map(r=>`<option value="${esc(r.run_id)}">${esc(r.run_id)}</option>`).join('')}</select></label><label>候选<select name="candidate_run_id" required>${selections.runs.map(r=>`<option value="${esc(r.run_id)}">${esc(r.run_id)}</option>`).join('')}</select></label><button class="button primary" ${selections.runs.length < 2 ? 'disabled' : ''}>查看协议与指标</button></form>${selections.runs.length < 2 ? '<p class="lab-muted">至少需要两个已登记运行；不会创建虚拟对照结果。</p>' : ''}</section>`;
    }
    const [doc,record]=await Promise.all([api(path+'/workspace?'+new URLSearchParams(query)),api(path+'/metadata')]);
    if (epoch!==renderEpoch) return '';
    current={...context,doc};
    if (pane==='conversations') return conversationsPage();
    if (pane==='plan') {
      const plan=await api(path+'/plan');
      return pageTitle(record?.title || project,'研究计划与官方日期') + projectNav(project,origin,pane) + deliveryPlan(plan) + `<a class="button primary" href="/studio/#/projects/${encodeURIComponent(project)}?lang=zh-CN">进入完整研究桌面 →</a>`;
    }
    if (origin==='fastresearch' && ['run-stage-explorer','run-comparison','resources'].includes(pane)) current.protocols=await api(path+'/protocols');
    const selection=listSelections(doc.renderer);
    const selectionBar=backendView==='run-stage-explorer' ? `<div class="toolbar"><label>实验<select id="lab-run-select"><option value="">当前登记选择</option>${selection.runs.map(r=>`<option value="${esc(r.run_id)}" ${r.run_id===query.run_id ? 'selected' : ''}>${esc(r.run_id)} · ${esc(translated(r.reported_status || r.status))}</option>`).join('')}</select></label></div>` : backendView==='paper-evidence' ? `<div class="toolbar"><label>论文<select id="lab-paper-select"><option value="">当前登记选择</option>${selection.papers.map(r=>`<option value="${esc(r.paper_id)}" ${r.paper_id===query.paper_id ? 'selected' : ''}>${esc(r.title || r.paper_id)}</option>`).join('')}</select></label></div>` : '';
    return `<a class="back-link" href="#/experiments">← 全部课题</a>` + pageTitle(record?.title || project,`${origin==='scitaste' ? 'SciTaste 历史引用' : 'SciTaste 课题'} · ${viewLabels[pane] || pane}`,origin==='fastresearch' ? labButton('登记实验协议','protocol','','primary') : tag('历史项目只读','blue'))
      + projectNav(project,origin,pane) + `<div class="lab-provenance">${tag('项目版本 r'+doc.freshness.project_revision,'green')}<span>${doc.freshness.evidence_count} 项绑定证据</span><span>快照 ${esc(doc.freshness.snapshot_sha256.slice(0,12))}</span>${labButton('同步课题','refresh','','button-small')}<a class="button button-small" href="/studio/#/projects/${encodeURIComponent(project)}?lang=zh-CN">完整研究桌面 ↗</a></div>` + selectionBar
      + (record.warnings?.length ? `<details class="panel lab-component"><summary>历史档案核查提示 · ${record.warnings.length} 项</summary><ul>${record.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>` : '')
      + protocolPanel(query)
      + doc.renderer.components.map(c=>component(c,pane)).join('')
      + (origin==='fastresearch' && doc.renderer.actions.length ? `<section class="panel lab-component"><h2>可登记的研究提案</h2><div class="actions">${doc.renderer.actions.map(a=>labButton(a.label,'proposal',a.action_id)).join('')}</div><p class="lab-muted">操作遵循原有控制器，形成有证据绑定的提案；提案不代表实验已执行。</p></section>` : '')
      + `<section class="panel lab-component"><div class="section-head"><h2>证据索引</h2><span class="count-text">登记来源与内容校验</span></div><div class="lab-evidence-index">${doc.renderer.snapshot.evidence_refs.map(r=>`<div><span><strong>${esc(r.label)}</strong><small>${esc(r.locator)} · ${esc(r.sha256.slice(0,12))}</small></span>${doc.renderer.components.some(c=>c.renderer==='ArtifactViewer' && c.data.artifact_ref_id===r.evidence_id) ? labButton('预览','inspect',r.evidence_id,'button-small') : ''}</div>`).join('')}</div></section>`;
  }
  function protocolPanel(query) {
    if (!current?.protocols?.protocols.length) return '';
    const ids=[query.run_id,query.baseline_run_id,query.candidate_run_id].filter(Boolean);
    const rows=current.protocols.protocols.filter(r=>!ids.length || ids.includes(r.run_id));
    if (!rows.length) return '';
    const keys=['model_id','model_revision','training_free','baseline','benchmark','split','scorer','budget_calls','budget_tokens','vram_gib','storage_gib','stop_condition'];
    const labels={model_id:'模型准确型号',model_revision:'模型版本 / 返回型号',training_free:'Training-free',baseline:'基线方法与版本',benchmark:'Benchmark / 版本',split:'数据划分',scorer:'评分器版本',budget_calls:'调用上限（规划）',budget_tokens:'token 上限（规划）',vram_gib:'显存 GiB（规划）',storage_gib:'存储标签 GiB（规划）',stop_condition:'停止条件'};
    return `<section class="panel lab-component"><div class="section-head"><h2>待执行协议与预算</h2>${tag('协议记录 · 非实验结果','amber')}</div><div class="table-wrap"><table class="compare-table"><thead><tr><th>条件</th>${rows.map(r=>`<th>${esc(r.run_id)} ${labButton('预览','protocol-inspect',r.run_id,'button-small')}</th>`).join('')}</tr></thead><tbody>${keys.map(k=>`<tr><th>${labels[k]}</th>${rows.map(r=>`<td>${esc(translated(r.protocol[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="lab-muted">数字是规划上限；未登记执行结果。模型版本、数据和总预算需要一致后再比较效果。存储只作标签，不参与排序。</p></section>`;
  }
  function projectNav(project,origin,pane) {
    return `<nav class="tabs lab-tabs" aria-label="课题工作区">${Object.entries(viewLabels).map(([view,label])=>`<a class="tab ${view===pane ? 'active' : ''}" href="${route(project,{origin,view})}">${esc(label)}</a>`).join('')}</nav>`;
  }
  async function conversationsPage() {
    const path=basePath(current), catalog=await api(path+'/workspaces');
    const items=catalog.workspaces || [];
    return pageTitle('研究对话','围绕课题证据整理视图；保留不可变轮次与反馈上下文。',current.origin==='fastresearch' ? labButton('新建证据对话','conversation','','primary') : '') + projectNav(current.project,current.origin,'conversations')
      + `<div class="note">当前接入已有证据与本地视图整理，模型问答尚未启用。</div>`
      + (items.length ? items.map(w=>`<article class="list-item"><div class="list-content"><h3>${esc(w.title)}</h3><p>话题版本 ${w.revision} · ${esc(w.updated_at)} · ${esc(translated(w.latest_status))}</p></div>${labButton('查看轮次','conversation-open',w.workspace_id,'button-small')}</article>`).join('') : empty('暂无研究对话','可以从项目进度、实验对照或下一门槛开始。'));
  }
  function createForm(candidate) {
    const c=candidate ? registry.research_candidates.find(x=>x.id===candidate) : null;
    dialog('新建研究课题',`<form id="lab-create-form" class="lab-form"><label>课题 ID<input name="project_id" required pattern="[A-Za-z0-9][A-Za-z0-9._-]*" maxlength="128" value="${c ? 'fastresearch-'+c.id.toLowerCase() : ''}" placeholder="chart-binding-v1"></label><label>课题名称<input name="title" required maxlength="160" value="${esc(c?.title || '')}"></label><label class="full">研究方向与验证门槛<textarea name="research_direction" required maxlength="2000">${esc(c ? `${c.title}\nBenchmark: ${c.benchmark_ids.map(id=>indexes.benchmarks[id].name).join(' / ')}\n${c.first_gate}` : '')}</textarea></label><label>目标会议<input name="target_venue" maxlength="120" placeholder="待选定"></label><div class="full note">创建课题只登记研究元数据；实验协议和预算在课题内单独维护。</div><button class="button primary">创建课题</button><p class="lab-form-error" role="alert"></p></form>`);
  }
  function input(name,label,type='text',value='',extra='') { return `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" required ${extra}></label>`; }
  function protocolForm() {
    if (!current || current.origin!=='fastresearch') return;
    const methods=registry.methods.filter(m=>m.training_free_class==='training_free' && m.reproducibility?.status==='verified_code');
    dialog('登记实验协议',`<form id="lab-protocol-form" class="lab-form">${input('run_id','实验 ID','text','','pattern="[A-Za-z0-9][A-Za-z0-9._-]*" maxlength="128"')}${input('title','实验名称')}${input('model_id','准确模型 ID / checkpoint','text','','list="lab-model-list"')}<datalist id="lab-model-list">${(registry.runtime_model_catalog || []).map(m=>`<option value="${esc(m.id)}"></option>`).join('')}</datalist><label>模型 revision / 返回型号<input name="model_revision" placeholder="滚动别名需补记录"></label>${input('baseline','基线方法与代码版本','text','','list="lab-baseline-list"')}<datalist id="lab-baseline-list">${methods.map(m=>`<option value="${esc(m.name+' @ '+m.reproducibility.commit)}"></option>`).join('')}</datalist>${input('benchmark','Benchmark 与版本')}${input('split','划分 / 开发或独立测试')}${input('scorer','评分代码与版本')}${input('host','执行位置','text','API 客户端')}${input('budget_calls','调用上限（规划）','number',0,'min="0" step="1"')}${input('budget_tokens','总 token 上限（规划）','number',0,'min="0" step="1"')}<label>存储预算标签 GiB（规划，可留空）<input name="storage_gib" type="number" min="0" step="0.01" placeholder="未知 / 待测"></label>${input('vram_gib','每卡显存预算 GiB（规划）','number',0,'min="0" step="0.01"')}<label class="lab-checkbox full"><input name="training_free" type="checkbox" checked> Training-free：不新增权重训练</label><label class="full">停止条件<textarea name="stop_condition" required placeholder="同预算强基线无独立增量时停止；列出费用/超时门槛"></textarea></label><div class="note full">这里保存待执行协议，资源数字为规划上限，尚非实际消耗。存储只作标签，不影响研究排序。当前工作台不连接付费模型或 GPU 启动器。</div><button class="button primary">保存待执行协议</button><p class="lab-form-error" role="alert"></p></form>`);
  }
  function identityEvent(renderer) {
    return {schema_version:'1.0',event_id:'fr-'+crypto.randomUUID(),project_id:renderer.project_id,surface_id:renderer.surface_id,surface_revision:renderer.surface_revision,surface_fingerprint:renderer.surface_fingerprint,snapshot_revision:renderer.snapshot.snapshot_revision,snapshot_sha256:renderer.snapshot.snapshot_sha256};
  }
  async function inspect(id) {
    const ref=current?.doc.renderer.snapshot.evidence_refs.find(r=>r.evidence_id===id);
    if (!ref) return;
    const body={...identityEvent(current.doc.renderer),event_type:'artifact_inspection_requested',artifact_ref_id:id};
    const data=await api(basePath(current)+'/inspections?'+new URLSearchParams(current.query),{method:'POST',body:JSON.stringify(body)});
    const preview=data.preview_kind==='image' ? `<img class="lab-artifact-image" src="data:${esc(data.receipt.media_type)};base64,${esc(data.image_base64)}" alt="${esc(ref.label)}">` : data.preview_kind==='pdf_metadata' ? `<p>PDF ${esc(data.pdf_version)} · ${data.receipt.byte_length} bytes</p>` : `<pre class="code-block lab-artifact-text">${esc(data.text_content)}</pre>`;
    dialog(ref.label,`<div class="note">来源 ${esc(data.receipt.locator)} · 内容校验 ${esc(data.receipt.artifact_sha256.slice(0,16))}</div>${preview}`);
  }
  async function conversationForm() {
    current.intents=await api(basePath(current)+'/intents');
    dialog('新建证据对话',`<form id="lab-conversation-form" class="lab-form"><label class="full">当前问题<textarea name="question" maxlength="1000" required placeholder="例如：查看项目进度与下一步门槛"></textarea></label><div class="full note">本地视图整理只使用当前项目证据，无法匹配的问题会明确显示证据缺口。</div><button class="button primary">整理当前证据</button><p class="lab-form-error" role="alert"></p></form>`);
  }
  function conversationDetail(data) {
    current.workspace=data.workspace;
    current.turns=data.turns;
    dialog(data.workspace.title,`${current.origin==='fastresearch' ? `<div class="actions">${labButton('继续追问','follow-up')}${labButton('修改话题名','rename-conversation')}</div>` : ''}<div class="lab-turn-list">${data.turns.map(t=>`<button class="list-item" data-lab-action="turn-open" data-value="${esc(t.turn_id)}"><span>第 ${t.ordinal} 轮 · ${esc(t.prompt.text)}<small>${esc(t.created_at)} · ${esc(translated(t.status))}</small></span></button>`).join('')}</div>`);
  }

  async function render(project,p) {
    const epoch=++renderEpoch;
    try { await loadStatus(); return project ? await projectPage(project,p,epoch) : await gallery(); }
    catch (error) { return pageTitle('实验工作台','') + empty('实验资料暂时不可用',error.message,labButton('重新同步','refresh')); }
  }
  function modernModelCard(m) {
    return `<article class="card"><div class="card-top">${tag(m.kind==='rolling_alias' ? '滚动别名' : '固定命名型号',m.kind==='rolling_alias' ? 'amber':'green')}<span class="card-id">${esc(m.checked_on)}</span></div><h3>${esc(m.id)}</h3><p class="description">${esc(m.notes)}</p><div class="tags">${tag('本机客户端显存 '+m.local_client_vram_gib+' GiB')}${tag('账户可用性未调用验证')}</div><div class="card-foot">${external(m.source_url,'官方型号文档')}</div></article>`;
  }
  async function resources() {
    let health;
    try { health=await loadStatus(); } catch (_) {}
    const known=registry.model_profiles.filter(m=>m.weight_storage_gib != null);
    return pageTitle('模型与资源','先确认当前型号与基线可复现性；storage 仅作标签，training-free 优先。')
      + (health ? `<div class="note">本机磁盘可用 <strong>${health.disk.free_gib} GiB</strong> / ${health.disk.total_gib} GiB · 观测 ${esc(health.disk.observed_at)}。存储大小不参与候选排序；显存数据按客户端、官方示例和未知分别标记。</div>` : '')
      + `<div class="section-head"><h2>当前 API 型号参考</h2><span class="count-text">文档已核实 · 未测试账户调用</span></div><div class="cards">${(registry.runtime_model_catalog || []).map(modernModelCard).join('')}</div><div class="divider"></div>`
      + `<div class="section-head"><h2>开源权重与存储标签</h2><span class="count-text">仅权重文件，不包含数据、环境或缓存</span></div><div class="cards">${known.map(m=>`<article class="card"><h3>${esc(m.reported_label)}</h3><div class="tags">${tag('权重 '+m.weight_storage_gib+' GiB','blue')}${tag(recencyLabels[m.recency_status],'amber')}</div><p class="description">仓库创建 ${esc(m.repository_created_on)} · 发布日待核。${esc(m.notes)}</p><div class="source-hash">${esc(m.weight_revision)}</div><div class="card-foot">${external(m.source_url,'官方模型仓库')}</div></article>`).join('')}</div><div class="divider"></div>`
      + `<div class="section-head"><div><h2>基线实现与资源条件</h2><p>冻结模型仍可能需要本地训练专家或高预算搜索；未知显存/存储保留待核。</p></div><a href="#/methods?tf=training_free">筛选 Training-free →</a></div><div class="cards">${registry.methods.filter(m=>m.reproducibility?.verified_on || m.id==='M42').map(methodCard).join('')}</div>`;
  }

  document.addEventListener('click',async event=> {
    const button=event.target.closest('[data-lab-action]'); if (!button) return;
    const {labAction:action,value}=button.dataset;
    button.disabled=true;
    try {
      if (action==='create-project') createForm();
      else if (action==='candidate-project') createForm(value);
      else if (action==='protocol') protocolForm();
      else if (action==='refresh') {status=null; await window.render();}
      else if (action==='inspect') await inspect(value);
      else if (action==='protocol-inspect') {
        const item=current.protocols.protocols.find(p=>p.run_id===value);
        const checked=await api(basePath(current)+'/protocol-inspections',{method:'POST',body:JSON.stringify({run_id:value,sha256:item.sha256,expected_revision:current.protocols.revision})});
        dialog('协议 · '+value,`<div class="note">${esc(checked.locator)} · SHA ${esc(checked.sha256.slice(0,16))}</div><pre class="code-block lab-artifact-text">${esc(JSON.stringify(checked.protocol,null,2))}</pre>`);
      }
      else if (action==='conversation') await conversationForm();
      else if (action==='conversation-open') {
        const data=await api(basePath(current)+'/workspaces/'+encodeURIComponent(value));
        conversationDetail(data);
      } else if (action==='turn-open') {
        const data=await api(basePath(current)+'/workspaces/'+current.workspace.workspace_id+'/turns/'+encodeURIComponent(value));
        const t=data.turn;
        dialog('第 '+t.ordinal+' 轮 · '+t.prompt.text,`<div class="note">${esc(translated(t.document.status))} · ${esc(t.document.reason_code)}</div>${t.document.renderer ? t.document.renderer.components.map(c=>component(c,'generated')).join('') : ''}<div class="actions">${labButton('返回轮次','conversation-open',current.workspace.workspace_id)}</div>`);
      } else if (action==='follow-up') {
        current.intents=await api(basePath(current)+'/intents');
        dialog('继续研究对话',`<form id="lab-followup-form" class="lab-form"><label class="full">当前问题<textarea name="question" maxlength="1000" required></textarea></label><div class="note full">关联上一轮证据上下文，历史轮次保留原样。</div><button class="button primary">保存新轮次</button><p class="lab-form-error" role="alert"></p></form>`);
      } else if (action==='rename-conversation') {
        dialog('修改话题名',`<form id="lab-rename-form" class="lab-form"><label class="full">话题名称<input name="title" maxlength="120" value="${esc(current.workspace.title)}" required></label><button class="button primary">保存名称</button><p class="lab-form-error" role="alert"></p></form>`);
      } else if (action==='proposal') {
        const data=await api(basePath(current)+'/events?'+new URLSearchParams(current.query),{method:'POST',body:JSON.stringify({...identityEvent(current.doc.renderer),event_type:'surface_action_requested',action_id:value})});
        dialog('提案已登记',`<div class="note">提案记录来自原控制器，实验执行状态仍以实际运行证据为准。</div>${fields(data)}`);
      }
    } catch (error) {toast(error.message);} finally {button.disabled=false;}
  });
  document.addEventListener('change',event=> {
    if (!current) return;
    if (event.target.id==='lab-run-select') location.hash=route(current.project,{origin:current.origin,view:'run-stage-explorer',run_id:event.target.value});
    if (event.target.id==='lab-paper-select') location.hash=route(current.project,{origin:current.origin,view:'paper-evidence',paper_id:event.target.value});
  });
  document.addEventListener('submit',async event=> {
    const form=event.target;
    if (!['lab-create-form','lab-protocol-form','lab-compare-form','lab-conversation-form','lab-followup-form','lab-rename-form'].includes(form.id)) return;
    event.preventDefault();
    const payload=Object.fromEntries(new FormData(form)), submit=form.querySelector('button[type=submit],button:not([type])');
    if (submit) submit.disabled=true;
    try {
      if (form.id==='lab-create-form') {
        if (!payload.target_venue.trim()) delete payload.target_venue;
        await api('fastresearch/projects',{method:'POST',body:JSON.stringify(payload)});
        $('#detail-dialog').close();location.hash=route(payload.project_id,{origin:'fastresearch'});toast('研究课题已创建');
      } else if (form.id==='lab-protocol-form') {
        payload.expected_revision=current.doc.freshness.project_revision;
        payload.training_free=form.elements.training_free.checked;
        for (const key of ['budget_calls','budget_tokens','vram_gib']) payload[key]=Number(payload[key]);
        payload.storage_gib=payload.storage_gib.trim() ? Number(payload.storage_gib) : null;
        const data=await api(basePath(current)+'/protocols',{method:'POST',body:JSON.stringify(payload)});
        $('#detail-dialog').close();location.hash=route(current.project,{origin:current.origin,view:'run-stage-explorer',run_id:data.run_id});toast('待执行协议已登记');
      } else if (form.id==='lab-compare-form') {
        if (payload.baseline_run_id===payload.candidate_run_id) throw new Error('请选择两个不同的运行');
        location.hash=route(current.project,{origin:current.origin,view:'run-comparison',...payload});
      } else if (['lab-conversation-form','lab-followup-form'].includes(form.id)) {
        const snapshot=current.intents.snapshot;
        const request={quick_catalog_fingerprint:current.intents.fingerprint,intent_request:{schema_version:'1.0',kind:'free_question',project_id:current.project,snapshot_revision:snapshot.snapshot_revision,snapshot_sha256:snapshot.snapshot_sha256,question:payload.question}};
        const followUp=form.id==='lab-followup-form';
        if (followUp) request.context_turn_ids=[current.workspace.latest_turn_id];
        await api(basePath(current)+'/workspaces'+(followUp ? '/'+current.workspace.workspace_id+'/turns' : ''),{method:'POST',body:JSON.stringify(request)});
        $('#detail-dialog').close();await window.render();toast('证据对话已保存');
      } else if (form.id==='lab-rename-form') {
        const request={title:payload.title,expected_title:current.workspace.title,expected_metadata_revision:current.workspace.metadata_revision};
        await api(basePath(current)+'/workspaces/'+current.workspace.workspace_id,{method:'PATCH',body:JSON.stringify(request)});
        $('#detail-dialog').close();await window.render();toast('话题名称已保存');
      }
    } catch (error) { const target=form.querySelector('.lab-form-error'); if(target) target.textContent=error.message; else toast(error.message); }
    finally {if(submit) submit.disabled=false;}
  });
  function deliveryPlan(record) {
    const plan=record.submission_plan;
    if (!plan) return `<section class="panel"><h2>尚未登记交付计划</h2><p>可在完整研究桌面中维护研究阶段；不会从记录数量推断完成状态。</p></section>`;
    const states={pending:'待开展',active:'进行中',blocked:'已阻塞',complete:'已完成',deferred:'已延后'};
    const titles=Object.fromEntries(plan.work_items.map(i=>[i.work_id,i.title]));
    return `<section class="panel"><div class="section-head"><h2>研究交付计划</h2>${tag('r'+plan.plan_revision,'green')}</div><p>${esc(plan.objective)}</p><p class="lab-muted">内部目标 ${esc(plan.internal_deadline_at)} · 计划状态来自项目档案</p><div class="table-wrap"><table class="research-table"><thead><tr><th>任务</th><th>状态 / 依赖</th><th>内部日期</th><th>验收证据</th></tr></thead><tbody>${plan.work_items.map(item=>`<tr data-program-task="${esc(item.work_id)}"><td><strong>${esc(item.title)}</strong></td><td>${tag(states[item.state] || translated(item.state),'blue')}<small>${esc(item.prerequisite_ids.map(id=>titles[id] || id).join(' → ') || '起点')}</small></td><td>${esc(item.due_at.slice(0,10))}</td><td>${item.acceptance.map(a=>`<small>${esc(a)}</small>`).join('')}</td></tr>`).join('')}</tbody></table></div></section>`;
  }
  return {render,resources};
})();

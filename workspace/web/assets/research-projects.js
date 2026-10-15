'use strict';

// Read-only research dossiers join reviewed report evidence to native projects.
// A dossier never creates a run, changes a scientific gate, or starts remote work.
window.ResearchProjects = (() => {
  let data = null;
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text = value => value == null ? '待核实' : Array.isArray(value) ? value.map(text).join('；') : typeof value === 'object' ? String(value.label || value.title || value.summary || value.state || '见来源记录') : String(value);
  const array = value => Array.isArray(value) ? value : [];
  const badge = (label, kind='') => `<span class="tag ${e(kind)}">${e(label)}</span>`;
  const link = (id, values={}) => '#/experiments/' + encodeURIComponent(id) + '?' + new URLSearchParams({origin:'fastresearch', ...(id==='fastresearch-cvpr2027'?{dossier:'reviewed'}:{}), ...values});
  const navs = [['project-introduction','项目简介'],['project-progress','项目进度'],['project-overview','项目记录'],['run-stage-explorer','实验结果'],['data','数据与案例'],['paper-evidence','论文与证据']];
  const nativeNavs = [['plan','研究计划'],['resources','资源配置'],['conversations','研究对话']];
  const panel = (title, body, extra='') => `<section class="panel rp-panel ${extra}"><div class="section-head"><h2>${e(title)}</h2></div>${body}</section>`;
  const empty = message => `<p class="rp-muted rp-empty">${e(message)}</p>`;
  const stateLabels = {passed:'已通过',active:'进行中',planned:'待完成',blocked:'阻塞',failed:'未通过',unknown:'待核实',partial:'局部证据',source_snapshot:'来源快照',complete:'已完成',completed:'已完成',not_started:'未开始',candidate:'候选',stopped:'已停止',paused:'暂停',archived:'归档',parallel_admission:'并行准入',parallel_running_admission:'并行准入中',submitted_pending_update:'已提交 · 待首更新',submitted_pending_prediction:'已提交 · 待首预测',evaluation_running:'评测进行中',training_running:'训练进行中',failed_preserved:'失败已保留',complete_single_arm:'单臂完成',awaiting_window:'等待资源窗口',implementation_admission:'实现验收',evaluation_running_verified_prediction:'评测进行中 · 已有预测',training_running_verified_update:'训练进行中 · 已有有效更新',submitted_pending_actual_evidence:'已提交 · 首产出待核',training_complete_evaluation_pending_prediction:'训练完成 · 待评测预测',evaluation_complete_pending_local_audit:'评测完成 · 待本地验收',process_not_verified:'进程尚未核实',historical_complete:'历史版本已完成',stopped_negative:'负结果版本已停',admission_only:'仅准入 · 未启动',proposal_only:'候选提案 · 未启动'};
  const projectList = () => array(data?.projects);
  const find = id => projectList().find(p => p.project_id === id);
  function exportControls(reportId='all', compact=false) {
    const all=reportId==='all', label=all?'全课题':reportId;
    const buttons=['markdown','zip'].map(format=>`<a class="button ${compact?'button-small':format==='zip'?'primary':''}" href="/api/research/export?${e(new URLSearchParams({format,project:reportId}).toString())}" download data-research-export="${e(format)}" aria-label="下载${e(label)}${format==='zip'?'资料ZIP':'Markdown'}">${all?'全课题 ':''}${format==='zip'?'资料 ZIP':'Markdown'} ↓</a>`).join('');
    if (compact) return `<div class="rp-export-compact" data-export-project="${e(reportId)}"><span>PPT资料</span><div class="actions">${buttons}</div></div>`;
    return panel(all?'导出全部进展 · 制作PPT':'导出课题进展 · 制作PPT',`<p>上传至ChatGPT制作PPT：导出已配置的审阅叙述与项目摘要，不含数据图像、原始响应或凭据。Markdown便于整理讲稿，ZIP包含叙述和摘要JSON。</p><div class="actions" data-export-project="${e(reportId)}">${buttons}</div>`,'rp-export-panel');
  }
  const liveRace = p => p.shared_race?.current ? p.shared_race : null;
  function projectStatus(p) {
    const armId = p.race_arm_id;
    const arm = liveRace(p) && array(p.shared_race.arms).find(a=>a.id===armId);
    return arm?.state ? `${text(arm.name || arm.label || arm.id)} · ${stateLabels[arm.state] || arm.state}` : p.status_label || '研究证据待完善';
  }
  function raceSnapshot(p, compact=false) {
    const r=liveRace(p);
    if (!r) return '';
    return `<div class="rp-live-snapshot ${compact?'rp-live-card':''}" data-research-live="${e(p.project_id)}"><strong>共享赛马 · 当前快照</strong><p>${e(text(r.current))}</p>${compact?'':'<small>读取共享赛马最近收据；运行进度与研究证据分别保留，完整评分及结论仍以验收为准。</small>'}</div>`;
  }

  async function load() {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const r = await fetch('/api/research/projects', {cache:'no-cache', signal:controller.signal});
      if (!r.ok) throw new Error('研究档案暂时不可读；原生项目仍可使用');
      const value = await r.json();
      if (value.schema_version !== 1 || !Array.isArray(value.projects) || value.projects.some(p => !p?.project_id) || new Set(value.projects.map(p=>p.project_id)).size !== value.projects.length) throw new Error('研究档案格式不完整；原生项目仍可使用');
      data = value;
      return value;
    } catch (error) {
      data = null;
      if (error.name === 'AbortError') throw new Error('研究档案读取超时；原生项目仍可使用');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function sources(p, keys, label='原始证据附件') {
    const wanted = [...new Set(array(keys))], records = array(p.sources);
    if (!wanted.length) return '';
    return `<details class="rp-attachments"><summary>${e(label)} · ${wanted.length}项</summary><p class="rp-muted">附件供逐项核查。方法、配置与结果以上方结构化说明为准。</p><div class="rp-source-buttons">${wanted.map(key => {
      const s = records.find(x => x.key === key);
      return s?.available === false || s?.browser_readable === false ? `<span class="rp-muted">${e(s.role || key)} · ${s.available===false?'来源缺失':'附件未接入网页，保留元数据'}</span>` : `<button class="button button-small" data-progress-source="${e(key)}">${e(s?.role || key)}</button>`;
    }).join('')}</div></details>`;
  }
  function rows(values) {
    const pairs = array(values).filter(row => Array.isArray(row) && row.length >= 2);
    return pairs.length ? `<dl class="rp-config">${pairs.map(([label,value]) => `<div><dt>${e(label)}</dt><dd>${e(text(value))}</dd></div>`).join('')}</dl>` : empty('该项配置尚未在来源中核实。');
  }
  function list(values, cls='') {
    return array(values).length ? `<ul class="rp-list ${e(cls)}">${values.map(v=>`<li>${e(text(v))}</li>`).join('')}</ul>` : '';
  }
  function note(title, value, boundary=false) {
    return `<div class="rp-note ${boundary?'rp-boundary':''}"><strong>${e(title)}</strong><p>${e(text(value))}</p></div>`;
  }
  function safeHref(raw) {
    try {
      const u = new URL(raw, location.origin);
      if (['https:','http:'].includes(u.protocol)) return u.href;
    } catch (_) {}
    return null;
  }
  function inline(raw) {
    // Escape before adding the small supported Markdown vocabulary. No raw HTML.
    const tokens = [];
    const masked = String(raw ?? '').replace(/`([^`]+)`|\[([^\]]+)\]\(([^\s)]+)\)/g, (match,code,label,url) => {
      const href = url ? safeHref(url) : null;
      tokens.push(code != null ? `<code>${e(code)}</code>` : href ? `<a href="${e(href)}" target="_blank" rel="noopener">${e(label)}</a>` : e(label));
      return '\u0000'+(tokens.length-1)+'\u0000';
    });
    return e(masked).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\u0000(\d+)\u0000/g,(_,i)=>tokens[Number(i)]);
  }
  function markdown(value) {
    const lines = String(value ?? '').split(/\r?\n/), output = [];
    let i=0;
    while (i<lines.length) {
      const line=lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^```/.test(line)) {
        const block=[]; i++;
        while (i<lines.length && !/^```/.test(lines[i])) block.push(lines[i++]);
        i++; output.push(`<pre class="rp-code"><code>${e(block.join('\n'))}</code></pre>`); continue;
      }
      if (/^\s*\|/.test(line) && i+1<lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i+1])) {
        const split = s => s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
        const header=split(line), body=[]; i+=2;
        while (i<lines.length && /^\s*\|/.test(lines[i])) body.push(split(lines[i++]));
        output.push(`<div class="table-wrap"><table class="research-table rp-table"><thead><tr>${header.map(c=>`<th scope="col">${inline(c)}</th>`).join('')}</tr></thead><tbody>${body.map(r=>`<tr>${header.map((_,n)=>`<td>${inline(r[n]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
      }
      const heading=line.match(/^#{1,6}\s+(.+)/);
      if (heading) { output.push(`<h3>${inline(heading[1])}</h3>`); i++; continue; }
      if (/^\s*(?:[-*]|\d+[.)])\s+/.test(line)) {
        const items=[];
        while (i<lines.length && /^\s*(?:[-*]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*(?:[-*]|\d+[.)])\s+/,''));
        output.push(`<ul>${items.map(s=>`<li>${inline(s)}</li>`).join('')}</ul>`); continue;
      }
      const paragraph=[];
      while (i<lines.length && lines[i].trim() && (i===0 || !/^#{1,6}\s|^```|^\s*(?:[-*]|\d+[.)])\s+/.test(lines[i]))) paragraph.push(lines[i++]);
      if (!paragraph.length) paragraph.push(lines[i++]);
      output.push(`<p>${inline(paragraph.join('\n')).replace(/\n/g,'<br>')}</p>`);
    }
    return `<div class="rp-prose">${output.join('')}</div>`;
  }
  function axes(p) {
    return Object.keys(p.axis_states || {}).length ? `<ol class="rp-axes" aria-label="研究证据进展">${Object.entries(p.axis_states).map(([axis,state])=>`<li class="rp-axis-${e(state)}"><span></span><strong>${e(axis)}</strong><small>${e(stateLabels[state] || state)}</small></li>`).join('')}</ol>` : '';
  }
  function methodCatalog(p) {
    return panel('版本配置与方法档案', `<p class="rp-muted">各版本保留自己的模型、训练量、数据划分、评测口径与失败边界。候选方案与已执行版本分别标注。</p><div class="rp-method-catalog">${array(p.methods).map(m=>`<a class="rp-method-card" href="${link(p.project_id,{view:'method',version:m.id})}" data-research-method-link="${e(m.id)}"><div>${badge(m.label || m.id)}<span>${e(m.stage || '执行状态待核实')}</span></div><h3>${e(m.title || m.id)}</h3><p>${e(m.model || '模型待核实')}</p>${rows([['训练 / 更新',array(m.training)[0]?.[1] || '见版本配置'],['评测范围',array(m.evaluation)[0]?.[1] || '见版本配置']])}<span class="rp-card-action">配置 · 数据 · 方法 · 评测 <b aria-hidden="true">↗</b></span></a>`).join('')}</div>${!array(p.methods).length?empty('方法档案尚待来源核实。'):''}`);
  }
  function methodPage(p, params) {
    const selected = params.get('version'), m = array(p.methods).find(x=>x.id===selected) || array(p.methods).find(x=>x.id===p.default_version) || array(p.methods)[0];
    if (!m) return methodCatalog(p);
    const tabs=`<nav class="tabs rp-version-tabs" aria-label="方法版本">${p.methods.map(x=>`<a class="tab ${x.id===m.id?'active':''}" ${x.id===m.id?'aria-current="page"':''} href="${link(p.project_id,{view:'method',version:x.id})}">${e(x.label || x.id)}</a>`).join('')}</nav>`;
    return panel('配置与具体方法',`${selected && selected!==m.id?note('版本未接入','该链接版本尚无已核实档案，以下展示首个可读版本。',true):''}${tabs}<div class="rp-version-heading" data-research-method="${e(m.id)}"><div><span class="eyebrow">${e(m.label || m.id)}</span><h3>${e(m.title || m.id)}</h3></div>${badge(m.stage || '执行状态待核实')}</div><p class="rp-model"><b>模型与干预范围：</b>${e(text(m.model))}</p><div class="actions"><a class="button primary" href="${link(p.project_id,{view:'run-stage-explorer',version:m.id})}">查看结果与范围 →</a><a class="button" href="${link(p.project_id,{view:'project-overview'})}">全部版本</a></div>`)
      + panel('训练、更新与资源预算',rows(m.training))
      + panel('评测数据与可比条件',rows(m.evaluation))
      + panel('实现流程',array(m.steps).length?`<ol class="rp-workflow">${m.steps.map(([title,detail],i)=>`<li><span>${String(i+1).padStart(2,'0')}</span><div><h3>${e(title)}</h3><p>${e(detail)}</p></div></li>`).join('')}</ol>`:empty('实现流程尚未核实。'))
      + panel('模型输入与输出',array(m.inputs_outputs).length?`<div class="rp-io">${m.inputs_outputs.map(([label,value])=>`<article><small>${e(label)}</small><p>${e(text(value))}</p></article>`).join('')}</div>`:empty('尚未接入已核实的输入输出说明。'))
      + panel('强对照与版本结论',list(m.controls)+note('本版本结论',m.finding || '尚无可验证结论')+note('边界与未验证部分',m.limits || '需先核实协议与独立性。',true)+sources(p,m.source_keys));
  }
  function resultTable(p, t) {
    const columns=array(t.columns), tableRows=array(t.rows);
    return `<article class="rp-result" data-research-result="${e(t.id)}"><div class="rp-result-head"><h3>${e(t.title)}</h3>${badge(t.evidence_level || '证据范围见协议')}</div><p class="rp-scope">${e(t.scope || '来源尚未明确评测范围')}</p>${columns.length?`<div class="table-wrap"><table class="research-table rp-table"><caption>${e(t.title)}</caption><thead><tr>${columns.map(c=>`<th scope="col">${e(c)}</th>`).join('')}</tr></thead><tbody>${tableRows.map(row=>`<tr>${columns.map((_,i)=>`<${i?'td':'th'} ${i?'':'scope="row"'}>${e(text(array(row)[i]))}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</tbody></table></div>`:empty('尚无已核实数值表。')}${note('结果解释',t.interpretation || '尚未形成可验证结论')}${note('可比边界',t.limits || '需核对数据、版本与预算。',true)}${sources(p,t.source_keys)}</article>`;
  }
  function results(p, params=new URLSearchParams()) {
    const tables=array(p.results), origin=t=>{
      const identity=[t.origin,t.evidence_level].filter(Boolean).join(' ');
      if (/author|literature|published|作者|文献|论文报告/i.test(identity)) return 'author';
      if (/local|measured|development|engineering|independent|benchmark|本地|实测|开发|独立|工程/i.test(identity)) return 'local';
      if (/author|literature|作者|文献|论文报告/i.test(t.scope || '')) return 'author';
      if (/local|本地|远端|synthetic|开发|独立|工程/i.test(t.scope || '')) return 'local';
      return 'unknown';
    };
    return panel('实验结果与来源范围',`<p class="rp-muted">作者报告与本地实验分区保留；不同模型、划分、评分器和预算的数值不能直接合并。版本筛选不隐藏其他结果与负证据。</p>${params.get('version')?note('来源版本',params.get('version')):''}<div class="actions"><a class="button" href="${link(p.project_id,{view:'project-overview'})}">查看对应方法档案 →</a></div>`)
      + panel('本地实验与工程验收',tables.filter(t=>origin(t)==='local').map(t=>resultTable(p,t)).join('') || empty('尚无已核实的本地结果表；不会以文献成绩代替实测。'))
      + panel('作者报告与公开基线',tables.filter(t=>origin(t)==='author').map(t=>resultTable(p,t)).join('') || empty('当前档案尚未接入独立的作者结果表；近邻与来源见项目记录。'))
      + (tables.some(t=>origin(t)==='unknown')?panel('来源汇总 · 范围待核实',tables.filter(t=>origin(t)==='unknown').map(t=>resultTable(p,t)).join('')):'');
  }
  function sharedRace(p) {
    const r=p.shared_race;
    if (!r) return '';
    const branches=array(r.arms || r.branches), controls=array(r.controls || r.shared_controls), nextActions=array(r.next_actions);
    return panel('共享赛马与经验',`<p>${e(text(r.summary || r.objective || r.description || '在同一协议下比较机制，保留跨实现扩展入口。'))}</p>${r.status?badge(stateLabels[r.status] || text(r.status)):''}${r.resource?rows([['共享远端入口',r.resource.endpoint || '待核实'],['访问身份',r.resource.identity_verified?'已核实':'尚未核实'],['可用资源窗口',r.resource.window_verified?'已核实':'尚未核实']]):''}${r.current?note('当前状态',r.current):''}${r.protocol?note('共同协议',r.protocol):''}${branches.length?`<div class="rp-race-arms">${branches.map(b=>`<article><h3>${e(text(b.title || b.name || b.label || b.id || b.branch_id))}</h3>${b.state?badge(stateLabels[b.state] || b.state):''}<p>${e(text(b.summary || b.mechanism || b.hypothesis || b.next_gate || b.status))}</p>${b.stop_condition?note('停止条件',b.stop_condition,true):''}</article>`).join('')}</div>`:''}${list(controls)}${nextActions.length?list(nextActions):''}<div class="actions"><a class="button" href="#/experience">共享经验池 →</a></div>${sources(p,r.source_keys)}`,'rp-shared-race');
  }
  function progress(p) {
    return (liveRace(p)?panel('当前实验进展',raceSnapshot(p),'rp-live-panel'):'')
      + panel('研究问题与当前证据',`<p class="rp-lead">${e(p.summary || p.brief?.intro || '')}</p>${note(liveRace(p)?'研究证据历史':'当前做到',p.current || '进展待核实')}${note('当前主张',p.claim || '尚未形成已验证主张')}${axes(p)}${note('关键证据缺口',p.gap || '见版本与来源边界',true)}<div class="actions"><a class="button primary" href="${link(p.project_id,{view:'project-overview'})}">方法与版本 →</a><a class="button" href="${link(p.project_id,{view:'run-stage-explorer'})}">完整结果 →</a><a class="button" href="${link(p.project_id,{view:'data'})}">数据与案例 →</a></div>`)
      + sharedRace(p)
      + panel('下一步优先级',list(p.next_actions) || empty(p.next || '下一步待核实'));
  }
  function overview(p) {
    return methodCatalog(p)+sharedRace(p)+array(p.brief?.sections).map(s=>panel(s.title || '研究记录',markdown(s.markdown || s.content || ''))).join('');
  }
  function cases(p) {
    const c=p.cases || {};
    const caseFields = pairs => rows(array(pairs).map(([label,value])=>[label,value!==null && typeof value==='object'?JSON.stringify(value,null,2):value]));
    if (array(c.samples).length) {
      const intro=p.introduction || {}, fields=[['研究问题',intro.question],['当前方法',intro.method],['输入 → 输出',intro.input_output],['已有证据与缺口',intro.evidence]].filter(([,v])=>v);
      const datasets=array(c.datasets).map(d=>`<article class="rp-dataset" data-research-dataset="${e(d.id)}"><div class="rp-result-head"><h3>${e(d.title)}</h3>${badge(d.role)}</div>${rows([['划分',d.split],['规模与单位',d.size],['输入',d.inputs],['目标输出',d.target],['标签来源',d.annotation],['评测',d.metric]])}${note('使用边界',d.limits,true)}</article>`).join('');
      const samples=c.samples.map((s,i)=>`<details class="rp-data-case" data-research-case="${e(s.id)}" ${i===0?'open':''}><summary><span>${badge(s.split)}<strong>${e(s.title)}</strong><small>${e(s.description)}</small></span><span class="rp-case-open" aria-hidden="true">展开 ↗</span></summary><div class="rp-case-body"><p class="rp-case-id">原样本ID：${e(s.source_id)}</p><h3>真实输入 · 完整文本</h3>${caseFields(s.inputs)}<h3>原标签与标注来源</h3>${caseFields(s.annotations)}<h3>已有模型输出</h3><div class="table-wrap"><table class="research-table rp-table"><caption>${e(s.title)} · 原预测记录</caption><thead><tr>${s.output_columns.map(x=>`<th scope="col">${e(x)}</th>`).join('')}</tr></thead><tbody>${s.outputs.map(row=>`<tr>${row.map(x=>`<td>${e(text(x))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${note('如何解读',s.limits,true)}<details class="rp-case-provenance"><summary>逐条来源与SHA · ${array(s.provenance).length}项</summary>${array(s.provenance).map(v=>`<p><b>${e(v.role)}</b> · 第${e(v.line_1based)}行<br>${e(v.path)}<br>记录：${e(v.record_id)}<br>SHA256：${e(v.sha256)}</p>`).join('')}</details></div></details>`).join('');
      return (fields.length?panel('先了解这项研究',rows(fields)):'')
        + panel(`真实数据样例 · ${c.samples.length}例`,note('取样方式',c.selection_policy)+note('样例的证据范围',c.limits,true)+`<p class="rp-muted">展开任一样例查看问题、参考、候选全文、原标签及已有预测；来源细节可继续展开。样例随本课题Markdown和ZIP一起导出。</p><div class="rp-case-list">${samples}</div><small class="rp-muted">样例审阅：${e(c.reviewed_at)}</small>`)
        + panel('数据来源与任务',`<p class="rp-lead">${e(c.summary)}</p><div class="rp-datasets">${datasets}</div>${sources(p,c.source_keys)}`);
    }
    return panel('数据、真实输入输出与案例',note('真实案例接入状态',c.available?'已有案例来源；当前尚无逐例可视化适配器。':c.reason || '尚未接入已审阅的真实逐例输入、输出或可视化资产。',true)+`<p class="rp-muted">数据集、划分、训练量与评测范围在对应方法页逐项列出。下方为实际来源配置说明，格式说明不代表逐例模型预测。</p><div class="actions"><a class="button primary" href="${link(p.project_id,{view:'project-overview'})}">查看数据与版本配置 →</a></div>${sources(p,c.source_keys)}`)
      + array(p.methods).map(m=>panel((m.label || m.id)+' · 数据与输入输出',`<h3>训练与资源</h3>${rows(m.training)}<h3>评测数据与范围</h3>${rows(m.evaluation)}<h3>接口说明</h3>${rows(m.inputs_outputs)}${sources(p,m.source_keys)}`)).join('');
  }
  function evidence(p) {
    return panel('论文主张与证据边界',note('当前可主张范围',p.claim || '尚未形成已验证主张')+note('尚未补齐',p.gap || '请核对来源与科学验收门。',true)+list(p.next_actions)+`<div class="actions"><a class="button" href="${link(p.project_id,{view:'run-stage-explorer'})}">结果与负证据 →</a><a class="button" href="#/progress?project=${encodeURIComponent(p.report_id)}">整体研究进展 ↗</a></div>`)
      + panel('来源索引与核查时间',`<p class="rp-muted">档案只投影已整理的研究说明与汇总。源修改时间、档案复核时间与页面读取时间各自保留；刷新页面不等于复核科研结论。未接入网页的代码、逐例记录和其他文件仅保留路径与校验值。</p><div class="rp-source-index">${array(p.sources).map(s=>`<article><div><strong>${e(s.role || s.key)}</strong>${s.available===false?badge('来源缺失'):s.browser_readable===false?badge('元数据 · 附件未接入'):s.changed_since_report?badge('较报告索引有变化','amber'):badge('来源索引')}</div><small>${e(s.path)}</small><small>源修改 ${e(s.modified_at || '待核实')}</small><code>SHA256 ${e(s.sha256 || '待核实')}</code>${s.available===false || s.browser_readable===false?'':`<button class="button button-small" data-progress-source="${e(s.key)}">查看原始证据</button>`}</article>`).join('')}</div>`);
  }
  function card(record) {
    const p=find(record.project_id);
    if (!p) return null;
    const isTrainingFree=p.project_id==='fastresearch-cvpr2027', mainLink=isTrainingFree?'#/experiments/fastresearch-cvpr2027':link(p.project_id);
    return `<article class="card rp-project-card" data-lab-project="${e(p.project_id)}" data-research-report="${e(p.report_id)}"><div class="card-top">${badge(projectStatus(p),'blue')}<span class="card-id">${e(p.report_id)}</span></div><h3><a href="${mainLink}">${e(p.title)}</a></h3>${raceSnapshot(p,true)}<p class="description clamp-three">${e(p.summary || '')}</p>${liveRace(p)?`<details class="rp-card-history"><summary>研究证据历史</summary><p>${e(p.current || '待核实')}</p></details>`:`<div class="rp-card-current"><small>当前做到</small><p>${e(p.current || '待核实')}</p></div>`}<div class="tags">${badge(array(p.methods).length+' 个方法档案')}${badge(array(p.results).length+' 组来源结果')}${badge(p.cases?.available?'案例来源已登记':'真实案例待接入')}</div>${isTrainingFree?`<div class="actions rp-card-entries"><a class="button button-small" href="${mainLink}">分支实验工作区 →</a><a class="button button-small" href="${link(p.project_id,{view:'project-overview'})}">研究简报 / 版本档案 →</a></div>`:''}<div class="card-foot"><span>${record.native_available===false?'只读证据档案':'原生计划＋证据档案'}</span><a href="${mainLink}">打开研究 →</a></div></article>`;
  }
  async function render(id, params, options={}) {
    const p=find(id);
    if (!p) throw new Error('该研究的结构化档案尚未接入');
    const method=params.get('view')==='method', pane=method?'project-overview':params.get('view')==='cases'?'data':navs.some(([key])=>key===params.get('view'))?params.get('view'):'project-progress';
    const nativeAvailable=options.nativeAvailable ?? p.native_available ?? false;
    const tabs=[...navs,...(nativeAvailable?nativeNavs:[])];
    const content=pane==='project-introduction'?await window.ResearchIntroduction.render(id,p.cases):method?methodPage(p,params):pane==='project-overview'?overview(p):pane==='run-stage-explorer'?results(p,params):pane==='data'?cases(p):pane==='paper-evidence'?evidence(p):progress(p);
    return `<div class="rp-dossier" data-research-project="${e(p.project_id)}" data-research-view="${e(method?'method':pane)}"><a class="back-link" href="#/experiments">← 全部课题</a><div class="page-title"><div><h1>${e(p.title)}</h1><p>${e(p.subtitle || '')}</p></div>${badge(projectStatus(p),'blue')}</div><nav class="tabs lab-tabs" aria-label="研究课题工作区">${tabs.map(([key,label])=>`<a class="tab ${pane===key?'active':''}" ${pane===key?'aria-current="page"':''} href="${link(id,{view:key})}">${e(label)}</a>`).join('')}</nav><div class="rp-provenance"><span>内容复核 ${e(p.reviewed_at || '待核实')}</span><span>${e(p.source_time_note || '来源时间不等于当前运行状态')}</span><a href="#/progress?project=${encodeURIComponent(p.report_id)}">整体研究进展 ↗</a>${nativeAvailable?`<a href="/studio/#/projects/${encodeURIComponent(id)}?lang=zh-CN">完整研究桌面 ↗</a>`:badge('只读证据档案')}</div>${content}</div>`;
  }
  return {load, projects:projectList, card, has:id=>Boolean(find(id)), render, exportControls};
})();

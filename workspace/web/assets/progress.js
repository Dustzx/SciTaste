'use strict';
window.FastResearchProgress = (() => {
  const e = v => String(v ?? '未知').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const projectName = id => id === 'FastResearch' ? 'SciTaste · 视觉研究' : id;
  const statuses={completed_baseline:'原图基线完成',stopped_headroom:'基线饱和已停止',completed_scored:'开发评分完成',completed_recovery_predictions:'恢复预测已完成',completed_diagnostic_predictions:'归因预测已完成',completed_predictions:'预测已完成',checkpoint_predictions:'阶段预测已完成',held_process_disappeared:'中断已保留',held_execution_failure:'执行失败暂停',held_format_truncation:'格式截断，已保留',running:'源记录运行中'};
  const armNames={direct:'直接推理',review:'推理复核',structure:'结构重解',pixel_match:'像素匹配',full_structure_replay:'完整结构摘要',answer_blind_structure:'去预填摘要',state_table:'状态表对照',state_invalidation:'依赖失效标记',crop_plain:'普通裁剪',crop_linked:'原图对应裁剪',crop_shuffled:'错位对应诊断',transform_vote:'全图变换投票',partition_sum:'三分区求和',conservation_decode:'区域守恒纠错',class_count_only:'类别文字计数',exemplar_count_only:'官方视觉示例计数',whole_review:'全图四轮视觉复核',whole_first:'全图首轮低预算',tile_scalar:'普通裁剪标量计数',halo_scalar:'上下文裁剪标量计数',tile_points:'普通裁剪点计数',halo_points:'上下文点归属',halo_unfiltered:'上下文点不作归属',halo_stitch:'常规跨裁剪点合并',countingdino:'CountingDINO视觉参考',fragment_center:'裁剪片段中心',instance_center:'全图实例中心',instance_scalar:'实例中心标量',legacy_halo_points:'旧上下文点归属',legacy_whole_review:'旧全图四轮复核',tile_points_unit:'示例单位校准（普通点）',halo_points_unit:'示例单位校准（上下文点）'};
  const metric = s => !s ? '待评分' : [Number.isFinite(s.score_mean) ? (100*s.score_mean).toFixed(2)+'%' : null, Number.isFinite(s.mae_valid_only) ? 'MAE '+s.mae_valid_only.toFixed(2) : null].filter(Boolean).join(' · ') || '无可用指标';
  const labels = {passed:'已过门', active:'推进中', blocked:'证据缺口', planned:'待执行', unknown:'未核实'};
  const source = (key, title='查看证据') => `<button class="button button-small" data-progress-source="${e(key)}">${e(title)}</button>`;
  async function load() {
    const response = await fetch('/api/progress', {cache:'no-cache'});
    if (!response.ok) throw new Error('进度资料读取失败');
    const d=await response.json();window.progressDocumentLinks=d.document_links||{};return d;
  }
  function narrative(content, path, links={}) {
    const inline = text => {
      const tokens=[];
      const token=html=>{tokens.push(html);return '\u0001'+(tokens.length-1)+'\u0002';};
      let raw=text.replace(/`([^`]+)`/g,(_,code)=>token('<code>'+e(code)+'</code>'));
      raw=raw.replace(/\[([^\]]+)\]\(([^\s)]+)\)/g,(_,label,url)=>{
        if (/^https?:\/\//i.test(url)) return token(`<a href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(label)} ↗</a>`);
        if (/^[a-z][a-z0-9+.-]*:/i.test(url)||url.startsWith('//')) return token(e(label));
        const target=new URL(url,'http://local'+path).pathname;
        return token(links[target]?source(links[target],label):`<span title="${e(url)}">${e(label)}</span>`);
      });
      return e(raw).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\u0001(\d+)\u0002/g,(_,n)=>tokens[Number(n)]);
    };
    const lines=content.split('\n');let out='',i=0;
    const cells=l=>l.replace(/\\\|/g,'\u0003').trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim().replace(/\u0003/g,'|'));
    while(i<lines.length){
      let l=lines[i];if(!l.trim()){i++;continue;}
      if(l.startsWith('```')){const code=[];i++;while(i<lines.length&&!lines[i].startsWith('```'))code.push(lines[i++]);out+='<pre>'+e(code.join('\n'))+'</pre>';i++;continue;}
      const h=l.match(/^(#{1,6})\s+(.+)/);if(h){out+=`<h4>${inline(h[2])}</h4>`;i++;continue;}
      if(l.includes('|')&&/^[\s|:-]+$/.test(lines[i+1]||'')&&(lines[i+1]||'').includes('---')){
        out+='<div class="table-wrap"><table><thead><tr>'+cells(l).map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>';i+=2;
        while(i<lines.length&&lines[i].trim().startsWith('|'))out+='<tr>'+cells(lines[i++]).map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>';
        out+='</tbody></table></div>';continue;
      }
      if(/^\s*[-*]\s+/.test(l)){out+='<ul>';while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i]))out+='<li>'+inline(lines[i++].replace(/^\s*[-*]\s+/,''))+'</li>';out+='</ul>';continue;}
      if(/^\d+\.\s+/.test(l)){out+='<ol>';while(i<lines.length&&/^\d+\.\s+/.test(lines[i]))out+='<li>'+inline(lines[i++].replace(/^\d+\.\s+/,''))+'</li>';out+='</ol>';continue;}
      out+='<p>'+inline(l.replace(/^>\s*/,''))+'</p>';i++;
    }
    return out;
  }
  function projectCards(d, q, selected) {
    return d.projects.filter(p=>!q||JSON.stringify(p).toLowerCase().includes(q)).map(p=>{
      const b=p.brief||{}, sections=b.sections||[];
      const sectionHtml=sections.map(s=>`<details class="brief-section" ${selected&&/^4[.、\s]/.test(s.title)?'open':''}><summary>${e(s.title)}${s.tables?`<span>${s.tables} 张表</span>`:''}</summary><div class="brief-content">${narrative(s.markdown,b.path,d.document_links)}</div></details>`).join('');
      return `<article class="panel progress-project" data-project="${e(p.id)}"><div class="section-head"><div><h2><a href="#/progress?project=${encodeURIComponent(p.id)}">${e(p.id==='FastResearch'?'SciTaste · 视觉研究':p.id)}</a></h2><p>${e(p.lane)}</p></div><span class="tag ${p.verification==='local_verified'?'blue':''}">${p.verification==='local_verified'?'本机已核查':'来源快照'}</span></div><div class="project-current"><small>当前做到</small><p>${e(b.current||p.status)}</p></div><p class="project-claim"><b>创新候选：</b>${e(b.claim||'见项目简报；尚未形成已验证主张')}</p><ol class="progress-axis" aria-label="${e(p.id)}整体证据进展">${d.axes.map(a=>`<li class="axis-${e(p.axis_states[a]||'unknown')}"><span class="axis-dot"></span><strong>${e(a)}</strong><small>${e(labels[p.axis_states[a]]||'未核实')}</small></li>`).join('')}</ol><p><b>关键缺口：</b>${e(p.gap)}</p><p><b>下一步：</b>${e(b.next_summary||p.next)}</p>${p.id==='FastResearch'?'<a class="button button-small" href="#/race">查看 training-free 分支赛马 →</a>':''}${p.id==='VOA'?'<a class="button button-small" href="#/experiments/voa">VOA版本结果与可视化 →</a>':''}<div class="project-brief">${sectionHtml}</div><div class="card-foot"><small>简报更新 ${e(b.modified_at)}<br>轴线复核 ${e(p.reviewed_at)}</small>${source(p.id+'.report','完整简报')}</div>${p.report_changed?'<p class="progress-notice">源记录较简报索引有变化，待研究结论复核；上方详细内容已读取本地最新简报。</p>':''}<details><summary>来源与时效</summary><p>${e(b.intro||'')}</p>${p.sources.map(s=>`<div class="progress-source"><span>${e(s.role)} · ${e(s.modified_at)}${s.changed_since_report?' · 已变化':''}</span>${s.available?source(s.key):'<span>来源缺失</span>'}</div>`).join('')}</details></article>`;
    }).join('');
  }
  const branchStates={mechanism_design:'机制设计',source_review:'来源审核',baseline_screen:'基线筛选',development:'开发对照',independent:'独立开发复验',confirmation:'冻结确认',stopped:'停止此版本',saturated:'基线饱和',archived:'历史归档'};
  function raceBoard(d, compact=false) {
    const r=d.portfolio||{}, branches=r.branches||[];
    if (!branches.length) return '<section class="panel race-summary"><h2>尚无分支赛马记录</h2><p>从研究课题登记候选假设、证据与晋级条件，保留完整的正负结果。</p><a class="button" href="#/experiments">打开研究课题 →</a></section>';
    return `<section class="panel race-summary"><div class="section-head"><div><h2>Training-free 分支赛马</h2><p>${e(r.objective)}</p></div><span class="tag">${branches.filter(b=>!['stopped','saturated','archived'].includes(b.stage)).length} 条候选线</span></div><p>${e(r.execution_policy)}</p><div class="race-stages">${(r.gates||[]).map((g,i)=>`<div><span>${i+1}</span><strong>${e(g.name)}</strong><p>${e(g.requirement)}</p></div>`).join('')}</div>${compact?'<a class="button" href="#/race">展开所有分支、预算和晋级条件 →</a>':`<div class="race-branches">${branches.map(b=>`<article class="race-branch"><div class="section-head"><div><small>${e(b.id)} · 优先级 ${e(b.priority??'历史')}</small><h3>${e(b.name)}</h3></div><span class="tag ${b.stage==='stopped'?'amber':'blue'}">${e(branchStates[b.stage]||b.stage)}</span></div><p><b>任务：</b>${e(b.benchmark)} · ${e(b.model)}</p><p><b>可提升空间：</b>${e(b.headroom)}</p><p><b>当前证据：</b>${e(b.evidence_summary)}</p><p><b>下一判别：</b>${e(b.next_action)}</p><p><b>晋级门：</b>${e(b.promotion_rule)}</p><p class="muted">${e(b.compute_state)} · ${e(b.budget_note)}</p><div class="tags">${(b.lesson_ids||[]).map(id=>`<a class="tag" href="#/experience?q=${encodeURIComponent(id)}">${e(id)}</a>`).join('')}</div></article>`).join('')}</div><details open><summary>扩展与数据使用约定</summary>${(r.expansion_rules||[]).map(x=>`<p>${e(x)}</p>`).join('')}</details>`}<p class="muted">来源核查 ${e(r.reviewed_at)} · 分支晋级依据冻结实验；计划不代表任务已经运行。</p></section>`;
  }
  async function race(){const d=await load();return `<div class="page-title"><div><h1>分支赛马与扩展</h1><p>在当前强模型上筛空间，按独立证据分配下一阶段预算。</p></div><a class="button" href="#/progress?project=FastResearch">SciTaste 视觉研究 →</a></div>${raceBoard(d)}`;}
  function experiments(d, project, q) {
    const rows = d.experiments.filter(x => (!project || x.project===project) && (!q || JSON.stringify(x).toLowerCase().includes(q)));
    return `<div class="section-head"><h2>实验与分支 <span class="muted">${rows.length}</span></h2></div><div class="progress-experiments">${rows.map(x => `<article class="panel"><div class="section-head"><div><span class="card-id">${e(projectName(x.project))}</span><h3>${e(x.name)}</h3></div><span class="tag ${x.live?'green':x.stale_running?'amber':''}">${e(x.live?'本机运行中':x.stale_running?'进程已退出，待处理':(statuses[x.status] || x.status))}</span></div><p>${e(x.protocol)}</p><p>${e(x.finding)}</p>${x.completed!=null?`<p><b>${e(x.completion_label || '完整配对')}：</b>${e(x.completed)} / ${e(x.planned)} 题；${e(x.updated_at)}</p>`:''}${x.requests?`<p class="muted">本次请求 ${x.requests.attempts} · 成功 ${x.requests.successful} · 未结算 ${x.requests.unsettled} · 自动重试 ${x.requests.retries}</p>`:''}${x.arms?`<div class="table-wrap"><table><thead><tr><th>对照</th><th>预测</th><th>开发指标</th><th>有效回答</th></tr></thead><tbody>${x.arms.map(a => `<tr><td>${e(armNames[a.arm] || a.arm)}</td><td>${a.predictions}</td><td>${e(metric(a.score))}</td><td>${a.score?`${a.score.valid}/${a.score.n}`:'待评分'}</td></tr>`).join('')}</tbody></table></div>`:''}<div class="card-foot"><small>${x.verification==='report_snapshot'?'来源简报快照；未查询远端':'本机进程与落盘产物；开发结果'}</small>${source(x.source_key)}</div></article>`).join('') || '<p class="muted">没有符合条件的实验</p>'}</div>`;
  }
  async function progress(params) {
    const d = await load(), p=params.get('project') || '', q=(params.get('q') || '').toLowerCase();
    const shown = {...d,projects:d.projects.filter(x=>!p || x.id===p)};
    const b=d.budget;
    if (!d.projects.length) return '<div class="page-title"><div><h1>研究进展</h1><p>项目证据、开发对照与独立确认</p></div></div><section class="panel"><h2>尚无本地项目汇报</h2><p>可先创建研究课题，或按部署文档接入已有的本地汇报目录。</p><a class="button" href="#/experiments">创建或查看课题 →</a></section>' + raceBoard(d,true);
    return `<div class="page-title"><div><h1>研究进展</h1><p>问题与协议 → 实现准入 → 开发对照 → 独立确认 → 机制与稿件</p></div><div class="actions"><a class="button" href="#/race">分支赛马 →</a><a class="button" href="#/experience">共享经验池 →</a></div></div><section class="panel"><p>${e(d.verification_policy)}</p><p>轴线表示证据门槛，不是工时完成百分比；开发提分、独立确认与投稿就绪分别判定。</p><div class="tags"><span class="tag">新论文预算 ¥${e(b.cap_cny)}</span><span class="tag">已结算公开价估算 ¥${Number(b.estimated_settled_cny || 0).toFixed(3)}</span><span class="tag amber">未结算请求预留 ¥${Number(b.unresolved_reserved_cny || 0).toFixed(3)}</span><span class="tag">保守累计 ¥${Number(b.conservative_total_cny || 0).toFixed(3)}</span></div><small>本地读取 ${e(d.generated_at)}；费用不是实际账单。</small></section><div class="toolbar"><select data-filter="project" aria-label="项目"><option value="">全部项目</option>${d.projects.map(x=>`<option value="${e(x.id)}" ${p===x.id?'selected':''}>${e(projectName(x.id))}</option>`).join('')}</select><input data-filter="q" type="search" aria-label="页面搜索" placeholder="搜索项目、实验、阻塞项…" value="${e(q)}"></div><div class="grid-two">${projectCards(shown,q,p)}</div>${!p||p==='FastResearch'?raceBoard(d,true):''}<details class="experiment-archive"><summary>实验条目与原始记录（含停止分支）</summary>${experiments(d,p,q)}</details>`;
  }
  async function experience(params) {
    const d=await load(), q=(params.get('q') || '').toLowerCase(), project=params.get('project') || '';
    const rows=d.experiences.filter(x=>(!q || JSON.stringify(x).toLowerCase().includes(q)) && (!project || x.project===project));
    return `<div class="page-title"><div><h1>共享经验池</h1><p>触发条件、实际证据、可采取的动作与适用限制放在一起；跨项目迁移需另行验证。</p></div><a class="button" href="#/progress">研究进展 →</a></div><div class="toolbar"><input data-filter="q" type="search" aria-label="页面搜索" placeholder="搜索 LoRA、费用、数据质量…" value="${e(q)}"><select data-filter="project" aria-label="经验来源项目"><option value="">全部项目</option>${[...new Set(d.experiences.map(x=>x.project))].map(p=>`<option ${p===project?'selected':''} value="${e(p)}">${e(projectName(p))}</option>`).join('')}</select><span>${rows.length} 条经验</span></div><div class="grid-two">${rows.map(x=>`<article class="panel"><span class="card-id">${e(x.id)} · ${e(projectName(x.project))}</span><h2>${e(x.title)}</h2><div class="tags">${x.tags.map(t=>`<span class="tag">${e(t)}</span>`).join('')}</div><p><b>触发条件：</b>${e(x.trigger)}</p><p><b>建议动作：</b>${e(x.action)}</p><p><b>实测观察：</b>${e(x.observation)}</p><p class="progress-notice"><b>限制：</b>${e(x.limits)}</p><p><b>迁移范围：</b>${e(x.transfer)}</p><div class="progress-evidence">${x.evidence.map(s=>`${source(s.source_key,s.locator)}<small>${e(s.modified_at)}</small>`).join('')}</div><small>维护 ${e(x.reviewed_at)} · ${e({supported_in_scope:'本范围有实证',operational:'运行规则',measured_negative:'本范围实测负结果',protocol_lesson:'可比性约定',hypothesis_with_exploratory_signal:'探索信号 · 待独立验证',policy_proposal:'执行约定 · 尚无普遍收益证明'}[x.status] || x.status)}</small></article>`).join('')}</div>`;
  }
  document.addEventListener('click', async ev => {
    const b=ev.target.closest('[data-progress-source]');if(!b)return;
    try {
      const r=await fetch('/api/progress/source?key='+encodeURIComponent(b.dataset.progressSource));
      if(!r.ok)throw new Error('证据尚未生成或不在可读范围');
      const d=await r.json();document.querySelector('#dialog-title').textContent='原始证据';
      document.querySelector('#dialog-body').innerHTML=`<p class="progress-path">${e(d.path)}</p><p>更新 ${e(d.modified_at)}</p>${d.path.endsWith('.md')?`<div class="brief-content">${narrative(d.content,d.path,window.progressDocumentLinks||{})}</div><details><summary>原文与校验值</summary><small>${e(d.sha256)}</small><pre class="progress-document">${e(d.content)}</pre></details>`:`<pre class="progress-document">${e(d.content)}</pre>`}`;
      const dialog=document.querySelector('#detail-dialog');if(!dialog.open)dialog.showModal();
    }catch(err){ document.querySelector('#toast').textContent=err.message;document.querySelector('#toast').hidden=false;setTimeout(()=>document.querySelector('#toast').hidden=true,3500); }
  });
  return {progress,experience,race};
})();

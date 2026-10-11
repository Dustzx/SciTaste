'use strict';

window.SciTasteProgram = (() => {
  let cached, revision;
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem('scitaste.venue_shortlist') || '[]'); } catch (_) {}
  if (!Array.isArray(saved)) saved = [];
  const labels = {upcoming:'尚可投稿',unknown:'日期待公布',past:'已截稿',journal:'期刊 · 日期待核'};
  const date = value => value ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)) : '待公布';
  const allDates = edition => (edition?.rounds || []).map(r => r.deadline?.utc).filter(Boolean).sort();

  function edition(venue, year) {
    const list = venue.editions.filter(e => !year || String(e.year) === year);
    const future = list.map(e => ({e, next:allDates(e).find(d => Date.parse(d) > Date.now())})).filter(x => x.next).sort((a,b) => a.next.localeCompare(b.next));
    return future[0]?.e || [...list].sort((a,b) => b.year-a.year)[0];
  }
  function state(venue, current) {
    if (venue.kind === 'journal') return 'journal';
    if (allDates(current).some(d => Date.parse(d) > Date.now())) return 'upcoming';
    if (!current || !current.rounds.length || current.rounds.some(r => !r.deadline?.utc)) return 'unknown';
    return 'past';
  }
  const saveButton = venue => `<button class="icon-button ${saved.includes(venue.id)?'saved':''}" data-program-save="${esc(venue.id)}" aria-label="${saved.includes(venue.id)?'取消关注':'关注投稿目标'} ${esc(venue.abbreviation||venue.name)}" aria-pressed="${saved.includes(venue.id)}">${saved.includes(venue.id)?'★':'☆'}</button>`;

  function timeline(current) {
    if (!current) return '<p class="muted">上游尚无届次与截稿记录。</p>';
    return `<div class="venue-timeline">${current.rounds.map((round,i) => `<div><strong>${esc(round.comment || (current.rounds.length>1?'第 '+(i+1)+' 轮':'论文投稿'))}</strong>${[['abstract_deadline','摘要 / 注册'],['opening','开放投稿'],['deadline','论文截止'],['rebuttal_deadline','回复截止'],['decision_deadline','录用通知']].filter(([key])=>round[key]).map(([key,title]) => `<p><span>${title}</span><time>${esc(date(round[key].utc))}${round[key].utc?' <small>北京时间</small>':''}</time><small>原记录 ${esc(round[key].raw)} · ${esc(round[key].timezone || '时区未公布')}${round[key].parse_issue?' · 需核实':''}</small></p>`).join('')}</div>`).join('') || '<p class="muted">时间待公布</p>'}</div>`;
  }
  function card(v, data, year) {
    const current=edition(v,year), status=state(v,current);
    const next=allDates(current).find(d=>Date.parse(d)>Date.now());
    const days=next?Math.ceil((Date.parse(next)-Date.now())/86400000):null;
    const title=v.abbreviation || v.name;
    return `<article class="panel venue-card" data-venue="${esc(v.id)}"><div class="section-head"><div class="tags">${tag('CCF '+v.rank,v.rank==='A'?'green':'blue')}${tag(v.kind==='journal'?'期刊':'会议')}${tag(labels[status],status==='upcoming'?'green':status==='past'?'':'amber')}</div>${saveButton(v)}</div><h2>${esc(title)}${current?' <small>'+esc(current.year)+'</small>':''}</h2>${v.abbreviation?'<p class="venue-name">'+esc(v.name)+'</p>':''}<p class="lab-muted">${v.categories.map(c=>esc(data.categories[c])).join(' · ')}${v.publisher?' · '+esc(v.publisher):''}</p>${v.kind==='conference'?`<div class="venue-next"><strong>${next?esc(date(next)):'日期'+(status==='past'?'已过':'待公布')}</strong><span>${next?'论文截止 · 北京时间 · 剩余 '+days+' 天':status==='past'?'显示上游最新已记录届次':'未推算下一届日期'}</span></div><p class="lab-muted">${esc(current?.meeting_date||'会期待公布')} · ${esc(current?.place||'地点待公布')}</p><details><summary>各轮次与原始时区</summary>${timeline(current)}</details><div class="card-foot">${external(current?.url,'会议官网')}${external(v.source_url,'CCF-DDL 来源')}</div>`:`<div class="venue-next"><strong>征稿日期待核实</strong><span>常规投稿与专刊分别以期刊官网为准。</span></div><div class="card-foot">${external(v.directory_url,'目录资料')}${external(v.source_url,'CCF 目录镜像')}</div><small class="lab-muted">目录链接可能指向 DBLP；尚未核实投稿系统。</small>`}</article>`;
  }
  async function load() {
    const nextRevision=app?.service?.venues_revision;
    if (!cached || revision!==nextRevision) {
      const response=await fetch('/api/venues',{cache:'no-cache'});
      if (!response.ok) throw new Error('投稿目录暂时不可用，请检查本地来源快照');
      cached=await response.json();revision=nextRevision;
    }
    return cached;
  }
  const planStates={candidate:'候选路线 · 未就绪',paused:'暂停路线 · 不排队',ready:'证据已就绪 · 待交付核验'};
  const checkpointStates={passed:'已完成',active:'推进中',planned:'待执行',blocked:'证据缺口',pending:'待执行',paused:'暂停'};
  const iterationStates={hypotheses_designed_not_admitted:'本轮提案已整理 · 待准入',source_review_and_falsifiable_design:'本轮来源审核与机制提案已整理',completed_review_round:'本轮并行审查已完成'};
  function targetHtml(target, role) {
    if (!target) return `<div class="publication-target"><small>${role}</small><strong>待选定</strong></div>`;
    const title=[target.abbreviation||target.name,target.year].filter(Boolean).join(' ');
    const officialDate=target.kind==='journal'?'常规投稿日期 / 专刊以官网核实':target.deadline_at?`${target.deadline_status==='official'?'官方论文截止':'目录截稿记录'}：${date(target.deadline_at)} · 北京时间`:'官方截稿：待核实，不推算下一届';
    const milestoneLabels={'abstract-registration':'官方摘要 / 注册截止','supplementary-submission':'官方补充材料截止'};
    const milestones=(target.official_milestones||[]).filter(m=>milestoneLabels[m.kind]);
    return `<div class="publication-target" data-plan-venue="${esc(target.venue_id||'')}"><small>${role} · CCF ${esc(target.rank||'待核')} · ${target.kind==='journal'?'期刊':'会议'}</small><strong><a href="${href('program',{q:target.abbreviation||target.name})}">${esc(title)}</a></strong><p>${esc(target.fit||'适配理由待复核')}</p><small>${esc(officialDate)}</small>${milestones.length?`<div class="publication-official-dates">${milestones.map(m=>`<small><b>${milestoneLabels[m.kind]}：</b>${esc(date(m.deadline_at))} · 北京时间</small>`).join('')}</div>`:''}${/^https:\/\//i.test(target.url||'')?external(target.url,'官网核验'):''}${(target.official_sources||[]).filter(s=>/^https:\/\//i.test(s.url||'')).slice(0,1).map(s=>external(s.url,'官方日期来源')).join('')}</div>`;
  }
  function deliveryHtml(reference) {
    if (!reference) return '';
    return `<details class="publication-delivery"><summary>原生周计划引用 · ${reference.internal_deadline_at?esc(date(reference.internal_deadline_at)):'内部目标待核'} · 项目 r${esc(reference.project_revision)}</summary><p>${esc(reference.deadline_note||'共享项目内部目标；不是官方截稿，也不替代分支科学证据。')}</p><p>分支检查点为当前条件性路线；原生周计划内部目标独立保留。</p><small>${esc(reference.project_id)} · ${esc(reference.plan_id)} · 计划 r${esc(reference.plan_revision)} · ${reference.publication_ready?'原生交付标记就绪':'原生交付尚未就绪'}</small>${reference.source_key?`<button class="button button-small" data-progress-source="${esc(reference.source_key)}">查看原生交付记录</button>`:''}</details>`;
  }
  function parallelHtml(iteration) {
    if (!iteration) return '';
    return `<details class="publication-parallel"><summary>${esc(iterationStates[iteration.status]||'并行协作记录')} · ${(iteration.roles||[]).length} 个角色</summary><div class="tags">${(iteration.roles||[]).map(r=>`<span class="tag">${r.branch_id?esc(r.branch_id)+' · ':''}${esc(r.role)}</span>`).join('')}</div><p>${esc(iteration.arbitration)}。付费执行共享 ${esc(iteration.paid_worker_max)} 个 worker，累计上限 ¥${esc(iteration.cumulative_cny_cap)}。</p><small>${esc(iteration.holdout_rule)} ${esc(iteration.continuity)}</small></details>`;
  }
  function publicationCard(branch, gates) {
    const plan=branch.publication_plan||{}, next=(plan.checkpoints||[]).find(c=>c.state!=='passed'), passed=new Set(branch.passed_gates||[]);
    const pending=gates.filter(g=>!passed.has(g.id));
    const checkpoint=c=>`<li><div><strong>${esc(c.title)}</strong><span class="tag">${esc(checkpointStates[c.state]||c.state||'待执行')}</span></div><small>内部检查点 ${c.due_at?esc(date(c.due_at))+' · 北京时间':'待安排'}；不是官方截稿</small><p>${esc(c.acceptance||'验收条件待补充')}</p></li>`;
    return `<article class="publication-route" data-plan-branch="${esc(branch.id)}"><div class="section-head"><div><small>${esc(branch.id)}</small><h3>${esc(branch.name)}</h3></div><span class="tag ${plan.status==='paused'?'amber':plan.status==='ready'?'green':'blue'}">${esc(planStates[plan.status]||'投稿路线待制定')}</span></div><p>${esc(plan.strategy||'按独立证据与同预算强对照确定投稿路线。')}</p><div class="publication-targets">${targetHtml(plan.primary,'主目标')}${(plan.alternatives||[]).map(t=>targetHtml(t,'备选目标')).join('')}</div><p class="publication-readiness"><b>科学证据门：</b>${pending.length?'待通过 '+pending.map(g=>esc(g.name)).join('、'):'赛马证据门已通过；交付完成仍以原生计划为准'}</p><p><b>下一决策：</b>${esc(plan.next_decision||branch.next_action||'待研究复核')}</p>${next?`<p class="publication-next"><b>下一内部检查点：</b>${esc(next.title)} · ${next.due_at?esc(date(next.due_at)):'待安排'}</p>`:''}<details class="publication-checkpoints"><summary>内部检查点与验收条件 · ${(plan.checkpoints||[]).length} 项</summary><ol>${(plan.checkpoints||[]).map(checkpoint).join('')}</ol></details>${deliveryHtml(plan.delivery_reference)}${plan.method_iteration?`<div class="publication-iteration"><small>并行方法迭代 · ${esc(iterationStates[plan.method_iteration.status]||'本轮提案记录 · 非后台运行')}</small><p>${esc(plan.method_iteration.summary||'方法提案需先核基线、预算与独立验证条件。')}</p>${plan.method_iteration.source_key?`<button class="button button-small" data-progress-source="${esc(plan.method_iteration.source_key)}">查看方法迭代证据</button>`:''}</div>`:''}<div class="card-foot"><a class="button button-small" href="#/race?branch=${encodeURIComponent(branch.id)}">查看此分支赛马 →</a><a href="${esc((plan.delivery_url||'').startsWith('#/')?plan.delivery_url:'#/experiments')}">原生交付状态 →</a></div></article>`;
  }
  async function publicationRoutes(params) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),8000);
    try {
      const response=await fetch('/api/progress',{cache:'no-cache',signal:controller.signal});
      if (!response.ok) throw new Error('progress unavailable');
      const d=await response.json(), portfolio=d.portfolio||{}, all=portfolio.branches||[], selected=params.get('branch')||'';
      window.progressDocumentLinks=d.document_links||{};
      const rows=all.filter(b=>!selected||b.id===selected), active=rows.filter(b=>b.publication_plan?.status!=='paused'), paused=rows.filter(b=>b.publication_plan?.status==='paused');
      return `<section class="panel publication-routes"><div class="section-head"><div><h2>分支投稿路线</h2><p>以实验闭环决定主目标、备选与内部检查点。</p></div><a href="#/race">赛马总览 →</a></div><p class="lab-muted">${all.length} 条分支已有路线；${all.filter(b=>b.publication_plan?.status==='paused').length} 条暂停。候选目标不代表投稿就绪；交付状态引用原生 submission_plan，目录星标仅为浏览器收藏。</p>${parallelHtml(portfolio.parallel_iteration)}<div class="tags publication-branch-filter"><a class="tag ${selected?'':'blue'}" href="${href('program',{...Object.fromEntries(params),branch:''})}">全部分支</a>${all.map(b=>`<a class="tag ${selected===b.id?'blue':''}" href="${href('program',{...Object.fromEntries(params),branch:b.id})}">${esc(b.id)}</a>`).join('')}</div>${selected?'<p class="lab-muted">仅聚焦此分支路线；下方 CCF 目录保持原筛选条件。</p>':''}<div class="publication-route-grid">${active.map(b=>publicationCard(b,portfolio.gates||[])).join('')}</div>${paused.length?`<details class="publication-paused" ${selected?'open':''}><summary>暂停与历史投稿路线 · ${paused.length} 条</summary><p>保留适配目标和重开条件；暂停路线不进入实验队列。</p><div class="publication-route-grid">${paused.map(b=>publicationCard(b,portfolio.gates||[])).join('')}</div></details>`:''}${!rows.length?'<p class="muted">没有对应分支；可切回全部分支。</p>':''}</section>`;
    } catch (_) {
      return '<section class="panel publication-routes"><h2>分支投稿路线暂不可用</h2><p>本地进展资料尚未读取成功。下方 CCF A/B 目录仍可浏览和筛选。</p><a href="#/race">打开分支赛马 →</a></section>';
    } finally {clearTimeout(timer);}
  }
  async function render(p) {
    const [d,routes]=await Promise.all([load(),publicationRoutes(p)]), year=p.get('year')||'', q=p.get('q')||'';
    const shortlist=d.venues.filter(v=>saved.includes(v.id));
    const years=[...new Set(d.venues.flatMap(v=>v.editions.map(e=>e.year)))].sort((a,b)=>b-a).map(String);
    let list=d.venues.filter(v=>(!p.get('kind')||v.kind===p.get('kind'))&&(!p.get('rank')||v.rank===p.get('rank'))&&(!p.get('area')||v.categories.includes(p.get('area')))&&(!p.get('saved')||saved.includes(v.id))&&(!year||v.kind==='journal'||v.editions.some(e=>String(e.year)===year))&&(!p.get('window')||state(v,edition(v,year))===p.get('window'))&&(!q||match([v.name,v.abbreviation,v.publisher,v.categories.map(c=>d.categories[c])],q)));
    const sortRank={upcoming:0,journal:1,unknown:2,past:3};
    list.sort((a,b)=>{
      const ea=edition(a,year),eb=edition(b,year),sa=state(a,ea),sb=state(b,eb);
      return sortRank[sa]-sortRank[sb] || (allDates(ea).find(d=>Date.parse(d)>Date.now())||'').localeCompare(allDates(eb).find(d=>Date.parse(d)>Date.now())||'') || a.rank.localeCompare(b.rank) || (a.abbreviation||a.name).localeCompare(b.abbreviation||b.name);
    });
    const size=24,pages=Math.max(1,Math.ceil(list.length/size)),page=Math.max(1,Math.min(Number(p.get('page'))||1,pages));
    const link=number=>{const values=Object.fromEntries(p);values.page=number;return href('program',values);};
    return pageTitle('投稿规划','面向 CCF A/B 类会议与期刊，从研究方向选择目标与时间窗口。',`<a class="button" href="#/experiments">课题与交付计划 →</a>`)
      + routes
      + `<details class="panel scitaste-mission"><summary><strong>SciTaste · Idea Research & Discovery</strong><span>五阶段科研与共享 Taste</span></summary><div class="mission-body"><div class="eyebrow">SCITASTE · SCIENTIFIC TASTE FOR AUTONOMOUS RESEARCH</div><h2>让科研判断贯穿全流程</h2><p>当前重点：Idea Research & Discovery</p><div class="idea-chain"><span>快速检索</span><b>→</b><span>证据综合</span><b>→</b><span>Idea 构造</span><b>→</b><span>Taste 指导优化</span></div><div class="research-stages">${[['01','Idea','当前重点'],['02','Experiment','实验规划与验证'],['03','Writing','论文组织与表达'],['04','Figure','科研图表设计'],['05','Review','批判性评价与改进']].map(([n,t,s])=>`<div><small>${n}</small><strong>${t}</strong><span>${s}</span></div>`).join('')}</div><p class="taste-shared"><b>Shared Scientific Taste</b> · 表示与学习判断原则、指导研究决策、检验跨阶段迁移与有限预算下的有效性。</p></div></details>`
      + `<div class="lab-stats venue-stats">${[['conference_A','A 类会议'],['conference_B','B 类会议'],['journal_A','A 类期刊'],['journal_B','B 类期刊']].map(([key,title])=>`<div><strong>${d.counts[key]||0}</strong><span>${title}</span></div>`).join('')}</div>`
      + `<section class="panel venue-sources"><p>会议接入 ${external(d.sources.conferences.url,'CCF-DDL')}；期刊使用 CCF 第七版（2026）目录镜像。${external(d.sources.journals.official_catalogue_url,'CCF 官方说明')}</p><small>会议快照 ${esc(d.synced_at)} · ${esc(d.sources.conferences.commit.slice(0,12))}；期刊目录更新 ${esc(d.sources.journals.catalogue_updated_on)}。社区截稿记录请在投稿前核会议官网。</small><details><summary>来源与同步方式</summary><p>${esc(d.sources.journals.access_note)}</p><p>网页同步读取本地最新快照；维护命令 <code>python scripts/sync_venues.py --refresh</code> 更新会议数据。期刊目录保留独立版本与 PDF 页码，未核投稿时间。</p></details></section>`
      + `<section class="panel venue-shortlist"><div class="section-head"><h2>关注的投稿目标 <small>${shortlist.length}</small></h2><a href="#/program?saved=1">仅看关注 →</a></div>${shortlist.length?`<div class="tags">${shortlist.map(v=>`<a class="tag" href="${href('program',{q:v.abbreviation||v.name})}">${esc(v.abbreviation||v.name)} · ${v.rank}</a>`).join('')}</div>`:'<p class="muted">点击卡片上的星标关注；目标保存在当前浏览器。</p>'}</section>`
      + filters(selectFilter('kind','类型',[['conference','会议'],['journal','期刊']],p.get('kind'))+selectFilter('rank','等级',['A','B'],p.get('rank'))+selectFilter('area','领域',Object.entries(d.categories),p.get('area'))+selectFilter('window','状态',Object.entries(labels),p.get('window'))+selectFilter('year','会议届次',years,p.get('year'))+searchFilter(q,'搜索会议、期刊、出版社或方向'))
      + `<div class="section-head"><p role="status">符合条件 ${list.length} 个目标 · 第 ${page}/${pages} 页</p><small>按可投稿时间优先；期刊日期单列。</small></div><div class="venue-grid">${list.slice((page-1)*size,page*size).map(v=>card(v,d,year)).join('')||empty('没有符合条件的目标','调整领域、年份或状态筛选。')}</div>`
      + `<nav class="pagination" aria-label="投稿目标分页">${page>1?'<a class="button" href="'+link(page-1)+'">上一页</a>':''}<span>${page} / ${pages}</span>${page<pages?'<a class="button" href="'+link(page+1)+'">下一页</a>':''}</nav>`;
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-program-save]');if(!target)return;
    const id=target.dataset.programSave;saved=saved.includes(id)?saved.filter(x=>x!==id):[...saved,id];
    try { localStorage.setItem('scitaste.venue_shortlist',JSON.stringify(saved)); } catch (_) { toast('浏览器暂时无法保存关注目标'); }
    if(route()[0]==='program')window.dispatchEvent(new HashChangeEvent('hashchange'));
  });
  return {render};
})();

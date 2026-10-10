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
  async function render(p) {
    const d=await load(), year=p.get('year')||'', q=p.get('q')||'';
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

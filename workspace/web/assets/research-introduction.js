/* Source-reviewed explanations shared by all nine research workspaces. */
window.ResearchIntroduction = (() => {
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text = value => Array.isArray(value) ? value.join('；') : typeof value === 'object' && value ? JSON.stringify(value) : value;
  const list = value => `<ul>${(Array.isArray(value)?value:[value]).filter(Boolean).map(x=>`<li>${e(text(x))}</li>`).join('')}</ul>`;
  const source = key => `<button class="button button-small" data-progress-source="${e(key)}">${e(key)}</button>`;
  const section = (id, label, body) => `<section class="panel ri-section" id="ri-${id}"><div class="section-head"><h2>${label}</h2></div>${body}</section>`;
  const asset = url => typeof url === 'string' && /^\/assets\/(?:research-introductions\/[a-z0-9-]+\/[a-z0-9-]+\.(?:svg|png)|projects\/voa\/cases\/[a-z0-9_-]+\.jpg)$/.test(url) ? url : '';
  async function load() {
    const response = await fetch('/api/research/introductions', {cache:'no-cache'});
    if (!response.ok) throw new Error('项目简介暂时不可读');
    const value = await response.json();
    if (value.schema_version !== 1 || !Array.isArray(value.projects)) throw new Error('项目简介格式不完整');
    return value;
  }
  async function render(id, cases) {
    const data = await load();
    const p = data.projects.find(project=>project.project_id===id);
    if (!p) return section('empty','暂无项目简介','<p>尚未配置该项目的审阅资料；未推断实验结果。</p>');
    const route = `#/experiments/${encodeURIComponent(id)}?origin=fastresearch&view=`;
    const diagram = asset(p.diagram.svg_url) ? `<figure class="ri-mechanism"><a href="${e(asset(p.diagram.svg_url))}" target="_blank" rel="noopener" aria-label="打开完整方法示意图"><img src="${e(asset(p.diagram.svg_url))}" alt="${e(p.diagram.caption)}" width="1200" height="640"></a><figcaption><b>方法机制图</b> · ${e(p.diagram.caption)}<br><span>${e(p.diagram.scope)}</span></figcaption></figure><div class="ri-figure-actions"><a class="button button-small" href="${e(asset(p.diagram.svg_url))}" target="_blank" rel="noopener">放大图解 ↗</a><a class="button button-small" href="${e(asset(p.diagram.png_url))}" download="${e(id)}-mechanism.png">下载PPT用PNG</a></div>` : '<p>尚未配置审阅机制图。</p>';
    const motivation = `<div class="ri-motivation">${[['01','问题',p.motivation.problem],['02','影响',p.motivation.consequence],['03','已有观察',p.motivation.observation]].map(([n,label,body])=>`<article><span class="ri-number">${n}</span><h3>${label}</h3><p>${e(body)}</p></article>`).join('')}</div>`;
    const method = `<p class="ri-version">${e(p.method.version)}</p><div class="ri-io"><article><small>输入</small><p>${e(text(p.method.inputs))}</p></article><span aria-hidden="true">→</span><article><small>输出</small><p>${e(text(p.method.outputs))}</p></article></div><div class="ri-steps" role="tablist" aria-label="方法分步说明">${p.method.steps.map((s,i)=>`<button type="button" role="tab" id="ri-step-${i}" aria-controls="ri-detail-${i}" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-ri-step="${i}"><span>${String(i+1).padStart(2,'0')}</span>${e(s.title)}</button>`).join('')}</div>${p.method.steps.map((s,i)=>`<article class="ri-step-detail" id="ri-detail-${i}" role="tabpanel" aria-labelledby="ri-step-${i}" ${i?'hidden':''}><h3>${e(s.title)}</h3><p>${e(s.detail)}</p></article>`).join('')}<details class="ri-controls"><summary>强对照与公平性条件</summary>${list(p.method.controls)}</details>`;
    const related = `<p class="ri-help">逐项区分共同点、候选差异和实际比较完成度。已有机制不能重新包装成创新。</p><div class="ri-related">${p.related_work.map((work,i)=>`<article class="ri-neighbor"><header><span class="ri-number">${String(i+1).padStart(2,'0')}</span><h3>${e(work.name)}</h3></header><p><b>已有方法</b>${e(work.mechanism)}</p><dl><div><dt>已被覆盖</dt><dd>${e(work.shared)}</dd></div><div><dt>本项目的差异</dt><dd>${e(work.difference)}</dd></div><div><dt>比较完成度</dt><dd>${e(work.comparison_status)}</dd></div></dl><details><summary>审阅来源</summary><div class="actions">${work.source_keys.map(source).join('')}</div></details></article>`).join('')}</div>`;
    const idea = `<div class="ri-hypothesis"><small>可检验假设</small><p>${e(p.idea.hypothesis)}</p></div><p><b>核心机制：</b>${e(p.idea.mechanism)}</p><p class="ri-status"><b>当前定位：</b>${e(p.idea.status)}</p><div class="ri-two"><article><h3>研究价值</h3><p>${e(p.idea.why_it_matters)}</p></article><article class="ri-open"><h3>尚未证明</h3>${list(p.idea.not_yet_proven)}</article></div>`;
    const contribution = `<p class="ri-hypothesis">${e(p.contribution.claim)}</p><p class="ri-status"><b>证据阶段：</b>${e(p.contribution.status)}</p><h3>主张成立需要</h3><ol class="ri-gates">${p.contribution.conditions.map((c,i)=>`<li><span>${i+1}</span><p>${e(c)}</p></li>`).join('')}</ol><div class="ri-falsifier"><b>什么结果会推翻它？</b><p>${e(text(p.contribution.falsifier))}</p></div>`;
    const evidence = `<div class="ri-two"><article class="ri-supported"><h3>已有证据</h3>${list(p.evidence.supported)}</article><article class="ri-open"><h3>证据边界</h3>${list(p.evidence.limitations)}</article></div><div class="ri-decision"><small>下一项能改变判断的检查</small><p>${e(text(p.evidence.next_decision))}</p></div><div class="actions"><a class="button button-small" href="${route}project-progress">查看当前进度 →</a><a class="button button-small" href="${route}${id==='fastresearch-cvpr2027'?'results':'run-stage-explorer'}">查看完整结果 →</a><a class="button button-small" href="${route}data">数据与案例 →</a></div>`;
    let media = '';
    if (p.media?.length) media = section('examples','已有资料中的直观案例',`<div class="ri-media">${p.media.map(m=>`<figure><a href="${e(asset(m.url))}" target="_blank" rel="noopener"><img src="${e(asset(m.url))}" alt="${e(m.title)}" loading="lazy"></a><figcaption><b>${e(m.title)}</b><p>${e(m.caption)}</p><small>${e(m.scope)}</small></figcaption></figure>`).join('')}</div><a class="button button-small" href="${route}data">打开完整数据与案例 →</a>`);
    if (cases?.samples?.length) {
      const s=cases.samples[0];
      media=section('examples','从真实任务理解输入与判断',`<p>${e(cases.selection_policy)}</p><article class="ri-text-case"><h3>${e(s.title)}</h3><span class="tag">${e(s.split)} · 原ID ${e(s.source_id)}</span><dl>${s.inputs.map(([k,v])=>`<div><dt>${e(k)}</dt><dd>${e(text(v))}</dd></div>`).join('')}</dl></article><p class="ri-help">这里只展示固定顺序选取的一例；完整6例、原标签、模型输出及逐行来源在“数据与案例”中。</p><a class="button button-small" href="${route}data">打开完整真实样例 →</a>`);
    }
    const outline=[['motivation','Motivation'],['mechanism','方法图解'],['idea','核心 Idea'],['method','方法步骤'],['related','相关工作'],['contribution','顶会价值'],['evidence','证据与缺口']];
    return `<div class="ri-introduction" data-introduction-project="${e(id)}"><section class="ri-hero"><small>项目简介 · 从问题到可检验贡献</small><h2>${e(p.one_liner)}</h2><p>科学主张按证据成立；下面的图解说明方法，不代表论文已达到投稿标准。</p><div class="actions"><a class="button button-small" href="/api/research/export?project=${encodeURIComponent(p.report_id)}&format=zip" download>下载本课题图文包</a><a class="button button-small" href="/api/research/export?project=${encodeURIComponent(p.report_id)}&format=markdown" download>导出PPT上下文</a></div></section><nav class="ri-outline" aria-label="项目简介内容">${outline.map(([key,label])=>`<button type="button" data-ri-jump="ri-${key}">${label}</button>`).join('')}</nav>${section('motivation','为什么值得研究 · Motivation',motivation)}${section('mechanism','先看懂任务与方法',diagram)}${media}${section('idea','核心 Idea 与机制',idea)}${section('method','当前方法 · 从输入到输出',method)}${section('related','与相关工作的区别',related)}${section('contribution','顶会价值与成立条件',contribution)}${section('evidence','现有证据支持到哪一步',evidence)}<details class="panel ri-sources"><summary>内容审阅与证据入口</summary><p>简介复核：${e(p.reviewed_at)}。源文档后续变化需要复核，页面刷新不等于实时核验研究任务。</p><div class="actions">${p.reading_sources.map(source).join('')}</div></details></div>`;
  }
  function select(button) {
    const root=button.closest('.ri-introduction');
    if (!root) return;
    root.querySelectorAll('[data-ri-step]').forEach(b=>{const active=b===button;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
    root.querySelectorAll('.ri-step-detail').forEach(p=>p.hidden=p.id!==button.getAttribute('aria-controls'));
  }
  document.addEventListener('click', event=>{
    const step=event.target.closest('[data-ri-step]');if(step) select(step);
    const jump=event.target.closest('[data-ri-jump]');if(jump) document.getElementById(jump.dataset.riJump)?.scrollIntoView({behavior:'smooth',block:'start'});
  });
  document.addEventListener('keydown', event=>{
    const step=event.target.closest('[data-ri-step]');if(!step || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const steps=[...step.closest('.ri-steps').querySelectorAll('[data-ri-step]')];let i=steps.indexOf(step);
    i=event.key==='Home'?0:event.key==='End'?steps.length-1:(i+(event.key==='ArrowRight'?1:-1)+steps.length)%steps.length;
    event.preventDefault();select(steps[i]);steps[i].focus();
  });
  return {render, load};
})();

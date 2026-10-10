'use strict';

// Reviewed project dossiers supplement native metadata. No code/artifact HTML is
// executed. Each version retains its own task, checkpoint, split and protocol.
window.ProjectEvidence = (() => {
  const base = '/assets/projects/voa/';
  let data;
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = n => (Number(n)*100).toFixed(2)+'%';
  const link = values => '#/experiments/voa?' + new URLSearchParams({origin:'fastresearch',...values});
  const badge = (s,kind='') => `<span class="tag ${kind}">${e(s)}</span>`;
  const panel = (title, body, extra='') => `<section class="panel voa-panel ${extra}"><div class="section-head"><h2>${e(title)}</h2></div>${body}</section>`;
  const navs = [['project-progress','项目进度'],['project-overview','项目记录'],['run-stage-explorer','实验结果'],['cases','真实案例'],['paper-evidence','论文与证据']];

  async function load() {
    const r = await fetch(base+'dossier.json', {cache:'no-cache'});
    if (!r.ok) throw new Error('VOA研究资料暂时不可读；请重新同步');
    data = await r.json();
    if (data.schema_version!==1 || !data.versions.some(v=>v.id===data.default_version)) throw new Error('VOA内容版本不完整');
    return data;
  }
  function resultTable(t) {
    return `<div class="table-wrap"><table class="research-table voa-table"><caption>${e(t.title)}</caption><thead><tr>${t.columns.map(c=>`<th scope="col">${e(c)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(row=>`<tr>${row.map((cell,i)=>`<${i?'td':'th'} ${i?'':'scope="row"'}>${e(t.formats[i]==='percent'?pct(cell):cell)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function chart(c) {
    // Native SVG, numeric attributes (no inline CSS), fixed 0–100% axis.
    const width=820, top=60, left=166, right=76, row=30, gap=35, track=width-left-right;
    const height=top+c.labels.length*(row*c.series.length+gap)+18;
    const ticks=[0,.25,.5,.75,1];
    let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${e(c.title)}；数值见对应结果表"><title>${e(c.title)}</title>${ticks.map(x=>`<line class="voa-gridline" x1="${left+x*track}" x2="${left+x*track}" y1="39" y2="${height-20}"/><text class="voa-axis-label" x="${left+x*track}" y="24" text-anchor="middle">${x*100}%</text>`).join('')}`;
    c.labels.forEach((label,i)=> {
      const y=top+i*(row*c.series.length+gap);
      svg+=`<text class="voa-chart-label" x="${left-15}" y="${y+16}" text-anchor="end">${e(label)}</text>`;
      c.series.forEach((s,j)=> {
        const v=Number(s.values[i]);
        svg+=`<rect class="voa-bar voa-series-${j%4}" x="${left}" y="${y+j*row}" width="${Math.max(0,Math.min(1,v))*track}" height="18" rx="4"><title>${e(s.name)} · ${e(label)}：${pct(v)}</title></rect><text class="voa-chart-value" x="${left+Math.max(0,Math.min(1,v))*track+8}" y="${y+j*row+14}">${pct(v)}</text>`;
      });
    });
    svg+='</svg>';
    return `<figure class="voa-chart"><figcaption>${e(c.title)}</figcaption><div class="voa-legend">${c.series.map((s,j)=>`<span><i class="voa-series-${j%4}"></i>${e(s.name)}</span>`).join('')}</div>${svg}</figure>`;
  }
  function sources(ids) {
    return `<div class="voa-source-links">${ids.map(id=>data.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a class="button button-small" href="${e(s.url)}" target="_blank" rel="noopener">${e(s.label)} ↗</a>`).join('')}</div>`;
  }
  function versionTabs(v) {
    return `<nav class="tabs voa-version-tabs" aria-label="实验版本">${data.versions.map(x=>`<a class="tab ${x.id===v.id?'active':''}" ${x.id===v.id?'aria-current="page"':''} href="${link({view:'run-stage-explorer',version:x.id})}">${e(x.label)}</a>`).join('')}</nav>`;
  }
  function results(params) {
    const v=data.versions.find(x=>x.id===params.get('version')) || data.versions.find(x=>x.id===data.default_version);
    return panel('按协议查看实验结果',`<p class="voa-muted">${e(data.default_reason)}</p>${versionTabs(v)}<div class="voa-version-heading"><div><span class="eyebrow">${e(v.id.toUpperCase())} / ${e(v.stage)}</span><h3>${e(v.title)}</h3></div>${badge(v.badge,v.adopted?'green':'amber')}</div><div class="voa-scope">${e(v.scope)}</div><p>${e(v.method)}</p><div class="voa-result-charts">${v.charts.map(chart).join('')}</div>${v.tables.map(resultTable).join('')}<div class="voa-finding"><strong>结论</strong><p>${e(v.finding)}</p></div><div class="voa-boundary"><strong>边界与负证据</strong><p>${e(v.limits)}</p></div><details class="voa-details" open><summary>评测口径与可比范围</summary>${v.notes.map(n=>`<p>${e(n)}</p>`).join('')}</details>${sources(v.sources)}`,'voa-results');
  }
  function metrics() {
    const v=data.versions[0], r=v.tables[0].rows.find(x=>x[0].startsWith('v82'));
    const cards=[['独立测试 · S2正例F1',pct(r[3]),'+9.91pp · 95% CI [7.94, 11.85]'],['独立测试 · 历史闭环','290 / 421','68.88% · 首轮＋两条独立分支'],['独立测试 · 无目标准确率',pct(r[4]),'强起点87.60% · 退步6.60pp'],['训练参数 / 基座','250,368','3个定位Q-head · Qwen3-VL-4B']];
    return `<div class="voa-metrics">${cards.map(([label,value,caption],i)=>`<div class="voa-metric ${i===2?'voa-metric-warning':''}"><span>${e(label)}</span><strong>${e(value)}</strong><small>${e(caption)}</small></div>`).join('')}</div>`;
  }
  function idea() {
    return `<p class="voa-lead">${e(data.idea)}</p><div class="voa-address-flow"><div><small>原子地址</small><code>&lt;1&gt;&lt;0&gt;<b class="voa-color-red">&lt;red&gt;</b></code><span>二进制编号＋四色</span></div><span class="voa-flow-arrow" aria-hidden="true">→</span><div><small>物体表达</small><code>&lt;BOT&gt; 地址A + 地址B &lt;EOT&gt;</code><span>一个组绑定一个物体</span></div><span class="voa-flow-arrow" aria-hidden="true">→</span><div><small>再次引用</small><code>Find the object referred to by …</code><span>保留生成码与空间身份</span></div></div><p class="voa-muted">颜色不对应类别或坐标。注意力热图用于读取空间所指；当前输出为编码定位，名称＋编码和通用QA仍是候选接口。</p>`;
  }
  function timeline() {
    return `<ol class="voa-timeline">${data.timeline.map(t=>`<li><div>${badge(t.state,t.state==='当前保留'?'green':'')}<h3>${e(t.version)}</h3></div><div><strong>${e(t.method)}</strong><p>${e(t.result)}</p></div></li>`).join('')}</ol>`;
  }
  function next() {
    return `<div class="voa-next">${data.next_steps.map((s,i)=>`<article><span class="voa-step">0${i+1}</span>${badge(s.state)}<h3>${e(s.title)}</h3><p>${e(s.detail)}</p></article>`).join('')}</div>`;
  }
  function progress() {
    return metrics()+panel('研究问题与当前证据',idea()+`<div class="voa-finding"><strong>当前主张</strong><p>${e(data.claim)}</p></div><div class="voa-evidence-axis"><div class="voa-axis-pass">协议与实现<span>已验收</span></div><div class="voa-axis-pass">S2开发与独立确认<span>局部收益成立</span></div><div class="voa-axis-open">S1／结构归因<span>证据缺口</span></div><div class="voa-axis-open">标准任务与投稿<span>待完成</span></div></div>`)
      +panel('当前保留模型 · v82',`<div class="voa-scope">S2任务 · step4096 · 无约束自由生成 · 新独立500 TEST</div>${chart(data.versions[0].charts[0])}${resultTable(data.versions[0].tables[0])}<div class="voa-boundary"><strong>正结果与失败边界并列</strong><p>${e(data.versions[0].limits)}</p></div><div class="actions"><a class="button primary" href="${link({view:'run-stage-explorer'})}">切换版本与完整结果 →</a><a class="button" href="${link({view:'cases',case:'double_gain'})}">查看实际输入、输出与注意力 →</a></div>`)
      +panel('方法迭代与决策',timeline())+panel('下一步优先级',next());
  }
  function records() {
    return panel('方法：从编码到可引用的空间身份',idea()+`<div class="voa-method-grid"><article><h3>S1 · 全图辨析目标</h3><p>图像＋Observe the image carefully. → 全图规范原子目录。完整生成CE＋完整编码组范围hinge；输入不给编码目录。</p><span class="tag amber">全图表达与阶段迁移未证实</span></article><article><h3>S2 · 当前v82实现</h3><p>图像＋Observe the image carefully. Find {expression}. → 相关物体编码组／NO_TARGET。无需先枚举全图；当前4096次接续仅S2。</p><span class="tag green">局部定位／回指有独立收益</span></article></div><div class="voa-pipeline"><div><b>01 原生视觉</b><p>完整图像token、MRoPE与DeepStack；无预关联ROI目录。</p></div><div><b>02 有限干预</b><p>固定3个定位Q-head的rank32编码位置适配器＋29词表行，共250368参数；KV/O/MLP及视觉基座冻结。</p></div><div><b>03 生成名字并绑定</b><p>TRAIN合法自由输出与GT一对一空间匹配；CE保持输出＋hinge学习范围，失败回退规范目标。</p></div><div><b>04 生成后空间读出</b><p>实际生成IDs完整重放；编码组→原生图像token注意力，不用GT选择head或修复身份。</p></div></div><details class="voa-details"><summary>注意力、损失与评分细节</summary><p>固定零基head：L21H18、L20H15、L21H31。每个原子的二进制＋颜色位置均参与平均；固定head合并后按图像条件归一化，物体码组取原子图平均。</p><p>训练：L = CE + 0.1 × 10 × mean(ReLU(0.5 − 区域质量)²)。匹配仅使用TRAIN GT，空间目标不强制区域内部均匀；不是KL。</p><p>评测：组注意力落入GT支持的质量≥50%才是可匹配边；最大基数一对一匹配、质量打破平局。F1 = 2TP / (预测组数＋GT实例数)。重复组不能额外得TP，仍计入预测分母。严格完整另要求无多余对象、结束、语法及目标偏好。</p><p>normal模式的原函数回退与小型能力筛查，不等于全面active能力保持。生成后完整重放会增加推理成本。</p></details>${sources(['method','method-audit'])}`)
      +panel('不同版本解决了什么',timeline())
      +panel('训练分布与证据边界',`<p>共享池16K图像／182881表达，不等于每臂都训练了16K。v82继承历史strong v40，近期4096次更新覆盖3315不同TRAIN图，不能称为从基座仅训练4096步。</p>${chart({title:'共享S2表达池 · 按请求目标数',labels:['单目标','双目标','无目标','3+目标'],series:[{name:'表达占比',values:[.5827,.3110,.0984,.0079]}]})}<p>v82普通定位3072次中：单1229、双1512、负307、3+共24；另1024真实历史。v86刻意提高3+到25%作压力诊断。目标数是每个请求要求的实例数，不是图中物体总数。</p><div class="voa-boundary"><strong>未验证</strong><p>四色相对普通ID增量、可组合原子结构、S1迁移、任意数量目标、跨域／未见类别和通用问答。自然名称＋编码指向需先打通自然文字的训练路径，尚非当前模型接口。</p></div>`);
  }
  const caseLabels={single_gain:'单目标 · 正向案例',double_gain:'双目标 · 正向案例',history_gain:'历史引用 · 闭环',single_regression:'单目标 · 退步',three_failure:'三目标 · 身份碰撞',negative_regression:'无目标 · 误报'};
  function cases(params) {
    const c=data.cases.find(x=>x.id===params.get('case')) || data.cases.find(x=>x.id==='double_gain');
    const key=params.get('model')==='strong'?'strong':'candidate', m=c.models[key];
    const index=Math.max(0,Math.min(m.panels.length-1,Number(params.get('group'))||0));
    const p=m.panels[index], isNegative=c.id==='negative_regression';
    const choose=(values)=>link({view:'cases',case:c.id,model:key,...values});
    const columns=c.annotation_ids.map((id,i)=>'GT '+(i+1));
    const masses=m.metric.mass_matrix || [];
    return panel('真实生成：点击编码查看空间所指',`<div class="voa-scope">S2 · 冻结v82与strong v40 · 额外DEV选例 · 非独立TEST案例／非随机代表样本</div><p class="voa-muted">六类按预定规则各选一个中位案例，正向与失败同时保留。绿色／蓝色／粉色轮廓是GT，热图是生成组的条件视觉注意力密度；固定0–5倍均匀密度显示，未逐图峰值归一化，非预测mask。</p><nav class="tabs voa-case-tabs" aria-label="案例类型">${data.cases.map(x=>`<a class="tab ${x.id===c.id?'active':''}" ${x.id===c.id?'aria-current="page"':''} href="${link({view:'cases',case:x.id,model:key})}">${e(caseLabels[x.id])}</a>`).join('')}</nav><div class="voa-case-heading"><h3>${e(caseLabels[c.id])}</h3><small>image ${e(c.image_id)} · 原生patch网格 ${c.native_grid.join('×')} · 符合该选例条件 ${e(c.qualifying_cases)} 例</small></div><div class="voa-prompt"><small>真实输入</small><p>${e(c.prompt)}</p></div><nav class="tabs" aria-label="案例模型">${[['candidate','v82 · 当前保留'],['strong','strong v40 · 强起点']].map(([k,n])=>`<a class="tab ${key===k?'active':''}" href="${choose({model:k,group:0})}">${e(n)}</a>`).join('')}</nav><div class="voa-case-visuals"><figure><img src="${base}cases/${e(c.image)}" alt="${e(caseLabels[c.id])}，原图" width="480" height="360"><figcaption>原图 · ${isNegative?'请求目标不存在':columns.join('、')}</figcaption></figure><figure>${p?`<img src="${base}cases/${e(p.file)}" alt="${e(key==='candidate'?'v82':'strong v40')}第${index+1}个实际生成码组的注意力热图" width="480" height="360">`:'<div class="voa-no-map">模型输出NO_TARGET，没有生成物体码组</div>'}<figcaption>${p?'生成组 '+(index+1)+' · 注意力／GT轮廓':'没有物体组注意力'}</figcaption></figure></div><div class="voa-density-legend"><span>0</span><div></div><span>5×均匀密度（以上截顶）</span></div><div class="voa-output"><small>真实输出 · 点击对象码组切换热图</small><div class="voa-code-groups">${m.groups.length?m.groups.map((g,i)=>`<a class="voa-code ${i===index?'active':''}" href="${choose({group:i})}"><span>对象 ${i+1}</span><code>${e('<BOT>'+g.join('+')+'<EOT>')}</code></a>`).join(''):`<code>${e(m.prediction)}</code>`}</div><details><summary>完整原始输出</summary><code>${e(m.prediction)}</code></details></div><div class="tags">${badge('结束：'+(m.ended?'是':'否'),m.ended?'green':'amber')}${badge('语法：'+(m.syntax?'合法':'无效'))}${badge(isNegative?'无目标判断：'+(m.metric.no_target_correct?'正确':'误报'):'实例F1：'+pct(m.metric.f1),m.metric.f1===1?'green':'amber')}${badge('严格完整：'+(m.metric.all_instances_with_strict_preference?'是':'否'))}</div>${columns.length&&masses.length?resultTable({title:'生成组 → GT的注意力质量（≥50%为匹配候选；一对一）',columns:['生成组',...columns],rows:masses.map((r,i)=>['对象 '+(i+1),...r]),formats:['text',...columns.map(()=>'percent')]}):''}${c.id==='single_gain'?'<p class="voa-muted">此例strong质量49.979%，接近50%阈值；展示一次阈值命中差异，不代表总体空间质量差距。</p>':''}${c.id==='history_gain'?'<div class="voa-boundary"><strong>闭环差别来自首轮</strong><p>本例两模型的两次后续回指都正确；strong首轮一个对象未过50%，因此完整闭环失败。不能把此例写成strong无法回指。</p></div>':''}${c.id==='three_failure'?'<div class="voa-boundary"><strong>失败：数目正确，身份仍碰撞</strong><p>三个输出组中后两个重名且集中于同一GT；重复组不重复获得TP，不能视为完整定位三个目标。</p></div>':''}${m.followups?.length?`<h3>真实历史 · 两条独立回指分支</h3><p class="voa-muted">每条分支各从同一首轮出发，非连续三轮；闭环还要求首轮全部绑定正确。</p><div class="voa-followups">${m.followups.map((f,i)=>`<article><h4>分支 ${i+1}</h4><p>${e(f.prompt)}</p><code>${e(f.prediction)}</code><img src="${base}cases/${e(f.panel)}" alt="分支${i+1}实际生成的回指注意力" width="480" height="360" loading="lazy"><div class="tags">${badge(f.reference_preserved?'原编码保持':'编码改变')}${badge(f.success?'回指正确':'回指失败',f.success?'green':'amber')}</div></article>`).join('')}</div>`:''}${sources(['cases'])}`,'voa-gallery');
  }
  function evidence() {
    return panel('论文主张：收益、归因和愿景分开',`<div class="voa-method-grid"><article><h3>已有正向证据</h3><p>冻结v82在独立500的新图定位与分支回指上优于strong v40；位置打乱／均匀控制显著更低。v86再现生成绑定相对规范目标的开发收益。</p></article><article><h3>不能据此宣称</h3><p>全图对象语言已内化、任意目标数、四色最优或不可替代、原子组合泛化、完整官方benchmark SOTA、跨域与全面能力保持。</p></article></div><p>相关近邻及novelty判据统一维护在研究主文档。普通ID的长度／词频／算力匹配消融、标准定位指标、真实连续历史和自然指向接口仍是投稿缺口。</p>${sources(['main','method'])}`)
      +panel('可审阅图表',`<div class="voa-publication-figures"><figure><a href="${base}voa_v82_method.svg" target="_blank" rel="noopener"><img src="${base}voa_v82_method.svg" alt="v82训练、推理及能力边界的方法图" loading="lazy"></a><figcaption>当前实际方法 · 点击展开SVG</figcaption></figure><figure><a href="${base}voa_v82_independent500.svg" target="_blank" rel="noopener"><img src="${base}voa_v82_independent500.svg" alt="独立500定量比较、历史闭环与多目标局限" loading="lazy"></a><figcaption>独立500定量结果 · <a href="${base}voa_v82_independent500.csv" download>下载CSV</a></figcaption></figure></div>`)
      +panel('来源索引与核查时间',`<p class="voa-muted">仅投影已验收汇总和小型审阅图。源记录不迁移，网页不访问权重、完整标注、原始TEST或远端机器。SHA绑定原文，刷新页面不更新科学结论。</p><div class="voa-source-index">${data.sources.map(s=>`<article><a href="${e(s.url)}" target="_blank" rel="noopener">${e(s.label)} ↗</a><small>${e(s.locator)}</small><small>源修改 ${e(s.modified_at)} · SHA256 ${e(s.sha256)}</small></article>`).join('')}</div><details class="voa-details"><summary>当前检查点身份</summary><code>${e(data.checkpoint.locator)}</code><p class="voa-muted">SHA256 ${e(data.checkpoint.sha256)}</p></details>`);
  }
  async function render(params) {
    await load();
    const pane=navs.some(([id])=>id===params.get('view'))?params.get('view'):'project-progress';
    const content=pane==='project-overview'?records():pane==='run-stage-explorer'?results(params):pane==='cases'?cases(params):pane==='paper-evidence'?evidence():progress();
    return `<div class="voa-dossier"><a class="back-link" href="#/experiments">← 全部课题</a><div class="page-title"><div><h1>${e(data.title)}</h1><p>学习紧凑、可组合、可复用的视觉表达 · CVPR 2027研究候选</p></div>${badge('v82 · 当前保留','green')}</div><nav class="tabs lab-tabs" aria-label="VOA课题工作区">${navs.map(([id,label])=>`<a class="tab ${pane===id?'active':''}" ${pane===id?'aria-current="page"':''} href="${link({view:id})}">${label}</a>`).join('')}</nav><div class="voa-provenance"><span>${e(data.runtime)}</span><span>内容复核 ${e(data.reviewed_at)}</span><a href="#/progress?project=VOA">整体研究进展 ↗</a></div>${content}</div>`;
  }
  async function cards() {
    // An unavailable optional dossier must not hide unrelated native projects.
    try { await load(); } catch { data=null; }
  }
  function card(p) {
    if (p.project_id!=='voa' || !data) return null;
    return `<article class="card voa-project-card" data-lab-project="voa"><div class="card-top">${badge('S2独立收益 · 机制待证','green')}<span class="card-id">v82</span></div><h3><a href="${link({})}">${e(data.title)}</a></h3><p class="description">少量符号绑定图像中的物体，在定位与对话中重复引用；保留多个版本的收益与失败边界。</p><div class="voa-card-score"><strong>68.83<small>%</small></strong><div>S2正例F1 · 独立500图<span>比strong v40 +9.91pp</span></div></div><div class="tags">${badge('CVPR 2027')}${badge('5组版本／诊断')}${badge('6类真实案例')}</div><div class="card-foot"><span>冻结证据 · 非投稿就绪</span><a href="${link({view:'run-stage-explorer'})}">查看实验 →</a></div></article>`;
  }
  return {render,cards,card};
})();

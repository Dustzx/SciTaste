/* Repository-owned procedures: prepare an explicit assistant task, never execute it. */
window.SciTasteSkills = (() => {
  const e=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list=x=>`<ul>${(x||[]).map(v=>`<li>${e(v)}</li>`).join('')}</ul>`;
  async function fetchJSON(query='') {
    const response=await fetch('/api/skills'+query,{cache:'no-cache'});
    if(!response.ok) throw new Error('核心技能资料暂不可读');
    return response.json();
  }
  async function render(id) {
    const data=await fetchJSON();
    if(!id) return `<div class="page-title"><div><h1>核心技能</h1><p>把使用中沉淀的稳定做法带入科研工作；规范、版本与执行任务一起保留。</p></div></div><section class="panel"><h2>从经验到可复用流程</h2><p>经验保留事实与限制，技能整理可重复的做法。选择技能、填写项目与目标，准备任务包后交给科研助手执行。</p><p>平台准备材料时不调用模型或实验；技能版本不代表科学有效性。</p></section><div class="grid-two">${data.skills.map(s=>`<article class="panel" data-core-skill="${e(s.id)}"><span class="tag">v${e(s.version)}</span><h2>${e(s.name)}</h2><p>${e(s.description)}</p><h3>适用场景</h3>${list(s.when_to_use)}<h3>交付内容</h3>${list(s.outputs)}<a class="button primary" href="#/skills/${e(s.id)}">查看与使用 →</a></article>`).join('')}</div>`;
    if(!data.skills.some(s=>s.id===id)) throw new Error('未登记该核心技能');
    const s=await fetchJSON('?'+new URLSearchParams({skill:id}));
    return `<a href="#/skills" class="back-link">← 核心技能</a><div class="page-title"><div><h1>${e(s.name)}</h1><p>${e(s.description)}</p></div><span class="tag">v${e(s.version)}</span></div>${s.workflow?.length?`<section class="panel"><h2>执行流程</h2><ol class="skill-workflow">${s.workflow.map(step=>`<li>${e(step)}</li>`).join('')}</ol><p>实测改变核心论证时回到重写与审稿；一致时保留已审结构定稿。</p></section>`:''}<section class="panel"><h2>准备技能任务</h2><p>填写项目名或目录和目标。任务包包含完整规范、模板与版本校验信息；执行助手核对项目资料后按所选技能推进。当前步骤只准备任务。</p><div class="skill-inputs"><label>项目名或目录<input id="skill-project" maxlength="240" placeholder="例如：my-research 或本地项目目录"></label><label>本次目标<textarea id="skill-goal" maxlength="2000" rows="3">${e(s.default_goal)}</textarea></label></div><button class="button primary" data-skill-prepare="${e(s.id)}">准备技能任务</button><p id="skill-status" role="status" aria-live="polite"></p><div id="skill-task" hidden><label for="skill-prompt">交给执行助手的任务与完整技能</label><textarea id="skill-prompt" rows="12" readonly></textarea><div class="actions"><button class="button" data-skill-copy>复制完整任务</button><a class="button" id="skill-task-download" download>下载任务包ZIP</a><a class="button" id="skill-markdown-download" download>下载任务Markdown</a></div><p>任务已准备，技能尚未执行。请提供项目现有资料或授权执行助手读取相应目录。</p></div></section><section class="panel"><h2>技能版本与复用</h2><p>版本 ${e(s.version)} · 完整修订SHA256 <code>${e(s.revision)}</code></p><div class="actions"><a class="button" href="/api/skills?skill=${encodeURIComponent(s.id)}&format=zip" download>下载技能包</a><a class="button" href="/api/skills?skill=${encodeURIComponent(s.id)}&format=markdown" download>下载SKILL.md</a></div><p>clone后可直接使用此页面或命令行准备任务；无需作者的研究目录。技能包可交给支持SKILL.md的执行助手，也可直接读取完整任务Markdown。</p></section><section class="panel skill-documents"><h2>规范与模板</h2>${s.documents.filter(d=>d.path.endsWith('.md')).map((d,i)=>`<details ${i===0?'open':''}><summary>${e(d.path)}</summary><pre>${e(d.content)}</pre></details>`).join('')}</section>`;
  }
  document.addEventListener('click',async event=>{
    const prepare=event.target.closest('[data-skill-prepare]');
    if(prepare){
      const status=document.getElementById('skill-status');prepare.disabled=true;
      try {
        const query=new URLSearchParams({skill:prepare.dataset.skillPrepare,format:'task',project:document.getElementById('skill-project').value,goal:document.getElementById('skill-goal').value});
        const value=await fetchJSON('?'+query);
        document.getElementById('skill-prompt').value=value.prompt;
        query.set('revision',value.skill_revision);query.set('format','task-zip');document.getElementById('skill-task-download').href='/api/skills?'+query;
        query.set('format','task-markdown');document.getElementById('skill-markdown-download').href='/api/skills?'+query;
        document.getElementById('skill-task').hidden=false;
        status.textContent='任务已准备 · 等待执行助手 · '+value.task_id;
      }catch(error){status.textContent=error.message;}finally{prepare.disabled=false;}
    }
    if(event.target.closest('[data-skill-copy]')){
      const field=document.getElementById('skill-prompt');
      try{await navigator.clipboard.writeText(field.value);document.getElementById('skill-status').textContent='完整任务已复制';}
      catch(_){field.focus();field.select();document.getElementById('skill-status').textContent='请复制已选中的完整任务';}
    }
  });
  return {render};
})();

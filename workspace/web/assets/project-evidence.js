'use strict';
// Optional project adapter. Project claims and metrics come from reviewed records.
window.ProjectEvidence = (() => {
  async function cards() { return []; }
  function card() { return null; }
  async function render(params) {
    await window.ResearchProjects.load();
    return '<section class="panel"><h2>暂无项目资料</h2><p>尚未配置此课题的审阅资料；没有预置实验结果。</p><a href="#/experiments">返回实验工作台 →</a></section>';
  }
  return {cards, card, render};
})();

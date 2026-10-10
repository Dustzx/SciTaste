#!/usr/bin/env python3
"""Validate authored report axes/lessons and render local Markdown projections."""
import json
from pathlib import Path

import progress_board as board


def main():
    data = board.snapshot()
    assert len({p['id'] for p in data['projects']}) == len(data['projects'])
    allowed = {'passed', 'active', 'blocked', 'planned', 'unknown'}
    for p in data['projects']:
        assert set(p['axis_states']) == set(data['axes'])
        assert set(p['axis_states'].values()) <= allowed
        assert (board.REPORT/p['report']).is_file()
    assert len({e['id'] for e in data['experiences']}) == len(data['experiences'])
    for e in data['experiences']:
        assert all(e.get(k) for k in ['trigger', 'action', 'observation', 'limits', 'transfer', 'evidence'])
        assert all(board.source_document(s['source_key']) for s in e['evidence'])
    labels = {'passed':'已过门', 'active':'推进中', 'blocked':'证据缺口', 'planned':'待执行', 'unknown':'未核实'}
    rows = ['# 整体研究进展轴线', '', '生成：'+data['generated_at']+'；轴线是证据门槛，不是工时百分比。', '',
            data['verification_policy'], '', '| 项目 | '+' | '.join(data['axes'])+' | 关键缺口 |',
            '| --- | '+' | '.join(['---']*(len(data['axes'])+1))+' |']
    for p in data['projects']:
        rows.append('| ['+p['id']+']('+p['report']+') | '+' | '.join(labels[p['axis_states'][a]] for a in data['axes'])+' | '+p['gap']+' |')
    rows += ['', '维护主数据：[STATUS_BOARD.json](STATUS_BOARD.json)。实验条目由项目简报与本机run产物投影，来源变化提示复核，原始结果不移动。', '',
             '平台：[研究进展](http://127.0.0.1:8765/#/progress) · [共享经验池](http://127.0.0.1:8765/#/experience)。', '',
             '维护命令：在 FastResearch 运行 `.venv/bin/python scripts/maintain_progress.py`。先核源状态/台账，再更新简报和轴线；新增经验须有条件、证据、限制及迁移范围。']
    (board.REPORT/'PROGRESS_AXES.md').write_text('\n'.join(rows)+'\n')
    rows = ['# 共享研究经验池', '', '生成：'+data['generated_at'], '',
            '唯一主数据：[EXPERIENCE_POOL.json](EXPERIENCE_POOL.json)。以下是生成投影，新增/更正先维护JSON再生成。', '',
            '经验不扩大实验、数据、费用或外部写入权限；跨项目迁移仍需验证。不把单次正结果写成通用定律。']
    for e in data['experiences']:
        rows += ['', '## '+e['id']+' · '+e['title'], '', '**来源与等级：** '+e['project']+' / '+e['status'], '',
                 '**触发：** '+e['trigger'], '', '**动作：** '+e['action'], '', '**观察：** '+e['observation'], '',
                 '**限制：** '+e['limits'], '', '**迁移：** '+e['transfer'], '',
                 '**证据：** '+' · '.join('['+s['locator']+']('+s['path']+')' for s in e['evidence'])]
    (board.REPORT/'EXPERIENCE_POOL.md').write_text('\n'.join(rows)+'\n')
    print(json.dumps({'projects':len(data['projects']), 'experiments':len(data['experiments']), 'experiences':len(data['experiences']), 'valid':True}))


if __name__ == '__main__':
    main()

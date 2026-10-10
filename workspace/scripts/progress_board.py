"""Read-only report projection and local run evidence; never launches research."""
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT.parent / 'report' if (ROOT.parent / 'report').is_dir() else ROOT / 'report'
REPORT = Path(os.environ.get('SCITASTE_REPORT_ROOT', str(DEFAULT_REPORT))).resolve()


def study_runs():
    study = ROOT/'outputs/projects/fastresearch-cvpr2027/research'
    return sorted([*study.glob('runs/*'), *study.glob('spacecast/runs/*'), *study.glob('hrbench/runs/*'), *study.glob('counting/runs/*'), *study.glob('counting/fsc147/runs/*'), *study.glob('gui/runs/*'), *study.glob('document/runs/*')])


def read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def stamp(path):
    if not path.is_file():
        return {'available': False}
    return {'available': True, 'modified_at': datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo('Asia/Shanghai')).isoformat(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def project_brief(path):
    """Project authored narrative verbatim; never infer experiment completion."""
    if not path.is_file():
        return {'available': False, 'sections': []}
    content = path.read_text()
    headings = list(re.finditer(r'^##\s+(.+)$', content, re.M))
    sections = []
    for i, heading in enumerate(headings):
        body = content[heading.end():headings[i+1].start() if i+1 < len(headings) else len(content)].strip()
        sections.append({'title': heading[1], 'markdown': body,
                         'tables': len(re.findall(r'^\|\s*[-:]+', body, re.M))})
    intro = content[:headings[0].start()] if headings else content
    def statement(label):
        match = re.search(r'\*\*' + label + r'[^*]*\*\*\s*(.+)', intro)
        return match[1].strip() if match else None
    next_section = next((s for s in sections if re.match(r'5[.、\s]', s['title'])), {})
    next_text = next_section.get('markdown', '').split('\n\n')[0]
    return {'path': str(path), **stamp(path), 'intro': intro.strip(),
            'current': statement('当前做到'), 'claim': statement('顶会级创新主张'),
            'next_summary': next_text, 'sections': sections,
            'table_count': sum(s['tables'] for s in sections)}


def alive(pid, run_id):
    try:
        cmd = Path(f'/proc/{int(pid)}/cmdline').read_bytes().decode().split('\0')
        if any('cvpr_countingdino_run.py' in a for a in cmd):
            return run_id == 'countingdino_vitl14reg_cpu_v1'
        if any(name in a for a in cmd for name in ['cvpr_hrbench_run.py','cvpr_count_run.py','cvpr_fsc_contract.py','cvpr_fsc_vote.py','cvpr_ownership_run.py','cvpr_scalar_controls_run.py','cvpr_gui_run.py','cvpr_global_center_run.py']):
            return '--run-id' in cmd and cmd[cmd.index('--run-id')+1] == run_id
        if any('cvpr_chart_anchoring.py' in a for a in cmd):
            return run_id == 'bailian_qwen38_flash_anchoring_diagnostic_v1'
        if any('cvpr_spacecast_api.py' in a for a in cmd):
            return run_id == 'bailian_qwen38_flash_spacecast_state_screen_v3'
        if any('cvpr_spacecast_recovery.py' in a for a in cmd):
            actual = cmd[cmd.index('--run-id')+1] if '--run-id' in cmd else 'bailian_qwen38_flash_spacecast_state_screen_v3_recovery_v1'
            return run_id == actual
        return any('cvpr_chart_api.py' in a for a in cmd) and '--run-id' in cmd and cmd[cmd.index('--run-id')+1] == run_id
    except (OSError, ValueError, IndexError, TypeError):
        return False


def report_experiments(path, project):
    if not path.is_file():
        return []
    text = path.read_text()
    section = re.search(r'## 4[.、\s].*?(?=\n## 5|\Z)', text, re.S)
    if not section:
        return []
    rows = []
    for line in section.group().splitlines():
        if not line.startswith('|') or re.match(r'^\|\s*[-:]', line):
            continue
        cells = [s.strip() for s in line.strip('|').split('|')]
        if len(cells) == 3 and not any(s in cells[0] for s in ['实验问题', '工作/实验']):
            rows.append({'project': project, 'name': cells[0], 'protocol': cells[1], 'finding': cells[2],
                         'verification': 'report_snapshot', 'status': '简报快照', 'source_key': project+'.report'})
    return rows


def sources():
    board = read(REPORT/'STATUS_BOARD.json', {'projects': []})
    index = read(REPORT/'sources.json', {'projects': {}})
    found = {}
    for p in board['projects']:
        found[p['id']+'.report'] = Path(REPORT/p['report'])
        for key, value in index['projects'].get(p['id'], {}).get('sources', {}).items():
            found[p['id']+'.'+key] = Path(value['path'])
    found['FastResearch.portfolio'] = ROOT/'outputs/projects/fastresearch-cvpr2027/research/PORTFOLIO.json'
    study = ROOT/'outputs/projects/fastresearch-cvpr2027/research'
    for path in [run/'SUMMARY.json' for run in study_runs() if (run/'SUMMARY.json').is_file()]:
        status=read(path.parent/'STATUS.json', {})
        found['run.'+path.parent.name] = path.parent/status.get('summary_file',path.name)
    for path in [run/'PARTIAL_SUMMARY.json' for run in study_runs() if (run/'PARTIAL_SUMMARY.json').is_file()]:
        found['run.'+path.parent.name+'.partial'] = path
    for path in [run/'STATUS.json' for run in study_runs() if (run/'STATUS.json').is_file()]:
        found['run.'+path.parent.name+'.status'] = path
    pool = read(REPORT/'EXPERIENCE_POOL.json', {'entries': []})
    for item in pool['entries']:
        for i, evidence in enumerate(item['evidence']):
            found['experience.'+item['id']+'.'+str(i)] = Path(evidence['path'])
    return found


def source_document(key):
    path = sources().get(key)
    if not path:
        return None
    resolved = path.resolve()
    roots = [ROOT.parent.resolve(), REPORT.resolve(), (Path.home() / 'zfx/papers').resolve()]
    if not any(root in resolved.parents for root in roots) or resolved.suffix not in {'.md', '.json'}:
        return None
    if not resolved.is_file() or resolved.stat().st_size > 2*1024*1024:
        return None
    # Only explicitly indexed narrative/summary sources, never raw calls, credentials or arbitrary paths.
    if resolved.name in {'API_LEDGER.json', 'calls.jsonl', 'API_AUTHORIZATION.json'}:
        return None
    return {'source_key': key, 'path': str(path), 'content': resolved.read_text(), **stamp(resolved)}


def snapshot():
    board = read(REPORT/'STATUS_BOARD.json', {'projects': [], 'axes': []})
    index = read(REPORT/'sources.json', {'projects': {}})
    pool = read(REPORT/'EXPERIENCE_POOL.json', {'entries': []})
    projects, experiments = [], []
    for row in board['projects']:
        p = dict(row)
        p['brief'] = project_brief(REPORT/p['report'])
        p['sources'] = []
        for role, ref in index['projects'].get(p['id'], {}).get('sources', {}).items():
            path = Path(ref['path'])
            metadata = stamp(path)
            p['sources'].append({'role': role, 'key': p['id']+'.'+role, 'path': str(path),
                                 'changed_since_report': metadata.get('sha256') != ref.get('sha256'), **metadata})
        p['report_changed'] = any(s['changed_since_report'] for s in p['sources'])
        projects.append(p)
        experiments.extend(report_experiments(REPORT/p['report'], p['id']))
    study = ROOT/'outputs/projects/fastresearch-cvpr2027/research'
    for run in study_runs():
        status = read(run/'STATUS.json', {})
        if not status:
            continue
        protocol = read(run/'PROTOCOL.json', {})
        nested = 'conservation_decode' in protocol.get('arms', [])
        contract = 'exemplar_count_only' in protocol.get('arms', [])
        strong_vote = protocol.get('source_run') == 'bailian_qwen38_max0902_fsc_headroom_v1'
        ownership = 'halo_points' in protocol.get('arms', [])
        countingdino = protocol.get('arms') == ['countingdino']
        scalar_format = protocol.get('diagnostic_kind') == 'scalar_format'
        derived_unit = run.name == 'point_unit_normalization_exploratory_v1'
        predictions = read(run/('BASELINE_PREDICTIONS.json' if nested and status.get('mode')=='baseline' else 'PREDICTIONS.json'), [])
        is_live = alive(status.get('pid'), run.name)
        summary = read(run/status.get('summary_file','SUMMARY.json'), read(run/'PARTIAL_SUMMARY.json'))
        rows = []
        for arm in protocol.get('arms', ['未生成']):
            preds = [p for p in predictions if arm in p] if nested else [p for p in predictions if p['arm'] == arm]
            score = summary.get('arms', {}).get(arm) if summary else None
            rows.append({'arm': arm, 'predictions': len(preds), 'score': score})
        experiments.append({'project': 'FastResearch', 'name': run.name, 'status': status.get('state'),
                            'verification': 'local_process_and_artifacts', 'live': is_live,
                            'stale_running': status.get('state') == 'running' and not is_live,
                            'completed': len(predictions) if nested else len(predictions)//max(1,len(protocol.get('arms', []))), 'planned': status.get('planned_samples', 40),
                            'completion_label': '标量格式归因诊断' if scalar_format else '事后派生算子诊断' if derived_unit else 'CPU视觉参考基线' if countingdino else '原图基线' if nested and status.get('mode')=='baseline' else ('强型号基线' if len(protocol['arms'])==1 else '输入契约配对') if contract else '强型号投票配对' if strong_vote else '机制开发配对' if ownership else '完整配对',
                            'updated_at': status.get('verified_at', status.get('updated_at', status.get('completed_at', status.get('started_at')))),
                            'protocol': f"{protocol.get('model', 'local备用')} · 冻结权重 · 开发集 · "+('CPU原版16图块/840px，额外示例位置与计算量单列' if countingdino else ('三视觉示例强型号基线' if len(protocol['arms'])==1 else '类别文字/三视觉示例的输入契约诊断') if contract else '七次调用纠错/投票配对，direct/三次求和预算另列' if nested else '三视觉示例七视图投票，identity复用且全额逻辑计费' if strong_vote else '五主臂各4调用/8192上限；whole_first低预算、halo派生控制全额逻辑计费' if ownership else '同生成上限配对'),
                            'finding': '评分待完成' if summary is None else summary.get('scope', '部分开发诊断；确认集未评测'),
                            'arms': rows, 'summary': summary,
                            'source_key': 'run.'+run.name+('' if (run/'SUMMARY.json').exists() else '.partial' if (run/'PARTIAL_SUMMARY.json').exists() else '.status')})
        if scalar_format:
            experiments[-1]['protocol'] = 'qwen3.8-max-0902 · 同标记crop/三示例/核心边界 · 两臂各4×2048 · 仅count输出格式归因'
        if protocol.get('diagnostic_kind') == 'gui_headroom':
            experiments[-1]['completion_label'] = 'GUI强型号headroom基线'
            experiments[-1]['protocol'] = 'qwen3.8-max-0902 · 原始截图/高分辨率选项 · 单次1024上限 · 官方点击框评分 · 固定32开发组'
        if protocol.get('diagnostic_kind') == 'global_center':
            experiments[-1]['completion_label'] = '全图实例中心机制对照'
            experiments[-1]['protocol'] = 'qwen3.8-max-0902 · 三臂同全图512/crop768/三示例 · 各4×2048 · 片段中心/全图实例中心/标量读出'
        if derived_unit:
            experiments[-1]['protocol'] = '缓存qwen3.8-max-0902点输出 · 零新增API · 原生成全额逻辑计费 · 额外合法示例框位置，后验探索'
        if summary and summary.get('expansion_gate_passed') is False:
            experiments[-1]['finding'] = '原冻结科学扩展门失败，此版本停止；探索信号不等于独立验证。'
    ledger = read(study/'API_LEDGER.json', {})
    for experiment in experiments:
        if experiment.get('verification') == 'local_process_and_artifacts':
            attempts = [a for a in ledger.get('attempts', {}).values() if a['run_id'] == experiment['name']]
            experiment['requests'] = {'attempts': len(attempts), 'successful': sum(a['status'] == 'settled' for a in attempts),
                                      'unsettled': sum(a['status'] != 'settled' for a in attempts),
                                      'retries': sum(a.get('attempt_index', 1) > 1 for a in attempts)}
    budget = {k: ledger.get(k) for k in ['cap_cny', 'estimated_settled_cny', 'unresolved_reserved_cny', 'conservative_total_cny', 'updated_at']}
    for entry in pool['entries']:
        entry['evidence'] = [{**e, 'source_key': 'experience.'+entry['id']+'.'+str(i), **stamp(Path(e['path']))}
                             for i, e in enumerate(entry['evidence'])]
    document_links = {name: key for key, path in sources().items() if path.is_file()
                      for name in {str(path), str(path.resolve())}}
    portfolio = read(study/'PORTFOLIO.json', {})
    return {'schema_version': 2, 'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'axes': board['axes'], 'projects': projects, 'experiments': experiments, 'experiences': pool['entries'],
            'document_links': document_links, 'portfolio': portfolio,
            'budget': budget, 'maintenance': board.get('maintenance'),
            'verification_policy': '本页刷新只读本地文件。仅本地 FastResearch API run 核查进程；其他项目为来源快照，未重新查询远端。'}

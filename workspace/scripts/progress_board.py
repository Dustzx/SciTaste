"""Read-only report projection and local run evidence; never launches research."""
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from publication_plans import project_routes
from local_research import SHARED_RACE

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT.parent / 'report' if (ROOT.parent / 'report').is_dir() else ROOT / 'report'
REPORT = Path(os.environ.get('SCITASTE_REPORT_ROOT', str(DEFAULT_REPORT))).resolve()


def study_runs():
    study = ROOT/'outputs/projects/fastresearch-cvpr2027/research'
    return sorted([*study.glob('runs/*'), *study.glob('spacecast/runs/*'), *study.glob('hrbench/runs/*'), *study.glob('counting/runs/*'), *study.glob('counting/fsc147/runs/*'), *study.glob('gui/runs/*'), *study.glob('document/runs/*'), *study.glob('multimodal_intent/runs/*'), *study.glob('route/runs/*')])


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
        if any(name in a for a in cmd for name in ['cvpr_hrbench_run.py','cvpr_count_run.py','cvpr_fsc_contract.py','cvpr_fsc_vote.py','cvpr_ownership_run.py','cvpr_scalar_controls_run.py','cvpr_gui_run.py','cvpr_global_center_run.py','cvpr_zoomclick.py','cvpr_regionfocus_run.py','cvpr_doc_run.py','cvpr_intent_run.py','cvpr_intent_control_run.py','cvpr_intent_history_run.py','cvpr_route_execute.py','cvpr_route_evaluate.py','cvpr_route_budget_run.py','cvpr_route_budget_noimage.py','cvpr_route_schema_control.py']):
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


def document_scoring_alive(pid, run_id):
    """CPU scorer identity is separate from the paid model runner identity."""
    try:
        cmd = Path(f'/proc/{int(pid)}/cmdline').read_bytes().decode().split('\0')
        return (any(Path(arg).name == 'cvpr_doc_score.py' for arg in cmd)
                and '--run-id' in cmd and cmd[cmd.index('--run-id') + 1] == run_id)
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
    for branch in ('gui', 'document'):
        found['FastResearch.'+branch+'_method_iteration'] = study/branch/'METHOD_ITERATION.json'
        found['FastResearch.'+branch+'_execution_source_audit'] = study/branch/'EXECUTION_SOURCE_AUDIT.json'
    found['FastResearch.document_data_manifest'] = study/'document/data/MANIFEST.json'
    for key, path in {
        'intent_contract_audit': 'multimodal_intent/ARCADE_CONTRACT_AUDIT_20261012.json',
        'route_scorer_audit': 'route/SCORER_AUDIT_20261012.json',
        'route_data_preparation_allocation': 'route/DATA_PREPARATION_ALLOCATION.json',
        'route_preparation_acceptance': 'route/data/development32_prepared/PREPARATION_ACCEPTANCE.json',
        'route_visual_input_summary': 'route/VISUAL_INPUT_AUDIT_PUBLIC_SUMMARY.json',
        'seer_execution_audit': 'spacecast/SEER_EXECUTION_AUDIT_20261012.json',
    }.items():
        found['FastResearch.'+key] = study/path
    for path in [run/'SUMMARY.json' for run in study_runs() if (run/'SUMMARY.json').is_file()]:
        status=read(path.parent/'STATUS.json', {})
        found['run.'+path.parent.name] = path.parent/status.get('summary_file',path.name)
    for path in [run/'PARTIAL_SUMMARY.json' for run in study_runs() if (run/'PARTIAL_SUMMARY.json').is_file()]:
        found['run.'+path.parent.name+'.partial'] = path
    for path in [run/'STATUS.json' for run in study_runs() if (run/'STATUS.json').is_file()]:
        found['run.'+path.parent.name+'.status'] = path
    for run in study_runs():
        if read(run/'PROTOCOL.json', {}).get('kind') in {'route_task2', 'route_task2_schema_control'}:
            found['run.'+run.name+'.protocol'] = run/'PROTOCOL.json'
        if read(run/'PROTOCOL.json', {}).get('diagnostic_kind') != 'document_order_screen':
            continue
        if (run/'MECHANISM_AUDIT.json').is_file():
            found['run.'+run.name+'.mechanism_audit'] = run/'MECHANISM_AUDIT.json'
        if (run/'COORDINATOR.json').is_file():
            found['run.'+run.name+'.coordinator'] = run/'COORDINATOR.json'
        for path in run.glob('scoring_v*/STATUS.json'):
            if re.fullmatch(r'scoring_v\d+', path.parent.name):
                found['run.'+run.name+'.'+path.parent.name+'.status'] = path
    pool = read(REPORT/'EXPERIENCE_POOL.json', {'entries': []})
    for item in pool['entries']:
        for i, evidence in enumerate(item['evidence']):
            found['experience.'+item['id']+'.'+str(i)] = Path(evidence['path'])
    return found


def browser_source_path(path):
    """Whether an explicitly indexed file can be exposed as a text attachment."""
    resolved = path.resolve()
    roots = [ROOT.resolve(), REPORT.resolve()]
    if not any(root in resolved.parents for root in roots) or resolved.suffix not in {'.md', '.json', '.tex'}:
        return None
    if not resolved.is_file() or resolved.stat().st_size > 2*1024*1024:
        return None
    # Only explicitly indexed narrative/summary sources, never raw calls, credentials or arbitrary paths.
    if resolved.name in {'API_LEDGER.json', 'calls.jsonl', 'API_AUTHORIZATION.json'}:
        return None
    return resolved


def source_document(key):
    path = sources().get(key)
    if not path:
        return None
    resolved = browser_source_path(path)
    if resolved is None:
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
                                 'browser_readable': browser_source_path(path) is not None,
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
        intent = run.parent.parent.name == 'multimodal_intent' and protocol.get('mode') in {'direct', 'arcade', 'modensemble', 'controlled_history_variant'}
        route_schema = protocol.get('kind') == 'route_task2_schema_control'
        route_task2 = protocol.get('kind') in {'route_task2', 'route_task2_schema_control'}
        zoomclick = protocol.get('diagnostic_kind') == 'zoomclick_baseline_transfer'
        document = protocol.get('diagnostic_kind') == 'document_order_screen'
        nested = 'conservation_decode' in protocol.get('arms', [])
        contract = 'exemplar_count_only' in protocol.get('arms', [])
        strong_vote = protocol.get('source_run') == 'bailian_qwen38_max0902_fsc_headroom_v1'
        ownership = 'halo_points' in protocol.get('arms', [])
        countingdino = protocol.get('arms') == ['countingdino']
        scalar_format = protocol.get('diagnostic_kind') == 'scalar_format'
        derived_unit = run.name == 'point_unit_normalization_exploratory_v1'
        # Intent progress is available in its safe STATUS. Do not open the raw
        # text predictions merely to count rows for the browser projection.
        predictions = [] if intent or route_task2 else read(run/('BASELINE_PREDICTIONS.json' if nested and status.get('mode')=='baseline' else 'PREDICTIONS.json'), [])
        is_live = alive(status.get('pid'), run.name)
        summary = read(run/'SUMMARY.json') if route_task2 else read(run/status.get('summary_file','SUMMARY.json'), read(run/'PARTIAL_SUMMARY.json'))
        if route_task2 and summary and (summary.get('status') != 'completed_scored' or summary.get('completed_response_records') != summary.get('selected_samples', 32)*(2 if route_schema else 1) or (route_schema and any(summary.get('arms', {}).get(arm, {}).get('completed_response_records') != summary.get('selected_samples', 32) for arm in ['R', 'S']))):
            summary = None  # Route scientific metrics require the complete frozen summary.
        rows = []
        for arm in protocol.get('arms', ['未生成']):
            preds = ([p for p in predictions if arm in p.get('arms', {})] if zoomclick
                     else [p for p in predictions if arm in p] if nested
                     else [p for p in predictions if p.get('arm') == arm])
            score = summary.get('arms', {}).get(arm) if summary else None
            if document and score:
                # Keep the scorer's original summary intact; normalize only the
                # per-arm presentation shared by the read-only research views.
                score = {**score, **score.get('score', {})}
                if 'valid_n' in score and 'valid' not in score:
                    score['valid'] = score['valid_n']
            rows.append({'arm': arm, 'predictions': len(preds), 'score': score})
        experiments.append({'project': 'FastResearch', 'name': run.name, 'status': status.get('state'),
                            'verification': 'local_process_and_artifacts', 'live': is_live,
                            'stale_running': status.get('state') == 'running' and not is_live,
                            'completed': len(predictions) if nested or zoomclick else len(predictions)//max(1,len(protocol.get('arms', []))), 'planned': status.get('planned_samples', 40),
                            'completion_label': '标量格式归因诊断' if scalar_format else '事后派生算子诊断' if derived_unit else 'CPU视觉参考基线' if countingdino else '原图基线' if nested and status.get('mode')=='baseline' else ('强型号基线' if len(protocol['arms'])==1 else '输入契约配对') if contract else '强型号投票配对' if strong_vote else '机制开发配对' if ownership else '完整配对',
                            'updated_at': status.get('verified_at', status.get('updated_at', status.get('completed_at', status.get('started_at')))),
                            'protocol': f"{protocol.get('model', 'local备用')} · 冻结权重 · 开发集 · "+('CPU原版16图块/840px，额外示例位置与计算量单列' if countingdino else ('三视觉示例强型号基线' if len(protocol['arms'])==1 else '类别文字/三视觉示例的输入契约诊断') if contract else '七次调用纠错/投票配对，direct/三次求和预算另列' if nested else '三视觉示例七视图投票，identity复用且全额逻辑计费' if strong_vote else '五主臂各4调用/8192上限；whole_first低预算、halo派生控制全额逻辑计费' if ownership else '同生成上限配对'),
                            'finding': '评分待完成' if summary is None else summary.get('scope', '部分开发诊断；确认集未评测'),
                            'arms': rows, 'summary': summary,
                            'source_key': 'run.'+run.name+('' if (run/'SUMMARY.json').exists() else '.partial' if (run/'PARTIAL_SUMMARY.json').exists() else '.status')})
        if intent:
            mode = protocol['mode']
            control = mode == 'modensemble'
            history_variant = mode == 'controlled_history_variant'
            arm = 'controlled_history_variant' if history_variant else 'direct' if mode == 'direct' else 'arcade'
            completed = status.get('completed_samples', 0)
            planned = status.get('selected_samples', len(protocol.get('sample_ids', [])))
            generation_state = status.get('status', status.get('state'))
            score = summary.get('arms', {}).get(arm) if summary else None
            if summary and score is None:
                score = summary.get('metrics')
            if score:
                score = {'n': summary.get('selected_samples', planned), **score}
            experiments[-1].update({
                'branch_id': 'FR-INTENT',
                'diagnostic_kind': 'intent_history' if history_variant else 'intent_control' if control else 'intent_headroom' if mode == 'direct' else 'intent_arcade',
                'title': 'ARCADE论文历史信息流受控变体（非严格复现）' if history_variant else '七次独立抽样＋同信息Judge（内部强控制）' if control else 'ARCADE / H-VLI 原模型 '+('direct headroom 开发筛选' if mode == 'direct' else 'ARCADE 代码路径开发对照'),
                'status': summary.get('status', 'completed_scored') if summary else generation_state,
                'generation_state': generation_state,
                'generation_actual_calls': status.get('successful_calls'),
                'completed': completed, 'planned': planned,
                'live': is_live, 'stale_running': generation_state == 'running' and not is_live,
                'model': protocol.get('model'), 'original_model': 'qwen3-vl-plus',
                'original_score_reproduced': False, 'independent_replication': False,
                'confirmation_evaluated': False,
                'actual_calls': summary.get('actual_calls', summary.get('successful_calls', status.get('successful_calls'))) if summary else status.get('successful_calls', status.get('paid_calls')),
                'api_cost_cny': summary.get('api_cost_cny', summary.get('cost_cny')) if summary else None,
                'max_logical_calls': protocol.get('max_logical_calls'),
                'active_stage': status.get('active_stage'),
                'completion_label': '官方 train 不同图像开发筛选',
                'protocol': (f"{protocol.get('model')} · ACL 2026 Findings ARCADE 原模型/原提示代码路径 · "
                             f"H-VLI 官方 train / H-VLI_images 子域 {planned} 张不同图像开发；{mode}，每调用输出≤{protocol.get('max_tokens_per_call')}；"
                             '非官方 test 或原论文成绩复现，拒答/无效/缺失计入全样本分母。'),
                'finding': ('启动预检失败，未进入模型推理；旧请求预留保持。' if generation_state == 'preflight_failed' else
                            summary.get('scope', '开发集全样本与条件指标并列；不能视为方法增益或独立复验。') if summary else
                            f'开发预测 {completed}/{planned}；'+('模型预测已完成，等待冻结评分。' if completed >= planned and planned else '完整 headroom 读出尚未形成。')),
                'arms': [{'arm': arm, 'label': '论文历史信息流受控变体' if history_variant else '原始图文直接推理' if mode == 'direct' else 'ARCADE 原代码路径',
                          'predictions': completed, 'score': score}],
            })
            if history_variant:
                comparisons = []
                for name, label in [('HISTORY_VS_ARCADE.json', '原ARCADE代码'), ('HISTORY_VS_SAMPLING_JUDGE.json', '七抽样Judge')]:
                    comparison = read(study/'multimodal_intent'/name, {})
                    if summary and comparison.get('candidate') == run.name:
                        comparisons.append({'control': label, 'paired': comparison.get('paired_full_coverage'),
                                            'costs': comparison.get('costs'), 'scope': comparison.get('scope')})
                experiments[-1]['history_comparisons'] = comparisons
                experiments[-1]['protocol'] = (
                    f"{protocol.get('model')} · 官方 train 同一{planned}图像开发面板；"
                    'ARCADE论文history受控变体，检方读上轮双方、辩方读当轮检方/上轮辩方，Judge读三轮；'
                    '隐式温度0.7→0.8与信息流同时改变，不能单归因history；'
                    '最多8stage/16384输出上限，正常路由2/4/8，异常在1–8stage前缀计错；非严格原法复现、非新方法。')
            if control:
                experiments[-1]['protocol'] = (
                    f"{protocol.get('model')} · 官方 train 同一{planned}图像开发面板；7次全新direct温度0.8＋同图文Judge温度0.1；"
                    '固定8调用/16384输出上限，免费plurality共享7抽样；内部强控制，非ARCADE原法；'
                    '仅同上限，不等于ARCADE自适应2/4/8调用的实际成本相等。')
                experiments[-1]['arms'] = [
                    {'arm': name, 'predictions': completed,
                     'score': summary.get('arms', {}).get(name) if summary else None}
                    for name in protocol.get('arms', ['ensemble_judge', 'plurality'])]
                if not summary:
                    experiments[-1]['finding'] = f'内部采样强控制开发 {completed}/{planned}；尚无完整评分，不作为ARCADE原法或方法增益。'
        if route_task2:
            completed = status.get('completed_samples', 0)
            planned = status.get('selected_samples', protocol.get('selected_samples', 32))
            generation_state = status.get('status', status.get('state'))
            uniform_repair = protocol.get('mode') == 'uniform4096_engineering_repair'
            noimage_control = protocol.get('image_mode') == 'none'
            route_mode_label = ('R/S schema与review普通强控制（非新方法）' if route_schema else '原四示例文本 · 同4096无图内部控制' if noimage_control else
                                '原四示例基线 · 全32统一4096工程纠错' if uniform_repair else '作者四示例 API 适配基准')
            experiments[-1].update({
                'branch_id': 'FR-ROUTE', 'diagnostic_kind': 'route_task2_schema_control' if route_schema else 'route_task2',
                'mode': protocol.get('mode'),
                'title': 'NeSy-Route Task2 '+route_mode_label,
                'status': summary.get('status', 'completed_scored') if summary else generation_state,
                'generation_state': generation_state,
                'generation_actual_calls': status.get('successful_calls'),
                'completed': completed, 'planned': planned,
                'live': is_live, 'stale_running': generation_state == 'running' and not is_live,
                'model': protocol.get('model'), 'original_model': 'qwen3-vl-plus',
                'original_score_reproduced': False, 'independent_replication': False,
                'confirmation_evaluated': False,
                'actual_calls': summary.get('actual_calls', status.get('successful_calls')) if summary else status.get('successful_calls'),
                'input_tokens': summary.get('input_tokens', status.get('input_tokens')) if summary else status.get('input_tokens'),
                'output_tokens': summary.get('output_tokens', status.get('output_tokens')) if summary else status.get('output_tokens'),
                'api_cost_cny': summary.get('cost_cny', summary.get('api_cost_cny')) if summary else None,
                'max_logical_calls': protocol.get('max_logical_calls', planned*(2 if route_schema else 1)),
                'completed_response_records': status.get('completed_response_records', completed),
                'expected_response_records': protocol.get('expected_response_records', planned*(2 if route_schema else 1)),
                'arm_progress': status.get('arms', {}) if route_schema else {},
                'ordinary_control': route_schema,
                'max_tokens_per_call': protocol.get('max_tokens_per_call'),
                'completion_label': 'Task2 评测来源开发；基准适配，非新方法',
                'protocol': (f"{protocol.get('model')} · Task2 {'仅原文本、不传图像' if noimage_control else '官方编号区域原图'}与作者四个文字示例提示；"
                             f"固定 {planned} 个评测来源开发样本，{'每题R/S各一次，最多64次逻辑调用' if route_schema else '每题一次、最多32次逻辑调用'}；"
                             f"每次输出上限 {protocol.get('max_tokens_per_call', '待核')}；"
                             f"{route_mode_label}，非新方法，非论文零样本成绩复现、正式方法比较或独立确认。"),
                'finding': (summary.get('scope', '开发基准完整读出；官方条件分母和固定全样本指标分别报告，非新方法。') if summary else
                            f'开发预测 {completed}/{planned}；完整评分未落盘，不填部分成绩。'),
                'arms': [],
                'protocol_source_key': 'run.'+run.name+'.protocol',
            })
        if zoomclick:
            experiments[-1]['completion_label'] = '已有方法迁移诊断（原模型未复现）'
            experiments[-1]['protocol'] = (str(protocol.get('model')) + ' · ZoomClick API迁移 · 原图首答/七次原图medoid/多尺度搜索 · 最多7调用每臂；不是论文原模型')
        if document:
            expected_arms = protocol.get('arms', [])
            page_arms = {}
            for prediction in predictions:
                if prediction.get('arm') in expected_arms and prediction.get('id') is not None:
                    page_arms.setdefault(prediction['id'], set()).add(prediction['arm'])
            ceilings = protocol.get('total_ceiling_per_arm', {})
            cap = protocol.get('max_completion_tokens', {})
            planned = status.get('planned_samples', len(protocol.get('sample_ids', [])))
            completed_pages = sum(set(expected_arms) <= present for present in page_arms.values()) if expected_arms else 0
            coordinator = read(run/'COORDINATOR.json', {})
            scoring_paths = [p for p in run.glob('scoring_v*/STATUS.json')
                             if re.fullmatch(r'scoring_v\d+', p.parent.name)]
            scoring_path = max(scoring_paths, key=lambda p: int(p.parent.name.split('_v')[1])) if scoring_paths else None
            scoring = read(scoring_path, {}) if scoring_path else {}
            scoring_live = document_scoring_alive(scoring.get('pid'), run.name) if scoring else False
            experiments[-1].update({
                'branch_id': 'FR-DOC', 'diagnostic_kind': 'document_order_screen',
                'model': protocol.get('model'), 'original_model': 'qwen3.6-plus',
                'original_score_reproduced': False, 'independent_replication': False,
                'confirmation_evaluated': False,
                'completed': completed_pages,
                'planned': planned, 'planned_page_arm_pairs': planned * len(expected_arms),
                'completed_page_arm_pairs': sum(len(present) for present in page_arms.values()),
                'actual_calls': summary.get('actual_calls') if summary else status.get('actual_calls'),
                'api_cost_cny': summary.get('api_cost_cny') if summary else status.get('api_cost_cny'),
                'total_token_ceilings': ceilings,
                'generation_state': status.get('state'),
                'generation_stale_running': status.get('state') == 'running' and not is_live,
                'generation_updated_at': status.get('updated_at'),
                'generation_actual_calls': status.get('actual_calls'),
                'generation_api_cost_cny': status.get('api_cost_cny'),
                'call_cost_source': 'official_summary' if summary else 'generation_status_snapshot',
                'coordinator': {**{k: coordinator[k] for k in ['state', 'pid', 'updated_at', 'run_id'] if k in coordinator},
                                'source_key': 'run.'+run.name+'.coordinator'} if coordinator else None,
                'scoring': {**{k: scoring[k] for k in ['state', 'pid', 'updated_at', 'elapsed_seconds', 'benchmark_pages', 'completed_arms', 'active_arm', 'current_arm', 'error'] if k in scoring},
                            'live': scoring_live, 'version': scoring_path.parent.name,
                            'source_key': 'run.'+run.name+'.'+scoring_path.parent.name+'.status'} if scoring_path else None,
                'completion_label': '文档开发页四臂完整配对',
                'protocol': (f"{protocol.get('model')} · 原API型号/提示迁移至OmniDocBench开发{planned}页 × {len(expected_arms)}臂；"
                    f"首答总token≤{ceilings.get('direct', cap.get('direct', '待核'))}，等预算直出≤{ceilings.get('direct_equal_budget', cap.get('direct_equal_budget', '待核'))}；"
                    f"两种修复共享首答+各≤{cap.get('repair', '待核')}，包含思考与答案；非论文原分数复现、无独立复验。"),
                'finding': (('四臂完整开发预测，官方评分尚未完成；未作独立确认。'
                             if planned > 0 and completed_pages >= planned
                             else f'开发预测进行中 {completed_pages}/{planned} 页四臂完成；官方评分尚未完成，未作独立确认。')
                            if summary is None else '官方scorer开发读出；完整对照、有效分母与冻结门见汇总，不等于独立验证。'),
            })
            # A scorer may call its frozen screen gate gate_passed; expose that
            # fact without changing the original JSON or granting a race gate.
            if summary and summary.get('gate_passed') is not None:
                experiments[-1]['screen_gate_passed'] = summary['gate_passed']
                if summary['gate_passed'] is False:
                    experiments[-1]['finding'] = '文档版本未通过冻结开发门；停止扩展，保留全部对照及负证据。'
            if summary and summary.get('status') == 'completed_scoring':
                experiments[-1]['status'] = 'completed_scored'
                experiments[-1]['stale_running'] = False
                experiments[-1]['updated_at'] = (summary.get('reviewed_at') or summary.get('verified_at')
                                                or scoring.get('updated_at') or experiments[-1]['updated_at'])
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
        if document:
            audit = read(run/'MECHANISM_AUDIT.json', {})
            if audit.get('run_id') == run.name and audit.get('status') == 'completed_development_mechanism_audit':
                experiments[-1]['mechanism_audit'] = {**{k: audit[k] for k in
                    ['status', 'adjudication', 'finding', 'reviewed_at', 'scope', 'ui_required_conclusions'] if k in audit},
                    'source_key': 'run.'+run.name+'.mechanism_audit'}
                experiments[-1]['finding'] = audit.get('finding') or experiments[-1]['finding']
    ledger = read(study/'API_LEDGER.json', {})
    for experiment in experiments:
        if experiment.get('verification') == 'local_process_and_artifacts':
            attempts = [a for a in ledger.get('attempts', {}).values() if a['run_id'] == experiment['name']]
            experiment['requests'] = {'attempts': len(attempts), 'successful': sum(a['status'] == 'settled' for a in attempts),
                                      'unsettled': sum(a['status'] != 'settled' for a in attempts),
                                      'retries': sum(a.get('attempt_index', 1) > 1 for a in attempts)}
            if experiment.get('diagnostic_kind') in {'document_order_screen', 'intent_headroom', 'intent_arcade', 'intent_control', 'intent_history', 'route_task2', 'route_task2_schema_control'} and not experiment.get('summary') and attempts:
                # Page-boundary STATUS snapshots can lag settled response receipts.
                # Use the existing ledger aggregate, never raw model call records.
                experiment['actual_calls'] = experiment['requests']['successful']
                if experiment.get('diagnostic_kind') in {'intent_control', 'intent_history', 'route_task2', 'route_task2_schema_control'}:
                    experiment['actual_calls'] = experiment['requests']['attempts']
                    experiment['successful_logical_calls'] = experiment['generation_actual_calls']
                experiment['api_cost_cny'] = sum(float(a.get('cost_cny') or 0) for a in attempts if a['status'] == 'settled')
                experiment['call_cost_source'] = 'api_ledger_settled'
    budget = {k: ledger.get(k) for k in ['cap_cny', 'estimated_settled_cny', 'unresolved_reserved_cny', 'conservative_total_cny', 'updated_at']}
    for entry in pool['entries']:
        entry['evidence'] = [{**e, 'source_key': 'experience.'+entry['id']+'.'+str(i), **stamp(Path(e['path']))}
                             for i, e in enumerate(entry['evidence'])]
    document_links = {name: key for key, path in sources().items() if path.is_file()
                      for name in {str(path), str(path.resolve())}}
    portfolio = read(study/'PORTFOLIO.json', {})
    portfolio = project_routes(portfolio, read(ROOT/'data/submission_venues.json', {}),
        read(study.parent/'PROJECT.json', {}),
        {key: value for key, value in
         [('FR-GUI', read(study/'gui/METHOD_ITERATION.json')),
          ('FR-DOC', read(study/'document/METHOD_ITERATION.json'))] if value})
    # Candidate review is literature/implementation evidence, not additional jobs.
    baseline_review = read(study/'BASELINES.json', {})
    portfolio['baseline_candidates'] = [{key: item.get(key) for key in
        ['method', 'version', 'publication', 'paper_url', 'api_model', 'api_available',
         'original_models', 'decision', 'reason', 'code_status']}
        for item in baseline_review.get('recent_review', [])]
    by_run = {e['name']: e for e in experiments if e.get('verification') == 'local_process_and_artifacts'}
    for branch in portfolio.get('branches', []):
        current = by_run.get(branch.get('current_run'))
        branch['runtime'] = ({key: current.get(key) for key in
            ['name', 'status', 'live', 'stale_running', 'completed', 'planned', 'updated_at', 'requests', 'source_key']}
            if current else {'live': False, 'status': 'not_started', 'completed': None, 'planned': None})
    # Route remains a CPU-admission candidate until root registers a branch.
    # Allocation is permission, never evidence that images are ready or paid.
    route_metadata = read(study/'route/METADATA_EXTRACTION.json', {}).get('aggregate_after_authorized_expansion', {})
    route_allocation = read(study/'route/DATA_PREPARATION_ALLOCATION.json', {})
    preparation_path = study/'route/data/development32_prepared/PREPARATION_RECEIPT.json'
    preparation_receipt = read(preparation_path, {})
    # The receipt also has per-group transport/target details. Expose aggregate
    # counters only, never image locations, target sources or raw receipt text.
    preparation = {k: preparation_receipt[k] for k in [
        'status', 'selected_images_saved', 'selected_pixel_decode_count',
        'unselected_pixel_decode_count', 'unselected_raw_images_persisted',
        'unselected_target_rows_persisted', 'paid_model_calls', 'gpu_used',
        'downloaded_body_bytes', 'budget_charged_body_bytes', 'byte_cap',
        'elapsed_seconds', 'max_rss_bytes'] if k in preparation_receipt}
    if preparation:
        preparation['updated_at'] = stamp(preparation_path).get('modified_at')
    route_runs = [e for e in by_run.values() if e.get('diagnostic_kind') in {'route_task2', 'route_task2_schema_control'}]
    route_latest = max(route_runs, key=lambda e: e.get('updated_at') or '', default=None)
    route_candidate = {
        'id': 'FR-ROUTE', 'role': 'cpu_admission_candidate',
        'status': 'execution_record' if route_latest else 'data_preparation',
        'selected_samples': route_metadata.get('selected_count'),
        'image_transfer_cap_bytes': route_allocation.get('image_physical_transfer_cap_bytes'),
        'images_ready': None, 'preparation': preparation or None,
        'preparation_acceptance': read(study/'route/data/development32_prepared/PREPARATION_ACCEPTANCE.json'),
        'visual_input_audit': read(study/'route/VISUAL_INPUT_AUDIT_PUBLIC_SUMMARY.json'),
        'current_run': route_latest.get('name') if route_latest else None,
        'runtime': {k: route_latest.get(k) for k in ['name', 'status', 'live', 'completed', 'planned', 'source_key']} if route_latest else None,
        'scope': 'Task2 评测来源开发候选；已有 easy 预览曝光保留，跨来源独立性未知。基准适配不是新方法或正式方法比较。',
    } if route_metadata or route_allocation or route_runs else None
    portfolio['observed_runtime'] = {
        'active_candidates': sum(b['stage'] not in {'stopped', 'saturated', 'archived'} for b in portfolio.get('branches', [])),
        'live_jobs': sum(bool(e.get('live')) for e in by_run.values()),
        'stale_running_jobs': sum(bool(e.get('stale_running')) for e in by_run.values()),
        'independent_passes': sum('replication' in b.get('passed_gates', []) for b in portfolio.get('branches', [])),
        'confirmation_passes': sum('confirmation' in b.get('passed_gates', []) for b in portfolio.get('branches', [])),
        'observed_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    }
    return {'schema_version': 2, 'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'axes': board['axes'], 'projects': projects, 'experiments': experiments, 'experiences': pool['entries'],
            'document_links': document_links, 'portfolio': portfolio,
            'route_candidate': route_candidate,
            'budget': budget, 'maintenance': board.get('maintenance'),
            'shared_race': read(SHARED_RACE, {}),
            'verification_policy': '本页刷新只读本地文件。FastResearch本机run可核进程；OPD远端资源以共同赛马记录的实查时刻为准，刷新不重新SSH。其他研究为来源快照，未据本页重新查询远端。'}

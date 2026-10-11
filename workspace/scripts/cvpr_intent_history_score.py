"""Offline complete-panel score for the controlled paper-history supplement.

Only CLI opens selected development targets, after frozen inference completes.
"""
import argparse
import fcntl
import importlib
import json
from pathlib import Path
import time

from cvpr_chart_api import now
from cvpr_chart_run import PROJECT, ROOT, atomic_json, sha
from cvpr_intent_control_score import score_arm, resource_metrics
from cvpr_intent_control_run import valid_label
from cvpr_intent_history_run import (BASE, CAP, MODEL, MODE, DIRECT_STAGES,
    INDIRECT_STAGES, implementation_hashes, load_upstream, parse_stage, stage_invalid, safe_run_id)


def validate_panel(predictions, calls, ids):
    if (len(ids) != 32 or len(set(ids)) != 32 or len(predictions) != 32
            or len({p['id'] for p in predictions}) != 32
            or {p['id'] for p in predictions} != set(ids)):
        raise ValueError('Only the complete frozen32 development panel may be scored')
    routes = {'error': ('gate',), 'safe': ('gate', 'implicit-p1'),
              'direct_standard': DIRECT_STAGES, 'indirect_multiround': INDIRECT_STAGES}
    expected = set()
    for prediction in predictions:
        route = routes.get(prediction['result'].get('final_stage'))
        if prediction['result'].get('final_stage') == 'error':
            candidate = tuple(prediction.get('stage_keys', []))
            if (not candidate or not any(candidate == stages[:len(candidate)] for stages in [DIRECT_STAGES, INDIRECT_STAGES])
                    or prediction['result'].get('failure_stage') != candidate[-1]):
                raise ValueError('Invalid-case stage trace is not a frozen route prefix')
            if valid_label(prediction['result'].get('verdict')) is not None:
                raise ValueError('Invalid-stage case cannot carry a valid final label')
            route = candidate
        if route is None or prediction.get('stage_keys') != list(route) or prediction.get('logical_calls') != len(route):
            raise ValueError('Prediction does not follow frozen adaptive route')
        if prediction['result'].get('final_stage') == 'indirect_multiround' and [x.get('round') for x in prediction['result'].get('history', [])] != [1,2,3]:
            raise ValueError('Indirect final judge needs all three ordered round pairs')
        expected.update(prediction['id']+'|'+stage for stage in route)
    if len(calls) != len(expected) or {c['key'] for c in calls} != expected:
        raise ValueError('Incomplete, duplicate or unrelated stage resource receipts')
    court, _ = load_upstream()
    by_id = {p['id']: p for p in predictions}
    for call in calls:
        if (call.get('status') != 'ok' or call.get('requested_model') != MODEL
                or call.get('token_cap') != CAP or not 0 <= call['output_tokens'] <= CAP
                or call['input_tokens'] < 0):
            raise ValueError('Invalid successful-stage resource receipt')
        sid, stage = call['key'].split('|')
        parsed = parse_stage(court, call['text'])
        invalid = stage_invalid(stage, parsed, call.get('truncated'))
        if invalid and (by_id[sid]['result'].get('final_stage') != 'error'
                        or by_id[sid]['result'].get('failure_stage') != stage):
            raise ValueError('Invalid/truncated stage cannot receive a valid final score')


def score_panel(predictions, calls, ids, labels, official_calculate):
    validate_panel(predictions, calls, ids)
    if set(labels) != set(ids) or any(type(v.get('final_label')) is not int or v['final_label'] not in range(6) for v in labels.values()):
        raise ValueError('Only complete frozen development targets may be scored')
    results = {p['id']: p['result']['verdict'] for p in predictions}
    score = score_arm(results, ids, labels, official_calculate)
    return {'metrics': score['metrics'], 'official_metrics': score['official_metrics'],
            'routing_counts': {stage: sum(p['result']['final_stage'] == stage for p in predictions)
                               for stage in ['error', 'safe', 'direct_standard', 'indirect_multiround']}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    safe_run_id(args.run_id)
    run = BASE/'runs'/args.run_id
    with (run/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol = json.loads((run/'PROTOCOL.json').read_text())
        status = json.loads((run/'STATUS.json').read_text())
        if (protocol.get('kind') != 'intent_history' or protocol.get('mode') != MODE
                or status.get('status') not in {'model_completed', 'completed'}
                or protocol['implementation_sha256'] != implementation_hashes()):
            raise ValueError('Only a frozen completed controlled-history run may be scored')
        for name,digest in protocol['implementation_sha256'].items():
            if sha((run/'SOURCE_SNAPSHOTS'/name).read_bytes()) != digest:
                raise ValueError('Frozen source snapshot changed')
        if sha((run/'SOURCE_SNAPSHOTS/PAPER_HISTORY_CONTRACT.json').read_bytes()) != protocol['paper_history_contract_sha256']:
            raise ValueError('Frozen paper-history contract changed')
        predictions = json.loads((run/'PREDICTIONS.json').read_text())
        ids = protocol['sample_ids']
        calls = [json.loads(line) for line in (run/'calls.jsonl').read_text().splitlines()]
        validate_panel(predictions, calls, ids)
        labels_path = BASE/'data/selected_labels_sealed.json'
        reference = json.loads((BASE/'runs/bailian_qwen3vlplus_intent_direct_screen_v2/SUMMARY.json').read_text())
        if sha(labels_path.read_bytes()) != reference['selected_labels_sha256']:
            raise ValueError('Selected development target file changed')
        labels = json.loads(labels_path.read_text())
        _, receipt = load_upstream()
        if receipt['files'] != protocol['source_files'] or receipt['revision'] != protocol['upstream_revision']:
            raise ValueError('Original source/scorer changed')
        official = importlib.import_module('evaluator')
        if Path(official.__file__).resolve().parent != (BASE/'sources/ARCADE-contract').resolve():
            raise ValueError('Wrong original scorer module')
        tick = time.monotonic()
        result = score_panel(predictions, calls, ids, labels, official.calculate_metrics)
        ledger = json.loads((PROJECT/'API_LEDGER.json').read_text())
        attempts = {key: value for key,value in ledger['attempts'].items() if value['run_id'] == args.run_id}
        for call in calls:
            attempt = attempts.get(call['ledger_key'])
            if not attempt or attempt['key'] != call['key']:
                raise ValueError('Response lacks durable physical-attempt ledger')
        summary = {
            'run_id': args.run_id, 'kind': 'intent_history', 'diagnostic_kind': 'intent_history',
            'mode': MODE, 'model': MODEL, 'title': protocol['title'], 'status': 'completed_scored',
            'selected_samples': 32, 'completed_samples': 32, 'created_at': now(), **result,
            'attempts': len(attempts), 'actual_attempts': len(attempts), 'actual_calls': len(attempts),
            'successful_calls': len(calls), 'successful_logical_calls': len(calls),
            'unknown_attempts': sum(a['status'] != 'settled' for a in attempts.values()),
            'truncated_calls': sum(bool(c.get('truncated')) for c in calls),
            'input_tokens': sum(c['input_tokens'] for c in calls),
            'output_tokens': sum(c['output_tokens'] for c in calls),
            'cost_cny': sum(a.get('cost_cny', 0) for a in attempts.values()),
            'conservative_cost_cny': sum(a.get('cost_cny', a['reserved_cny']) for a in attempts.values()),
            'successful_path_resources': resource_metrics(calls),
            'resources': {'maximum_successful_stages_per_sample': 8,
                          'maximum_successful_output_tokens_per_sample': 16384,
                          'same_upper_bound_not_equal_realized_cost': True,
                          'retry_unknown_usage_is_not_zero': True},
            'gate': {'next_action': 'root_controlled_history_paired_analysis_required', 'expansion_authorized': False},
            'scope': '已曝光H-VLI-source train32上的ARCADE论文history受控变体补充；非严格原法复现、非新方法。',
            'limitations': [
                '隐式消息依赖及温度.7→.8共同改变，不能单独归因history。',
                '原文没有唯一确定JSON序列化和轮2/3提示，显式标记controlled_history_variant。',
                '正常safe/direct/implicit为2/4/8stage；内容异常在1–8stage前缀终止并计全样本错误；同上限不等于实耗一致。',
                '全部拒答、无效、缺失算全32错误，官方条件宽松评分另列。',
                '开发面板存在重复语义主题，路径/hash不同不是独立来源；未开确认。',
                '成功路径tokencap不覆盖失败HTTP未知用量；保留未知全额预留。'],
            'original_score_reproduced': False, 'independent_replication': False,
            'confirmation_evaluated': False, 'publication_ready': False,
            'evidence_sha256': {name: sha((run/name).read_bytes()) for name in ['PROTOCOL.json','PREDICTIONS.json','calls.jsonl']},
            'paper_history_contract_sha256': protocol['paper_history_contract_sha256'],
            'selected_labels_sha256': sha(labels_path.read_bytes()),
            'scorer_source_sha256': sha((BASE/'sources/ARCADE-contract/evaluator.py').read_bytes()),
            'cpu_score_seconds': time.monotonic()-tick}
        if (run/'SUMMARY.json').exists():
            old = json.loads((run/'SUMMARY.json').read_text())
            if old['evidence_sha256'] != summary['evidence_sha256'] or old['metrics'] != summary['metrics']:
                raise ValueError('Existing scientific summary changed')
            print(json.dumps({'status': 'already_scored', 'run_id': args.run_id}))
            return
        atomic_json(run/'SUMMARY.json', summary)
        status.update(status='completed', scored_at=now(), summary_sha256=sha((run/'SUMMARY.json').read_bytes()))
        atomic_json(run/'STATUS.json', status)
        print(json.dumps({key: summary[key] for key in ['run_id','kind','cost_cny','attempts','successful_calls','truncated_calls']}))


if __name__ == '__main__':
    main()

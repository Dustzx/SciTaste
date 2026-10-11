"""Offline score for the frozen seven-draw sampling control.

Only main(), after complete inference, opens the selected development labels.
Candidate/oracle coverage is an offline diagnostic, never a prediction arm.
"""
import argparse
import fcntl
import importlib
import json
from pathlib import Path
import time

from cvpr_chart_api import now
from cvpr_chart_run import PROJECT, ROOT, atomic_json, sha
from cvpr_intent_control_run import (BASE, CAP, DRAWS, MODEL, STAGES,
                                     implementation_hashes, load_upstream,
                                     plurality, safe_run_id, valid_label)


def score_arm(results, ids, labels, official_calculate):
    correct = binary_correct = refused = invalid = missing = 0
    for sid in ids:
        if sid not in results:
            missing += 1
            continue
        verdict = results[sid]
        if isinstance(verdict, dict) and verdict.get('refusal') is True:
            refused += 1
            continue
        label = valid_label(verdict)
        if label is None:
            invalid += 1
            continue
        target = labels[sid]['final_label']
        correct += label == target
        binary_correct += (label > 0) == (target > 0)
    # Preserve the author's permissive parser/conditional denominator separately
    # from strict full-panel validity. Never alter invalid labels using the GT.
    official_input = {sid: verdict if isinstance(verdict, dict) else {'label': None}
                      for sid, verdict in results.items()}
    official = official_calculate(official_input, labels, mode='multiclass')
    n = len(ids)
    metrics = {'full_accuracy': correct/n, 'correct': correct,
               'full_binary_accuracy': binary_correct/n, 'binary_correct': binary_correct,
               'conditional_accuracy': (official['global']['strict_correct']/official['global']['total']
                                        if official['global']['total'] else None),
               'official_counted_samples': official['global']['total'],
               'official_macro_f1': official['sklearn'].get('f1_macro'),
               'valid': n-refused-invalid-missing, 'refused_count': refused,
               'invalid_count': invalid, 'missing_count': missing}
    return {'n': n, 'metrics': metrics, 'official_metrics': official}


def score_panel(predictions, ids, labels, official_calculate):
    if (len(ids) != 32 or len(set(ids)) != 32 or len(predictions) != 32
            or {p['id'] for p in predictions} != set(ids)
            or len({p['id'] for p in predictions}) != 32 or set(labels) != set(ids)):
        raise ValueError('Only the complete frozen 32-image development panel may be scored')
    for target in labels.values():
        if type(target.get('final_label')) is not int or target['final_label'] not in range(6):
            raise ValueError('Invalid selected development target schema')
    arms = {'ensemble_judge': {}, 'plurality': {}}
    oracle_hit = any_valid = all_valid = valid_draws = judge_hit = judge_missed_available = 0
    for prediction in predictions:
        sid, drafts = prediction['id'], prediction['drafts']
        if len(drafts) != DRAWS or prediction.get('logical_calls') != 8:
            raise ValueError('Incomplete fixed seven-draw-plus-judge record')
        if prediction['plurality'] != plurality(drafts):
            raise ValueError('Free vote does not match the frozen deterministic rule')
        arms['ensemble_judge'][sid] = prediction['ensemble_judge']
        arms['plurality'][sid] = prediction['plurality']
        candidates = [valid_label(draft) for draft in drafts]
        valid = [label for label in candidates if label is not None]
        valid_draws += len(valid)
        any_valid += bool(valid)
        all_valid += len(valid) == DRAWS
        hit = labels[sid]['final_label'] in valid
        oracle_hit += hit
        judge_correct = valid_label(prediction['ensemble_judge']) == labels[sid]['final_label']
        judge_hit += hit and judge_correct
        judge_missed_available += hit and not judge_correct
    return {
        'arms': {arm: score_arm(results, ids, labels, official_calculate) for arm, results in arms.items()},
        'offline_candidate_diagnostics': {
            'scope': '仅在完整生成结束后使用开发标签；不是可部署实验臂或方法收益。',
            'oracle_candidate_coverage_at7': oracle_hit/len(ids), 'oracle_hit_count': oracle_hit,
            'valid_candidate_coverage_at7': any_valid/len(ids), 'at_least_one_valid_count': any_valid,
            'all_seven_valid_count': all_valid, 'valid_draw_count': valid_draws,
            'total_draw_count': len(ids)*DRAWS,
            'judge_correct_with_candidate_hit_count': judge_hit,
            'judge_missed_available_candidate_count': judge_missed_available,
            'deployable': False, 'selected_samples': len(ids),
        },
    }


def validate_calls(calls, ids):
    expected = {sid+'|'+stage for sid in ids for stage in STAGES}
    if len(calls) != len(expected) or {call['key'] for call in calls} != expected:
        raise ValueError('Scoring requires every one of the 256 successful-path stages')
    for call in calls:
        if (call.get('status') != 'ok' or call.get('requested_model') != MODEL
                or call.get('token_cap') != CAP or not 0 <= call['output_tokens'] <= CAP
                or call['input_tokens'] < 0):
            raise ValueError('Invalid successful response resource receipt')


def resource_metrics(calls):
    return {'logical_calls': len(calls),
            'logical_input_tokens': sum(call['input_tokens'] for call in calls),
            'logical_output_tokens': sum(call['output_tokens'] for call in calls),
            'logical_api_cost_cny': sum(call['api_cost_cny'] for call in calls),
            'logical_seconds': sum(call.get('elapsed_seconds', 0) for call in calls)}


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
        if (protocol.get('kind') != 'intent_control' or protocol.get('mode') != 'modensemble'
                or status.get('status') not in {'model_completed', 'completed'}
                or protocol['implementation_sha256'] != implementation_hashes()):
            raise ValueError('Only the frozen, completed sampling control may be scored')
        for name, digest in protocol['implementation_sha256'].items():
            if sha((run/'SOURCE_SNAPSHOTS'/name).read_bytes()) != digest:
                raise ValueError('Frozen source snapshot changed')
        predictions = json.loads((run/'PREDICTIONS.json').read_text())
        ids = protocol['sample_ids']
        calls = [json.loads(line) for line in (run/'calls.jsonl').read_text().splitlines()]
        validate_calls(calls, ids)
        # No confirmation or alternative label path is accepted by this CLI.
        labels_path = BASE/'data/selected_labels_sealed.json'
        reference = json.loads((BASE/'runs/bailian_qwen3vlplus_intent_direct_screen_v2/SUMMARY.json').read_text())
        if sha(labels_path.read_bytes()) != reference['selected_labels_sha256']:
            raise ValueError('Selected labels changed after the frozen direct screen')
        labels = json.loads(labels_path.read_text())
        _, receipt = load_upstream()
        if receipt['files'] != protocol['source_files'] or receipt['revision'] != protocol['upstream_revision']:
            raise ValueError('Official scorer source differs from the frozen control')
        official = importlib.import_module('evaluator')
        if Path(official.__file__).resolve().parent != (BASE/'sources/ARCADE-contract').resolve():
            raise ValueError('Wrong official scorer module')
        tick = time.monotonic()
        result = score_panel(predictions, ids, labels, official.calculate_metrics)
        ledger = json.loads((PROJECT/'API_LEDGER.json').read_text())
        attempts = [value for value in ledger['attempts'].values() if value['run_id'] == args.run_id]
        attempt_by_key = {key: value for key, value in ledger['attempts'].items() if value['run_id'] == args.run_id}
        for call in calls:
            attempt = attempt_by_key.get(call['ledger_key'])
            if not attempt or attempt['key'] != call['key']:
                raise ValueError('Response lacks a matching durable ledger reservation')
        draws = [call for call in calls if call['stage'].startswith('draw-')]
        result['arms']['ensemble_judge'].update(resource_metrics(calls))
        result['arms']['plurality'].update(resource_metrics(draws))
        result['arms']['plurality']['additional_calls_for_derivation'] = 0
        summary = {
            'run_id': args.run_id, 'kind': 'intent_control', 'diagnostic_kind': 'intent_control',
            'model': MODEL, 'mode': 'modensemble', 'status': 'completed_scored',
            'selected_samples': 32, 'completed_samples': 32, 'created_at': now(), **result,
            'attempts': len(attempts), 'actual_attempts': len(attempts),
            'successful_calls': len(calls), 'successful_logical_calls': len(calls),
            'actual_calls': len(attempts),
            'unknown_attempts': sum(a['status'] != 'settled' for a in attempts),
            'truncated_calls': sum(bool(call.get('truncated')) for call in calls),
            'input_tokens': sum(call['input_tokens'] for call in calls),
            'output_tokens': sum(call['output_tokens'] for call in calls),
            'cost_cny': sum(a.get('cost_cny', 0) for a in attempts),
            'conservative_cost_cny': sum(a.get('cost_cny', a['reserved_cny']) for a in attempts),
            'resources': {'successful_path_calls_per_sample': 8, 'successful_path_output_ceiling_per_sample': 16384,
                          'plurality_shared_draws': 224, 'additional_plurality_api_calls': 0,
                          'same_upper_bound_not_equal_realized_arcade_cost': True,
                          'retry_unknown_usage_is_not_zero': True,
                          'per_arm_logical_costs_share_draws_do_not_sum': True},
            'gate': {'next_action': 'root_paired_analysis_required', 'expansion_authorized': False},
            'scope': '官方 H-VLI-source train 32 图像开发内部采样控制；非 ARCADE 原法、非独立验证/确认。',
            'limitations': [
                '相同 8 调用/16384 输出上限不等于 ARCADE 自适应 2/4/8 调用的逐题实耗相等，须同时报告真实调用、token、费用。',
                '免费投票与 Judge 共享七次抽样，分臂逻辑成本不能相加当物理总费用。',
                '路径/哈希去重不证明语义或来源独立；供应商滚动模型权重 revision 与随机独立性未知。',
                '拒答、无效、缺失均保留全样本错误；官方条件 scorer 的宽松解析及分母另列。',
                '候选覆盖/oracle@7 仅离线开发诊断，不是可部署准确率，不据此筛选或重试生成。',
                '成功路径上限不含失败 HTTP 尝试的未知用量；旧未知保守预留全部保留。',
            ],
            'original_score_reproduced': False, 'independent_replication': False,
            'confirmation_evaluated': False, 'publication_ready': False,
            'evidence_sha256': {name: sha((run/name).read_bytes()) for name in ['PROTOCOL.json', 'PREDICTIONS.json', 'calls.jsonl']},
            'selected_labels_sha256': sha(labels_path.read_bytes()),
            'scorer_source_sha256': sha((BASE/'sources/ARCADE-contract/evaluator.py').read_bytes()),
            'cpu_score_seconds': time.monotonic() - tick,
        }
        if (run/'SUMMARY.json').exists():
            old = json.loads((run/'SUMMARY.json').read_text())
            if old['evidence_sha256'] != summary['evidence_sha256'] or old['arms'] != summary['arms']:
                raise ValueError('Existing scientific summary changed; preserve prior evidence')
            print(json.dumps({'status': 'already_scored', 'run_id': args.run_id}))
            return
        atomic_json(run/'SUMMARY.json', summary)
        status.update(status='completed', scored_at=now(), summary_sha256=sha((run/'SUMMARY.json').read_bytes()))
        atomic_json(run/'STATUS.json', status)
        print(json.dumps({key: summary[key] for key in ['run_id', 'kind', 'cost_cny', 'attempts', 'successful_calls', 'truncated_calls']}))


if __name__ == '__main__':
    main()

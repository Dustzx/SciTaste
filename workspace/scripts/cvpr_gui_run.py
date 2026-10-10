"""Bounded high-resolution GUI headroom baseline. Inference never opens labels."""
import argparse
import base64
import fcntl
import json
import math
import os
import threading
import time
from pathlib import Path

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha

BASE = PROJECT / 'gui'
CAP = 1024
MODEL = 'qwen3.8-max-0902'
SYSTEM = 'Use the supplied screenshot to ground the user instruction. Return only the requested JSON object.'
PROMPT = ('Identify the UI element that should be clicked to carry out the instruction in this screenshot. '
          'Inspect the full screenshot carefully, check the element identity and its position, then choose a point '
          'inside the intended clickable element. Coordinates refer to the entire original screenshot, normalized '
          'to [0,1000]: [0,0] is top-left and [1000,1000] is bottom-right. Return ONLY JSON '
          '{"reasoning":"brief visual evidence and coordinate check","point":[x,y]}. '
          'Do not execute the action. Instruction: ')


def point(call):
    obj = call.get('parsed')
    p = obj.get('point') if isinstance(obj, dict) else None
    if call.get('truncated') or not isinstance(p, list) or len(p) != 2:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1000 for v in p):
        return None
    return [v / 1000 for v in p]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--stop-after', type=int, default=32)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    assert args.run_id.replace('_', '').replace('-', '').isalnum() and 1 <= args.stop_after <= 32
    data, source = BASE / 'data', BASE / 'sources'
    manifest = json.loads((data / 'MANIFEST.json').read_text())
    for name in ['development_inputs.jsonl', 'screen_ids.json']:
        assert sha((data / name).read_bytes()) == manifest['files'][name]
    rows = list(map(json.loads, (data / 'development_inputs.jsonl').read_text().splitlines()))
    ids = json.loads((data / 'screen_ids.json').read_text())
    assert [r['id'] for r in rows] == ids and len(ids) == len(set(ids)) == 32
    for row in rows:
        assert row['partition'] == 'development' and not {'bbox', 'answer', 'point', 'instruction_cn'} & set(row)
        assert sha((ROOT / row['image']['path']).read_bytes()) == row['image']['sha256']
    run = BASE / 'runs' / args.run_id
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / '.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    api_lock = (PROJECT / '.api-single-worker.lock').open('a')
    fcntl.flock(api_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
    current_unknown = {k: v for k, v in ledger['attempts'].items() if v['status'] != 'settled'}
    for entry in current_unknown.values():
        proc = Path('/proc') / str(entry['pid']) / 'cmdline'
        assert not proc.exists() or entry['run_id'].encode() not in proc.read_bytes()
    old_protocol = json.loads((run / 'PROTOCOL.json').read_text()) if (run / 'PROTOCOL.json').exists() else None
    frozen = ['cvpr_gui_run.py', 'cvpr_gui_score.py', 'cvpr_api_retry.py', 'cvpr_chart_api.py', 'cvpr_chart_run.py']
    protocol = {'model': MODEL, 'weight_revision': None, 'temperature': 0, 'thinking': False,
                'training': False, 'local_gpu': False, 'arms': ['direct'], 'sample_ids': ids,
                'diagnostic_kind': 'gui_headroom', 'benchmark': 'ScreenSpot-Pro',
                'scope': '32 stratified public-test groups designated development before inference; headroom only, no proposed method or confirmation',
                'input': 'One original PNG screenshot and English task instruction only; no boxes, labels, application metadata, OCR or external expert',
                'resolution': {'client_resize': False, 'vl_high_resolution_images': True,
                               'provider_max_pixels': 16777216, 'provider_actual_raster': None,
                               'limitation': 'Provider preprocessing/weights not observable. Images above the documented pixel limit are provider-scaled.'},
                'caps': {'per_call': CAP, 'per_paid_arm': CAP}, 'calls_per_paid_arm': 1,
                'prompts': {'system': SYSTEM, 'instruction_prefix': PROMPT},
                'coordinates': 'Continuous normalized 0..1000 converted to unit coordinates; no clamp or oracle correction',
                'scorer': 'Official eval_sample_positive_gt, inclusive bbox; malformed/truncated outputs wrong in full denominator',
                'phase_cap_cny': 40, 'project_cap_cny': 300, 'workers': 1, 'prices': PRICES[MODEL],
                'expected_settled_cny': 7, 'maximum_new_logical_calls': 32,
                'retained_unknown': old_protocol['retained_unknown'] if old_protocol else current_unknown,
                'manifest_sha256': sha((data / 'MANIFEST.json').read_bytes()),
                'official_scorer_sha256': sha((source / 'eval_screenspot_pro.py').read_bytes()),
                'source_sha256': {name: sha((ROOT / 'scripts' / name).read_bytes()) for name in frozen},
                'interface_gate': 'First2 both parse valid and no truncation; inspect format/model/throughput only, no correctness before full32',
                'stopping_rule': 'Exactly32 fixed groups once. At least30 valid required. Accuracy>=85% stops saturated branch; below85% only admits an error audit, not a method promotion. No prompt/resolution/cap sweep or confirmation access.',
                'grouping_limit': manifest['grouping_limit'], 'confirmation_evaluated': False}
    if old_protocol:
        assert old_protocol == json.loads(json.dumps(protocol)), 'Frozen protocol changed; do not silently overwrite'
    else:
        atomic_json(run / 'PROTOCOL.json', protocol)
        for name in frozen:
            (run / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    if args.prepare_only:
        print(json.dumps({'groups': 32, 'maximum_new_logical_calls': 32, 'paid_calls': 0}))
        return
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines())) if (run / 'calls.jsonl').exists() else []
    done = {call['key']: call for call in calls}
    assert len(done) == len(calls)
    for call in calls:
        entry = ledger['attempts'][call['ledger_key']]
        assert entry['status'] == 'settled' and entry['response_id'] == call['response_id'], 'Reconcile durable receipt before new POST'
    prior = {}
    for entry in ledger['attempts'].values():
        if entry['run_id'] == args.run_id:
            prior[entry['logical_key']] = max(prior.get(entry['logical_key'], 0), entry['attempt_index'])
    predictions = json.loads((run / 'PREDICTIONS.json').read_text()) if (run / 'PREDICTIONS.json').exists() else []
    completed = {p['id'] for p in predictions}
    started = time.monotonic()
    halt = threading.Event()
    requester = PaidRequester(budget=Budget(current_unknown, retry_own_failures=True), run=run, run_id=args.run_id,
                              secret=credential(), halt=halt, prices=PRICES[MODEL], phase_cap=40,
                              prior_attempts=prior, wall_limit_seconds=7200)

    def status(state):
        atomic_json(run / 'STATUS.json', {'state': state, 'pid': os.getpid(), 'updated_at': now(),
                    'planned_samples': 32, 'completed_samples': len(completed), 'actual_calls': len(calls),
                    'api_cost_cny': sum(c['api_cost_cny'] for c in calls), 'mode': 'baseline',
                    'elapsed_seconds_this_session': time.monotonic() - started,
                    'local_gpu': False, 'confirmation_evaluated': False})

    def save(call):
        call['input_image_sha256'] = image_digest
        call['vl_high_resolution_images'] = True
        with (run / 'calls.jsonl').open('a') as handle:
            handle.write(json.dumps(call, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        calls.append(call)
        done[call['key']] = call

    status('running')
    try:
        for row in rows[:args.stop_after]:
            uid = row['id']
            blob = (ROOT / row['image']['path']).read_bytes()
            image_digest = sha(blob)
            body = {'model': MODEL, 'temperature': 0, 'enable_thinking': False, 'max_tokens': CAP,
                    'vl_high_resolution_images': True, 'response_format': {'type': 'json_object'},
                    'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': [
                        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(blob).decode()}},
                        {'type': 'text', 'text': PROMPT + row['instruction']}]}]}
            digest, key = sha(json.dumps(body, sort_keys=True).encode()), uid + '|direct'
            assert len(json.dumps(body).encode()) < 16 * 1024**2
            call = done.get(key)
            if call:
                assert call['prompt_sha256'] == digest
            else:
                call = requester.call(key=key, cap=CAP, body=body, digest=digest, save=save)
            assert call['returned_model'] == MODEL and call['vl_high_resolution_images'] is True
            prediction = {'id': uid, 'arm': 'direct', 'image_group': row['image_group'],
                          'category': row['category'], 'ui_type': row['ui_type'], 'point': point(call),
                          'valid': point(call) is not None, 'actual_call_keys': [call['ledger_key']], 'logical_calls': 1,
                          **{'logical_' + name: call[name] for name in ['input_tokens', 'output_tokens', 'elapsed_seconds', 'api_cost_cny']}}
            predictions = [p for p in predictions if p['id'] != uid] + [prediction]
            atomic_json(run / 'PREDICTIONS.json', predictions)
            completed.add(uid)
            status('running')
            print(json.dumps({'complete': uid, 'completed_samples': len(completed),
                              'actual_calls': len(calls), 'elapsed_seconds': time.monotonic() - started}), flush=True)
    except Exception:
        halt.set()
        status('held_execution_failure')
        raise
    status('completed_predictions' if args.stop_after == 32 else 'checkpoint_predictions')


if __name__ == '__main__':
    main()

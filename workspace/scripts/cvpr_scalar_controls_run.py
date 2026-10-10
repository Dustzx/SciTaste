"""Output-format attribution diagnostic on the same exposed development groups."""
import argparse
import base64
import fcntl
import io
import json
import os
import statistics
import threading
import time
from pathlib import Path

from PIL import Image

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_count_code import valid_count
from cvpr_count_run import BASE
from cvpr_hrbench_views import letterbox
from cvpr_ownership import map_points, merge_cross_view, parsed_points, tiles, view

PAID_ARMS = ['tile_scalar', 'halo_scalar']
ARMS = PAID_ARMS
CAP = 2048
SYSTEM = 'Use only supplied visual evidence. Follow the requested JSON schema.'
TARGET = ('The first image is the scene or scene crop to inspect. Images 2, 3 and 4 are '
          'the task-provided visual examples of the target object type. Count distinct '
          'visible objects of that same visual type in the first image only. The three '
          'reference images are not additional objects. Ignore the thin green frame as an object. ')
SCALAR = ('Inspect systematically. Return ONLY JSON {"count":nonnegative_integer}. '
          'Do not output an explanation.')
POINTS = ('Locate every target object in the entire first image, including objects outside '
          'the green frame and partially visible targets. Return ONLY JSON '
          '{"points":[[x,y],...]}. Each point is the center of the visible extent of one '
          'distinct target object. Coordinates are normalized to the full displayed square: '
          'top left [0,0], bottom right [1000,1000]. Do not invent hidden objects, '
          'add a total count, include the reference images, or repeat an object. '
          'An empty list means no visible targets.')
REVIEW = ('Reinspect the same scene carefully, checking the previous enumeration for omissions '
          'and duplicate counting. You may replace the previous result. ' + SCALAR)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--model', choices=PRICES, default='qwen3.8-max-0902')
    parser.add_argument('--stop-after', type=int, default=32)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    assert args.run_id.replace('_', '').replace('-', '').isalnum() and 1 <= args.stop_after <= 32
    base = BASE / 'fsc147'
    data = base / 'data'
    manifest = json.loads((data / 'MANIFEST.json').read_text())
    assert sha((data / 'development_inputs.jsonl').read_bytes()) == manifest['files']['development_inputs.jsonl']
    ids = json.loads((data / 'screen_ids.json').read_text())
    rows = {r['id']: r for r in map(json.loads, (data / 'development_inputs.jsonl').read_text().splitlines())}
    source = base / 'runs/bailian_qwen38_max0902_fsc_headroom_v1'
    refs = {r['id']: r for r in json.loads((source / 'EXEMPLAR_INPUTS.json').read_text())}
    assert len(ids) == len(set(ids)) == len({rows[k]['image_group'] for k in ids}) == 32
    for uid in ids:
        row = rows[uid]
        assert row['partition'] == 'development' and not {'answer', 'points', 'caption'} & set(row)
        assert sha((ROOT / row['image']['path']).read_bytes()) == row['image']['sha256']
        for ref in refs[uid]['provided_examples']:
            assert sha((ROOT / ref['path']).read_bytes()) == ref['sha256']
    run = base / 'runs' / args.run_id
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / '.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
    retained = {k: v for k, v in ledger['attempts'].items() if v['status'] != 'settled'}
    assert not any(v['run_id'] == args.run_id for v in retained.values())
    for entry in retained.values():
        cmdline = Path('/proc') / str(entry['pid']) / 'cmdline'
        assert not cmdline.exists() or entry['run_id'].encode() not in cmdline.read_bytes()
    frozen = ['cvpr_scalar_controls_run.py', 'cvpr_ownership.py', 'cvpr_scalar_controls_score.py',
              'cvpr_api_retry.py', 'cvpr_chart_api.py', 'cvpr_hrbench_views.py',
              'cvpr_count_code.py', 'cvpr_count_run.py', 'cvpr_chart_run.py']
    protocol = {
        'model': args.model, 'weight_revision': None, 'temperature': 0, 'thinking': False,
        'training': False, 'local_gpu': False, 'sample_ids': ids, 'arms': ARMS,
        'paid_arms': PAID_ARMS, 'sample_arm_order': 'Rotate paid-arm order by sample index; fixed quadrant order',
        'scope': '32 exposed FSC validation groups; scalar output-format attribution only, not independent method validation',
        'halo_fraction_of_full_image': .125, 'grid': [2, 2], 'point_coordinates': 'continuous normalized0..1000 in768 square',
        'ownership': 'Inverse actual rounded letterbox map; keep visible-extent centers in disjoint half-open cores; boundary goes right/bottom; exact duplicate coordinates collapse, no radius deduplication',
        'stitch_control': 'Cross-view connected components at radius0.35 times median min(width,height) of the three provided exemplar boxes; no tuning',
        'caps': {'per_call': CAP, 'per_paid_arm': CAP * 4},
        'calls_per_paid_arm': 4, 'raster_pixels_per_call': 768**2 + 3 * 128**2,
        'derived_controls': 'None; compare against immutable v1 outputs, all old costs retained',
        'prompts': {'system': SYSTEM, 'target': TARGET, 'scalar': SCALAR},
        'phase_cap_cny': 40, 'project_cap_cny': 300, 'workers': 1, 'prices': PRICES[args.model],
        'retained_unknown': retained, 'manifest_sha256': sha((data / 'MANIFEST.json').read_bytes()),
        'provided_examples_sha256': sha((source / 'EXEMPLAR_INPUTS.json').read_bytes()),
        'source_sha256': {n: sha((ROOT / 'scripts' / n).read_bytes()) for n in frozen},
        'diagnostic_kind': 'scalar_format',
        'stopping_rule': 'First2 interface valid required; then exactly32 groups and score all failures. No further format/cap sweeps. Never reverse ownership-v1 stop decision or open confirmation.',
        'expected_settled_cny': 3.5, 'maximum_new_logical_calls': 256,
        'limits': 'Context, resolution and readout effects must be separated by controls. Geometry is not a perceptual truth guarantee. MAE/RMSE on valid outputs with explicit denominator; invalids count wrong in exact. No threshold, prompt or halo sweep after outcomes. No test labels or hidden targets enter inference. Equal call/output/raster ceilings are not equal provider FLOPs.',
    }
    if (run / 'PROTOCOL.json').exists():
        assert json.loads((run / 'PROTOCOL.json').read_text()) == json.loads(json.dumps(protocol))
    else:
        atomic_json(run / 'PROTOCOL.json', protocol)
        for name in frozen:
            (run / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    if args.prepare_only:
        print(json.dumps({'groups': 32, 'paid_arms': 2, 'max_new_requests': 256, 'paid_calls': 0}))
        return
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines())) if (run / 'calls.jsonl').exists() else []
    done = {c['key']: c for c in calls}
    for call in calls:
        entry = ledger['attempts'][call['ledger_key']]
        assert entry['status'] == 'settled' and entry['response_id'] == call['response_id']
    predictions = json.loads((run / 'PREDICTIONS.json').read_text()) if (run / 'PREDICTIONS.json').exists() else []
    completed = {uid for uid in ids if sum(p['id'] == uid for p in predictions) == len(ARMS)}
    geometry_records = json.loads((run / 'GEOMETRY.json').read_text()) if (run / 'GEOMETRY.json').exists() else {}
    started = time.monotonic()
    halt = threading.Event()
    requester = PaidRequester(budget=Budget(retained, retry_own_failures=True), run=run,
                              run_id=args.run_id, secret=credential(), halt=halt,
                              prices=PRICES[args.model], phase_cap=40, wall_limit_seconds=10800)

    def status(state):
        atomic_json(run / 'STATUS.json', {'state': state, 'pid': os.getpid(), 'updated_at': now(),
                    'planned_samples': 32, 'completed_samples': len(completed), 'actual_calls': len(calls),
                    'api_cost_cny': sum(c['api_cost_cny'] for c in calls),
                    'elapsed_seconds_this_session': time.monotonic() - started,
                    'local_gpu': False, 'confirmation_evaluated': False})

    def save(call):
        with (run / 'calls.jsonl').open('a') as handle:
            handle.write(json.dumps(call, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        calls.append(call)
        done[call['key']] = call

    def invoke(uid, stage, images, prompt, previous=()):
        blobs = []
        for image in images:
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            blobs.append(stream.getvalue())
        content = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(b).decode()}} for b in blobs]
        content.append({'type': 'text', 'text': prompt})
        messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': content}]
        for old in previous:
            messages += [{'role': 'assistant', 'content': old['text']}, {'role': 'user', 'content': REVIEW}]
        body = {'model': args.model, 'temperature': 0, 'enable_thinking': False, 'max_tokens': CAP,
                'response_format': {'type': 'json_object'}, 'messages': messages}
        digest = sha(json.dumps(body, sort_keys=True).encode())
        key = uid + '|' + stage
        if key in done:
            assert done[key]['prompt_sha256'] == digest
            return done[key]
        same = next((c for c in done.values() if c['sample_id'] == uid and c['prompt_sha256'] == digest), None)
        if same:
            return same
        return requester.call(key=key, cap=CAP, body=body, digest=digest, save=save)

    def scalar(call):
        value = call['parsed'].get('count') if isinstance(call['parsed'], dict) else None
        return value if valid_count(value) and not call['truncated'] else None

    def record(row, arm, answer, used, **extra):
        return {'id': row['id'], 'arm': arm, 'image_group': row['image_group'],
                'category': row['category'], 'answer': answer, 'valid': answer is not None,
                'actual_call_keys': [c['ledger_key'] for c in used], 'logical_calls': len(used),
                **{'logical_' + name: sum(c[name] for c in used)
                   for name in ['input_tokens', 'output_tokens', 'elapsed_seconds', 'api_cost_cny']}, **extra}

    status('running')
    try:
        for index, uid in enumerate(ids[:args.stop_after]):
            if uid in completed:
                continue
            row = rows[uid]
            original = Image.open(ROOT / row['image']['path']).convert('RGB')
            references = [Image.open(ROOT / x['path']).convert('RGB') for x in refs[uid]['provided_examples']]
            original_view = letterbox(original, 768)[0]
            geometries, canvases = {}, {}
            for kind, halo in [('tile', 0), ('halo', .125)]:
                pairs = [view(original, g) for g in tiles(*original.size, halo)]
                canvases[kind], geometries[kind] = [p[0] for p in pairs], [p[1] for p in pairs]
            geometry_records[uid] = geometries
            atomic_json(run / 'GEOMETRY.json', geometry_records)
            local = []
            order = PAID_ARMS[index % len(PAID_ARMS):] + PAID_ARMS[:index % len(PAID_ARMS)]
            for arm in order:
                used, mapped, values = [], [], []
                kind = arm.split('_')[0]
                all_valid = True
                for tile_index in range(4):
                    geometry = geometries[kind][tile_index]
                    bounds = geometry['core_normalized']
                    prompt = TARGET + (f'Count only target objects whose visible-extent centers lie in '
                                       f'the green-frame interior x in[{bounds[0]},{bounds[2]}), '
                                       f'y in[{bounds[1]},{bounds[3]}) in normalized0..1000 coordinates. '
                                       'Use surrounding context to recognize boundary objects. ') + SCALAR
                    call = invoke(uid, arm + str(tile_index), [canvases[kind][tile_index]] + references, prompt)
                    used.append(call)
                    count = scalar(call)
                    all_valid &= count is not None
                    values.append(count)
                local.append(record(row, arm, sum(values) if all_valid else None, used, counts=values))
            assert len(local) == len(ARMS) and {p['arm'] for p in local} == set(ARMS)
            predictions = [p for p in predictions if p['id'] != uid] + local
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

"""Matched-input causal screen: crop-fragment versus whole-scene object centers."""
import argparse
import base64
import fcntl
import io
import json
import os
import threading
import time
from pathlib import Path

from PIL import Image

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_count_code import valid_count
from cvpr_count_run import BASE
from cvpr_global_center import SYSTEM, TARGET, POINT_RULE, FRAGMENT, INSTANCE, SCALAR, canvases, map_global, prompt
from cvpr_ownership import parsed_points, tiles

ARMS = ['fragment_center', 'instance_center', 'instance_scalar']
MODEL, CAP = 'qwen3.8-max-0902', 2048


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--stop-after', type=int, default=32)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    assert args.run_id.replace('_', '').replace('-', '').isalnum() and 1 <= args.stop_after <= 32
    base = BASE / 'fsc147'
    data, source = base / 'data', base / 'runs/bailian_qwen38_max0902_fsc_headroom_v1'
    manifest = json.loads((data / 'MANIFEST.json').read_text())
    assert sha((data / 'development_inputs.jsonl').read_bytes()) == manifest['files']['development_inputs.jsonl']
    ids = json.loads((data / 'screen_ids.json').read_text())
    rows = {r['id']: r for r in map(json.loads, (data / 'development_inputs.jsonl').read_text().splitlines())}
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
    api_lock = (PROJECT / '.api-single-worker.lock').open('a')
    fcntl.flock(api_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
    retained = {k: v for k, v in ledger['attempts'].items() if v['status'] != 'settled'}
    for entry in retained.values():
        proc = Path('/proc') / str(entry['pid']) / 'cmdline'
        assert not proc.exists() or entry['run_id'].encode() not in proc.read_bytes()
    old_protocol = json.loads((run / 'PROTOCOL.json').read_text()) if (run / 'PROTOCOL.json').exists() else None
    frozen = ['cvpr_global_center_run.py', 'cvpr_global_center_score.py', 'cvpr_global_center.py',
              'cvpr_ownership.py', 'cvpr_ownership_score.py', 'cvpr_api_retry.py', 'cvpr_chart_api.py',
              'cvpr_hrbench_views.py', 'cvpr_count_code.py', 'cvpr_count_run.py', 'cvpr_chart_run.py']
    old = base / 'runs/bailian_qwen38_max0902_fsc_ownership_v1'
    protocol = {'model': MODEL, 'weight_revision': None, 'temperature': 0, 'thinking': False,
                'training': False, 'local_gpu': False, 'sample_ids': ids, 'arms': ARMS,
                'diagnostic_kind': 'global_center',
                'scope': '32 already exposed FSC validation groups; falsifiable whole-scene center attribution screen, no independent validation',
                'hypothesis': 'Crop-fragment visible centers can assign one long object to multiple cores; a fixed whole-scene visible-instance center may preserve ownership',
                'input': 'Identical pixels/information across3 arms: whole512 square + same halo768 crop +3 task-provided128 visual examples. Same core/viewport addresses. No target labels or captions.',
                'sample_arm_order': 'Rotate3 arm order by sample index; fixed quadrant order',
                'halo_fraction_of_full_image': .125, 'grid': [2, 2],
                'point_coordinates': 'All arms use whole-scene512 square normalized0..1000; inverse actual rounded letterbox separately per axis',
                'ownership': 'Half-open disjoint cores, boundary right/bottom; padding/outside scene excluded; exact within-call duplicate points collapse, no radius tuning',
                'caps': {'per_call': CAP, 'per_paid_arm': CAP * 4}, 'calls_per_paid_arm': 4,
                'raster_pixels_per_call': 512**2 + 768**2 + 3 * 128**2,
                'prompts': {'system': SYSTEM, 'target': TARGET, 'point_rule': POINT_RULE, 'fragment': FRAGMENT, 'instance': INSTANCE, 'scalar': SCALAR},
                'phase_cap_cny': 60, 'project_cap_cny': 300, 'workers': 1, 'prices': PRICES[MODEL],
                'retained_unknown': old_protocol['retained_unknown'] if old_protocol else retained,
                'expected_settled_cny': 18, 'maximum_new_logical_calls': 384,
                'allocation_exception': '3 matched-input arms x4 calls x32 groups needed to separate center semantics from scalar readout; explicit screen allocation exceeds generic96call/10CNY target but stays shared300 and phase60, not extra authorization',
                'manifest_sha256': sha((data / 'MANIFEST.json').read_bytes()),
                'provided_examples_sha256': sha((source / 'EXEMPLAR_INPUTS.json').read_bytes()),
                'legacy_scored_sha256': sha((old / 'SCORED_PREDICTIONS.json').read_bytes()),
                'source_sha256': {name: sha((ROOT / 'scripts' / name).read_bytes()) for name in frozen},
                'interface_gate': 'First2 all3 arms valid/no truncation and matching model; format/geometry/throughput only, no target scores',
                'expansion_gate': {'minimum_valid_images_each_main_arm': 30, 'minimum_valid_paired': 30,
                                   'minimum_center_count_changes': 8,
                                   'mae_reduction_vs_each_main_control_at_least': .15,
                                   'paired_mae_reduction_95ci_lower_gt': 0, 'relative_error_reduction_95ci_lower_gt': 0,
                                   'main_controls': ['fragment_center', 'instance_scalar', 'legacy_halo_points']},
                'stopping_rule': 'One frozen complete readout; no prompt/halo/core/threshold/cap search. Failure stops this version, never reverses ownership-v1. Pass needs novelty/visual audit and independent development before any confirmation.',
                'limits': 'Center referencing/whole context are hypotheses, not established novelty.3 new arms share input and call/output/raster ceilings, not measurable cloud FLOPs. Legacy controls have less input/compute and are auxiliary practical barriers, not matched-input mechanisms. MAE on valid with explicit denominators; invalid exact wrong. All32 exposed, official test1190 unopened.'}
    if old_protocol:
        assert old_protocol == json.loads(json.dumps(protocol)), 'Frozen protocol changed'
    else:
        atomic_json(run / 'PROTOCOL.json', protocol)
        for name in frozen:
            (run / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    if args.prepare_only:
        print(json.dumps({'groups': 32, 'arms': ARMS, 'maximum_new_logical_calls': 384, 'paid_calls': 0}))
        return
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines())) if (run / 'calls.jsonl').exists() else []
    done = {c['key']: c for c in calls}
    assert len(done) == len(calls)
    for c in calls:
        entry = ledger['attempts'][c['ledger_key']]
        assert entry['status'] == 'settled' and entry['response_id'] == c['response_id']
    prior = {}
    for entry in ledger['attempts'].values():
        if entry['run_id'] == args.run_id:
            prior[entry['logical_key']] = max(prior.get(entry['logical_key'], 0), entry['attempt_index'])
    predictions = json.loads((run / 'PREDICTIONS.json').read_text()) if (run / 'PREDICTIONS.json').exists() else []
    completed = {uid for uid in ids if sum(p['id'] == uid for p in predictions) == len(ARMS)}
    geometry_records = json.loads((run / 'GEOMETRY.json').read_text()) if (run / 'GEOMETRY.json').exists() else {}
    started, halt = time.monotonic(), threading.Event()
    requester = PaidRequester(budget=Budget(retained, retry_own_failures=True), run=run, run_id=args.run_id,
                              secret=credential(), halt=halt, prior_attempts=prior, prices=PRICES[MODEL], phase_cap=60,
                              wall_limit_seconds=10800)

    def status(state):
        atomic_json(run / 'STATUS.json', {'state': state, 'pid': os.getpid(), 'updated_at': now(),
                    'planned_samples': 32, 'completed_samples': len(completed), 'actual_calls': len(calls),
                    'api_cost_cny': sum(c['api_cost_cny'] for c in calls),
                    'elapsed_seconds_this_session': time.monotonic() - started,
                    'local_gpu': False, 'confirmation_evaluated': False})

    def save(call):
        call['input_images_sha256'] = image_hashes
        with (run / 'calls.jsonl').open('a') as handle:
            handle.write(json.dumps(call, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        calls.append(call)
        done[call['key']] = call

    status('running')
    try:
        for index, uid in enumerate(ids[:args.stop_after]):
            row = rows[uid]
            image = Image.open(ROOT / row['image']['path']).convert('RGB')
            examples = [Image.open(ROOT / x['path']).convert('RGB') for x in refs[uid]['provided_examples']]
            pairs = [canvases(image, g) for g in tiles(*image.size, .125)]
            geometry_records[uid] = [pair[2] for pair in pairs]
            atomic_json(run / 'GEOMETRY.json', geometry_records)
            if uid in completed:
                continue
            local = []
            for arm in ARMS[index % 3:] + ARMS[:index % 3]:
                used, mapped, counts, valid = [], [], [], True
                for tile_index, (whole, crop, geometry) in enumerate(pairs):
                    blobs = []
                    for canvas in [whole, crop] + examples:
                        stream = io.BytesIO()
                        canvas.save(stream, format='PNG')
                        blobs.append(stream.getvalue())
                    image_hashes = [sha(b) for b in blobs]
                    content = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(b).decode()}} for b in blobs]
                    content.append({'type': 'text', 'text': prompt(arm, geometry)})
                    body = {'model': MODEL, 'temperature': 0, 'enable_thinking': False, 'max_tokens': CAP,
                            'response_format': {'type': 'json_object'},
                            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': content}]}
                    key, digest = uid + '|' + arm + str(tile_index), sha(json.dumps(body, sort_keys=True).encode())
                    if key in done:
                        call = done[key]
                        assert call['prompt_sha256'] == digest and call['input_images_sha256'] == image_hashes
                    else:
                        call = requester.call(key=key, cap=CAP, body=body, digest=digest, save=save)
                    assert call['returned_model'] == MODEL
                    used.append(call)
                    if arm == 'instance_scalar':
                        value = call['parsed'].get('count') if isinstance(call['parsed'], dict) else None
                        ok = valid_count(value) and not call['truncated']
                        valid &= ok
                        counts.append(value if ok else None)
                    else:
                        points = parsed_points(call)
                        valid &= points is not None
                        if points is not None:
                            mapped += map_global(points, geometry)
                owned = [p for p in mapped if p['in_scene'] and p['owned']]
                answer = (sum(counts) if arm == 'instance_scalar' else len(owned)) if valid else None
                local.append({'id': uid, 'arm': arm, 'image_group': row['image_group'], 'category': row['category'],
                              'answer': answer, 'valid': valid, 'actual_call_keys': [c['ledger_key'] for c in used],
                              'logical_calls': 4, 'mapped_points': mapped, 'owned_points': owned, 'scalar_counts': counts,
                              **{'logical_' + name: sum(c[name] for c in used) for name in ['input_tokens', 'output_tokens', 'elapsed_seconds', 'api_cost_cny']}})
            assert {p['arm'] for p in local} == set(ARMS)
            predictions = [p for p in predictions if p['id'] != uid] + local
            atomic_json(run / 'PREDICTIONS.json', predictions)
            completed.add(uid)
            status('running')
            print(json.dumps({'complete': uid, 'completed_samples': len(completed), 'actual_calls': len(calls),
                              'elapsed_seconds': time.monotonic() - started}), flush=True)
    except Exception:
        halt.set()
        status('held_execution_failure')
        raise
    status('completed_predictions' if args.stop_after == 32 else 'checkpoint_predictions')


if __name__ == '__main__':
    main()

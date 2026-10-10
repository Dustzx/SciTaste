"""CPU-only ScreenSpot-Pro official scoring and receipt audit."""
import argparse
import ast
import contextlib
import io
import json
import math
from pathlib import Path

from cvpr_chart_api import now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_gui_run import BASE, MODEL, point


def official_scorer():
    tree = ast.parse((BASE / 'sources/eval_screenspot_pro.py').read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'eval_sample_positive_gt']
    assert len(nodes) == 1
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pinned official positive scorer>', 'exec'), namespace)
    return namespace['eval_sample_positive_gt']


def score(sample, p):
    with contextlib.redirect_stdout(io.StringIO()):
        return official_scorer()(sample, {'point': p})


def validate():
    synthetic = {'bbox': [10, 20, 30, 40], 'img_size': [100, 100]}
    assert score(synthetic, [.1, .2]) == score(synthetic, [.3, .4]) == 'correct'
    assert score(synthetic, [.09999, .2]) == 'wrong'
    assert score(synthetic, None) == 'wrong_format'
    assert point({'parsed': {'point': [1000, 0]}, 'truncated': False}) == [1, 0]
    for invalid in [[True, 0], [float('nan'), 0], [1001, 0], [-1, 0], ['10', 0], [1]]:
        assert point({'parsed': {'point': invalid}}) is None
    assert point({'parsed': {'point': [1, 2]}, 'truncated': True}) is None
    print('Official edge inclusion, coordinate bounds/units, invalid/truncation checks passed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.validate:
        validate()
        return
    assert args.run_id
    run, data = BASE / 'runs' / args.run_id, BASE / 'data'
    assert not (run / 'SUMMARY.json').exists(), 'Readout already persisted; do not overwrite'
    protocol = json.loads((run / 'PROTOCOL.json').read_text())
    manifest = json.loads((data / 'MANIFEST.json').read_text())
    assert sha((data / 'MANIFEST.json').read_bytes()) == protocol['manifest_sha256']
    assert sha((BASE / 'sources/eval_screenspot_pro.py').read_bytes()) == protocol['official_scorer_sha256']
    for name, digest in protocol['source_sha256'].items():
        assert sha((run / name).read_bytes()) == digest
    for name in ['DEVELOPMENT_LABELS.json', 'development_inputs.jsonl', 'screen_ids.json']:
        assert sha((data / name).read_bytes()) == manifest['files'][name]
    ids = protocol['sample_ids']
    labels = json.loads((data / 'DEVELOPMENT_LABELS.json').read_text())
    inputs = {r['id']: r for r in map(json.loads, (data / 'development_inputs.jsonl').read_text().splitlines())}
    preds = json.loads((run / 'PREDICTIONS.json').read_text())
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines()))
    ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
    assert len(preds) == len(calls) == len(ids) == 32 and {p['id'] for p in preds} == set(ids) == set(labels)
    by_call = {c['ledger_key']: c for c in calls}
    results = []
    for pred in preds:
        uid = pred['id']
        call = by_call[pred['actual_call_keys'][0]]
        entry = ledger['attempts'][call['ledger_key']]
        assert call['sample_id'] == uid and entry['status'] == 'settled' and entry['response_id'] == call['response_id']
        assert entry['usage'] == call['usage'] and call['requested_model'] == call['returned_model'] == MODEL
        assert call['input_image_sha256'] == inputs[uid]['image']['sha256'] and call['vl_high_resolution_images'] is True
        assert sha((ROOT / inputs[uid]['image']['path']).read_bytes()) == inputs[uid]['image']['sha256']
        assert pred['point'] == point(call) and pred['valid'] == (pred['point'] is not None)
        correctness = score(labels[uid], pred['point'])
        results.append({**pred, 'correctness': correctness})
    correct = sum(r['correctness'] == 'correct' for r in results)
    valid = sum(r['valid'] for r in results)
    z = 1.959963984540054
    n, rate = 32, correct / 32
    center = (rate + z*z/(2*n)) / (1 + z*z/n)
    half = z * math.sqrt(rate*(1-rate)/n + z*z/(4*n*n)) / (1 + z*z/n)
    attempts = [e for e in ledger['attempts'].values() if e['run_id'] == args.run_id]
    metrics = {'n': 32, 'valid': valid, 'correct': correct, 'accuracy': rate,
               'accuracy_wilson95': [center-half, center+half],
               'by_ui_type': {kind: {'n': sum(r['ui_type'] == kind for r in results),
                   'correct': sum(r['ui_type'] == kind and r['correctness'] == 'correct' for r in results)} for kind in ['text', 'icon']},
               'input_tokens': sum(c['input_tokens'] for c in calls), 'output_tokens': sum(c['output_tokens'] for c in calls),
               'logical_calls': 32, 'api_cost_cny': sum(c['api_cost_cny'] for c in calls)}
    disposition = 'held_invalid_coverage' if valid < 30 else 'stopped_saturated' if rate >= .85 else 'admitted_error_audit_only'
    summary = {'created_at': now(), 'scope': protocol['scope'], 'arms': {'direct': metrics},
               'attempts': len(attempts), 'successful_calls': len(calls),
               'truncated_responses': sum(c['truncated'] for c in calls),
               'unresolved_reserved_cny': sum(e['reserved_cny'] for e in attempts if e['status'] != 'settled'),
               'disposition': disposition, 'headroom_gate_passed': valid >= 30 and rate < .85,
               'method_evaluated': False, 'confirmation_evaluated': False,
               'limits': 'Stratified development panel, not benchmark-wide score; CI treats filenames as groups, session/near-duplicate dependence not yet certified. No proposed-method gain or novelty established.'}
    atomic_json(run / 'SCORED_PREDICTIONS.json', results)
    atomic_json(run / 'SUMMARY.json', summary)
    status = json.loads((run / 'STATUS.json').read_text())
    status.update(state='completed_scored', verified_at=now(), summary_file='SUMMARY.json')
    atomic_json(run / 'STATUS.json', status)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

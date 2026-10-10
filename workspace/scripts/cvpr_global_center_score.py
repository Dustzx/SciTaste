"""Complete CPU readout and frozen gates for whole-scene center attribution."""
import argparse
import json

import numpy as np
from PIL import Image

from cvpr_chart_api import now
from cvpr_chart_run import PROJECT, atomic_json, sha
from cvpr_count_run import BASE
from cvpr_global_center import canvases, forward, map_global
from cvpr_global_center_run import ARMS
from cvpr_ownership import tiles
from cvpr_ownership_score import interval


def validate():
    image = Image.new('RGB', (1023, 517), 'white')
    geoms = [canvases(image, g)[2] for g in tiles(*image.size, .125)]
    # A true whole-scene center is owned once, even if its long object intersects all crops.
    center = [511, 258]
    points = [map_global([forward(center, g['whole_letterbox'])], g)[0] for g in geoms]
    assert [p['owned'] for p in points] == [False, False, False, True]
    assert all(np.allclose(p['point'], center) for p in points)
    # Two separated visible fragment centers would be owned by two distinct cores.
    fragment_centers = [[300, 100], [700, 400]]
    assert sum(map_global([forward(p, g['whole_letterbox'])], g)[0]['owned'] for p in fragment_centers for g in geoms) == 2
    assert not any(map_global([[0, 0]], g)[0]['owned'] for g in geoms)  # letterbox padding
    assert len(map_global([[500, 500], [500, 500]], geoms[0])) == 1
    assert interval([0] * 32) == [0, 0] and interval([1] * 32) == [1, 1]
    print('Odd raster inverse mapping, half-open boundary, long-object fragmentation, padding/duplicates and interval direction checked')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.validate:
        validate()
        return
    assert args.run_id and args.run_id.replace('_', '').replace('-', '').isalnum()
    base = BASE / 'fsc147'
    run, data = base / 'runs' / args.run_id, base / 'data'
    assert not (run / 'SUMMARY.json').exists()
    status = json.loads((run / 'STATUS.json').read_text())
    assert status['state'] == 'completed_predictions'
    protocol = json.loads((run / 'PROTOCOL.json').read_text())
    manifest = json.loads((data / 'MANIFEST.json').read_text())
    assert sha((data / 'MANIFEST.json').read_bytes()) == protocol['manifest_sha256']
    for name, digest in protocol['source_sha256'].items():
        assert sha((run / name).read_bytes()) == digest
    path = data / 'development_labels.json'
    assert sha(path.read_bytes()) == manifest['files'][path.name]
    labels = {r['id']: r for r in json.loads(path.read_text())}
    rows = json.loads((run / 'PREDICTIONS.json').read_text())
    ids = protocol['sample_ids']
    assert len(rows) == len(ids) * len(ARMS) and len({(r['id'], r['arm']) for r in rows}) == len(rows)
    assert {r['id'] for r in rows} == set(ids)
    details, lookup, metrics = [], {arm: {} for arm in ARMS}, {}
    for row in rows:
        label = labels[row['id']]
        assert label['partition'] == 'development' and label['image_group'] == row['image_group']
        target = label['answer']
        d = {**row, 'target': target, 'score': int(row['valid'] and row['answer'] == target),
             'absolute_error': abs(row['answer'] - target) if row['valid'] else None,
             'normalized_absolute_error': abs(row['answer'] - target) / max(1, target) if row['valid'] else None}
        details.append(d)
        lookup[row['arm']][row['id']] = d
    old = base / 'runs/bailian_qwen38_max0902_fsc_ownership_v1/SCORED_PREDICTIONS.json'
    assert sha(old.read_bytes()) == protocol['legacy_scored_sha256']
    legacy = json.loads(old.read_text())
    for arm in ['halo_points', 'whole_review']:
        lookup['legacy_' + arm] = {r['id']: r for r in legacy if r['arm'] == arm}
    for arm, by_id in lookup.items():
        assert set(by_id) == set(ids)
        rs = list(by_id.values())
        valid = [r for r in rs if r['valid']]
        for row in rs:
            assert row['target'] == labels[row['id']]['answer'] and row['image_group'] == labels[row['id']]['image_group']
        errors = [r['absolute_error'] for r in valid]
        metrics[arm] = {'n': 32, 'valid': len(valid), 'correct': sum(r['score'] for r in rs),
                        'score_mean': float(np.mean([r['score'] for r in rs])),
                        'mae_valid_only': float(np.mean(errors)) if errors else None,
                        'rmse_valid_only': float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
                        'mean_relative_error_valid_only': float(np.mean([r['normalized_absolute_error'] for r in valid])) if errors else None,
                        **{key: sum(r[key] for r in rs) for key in ['logical_calls', 'logical_input_tokens', 'logical_output_tokens', 'logical_elapsed_seconds', 'logical_api_cost_cny']}}
    candidate, pairs = lookup['instance_center'], {}
    for arm in ['fragment_center', 'instance_scalar', 'legacy_halo_points', 'legacy_whole_review']:
        control = lookup[arm]
        paired = [uid for uid in ids if candidate[uid]['valid'] and control[uid]['valid']]
        ae = [control[k]['absolute_error'] - candidate[k]['absolute_error'] for k in paired]
        re = [control[k]['normalized_absolute_error'] - candidate[k]['normalized_absolute_error'] for k in paired]
        old_mean = float(np.mean([control[k]['absolute_error'] for k in paired])) if paired else 0
        pairs[arm] = {'paired_valid': len(paired), 'mae_reduction': float(np.mean(ae)) if ae else None,
                      'paired_mae_reduction_fraction': float(np.mean(ae)) / old_mean if old_mean else 0,
                      'mae_reduction_95ci': interval(ae),
                      'relative_error_reduction': float(np.mean(re)) if re else None,
                      'relative_error_reduction_95ci': interval(re),
                      'exact_delta_all_images': float(np.mean([candidate[k]['score'] - control[k]['score'] for k in ids])),
                      'improved_absolute_error_ids': [k for k in paired if candidate[k]['absolute_error'] < control[k]['absolute_error']],
                      'regressed_absolute_error_ids': [k for k in paired if candidate[k]['absolute_error'] > control[k]['absolute_error']]}
    changes = [uid for uid in ids if candidate[uid]['valid'] and lookup['fragment_center'][uid]['valid'] and candidate[uid]['answer'] != lookup['fragment_center'][uid]['answer']]
    gate = protocol['expansion_gate']
    checks = {'candidate_coverage': metrics['instance_center']['valid'] >= gate['minimum_valid_images_each_main_arm'],
              'center_readout_changes_at_least8_images': len(changes) >= gate['minimum_center_count_changes']}
    for arm in gate['main_controls']:
        pair = pairs[arm]
        checks[arm + '_coverage'] = (metrics[arm]['valid'] >= gate['minimum_valid_images_each_main_arm'] and pair['paired_valid'] >= gate['minimum_valid_paired'] and metrics['instance_center']['valid'] >= metrics[arm]['valid'])
        checks[arm + '_gain'] = (pair['paired_mae_reduction_fraction'] >= gate['mae_reduction_vs_each_main_control_at_least'] and pair['mae_reduction_95ci'] is not None and pair['mae_reduction_95ci'][0] > 0 and pair['relative_error_reduction_95ci'][0] > 0)
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines()))
    assert len(calls) == len({c['key'] for c in calls}) == len({c['response_id'] for c in calls}) == 384
    ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
    for call in calls:
        entry = ledger['attempts'][call['ledger_key']]
        assert call['requested_model'] == call['returned_model'] == protocol['model']
        assert entry['status'] == 'settled' and entry['response_id'] == call['response_id'] and entry['usage'] == call['usage']
    for uid in ids:
        # The three arms use precisely the same five raster inputs for each quadrant.
        for tile in range(4):
            hashes = [c['input_images_sha256'] for c in calls if c['sample_id'] == uid and c['stage'].endswith(str(tile))]
            assert len(hashes) == 3 and hashes[0] == hashes[1] == hashes[2]
    attempts = [e for e in ledger['attempts'].values() if e['run_id'] == args.run_id]
    passed = all(checks.values())
    summary = {'run_id': args.run_id, 'verified_at': now(), 'model': protocol['model'],
               'scope': protocol['scope'], 'samples': 32, 'paired_samples': 32, 'arms': metrics,
               'paired_instance_center_vs': pairs, 'center_changed_images': len(changes),
               'expansion_gate_checks': checks, 'expansion_gate_passed': passed,
               'decision': 'Novelty/visual audit then frozen independent development replication' if passed else 'Stop this version; preserve all outcomes, no prompt/center/halo sweep',
               'actual_calls': len(calls), 'attempts': len(attempts), 'api_cost_cny': sum(c['api_cost_cny'] for c in calls),
               'truncations': sum(c['truncated'] for c in calls),
               'unresolved_reserved_cny': sum(e['reserved_cny'] for e in attempts if e['status'] != 'settled'),
               'same_input_and_ceiling_audit': True, 'confirmation_evaluated': False,
               'publication_ready': False, 'novelty_established': False, 'limits': protocol['limits']}
    atomic_json(run / 'SCORED_PREDICTIONS.json', details)
    atomic_json(run / 'SUMMARY.json', summary)
    atomic_json(run / 'STATUS.json', {**status, 'state': 'completed_scored', 'verified_at': now(), 'summary_file': 'SUMMARY.json'})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""CPU-only paired readout; labels never reach the ownership executor."""
import argparse
import json
import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from cvpr_chart_api import now
from cvpr_chart_run import atomic_json, sha
from cvpr_count_run import BASE


def interval(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return None
    rng = np.random.default_rng(2710)
    means = values[rng.integers(0, len(values), (5000, len(values)))].mean(axis=1)
    return np.percentile(means, [2.5, 97.5]).tolist()


def point_proxy(predicted, targets, radius):
    predicted, targets = np.asarray(predicted), np.asarray(targets)
    n, m = len(predicted), len(targets)
    matched = 0
    if n and m:
        distances = np.linalg.norm(predicted[:, None, :] - targets[None, :, :], axis=-1)
        # Maximum number within radius, then shortest distance among equally-sized matchings.
        cost = (distances > radius) * (max(n, m) + 1) + np.minimum(distances / radius, 1)
        pi, ti = linear_sum_assignment(cost)
        matched = int(np.sum(distances[pi, ti] <= radius))
    return {'predicted': n, 'reference': m, 'matched': matched,
            'precision': matched / n if n else float(m == 0),
            'recall': matched / m if m else float(n == 0),
            'f1': 2 * matched / (n + m) if n + m else 1.0, 'radius_pixels': radius}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    assert args.run_id.replace('_', '').replace('-', '').isalnum()
    base = BASE / 'fsc147'
    run = base / 'runs' / args.run_id
    status = json.loads((run / 'STATUS.json').read_text())
    assert status['state'] == 'completed_predictions'
    protocol = json.loads((run / 'PROTOCOL.json').read_text())
    manifest = json.loads((base / 'data/MANIFEST.json').read_text())
    path = base / 'data/development_labels.json'
    assert sha(path.read_bytes()) == manifest['files'][path.name]
    labels = {r['id']: r for r in json.loads(path.read_text())}
    rows = json.loads((run / 'PREDICTIONS.json').read_text())
    ids, arms = protocol['sample_ids'], protocol['arms']
    assert len(rows) == len(ids) * len(arms) and len({(r['id'], r['arm']) for r in rows}) == len(rows)
    details, lookup, metrics = [], {a: {} for a in arms}, {}
    for row in rows:
        label = labels[row['id']]
        assert label['partition'] == 'development' and label['image_group'] == row['image_group']
        target = label['answer']
        d = {**row, 'target': target, 'score': int(row['valid'] and row['answer'] == target),
             'absolute_error': abs(row['answer'] - target) if row['valid'] else None,
             'normalized_absolute_error': abs(row['answer'] - target) / max(1, target) if row['valid'] else None}
        details.append(d)
        lookup[row['arm']][row['id']] = d
    for arm in arms:
        assert set(lookup[arm]) == set(ids)
        rs = list(lookup[arm].values())
        valid = [r for r in rs if r['valid']]
        errors = [r['absolute_error'] for r in valid]
        metrics[arm] = {'n': len(rs), 'valid': len(valid), 'correct': sum(r['score'] for r in rs),
                        'score_mean': float(np.mean([r['score'] for r in rs])),
                        'mae_valid_only': float(np.mean(errors)) if errors else None,
                        'rmse_valid_only': float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
                        'mean_relative_error_valid_only': float(np.mean([r['normalized_absolute_error'] for r in valid])) if errors else None,
                        **{key: sum(r[key] for r in rs) for key in
                           ['logical_calls', 'logical_input_tokens', 'logical_output_tokens',
                            'logical_elapsed_seconds', 'logical_api_cost_cny']}}
    candidate = lookup['halo_points']
    pairs = {}
    gate = protocol['expansion_gate']
    for arm in gate['main_controls'] + ['whole_first', 'halo_unfiltered']:
        control = lookup[arm]
        paired = [k for k in ids if candidate[k]['valid'] and control[k]['valid']]
        ae = [control[k]['absolute_error'] - candidate[k]['absolute_error'] for k in paired]
        re = [control[k]['normalized_absolute_error'] - candidate[k]['normalized_absolute_error'] for k in paired]
        old = float(np.mean([control[k]['absolute_error'] for k in paired])) if paired else None
        new = float(np.mean([candidate[k]['absolute_error'] for k in paired])) if paired else None
        pairs[arm] = {'paired_valid': len(paired), 'mae_reduction': float(np.mean(ae)) if ae else None,
                      'paired_mae_reduction_fraction': (old - new) / old if old else 0,
                      'mae_reduction_95ci': interval(ae), 'relative_error_reduction': float(np.mean(re)) if re else None,
                      'relative_error_reduction_95ci': interval(re),
                      'exact_delta_all_images': float(np.mean([candidate[k]['score'] - control[k]['score'] for k in ids])),
                      'exact_delta_95ci': interval([candidate[k]['score'] - control[k]['score'] for k in ids]),
                      'improved_absolute_error_ids': [k for k in paired if candidate[k]['absolute_error'] < control[k]['absolute_error']],
                      'regressed_absolute_error_ids': [k for k in paired if candidate[k]['absolute_error'] > control[k]['absolute_error']]}
    changes = [k for k in ids if candidate[k]['valid'] and lookup['halo_unfiltered'][k]['valid']
               and candidate[k]['answer'] != lookup['halo_unfiltered'][k]['answer']]
    checks = {'candidate_coverage': metrics['halo_points']['valid'] >= gate['minimum_valid_images_each_main_arm'],
              'ownership_operates_on_at_least8_images': len(changes) >= gate['minimum_samples_ownership_changes']}
    for arm in gate['main_controls']:
        pair = pairs[arm]
        checks[arm + '_coverage'] = (metrics[arm]['valid'] >= gate['minimum_valid_images_each_main_arm']
                                   and pair['paired_valid'] >= gate['minimum_valid_paired']
                                   and metrics['halo_points']['valid'] >= metrics[arm]['valid'])
        checks[arm + '_gain'] = (pair['paired_mae_reduction_fraction'] >= gate['mae_reduction_vs_each_main_control_at_least']
                               and pair['mae_reduction_95ci'] is not None and pair['mae_reduction_95ci'][0] > 0
                               and pair['relative_error_reduction_95ci'][0] > 0)
    # Grounding proxy is diagnostic only. Point annotations need not equal visible-extent centers.
    inputs = {r['id']: r for r in map(json.loads, (base / 'data/development_inputs.jsonl').read_text().splitlines())}
    ann = json.loads((base / 'sources/annotation_FSC147_384.json').read_text())
    grounding = []
    for uid in ids:
        row, target = inputs[uid], ann[inputs[uid]['source_name']]
        width, height = row['image']['size']
        assert abs(target['W'] * target['ratio_w'] - width) < 1e-6
        assert abs(target['H'] * target['ratio_h'] - height) < 1e-6
        assert len(target['points']) == labels[uid]['answer']
        for arm in ['tile_points', 'halo_points']:
            pred = lookup[arm][uid]
            if pred['valid']:
                proxy = point_proxy([p['point'] for p in pred['owned_points']], target['points'], .02 * math.hypot(width, height))
                grounding.append({'id': uid, 'arm': arm, **proxy})
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines()))
    passed = all(checks.values())
    summary = {'run_id': args.run_id, 'verified_at': now(), 'model': protocol['model'],
               'scope': protocol['scope'], 'samples': len(ids), 'paired_samples': len(ids),
               'arms': metrics, 'paired_halo_points_vs': pairs, 'ownership_changed_images': len(changes),
               'expansion_gate_checks': checks, 'expansion_gate_passed': passed,
               'decision': 'Proceed to visual/novelty audit and frozen independent development replication before confirmation' if passed
                           else 'Stop this version; preserve all outcomes and select a distinct falsifiable mechanism',
               'actual_calls': len(calls), 'api_cost_cny': sum(c['api_cost_cny'] for c in calls),
               'truncations': sum(c['truncated'] for c in calls), 'confirmation_evaluated': False,
               'publication_ready': False, 'novelty_established': False,
               'limits': protocol['limits']}
    atomic_json(run / 'SCORED_PREDICTIONS.json', details)
    atomic_json(run / 'GROUNDING_PROXY.json', {'radius_rule': '.02 times actual image diagonal; fixed before labels',
                'scope': 'Diagnostic reference only; not human-certified object identity or causal validation', 'cases': grounding})
    atomic_json(run / 'SUMMARY.json', summary)
    atomic_json(run / 'STATUS.json', {**status, 'state': 'completed_scored', 'verified_at': now(), 'summary_file': 'SUMMARY.json'})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

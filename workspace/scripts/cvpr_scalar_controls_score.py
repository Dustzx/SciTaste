"""CPU-only paired readout; scalar format diagnostic; labels never reach the executor."""
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
    old_run = base / 'runs/bailian_qwen38_max0902_fsc_ownership_v1'
    old = json.loads((old_run / 'SCORED_PREDICTIONS.json').read_text())
    previous = {(r['arm'], r['id']): r for r in old}
    pairs = {}
    for arm in arms:
        for control_arm in [arm, 'halo_points', 'whole_review']:
            paired = [k for k in ids if lookup[arm][k]['valid'] and previous[control_arm, k]['valid']]
            for k in paired:
                assert lookup[arm][k]['target'] == previous[control_arm, k]['target']
                assert lookup[arm][k]['image_group'] == previous[control_arm, k]['image_group']
            ae = [previous[control_arm, k]['absolute_error'] - lookup[arm][k]['absolute_error'] for k in paired]
            re = [previous[control_arm, k]['normalized_absolute_error'] - lookup[arm][k]['normalized_absolute_error'] for k in paired]
            pairs[arm + '_vs_' + control_arm] = {'paired_valid': len(paired),
                'mae_reduction_new_vs_old': float(np.mean(ae)) if ae else None,
                'mae_reduction_95ci': interval(ae),
                'relative_error_reduction': float(np.mean(re)) if re else None,
                'relative_error_reduction_95ci': interval(re)}
    calls = list(map(json.loads, (run / 'calls.jsonl').read_text().splitlines()))
    assert len(calls) == 256 and len({c['key'] for c in calls}) == 256
    assert all(c['requested_model'] == c['returned_model'] == protocol['model'] for c in calls)
    assert json.loads((run / 'GEOMETRY.json').read_text()) == json.loads((old_run / 'GEOMETRY.json').read_text())
    ledger = json.loads((base.parents[1] / 'API_LEDGER.json').read_text())
    for c in calls:
        receipt = ledger['attempts'][c['ledger_key']]
        assert receipt['status'] == 'settled' and receipt['response_id'] == c['response_id'] and receipt['usage'] == c['usage']
    summary = {'run_id': args.run_id, 'verified_at': now(), 'model': protocol['model'],
        'scope': protocol['scope'], 'samples': len(ids), 'paired_samples': len(ids),
        'arms': metrics, 'paired_new_scalar_vs_cached': pairs,
        'actual_calls': len(calls), 'api_cost_cny': sum(c['api_cost_cny'] for c in calls),
        'truncations': sum(c['truncated'] for c in calls),
        'confirmation_evaluated': False, 'publication_ready': False, 'novelty_established': False,
        'decision': 'Use this format diagnostic to assess scalar-control weakness; ownership-v1 stays stopped. No prompt/cap sweep.',
        'limits': protocol['limits']}
    atomic_json(run / 'SCORED_PREDICTIONS.json', details)
    atomic_json(run / 'SUMMARY.json', summary)
    atomic_json(run / 'STATUS.json', {**status, 'state': 'completed_scored', 'verified_at': now(), 'summary_file': 'SUMMARY.json'})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

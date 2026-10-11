"""NeSy-Route Task2 offline CPU score helpers. No GT-loading CLI enabled.

Author metrics are unmodified and conditional. Added strict metrics retain all32
IDs and never assign a numerical zero to an undefined preference correlation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from cvpr_route_run import (N, CAP, MODEL, SOURCE, VECTOR_FIELDS, verify_source,
                            prediction_from_call, valid_vectors)


def load_official_calculator(source=SOURCE):
    """Load only checked official scorer code, never its CLI or dataset loader."""
    verify_source(source)
    source = Path(source).resolve()
    for name, directory in [('evaluation', source/'evaluation'), ('evaluation.task2', source/'evaluation/task2')]:
        if name in sys.modules:
            if list(getattr(sys.modules[name], '__path__', [])) != [str(directory)]:
                raise ValueError('Foreign evaluation package already imported')
        else:
            package = types.ModuleType(name)
            package.__path__ = [str(directory)]
            sys.modules[name] = package
    name = 'evaluation.task2.evaluate'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, source/'evaluation/task2/evaluate.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    for name in ('evaluation.task2.evaluate', 'evaluation.data', 'evaluation.vector_metrics'):
        if Path(sys.modules[name].__file__).resolve() != source/Path(*name.split('.')).with_suffix('.py'):
            raise ValueError('Foreign official scorer dependency')
    return module.calculate_metrics


def validate_complete_panel(predictions, calls, ids):
    if (len(ids) != N or len(set(ids)) != N or len(predictions) != N
            or {p['sample_id'] for p in predictions} != set(ids)
            or len({p['sample_id'] for p in predictions}) != N):
        raise ValueError('Only complete frozen32 response/prediction panels may open selected targets')
    expected = {sid+'|direct' for sid in ids}
    if len(calls) != N or {c['key'] for c in calls} != expected:
        raise ValueError('All32 successful API receipts required, including invalid content')
    actual = {p['sample_id']: p for p in predictions}
    for call in calls:
        if (call.get('status') != 'ok' or call.get('requested_model') != MODEL or call.get('token_cap') != CAP
                or type(call.get('input_tokens')) is not int or call['input_tokens'] < 0
                or type(call.get('output_tokens')) is not int or not 0 <= call['output_tokens'] <= CAP):
            raise ValueError('Invalid successful-stage resource receipt')
        recomputed = prediction_from_call(call)
        if recomputed != actual[recomputed['sample_id']]:
            raise ValueError('Prediction differs from independently parsed successful response')
    return actual


def score_panel(predictions, calls, ids, targets, official_calculate):
    """Targets are injected after validate_complete_panel; never loaded here."""
    actual = validate_complete_panel(predictions, calls, ids)
    if (set(targets) != set(ids) or any(set(targets[sid]) != set(VECTOR_FIELDS)
            or not valid_vectors(targets[sid]) for sid in ids)):
        raise ValueError('Only exactly selected32 targets with three strict8D vectors allowed')
    valid = [sid for sid in ids if actual[sid]['success']]
    official_rows = [{k:v for k,v in actual[sid].items() if k not in ('status', 'logic_reasoning', 'reasoning')}
                     for sid in ids]
    if valid:
        official = official_calculate(official_rows, targets)
        official_available, pr_count = True, official['preference']['ranking_correlation']['valid_samples']
    else:
        # Official calculate_metrics raises ValueError when every row is invalid.
        official = None
        official_available, pr_count = False, 0
    region_correct = traverse_exact = cost_exact = all_exact = 0
    present_correct = absent_correct = present_n = absent_n = 0
    gt_rank_eligible = 0
    for sid in ids:
        target = targets[sid]
        mask = [i for i,v in enumerate(target['traverse_vector']) if v == 1]
        gt_rank_eligible += len(mask) >= 2 and len({target['cost_vector'][i] for i in mask}) > 1
        for i, target_region in enumerate(target['region_vector']):
            present_n += target_region > 0
            absent_n += target_region == 0
            hit = actual[sid]['success'] and actual[sid]['region_vector'][i] == target_region
            region_correct += hit
            present_correct += hit and target_region > 0
            absent_correct += hit and target_region == 0
        if actual[sid]['success']:
            traverse_exact += actual[sid]['traverse_vector'] == target['traverse_vector']
            cost_exact += actual[sid]['cost_vector'] == target['cost_vector']
            all_exact += all(actual[sid][key] == target[key] for key in VECTOR_FIELDS)
    states = sorted({actual[sid]['status'] for sid in ids})
    return {
        'selected_samples': N, 'completed_response_records': N, 'valid_predictions': len(valid),
        'failed_predictions': N-len(valid), 'missing_predictions': 0,
        'coverage_counts': {state: sum(actual[sid]['status'] == state for sid in ids) for state in states},
        'official_metrics_available': official_available, 'official_metrics': official,
        'official_unavailable_reason': None if official_available else 'Unmodified official scorer requires at least one valid prediction.',
        'official_denominators': {'submitted': N, 'valid': len(valid), 'PR_eligible': pr_count},
        'full_denominator_strict': {
            'N': N, 'RM': region_correct/(8*N), 'RM_correct_elements': region_correct, 'RM_elements': 8*N,
            'TM': traverse_exact/N, 'TM_correct': traverse_exact,
            'cost_vector_exact': cost_exact/N, 'cost_vector_exact_correct': cost_exact,
            'all_vector_exact': all_exact/N, 'all_vector_exact_correct': all_exact,
            'invalid_policy': 'Every invalid/refused/truncated completed ID contributes zero, never removed from denominator.',
            'PR': None, 'PR_note': 'A full-N PR is not defined; use original conditional Kendall correlation and eligible count.'},
        'diagnostics': {
            'present_class_RM': present_correct/present_n if present_n else None,
            'present_class_correct': present_correct, 'present_class_elements': present_n,
            'absence_RM': absent_correct/absent_n if absent_n else None,
            'absence_correct': absent_correct, 'absence_elements': absent_n,
            'GT_rank_eligible_samples': gt_rank_eligible,
            'PR_defined_valid_samples': pr_count,
            'PR_not_defined_among_valid': len(valid)-pr_count,
            'absence_warning': 'Official RM includes matching absent0 entries; present-class and absence scores are separate diagnostics.'},
        'independent_confirmation': False, 'publication_ready': False,
        'scope': 'Evaluation-derived32 development author4shot API adapter; engineering acceptance is not scientific evidence.'}


if __name__ == '__main__':
    raise SystemExit('CPU score helpers only: no GT-reading CLI until root freezes selected-only targets and data admission.')

"""Offline Task2 evaluation; complete32 responses required before target access."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import stat
import time

from cvpr_chart_api import now
from cvpr_chart_run import PROJECT, atomic_json
from cvpr_route_run import BASE, N, VECTOR_FIELDS, sha, strict_json, valid_vectors
from cvpr_route_score import validate_complete_panel, load_official_calculator, score_panel
from cvpr_route_execute import read_admission, verify_snapshots, SCIENTIFIC_GATES


def load_selected_targets(contract):
    path = Path(contract['targets_path'])
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('Selected targets must be sealed mode600 or stricter')
    raw = path.read_bytes()
    if sha(raw) != contract['targets_sha256']:
        raise ValueError('Selected targets hash changed')
    data = strict_json(raw)
    if set(data) != {'schema_version','role','rows'} or data['schema_version'] != 1 or data['role'] != 'selected_development_only':
        raise ValueError('Only separately projected selected-development targets accepted')
    rows = data['rows']
    if (not isinstance(rows,list) or len(rows) != N
            or any(set(row) != {'sample_id',*VECTOR_FIELDS} or not valid_vectors(row) for row in rows)
            or len({row['sample_id'] for row in rows}) != N
            or {row['sample_id'] for row in rows} != set(contract['sample_ids'])):
        raise ValueError('Targets contain missing/duplicate/unselected IDs or extra fields')
    return {row['sample_id']:{key:row[key] for key in VECTOR_FIELDS} for row in rows}


def evaluate_records(predictions,calls,ids,targets_loader,official_calculate):
    # Ordering is intentional: this fails before executing the GT loader.
    actual = validate_complete_panel(predictions,calls,ids)
    targets = targets_loader()
    result = score_panel(predictions,calls,ids,targets,official_calculate)
    strata = {}
    present_error_ids = 0
    for sid in ids:
        pred,target = actual[sid],targets[sid]
        if not pred['success']:
            key = 'invalid_output_unknown_mechanism'
        else:
            region,target_region = pred['region_vector'],target['region_vector']
            present_error_ids += any(g > 0 and p != g for p,g in zip(region,target_region,strict=True))
            support_ok = [p>0 for p in region] == [g>0 for g in target_region]
            mapping = ('support_error' if not support_ok else 'region_exact' if region == target_region else 'ID_binding_only_error')
            rules_ok = all(pred[k] == target[k] for k in ('traverse_vector','cost_vector'))
            key = mapping+('|TM_cost_exact' if rules_ok else '|TM_or_cost_error')
        strata[key] = strata.get(key,0)+1
    result['diagnostics']['factorization_counts'] = strata
    result['diagnostics']['distinct_valid_present_mapping_error_ids'] = present_error_ids
    result['diagnostics']['factorization_limit'] = 'Output discrepancy diagnostic, not causal attribution. Correct region with wrongT/C supports language/rule-pipeline review; mixed errors remain unknown. No GT used during model inference.'
    if result['valid_predictions'] < SCIENTIFIC_GATES['minimum_valid_predictions']:
        next_action = 'review_engineering_or_format_failures_without_resampling_original_run'
    elif present_error_ids < SCIENTIFIC_GATES['minimum_distinct_present_mapping_error_ids']:
        next_action = 'visual_binding_intervention_not_admitted_review_language_rules_or_other_candidate'
    else:
        next_action = 'root_may_review_one_falsifiable_visual_hypothesis_and_strong_controls_before_new_execution'
    decision = {'stage':'baseline_headroom_diagnostic','next_action':next_action,
                'scientific_gates':SCIENTIFIC_GATES,'visual_error_count':present_error_ids,
                'paid_expansion_authorized':False,'new_method_admitted':False,
                'confirmation_authorized':False,'publication_ready':False}
    return result,decision


def resources(calls,ledger,run_id):
    attempts = {k:v for k,v in ledger['attempts'].items() if v['run_id'] == run_id}
    for call in calls:
        entry = attempts.get(call['ledger_key'])
        if (entry is None or entry['key'] != call['key'] or entry.get('status') != 'settled'
                or entry.get('response_id') != call.get('response_id')
                or entry.get('cost_cny') != call['api_cost_cny']):
            raise ValueError('Successful response lacks matching settled resource receipt')
    return {'actual_attempts':len(attempts),'actual_calls':len(attempts),
        'successful_calls':len(calls),'successful_logical_calls':len(calls),
        'unknown_attempts':sum(e['status'] != 'settled' for e in attempts.values()),
        'input_tokens':sum(c['input_tokens'] for c in calls),
        'output_tokens':sum(c['output_tokens'] for c in calls),
        'cost_cny':sum(e.get('cost_cny',0) for e in attempts.values()),
        'conservative_cost_cny':sum(e.get('cost_cny',e['reserved_cny']) for e in attempts.values()),
        'reservation_cny_per_physical_attempt':3.06144,
        'returned_models':sorted({c['returned_model'] for c in calls if isinstance(c.get('returned_model'),str)}),
        'truncated_calls':sum(bool(c.get('truncated')) for c in calls)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--admission',required=True,type=Path)
    parser.add_argument('--admission-sha256',required=True)
    args = parser.parse_args()
    admission,_,manifest,targets_contract = read_admission(args.admission,args.admission_sha256)
    if args.run_id != admission['run_id']:
        raise ValueError('CLI run ID differs from root admission')
    run = BASE/'runs'/admission['run_id']
    with (run/'.run.lock').open('a') as run_lock, (PROJECT/'.api-single-worker.lock').open('a') as worker_lock:
        fcntl.flock(run_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(worker_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        protocol = strict_json((run/'PROTOCOL.json').read_bytes())
        status = strict_json((run/'STATUS.json').read_bytes())
        if (protocol.get('kind') != 'route_task2' or protocol.get('paid_admission') is not True
                or protocol.get('admission_sha256') != args.admission_sha256
                or protocol['targets_contract_sha256'] != admission['targets_contract']['sha256']
                or protocol['sample_ids'] != manifest['sample_ids']
                or status.get('status') not in {'model_completed','completed'}):
            raise ValueError('Only the frozen completed root-admitted baseline can open selected targets')
        verify_snapshots(run,protocol)
        predictions = strict_json((run/'PREDICTIONS.json').read_bytes())
        calls = [strict_json(line) for line in (run/'calls.jsonl').read_text().splitlines()]
        validate_complete_panel(predictions,calls,protocol['sample_ids'])
        accounting = resources(calls,strict_json((PROJECT/'API_LEDGER.json').read_bytes()),admission['run_id'])
        official = load_official_calculator()
        tick = time.monotonic()
        result,decision = evaluate_records(predictions,calls,protocol['sample_ids'],
            lambda:load_selected_targets(targets_contract),official)
        evidence = {name:sha((run/name).read_bytes()) for name in ('PROTOCOL.json','PREDICTIONS.json','calls.jsonl')}
        summary = {'run_id':admission['run_id'],'kind':'route_task2','mode':protocol['mode'],
                   'model':protocol['model'],'status':'completed_scored','created_at':now(),
                   **result,**accounting,'evidence_sha256':evidence,
                   'admission_sha256':args.admission_sha256,
                   'selected_targets_sha256':targets_contract['targets_sha256'],
                   'source_contract_sha256':protocol['source_contract_sha256'],
                   'input_manifest_sha256':protocol['manifest_sha256'],
                   'original_score_reproduced':False,'confirmation_evaluated':False,
                   'gate':decision,'cpu_score_seconds':time.monotonic()-tick}
        path = run/'SUMMARY.json'
        if path.exists():
            old = strict_json(path.read_bytes())
            for key in ('evidence_sha256','full_denominator_strict','official_metrics','selected_targets_sha256'):
                if old[key] != summary[key]:
                    raise ValueError('Existing result changed; never overwrite historical evidence')
            if strict_json((run/'DECISION.json').read_bytes()) != decision:
                raise ValueError('Existing decision changed')
        else:
            if (run/'DECISION.json').exists():
                raise ValueError('Partial result requires root review, not overwrite')
            atomic_json(run/'DECISION.json',decision)
            atomic_json(path,summary)
        status.update(status='completed',scored_at=now(),summary_sha256=sha(path.read_bytes()))
        atomic_json(run/'STATUS.json',status)
        print(json.dumps({key:summary[key] for key in ('run_id','selected_samples','valid_predictions','cost_cny','conservative_cost_cny')}))


if __name__ == '__main__':
    main()

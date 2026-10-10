"""Replay pinned SpaceCast exact scoring and paired scene-cluster diagnostics."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from cvpr_chart_run import PROJECT,atomic_json,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='bailian_qwen38_flash_spacecast_state_screen_v3')
    parser.add_argument('--revision', type=int, help='Write a new version without replacing existing scores or scorer snapshot')
    parser.add_argument('--partial-diagnostic',action='store_true',help='Only score complete saved pairs in a held run; never opens expansion')
    args=parser.parse_args()
    assert args.run_id.replace('-', '').replace('_', '').isalnum()
    base=PROJECT/'spacecast';run=base/'runs'/args.run_id
    status=json.loads((run/'STATUS.json').read_text())
    assert status['state']=='completed_predictions' or (args.partial_diagnostic and status['state'].startswith('held_'))
    assert args.revision is None or args.revision>=2
    suffix=f'_V{args.revision}' if args.revision else ''
    scorer_copy=run/(Path(__file__).stem+suffix+'.py')
    if scorer_copy.exists():
        assert scorer_copy.read_bytes()==Path(__file__).read_bytes(), 'Scorer version differs; preserve old result and use a new diagnostic version'
    else:
        scorer_copy.write_bytes(Path(__file__).read_bytes())
    protocol=json.loads((run/'PROTOCOL.json').read_text());manifest=json.loads((base/'data/MANIFEST.json').read_text())
    assert sha((base/'data/MANIFEST.json').read_bytes())==protocol['manifest_sha256']
    receipt=json.loads((PROJECT/'sources/spacecast/SOURCES.json').read_text())
    for name in ['spacecast_eval/scoring.py','spacecast_eval/protocol.py','spacecast_eval/data.py']:
        assert sha((PROJECT/'sources/spacecast'/name).read_bytes())==receipt['files'][name]['sha256']
    sys.path.insert(0,str(PROJECT/'sources/spacecast'))
    from spacecast_eval.scoring import score
    labels={r['question_uid']:r for r in json.loads((base/'data/development_labels.json').read_text())}
    preds=json.loads((run/'PREDICTIONS.json').read_text())
    observed={p['question_uid'] for p in preds}
    assert observed <= set(protocol['sample_ids'])
    ids=[k for k in protocol['sample_ids'] if k in observed] if args.partial_diagnostic else protocol['sample_ids']
    assert ids
    gold=[labels[k] for k in ids];assert all(r['partition']=='development' for r in gold)
    assert len(preds)==len(ids)*4
    assert len({(p['question_uid'],p['arm']) for p in preds})==len(preds)
    arms={};detail={}
    for arm in protocol['arms']:
        rows=[p for p in preds if p['arm']==arm];assert {r['question_uid'] for r in rows}==set(ids)
        report,per=score(gold,rows);detail[arm]=per
        arms[arm]={'n':len(rows),'score_mean':report['overall']['accuracy'],'valid':sum(p['valid'] for p in rows),
                   'types':report['by_type'],'diagnostic_macro_on_selected_types':report['macro_type_accuracy'],
                   'logical_calls':sum(p['logical_calls'] for p in rows),'logical_input_tokens':sum(p['logical_input_tokens'] for p in rows),
                   'logical_output_tokens':sum(p['logical_output_tokens'] for p in rows),'logical_seconds':sum(p['logical_seconds'] for p in rows),
                   'logical_api_cost_cny':sum(p['logical_api_cost_cny'] for p in rows)}
    groups={k:labels[k]['scene_group'] for k in ids};unique=sorted(set(groups.values()));pairs={}
    ours={r['question_uid']:r['correct'] for r in detail['state_invalidation']}
    for arm in ['direct','review','state_table']:
        other={r['question_uid']:r['correct'] for r in detail[arm]}
        delta={k:float(ours[k])-float(other[k]) for k in ids}
        vectors={g:[delta[k] for k in ids if groups[k]==g] for g in unique};rng=np.random.default_rng(17)
        draws=[np.concatenate([vectors[g] for g in rng.choice(unique,len(unique),replace=True)]).mean() for _ in range(5000)]
        pairs[arm]={'delta':float(np.mean(list(delta.values()))),'cluster_bootstrap_95ci':np.percentile(draws,[2.5,97.5]).tolist(),
                    'groups':len(unique),'improved':sum(v>0 for v in delta.values()),'regressed':sum(v<0 for v in delta.values())}
    audits=[p['state_audit'] for p in preds if p['arm']=='state_invalidation']
    changed=sum(bool(a.get('changed_count')) for a in audits);net=min(pairs[a]['improved']-pairs[a]['regressed'] for a in ['review','state_table'])
    calls=[json.loads(line) for line in (run/'calls.jsonl').read_text().splitlines()]
    summary={'scope':f'SpaceCast{len(ids)}/{len(protocol["sample_ids"])}问题、{len(unique)}场景组'+('中断部分诊断；不能判定完整筛选门' if args.partial_diagnostic else '完整开发诊断')+'；不是官方全量macro或独立确认','run_id':run.name,'dataset_revision':manifest['revision'],
             'source_commit':manifest['source_commit'],'paired_samples':len(ids),'planned_samples':len(protocol['sample_ids']),'scene_groups':len(unique),'screen_complete':not args.partial_diagnostic,
             'official_test_score':False,'confirmation_evaluated':False,'arms':arms,'paired_vs_state_invalidation':pairs,
             'state_dependency':{'changed_questions':changed,'unsupported':sum(a['status']=='unsupported' for a in audits),
                                 'verified_grounding':False,'new_spatial_facts_added':False},
             'minimum_net_improvements_over_review_and_table':net,'development_count_gate_passed':not args.partial_diagnostic and net>=3 and changed>0,
             'expansion_gate_authorized':False,'note':'Count gate alone never opens confirmation: frame/fact audit, scorer, independent coverage and novelty still required',
             'actual_calls':len(calls),'new_successful_calls':sum(not c.get('inherited_from_run') for c in calls),
             'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'cost_includes_cached_responses':True,
             'observed_sample_ids':ids,'missing_sample_ids':[k for k in protocol['sample_ids'] if k not in observed],
             'scorer_sha256':sha(Path(__file__).read_bytes()),'model':protocol['model'],'publication_ready':False,
             'comparability':'Same total generated-token ceilings and observed images; actual input/output tokens and alias stochasticity differ'}
    if isinstance(protocol.get('retry'),dict):
        ledger=json.loads((PROJECT/'API_LEDGER.json').read_text())
        unresolved=[{'key':e['key'],'run_id':e['run_id'],'reserved_cny':e['reserved_cny'],'usage':'unknown'}
                    for e in ledger['attempts'].values() if 'spacecast' in e['run_id'] and e['key'].split('|')[0] in ids and e['status']!='settled']
        summary['comparability']='Same observed images and1792-token ceiling per successful path; HTTP retries are extra attempts with unreported failed usage, so total generated tokens/FLOPs are not strictly matched. Rolling-alias/cache dates differ.'
        summary['retry_accounting']={'failed_attempts_with_unknown_usage':unresolved,'full_failed_reservations_retained':True,
                                     'strict_total_generation_budget_match':False,'all_attempts_count_toward_project_and_phase_caps':True}
    if args.revision:
        original=json.loads((run/'SUMMARY.json').read_text())
        assert original['arms']==summary['arms'] and original['paired_vs_state_invalidation']==summary['paired_vs_state_invalidation']
        summary['supersedes']={'file':'SUMMARY.json','sha256':sha((run/'SUMMARY.json').read_bytes()),
                              'scope':'Resource comparability clarification; all numeric scores, paired effects and scientific decision unchanged'}
    prefix='PARTIAL_' if args.partial_diagnostic else ''
    summary_file=prefix+'SUMMARY'+suffix+'.json'
    atomic_json(run/(prefix+'SCORED_PREDICTIONS'+suffix+'.json'),detail);atomic_json(run/summary_file,summary)
    status['partial_diagnostic_score_computed' if args.partial_diagnostic else 'scientific_score_computed']=True
    status['summary_file']=summary_file
    atomic_json(run/'STATUS.json',status)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

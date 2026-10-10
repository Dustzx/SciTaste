"""Exact canonical-option development scoring; not the official cyclic leaderboard."""
import argparse
import json

import numpy as np

from cvpr_chart_api import now
from cvpr_chart_run import atomic_json, sha
from cvpr_hrbench_run import BASE, ARMS


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True)
    p.add_argument('--canonical-input-reuse',action='store_true',help='Versioned no-call correction: identical sample/prompt/image inputs reuse first persisted receipt')
    args=p.parse_args()
    assert args.run_id.replace('-','').replace('_','').isalnum()
    run=BASE/'runs'/args.run_id
    protocol=json.loads((run/'PROTOCOL.json').read_text());status=json.loads((run/'STATUS.json').read_text())
    assert status['state']=='completed_predictions' or (args.canonical_input_reuse and status['state']=='completed_scored'), 'Complete paired screen is required'
    preds=json.loads((run/'PREDICTIONS.json').read_text())
    correction=[]
    if args.canonical_input_reuse:
        calls=[json.loads(s) for s in (run/'calls.jsonl').read_text().splitlines()]
        by_key={c['key']:c for c in calls};first={}
        for c in calls:first.setdefault((c['sample_id'],c['prompt_sha256']),c)
        for pred in preds:
            old=by_key[pred['actual_call_keys'][-1]];canonical=first[(old['sample_id'],old['prompt_sha256'])]
            if canonical['key']!=old['key']:
                answer=(canonical['parsed'] or {}).get('answer')
                valid=isinstance(answer,str) and len(answer.strip())==1 and answer.strip() in 'ABCD' and not canonical['truncated']
                correction.append({'id':pred['id'],'arm':pred['arm'],'old_key':old['key'],'canonical_key':canonical['key'],
                                   'old_answer':pred['answer'],'canonical_answer':answer.strip() if valid else None,
                                   'prompt_sha256':old['prompt_sha256'],'policy':'First persisted same-input response, selected without target labels'})
                pred['answer']=answer.strip() if valid else None;pred['valid']=valid
                pred['actual_call_keys'][-1]=canonical['key']
                charge=[by_key[k] for k in pred['actual_call_keys']]
                for k,field in [('logical_input_tokens','input_tokens'),('logical_output_tokens','output_tokens'),('logical_seconds','elapsed_seconds'),('logical_api_cost_cny','api_cost_cny')]:pred[k]=sum(c[field] for c in charge)
    assert len(preds)==len(protocol['sample_ids'])*len(ARMS)
    assert len({(r['id'],r['arm']) for r in preds})==len(preds)
    assert {r['id'] for r in preds}==set(protocol['sample_ids'])
    assert {r['arm'] for r in preds}==set(ARMS)
    manifest=json.loads((BASE/'data/MANIFEST.json').read_text())
    path=BASE/'data/development_labels.json'
    assert sha(path.read_bytes())==manifest['files'][path.name]
    labels={r['id']:r for r in json.loads(path.read_text())}
    details=[]
    for r in preds:
        target=labels[r['id']];assert target['partition']=='development' and target['image_group']==r['image_group']
        details.append({**r,'target':target['answer'],'score':int(r['valid'] and r['answer']==target['answer'])})
    by_arm={a:{r['id']:r for r in details if r['arm']==a} for a in ARMS}
    arms={}
    for a,lookup in by_arm.items():
        rows=list(lookup.values())
        arms[a]={'n':len(rows),'score_mean':float(np.mean([r['score'] for r in rows])),'valid':sum(r['valid'] for r in rows),
                 'categories':{c:{'n':sum(r['category']==c for r in rows),'score_mean':float(np.mean([r['score'] for r in rows if r['category']==c]))} for c in sorted({r['category'] for r in rows})},
                 **{k:sum(r[k] for r in rows) for k in ['logical_calls','logical_input_tokens','logical_output_tokens','logical_seconds','logical_api_cost_cny']}}
    pairs={};ours=by_arm['crop_linked']
    groups=sorted({r['image_group'] for r in ours.values()})
    for a in ARMS:
        if a=='crop_linked':continue
        deltas={g:[ours[k]['score']-by_arm[a][k]['score'] for k in ours if ours[k]['image_group']==g] for g in groups}
        rng=np.random.default_rng(2710)
        draws=[np.concatenate([deltas[g] for g in rng.choice(groups,size=len(groups),replace=True)]).mean() for _ in range(5000)]
        improved=[k for k in ours if ours[k]['score']>by_arm[a][k]['score']]
        regressed=[k for k in ours if ours[k]['score']<by_arm[a][k]['score']]
        pairs[a]={'delta':float(np.mean([ours[k]['score']-by_arm[a][k]['score'] for k in ours])),
                  'cluster_bootstrap_95ci':np.percentile(draws,[2.5,97.5]).tolist(),'groups':len(groups),'bootstrap_replicates':5000,'seed':2710,
                  'improved':len(improved),'regressed':len(regressed),'improved_ids':improved,'regressed_ids':regressed}
    supported=sum(r['supported_regions']==2 for r in ours.values())
    numerical_gate=all(pairs[a]['improved']-pairs[a]['regressed']>=3 for a in ['crop_plain','review']) and supported>=20 and arms['direct']['score_mean']<.9
    summary={'run_id':args.run_id,'verified_at':now(),'scope':'Exploratory HR-Bench 4K, canonical one-option-order development screen; not official 800-row/cyclic score',
             'model':protocol['model'],'paired_samples':len(ours),'image_groups':len(groups),'screen_complete':True,'arms':arms,'paired_vs_crop_linked':pairs,
             'two_supported_regions':supported,'numerical_expansion_gate':numerical_gate,
             'expansion_gate_authorized':False,'case_audit_required':True,'confirmation_evaluated':False,'publication_ready':False,
             'decision':'Mechanism audit required before any confirmation' if numerical_gate else 'Stop this version: failed prespecified development expansion gate',
             'scorer':'Strict exact JSON option letter against canonical label; invalid/truncated=incorrect. Official repo also provides LLM judgment and circular grouping; neither silently emulated.',
             'actual_calls':status['actual_calls'],'api_cost_cny':status['api_cost_cny'],
             'resource_limits':protocol['pixel_budget_caveat']+' Shared locate counted in each crop arm; failed retries retain unknown reservations and can include extra unreported server generation.'}
    suffix='_V2' if args.canonical_input_reuse else ''
    if args.canonical_input_reuse:
        summary['analysis_correction']={'scope':'No new calls; original raw receipts, predictions, SUMMARY and all actual costs preserved',
            'changes':correction,'original_summary_sha256':sha((run/'SUMMARY.json').read_bytes()),'script_sha256':sha(open(__file__,'rb').read())}
        summary['negative_control_limit']='Crop-order/bookkeeping mismatch is not guaranteed to destroy semantic identity: the model can still recover identity visually. Invariance alone does not establish ignored correspondence.'
    atomic_json(run/('SCORED_PREDICTIONS'+suffix+'.json'),details);atomic_json(run/('SUMMARY'+suffix+'.json'),summary)
    atomic_json(run/'STATUS.json',{**status,'state':'completed_scored','verified_at':now(),'scientific_gate_passed':numerical_gate,'summary_file':'SUMMARY'+suffix+'.json'})
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

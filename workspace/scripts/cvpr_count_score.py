"""Development-only exact counting readout; never exposes labels to inference."""
import argparse
import json
import numpy as np

from cvpr_count_run import BASE
from cvpr_chart_api import now
from cvpr_chart_run import atomic_json,sha


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--headroom',action='store_true');p.add_argument('--dataset',choices=['tallybench','fsc147'],default='tallybench');args=p.parse_args()
    base=BASE if args.dataset=='tallybench' else BASE/'fsc147'
    assert args.run_id.replace('-','').replace('_','').isalnum();run=base/'runs'/args.run_id
    proto=json.loads((run/'PROTOCOL.json').read_text());status=json.loads((run/'STATUS.json').read_text())
    path=base/'data/development_labels.json';manifest=json.loads((base/'data/MANIFEST.json').read_text());assert sha(path.read_bytes())==manifest['files'][path.name]
    labels={r['id']:r for r in json.loads(path.read_text())}
    name='BASELINE_PREDICTIONS.json' if args.headroom else 'PREDICTIONS.json';rows=json.loads((run/name).read_text())
    assert len(rows)==len(proto['sample_ids'])==32 and {r['id'] for r in rows}==set(proto['sample_ids'])
    for r in rows:assert labels[r['id']]['partition']=='development' and labels[r['id']]['image_group']==r['image_group']
    if args.headroom:
        correct=sum(r['direct']['answer']==labels[r['id']]['answer'] for r in rows);proceed=correct/len(rows)<.85
        head={'verified_at':now(),'n':len(rows),'correct':correct,'exact_accuracy':correct/len(rows),'proceed_full':proceed,
              'gate':proto['headroom_gate'],'decision':'Proceed frozen full paired screen' if proceed else 'Stop saturated benchmark/version; no full calls','confirmation_evaluated':False}
        atomic_json(run/'HEADROOM.json',head)
        if not proceed:
            calls=[json.loads(s) for s in (run/'calls.jsonl').read_text().splitlines()]
            summary={'run_id':args.run_id,'verified_at':now(),'scope':'Fixed32 development-only baseline headroom check; method arms NOT evaluated','model':proto['model'],
                'paired_samples':None,'arms':{'direct':{'n':len(rows),'score_mean':correct/len(rows),'valid':sum(r['direct']['answer'] is not None for r in rows),'correct':correct}},
                'decision':head['decision'],'headroom_gate_passed':False,'confirmation_evaluated':False,'publication_ready':False,
                'actual_calls':len(calls),'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'method_gain':None}
            atomic_json(run/'SUMMARY.json',summary)
            atomic_json(run/'STATUS.json',{**status,'state':'stopped_headroom','verified_at':now(),'summary_file':'SUMMARY.json','scientific_gate_passed':False})
        print(json.dumps(head,indent=2));return
    arms=proto['arms'];scores={a:[] for a in arms};details=[]
    for r in rows:
        target=labels[r['id']]['answer'];detail={**r,'target':target}
        for a in arms:
            answer=r[a]['answer'];score=int(answer==target);scores[a].append(score);detail[a]={**r[a],'score':score,'absolute_error':abs(answer-target) if answer is not None else None}
        details.append(detail)
    metrics={}
    for a in arms:
        valid=[d[a]['absolute_error'] for d in details if d[a]['absolute_error'] is not None]
        metrics[a]={'n':32,'correct':sum(scores[a]),'score_mean':float(np.mean(scores[a])),'valid':len(valid),'mae_valid_only':float(np.mean(valid)) if valid else None,
                    'rmse_valid_only':float(np.sqrt(np.mean(np.square(valid)))) if valid else None,
                    'categories':{c:{'n':sum(d['image_type']==c for d in details),'score_mean':float(np.mean([d[a]['score'] for d in details if d['image_type']==c]))} for c in sorted({d['image_type'] for d in details})},
                    **{k:sum(d[a][k] for d in details) for k in ['logical_calls','input_tokens','output_tokens','api_cost_cny','seconds']}}
    pairs={};ours=np.array(scores['conservation_decode'])
    for a in arms:
        if a=='conservation_decode':continue
        delta=ours-np.array(scores[a]);rng=np.random.default_rng(2710);boot=[float(np.mean(rng.choice(delta,len(delta),replace=True))) for _ in range(5000)]
        pairs[a]={'delta':float(delta.mean()),'cluster_bootstrap_95ci':np.percentile(boot,[2.5,97.5]).tolist(),'groups':32,'seed':2710,'replicates':5000,
            'improved':sum(int(v>0) for v in delta),'regressed':sum(int(v<0) for v in delta),'improved_ids':[r['id'] for r,v in zip(rows,delta) if v>0],'regressed_ids':[r['id'] for r,v in zip(rows,delta) if v<0]}
        error_delta=[d[a]['absolute_error']-d['conservation_decode']['absolute_error'] for d in details if d[a]['absolute_error'] is not None and d['conservation_decode']['absolute_error'] is not None]
        rng=np.random.default_rng(2710)
        pairs[a]['mae_reduction_valid_paired']={'n':len(error_delta),'mean':float(np.mean(error_delta)) if error_delta else None,
            'cluster_bootstrap_95ci':np.percentile([np.mean(rng.choice(error_delta,len(error_delta),replace=True)) for _ in range(5000)],[2.5,97.5]).tolist() if error_delta else None}
    accepted=[d for d in details if d['conservation_decode']['accepted']]
    repairs=[d['id'] for d in accepted if d['direct']['answer'] is not None and not d['direct']['score'] and d['conservation_decode']['score']]
    invalid_recoveries=[d['id'] for d in accepted if d['direct']['answer'] is None and d['conservation_decode']['score']]
    wrong_consistent=[d['id'] for d in accepted if not d['conservation_decode']['score']]
    gate=all(pairs[a]['improved']-pairs[a]['regressed']>=3 for a in ['transform_vote','partition_sum']) and len(accepted)>=8 and len(repairs)>=2
    calls=[json.loads(s) for s in (run/'calls.jsonl').read_text().splitlines()]
    summary={'run_id':args.run_id,'verified_at':now(),'scope':proto['scope'],'model':proto['model'],'paired_samples':32,'arms':metrics,'paired_vs_conservation_decode':pairs,
        'accepted_decodes':len(accepted),'accepted_repairs_of_global':repairs,'accepted_invalid_global_recoveries':invalid_recoveries,'accepted_but_wrong':wrong_consistent,
        'numerical_expansion_gate':gate,'expansion_gate_authorized':False,'confirmation_evaluated':False,'publication_ready':False,
        'decision':'Requires visual/novelty audit before confirmation' if gate else 'Stop this version: failed frozen expansion gate',
        'actual_calls':len(calls),'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'truncations':sum(c['truncated'] for c in calls),
        'scorer':'Strict JSON integer equality; invalid/truncated incorrect. MAE only on valid outputs, never fills missing counts with zero.',
        'limits':proto['limits'],'headroom_file_sha256':sha((run/'HEADROOM.json').read_bytes())}
    atomic_json(run/'SCORED_PREDICTIONS.json',details);atomic_json(run/'SUMMARY.json',summary)
    atomic_json(run/'STATUS.json',{**status,'state':'completed_scored','verified_at':now(),'scientific_gate_passed':gate,'summary_file':'SUMMARY.json'})
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()

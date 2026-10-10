"""CPU readout for task-input comparison on the exposed FSC development set."""
import argparse,json
import numpy as np
from cvpr_fsc_contract import BASE,ARMS
from cvpr_chart_run import atomic_json,sha
from cvpr_chart_api import now

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);args=p.parse_args();assert args.run_id.replace('_','').replace('-','').isalnum()
    base=BASE/'fsc147';run=base/'runs'/args.run_id;status=json.loads((run/'STATUS.json').read_text());assert status['state']=='completed_predictions'
    proto=json.loads((run/'PROTOCOL.json').read_text());manifest=json.loads((base/'data/MANIFEST.json').read_text());path=base/'data/development_labels.json';assert sha(path.read_bytes())==manifest['files'][path.name]
    arms=proto['arms'];labels={r['id']:r for r in json.loads(path.read_text())};rows=json.loads((run/'PREDICTIONS.json').read_text());assert len(rows)==32*len(arms)
    assert len({(r['id'],r['arm']) for r in rows})==32*len(arms) and {r['id'] for r in rows}==set(proto['sample_ids'])
    for r in rows:assert labels[r['id']]['partition']=='development' and labels[r['id']]['image_group']==r['image_group']
    details=[{**r,'target':labels[r['id']]['answer'],'score':int(r['answer']==labels[r['id']]['answer']),'absolute_error':abs(r['answer']-labels[r['id']]['answer']) if r['valid'] else None} for r in rows]
    lookup={a:{r['id']:r for r in details if r['arm']==a} for a in arms};metrics={}
    for a in arms:
        r=list(lookup[a].values());err=[x['absolute_error'] for x in r if x['valid']]
        metrics[a]={'n':len(r),'valid':len(err),'score_mean':float(np.mean([x['score'] for x in r])),'correct':sum(x['score'] for x in r),
            'mae_valid_only':float(np.mean(err)) if err else None,'rmse_valid_only':float(np.sqrt(np.mean(np.square(err)))) if err else None,
            **{k:sum(x[k] for x in r) for k in ['logical_calls','logical_input_tokens','logical_output_tokens','logical_api_cost_cny','logical_seconds']}}
    ids=proto['sample_ids'];delta=[lookup['exemplar_count_only'][k]['score']-lookup['class_count_only'][k]['score'] for k in ids] if len(arms)==2 else [];rng=np.random.default_rng(2710)
    pair={'delta':float(np.mean(delta)),'cluster_bootstrap_95ci':np.percentile([np.mean(rng.choice(delta,32,replace=True)) for _ in range(5000)],[2.5,97.5]).tolist(),
        'groups':32,'improved_ids':[k for k,d in zip(ids,delta) if d>0],'regressed_ids':[k for k,d in zip(ids,delta) if d<0]} if delta else None
    calls=[json.loads(l) for l in (run/'calls.jsonl').read_text().splitlines()];saturated=metrics['exemplar_count_only']['score_mean']>=.85
    summary={'run_id':args.run_id,'verified_at':now(),'scope':proto['scope'],'model':proto['model'],'samples':32,'paired_samples':32 if len(arms)==2 else None,'arms':metrics,'paired_exemplar_vs_class':pair,
        'headroom_saturated':saturated,'confirmation_evaluated':False,'publication_ready':False,'novel_method_gain_claim':False,
        'decision':'Stop saturated task' if saturated else 'Correct task input has headroom; benchmark candidate only, new mechanism still required',
        'actual_calls':len(calls),'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'truncations':sum(c['truncated'] for c in calls),'limits':proto['interpretation']}
    atomic_json(run/'SCORED_PREDICTIONS.json',details);atomic_json(run/'SUMMARY.json',summary);atomic_json(run/'STATUS.json',{**status,'state':'completed_scored','summary_file':'SUMMARY.json','verified_at':now()})
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()

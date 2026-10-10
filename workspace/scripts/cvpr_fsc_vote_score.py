"""CPU score for the prespecified strong-model ensemble; development only."""
import argparse,json
import numpy as np
from cvpr_fsc_vote import BASE
from cvpr_chart_run import atomic_json,sha
from cvpr_chart_api import now

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);args=p.parse_args();assert args.run_id.replace('_','').replace('-','').isalnum()
    base=BASE/'fsc147';run=base/'runs'/args.run_id;status=json.loads((run/'STATUS.json').read_text());assert status['state']=='completed_predictions'
    proto=json.loads((run/'PROTOCOL.json').read_text());manifest=json.loads((base/'data/MANIFEST.json').read_text());path=base/'data/development_labels.json';assert sha(path.read_bytes())==manifest['files'][path.name]
    labels={r['id']:r for r in json.loads(path.read_text())};rows=json.loads((run/'PREDICTIONS.json').read_text());assert len(rows)==64 and len({(r['id'],r['arm']) for r in rows})==64
    lookup={arm:{} for arm in proto['arms']};details=[];metrics={}
    for r in rows:
        target=labels[r['id']];assert target['partition']=='development' and target['image_group']==r['image_group']
        d={**r,'target':target['answer'],'score':int(r['valid'] and r['answer']==target['answer']),'absolute_error':abs(r['answer']-target['answer']) if r['valid'] else None};lookup[r['arm']][r['id']]=d;details.append(d)
    for arm,entries in lookup.items():
        assert set(entries)==set(proto['sample_ids']);rs=list(entries.values());errs=[r['absolute_error'] for r in rs if r['valid']]
        metrics[arm]={'n':32,'valid':len(errs),'correct':sum(r['score'] for r in rs),'score_mean':float(np.mean([r['score'] for r in rs])),'mae_valid_only':float(np.mean(errs)) if errs else None,'rmse_valid_only':float(np.sqrt(np.mean(np.square(errs)))) if errs else None,**{k:sum(r[k] for r in rs) for k in ['logical_calls','logical_input_tokens','logical_output_tokens','logical_elapsed_seconds','logical_api_cost_cny']}}
    ids=proto['sample_ids'];a=lookup['direct'];b=lookup['transform_vote'];delta=np.array([b[k]['score']-a[k]['score'] for k in ids]);rng=np.random.default_rng(2710)
    pair={'groups':32,'delta':float(delta.mean()),'cluster_bootstrap_95ci':np.percentile([rng.choice(delta,32,replace=True).mean() for _ in range(5000)],[2.5,97.5]).tolist(),'improved_ids':[k for k in ids if b[k]['score']>a[k]['score']],'regressed_ids':[k for k in ids if b[k]['score']<a[k]['score']]}
    calls=[json.loads(l) for l in (run/'calls.jsonl').read_text().splitlines()];saturated=metrics['transform_vote']['score_mean']>=.85
    summary={'run_id':args.run_id,'verified_at':now(),'scope':proto['scope'],'model':proto['model'],'samples':32,'paired_samples':32,'arms':metrics,'paired_vote_vs_direct':pair,'headroom_saturated':saturated,'confirmation_evaluated':False,'publication_ready':False,'novel_method_gain_claim':False,'decision':'Stop saturated task' if saturated else 'Strong seven-view baseline still has headroom; freeze benchmark diagnostics, select distinct mechanism','actual_calls':len(calls),'reused_identity_calls':32,'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'truncations':sum(c['truncated'] for c in calls),'limits':'All32 development groups already exposed; D4 transformation and vote are a strong baseline, not a new method. Point counts unchanged. Provider weight hash/compute unknown. MAE/RMSE exclude invalid answers; invalids remain incorrect in exact.'}
    atomic_json(run/'SCORED_PREDICTIONS.json',details);atomic_json(run/'SUMMARY.json',summary);atomic_json(run/'STATUS.json',{**status,'state':'completed_scored','summary_file':'SUMMARY.json','verified_at':now()});print(json.dumps(summary,indent=2))
if __name__=='__main__':main()

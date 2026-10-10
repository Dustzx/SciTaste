"""Score the fixed CPU reference after all 32 predictions, separately from inference."""
import json
from pathlib import Path
import numpy as np
from cvpr_countingdino_run import BASE, digest, save
from cvpr_chart_api import now


def main():
    run = BASE/'runs/countingdino_vitl14reg_cpu_v1'
    protocol = json.loads((run/'PROTOCOL.json').read_text())
    rows = json.loads((run/'PREDICTIONS.json').read_text())
    status = json.loads((run/'STATUS.json').read_text())
    assert status['state']=='completed_predictions'
    assert len(rows)==32 and {r['id'] for r in rows}==set(protocol['sample_ids'])
    manifest = json.loads((BASE/'data/MANIFEST.json').read_text())
    labelpath=BASE/'data/development_labels.json'
    assert digest(labelpath)==manifest['files'][labelpath.name]
    labels={r['id']:r for r in json.loads(labelpath.read_text())}
    scored=[]
    for r in rows:
        label=labels[r['id']]
        assert label['partition']=='development' and r['image_group']==label['image_group']
        target=label['answer']
        scored.append({**r,'target':target,'absolute_error':abs(r['answer']-target),
                       'normalized_absolute_error':abs(r['answer']-target)/max(1,target)})
    errors=np.array([r['absolute_error'] for r in scored])
    summary={'run_id':run.name,'verified_at':now(),'samples':32,'valid':32,
             'model':protocol['model'],'mae':float(errors.mean()),'rmse':float(np.sqrt(np.mean(errors**2))),
             'mean_relative_error':float(np.mean([r['normalized_absolute_error'] for r in scored])),
             'rounded_exact_diagnostic':sum(round(r['answer'])==r['target'] for r in scored),
             'elapsed_prediction_seconds':sum(r['elapsed_seconds'] for r in rows),
             'peak_rss_mib':max(r['peak_rss_mib'] for r in rows),'local_gpu':False,
             'api_cost_cny':0,'scope':protocol['scope'],'information_difference':protocol['information_difference'],
             'confirmation_evaluated':False,'novel_method_gain_claim':False,
             'limitations':['Published count is continuous; MAE/RMSE are unrounded.',
                            'Original FSC density maps not used as targets; original point counts used.',
                            'Pinned current DINO source and torch2.5.1 CPU differ from original paper environment.',
                            'Not same-information/compute as VLM; not a full official-test reproduction.']}
    summary['arms']={'countingdino':{'n':32,'valid':32,'mae_valid_only':summary['mae'],
                                  'rmse_valid_only':summary['rmse']}}
    save(run/'SCORED_PREDICTIONS.json',scored)
    save(run/'SUMMARY.json',summary)
    save(run/'STATUS.json',{**status,'state':'completed_scored','verified_at':now()})
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()

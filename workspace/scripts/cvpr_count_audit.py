"""Audit all completed FSC development decodes without issuing model requests."""
import argparse,json
from collections import Counter
from PIL import Image
import numpy as np
from cvpr_count_code import MATRIX,valid_count
from cvpr_count_run import BASE
from cvpr_hrbench_views import letterbox
from cvpr_chart_run import ROOT,atomic_json,sha
from cvpr_chart_api import now

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);args=p.parse_args();assert args.run_id.replace('_','').replace('-','').isalnum()
    base=BASE/'fsc147';run=base/'runs'/args.run_id;status=json.loads((run/'STATUS.json').read_text());assert status['state']=='completed_scored'
    rows=json.loads((run/'SCORED_PREDICTIONS.json').read_text());inputs={r['id']:r for r in map(json.loads,(base/'data/development_inputs.jsonl').read_text().splitlines())}
    annotations=json.loads((base/'sources/annotation_FSC147_384.json').read_text());calls={r['key']:r for r in map(json.loads,(run/'calls.jsonl').read_text().splitlines())}
    audits=[]
    for r in rows:
        row=inputs[r['id']];im=Image.open(ROOT/row['image']['path']).convert('RGB');d=r['conservation_decode'];anno=annotations[row['source_name']]
        _,transform=letterbox(im,768)
        point_audit={'available':False,'reason':'Point coordinates are annotation locations, not certified bbox centers'}
        resized_contract=abs(anno['W']*anno['ratio_w']-im.width)<1e-6 and abs(anno['H']*anno['ratio_h']-im.height)<1e-6
        if resized_contract:
            points=np.asarray(anno['points'],dtype=float)
            if points.ndim==2 and points.shape[1]==2 and np.all(points>=0) and np.all(points[:,0]<=im.width) and np.all(points[:,1]<=im.height):
                width=transform['size'][0];offset=transform['offset'][0]
                indices=np.minimum(2,np.floor((points[:,0]*width/im.width+offset)/256).astype(int))
                cells=np.bincount(indices,minlength=3).tolist();ideal=(MATRIX@cells).tolist()
                mismatches=[i for i,y in enumerate(d['counts']) if not valid_count(y) or y!=ideal[i]]
                point_audit={'available':True,'cells':cells,'regional_point_counts':ideal,'measurement_mismatch_rows':mismatches,
                             'coordinate_contract':'annotation_FSC147_384 points are in resized image coordinates; W/H are original dimensions, W*ratio_w and H*ratio_h match actual raster; every stored point checked within raster bounds.',
                             'limitation':'Approximate ownership reference only: point is not certified visible bbox center; original labels may be ambiguous/inaccurate.'}
        accepted=d['accepted'];changed=d['answer']!=r['direct']['answer']
        if accepted:
            x=np.array(d['cells']);expected=(MATRIX@x).tolist();mismatch=[i for i,y in enumerate(d['counts']) if not valid_count(y) or y!=expected[i]]
            assert mismatch==d['mismatches'] and len(mismatch)<=1 and int(x.sum())==d['answer'] and np.all(x>=0)
        audits.append({'id':r['id'],'category':r['category'],'target':r['target'],'direct':r['direct']['answer'],'vote':r['transform_vote']['answer'],
            'sum':r['partition_sum']['answer'],'decoded':d['answer'],'accepted':accepted,'changed_global':changed,
            'correct':bool(d['score']),'valid_numerical_global_repair':accepted and r['direct']['answer'] is not None and not r['direct']['score'] and bool(d['score']),
            'invalid_global_recovery':accepted and r['direct']['answer'] is None and bool(d['score']),
            'accepted_wrong':accepted and not bool(d['score']),'code_mismatches':d['mismatches'],'counts':d['counts'],'point_reference':point_audit,
            'truncated_call_keys':[k for k in set(d['call_keys']+r['transform_vote']['call_keys']) if calls[k]['truncated']]})
    audit={'verified_at':now(),'run_id':args.run_id,'scope':'All fixed32 exposed FSC development images; no model calls or confirmation evaluation',
        'summary_sha256':sha((run/'SUMMARY.json').read_bytes()),'accepted':sum(a['accepted'] for a in audits),'changed_global':sum(a['changed_global'] for a in audits),
        'accepted_wrong':sum(a['accepted_wrong'] for a in audits),'valid_numerical_repairs':sum(a['valid_numerical_global_repair'] for a in audits),
        'invalid_global_recoveries':sum(a['invalid_global_recovery'] for a in audits),'decoded_contract_checks_pass':True,
        'point_reference_available':sum(a['point_reference']['available'] for a in audits),'manual_visual_audit_complete':False,'cases':audits,
        'limits':'Point references never enter inference/decoder. A correct total or algebraic agreement alone does not validate object identity or center assignment. No label modifications.'}
    audit['analysis_correction']={'scope':'Point-reference metadata interpretation only; original audit/summary/predictions/score/decision remain unchanged',
        'original_audit_sha256':sha((run/'MECHANISM_AUDIT.json').read_bytes()),'script_sha256':sha(open(__file__,'rb').read())}
    atomic_json(run/'MECHANISM_AUDIT_V2.json',audit);print(json.dumps({k:v for k,v in audit.items() if k!='cases'},indent=2))

if __name__=='__main__':main()

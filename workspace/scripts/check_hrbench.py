"""No-call checks for view provenance, unsupported addresses and pricing."""
import json
import tempfile
import threading
from pathlib import Path

import requests
from PIL import Image

import cvpr_chart_api
from cvpr_api_retry import PaidRequester
from cvpr_hrbench_views import letterbox, regions, views, correspondence
from cvpr_hrbench_run import cached_response


def main():
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    image=Image.new('RGB',(200,100),'white')
    image.paste('red',(20,10,60,40));image.paste('blue',(120,60,160,90))
    _,t=letterbox(image,1024)
    check('letterbox_aspect_and_offset',t['size']==[1024,512] and t['offset']==[0,256])
    chosen,audit=regions({'regions':[{'description':'red','box':[100,300,300,450]},{'description':'blue','box':[600,550,800,700]}]},image)
    check('display_to_original_coordinate_roundtrip',[r['source_box'] for r in chosen]==[[20,10,60,40],[120,60,160,90]])
    a=views(image,chosen);b=views(image,chosen,linked=True);c=views(image,chosen,linked=True,shuffled=True)
    check('equal_raster_budget',[im.size for im in a]==[im.size for im in b]==[(1024,1024),(768,768),(768,768)])
    check('crop_pixels_unchanged_by_correspondence',a[1].tobytes()==b[1].tobytes() and a[2].tobytes()==b[2].tobytes())
    check('negative_control_only_swaps_crops',b[0].tobytes()==c[0].tobytes() and b[1].tobytes()==c[2].tobytes() and b[2].tobytes()==c[1].tobytes())
    check('metadata_refers_to_source_pixels',correspondence(chosen)[0]['source_box_pixels']==[20,10,60,40])
    receipt={'key':'q|linked','sample_id':'q','prompt_sha256':'same'}
    check('identical_inputs_reuse_response',cached_response({'q|linked':receipt},'q|shuffled','same') is receipt)
    check('different_sample_not_reused',cached_response({'q|linked':receipt},'another|shuffled','same') is None)
    for bad in [None,{}, {'regions':None},{'regions':[{'box':[1,2,0,3]}]}, {'regions':[{'box':[float('nan'),0,100,100]}]}]:
        fallback,_=regions(bad,image)
        check('unsupported_falls_back_without_inventing_evidence_'+str(len(checks)),all(not r['supported'] and r['source_box']==[0,0,200,100] for r in fallback))
    original=cvpr_chart_api.PROJECT
    try:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cvpr_chart_api.PROJECT=root
            (root/'API_AUTHORIZATION.json').write_text(json.dumps({'authorized_cny':300,'previous_blink_budget_inherited':False}))
            response=requests.Response();response.status_code=200
            response._content=json.dumps({'id':'fixture','model':'qwen3.8-27b','usage':{'prompt_tokens':100,'completion_tokens':10},
                'choices':[{'finish_reason':'stop','message':{'content':'{"answer":"A"}'}}]}).encode()
            saved=[]
            requester=PaidRequester(budget=cvpr_chart_api.Budget(),run=root,run_id='fixture',secret='fixture-secret',halt=threading.Event(),
                prices=(3,12),phase_cap=20,post=lambda *a,**k:response)
            requester.call(key='q|direct',cap=1024,body={'model':'qwen3.8-27b'},digest='fixture',save=saved.append)
            ledger=json.loads((root/'API_LEDGER.json').read_text());entry=next(iter(ledger['attempts'].values()))
            check('custom_model_full_context_reserved',abs(entry['reserved_cny']-(3+1024*12/1e6))<1e-12)
            check('custom_model_settlement_price',abs(saved[0]['api_cost_cny']-(100*3+10*12)/1e6)<1e-12)
    finally:
        cvpr_chart_api.PROJECT=original
    result={'checks':checks,'passed':len(checks),'paid_calls':0}
    (Path(__file__).resolve().parents[1]/'reports/fastresearch_hrbench_validation_20261010.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()

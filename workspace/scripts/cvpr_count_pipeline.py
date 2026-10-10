"""Supervise the prespecified baseline gate, paired screen and CPU scoring."""
import argparse,json,subprocess,sys
from pathlib import Path
from cvpr_count_run import BASE
from cvpr_chart_run import ROOT,atomic_json,sha
from cvpr_chart_api import now

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--dataset',choices=['tallybench','fsc147'],default='tallybench');args=p.parse_args()
    base=BASE if args.dataset=='tallybench' else BASE/'fsc147'
    assert args.run_id.replace('_','').replace('-','').isalnum();run=base/'runs'/args.run_id
    atomic_json(run/'PIPELINE.json',{'state':'baseline','updated_at':now(),'script_sha256':sha(Path(__file__).read_bytes()),'steps':['baseline32','headroom','conditional_full32','score'],'background_analysis_after_turn':False})
    def step(script,*rest):
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--run-id',args.run_id,'--dataset',args.dataset,*rest],cwd=ROOT)
        if result.returncode:
            atomic_json(run/'PIPELINE.json',{'state':'held_failure','step':script,'returncode':result.returncode,'updated_at':now()})
            raise SystemExit(result.returncode)
    step('cvpr_count_run.py','--mode','baseline')
    step('cvpr_count_score.py','--headroom')
    if not json.loads((run/'HEADROOM.json').read_text())['proceed_full']:
        atomic_json(run/'PIPELINE.json',{'state':'stopped_headroom','updated_at':now()});return
    atomic_json(run/'PIPELINE.json',{'state':'full_screen','updated_at':now()})
    step('cvpr_count_run.py','--mode','full');step('cvpr_count_score.py')
    atomic_json(run/'PIPELINE.json',{'state':'completed_scored','updated_at':now(),'next':'Agent must audit gate, cases and novelty; no confirmation queued'})

if __name__=='__main__':main()

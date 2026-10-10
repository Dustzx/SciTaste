"""One persistent, finite local GPU admission waiter. No paid API or training."""
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs/projects/fastresearch-cvpr2027/research"
STATE = PROJECT / "QUEUE_STATUS.json"
RUN_ID = "local_qwen35_screen_smoke_v2"


def status(**data):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps({"pid": os.getpid(), "observed_at": datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                     "run_id": RUN_ID, "scientific_training": False, "paid_api_calls": False, **data}, indent=2)+'\n')
    temp.replace(STATE)


def main():
    lock = (PROJECT / ".local-gpu-queue.lock").open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run = PROJECT / "runs" / RUN_ID
    if (run / "STATUS.json").exists():
        status(state="held_existing_run", reason="Never duplicate or retry an existing run")
        return
    while True:
        processes = subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'], text=True).strip()
        info = subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'], text=True).strip()
        free, util = map(int, info.splitlines()[0].split(','))
        if not processes and free >= 20480 and util <= 20:
            # Child repeats admission immediately before allocating any GPU memory.
            break
        status(state="waiting_gpu", free_mib=free, utilization=util,
               foreign_compute_pids=processes.splitlines(), poll_seconds=60,
               admission="no foreign compute processes, >=20GiB free, <=20% utilization")
        time.sleep(60)
    env_python = PROJECT / ".inference-env/bin/python"
    status(state="starting_bounded_smoke", free_mib=free, utilization=util, samples=2, arms=4)
    with (PROJECT/'local-smoke-v2.log').open('w') as log:
        child = subprocess.Popen([str(env_python), str(ROOT/'scripts/cvpr_chart_run.py'),
                    '--run-id',RUN_ID,'--limit','2','--arms','direct','review','structure','pixel_match'],
                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        status(state="running_bounded_smoke", child_pid=child.pid, samples=2, arms=4)
        code=child.wait()
    if code:
        status(state="held_smoke_failure", exit_code=code, log="local-smoke-v2.log")
        return
    with (PROJECT/'local-smoke-v2-score.log').open('w') as log:
        scored=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/cvpr_chart_score.py'),'--run-id',RUN_ID],
                         cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if scored.returncode:
        status(state="held_score_failure", exit_code=scored.returncode)
        return
    summary=json.loads((run/'SUMMARY.json').read_text())
    passed=all(a['valid']>=1 for a in summary['arms'].values())
    status(state="completed_bounded_smoke" if passed else "held_format_gate_failed", engineering_gate=passed,
           summary=str((run/'SUMMARY.json').relative_to(PROJECT)),
           scientific_gain_established=False, automatic_expansion=False,
           next_action="Agent checks actual grounding support and scientific opportunity before any larger study")


if __name__=='__main__':
    main()

"""No-call integration checks for retry decisions, accounting, and redaction."""
import json
import tempfile
import threading
from pathlib import Path

import requests

import cvpr_chart_api
from cvpr_api_retry import PaidRequester, retry_delay


def main():
    checks=[]
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def response(code, *, headers=None, content=None):
        r=requests.Response();r.status_code=code;r.headers.update(headers or {})
        r._content=json.dumps(content or {'error':{'code':'TemporaryError','message':'Bearer test-secret sk-12345'}}).encode()
        return r
    good={'id':'fake-response','model':'fixture','usage':{'prompt_tokens':100,'completion_tokens':10},
          'choices':[{'finish_reason':'stop','message':{'content':'{"answer":"A"}'}}]}
    original_project=cvpr_chart_api.PROJECT
    try:
        with tempfile.TemporaryDirectory() as temp:
            def fixture(sequence, *, prior=None, retry=True, save=None, log_fail=False, extra=None):
                directory=Path(temp)/str(len(list(Path(temp).iterdir())));directory.mkdir()
                cvpr_chart_api.PROJECT=directory
                (directory/'API_AUTHORIZATION.json').write_text(json.dumps({'authorized_cny':300,'previous_blink_budget_inherited':False}))
                if extra:
                    (directory/'API_LEDGER.json').write_text(json.dumps({'attempts':extra,'cap_cny':300}))
                budget=cvpr_chart_api.Budget(retry_own_failures=retry, phase_run_ids={'test','old-spacecast'})
                time=[0.0];posts=[];saved=[]
                def sleep(seconds):time[0]+=seconds
                def post(*args,**kwargs):
                    posts.append(kwargs);item=sequence.pop(0)
                    if isinstance(item,Exception):raise item
                    return item
                requester=PaidRequester(budget=budget,run=directory,run_id='test',secret='test-secret',halt=threading.Event(),
                                        prior_attempts=prior,post=post,monotonic=lambda:time[0],sleeper=sleep)
                if log_fail:
                    def fail(item):raise OSError('fake disk failure')
                    requester.event=fail
                error=None
                try:
                    requester.call(key='q|direct',cap=512,body={'model':'fixture'},digest='fixture',save=save or saved.append)
                except RuntimeError as exc:error=exc
                ledger=json.loads((directory/'API_LEDGER.json').read_text())
                return posts,saved,ledger,time[0],error,directory
            posts,saved,ledger,elapsed,error,directory=fixture([response(500),response(429,headers={'Retry-After':'95'}),response(200,content=good)])
            check('500_then429_then_success',len(posts)==3 and len(saved)==1 and error is None)
            check('backoff_and_retry_after_respected',elapsed>=125)
            check('all_three_attempts_have_distinct_durable_keys',len(ledger['attempts'])==3)
            check('unknown_reservations_not_released',abs(ledger['unresolved_reserved_cny']-2*(.8+512*2.7/1e6))<1e-12)
            check('public_estimate_plus_all_reservations',ledger['conservative_total_cny']==ledger['estimated_settled_cny']+ledger['unresolved_reserved_cny'])
            check('error_receipts_redact_credentials','test-secret' not in (directory/'ATTEMPTS.jsonl').read_text() and 'sk-12345' not in (directory/'ATTEMPTS.jsonl').read_text())
            posts,_,_,elapsed,error,_=fixture([requests.ReadTimeout(),response(200,content=good)])
            check('timeout_retries_without_user_prompt',len(posts)==2 and elapsed>=30 and error is None)
            abort={'error':{'code':'invalid_parameter_error','message':'<400> InternalError.Algo.InvalidParameter: Model output became abnormal while generating a JSON response for response_format. The generation was aborted because the partial output may be incomplete or invalid JSON. Please retry the request or adjust your prompt or JSON schema.'}}
            posts,_,_,_,error,_=fixture([response(400,content=abort),response(200,content=good)])
            check('observed_json_generation_abort400_retries',len(posts)==2 and error is None)
            posts,_,_,_,error,_=fixture([response(400,content={'error':{'code':'invalid_parameter_error','message':'Invalid image bytes'}})])
            check('ordinary_invalid_input400_not_blindly_repeated',len(posts)==1 and error is not None)
            posts,_,_,_,error,_=fixture([response(401)])
            check('authentication_error_not_blindly_repeated',len(posts)==1 and error is not None)
            posts,_,ledger,_,error,_=fixture([response(503),response(503),response(503)])
            check('three_attempts_are_hard_limit',len(posts)==3 and len(ledger['attempts'])==3 and error is not None)
            posts,_,ledger,_,error,_=fixture([response(503),response(200,content=good)],prior={'q|direct':1})
            check('historical_failure_counts_towards_limit',list(ledger['attempts'])==['test|q|direct|attempt-2','test|q|direct|attempt-3'] and len(posts)==2 and error is None)
            truncated=json.loads(json.dumps(good));truncated['choices'][0]['finish_reason']='length'
            posts,saved,_,_,error,_=fixture([response(200,content=truncated)])
            check('successful_truncation_is_not_resampled',len(posts)==1 and saved[0]['truncated'] and error is None)
            posts,_,ledger,_,error,_=fixture([response(200,content=good)],log_fail=True)
            check('post_settlement_log_failure_preserves_settlement',len(posts)==1 and all(e['status']=='settled' for e in ledger['attempts'].values()) and error is not None)
            posts,_,ledger,_,error,_=fixture([response(500)],retry=False)
            cvpr_chart_api.PROJECT=Path(temp)/'default-budget';cvpr_chart_api.PROJECT.mkdir()
            (cvpr_chart_api.PROJECT/'API_AUTHORIZATION.json').write_text(json.dumps({'authorized_cny':300,'previous_blink_budget_inherited':False}))
            (cvpr_chart_api.PROJECT/'API_LEDGER.json').write_text(json.dumps(ledger))
            try:
                cvpr_chart_api.Budget().change('blocked',record={'run_id':'test','pid':0,'reserved_cny':.8,'status':'pending'},phase_cap=20,run_id='test')
            except RuntimeError:check('legacy_default_remains_fail_closed',True)
            else:raise AssertionError('Legacy default changed')
            old={'old-spacecast|old':{'run_id':'old-spacecast','pid':0,'reserved_cny':.8,'status':'settled','cost_cny':19.9}}
            posts,_,_,_,error,_=fixture([response(200,content=good)],extra=old)
            check('phase_cap_includes_previous_cohorts',not posts and error is not None)
            check('http_date_retry_after',retry_delay(1,'Thu, 01 Jan 1970 00:02:00 GMT',wall_time=0)==120)
    finally:cvpr_chart_api.PROJECT=original_project
    report={'passed':len(checks),'checks':checks,'paid_calls':0,'fixture_only':True}
    (Path(__file__).resolve().parents[1]/'reports/fastresearch_api_retry_validation_20261010.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()

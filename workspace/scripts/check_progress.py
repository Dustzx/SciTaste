#!/usr/bin/env python3
"""Check report projection, evidence access, and the actual progress UI."""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8765'


def main():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append({'check': name, 'passed': True})

    def request(path, method='GET'):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, method=method), timeout=15) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    status, payload = request('/api/progress')
    check('progress_endpoint', status == 200)
    data = json.loads(payload)
    check('eight_projects_five_axes', len(data['projects']) == 8 and len(data['axes']) == 5)
    check('authored_verification_and_review_time_preserved', all(p['verification'] in {'local_verified','source_snapshot'} and p.get('reviewed_at') for p in data['projects']))
    check('all_project_details_projected', all(p['brief']['available'] and p['brief']['current'] and p['brief']['claim'] and len(p['brief']['sections']) == 5 and p['brief']['table_count'] >= 1 for p in data['projects']))
    check('at_most_three_candidates_with_separate_actual_jobs', len([b for b in data['portfolio']['branches'] if b['stage'] not in {'stopped','saturated','archived'}]) <= 3 and len([e for e in data['experiments'] if e.get('live')]) <= 1)
    check('test_feedback_lesson_discloses_scope', any(e['id']=='EXP-012' and '开发成绩' in e['action'] and '确认' in e['limits'] for e in data['experiences']))
    check('lessons_have_conditions_and_limits', all(e.get('trigger') and e.get('action') and e.get('limits') and e.get('evidence') for e in data['experiences']))
    lora = next(e for e in data['experiences'] if e['id'] == 'EXP-001')
    code, source = request('/api/progress/source?' + urllib.parse.urlencode({'key': lora['evidence'][0]['source_key']}))
    check('lora_evidence_accessible', code == 200 and '3.811' in json.loads(source)['content'])
    for key in ['../../.env', 'API_LEDGER.json', 'unknown']:
        check('unknown_source_denied_' + key, request('/api/progress/source?' + urllib.parse.urlencode({'key': key}))[0] == 404)
    check('http_writes_denied', request('/api/progress', 'POST')[0] == 405)
    run = next(e for e in data['experiments'] if e['name'] == 'bailian_qwen38_flash_spacecast_state_screen_v3')
    hr = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_flash_hrbench_correspondence_v1'), None)
    if hr:
        check('hr_versioned_correction_projected', bool(hr['summary'].get('analysis_correction')) and hr['summary']['actual_calls']==217)
    count = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_flash_count_conservation_v1'), None)
    if count:
        check('baseline_not_reported_as_full_pairs', count['completion_label']=='原图基线' and next(a for a in count['arms'] if a['arm']=='conservation_decode')['predictions']==0)
        check('saturation_stop_has_no_method_gain', count['summary']['method_gain'] is None and count['summary']['actual_calls']==32)
    contract = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_flash_fsc_input_contract_v1'), None)
    if contract and contract['summary']:
        check('input_contract_flat_schema_projected', contract['completed']==32 and all(a['predictions']==32 for a in contract['arms']))
        check('input_contract_not_method_gain', contract['summary']['novel_method_gain_claim'] is False)
    strong = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_max0902_fsc_headroom_v1'), None)
    if strong and strong['summary']:
        check('strong_single_baseline_not_paired', strong['completion_label']=='强型号基线' and strong['summary']['paired_samples'] is None and strong['completed']==32)
    vote = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_max0902_fsc_vote_v1'), None)
    if vote and vote['summary']:
        check('strong_vote_flat_schema_projected', vote['completion_label']=='强型号投票配对' and vote['completed']==32 and all(a['predictions']==32 for a in vote['arms']))
        check('reused_identity_full_logical_cost', vote['summary']['reused_identity_calls']==32 and vote['summary']['actual_calls']<=192 and vote['summary']['arms']['transform_vote']['logical_calls']==224)
        check('strong_vote_not_novel_contribution', vote['summary']['novel_method_gain_claim'] is False and vote['summary']['confirmation_evaluated'] is False)
    ownership = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_max0902_fsc_ownership_v1'), None)
    if ownership:
        check('ownership_flat_eight_arms_projected', ownership['completion_label']=='机制开发配对' and len(ownership['arms'])==8 and all(a['predictions']==ownership['completed'] for a in ownership['arms']))
        check('ownership_equal_ceilings_and_derived_cost_explained', '4调用/8192' in ownership['protocol'] and '派生控制全额' in ownership['protocol'])
    countingdino = next((e for e in data['experiments'] if e['name']=='countingdino_vitl14reg_cpu_v1'), None)
    if countingdino:
        check('cpu_reference_not_budget_matched_vlm', countingdino['completion_label']=='CPU视觉参考基线' and '额外示例位置与计算量单列' in countingdino['protocol'])
    gui = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_max0902_gui_headroom_v1'), None)
    if gui:
        check('gui_single_baseline_not_method_pairs', gui['completion_label']=='GUI强型号headroom基线' and len(gui['arms'])==1 and '高分辨率' in gui['protocol'])
    global_center = next((e for e in data['experiments'] if e['name']=='bailian_qwen38_max0902_fsc_global_center_v1'), None)
    if global_center:
        check('global_center_matched_input_three_arms', global_center['completion_label']=='全图实例中心机制对照' and len(global_center['arms'])==3 and '同全图512/crop768' in global_center['protocol'])
    check('spacecast_run_projected', len(run['arms']) == 4 and run['planned'] == 32)
    recovery = next((e for e in data['experiments'] if e['name'] == 'bailian_qwen38_flash_spacecast_state_screen_v3_recovery_v1'), None)
    if recovery:
        check('recovery_attempts_and_retry_count_projected', recovery['requests']['attempts'] >= 1 and recovery['requests']['retries'] >= 1)
        check('historical_failed_run_retained', run['status'] == 'held_execution_failure')
        for recovered in [e for e in data['experiments'] if e['name'].startswith('bailian_qwen38_flash_spacecast_state_screen_v3_recovery_')]:
            check('recovery_source_accessible_' + recovered['name'], request('/api/progress/source?' + urllib.parse.urlencode({'key': recovered['source_key']}))[0] == 200)
    if run['summary']:
        code, source = request('/api/progress/source?' + urllib.parse.urlencode({'key': run['source_key']}))
        check('spacecast_summary_accessible', code == 200 and json.loads(json.loads(source)['content'])['run_id'] == run['name'])
    errors = []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/#/progress')
        expect(page.locator('.progress-project')).to_have_count(8)
        check('project_axes_rendered', True)
        expect(page.locator('.brief-section')).to_have_count(40)
        page.get_by_label('项目', exact=True).select_option('attnOPD')
        expect(page.locator('.progress-project')).to_have_count(1)
        expect(page.locator('.progress-project')).to_contain_text(next(p for p in data['projects'] if p['id']=='attnOPD')['brief']['current'])
        expect(page.locator('.brief-section[open] table').first).to_be_visible()
        check('latest_report_content_and_tables_in_project_card', True)
        page.goto(BASE + '/#/race')
        expect(page.locator('.race-branch')).to_have_count(5)
        expect(page.locator('.race-summary')).to_contain_text('未曝光')
        expect(page.locator('.race-summary')).to_contain_text(data['portfolio']['execution_policy'])
        check('race_stages_branches_and_data_rules_rendered', True)
        page.goto(BASE + '/#/progress')
        page.get_by_label('项目', exact=True).select_option('OC-SOD')
        expect(page.locator('.progress-experiments article')).to_have_count(len([e for e in data['experiments'] if e['project'] == 'OC-SOD']))
        check('experiment_filter', True)
        if recovery:
            page.get_by_label('项目', exact=True).select_option('FastResearch')
            expect(page.locator('.progress-experiments')).to_contain_text(recovery['name'])
            expect(page.locator('.progress-experiments')).to_contain_text('自动重试')
            check('retry_count_rendered', True)
        page.goto(BASE + '/#/experience')
        page.get_by_label('页面搜索', exact=True).fill('LoRA')
        expect(page.locator('.grid-two article')).to_have_count(len([e for e in data['experiences'] if 'lora' in json.dumps(e, ensure_ascii=False).lower()]))
        page.locator('.grid-two article').first.locator('[data-progress-source]').first.click()
        expect(page.locator('#detail-dialog')).to_be_visible()
        expect(page.locator('#detail-dialog')).to_contain_text('3.811')
        check('evidence_dialog', True)
        page.locator('#detail-dialog button').first.click()
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE + '/#/progress')
        expect(page.locator('.progress-project')).to_have_count(8)
        check('mobile_no_page_overflow', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        page.get_by_label('项目', exact=True).select_option('FastResearch')
        expect(page.locator('.brief-section[open] table').first).to_be_visible()
        check('mobile_expanded_tables_no_page_overflow', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        page.goto(BASE + '/#/race')
        expect(page.locator('.race-branch')).to_have_count(5)
        check('mobile_race_no_page_overflow', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        page.screenshot(path=str(ROOT / 'reports/progress_mobile_20261010.png'))
        check('browser_no_page_errors', not errors)
        browser.close()
    report = {'date': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'pages': ['/#/progress', '/#/experience', '/#/race'],
              'checks': checks, 'projects': len(data['projects']), 'experiments': len(data['experiments']),
              'experiences': len(data['experiences']), 'passed': True,
              'existing_checks': {key: {'report': str(path), 'verified_on': metadata.get('verified_on', metadata.get('date')), 'passed_checks': metadata.get('passed_checks', len(metadata.get('checks', [])))}
                                  for key in ['web','product','standalone']
                                  for path in [ROOT / ('reports/fastresearch_'+key+'_validation_20261010.json')]
                                  for metadata in [json.loads(path.read_text()) if path.is_file() else {}]}}
    (ROOT / 'reports/fastresearch_progress_validation_20261010.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Validate the branch portfolio and its source-bound promotion evidence.

Read-only: never launches inference, alters a frozen protocol or opens labels.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'outputs/projects/fastresearch-cvpr2027/research'
STAGES = {'source_review': 0, 'mechanism_design': 0, 'baseline_screen': 0,
          'development': 1, 'independent': 2, 'confirmation': 4}


def assess(portfolio):
    assert portfolio['owner_project'] == 'fastresearch-cvpr2027'
    assert portfolio['budget']['project_cap_cny'] == 300
    branches = portfolio['branches']
    assert len({b['id'] for b in branches}) == len(branches)
    active = [b for b in branches if b['stage'] not in {'stopped', 'saturated', 'archived'}]
    assert len(active) <= 3
    gates = [g['id'] for g in portfolio['gates']]
    allocations = portfolio.get('screen_allocations', [])
    assert len({a['run_id'] for a in allocations}) == len(allocations)
    for allocation in allocations:
        assert allocation['branch'] in {b['id'] for b in branches}
        assert 0 < allocation['expected_settled_cny'] <= allocation['phase_cap_cny'] <= 300
        assert allocation['new_logical_calls_max'] > 0 and allocation['additional_authorization'] is False
        assert allocation.get('reason') and allocation.get('frozen_at')
        path = (STUDY / allocation['protocol_path']).resolve()
        assert STUDY.resolve() in path.parents and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == allocation['protocol_sha256']
        contract = json.loads(path.read_text())
        assert contract['maximum_new_logical_calls'] == allocation['new_logical_calls_max']
        assert contract['phase_cap_cny'] == allocation['phase_cap_cny']
        assert contract['expected_settled_cny'] == allocation['expected_settled_cny']
        assert contract['project_cap_cny'] == 300 and contract['workers'] == 1
    lessons = json.loads((ROOT.parent/'report/EXPERIENCE_POOL.json').read_text())['entries']
    lesson_ids = {r['id'] for r in lessons}
    outcomes = []
    for b in branches:
        assert set(b['lesson_ids']) <= lesson_ids
        assert all(b.get(k) for k in ['benchmark', 'model', 'headroom', 'evidence_summary', 'next_action', 'promotion_rule', 'compute_state', 'budget_note'])
        passed = b['passed_gates']
        assert passed == gates[:len(passed)]
        proof = {}
        for evidence in b['evidence']:
            path = (STUDY/evidence['path']).resolve()
            assert STUDY.resolve() in path.parents
            assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == evidence['sha256']
            assert evidence['gate'] in gates
            proof.setdefault(evidence['gate'], []).append(path)
        for gate in passed:
            assert proof.get(gate), f"{b['id']}: no immutable evidence for {gate}"
        if b['stage'] in STAGES:
            assert len(passed) >= STAGES[b['stage']], f"{b['id']}: stage exceeds evidence"
        for path in proof.get('screen', []):
            summary = json.loads(path.read_text())
            assert summary.get('expansion_gate_passed') is True, 'A failed screen cannot promote'
            assert summary.get('confirmation_evaluated') is False
        outcomes.append({'id': b['id'], 'stage': b['stage'], 'passed_gates': passed,
                         'next_required_gate': gates[len(passed)] if len(passed) < len(gates) else None,
                         'promotion_automatic': False})
    ledger = json.loads((STUDY/'API_LEDGER.json').read_text())
    return {'valid': True, 'active_candidates': len(active), 'branches': outcomes,
            'explicit_screen_allocations': len(allocations),
            'conservative_total_cny': ledger['conservative_total_cny'],
            'remaining_under_hard_cap_cny': max(0, 300-ledger['conservative_total_cny']),
            'limits': 'Portfolio validation is not a scientific pass or an experiment scheduler.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['validate', 'assess'])
    parser.parse_args()
    print(json.dumps(assess(json.loads((STUDY/'PORTFOLIO.json').read_text())), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

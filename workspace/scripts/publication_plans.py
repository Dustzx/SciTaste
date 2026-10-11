"""Join authored race routes to venue and native delivery facts, without writes."""
from copy import deepcopy


def project_routes(portfolio, catalogue, native, iterations):
    """No schedule, historical milestone or method proposal grants a science gate."""
    venues = {v['id']: v for v in catalogue.get('venues', [])}
    delivery = native.get('submission_plan') or {}
    work = {w['work_id']: w for w in delivery.get('work_items', [])}
    schedule = native.get('venue_schedule') or {}
    gates = portfolio.get('gates', [])

    def target(ref):
        venue = venues.get(ref.get('venue_id'))
        if not venue or venue.get('rank') not in {'A', 'B'}:
            raise ValueError('Publication route must reference a CCF A/B catalogue venue')
        year = ref.get('year')
        edition = next((e for e in venue.get('editions', []) if e['year'] == year), {})
        dates = [r['deadline']['utc'] for r in edition.get('rounds', [])
                 if r.get('deadline', {}).get('utc')]
        deadline = min(dates) if dates else None
        result = {k: venue.get(k) for k in ['abbreviation', 'name', 'rank', 'kind']}
        result.update(venue_id=venue['id'], year=year, fit=ref.get('fit'),
                      url=edition.get('url') or ref.get('official_url') or venue.get('directory_url'),
                      deadline_at=deadline, deadline_status='catalogue' if deadline else 'unpublished',
                      source_url=venue.get('source_url'))
        # Official native schedule takes precedence for the same venue and year.
        # Deliberately do not apply CVPR dates to unrelated venues or editions.
        if venue['id'] == 'conference-AI-cvpr' and year == 2027 and schedule.get('venue_id') == 'cvpr2027':
            milestones = schedule.get('milestones', [])
            paper = next((m for m in milestones if m['kind'] == 'paper-submission'), None)
            if paper:
                result.update(deadline_at=paper['deadline_at'], deadline_status='official',
                              official_milestones=deepcopy(milestones),
                              official_sources=deepcopy(schedule.get('sources', [])))
        return result

    for branch in portfolio.get('branches', []):
        authored = branch.get('publication_plan')
        if not authored:
            continue
        route = deepcopy(authored)
        paused = branch['stage'] in {'stopped', 'saturated', 'archived'}
        passed = set(branch.get('passed_gates', []))
        all_gates = bool(gates) and all(g['id'] in passed for g in gates)
        route['status'] = ('paused' if paused else 'ready' if all_gates and
                           native.get('publication_ready') and delivery.get('publication_ready') else 'candidate')
        route['primary'] = target(route['primary'])
        route['alternatives'] = [target(t) for t in route.get('alternatives', [])]
        for point in route.get('checkpoints', []):
            gate = point.get('gate_id')
            point['state'] = ('paused' if paused else 'passed' if gate in passed else
                              'active' if gate == next((g['id'] for g in gates if g['id'] not in passed), None)
                              else 'planned')
            native_item = work.get(point.get('native_work_id'))
            if native_item:
                point['native_reference'] = {
                    'work_id': native_item['work_id'], 'state': native_item['state'],
                    'due_at': native_item.get('due_at'),
                    'note': '共享项目历史交付记录；不代替本分支科学门或新的基线准入。'}
        route['delivery_url'] = '#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=plan'
        route['delivery_reference'] = {
            'project_id': native.get('project_id'), 'project_revision': native.get('revision'),
            'plan_id': delivery.get('plan_id'), 'plan_revision': delivery.get('plan_revision'),
            'publication_ready': native.get('publication_ready', False),
            'internal_deadline_at': delivery.get('internal_deadline_at'),
            'deadline_note': delivery.get('deadline_note'),
            'source_key': 'FastResearch.project'}
        item = iterations.get(branch['id'])
        if item:
            route['method_iteration'] = {'available': True, 'summary': item.get('summary') or item.get('decision') or route.get('method_summary'),
                                         'source_key': route.get('method_source_key'),
                                         'status': item.get('status')}
        else:
            route.pop('method_iteration', None)
        branch['publication_plan'] = route
    return portfolio

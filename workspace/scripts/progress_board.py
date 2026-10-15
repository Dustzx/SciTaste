"""Read-only projections of explicitly configured local reports; no research implementation."""
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from local_research import SHARED_RACE

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT.parent / 'report' if (ROOT.parent / 'report').is_dir() else ROOT / 'report'
REPORT = Path(os.environ.get('SCITASTE_REPORT_ROOT', str(DEFAULT_REPORT))).resolve()


def read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default

def stamp(path):
    if not path.is_file():
        return {'available': False}
    return {'available': True, 'modified_at': datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo('Asia/Shanghai')).isoformat(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def project_brief(path):
    """Project authored narrative verbatim; never infer experiment completion."""
    if not path.is_file():
        return {'available': False, 'sections': []}
    content = path.read_text()
    headings = list(re.finditer(r'^##\s+(.+)$', content, re.MULTILINE))
    sections = []
    for i, heading in enumerate(headings):
        body = content[heading.end():headings[i+1].start() if i+1 < len(headings) else len(content)].strip()
        sections.append({'title': heading[1], 'markdown': body,
                         'tables': len(re.findall(r'^\|\s*[-:]+', body, re.MULTILINE))})
    intro = content[:headings[0].start()] if headings else content
    def statement(label):
        match = re.search(r'\*\*' + label + r'[^*]*\*\*\s*(.+)', intro)
        return match[1].strip() if match else None
    next_section = next((s for s in sections if re.match(r'5[.、\s]', s['title'])), {})
    next_text = next_section.get('markdown', '').split('\n\n')[0]
    return {'path': str(path), **stamp(path), 'intro': intro.strip(),
            'current': statement('当前做到'), 'claim': statement('顶会级创新主张'),
            'next_summary': next_text, 'sections': sections,
            'table_count': sum(s['tables'] for s in sections)}

def report_experiments(path, project):
    if not path.is_file():
        return []
    text = path.read_text()
    section = re.search(r'## 4[.、\s].*?(?=\n## 5|\Z)', text, re.DOTALL)
    if not section:
        return []
    rows = []
    for line in section.group().splitlines():
        if not line.startswith('|') or re.match(r'^\|\s*[-:]', line):
            continue
        cells = [s.strip() for s in line.strip('|').split('|')]
        if len(cells) == 3 and not any(s in cells[0] for s in ['实验问题', '工作/实验']):
            rows.append({'project': project, 'name': cells[0], 'protocol': cells[1], 'finding': cells[2],
                         'verification': 'report_snapshot', 'status': '简报快照', 'source_key': project+'.report'})
    return rows

def browser_source_path(path):
    """Whether an explicitly indexed file can be exposed as a text attachment."""
    resolved = path.resolve()
    roots = [ROOT.resolve(), REPORT.resolve()]
    if not any(root in resolved.parents for root in roots) or resolved.suffix not in {'.md', '.json', '.tex'}:
        return None
    if not resolved.is_file() or resolved.stat().st_size > 2*1024*1024:
        return None
    # Only explicitly indexed narrative/summary sources, never raw calls, credentials or arbitrary paths.
    if resolved.name in {'API_LEDGER.json', 'calls.jsonl', 'API_AUTHORIZATION.json'}:
        return None
    return resolved


def sources():
    found = {}
    index = read(REPORT / 'sources.json', {'projects': {}})
    for project, data in index.get('projects', {}).items():
        for role, source in data.get('sources', {}).items():
            found[project + '.' + role] = Path(source['path'])
    board = read(REPORT / 'STATUS_BOARD.json', {'projects': []})
    for project in board.get('projects', []):
        path = (REPORT / project['report']).resolve()
        if REPORT in path.parents and path.suffix == '.md':
            found[project['id'] + '.report'] = path
    for entry in read(REPORT / 'EXPERIENCE_POOL.json', {'entries': []}).get('entries', []):
        for i, evidence in enumerate(entry.get('evidence', [])):
            found['experience.' + entry['id'] + '.' + str(i)] = Path(evidence['path'])
    return found


def source_document(key):
    path = sources().get(key)
    if path is None:
        return None
    resolved = browser_source_path(path)
    return None if resolved is None else {
        'source_key': key, 'path': str(path), 'content': resolved.read_text(), **stamp(resolved)}


def snapshot():
    board = read(REPORT / 'STATUS_BOARD.json', {'projects': [], 'axes': []})
    index = read(REPORT / 'sources.json', {'projects': {}})
    pool = read(REPORT / 'EXPERIENCE_POOL.json', {'entries': []})
    projects, experiments = [], []
    for row in board.get('projects', []):
        project = dict(row)
        path = (REPORT / project['report']).resolve()
        if REPORT not in path.parents or path.suffix != '.md':
            raise ValueError('Report narrative must stay within the configured report root')
        project['brief'] = project_brief(path)
        project['sources'] = []
        for role, ref in index.get('projects', {}).get(project['id'], {}).get('sources', {}).items():
            source = Path(ref['path'])
            metadata = stamp(source)
            project['sources'].append({
                'role': role, 'key': project['id'] + '.' + role, 'path': str(source),
                'browser_readable': browser_source_path(source) is not None,
                'changed_since_report': metadata.get('sha256') != ref.get('sha256'), **metadata})
        project['report_changed'] = any(source['changed_since_report'] for source in project['sources'])
        projects.append(project)
        experiments.extend(report_experiments(path, project['id']))
    return {
        'schema_version': 2, 'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'axes': board.get('axes', []), 'projects': projects, 'experiments': experiments,
        'experiences': pool.get('entries', []),
        'document_links': {str(path): key for key, path in sources().items() if browser_source_path(path)},
        'portfolio': read(REPORT / 'PORTFOLIO.json', {'branches': [], 'gates': []}),
        'route_candidate': None, 'zoombench_candidate': None, 'diagram_candidate': None,
        'budget': read(REPORT / 'BUDGET.json', {}), 'maintenance': board.get('maintenance'),
        'shared_race': read(SHARED_RACE, {}),
        'verification_policy': '本页只读已配置的本地记录；进展是来源快照，刷新不查询远端或启动研究。'}

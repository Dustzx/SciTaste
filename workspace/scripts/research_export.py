"""Export explicitly configured reviewed narrative; no benchmark assets or calls."""
import io
import json
import re
import zipfile

import research_dossiers

MAX_EXPORT_BYTES = 4 * 1024 * 1024


def build(project='all', format='markdown'):
    if format not in {'markdown', 'zip'}:
        raise ValueError('Only markdown or zip export is supported')
    profiles = research_dossiers.snapshot()['projects']
    profiles = [p for p in profiles if project == 'all' or p['report_id'] == project]
    if not profiles:
        raise ValueError('No configured reviewed project is available')
    members = {}
    for profile in profiles:
        pid = profile['project_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
            raise ValueError('Unsafe reviewed project identity')
        brief = profile.get('brief') or {}
        lines = ['# ' + str(profile.get('title') or pid), '',
                 'Scope: reviewed local narrative; not a new experiment '
                 'or independent verification.', '',
                 brief.get('intro') or 'No reviewed introduction configured.']
        for section in brief.get('sections', []):
            lines.extend(['', '## ' + section['title'], '', section['markdown']])
        members[pid + '/BRIEF.md'] = ('\n'.join(lines) + '\n').encode()
        # Only presentation fields; source locators, raw calls and target files are excluded.
        safe = {key: profile[key] for key in ('schema_version', 'project_id', 'report_id',
            'title', 'summary', 'current', 'claim', 'gap', 'next', 'reviewed_at') if key in profile}
        members[pid + '/PROJECT.json'] = json.dumps(safe, ensure_ascii=False, indent=2).encode()
    if sum(map(len, members.values())) > MAX_EXPORT_BYTES:
        raise ValueError('Reviewed narrative exceeds bounded export size')
    if format == 'markdown':
        body = b'\n\n---\n\n'.join(v for k, v in members.items() if k.endswith('.md'))
        return body, 'text/markdown; charset=utf-8', 'SciTaste-reviewed-projects.md'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return stream.getvalue(), 'application/zip', 'SciTaste-reviewed-projects.zip'

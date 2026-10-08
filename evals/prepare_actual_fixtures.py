"""Prepare new Git inputs only. Outputs/review judgments are authored by the evaluating agent.
Usage: python -X utf8 evals/prepare_actual_fixtures.py
Existing run directories are refused. No database or model is invoked.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / '.superpowers/sdd/2026-10-08-release-docs-plugin/actual-run'
ARCHIVE = ROOT / 'evals/actual'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.STDOUT).decode('utf-8').strip()


def write(repo, name, value):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def masked(value):
    # Known synthetic fixture values only; no claim of general secret detection.
    if 'ConnectionStrings' in value:
        data = json.loads(value)
        data['ConnectionStrings'] = {key: '[已遮罩]' for key in data['ConnectionStrings']}
        value = json.dumps(data, ensure_ascii=False)
    for secret in ['fixture-new-secret', 'fixture-secret']:
        value = value.replace(secret, '[已遮罩]')
    return value


def main():
    if RUN.exists():
        raise SystemExit('Run already exists; preserve evidence and choose a new run directory')
    scenarios = json.loads((ROOT / 'evals/scenarios.json').read_text(encoding='utf-8'))['scenarios']
    for case in scenarios:
        repo = RUN / ('中文 空白 ' + case['id'])
        repo.mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'config', 'user.email', 'fixture@example.invalid')
        git(repo, 'config', 'user.name', 'Actual evaluation fixture')
        write(repo, 'AGENTS.md', 'Read every changed source. Do not execute deployment SQL. Synthetic evaluation only.\n')
        for name, value in case['sources'].items():
            if name.startswith('base:'):
                write(repo, name[5:], value)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'base')
        base = git(repo, 'rev-parse', 'HEAD')
        pseudo = {'branch', 'constraint', 'defects', 'existing:04_上線指引.md', 'old-report', 'change', '04_上線指引.md'}
        for name, value in case['sources'].items():
            if name.startswith('target:'):
                write(repo, name[7:], value)
            elif ':' not in name and name not in pseudo and isinstance(value, str):
                write(repo, name, value)
        if case['id'] in {'required-review', 'review-stale-report', 'blank-signoff-placeholder', 'path-and-signoff'}:
            write(repo, 'docs/migration.sql', 'CREATE TABLE dbo.EvalMarker (Id int NOT NULL PRIMARY KEY);\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '--allow-empty', '-qm', 'target')
        target = git(repo, 'rev-parse', 'HEAD')
        if case['id'] == 'no-changes':
            base = target
        if case['id'] == 'uncommitted':
            write(repo, 'schema.sql', 'CREATE TABLE dbo.LaterHead (Id int);')
            git(repo, 'commit', '-qam', 'later head, excluded')
            write(repo, 'schema.sql', case['sources']['index:schema.sql'])
            git(repo, 'add', 'schema.sql')
            write(repo, 'schema.sql', case['sources']['working-tree:schema.sql'])
            write(repo, 'new.sql', case['sources']['untracked:new.sql'])
        nested = repo / 'nested/deeper'
        nested.mkdir(parents=True)
        archive = ARCHIVE / case['id']
        archive.mkdir(parents=True)
        evidence = subprocess.check_output([
            'git', '-C', str(nested), 'rev-parse', '--show-toplevel']).decode('utf-8').strip()
        invocation = {'executor': 'Task4 agent manually applying read skills, new Git run; not an automated LLM invocation',
                      'entry_skill': 'skills/release-docs/SKILL.md', 'review_skill': 'skills/release-docs-review/SKILL.md',
                      'repo': str(repo), 'cwd': str(nested), 'discovered_root': evidence,
                      'base': None if case['id'] == 'unknown-base' else base,
                      'target': None if case['id'] == 'unknown-base' else target,
                      'fixture_base': base, 'fixture_target': target, 'diff_mode': 'direct',
                      'identifier': '../#42\\正式' if case['id'] == 'path-and-signoff' else case['id'],
                      'date_timezone': '2026-10-08 Asia/Taipei',
                      'working_tree_inclusion': 'unspecified' if case['id'] == 'uncommitted' else 'excluded',
                      'request': case['request'], 'criteria': case['criteria'], 'sql_executed': False}
        (archive / 'invocation.json').write_text(json.dumps(invocation, ensure_ascii=False, indent=2), encoding='utf-8')
        # Full safe source export at each revision; original bytes remain in the retained Git fixture.
        inventory = []
        for label, sha in [('base', base), ('target', target)]:
            paths = git(repo, 'ls-tree', '-r', '--name-only', sha).splitlines()
            for path in paths:
                raw = subprocess.check_output(['git', '-C', str(repo), 'show', sha + ':' + path])
                dest = archive / 'sources' / label / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(masked(raw.decode('utf-8')), encoding='utf-8')
                inventory.append({'revision': sha, 'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'export_redacted': masked(raw.decode('utf-8')) != raw.decode('utf-8')})
        (archive / 'source-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Prepared {len(scenarios)} independent Git fixtures. No documents generated.')


if __name__ == '__main__':
    main()

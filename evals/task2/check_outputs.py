"""Fixture/contract checks only: no LLM invocation, SQL parsing or SQL execution."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAMES = ['01_結構SQL.md', '02_資料SQL.md', '03_appsettings異動.md', '04_上線指引.md']


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
               GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_EMAIL='fixture@example.invalid',
               GIT_AUTHOR_DATE='2026-10-08T12:00:00+08:00', GIT_COMMITTER_DATE='2026-10-08T12:00:00+08:00')
    return subprocess.run(['git', '-C', str(repo), *args], env=env, check=True,
                          capture_output=True).stdout.decode('utf-8').strip()


def main():
    # Temporary Git fixture is local to this project and removed by its context manager.
    with tempfile.TemporaryDirectory(prefix='.task2-fixture-', dir=ROOT) as folder:
        repo = Path(folder)
        git(repo, 'init', '-q')
        git(repo, 'config', 'core.autocrlf', 'false')
        for name in ['Program.cs', 'deployment.yaml', 'README.md']:
            (repo / name).write_text((HERE / 'sources' / name).read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
        (repo / 'appsettings.json').write_text((HERE / 'sources/appsettings.base.json').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'base')
        base = git(repo, 'rev-parse', 'HEAD')
        (repo / 'appsettings.json').write_text((HERE / 'sources/appsettings.target.json').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
        (repo / 'mixed.sql').write_text((HERE / 'sources/mixed.sql').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'target')
        target = git(repo, 'rev-parse', 'HEAD')
        import sys
        metadata = json.loads(subprocess.run([
            sys.executable, str(ROOT / 'skills/release-docs/scripts/collect_release_evidence.py'),
            '--repo', folder, '--base', base, '--target', target, '--diff-mode', 'direct'
        ], check=True, capture_output=True).stdout)
        assert {x['path'] for x in metadata['committed_changes']} == {'appsettings.json', 'mixed.sql'}
        assert all(not x for x in metadata['working_tree_changes'].values())
        assert 'fixture-secret' not in json.dumps(metadata)
        print('PASS real Git fixture: appsettings.json modified; mixed.sql added; workspace clean; metadata has no secret values')

    outputs = {}
    for name in NAMES:
        path = HERE / 'outputs' / name
        contents = path.read_text(encoding='utf-8')
        # Initial materialization fills only authentic SHA headers. Prose is manually authored.
        if '{{BASE_SHA}}' in contents or '{{TARGET_SHA}}' in contents:
            contents = contents.replace('{{BASE_SHA}}', base).replace('{{TARGET_SHA}}', target)
            path.write_text(contents, encoding='utf-8', newline='\n')
        assert base in contents and target in contents, name
        assert '{{' not in contents, name
        for field in ['產出日期／時區', '識別', 'base SHA', 'target SHA', 'diff 模式', '工作區範圍', '來源證據']:
            assert field in contents, (name, field)
        outputs[name] = contents
    combined = '\n'.join(outputs.values())
    for value in ['fixture-secret', 'fixture-new-secret', 'User Id=demo', 'User Id=svc']:
        assert value not in combined
    rows = [line for line in outputs[NAMES[3]].splitlines() if re.match(r'\| \d+ \| SQL-001 \|', line)]
    assert len(rows) == 1
    assert 'SQL-001' in outputs[NAMES[0]] and 'SQL-001' in outputs[NAMES[1]]
    settings = outputs[NAMES[2]]
    for key in ['Feature:Old', 'Feature:Enabled', 'Feature:Timeout', 'Endpoints:0:Url', 'ConnectionStrings:Db']:
        assert key in settings
    assert '[已遮罩]' in settings
    assert '待確認' in outputs[NAMES[3]] and '未執行' in outputs[NAMES[3]]
    print('PASS four authored outputs: common authentic SHA/scope fields; mixed execution row once; complete config keys; known sensitive values absent; unresolved status retained')

    skill = ROOT / 'skills/release-docs/SKILL.md'
    text = skill.read_text(encoding='utf-8')
    assert text.startswith('---\nname: release-docs\ndescription: Use when ')
    assert text.split('---', 2)[1].count('name:') == 1
    for target_link in re.findall(r'\]\(([^)]+)\)', text):
        assert (skill.parent / target_link).resolve().is_file(), target_link
    print('PASS stdlib skill contract: name/description frontmatter and all supporting relative links resolve')
    print('LIMIT: assertions check fixture artifacts/contracts only; human semantic results are separate; no SQL/LLM/install executed; no independent review report generated')
    print('fixture base SHA=' + base)
    print('fixture target SHA=' + target)


if __name__ == '__main__':
    main()

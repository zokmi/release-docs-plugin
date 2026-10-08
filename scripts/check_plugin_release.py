"""Read-only release gates; never create tags or publish releases."""
import argparse
import json
from pathlib import Path
import re
import subprocess

MANIFESTS = ['plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json']
RESOURCES = [
    'skills/release-docs/SKILL.md', 'skills/release-docs-review/SKILL.md',
    'assets/01_結構SQL.md', 'assets/02_資料SQL.md', 'assets/03_appsettings異動.md',
    'assets/04_上線指引.md', 'assets/05_版更審查報告.md',
    'references/sql-review-rules.md', 'references/config-rules.md',
    'skills/release-docs/scripts/collect_release_evidence.py',
    'skills/release-docs/scripts/review_fingerprint.py',
    '.claude-plugin/marketplace.json', '.agents/plugins/marketplace.json', 'LICENSE', 'README.md',
]


def validate_tag(tag):
    if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag):
        raise ValueError('Tag must be strict vMAJOR.MINOR.PATCH without leading zeroes')
    return tag[1:]


def check_package(root, tag):
    version = validate_tag(tag)
    for name in MANIFESTS:
        path = root / name
        if not path.is_file():
            raise ValueError(f'Missing manifest: {name}')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('name') != 'release-docs' or data.get('version') != version:
            raise ValueError(f'Plugin name/version mismatch: {name}')
    for name in RESOURCES:
        if not (root / name).is_file() or (root / name).stat().st_size == 0:
            raise ValueError(f'Missing or empty resource: {name}')


def check_git(root, tag):
    validate_tag(tag)
    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f'Git gate failed: {result.stderr.strip()}')
        return result.stdout.strip()
    sha = git('rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}')
    # Check membership first so side-branch tags have a useful diagnostic.
    git('rev-parse', '--verify', 'refs/remotes/origin/main^{commit}')
    result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', sha, 'refs/remotes/origin/main'], capture_output=True)
    if result.returncode:
        raise ValueError('Tag commit is not reachable from origin/main')
    if git('rev-parse', 'HEAD') != sha:
        raise ValueError('Tag commit differs from checkout HEAD')
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--tag-only', action='store_true')
    args = parser.parse_args()
    try:
        version = validate_tag(args.tag)
        if not args.tag_only:
            check_package(args.repo, args.tag)
            check_git(args.repo, args.tag)
        print(json.dumps({'tag': args.tag, 'version': version, 'validated': True}))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()

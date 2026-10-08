"""Collect path/revision metadata only; never emit file contents."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    if result.returncode:
        # Git diagnostics may include caller-controlled text, but no file contents.
        raise ValueError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout


def revision(repo, value):
    try:
        return git(repo, 'rev-parse', '--verify', '--end-of-options', value + '^{commit}').decode('ascii').strip()
    except ValueError as exc:
        raise ValueError('Unable to resolve requested revision: ' + str(exc)) from exc


def changes(repo, args, old_revision, new_revision):
    fields = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '-M', *args, '--').split(b'\0')
    items = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode('ascii')
        index += 1
        old_path = None
        if status[0] in 'RC':
            old_path = fields[index].decode('utf-8', errors='surrogateescape')
            index += 1
        path = fields[index].decode('utf-8', errors='surrogateescape')
        index += 1
        items.append({'status': status, 'old_path': old_path, 'path': path,
                      'source_revision': old_revision if status[0] == 'D' else new_revision})
    return items


def collect(repo, base, target, diff_mode):
    root = Path(git(repo, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve()
    base_sha = revision(root, base)
    target_sha = revision(root, target)
    if diff_mode == 'merge-base':
        bases = git(root, 'merge-base', '--all', base_sha, target_sha).decode('ascii').splitlines()
        if len(bases) != 1:
            raise ValueError('Expected one merge base; specify an unambiguous revision range')
        base_sha = bases[0]
    head = revision(root, 'HEAD')
    untracked = [{'status': '?', 'old_path': None, 'path': path.decode('utf-8', errors='surrogateescape'),
                  'source_revision': 'working-tree'}
                 for path in git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if path]
    return {'schema_version': 1, 'repo_root': str(root), 'base_sha': base_sha,
            'target_sha': target_sha, 'diff_mode': diff_mode,
            'committed_changes': changes(root, [base_sha, target_sha], base_sha, target_sha),
            'working_tree_changes': {
                'staged': changes(root, ['--cached', head], head, 'index'),
                'unstaged': changes(root, [], 'index', 'working-tree'),
                'untracked': untracked}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--diff-mode', choices=['direct', 'merge-base'], required=True)
    args = parser.parse_args()
    try:
        data = collect(args.repo, args.base, args.target, args.diff_mode)
    except (ValueError, OSError) as exc:
        print('Evidence collection failed: ' + str(exc), file=sys.stderr)
        return 1
    # ASCII transport is portable on Windows consoles; JSON retains Unicode paths.
    print(json.dumps(data, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

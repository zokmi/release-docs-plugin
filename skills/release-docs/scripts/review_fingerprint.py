"""Evidence identity only; never a semantic review or approval."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from validate_output_paths import DOCUMENTS, REPORT, validate_output_paths



def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(repo, documents, base=None, target=None, diff_mode=None, commit_scope=None):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], input=b'', stderr=subprocess.PIPE)

    if commit_scope is not None and any(v is not None for v in (base, target, diff_mode)):
        raise ValueError('Commit scope and range are mutually exclusive')
    repo, docs = validate_output_paths(repo, documents)
    excluded = []
    document_hashes = {}
    for name in (*DOCUMENTS, REPORT):
        path = docs / name
        if name in DOCUMENTS:
            document_hashes[name] = digest(path.read_bytes())
        excluded.append(path.relative_to(repo).as_posix())
    paths = ['--', '.', *[':(exclude,literal)' + p for p in excluded]]
    # Full trees bind referenced source content at the actual revisions, including
    # unchanged dependencies; no working-tree reads substitute for target bytes.
    def tree_hash(sha):
        entries = git('ls-tree', '-r', '-z', '--full-tree', sha).split(b'\0')
        return digest(b'\0'.join(entry for entry in entries if entry and entry.split(b'\t', 1)[1].decode('utf-8') not in excluded))

    def resolve(revision):
        if not isinstance(revision, str) or not revision or revision.startswith('-'):
            raise ValueError('Invalid revision')
        return git('rev-parse', '--verify', revision + '^{commit}').decode().strip()

    if commit_scope is not None:
        selected = json.loads(Path(commit_scope).read_text(encoding='utf-8'))
        if not isinstance(selected, list) or not selected:
            raise ValueError('Commit scope must be a nonempty ordered list')
        pairs, evidence = [], []
        for item in selected:
            if not isinstance(item, dict) or set(item) != {'commit', 'parent'}:
                raise ValueError('Each selected pair requires commit and parent')
            commit = resolve(item['commit'])
            parents = git('rev-list', '--parents', '-n', '1', commit).decode().strip().split()[1:]
            parent = None if item['parent'] is None else resolve(item['parent'])
            if (parents and parent not in parents) or (not parents and parent is not None):
                raise ValueError('Selected parent must be a direct parent; root requires null')
            pairs.append({'commit': commit, 'parent': parent})
            # Root comparisons use Git's object-format-specific empty tree.
            start = parent or git('hash-object', '-t', 'tree', '--stdin').decode().strip()
            status = git('diff', '--name-status', '-z', '--no-ext-diff', '--no-textconv', start, commit, *paths)
            changed = git('diff', '--name-only', '-z', '--no-ext-diff', '--no-textconv', start, commit, *paths)
            evidence.append({'parent_tree': tree_hash(parent) if parent else None,
                             'commit_tree': tree_hash(commit), 'status': digest(status),
                             'changed_paths': [p.decode('utf-8') for p in changed.split(b'\0') if p],
                             'diff': digest(git('diff', '--binary', '--no-ext-diff', '--no-textconv', start, commit, *paths))})
        identity = {'commit_scope': pairs}
        committed = {'pairs': evidence}
    else:
        if base is None or target is None or diff_mode not in ('two-dot', 'three-dot'):
            raise ValueError('Range requires base, target and diff mode')
        base_sha, target_sha = resolve(base), resolve(target)
        start = base_sha if diff_mode == 'two-dot' else git('merge-base', base_sha, target_sha).decode().strip()
        identity = {'base': base_sha, 'target': target_sha, 'diff_mode': diff_mode}
        committed = {'base': tree_hash(base_sha), 'target': tree_hash(target_sha),
                     'diff': digest(git('diff', '--binary', '--no-ext-diff', '--no-textconv', start, target_sha, *paths))}
    working_tree = {
        'staged': digest(git('diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv', *paths)),
        'unstaged': digest(git('diff', '--binary', '--no-ext-diff', '--no-textconv', *paths)),
        'untracked': {},
    }
    for raw in git('ls-files', '--others', '--exclude-standard', '-z', *paths).split(b'\0'):
        if not raw:
            continue
        name = raw.decode('utf-8')
        path = repo / name
        path.resolve().relative_to(repo)
        working_tree['untracked'][name] = digest(path.read_bytes())
    result = {'schema_version': 1, **identity, 'documents': document_hashes,
              'committed': committed, 'working_tree': working_tree}
    result['fingerprint'] = digest(json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('repo', 'documents'):
        parser.add_argument('--' + option, required=True)
    for option in ('base', 'target', 'commit-scope'):
        parser.add_argument('--' + option)
    parser.add_argument('--diff-mode', choices=('two-dot', 'three-dot'))
    args = parser.parse_args()
    try:
        result = snapshot(**vars(args))
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(2, 'Fingerprint unavailable: invalid Git scope, unsafe path, missing document, or unreadable evidence.\n')
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()

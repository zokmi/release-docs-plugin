"""Evidence identity only; never a semantic review or approval."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DOCUMENTS = ('01_結構SQL.md', '02_資料SQL.md', '03_appsettings異動.md', '04_上線指引.md')
REPORT = '05_版更審查報告.md'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(repo, documents, base, target, diff_mode):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)

    repo = Path(git('rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve()
    docs = Path(documents).resolve(strict=True)
    docs.relative_to(repo / 'docs')
    excluded = []
    document_hashes = {}
    for name in (*DOCUMENTS, REPORT):
        path = docs / name
        if path.is_symlink():
            raise ValueError('Named output must not be a symlink')
        path.resolve().relative_to(repo)
        if name in DOCUMENTS:
            document_hashes[name] = digest(path.read_bytes())
        excluded.append(path.relative_to(repo).as_posix())
    paths = ['--', '.', *[':(exclude,literal)' + p for p in excluded]]
    base_sha = git('rev-parse', '--verify', base + '^{commit}').decode().strip()
    target_sha = git('rev-parse', '--verify', target + '^{commit}').decode().strip()
    start = base_sha
    if diff_mode == 'three-dot':
        start = git('merge-base', base_sha, target_sha).decode().strip()
    # Full trees bind referenced source content at the actual revisions, including
    # unchanged dependencies; no working-tree reads substitute for target bytes.
    committed = {}
    for label, sha in (('base', base_sha), ('target', target_sha)):
        entries = git('ls-tree', '-r', '-z', '--full-tree', sha).split(b'\0')
        committed[label] = digest(b'\0'.join(entry for entry in entries if entry and entry.split(b'\t', 1)[1].decode('utf-8') not in excluded))
    committed['diff'] = digest(git('diff', '--binary', '--no-ext-diff', '--no-textconv', start, target_sha, *paths))
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
    result = {'schema_version': 1, 'base': base_sha, 'target': target_sha,
              'diff_mode': diff_mode, 'documents': document_hashes,
              'committed': committed, 'working_tree': working_tree}
    result['fingerprint'] = digest(json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('repo', 'documents', 'base', 'target'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--diff-mode', choices=('two-dot', 'three-dot'), required=True)
    args = parser.parse_args()
    try:
        result = snapshot(**vars(args))
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(2, 'Fingerprint unavailable: invalid Git scope, unsafe path, missing document, or unreadable evidence.\n')
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()

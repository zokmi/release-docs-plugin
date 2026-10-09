"""Read-only preflight for release-document destinations."""
import argparse
import json
import stat
import subprocess
from pathlib import Path

REQUIRED_DOCUMENTS = ('00_上線指引.md', '01_結構SQL.sql')
OPTIONAL_DOCUMENTS = ('01_索引調整.sql', '02_資料SQL.sql', '03_例外排除.json', '04_參數異動.md')
DOCUMENTS = REQUIRED_DOCUMENTS + OPTIONAL_DOCUMENTS
REPORT = '05_版更審查報告.md'
ALLOWED_DOCUMENTS = frozenset((*DOCUMENTS, REPORT))


def validate_output_paths(repo, documents):
    root = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--show-toplevel'],
                                   stderr=subprocess.PIPE).decode('utf-8').strip()
    repo = Path(root).resolve(strict=True)
    docs_root = repo / 'docs'
    docs_root.resolve().relative_to(repo)
    docs = Path(documents).resolve()
    docs.relative_to(docs_root)
    # Missing directories are allowed, but every existing ancestor must be a directory.
    for directory in (docs_root, docs, *docs.parents):
        if directory.exists() and not directory.is_dir():
            raise ValueError('Output directory must be a directory')
    for name in (*REQUIRED_DOCUMENTS, *OPTIONAL_DOCUMENTS, REPORT):
        path = docs / name
        if path.is_symlink():
            raise ValueError('Named output must not be a symlink')
        path.resolve().relative_to(docs)
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ValueError('Named output must be a regular file with no hard-link aliases')
    if docs.exists():
        for entry in docs.iterdir():
            if entry.name not in ALLOWED_DOCUMENTS:
                raise ValueError('Unexpected release output: ' + entry.name)
    return repo, docs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--documents', required=True)
    args = parser.parse_args()
    try:
        repo, docs = validate_output_paths(args.repo, args.documents)
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(2, 'Output preflight refused: unsafe directory or named destination; no files written.\n')
    print(json.dumps({'repo_root': str(repo), 'documents': str(docs), 'safe': True}, ensure_ascii=True))


if __name__ == '__main__':
    main()

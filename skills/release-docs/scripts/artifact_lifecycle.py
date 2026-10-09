"""Manage ignored, owned release evidence. Never approves SQL or deploys it."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import uuid

from validate_output_paths import DOCUMENTS, REPORT, REQUIRED_DOCUMENTS, validate_output_paths
from validate_release_artifacts import validate

ROOT = '.release-docs'
LEGACY = 'docs/release-artifacts'
MANIFEST = 'run.json'
LOCK = '.lock'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def root_path(repo):
    return Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve(strict=True)


def safe_tree(path):
    """Reject all aliases before writing or recursively deleting an owned tree."""
    if not path.exists() and not path.is_symlink():
        return
    info = path.lstat()
    if (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Aliases/reparse points are not allowed')
    if stat.S_ISDIR(info.st_mode):
        for entry in path.iterdir():
            safe_tree(entry)
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        raise ValueError('Only regular, unaliased files are allowed')


def check_ignore(repo):
    if git(repo, 'ls-files', '-z', '--', ROOT, LEGACY):
        raise ValueError('Runtime or legacy artifacts are tracked/staged; resolve explicitly first')
    # Check representative child paths, not only directory names.
    for name in (ROOT + '/runs/probe/run.json', LEGACY + '/probe/artifact.json'):
        result = subprocess.run(['git', '-C', str(repo), 'check-ignore', '-q', '--', name])
        if result.returncode != 0:
            raise ValueError('Required Git ignore missing: ' + name)
    if git(repo, 'ls-files', '--others', '--exclude-standard', '-z', '--', ROOT, LEGACY):
        raise ValueError('Some runtime artifacts are not ignored')


def owned(repo, run):
    repo = root_path(repo)
    check_ignore(repo)
    base = repo / ROOT / 'runs'
    for ancestor in (repo / ROOT, base):
        if ancestor.exists() or ancestor.is_symlink():
            info = ancestor.lstat()
            if (not stat.S_ISDIR(info.st_mode) or ancestor.is_symlink()
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise ValueError('Unsafe runtime root')
    candidate = Path(run).absolute()
    try:
        relative = candidate.resolve(strict=False).relative_to(base.resolve(strict=False))
    except ValueError:
        raise ValueError('Not a direct owned run directory')
    if len(relative.parts) != 1 or not re.fullmatch(r'[0-9a-f]{32}', candidate.name):
        raise ValueError('Not a direct owned run directory')
    safe_tree(candidate)
    candidate.resolve(strict=True).relative_to(base.resolve(strict=True))
    state = json.loads((candidate / MANIFEST).read_text(encoding='utf-8'))
    if (state.get('owner') != 'release-docs' or state.get('schema_version') != 1
            or state.get('run_id') != candidate.name or state.get('repo_root') != str(repo)):
        raise ValueError('Ownership manifest mismatch')
    return repo, candidate, state


def save(run, state):
    (run / MANIFEST).write_text(json.dumps(state, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


def prune(repo):
    repo = root_path(repo)
    check_ignore(repo)
    base = repo / ROOT / 'runs'
    # Do not follow a substituted runtime root even if it contains valid manifests.
    for ancestor in (repo / ROOT, base):
        if ancestor.exists() or ancestor.is_symlink():
            info = ancestor.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or ancestor.is_symlink():
                raise ValueError('Unsafe runtime root')
    removed, skipped = [], []
    if base.exists():
        for run in base.iterdir():
            try:
                _, run, state = owned(repo, run)
                if state['status'] not in ('failed', 'interrupted') or (run / LOCK).exists():
                    continue
                if datetime.fromisoformat(state['expires_at']) > datetime.now(timezone.utc):
                    continue
                # owned() validates the entire tree before any recursive deletion.
                shutil.rmtree(run)
                removed.append(run.name)
            except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
                skipped.append(run.name)
    return {'removed': removed, 'skipped': skipped}


def initialize(repo):
    repo = root_path(repo)
    cleanup = prune(repo)
    run = repo / ROOT / 'runs' / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    state = {'schema_version': 1, 'owner': 'release-docs', 'repo_root': str(repo),
             'run_id': run.name, 'status': 'running', 'created_at': now.isoformat(),
             'expires_at': None}
    save(run, state)
    (run / LOCK).write_text('running\n', encoding='utf-8')
    return {'run_id': run.name, 'run_path': run.relative_to(repo).as_posix(), 'prune': cleanup}


def hashes(paths, base):
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def finish(repo, run, documents):
    repo, run, state = owned(repo, run)
    _, docs = validate_output_paths(repo, documents)
    if not all((docs / name).is_file() for name in (*REQUIRED_DOCUMENTS, REPORT)):
        raise ValueError('Deliverables or durable review summary missing')
    if validate(docs)['status'] != '通過':
        raise ValueError('Deliverable structural validation failed')
    report = (docs / REPORT).read_text(encoding='utf-8')
    blocks = re.findall(r'<!-- release-docs-lifecycle\s*(\{.*?\})\s*-->', report, re.S)
    if len(blocks) != 1:
        raise ValueError('Exactly one durable lifecycle receipt is required in 05')
    receipt = json.loads(blocks[0])
    if receipt.get('run_id') != run.name or receipt.get('sql_content_status') != '通過':
        raise ValueError('Review not passed for this run')
    if receipt.get('deployment_status') not in ('通過', '未執行'):
        raise ValueError('Deployment failed or remains blocked; retain evidence')
    if not isinstance(receipt.get('scope'), dict) or not receipt['scope'] or not receipt.get('tooling') or 'unit_mapping' not in receipt:
        raise ValueError('Durable provenance summary incomplete')
    actual_docs = hashes([docs / n for n in DOCUMENTS if (docs / n).exists()], docs)
    if receipt.get('documents') != actual_docs:
        raise ValueError('Deliverable hash inventory changed')
    for name in (*actual_docs, REPORT):
        text = (docs / name).read_text(encoding='utf-8-sig')
        if re.search(r'(?:\.release-docs|release-artifacts)[/\\]', text, re.I):
            raise ValueError('Deliverable still depends on temporary evidence paths')
    evidence = [p for p in run.rglob('*') if p.is_file() and p not in (run / MANIFEST, run / LOCK)]
    if receipt.get('evidence') != hashes(evidence, run) or not evidence:
        raise ValueError('Evidence hash inventory missing or changed')
    # Recheck ownership, aliases and Git membership immediately before deletion.
    owned(repo, run)
    shutil.rmtree(run)
    return {'removed': run.name, 'documents_preserved': str(docs)}


def fail(repo, run, interrupted=False):
    _, run, state = owned(repo, run)
    state['status'] = 'interrupted' if interrupted else 'failed'
    state['expires_at'] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    save(run, state)
    (run / LOCK).unlink(missing_ok=True)
    return {'run_id': run.name, 'status': state['status'], 'expires_at': state['expires_at']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'check', 'finish', 'fail', 'interrupt', 'prune'))
    parser.add_argument('--repo', required=True)
    parser.add_argument('--run')
    parser.add_argument('--documents')
    args = parser.parse_args()
    if args.action in ('check', 'finish', 'fail', 'interrupt') and not args.run:
        parser.error('--run required')
    if args.action == 'finish' and not args.documents:
        parser.error('--documents required')
    try:
        if args.action == 'init':
            result = initialize(args.repo)
        elif args.action == 'prune':
            result = prune(args.repo)
        elif args.action == 'finish':
            result = finish(args.repo, args.run, args.documents)
        elif args.action == 'check':
            _, run, state = owned(args.repo, args.run)
            result = {'safe': True, 'run_id': run.name, 'status': state['status']}
        else:
            result = fail(args.repo, args.run, args.action == 'interrupt')
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(2, 'Lifecycle refused: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()

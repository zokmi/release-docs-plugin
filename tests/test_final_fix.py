"""Real Git scope and read-only destination preflight regressions."""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import test_review_fingerprint as fixtures

NAMES, SCRIPT = fixtures.NAMES, fixtures.SCRIPT

GUARD = SCRIPT.with_name('validate_output_paths.py')


class GitFixture(unittest.TestCase):
    setUp = fixtures.FingerprintTests.setUp
    git = fixtures.FingerprintTests.git
    run_cli = fixtures.FingerprintTests.run_cli


class CommitScopeTests(GitFixture):
    def scope_cli(self, pairs, *extra):
        scope = self.repo.parent / 'scope.json'
        scope.write_text(json.dumps(pairs), encoding='utf-8')
        return subprocess.run([sys.executable, str(SCRIPT), '--repo', str(self.repo),
                               '--documents', str(self.docs), '--commit-scope', str(scope), *extra],
                              capture_output=True)

    def scope(self, pairs):
        result = self.scope_cli(pairs)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return json.loads(result.stdout)

    def test_ordered_noncontiguous_pairs_exclude_intermediate_diff(self):
        a = self.target
        (self.repo / 'intermediate.sql').write_text('SELECT 2;')
        self.git('add', 'intermediate.sql')
        self.git('commit', '-qm', 'B excluded')
        b = self.git('rev-parse', 'HEAD')
        (self.repo / 'selected.sql').write_text('SELECT 3;')
        self.git('add', 'selected.sql')
        self.git('commit', '-qm', 'C selected')
        c = self.git('rev-parse', 'HEAD')
        pairs = [{'commit': a, 'parent': self.base}, {'commit': c, 'parent': b}]
        result = self.scope(pairs)
        self.assertEqual(result['commit_scope'], pairs)
        self.assertNotIn('base', result)
        self.assertNotIn('target', result)
        self.assertNotIn('diff_mode', result)
        self.assertEqual([p['changed_paths'] for p in result['committed']['pairs']],
                         [['schema.sql'], ['selected.sql']])
        for pair, evidence in zip(pairs, result['committed']['pairs']):
            raw = subprocess.check_output(['git', '-C', str(self.repo), 'diff', '--binary',
                                           '--no-ext-diff', '--no-textconv', pair['parent'], pair['commit'], '--', '.'])
            self.assertEqual(evidence['diff'], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(result['fingerprint'], self.scope(list(reversed(pairs)))['fingerprint'])
        self.assertEqual(result['committed'], self.scope(pairs)['committed'])

    def test_root_and_direct_parent_validation(self):
        self.assertEqual(self.scope([{'commit': self.base, 'parent': None}])['commit_scope'],
                         [{'commit': self.base, 'parent': None}])
        for pairs in ([{'commit': self.target, 'parent': None}],
                      [{'commit': self.target, 'parent': self.target}],
                      [{'commit': self.base, 'parent': self.target}], [],
                      [{'commit': self.target}]):
            self.assertNotEqual(self.scope_cli(pairs).returncode, 0, pairs)

    def test_revision_aliases_resolve_to_exact_shas(self):
        result = self.scope([{'commit': 'HEAD', 'parent': 'HEAD^'}])
        self.assertEqual(result['commit_scope'], [{'commit': self.target, 'parent': self.base}])

    def test_merge_explicit_parent_identity(self):
        self.git('checkout', '-qb', 'side', self.base)
        (self.repo / 'side.sql').write_text('SELECT 4;')
        self.git('add', 'side.sql')
        self.git('commit', '-qm', 'side')
        side = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '--detach', self.target)
        self.git('merge', '--no-ff', '-qm', 'merge', 'side')
        merge = self.git('rev-parse', 'HEAD')
        first = self.scope([{'commit': merge, 'parent': self.target}])
        second = self.scope([{'commit': merge, 'parent': side}])
        self.assertNotEqual(first['fingerprint'], second['fingerprint'])
        self.assertNotEqual(self.scope_cli([{'commit': merge, 'parent': self.base}]).returncode, 0)
        self.assertNotEqual(self.scope_cli([{'commit': merge, 'parent': None}]).returncode, 0)

    def test_scope_range_options_mutually_exclusive(self):
        pairs = [{'commit': self.target, 'parent': self.base}]
        for option, value in (('--base', self.base), ('--target', self.target), ('--diff-mode', 'two-dot')):
            self.assertNotEqual(self.scope_cli(pairs, option, value).returncode, 0)


class OutputPathTests(GitFixture):
    def guard(self, docs=None):
        return subprocess.run([sys.executable, str(GUARD), '--repo', str(self.repo),
                               '--documents', str(docs or self.docs)], capture_output=True)

    def test_regular_and_not_yet_created_docs_are_permitted_read_only(self):
        self.assertEqual(self.guard().returncode, 0)
        new = self.repo / 'docs/new-version'
        self.assertEqual(self.guard(new).returncode, 0)
        self.assertFalse(new.exists())
        self.assertNotEqual(self.guard(self.repo.parent / 'outside').returncode, 0)

    def test_all_named_symlinks_refused_without_target_mutation(self):
        outside = self.repo.parent / 'external.sql'
        outside.write_bytes(b'external original')
        for target in (self.source, outside):
            for name in [*NAMES, '05_版更審查報告.md']:
                path = self.docs / name
                path.unlink(missing_ok=True)
                try:
                    path.symlink_to(target)
                except OSError:
                    self.skipTest('OS does not permit symlinks')
                before = target.read_bytes()
                self.assertNotEqual(self.guard().returncode, 0)
                self.assertEqual(target.read_bytes(), before)
                self.assertNotEqual(self.run_cli().returncode, 0)
                path.unlink()
                if name in NAMES:
                    path.write_text('待確認', encoding='utf-8')

    def test_hardlinks_refused(self):
        for name in [NAMES[0], '05_版更審查報告.md']:
            path = self.docs / name
            path.unlink(missing_ok=True)
            try:
                os.link(self.source, path)
            except OSError as error:
                self.skipTest('OS does not permit hardlinks: ' + str(error))
            before = self.source.read_bytes()
            self.assertNotEqual(self.guard().returncode, 0)
            self.assertNotEqual(self.run_cli().returncode, 0)
            self.assertEqual(self.source.read_bytes(), before)
            path.unlink()
            if name in NAMES:
                path.write_text('待確認', encoding='utf-8')

    def test_nonregular_outputs_refused(self):
        for name in [NAMES[0], '05_版更審查報告.md']:
            path = self.docs / name
            path.unlink(missing_ok=True)
            path.mkdir()
            self.assertNotEqual(self.guard().returncode, 0)
            self.assertNotEqual(self.run_cli().returncode, 0)
            path.rmdir()
            if name in NAMES:
                path.write_text('待確認', encoding='utf-8')

    def test_directory_symlink_outside_docs_is_refused(self):
        alias = self.repo / 'docs/alias'
        try:
            alias.symlink_to(self.repo.parent, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit symlinks')
        self.assertNotEqual(self.guard(alias / 'release').returncode, 0)
        self.assertFalse((self.repo.parent / 'release').exists())


if __name__ == '__main__':
    unittest.main()

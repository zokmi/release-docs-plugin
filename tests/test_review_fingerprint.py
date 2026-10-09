import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/release-docs/scripts/review_fingerprint.py'
NAMES = ['01_結構SQL.sql', '02_資料SQL.sql', '03_appsettings異動.md', '04_上線指引.md']


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / '中文 repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'user.name', 'Fixture')
        self.source = self.repo / 'schema.sql'
        self.source.write_text('CREATE TABLE A (Id int);')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.source.write_text('CREATE TABLE B (Id int);')
        self.git('commit', '-qam', 'target')
        self.target = self.git('rev-parse', 'HEAD').strip()
        self.docs = self.repo / 'docs/2026-10-08_fixture'
        self.docs.mkdir(parents=True)
        for name in NAMES:
            (self.docs / name).write_text('待確認', encoding='utf-8')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args]).decode().strip()

    def run_cli(self, **options):
        args = dict(repo=self.repo, documents=self.docs, base=self.base, target=self.target, diff_mode='two-dot')
        args.update(options)
        return subprocess.run([sys.executable, str(SCRIPT), *[part for k,v in args.items() for part in ('--'+k.replace('_','-'), str(v))]], capture_output=True)

    def snapshot(self, **options):
        result = self.run_cli(**options)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        return json.loads(result.stdout)

    def test_stable_and_report_write_does_not_invalidate(self):
        before = self.snapshot()
        (self.docs / '05_版更審查報告.md').write_text(json.dumps(before))
        self.assertEqual(before, self.snapshot())
        self.git('add', 'docs')
        self.assertEqual(before, self.snapshot())

    def test_four_documents_change(self):
        for name in NAMES:
            before = self.snapshot()
            (self.docs / name).write_text('changed')
            self.assertNotEqual(before['fingerprint'], self.snapshot()['fingerprint'])

    def test_scope_and_mode_change(self):
        before = self.snapshot()['fingerprint']
        for options in ({'base':self.target}, {'target':self.base}, {'diff_mode':'three-dot'}):
            self.assertNotEqual(before, self.snapshot(**options)['fingerprint'])

    def test_staged_unstaged_untracked_and_docs_source_change(self):
        before = self.snapshot()['fingerprint']
        self.source.write_text('staged')
        self.git('add', 'schema.sql')
        staged = self.snapshot()['fingerprint']
        self.assertNotEqual(before, staged)
        self.source.write_text('unstaged')
        unstaged = self.snapshot()['fingerprint']
        self.assertNotEqual(staged, unstaged)
        extra = self.repo / 'docs/migration.sql'
        extra.write_text('INSERT INTO A VALUES(1);')
        untracked = self.snapshot()['fingerprint']
        self.assertNotEqual(unstaged, untracked)
        extra.write_text('INSERT INTO A VALUES(2);')
        self.assertNotEqual(untracked, self.snapshot()['fingerprint'])

    def test_target_content_is_not_worktree_content(self):
        before = self.snapshot()
        self.source.write_text('worktree secret')
        after = self.snapshot()
        self.assertEqual(before['committed'], after['committed'])
        self.assertNotEqual(before['working_tree'], after['working_tree'])
        self.assertNotIn('worktree secret', json.dumps(after))

    def test_missing_document_and_outside_docs_fail(self):
        self.assertNotEqual(self.run_cli(documents=self.repo).returncode, 0)
        self.assertNotEqual(self.run_cli(documents=self.repo.parent).returncode, 0)
        for name in (NAMES[0], NAMES[2], NAMES[3]):
            with self.subTest(missing=name):
                path = self.docs / name
                content = path.read_bytes()
                path.unlink()
                self.assertNotEqual(self.run_cli().returncode, 0)
                path.write_bytes(content)

    def test_data_sql_is_optional_for_review(self):
        (self.docs / NAMES[1]).unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_document_symlink_escape_fails(self):
        target = self.repo.parent / 'outside.md'
        target.write_text('outside')
        doc = self.docs / NAMES[0]
        doc.unlink()
        try:
            doc.symlink_to(target)
        except OSError:
            self.skipTest('OS does not permit symlinks')
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_report_symlink_to_internal_source_fails(self):
        report = self.docs / '05_版更審查報告.md'
        try:
            report.symlink_to(self.source)
        except OSError:
            self.skipTest('OS does not permit symlinks')
        self.assertNotEqual(self.run_cli().returncode, 0)


if __name__ == '__main__':
    unittest.main()



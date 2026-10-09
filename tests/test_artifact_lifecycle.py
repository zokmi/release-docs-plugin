"""Lifecycle tests use real Git repositories and filesystem operations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/release-docs/scripts/artifact_lifecycle.py'


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo / '.gitignore').write_text('/.release-docs/\n/docs/release-artifacts/\n')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True, check=True)

    def cli(self, action, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), action, '--repo', str(self.repo), *args], capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def init(self):
        data = self.cli('init')
        return self.repo / data['run_path']

    def test_init_requires_ignore_before_creating_run(self):
        (self.repo / '.gitignore').unlink()
        self.cli('init', ok=False)
        self.assertFalse((self.repo / '.release-docs').exists())

    def test_init_creates_owned_unique_ignored_runs(self):
        first, second = self.init(), self.init()
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads((first / 'run.json').read_text())['owner'], 'release-docs')
        self.git('check-ignore', str(first / 'run.json'))

    def test_force_staged_legacy_artifact_blocks_init(self):
        legacy = self.repo / 'docs/release-artifacts/old.sql'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('SELECT 1;')
        self.git('add', '-f', 'docs/release-artifacts/old.sql')
        self.cli('init', ok=False)
        self.assertTrue(legacy.exists())

    def test_check_detects_new_unignored_file(self):
        run = self.init()
        (self.repo / '.gitignore').write_text('/.release-docs/\n/docs/release-artifacts/\n!/.release-docs/\n!/.release-docs/**\n')
        self.cli('check', '--run', str(run), ok=False)
        self.assertTrue(run.exists())

    def test_failed_run_retained_and_expired_pruned(self):
        run = self.init()
        self.cli('fail', '--run', str(run))
        state = json.loads((run / 'run.json').read_text())
        self.assertEqual(state['status'], 'failed')
        self.assertFalse((run / '.lock').exists())
        self.assertEqual(self.cli('prune')['removed'], [])
        state['expires_at'] = '2000-01-01T00:00:00+00:00'
        (run / 'run.json').write_text(json.dumps(state))
        self.assertEqual(len(self.cli('prune')['removed']), 1)
        self.assertFalse(run.exists())

    def test_prune_preserves_running_locked_and_unowned(self):
        running = self.init()
        unknown = running.parent / 'user-data'
        unknown.mkdir()
        (unknown / 'keep.sql').write_text('SELECT 1;')
        failed = self.init()
        self.cli('fail', '--run', str(failed))
        state = json.loads((failed / 'run.json').read_text())
        state['expires_at'] = '2000-01-01T00:00:00+00:00'
        (failed / 'run.json').write_text(json.dumps(state))
        (failed / '.lock').write_text('active')
        self.assertEqual(self.cli('prune')['removed'], [])
        self.assertTrue(running.exists() and unknown.exists() and failed.exists())

    def receipt(self, run):
        docs = self.repo / 'docs/release-doc/2026-10-12'
        docs.mkdir(parents=True)
        (docs / '00_上線指引.md').write_text('用途說明', encoding='utf-8')
        (docs / '01_結構SQL.sql').write_text('-- artifact_class: schema-deployment\n-- 無異動\n', encoding='utf-8')
        evidence = run / 'tool-output.sql'
        evidence.write_text('-- schema compare: no difference\n')
        hashes = lambda paths: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        receipt = {'run_id': run.name, 'sql_content_status': '通過', 'deployment_status': '未執行',
                   'scope': {'base': 'a', 'target': 'b'}, 'tooling': {'name': 'fixture'},
                   'unit_mapping': [], 'documents': hashes([docs / '00_上線指引.md', docs / '01_結構SQL.sql']),
                   'evidence': hashes([evidence])}
        report = docs / '05_版更審查報告.md'
        report.write_text('<!-- release-docs-lifecycle\n' + json.dumps(receipt, ensure_ascii=False) + '\n-->\n', encoding='utf-8')
        return docs, report, receipt

    def test_finish_removes_only_run_and_preserves_deliverables(self):
        run, other = self.init(), self.init()
        docs, report, _ = self.receipt(run)
        self.cli('finish', '--run', str(run), '--documents', str(docs))
        self.assertFalse(run.exists())
        self.assertTrue(other.exists() and report.exists())

    def test_finish_refuses_changed_evidence(self):
        run = self.init()
        docs, _, _ = self.receipt(run)
        (run / 'tool-output.sql').write_text('changed')
        self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)
        self.assertTrue(run.exists())

    def test_finish_refuses_structurally_invalid_deliverable(self):
        run = self.init()
        docs, report, receipt = self.receipt(run)
        sql = docs / '01_結構SQL.sql'
        sql.write_text('-- unfilled {{SQL}}\n')
        receipt['documents'][sql.name] = hashlib.sha256(sql.read_bytes()).hexdigest()
        report.write_text('<!-- release-docs-lifecycle\n' + json.dumps(receipt) + '\n-->')
        self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)
        self.assertTrue(run.exists())

    def test_force_staged_runtime_blocks_finish(self):
        run = self.init()
        docs, _, _ = self.receipt(run)
        self.git('add', '-f', str(run / 'tool-output.sql'))
        self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)
        self.assertTrue(run.exists())

    def test_interrupted_run_is_retained_seven_days(self):
        run = self.init()
        result = self.cli('interrupt', '--run', str(run))
        from datetime import datetime, timezone
        days = (datetime.fromisoformat(result['expires_at']) - datetime.now(timezone.utc)).total_seconds() / 86400
        self.assertGreater(days, 6.99)
        self.assertEqual(result['status'], 'interrupted')
        self.assertTrue(run.exists())
        self.assertFalse((run / '.lock').exists())

    def test_finish_refuses_changed_document(self):
        run = self.init()
        docs, _, _ = self.receipt(run)
        (docs / '01_結構SQL.sql').write_text('ALTER TABLE x;')
        self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)
        self.assertTrue(run.exists())

    def test_finish_refuses_failed_review_or_deployment(self):
        for key in ['sql_content_status', 'deployment_status']:
            with self.subTest(key=key):
                run = self.init()
                docs, report, receipt = self.receipt(run)
                receipt[key] = '未通過'
                report.write_text('<!-- release-docs-lifecycle\n' + json.dumps(receipt) + '\n-->')
                self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)
                self.assertTrue(run.exists())
                # Each fixture uses the same deliverable path.
                for p in docs.iterdir():
                    p.unlink()
                docs.rmdir()

    def test_finish_refuses_temporary_reference(self):
        run = self.init()
        docs, report, receipt = self.receipt(run)
        guide = docs / '00_上線指引.md'
        guide.write_text('docs/release-artifacts/old/file.sql')
        receipt['documents'][guide.name] = hashlib.sha256(guide.read_bytes()).hexdigest()
        report.write_text('<!-- release-docs-lifecycle\n' + json.dumps(receipt) + '\n-->')
        self.cli('finish', '--run', str(run), '--documents', str(docs), ok=False)

    def test_refuses_outside_or_unowned_run(self):
        self.cli('fail', '--run', str(self.repo), ok=False)
        run = self.init()
        (run / 'run.json').unlink()
        self.cli('fail', '--run', str(run), ok=False)
        self.assertTrue(run.exists())

    def test_refuses_link_or_hard_link_before_deletion(self):
        run = self.init()
        outside = self.repo / 'keep.txt'
        outside.write_text('keep')
        try:
            os.link(outside, run / 'alias')
        except OSError as error:
            self.skipTest(str(error))
        self.cli('fail', '--run', str(run), ok=False)
        self.assertTrue(outside.exists() and run.exists())


if __name__ == '__main__':
    unittest.main()

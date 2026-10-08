import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EvaluationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.clone = Path(self.temp.name)
        (self.clone / 'evals').mkdir()
        self.script = self.clone / 'evals/prepare_actual_fixtures.py'
        shutil.copyfile(ROOT / 'evals/prepare_actual_fixtures.py', self.script)
        (self.clone / 'evals/scenarios.json').write_text(json.dumps({'scenarios': [
            {'id': 'no-changes', 'request': 'same revision', 'sources': {}, 'criteria': []}
        ]}), encoding='utf-8')
        self.run_root = self.clone / 'fresh-run'
        self.archive_root = self.clone / 'evals/actual'

    def invoke(self, with_destinations=True):
        args = [sys.executable, '-X', 'utf8', str(self.script)]
        if with_destinations:
            args += ['--run-root', str(self.run_root), '--archive-root', str(self.archive_root)]
        return subprocess.run(args, capture_output=True, text=True, encoding='utf-8')

    def test_existing_archive_rejected_before_writes_even_without_run(self):
        case = self.archive_root / 'no-changes'
        case.mkdir(parents=True)
        for name in ['invocation.json', 'source-inventory.json', 'outcome.json', 'outputs/05.md']:
            path = case / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'existing evidence\r\n')
        before = {p.relative_to(self.archive_root): p.read_bytes() for p in self.archive_root.rglob('*') if p.is_file()}
        result = self.invoke()
        after = {p.relative_to(self.archive_root): p.read_bytes() for p in self.archive_root.rglob('*') if p.is_file()}
        self.assertEqual(after, before, 'Existing invocation/source/outcome/output bytes must be untouched')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('archive', result.stderr.lower())
        self.assertFalse(self.run_root.exists())
        self.assertFalse((self.clone / '.superpowers').exists())

    def test_existing_run_rejected_before_any_archive_writes(self):
        self.run_root.mkdir()
        marker = self.run_root / 'original.bin'
        marker.write_bytes(b'preserve run\x00')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('run', result.stderr.lower())
        self.assertEqual(marker.read_bytes(), b'preserve run\x00')
        self.assertFalse(self.archive_root.exists())

    def test_fresh_explicit_destinations_generate_separate_git_and_archive(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        invocation = json.loads((self.archive_root / 'no-changes/invocation.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(invocation['repo']).is_relative_to(self.run_root))
        self.assertTrue((Path(invocation['repo']) / '.git').is_dir())
        self.assertEqual(invocation['base'], invocation['target'])
        self.assertFalse((self.clone / '.superpowers').exists())

    def test_destinations_are_required_before_any_writes(self):
        result = self.invoke(with_destinations=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--run-root', result.stderr)
        self.assertFalse(self.archive_root.exists())
        self.assertFalse((self.clone / '.superpowers').exists())


if __name__ == '__main__':
    unittest.main()

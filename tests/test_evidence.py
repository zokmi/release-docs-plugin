import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/release-docs/scripts/collect_release_evidence.py'


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='版更 空白 ', dir=SCRIPT.parents[3])
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        for name in ['modify.sql', 'delete.sql', '舊 檔.sql', 'appsettings.json']:
            self.write(name, name + ': secret-original-value\n')
        self.base = self.commit('base')
        self.write('modify.sql', 'changed SQL secret\n')
        (self.repo / 'delete.sql').unlink()
        self.git('mv', '舊 檔.sql', '新 檔.sql')
        self.write('add.sql', 'new SQL secret\n')
        self.target = self.commit('target')
        self.write('later.sql', 'not in target\n')
        self.head = self.commit('later')
        self.write('staged.sql', 'staged secret\n')
        self.git('add', 'staged.sql')
        self.write('appsettings.json', 'unstaged-secret-value\n')
        self.write('未追蹤 空白.sql', 'untracked-secret-value\n')
        (self.repo / 'nested/deeper').mkdir(parents=True)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args]).decode('utf-8').strip()

    def write(self, name, content):
        (self.repo / name).write_text(content, encoding='utf-8')

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def collect(self, base=None, target=None, mode='direct', repo=None):
        self.assertTrue(SCRIPT.is_file(), 'Evidence collector is missing')
        return subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), '--repo', str(repo or self.repo / 'nested/deeper'), '--base', base or self.base, '--target', target or self.target, '--diff-mode', mode], capture_output=True, text=True, encoding='utf-8')

    def test_old_target_and_nul_paths_are_separate_from_working_tree(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(Path(data['repo_root']), self.repo.resolve())
        self.assertEqual((data['base_sha'], data['target_sha'], data['diff_mode']), (self.base, self.target, 'direct'))
        changes = {item['path']: item for item in data['committed_changes']}
        self.assertEqual(set(changes), {'modify.sql', 'delete.sql', '新 檔.sql', 'add.sql'})
        self.assertEqual({p: x['status'][0] for p, x in changes.items()}, {'modify.sql': 'M', 'delete.sql': 'D', '新 檔.sql': 'R', 'add.sql': 'A'})
        self.assertEqual(changes['新 檔.sql']['old_path'], '舊 檔.sql')
        self.assertEqual(changes['delete.sql']['source_revision'], self.base)
        self.assertEqual(changes['add.sql']['source_revision'], self.target)
        work = data['working_tree_changes']
        self.assertEqual({x['path'] for x in work['staged']}, {'staged.sql'})
        self.assertEqual({x['path'] for x in work['unstaged']}, {'appsettings.json'})
        self.assertEqual({x['path'] for x in work['untracked']}, {'未追蹤 空白.sql'})
        for secret in ['secret-original-value', 'unstaged-secret-value', 'untracked-secret-value', 'changed SQL secret']:
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_merge_base_diff_on_diverged_branches(self):
        self.git('checkout', '-qb', 'other', self.base)
        self.write('other.sql', 'other\n')
        other = self.commit('other')
        direct = json.loads(self.collect(base=other).stdout)
        merged = json.loads(self.collect(base=other, mode='merge-base').stdout)
        self.assertIn('other.sql', {x['path'] for x in direct['committed_changes']})
        self.assertNotIn('other.sql', {x['path'] for x in merged['committed_changes']})
        self.assertEqual(merged['base_sha'], self.base)

    def test_no_changes(self):
        result = self.collect(base=self.target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['committed_changes'], [])

    def test_unknown_revision_fails_without_json(self):
        result = self.collect(base='nonexistent-revision')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('revision', result.stderr.lower())

    def test_non_repository_fails(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[3]) as outside:
            result = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), '--repo', outside, '--base', self.base, '--target', self.target, '--diff-mode', 'direct'], capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(Path(outside).parent)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('not a git repository', result.stderr.lower())


if __name__ == '__main__':
    unittest.main()

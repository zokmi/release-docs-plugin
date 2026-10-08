import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'scripts/check_plugin_release.py'
        if not path.is_file():
            raise AssertionError('release checker is missing')
        spec = importlib.util.spec_from_file_location('release_check', path)
        cls.check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.check)

    def test_strict_tag_validation(self):
        self.assertEqual(self.check.validate_tag('v0.1.0'), '0.1.0')
        for tag in ['v01.1.0', '0.1.0', 'v1.2', 'v1.2.3-rc1', 'v1.2.3\n', '--help', 'v1.2.3;echo bad', 'refs/tags/v1.2.3']:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.check.validate_tag(tag)

    def test_versions_and_missing_resources_block_release(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            for name in self.check.MANIFESTS + self.check.RESOURCES:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, dest)
                if name in self.check.MANIFESTS:
                    data = json.loads(dest.read_text(encoding='utf-8'))
                    data['version'] = '0.1.0'  # synthetic release fixture independent of repository version
                    dest.write_text(json.dumps(data), encoding='utf-8')
            self.check.check_package(root, 'v0.1.0')
            path = root / self.check.MANIFESTS[1]
            data = json.loads(path.read_text(encoding='utf-8'))
            data['version'] = '0.2.0'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'version'):
                self.check.check_package(root, 'v0.1.0')
            data['version'] = '0.1.0'
            path.write_text(json.dumps(data), encoding='utf-8')
            (root / self.check.RESOURCES[0]).unlink()
            with self.assertRaisesRegex(ValueError, 'Missing'):
                self.check.check_package(root, 'v0.1.0')

    def test_real_git_tag_must_resolve_on_main_and_match_checkout(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT).decode().strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.email', 'fixture@example.invalid')
            git('config', 'user.name', 'Fixture')
            (root / 'file').write_text('base')
            git('add', '.')
            git('commit', '-qm', 'base')
            git('update-ref', 'refs/remotes/origin/main', 'HEAD')
            git('tag', '-a', 'v0.1.0', '-m', 'fixture')
            self.check.check_git(root, 'v0.1.0')
            git('checkout', '-qb', 'other')
            (root / 'file').write_text('other')
            git('commit', '-qam', 'other')
            git('tag', 'v0.2.0')
            with self.assertRaisesRegex(ValueError, 'origin/main'):
                self.check.check_git(root, 'v0.2.0')
            with self.assertRaisesRegex(ValueError, 'checkout'):
                self.check.check_git(root, 'v0.1.0')

    def test_workflow_gate_order_and_scoped_permissions(self):
        text = (ROOT / '.github/workflows/release.yml').read_text()
        self.assertIn('permissions:\n  contents: read', text)
        self.assertEqual(text.count('contents: write'), 1)
        self.assertLess(text.index('Validate tag input'), text.index('ref: ${{ needs.validate.outputs.tag }}'))
        self.assertIn('needs: [validate, test]', text)
        self.assertLess(text.index('check_plugin_release.py --tag'), text.index('gh release create'))
        self.assertNotIn('${{ inputs.tag }}', text[text.index('run: |'):])
        self.assertIn('--verify-tag --generate-notes', text)
        self.assertIn('gh release view', text)


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_manifests_have_consistent_identity_and_resolvable_skills(self):
        for name in ['plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json']:
            with self.subTest(manifest=name):
                path = ROOT / name
                self.assertTrue(path.is_file(), f'Missing manifest: {name}')
                data = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual((data['name'], data['version']), ('release-docs', '0.1.0'))
                self.assertEqual(data['skills'], './skills/')
                self.assertTrue((ROOT / data['skills']).is_dir())
                self.assertNotIn('mcpServers', data)
                self.assertNotIn('dependencies', data)

    def test_package_has_license_readme_and_collector(self):
        for name in ['LICENSE', 'README.md', 'skills/release-docs/scripts/collect_release_evidence.py']:
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()

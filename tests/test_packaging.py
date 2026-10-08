import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_skill_frontmatter_and_all_local_references_resolve(self):
        for skill in ['release-docs', 'release-docs-review']:
            path = ROOT / 'skills' / skill / 'SKILL.md'
            text = path.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('---\n'))
            front = text.split('---', 2)[1]
            self.assertIn('name: ' + skill, front)
            self.assertRegex(front, r'(?m)^description: .+')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if not target.startswith(('https://', 'http://')):
                    self.assertTrue((path.parent / target).is_file(), target)

    def test_local_marketplaces_resolve_to_plugin_root(self):
        for name in ['.claude-plugin/marketplace.json', '.agents/plugins/marketplace.json']:
            data = json.loads((ROOT / name).read_text(encoding='utf-8'))
            self.assertEqual(data['name'], 'release-docs-plugins')
            entry = data['plugins'][0]
            self.assertEqual(entry['name'], 'release-docs')
            source = entry['source']
            path = source if isinstance(source, str) else source['path']
            self.assertEqual((ROOT / path).resolve(), ROOT)
            self.assertEqual(json.loads((ROOT / path / 'plugin.json').read_text(encoding='utf-8'))['name'], entry['name'])

    def test_manifests_have_consistent_identity_and_resolvable_skills(self):
        version = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))['version']
        for name in ['plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json']:
            with self.subTest(manifest=name):
                path = ROOT / name
                self.assertTrue(path.is_file(), f'Missing manifest: {name}')
                data = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual((data['name'], data['version']), ('release-docs', version))
                self.assertEqual(data['skills'], './skills/')
                self.assertTrue((ROOT / data['skills']).is_dir())
                self.assertNotIn('mcpServers', data)
                self.assertNotIn('dependencies', data)

    def test_package_has_license_readme_and_collector(self):
        for name in ['LICENSE', 'README.md', 'skills/release-docs/scripts/collect_release_evidence.py']:
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()

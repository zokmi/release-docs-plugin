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

    def test_transactional_pipeline_resources_are_packaged(self):
        for name in ('detect_entity_framework.py', 'analyze_release_units.py', 'assemble_deployment_sql.py',
                     'run_local_validation.py', 'render_release_documents.py', 'lifecycle_store.py'):
            self.assertTrue((ROOT / 'skills/release-docs/scripts' / name).is_file(), name)
        for name in ('validate_release_output.py', 'review_fingerprint.py'):
            self.assertTrue((ROOT / 'skills/release-docs-review/scripts' / name).is_file(), name)
        for name in ('00_上線指引.md', '02_參數異動.md'):
            self.assertTrue((ROOT / 'skills/release-docs/assets' / name).is_file(), name)

    def test_transaction_validation_contract_is_documented(self):
        rules = (ROOT / 'references/sql-review-rules.md').read_text(encoding='utf-8')
        skill = (ROOT / 'skills/release-docs/SKILL.md').read_text(encoding='utf-8')
        for text in (rules, skill):
            self.assertIn('ValidateOnly=1', text)
            self.assertIn('ValidateOnly=0', text)
            self.assertIn('同一 connection/session', text)
            self.assertIn('禁止第一次', text)

    def test_index_adjustment_is_optional_and_guarded(self):
        guide = (ROOT / 'assets/00_上線指引.md').read_text(encoding='utf-8')
        index_sql = (ROOT / 'assets/01_索引調整.sql').read_text(encoding='utf-8')
        validator = (ROOT / 'skills/release-docs/scripts/validate_release_artifacts.py').read_text(encoding='utf-8')
        self.assertIn('01_索引調整.sql', guide)
        self.assertIn('sys.indexes', index_sql)
        self.assertIn('找不到或多個符合者停止', index_sql)
        self.assertIn('index-adjustment', validator)

    def test_guide_template_is_dba_change_summary(self):
        guide = (ROOT / 'assets/00_上線指引.md').read_text(encoding='utf-8')
        self.assertIn('## 結構異動表格說明', guide)
        self.assertIn('## 資料異動表格說明', guide)
        self.assertIn('## 執行摘要', guide)
        self.assertNotIn('## 完整驗證與部署', guide)


if __name__ == '__main__':
    unittest.main()

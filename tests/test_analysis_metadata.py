import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs/scripts'))
from analyze_release_units import AnalysisResult, analyze_release_units
from lifecycle_store import write_lifecycle_run
from collect_release_evidence import collect_release_evidence
import subprocess


def _config_evidence(tmp_path, before, after):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    config = tmp_path / 'appsettings.json'
    config.write_text(before, encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    config.write_text(after, encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '--allow-empty', '-qm', 'target')
    target = git('rev-parse', 'HEAD')
    return collect_release_evidence(tmp_path, base, target)


def test_pinned_appsettings_change_populates_analysis_without_worktree_content(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":120}}')
    (tmp_path / 'appsettings.json').write_text('{"Cache":{"TTL":999}}', encoding='utf-8')
    evidence['parameter_source_inventory'] = {
        'appsettings.json': {'environment': 'Production', 'service': 'CustomerAPI'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is True
    assert [(item['key'], item['old_value'], item['new_value'])
            for item in analysis.parameter_changes] == [('Cache:TTL', 60, 120)]
    assert {item['role'] for item in analysis.checked_parameter_sources} == {'base', 'target'}
    assert all('content' not in item for item in analysis.checked_parameter_sources)


def test_unchanged_pinned_config_is_confirmed_false_with_checked_sources(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":60}}')
    evidence['parameter_source_inventory'] = {
        'appsettings.json': {'environment': 'Production', 'service': 'CustomerAPI'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is False
    assert analysis.parameter_changes == []
    assert {item['role'] for item in analysis.checked_parameter_sources} == {'base', 'target'}


def test_config_without_scope_stays_unresolved_and_blocks_analysis(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":120}}')
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert analysis.blocked
    assert analysis.checked_parameter_sources


def test_checked_parameter_sources_are_persisted_without_raw_secret(tmp_path):
    analysis = AnalysisResult(parameters_applicable=False)
    analysis.checked_parameter_sources = [
        {'role': 'target', 'path': 'appsettings.json', 'revision': 'a' * 40,
         'source_hash': 'b' * 64, 'note': 'opaque-production-secret'}]
    manifest = write_lifecycle_run(tmp_path / '.release-docs/runs/checked', analysis,
                                   secrets=('opaque-production-secret',))
    raw = (manifest.parent / 'source_unit_metadata.json').read_text(encoding='utf-8')
    saved = json.loads(raw)
    assert saved['parameters_applicable'] is False
    assert saved['checked_parameter_sources'][0]['path'] == 'appsettings.json'
    assert 'opaque-production-secret' not in raw


def test_analysis_metadata_roundtrip_masks_secrets(tmp_path):
    analysis = AnalysisResult()
    analysis.structure_changes = [{'unit_id': 'one', 'kind': 'table', 'name': 'dbo.One',
                                   'description': '建立', 'impact': '查詢'}]
    analysis.parameters_applicable = True
    analysis.parameter_changes = [{'environment': 'test', 'service': 'api', 'key': 'Token',
                                   'new_value': 'sensitive-value', 'format_example': 'sensitive-value',
                                   'apply': 'set sensitive-value', 'reload': 'restart', 'validation': 'health'}]
    manifest = write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis)
    raw = (manifest.parent / 'source_unit_metadata.json').read_text()
    saved = json.loads(raw)
    assert saved['structure_changes'] == analysis.structure_changes
    assert saved['parameters_applicable'] is True
    assert 'sensitive-value' not in raw
    assert 'new_value' not in raw
    assert '[REDACTED]' in saved['parameter_changes'][0]['apply']


def test_lifecycle_redacts_generator_secrets_in_each_durable_document(tmp_path):
    analysis = AnalysisResult()
    analysis.findings = [{'blocking': False,
                          'message': 'provider returned lifecycle-generator-secret'}]
    manifest = write_lifecycle_run(
        tmp_path / '.release-docs/runs/generator', analysis,
        secrets=(secret for secret in ['lifecycle-generator-secret']))

    for name in ('lifecycle_exclusion_manifest.json', 'source_unit_metadata.json',
                 'lifecycle_metadata.json'):
        content = (manifest.parent / name).read_text(encoding='utf-8')
        assert 'lifecycle-generator-secret' not in content
    assert 'provider returned [REDACTED]' in \
        (manifest.parent / 'source_unit_metadata.json').read_text(encoding='utf-8')


def test_unknown_parameter_applicability_is_persisted(tmp_path):
    analysis = AnalysisResult()
    manifest = write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis)
    saved = json.loads((manifest.parent / 'source_unit_metadata.json').read_text())
    assert saved['parameters_applicable'] is None


def test_parameter_contract_conflict_is_rejected_before_write(tmp_path):
    analysis = AnalysisResult()
    analysis.parameters_applicable = True
    with pytest.raises(ValueError, match='applicability'):
        write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis,
                            operator_contract={'parameters_applicable': False})
    assert not (tmp_path / '.release-docs/runs/one').exists()


def test_scope_decisions_survive_analysis(tmp_path):
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('')
    scope = {'base_sha': 'a' * 40, 'target_sha': 'b' * 40, 'requested_base_sha': 'c' * 40,
             'diff_base_sha': 'a' * 40, 'diff_mode': 'merge-base', 'workspace_policy': 'excluded'}
    result = analyze_release_units(tmp_path, scope, baseline, None)
    assert result.source_scope == scope


def test_path_helper_supports_missing_junction_api():
    from path_safety import is_linked_path
    class LegacyPath:
        def is_symlink(self): return False
        def exists(self): return False
    assert is_linked_path(LegacyPath()) is False


def test_path_helper_rejects_reparse():
    from path_safety import is_linked_path
    class ReparsePath:
        def is_symlink(self): return False
        def exists(self): return True
        def stat(self):
            return type('Info', (), {'st_file_attributes': 1024})()
    assert is_linked_path(ReparsePath()) is True

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs/scripts'))
from analyze_release_units import (AnalysisResult, _parameter_changed_paths,
                                   analyze_release_units)
from lifecycle_store import write_lifecycle_run
from collect_release_evidence import collect_release_evidence
import subprocess


def _config_evidence(tmp_path, before, after, source_path='appsettings.json'):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    config = tmp_path / source_path
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(before, encoding='utf-8')
    git('add', source_path)
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    config.write_text(after, encoding='utf-8')
    git('add', source_path)
    git('commit', '--allow-empty', '-qm', 'target')
    target = git('rev-parse', 'HEAD')
    return collect_release_evidence(tmp_path, base, target)


def test_pinned_appsettings_change_populates_analysis_without_worktree_content(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":120}}')
    (tmp_path / 'appsettings.json').write_text('{"Cache":{"TTL":999}}', encoding='utf-8')
    evidence['parameter_source_inventory'] = {
        'appsettings.json': {'environment': 'Production', 'service': 'CustomerAPI',
                             'parameter_group': 'Cache', 'business_context': '快取查詢',
                             'module': '查詢 API', 'users': '客服',
                             'impact': '快取期限改為 120 秒'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is True
    assert [(item['key'], item['old_value'], item['new_value'])
            for item in analysis.parameter_changes] == [('Cache:TTL', 60, 120)]
    assert {'base', 'target'} <= {item['role'] for item in analysis.checked_parameter_sources}
    assert all('content' not in item for item in analysis.checked_parameter_sources)
    assert {field: analysis.parameter_changes[0][field] for field in (
        'parameter_group', 'business_context', 'module', 'users', 'impact')} == {
        'parameter_group': 'Cache', 'business_context': '快取查詢',
        'module': '查詢 API', 'users': '客服', 'impact': '快取期限改為 120 秒'}


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
    assert {'base', 'target'} <= {item['role'] for item in analysis.checked_parameter_sources}


def test_config_without_scope_stays_unresolved_and_blocks_analysis(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":120}}')
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert analysis.blocked
    assert analysis.checked_parameter_sources


@pytest.mark.parametrize('supplied_changes', [None, []])
def test_missing_or_incomplete_change_list_does_not_hide_pinned_appsettings(tmp_path, supplied_changes):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":120}}')
    if supplied_changes is None:
        evidence.pop('committed_changes')
    else:
        evidence['committed_changes'] = supplied_changes
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert analysis.blocked
    assert any(item.get('path') == 'appsettings.json'
               for item in analysis.checked_parameter_sources)


def test_renamed_appsettings_to_unrecognized_json_is_inspected(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":60}}')
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('mv', 'appsettings.json', 'runtime.json')
    git('commit', '-qm', 'rename config')
    evidence = collect_release_evidence(tmp_path, evidence['base_sha'], git('rev-parse', 'HEAD'))
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert analysis.blocked
    assert {'appsettings.json', 'runtime.json'} <= {
        item.get('path') for item in analysis.checked_parameter_sources}


def test_missing_inventory_path_is_unresolved_not_confirmed_no_change(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":60}}')
    evidence['parameter_source_inventory'] = {
        'missing.json': {'environment': 'Production', 'service': 'API'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert any(f['code'] == 'unavailable_parameter_source' for f in analysis.findings)


def test_no_config_change_retains_checked_diff_evidence(tmp_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":60}}')
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is False
    assert analysis.checked_parameter_sources
    assert analysis.checked_parameter_sources[0]['role'] == 'diff'


def test_inventory_listed_config_is_a_parameter_source():
    config, deployment = _parameter_changed_paths(
        [{'status': 'M', 'path': 'client.config'},
         {'status': 'M', 'path': 'web.config'}],
        {'client.config': {'environment': 'Production', 'service': 'CustomerAPI'}})

    assert config == {'client.config', 'web.config'}
    assert deployment == set()


@pytest.mark.parametrize('source_path', ['Web.config', 'service/wEb.CoNfIg',
                                       'App.config', 'service/aPP.CONFIG'])
@pytest.mark.parametrize('with_inventory', [False, True])
def test_canonical_config_unsupported_section_blocks_analysis(tmp_path, source_path, with_inventory):
    evidence = _config_evidence(tmp_path, '<configuration/>',
                                '<configuration><custom/></configuration>', source_path)
    if with_inventory:
        evidence['parameter_source_inventory'] = {
            source_path: {'environment': 'Production', 'service': 'API'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.blocked
    assert analysis.parameters_applicable is None
    assert any(f['code'] == 'unresolved_parameter_change' and f.get('source_path') == source_path
               for f in analysis.findings)


def test_standard_xml_setting_change_is_discovered_from_pinned_source(tmp_path):
    evidence = _config_evidence(tmp_path,
        '<configuration><appSettings><add key="Cache:TTL" value="60"/></appSettings></configuration>',
        '<configuration><appSettings><add key="Cache:TTL" value="120"/></appSettings></configuration>', 'Web.config')
    evidence['parameter_source_inventory'] = {'Web.config': {
        'environment': 'Production', 'service': 'API'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')
    analysis = analyze_release_units(tmp_path, evidence, baseline, None)
    assert not analysis.blocked, analysis.findings
    assert analysis.parameters_applicable is True
    assert analysis.parameter_changes[0]['key_segments'] == ['Cache:TTL']
    assert analysis.parameter_changes[0]['target_config'] == {'Cache:TTL': '120'}
    assert analysis.parameter_changes[0]['configuration_provider'] == 'xml'


@pytest.mark.parametrize('operation', ['<clear/>', '<remove key="Inherited"/>'])
def test_xml_inherited_operation_cannot_be_reported_as_no_change(tmp_path, operation):
    before = '<configuration><appSettings><add key="Cache:TTL" value="60"/></appSettings></configuration>'
    after = before.replace('<appSettings>', '<appSettings>' + operation)
    evidence = _config_evidence(tmp_path, before, after, 'Web.config')
    evidence['parameter_source_inventory'] = {'Web.config': {
        'environment': 'Production', 'service': 'API'}}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')
    analysis = analyze_release_units(tmp_path, evidence, baseline, None)
    assert analysis.blocked
    assert analysis.parameters_applicable is None
    assert any(f['code'] == 'unresolved_parameter_change' for f in analysis.findings)


def _deployment_evidence(tmp_path):
    evidence = _config_evidence(tmp_path, 'Foo__Bar=60\n', 'Foo__Bar=120\n', '.env.production')
    provider = tmp_path / 'Provider.cs'
    provider.write_text('builder.AddJsonFile("appsettings.json").AddEnvironmentVariables();', encoding='utf-8')
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], capture_output=True,
                              check=True, text=True).stdout.strip()
    git('add', 'Provider.cs')
    git('commit', '-qm', 'provider proof')
    evidence = collect_release_evidence(tmp_path, evidence['base_sha'], git('rev-parse', 'HEAD'))
    import hashlib
    evidence['deployment_source_inventory'] = {'.env.production': {
        'environment': 'Production', 'service': 'API',
        'provider_precedence': {'conclusion': 'passed', 'reason': 'Consumer registers JSON before environment.',
            'source_reference': {'path': 'Provider.cs', 'revision': evidence['target_sha'],
                                 'source_hash': hashlib.sha256(provider.read_bytes()).hexdigest()}}}}
    return evidence


def test_reviewed_deployment_proof_enables_parameter_discovery(tmp_path):
    evidence = _deployment_evidence(tmp_path)
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')
    analysis = analyze_release_units(tmp_path, evidence, baseline, None)
    assert not analysis.blocked, analysis.findings
    assert analysis.parameters_applicable is True
    item = analysis.parameter_changes[0]
    assert (item['key'], item['old_value'], item['new_value']) == ('Foo:Bar', '60', '120')
    assert item['environment_variable'] == 'Foo__Bar'
    assert any(source['role'] == 'provider' for source in analysis.checked_parameter_sources)


@pytest.mark.parametrize('damage', ['source_hash', 'revision', 'path', 'boolean'])
def test_invalid_deployment_proof_is_blocked(tmp_path, damage):
    evidence = _deployment_evidence(tmp_path)
    metadata = evidence['deployment_source_inventory']['.env.production']
    if damage == 'boolean':
        metadata['provider_precedence'] = True
    else:
        metadata['provider_precedence']['source_reference'][damage] = {
            'source_hash': '0' * 64, 'revision': evidence['base_sha'], 'path': 'missing.cs'}[damage]
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')
    analysis = analyze_release_units(tmp_path, evidence, baseline, None)
    assert analysis.blocked
    assert analysis.parameters_applicable is None
    assert any(f['code'] == 'unresolved_deployment_source' for f in analysis.findings)


@pytest.mark.parametrize('source_path', ['client.config', 'packages.config', 'service/PACKAGES.CONFIG'])
def test_unlisted_noncanonical_config_does_not_block_analysis(tmp_path, source_path):
    evidence = _config_evidence(tmp_path, '<configuration/>',
                                '<configuration><runtime/></configuration>', source_path)
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert not analysis.blocked
    assert analysis.parameters_applicable is False
    assert analysis.parameter_changes == []


@pytest.mark.parametrize('source_path', ['deployment.yaml', 'docker-compose.yml', '.env.production'])
def test_changed_deployment_mapping_reaches_discovery_and_blocks(tmp_path, source_path):
    evidence = _config_evidence(tmp_path, '{"Cache":{"TTL":60}}',
                                '{"Cache":{"TTL":60}}')
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    (tmp_path / source_path).write_text('env:\n  Foo__Bar: value\n', encoding='utf-8')
    git('add', source_path)
    git('commit', '-qm', 'deployment mapping')
    evidence = collect_release_evidence(tmp_path, evidence['base_sha'], git('rev-parse', 'HEAD'))
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('', encoding='utf-8')

    analysis = analyze_release_units(tmp_path, evidence, baseline, None)

    assert analysis.parameters_applicable is None
    assert analysis.blocked
    assert any(item['role'] == 'deployment' and item['path'] == source_path
               for item in analysis.checked_parameter_sources)
    assert any(f.get('key') == 'Foo:Bar' for f in analysis.findings)


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

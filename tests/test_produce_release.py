import hashlib
import json
import re
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs/scripts'))
from analyze_release_units import AnalysisResult


def inputs(tmp_path):
    sql = "IF OBJECT_ID(N'dbo.One', N'U') IS NULL BEGIN CREATE TABLE dbo.One (Id int); END;\n"
    digest = hashlib.sha256(sql.encode()).hexdigest()
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True).stdout.decode().strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (tmp_path / 'one.sql').write_bytes(sql.encode())
    git('add', 'one.sql')
    git('commit', '-qm', 'source')
    revision = git('rev-parse', 'HEAD')
    unit = {'unit_id': 'one', 'phase': 'SCHEMA', 'complete': True, 'sql': sql,
            'source_path': 'one.sql', 'source_revision': revision, 'source_hash': digest,
            'sql_hash': digest, 'source_line': 1, 'depends_on': [], 'objects': ['dbo.One']}
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('-- baseline')
    scope = {'base_sha': revision, 'target_sha': revision, 'diff_mode': 'direct',
             'requested_base_sha': revision, 'diff_base_sha': revision, 'workspace_policy': 'excluded'}
    analysis = AnalysisResult(units=[unit], source_scope=scope)
    analysis.parameters_applicable = False
    analysis.baseline = {'source_path': str(baseline), 'source_hash': hashlib.sha256(baseline.read_bytes()).hexdigest()}
    analysis.structure_changes = [{'unit_id': 'one', 'kind': 'table', 'name': 'dbo.One',
                                  'description': '建立資料表', 'impact': '新增查詢來源'}]
    args = {'repo': tmp_path, 'evidence': scope, 'analysis': analysis, 'release_id': 'release-one',
            'run_root': tmp_path / '.release-docs/runs/one', 'output_dir': tmp_path / 'operator',
            'baseline_source': baseline}
    return args


@pytest.mark.parametrize('damage', ['blocked', 'unknown_parameters', 'missing_structure', 'data_expectations'])
def test_preflight_failure_does_not_produce_sql(tmp_path, damage):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    analysis = args['analysis']
    if damage == 'blocked': analysis.findings = [{'blocking': True, 'code': 'missing_source'}]
    elif damage == 'unknown_parameters': analysis.parameters_applicable = None
    elif damage == 'missing_structure': analysis.structure_changes = []
    else: analysis.units[0]['phase'] = 'DATA'
    with pytest.raises(ProductionError) as error:
        produce_release(**args)
    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()


def test_confirmed_appsettings_diff_cannot_be_delivered_as_sql_only(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    base = args['evidence']['base_sha']
    (tmp_path / 'appsettings.json').write_text('{"Cache":{"TTL":120}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'config change')
    target = git('rev-parse', 'HEAD')
    args['evidence']['target_sha'] = target
    args['evidence']['committed_changes'] = [{'path': 'appsettings.json', 'status': 'A'}]
    args['analysis'].source_scope['target_sha'] = target

    with pytest.raises(ProductionError) as error:
        produce_release(**args)

    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


@pytest.mark.parametrize('supplied_changes', [None, []])
def test_pinned_config_change_blocks_sql_only_when_change_evidence_missing(tmp_path, supplied_changes):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    (tmp_path / 'appsettings.json').write_text('{"Cache":{"TTL":120}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'config change')
    target = git('rev-parse', 'HEAD')
    args['evidence']['target_sha'] = target
    if supplied_changes is not None:
        args['evidence']['committed_changes'] = supplied_changes
    args['analysis'].source_scope['target_sha'] = target

    with pytest.raises(ProductionError) as error:
        produce_release(**args)

    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


def test_missing_inventory_source_blocks_confirmed_no_change_before_output(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    args['evidence']['parameter_source_inventory'] = {
        'missing.json': {'environment': 'Production', 'service': 'API'}}

    with pytest.raises(ProductionError) as error:
        produce_release(**args)

    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


@pytest.mark.parametrize('missing', ['environment', 'service', 'key'])
def test_incomplete_parameter_descriptor_blocks_before_output(tmp_path, missing):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    descriptor = {'environment': 'Production', 'service': 'API', 'key': 'Cache:TTL'}
    descriptor.pop(missing)
    args['analysis'].parameter_changes = [descriptor]
    args['analysis'].parameters_applicable = True

    with pytest.raises(ProductionError) as error:
        produce_release(**args)

    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


def test_partial_descriptors_cannot_hide_a_pinned_config_change(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    config = tmp_path / 'appsettings.json'
    config.write_text('{"Cache":{"TTL":120,"Enabled":true}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'config change')
    target = git('rev-parse', 'HEAD')
    args['evidence']['target_sha'] = target
    args['evidence']['committed_changes'] = [{'path': 'appsettings.json', 'status': 'A'}]
    args['analysis'].source_scope['target_sha'] = target
    args['analysis'].checked_parameter_sources = [{
        'role': 'target', 'path': 'appsettings.json', 'revision': target,
        'source_hash': hashlib.sha256(config.read_bytes()).hexdigest(),
        'environment': 'Production', 'service': 'API'}]
    args['analysis'].parameters_applicable = True
    args['analysis'].parameter_changes = [{
        'environment': 'Production', 'service': 'API', 'key': 'Cache:TTL',
        'change': 'add', 'new_value': 120, 'format_example': 'integer',
        'apply': 'update config', 'reload': 'restart', 'validation': 'health'}]

    with pytest.raises(ProductionError) as error:
        produce_release(**args)

    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


def test_pinned_config_analysis_produces_parameter_document_and_checked_scope(tmp_path):
    from analyze_release_units import analyze_release_units
    from produce_release import produce_release
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    (tmp_path / 'appsettings.json').write_text('{"Cache":{"TTL":120}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'config change')
    target = git('rev-parse', 'HEAD')
    args['evidence']['target_sha'] = target
    args['evidence']['committed_changes'] = [{'path': 'appsettings.json', 'status': 'A'}]
    args['evidence']['parameter_source_inventory'] = {'appsettings.json': {
        'environment': 'Production', 'service': 'API', 'format_example': 'integer',
        'apply': 'update config', 'reload': 'restart', 'validation': 'health'}}
    analysis = analyze_release_units(tmp_path, args['evidence'], args['baseline_source'], None)
    analysis.units = args['analysis'].units
    analysis.structure_changes = args['analysis'].structure_changes
    args['analysis'] = analysis

    result = produce_release(**args)

    assert analysis.parameters_applicable is True
    assert '02_參數異動.md' in result.inventory.files
    saved = json.loads((args['run_root'] / 'source_unit_metadata.json').read_text())
    assert saved['parameters_applicable'] is True
    assert any(item.get('role') == 'target' and item.get('revision') == target
               for item in saved['checked_parameter_sources'])


def parameter_update_inputs(tmp_path, *, unchanged=False, new_value=120):
    from analyze_release_units import analyze_release_units
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    config = tmp_path / 'appsettings.json'
    config.write_text('{"Cache":{"TTL":60}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'base config')
    base = git('rev-parse', 'HEAD')
    if not unchanged:
        config.write_text(json.dumps({'Cache': {'TTL': new_value}}), encoding='utf-8')
        git('add', 'appsettings.json')
        git('commit', '-qm', 'update config')
    target = git('rev-parse', 'HEAD')
    args['evidence'].update(base_sha=base, target_sha=target,
                            requested_base_sha=base, diff_base_sha=base,
                            committed_changes=[] if unchanged else [
                                {'path': 'appsettings.json', 'status': 'M'}])
    args['evidence']['parameter_source_inventory'] = {'appsettings.json': {
        'environment': 'Production', 'service': 'API', 'format_example': 'integer',
        'apply': 'update config', 'reload': 'restart', 'validation': 'health'}}
    analysis = analyze_release_units(tmp_path, args['evidence'], args['baseline_source'], None)
    analysis.units = args['analysis'].units
    analysis.units[0]['source_revision'] = target
    analysis.structure_changes = args['analysis'].structure_changes
    args['analysis'] = analysis
    return args


@pytest.mark.parametrize('unchanged', [False, True], ids=['modified', 'inventory'])
@pytest.mark.parametrize('damage', ['missing_base', 'missing_target', 'duplicate_base',
                                    'duplicate_target', 'missing_diff', 'duplicate_diff',
                                    'wrong_revision', 'extra_source'])
def test_parameter_preflight_requires_exact_pinned_tree_coverage(tmp_path, unchanged, damage):
    from produce_release import produce_release, ProductionError
    args = parameter_update_inputs(tmp_path, unchanged=unchanged)
    analysis = args['analysis']
    checked = analysis.checked_parameter_sources
    if damage.startswith('missing_'):
        role = damage.removeprefix('missing_')
        analysis.checked_parameter_sources = [s for s in checked if s['role'] != role]
    elif damage.startswith('duplicate_'):
        role = damage.removeprefix('duplicate_')
        checked.append(dict(next(s for s in checked if s['role'] == role)))
    elif damage == 'wrong_revision':
        next(s for s in checked if s['role'] == 'base')['revision'] = '0' * 40
    else:
        checked.append({'role': 'target', 'path': 'one.sql',
                        'revision': args['evidence']['target_sha'],
                        'source_hash': args['analysis'].units[0]['source_hash']})
    # Forge internally consistent "add" descriptors after removing the old source.
    # Rediscovery alone accepts these unless coverage is checked against Git trees.
    if damage == 'missing_base' and not unchanged:
        for change in analysis.parameter_changes:
            change['change'] = 'add'
            change.pop('old_value', None)
    with pytest.raises(ProductionError) as error:
        produce_release(**args)
    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


def test_modified_config_is_delivered_as_update_with_both_pinned_sources(tmp_path):
    from produce_release import produce_release
    args = parameter_update_inputs(tmp_path)
    produce_release(**args)
    content = (args['output_dir'] / '02_參數異動.md').read_text(encoding='utf-8')
    assert '| Production | API | Cache:TTL | update | 60 → 120 |' in content
    saved = json.loads((args['run_root'] / 'source_unit_metadata.json').read_text(encoding='utf-8'))
    assert {s['role'] for s in saved['checked_parameter_sources']} == {'diff', 'base', 'target'}


@pytest.mark.parametrize('damage', ['forged', 'omitted'])
def test_parameter_context_cannot_forge_copyable_configuration(tmp_path, damage):
    from produce_release import produce_release, ProductionError
    args = parameter_update_inputs(tmp_path)
    if damage == 'forged':
        args['analysis'].parameter_changes[0]['target_config'] = {'Cache': {'TTL': 999}}
    else:
        args['analysis'].parameter_changes[0].pop('target_config')
    with pytest.raises(ProductionError) as error:
        produce_release(**args)
    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


@pytest.mark.parametrize('damage', ['path', 'revision', 'source_hash', 'line', 'missing_role', 'string', 'segments'])
def test_parameter_preflight_rejects_forged_descriptor_provenance(tmp_path, damage):
    from produce_release import produce_release, ProductionError
    args = parameter_update_inputs(tmp_path)
    item = args['analysis'].parameter_changes[0]
    if damage == 'segments':
        item['key_segments'] = ['Wrong', 'TTL']
    elif damage == 'missing_role':
        item['source_reference'].pop('base')
    elif damage == 'string':
        item['source_reference'] = 'target:forged.json:1'
    else:
        item['source_reference']['target'][damage] = {
            'path': 'forged.json', 'revision': '0' * 40,
            'source_hash': '0' * 64, 'line': 999}[damage]
    with pytest.raises(ProductionError) as error:
        produce_release(**args)
    assert error.value.stage == 'preflight'
    assert not args['run_root'].exists()
    assert not args['output_dir'].exists()


def test_caller_secret_is_redacted_from_parameter_document(tmp_path):
    from produce_release import produce_release
    args = parameter_update_inputs(tmp_path, new_value='opaque-caller-secret')
    change = args['analysis'].parameter_changes[0]
    assert change['key'] == 'Cache:TTL'
    assert change['new_value'] == 'opaque-caller-secret'
    assert change.get('sensitive') is not True
    produce_release(**args, secrets=(s for s in ['opaque-caller-secret']))
    content = (args['output_dir'] / '02_參數異動.md').read_text(encoding='utf-8')
    assert 'opaque-caller-secret' not in content
    assert '[REDACTED]' in content


def test_production_preserves_safe_parameter_projection_for_renderer(tmp_path):
    from analyze_release_units import analyze_release_units
    from produce_release import produce_release
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    config = tmp_path / 'appsettings.json'
    config.write_text('{"Cache":{"TTL":120},"Auth":{"JwtSecret":"PRIVATE_VALUE"}}', encoding='utf-8')
    git('add', 'appsettings.json')
    git('commit', '-qm', 'config change')
    target = git('rev-parse', 'HEAD')
    args['evidence']['target_sha'] = target
    args['evidence']['committed_changes'] = [{'path': 'appsettings.json', 'status': 'A'}]
    args['evidence']['parameter_source_inventory'] = {'appsettings.json': {
        'environment': 'Production', 'service': 'API', 'format_example': 'integer',
        'apply': 'update config', 'reload': 'restart', 'validation': 'health'}}
    analysis = analyze_release_units(tmp_path, args['evidence'], args['baseline_source'], None)
    analysis.units = args['analysis'].units
    analysis.structure_changes = args['analysis'].structure_changes
    for change in analysis.parameter_changes:
        change.update(parameter_group='Runtime', business_context='線上查詢',
                      module='API 查詢', users='客服', impact='快取期限')
    args['analysis'] = analysis

    result = produce_release(**args)

    content = (args['output_dir'] / '02_參數異動.md').read_text(encoding='utf-8')
    assert '02_參數異動.md' in result.inventory.files
    assert '| ["Production","API","Runtime"] | 線上查詢 | API 查詢 | 客服 | 快取期限 |' in content
    assert '| Production | API | Cache:TTL | add | — → 120 |' in content
    assert '"change": "add"' in content and '"new_value": 120' in content
    assert 'PRIVATE_VALUE' not in content
    saved = (args['run_root'] / 'source_unit_metadata.json').read_text(encoding='utf-8')
    assert 'PRIVATE_VALUE' not in saved
    descriptor = next(item for item in json.loads(saved)['parameter_changes']
                      if item['key'] == 'Cache:TTL')
    assert descriptor['key'] == 'Cache:TTL'
    assert 'new_value' not in descriptor


@pytest.mark.parametrize('provider', ['xml', 'environment'])
def test_pinned_non_json_parameter_provider_delivers_document(tmp_path, provider):
    from analyze_release_units import analyze_release_units
    from produce_release import produce_release
    args = inputs(tmp_path)
    def git(*parts):
        return subprocess.run(['git', '-C', str(tmp_path), *parts], check=True,
                              capture_output=True, text=True).stdout.strip()
    path = 'Web.config' if provider == 'xml' else '.env.production'
    content = ('<configuration><appSettings><add key="Cache:TTL" value="120"/>'
               '</appSettings></configuration>' if provider == 'xml' else 'Cache__TTL=120\n')
    (tmp_path / path).write_text(content, encoding='utf-8')
    git('add', path)
    if provider == 'environment':
        consumer = 'builder.AddJsonFile("appsettings.json").AddEnvironmentVariables();\n'
        (tmp_path / 'Provider.cs').write_text(consumer, encoding='utf-8')
        git('add', 'Provider.cs')
    git('commit', '-qm', 'parameter provider change')
    target = git('rev-parse', 'HEAD')
    args['evidence'].update(target_sha=target, committed_changes=[{'path': path, 'status': 'A'}])
    metadata = {'environment': 'Production', 'service': 'API', 'format_example': 'integer',
                'apply': 'update provider', 'reload': 'restart', 'validation': 'health'}
    if provider == 'environment':
        args['evidence']['committed_changes'].append({'path': 'Provider.cs', 'status': 'A'})
        metadata['provider_precedence'] = {'conclusion': 'passed', 'reason': 'Reviewed JSON before environment',
            'source_reference': {'path': 'Provider.cs', 'revision': target,
                                 'source_hash': hashlib.sha256(subprocess.run(
                                     ['git', '-C', str(tmp_path), 'show', target + ':Provider.cs'],
                                     check=True, capture_output=True).stdout).hexdigest()}}
    args['evidence']['parameter_source_inventory' if provider == 'xml' else 'deployment_source_inventory'] = {path: metadata}
    analysis = analyze_release_units(tmp_path, args['evidence'], args['baseline_source'], None)
    assert not analysis.blocked, analysis.findings
    analysis.units = args['analysis'].units
    analysis.units[0]['source_revision'] = target
    analysis.structure_changes = args['analysis'].structure_changes
    args['analysis'] = analysis
    result = produce_release(**args)
    assert '02_參數異動.md' in result.inventory.files
    content = (args['output_dir'] / '02_參數異動.md').read_text(encoding='utf-8')
    blocks = [json.loads(block) for block in re.findall(r'```json\n(.*?)\n```', content, re.S)]
    assert blocks[-1][0]['configuration_provider'] == provider
    assert blocks[-1][0]['key_segments'] == (['Cache:TTL'] if provider == 'xml' else ['Cache', 'TTL'])
    assert '邏輯設定 JSON' in content


def test_delivery_preserves_bytes_and_no_adapter_is_not_run(tmp_path):
    from produce_release import produce_release
    args = inputs(tmp_path)
    result = produce_release(**args)
    assert (args['output_dir'] / '01_部署SQL.sql').read_bytes() == result.artifact.path.read_bytes()
    assert result.stage_statuses['deployment_validation'] == 'not_run'
    assert result.delivery_eligible is False
    assert set(result.inventory.files) == {'00_上線指引.md', '01_部署SQL.sql'}
    source = json.loads((args['run_root'] / 'source_unit_metadata.json').read_text())
    assert source['parameters_applicable'] is False
    assert produce_release(**args).artifact.sha256 == result.artifact.sha256


def test_changed_input_cannot_replace_execution_artifact(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    result = produce_release(**args)
    original = result.artifact.path.read_bytes()
    unit = args['analysis'].units[0]
    unit['sql'] += '-- different\n'
    unit['sql_hash'] = hashlib.sha256(unit['sql'].encode()).hexdigest()
    with pytest.raises(ProductionError): produce_release(**args)
    assert result.artifact.path.read_bytes() == original


def test_render_failure_preserves_permanent_evidence(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    # Collision discovered during preflight, before any permanent write.
    args['output_dir'].mkdir()
    (args['output_dir'] / 'unrelated.txt').write_text('keep')
    with pytest.raises(ProductionError): produce_release(**args)
    assert (args['output_dir'] / 'unrelated.txt').read_text() == 'keep'


def test_excluded_dependency_is_rejected(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    args['analysis'].units[0]['depends_on'] = ['excluded']
    args['analysis'].exclusions = [{'unit_ids': ['excluded']}]
    with pytest.raises(ProductionError): produce_release(**args)
    assert not args['run_root'].exists()


def test_declared_source_hash_is_checked_before_production(tmp_path):
    from produce_release import produce_release, ProductionError
    args = inputs(tmp_path)
    args['analysis'].units[0]['source_hash'] = '0' * 64
    with pytest.raises(ProductionError): produce_release(**args)
    assert not args['run_root'].exists()


def test_unit_only_structure_descriptions_are_delivered(tmp_path):
    from produce_release import produce_release
    args = inputs(tmp_path)
    change = dict(args['analysis'].structure_changes[0])
    change.pop('unit_id')
    args['analysis'].structure_changes = []
    args['analysis'].units[0]['structure_changes'] = [change]
    produce_release(**args)
    text = (args['output_dir'] / '00_上線指引.md').read_text(encoding='utf-8')
    assert 'dbo.One：建立資料表；影響：新增查詢來源' in text
    assert '結構異動說明待確認；來源宣告物件' not in text


def test_produce_release_redacts_supplied_unlabelled_secret_from_lifecycle(tmp_path):
    from produce_release import produce_release
    args = inputs(tmp_path)
    args['analysis'].findings = [{'code': 'provider_warning', 'blocking': False,
                                  'message': 'provider returned opaque-production-secret'}]

    produce_release(**args, secrets=('opaque-production-secret',))

    persisted = (args['run_root'] / 'source_unit_metadata.json').read_text(encoding='utf-8')
    assert 'opaque-production-secret' not in persisted
    assert 'provider returned [REDACTED]' in persisted


def test_produce_release_reuses_generator_secrets_across_durable_lifecycle_writes(tmp_path):
    from produce_release import produce_release
    args = inputs(tmp_path)
    args['analysis'].findings = [{'code': 'provider_warning', 'blocking': False,
                                  'message': 'provider returned generator-production-secret'}]

    produce_release(**args, secrets=(secret for secret in ['generator-production-secret']))

    for name in ('source_unit_metadata.json', 'lifecycle_metadata.json'):
        persisted = (args['run_root'] / name).read_text(encoding='utf-8')
        assert 'generator-production-secret' not in persisted
    persisted = (args['run_root'] / 'source_unit_metadata.json').read_text(encoding='utf-8')
    assert 'provider returned [REDACTED]' in persisted

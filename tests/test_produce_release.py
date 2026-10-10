import hashlib
import json
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

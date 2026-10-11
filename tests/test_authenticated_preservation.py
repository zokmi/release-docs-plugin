"""N/A must describe authenticated execution, including producer status projection."""
import hashlib
import json
from pathlib import Path

import pytest

from test_release_review import (api, git, release, replace_sql, update_metadata,
                                 write_json, _na_localdb_evidence)
from test_semantic_review import record_for


def pin_body(release, sql, provider=None):
    """Keep source, mapping, execution bytes and lifecycle hashes current."""
    from assemble_deployment_sql import assemble_deployment_sql
    repo, _, run, _ = release
    (repo / 'customer.sql').write_bytes(sql.encode('utf-8'))
    git(repo, 'add', 'customer.sql')
    git(repo, 'commit', '-qm', 'pin regression execution')
    revision = git(repo, 'rev-parse', 'HEAD')
    source = json.loads((run / 'source_unit_metadata.json').read_text())
    source['source_scope']['target_sha'] = revision
    digest = hashlib.sha256(sql.encode('utf-8')).hexdigest()
    unit = source['units'][0]
    unit.update(sql=sql, target_definition={'sql': sql}, source_revision=revision,
                source_hash=digest, sql_hash=digest)
    if provider:
        unit['provider_kind'] = provider
    for row in source['sources']:
        if row['source_path'] == 'customer.sql':
            row.update(source_revision=revision, source_hash=digest)
    write_json(run / 'source_unit_metadata.json', source)
    artifact = assemble_deployment_sql([unit], run / 'assembly/01_部署SQL.sql',
                                      {'profile': 'database_tool_minimal'})
    replace_sql(release, artifact.path.read_bytes().decode('utf-8'))
    update_metadata(release, execution_artifact={'path': 'assembly/01_部署SQL.sql',
                    'sha256': artifact.sha256, 'sql_profile': 'database_tool_minimal'})
    return source


@pytest.mark.parametrize('copy_field', ['sql', 'target_definition', 'both'])
def test_valid_hash_mutation_cannot_use_stale_descriptor_na(release, copy_field):
    from semantic_review import write_semantic_review, validate_semantic_review
    source = pin_body(release, 'UPDATE dbo.Customer SET Id=2 WHERE Id=1;\n')
    unit = source['units'][0]
    if copy_field in ('sql', 'both'):
        unit['sql'] = 'SELECT 1;\n'
    if copy_field in ('target_definition', 'both'):
        unit['target_definition']['sql'] = 'SELECT 1;\n'
    write_json(release[2] / 'source_unit_metadata.json', source)
    release = (*release[:3], source['source_scope'])
    evidence, _ = _na_localdb_evidence(release)
    update_metadata(release, localdb_validation=evidence)
    record, _, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    write_semantic_review(release[2], record)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    states = {f['code']: f['status'] for f in result if f['code'].endswith('_status')}
    assert states['sql_content_status'] == '未通過'
    assert states['deployment_validation_status'] != '通過'
    assert 'unit_sql_descriptor_mismatch' in {f['code'] for f in result}
    assert not api()._non_mutating_preservation([unit], {'customer': 'N/A'}, evidence['preservation'])
    assert api()._data_expectations(source, exclusions)[1] is (copy_field == 'both')
    # The standalone source review has no artifact body; the integrated review
    # above is the authority for authenticated execution classification.


@pytest.mark.parametrize('mutation', ['DELETE FROM dbo.Customer', 'UPDATE dbo.Customer SET Id=2'])
def test_modified_dynamic_provider_with_current_hash_cannot_authorize_na(release, mutation):
    from metadata_provider import render_dynamic_drop_constraint_provider
    from assemble_deployment_sql import SQLContractError
    sql = render_dynamic_drop_constraint_provider().replace(
        '    EXEC sys.sp_executesql @ReleaseSql;',
        f"    SET @ReleaseSql = @ReleaseSql + N'; {mutation};';\n"
        '    EXEC sys.sp_executesql @ReleaseSql;')
    with pytest.raises(SQLContractError):
        pin_body(release, sql, 'dynamic_ddl')


@pytest.mark.parametrize('declaration', [
    'Id int IDENTITY(1,1) NOT NULL', 'Id bigint IDENTITY NULL',
    'Total AS (Price * Quantity) PERSISTED',
    'ValidFrom datetime2 GENERATED ALWAYS AS ROW START NOT NULL',
])
def test_generated_existing_row_columns_cannot_authorize_na(declaration):
    from semantic_review import classify_data_impact
    assert classify_data_impact({'sql': f'ALTER TABLE dbo.T ADD {declaration};'}) in ('mutation', 'unknown')


def test_populated_table_identity_addition_requires_fixture_evidence(release):
    from run_local_validation import run_local_validation
    from semantic_review import write_semantic_review
    sql = "IF COL_LENGTH(N'dbo.Customer', N'NewId') IS NULL\nALTER TABLE dbo.Customer ADD NewId int IDENTITY(1,1) NOT NULL;\n"
    source = pin_body(release, sql)
    evidence, _ = _na_localdb_evidence(release)
    baseline = Path(evidence['rounds']['commit']['baseline_source'])
    baseline.write_text('CREATE TABLE dbo.Customer (Id int);', encoding='utf-8')
    Path(evidence['fixture_source']).write_text('INSERT INTO dbo.Customer VALUES (1),(2);', encoding='utf-8')
    manifest = Path(evidence['fixture_manifest'])
    write_json(manifest, {'expected_preserved_data_summary': {'customer': 'N/A'},
                          'preservation': evidence['preservation']})
    calls = []
    result = run_local_validation(release[2] / 'assembly/01_部署SQL.sql',
        server='(localdb)\\test', database='disposable', sql_profile='database_tool_minimal',
        baseline_source=str(baseline), fixture_source=evidence['fixture_source'], fixture_manifest=manifest,
        data_units=source['units'], executor=lambda **kwargs: calls.append(kwargs),
        adapter_provenance='recorded/1', provider_version='sql/1', tool_version='tool/1')
    assert result['data_impact']['customer'] in ('mutation', 'unknown')
    assert result['status'] == 'not_run' and calls == []
    update_metadata(release, localdb_validation=result)
    release = (*release[:3], source['source_scope'])
    record, _, _, _ = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    write_semantic_review(release[2], record)
    findings = api().validate_release_output(release[1], release[2], repo=release[0])
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') != '通過'
    assert 'missing_data_expectations' in {f['code'] for f in findings}


@pytest.mark.parametrize('declaration, expected', [
    ('Amount decimal(10,2) NULL DEFAULT 0', 'non_mutating'),
    ('Amount numeric(18,4) NULL CONSTRAINT DF_Amount DEFAULT (0)', 'non_mutating'),
    ("[Amount, net] decimal(10,2) NULL DEFAULT (CONVERT(decimal(10,2), 0))", 'non_mutating'),
    ("Note nvarchar(20) NULL DEFAULT N'a,b' /* , ignored */", 'non_mutating'),
    ('Amount decimal(10,2) NOT NULL DEFAULT 0', 'mutation'),
    ('Amount decimal(10,2) NULL DEFAULT 0 WITH VALUES', 'mutation'),
    ('Amount decimal(10,2) DEFAULT 0', 'unknown'),
    ('Amount decimal(10,2) NULL DEFAULT 0, Count int NULL DEFAULT 0', 'unknown'),
    ('Amount decimal(10,2) NULL DEFAULT 0, Count int NOT NULL DEFAULT 1', 'mutation'),
])
def test_add_column_commas_respect_lexical_context(declaration, expected):
    from semantic_review import classify_data_impact
    sql = f"IF COL_LENGTH(N'dbo.T', N'Amount') IS NULL\nALTER TABLE dbo.T ADD {declaration};"
    assert classify_data_impact({'sql': sql}) == expected


@pytest.mark.parametrize('profile', ['database_tool_minimal', 'framework'])
def test_producer_runner_renderer_and_review_agree_on_schema_na(tmp_path, profile):
    from produce_release import produce_release
    from semantic_review import write_semantic_review
    from test_produce_release import inputs
    from test_local_validation import _non_mutating_executor
    args = inputs(tmp_path)
    unit = args['analysis'].units[0]
    unit['validation_queries'] = [{'query': 'SELECT 1;', 'expected': 1}]
    fixture = tmp_path / 'input-fixture.sql'
    fixture.write_text('-- schema-only fixture; no formal rows', encoding='utf-8')
    manifest = tmp_path / 'input-fixture.json'
    write_json(manifest, {'expected_preserved_data_summary': {'one': 'N/A'},
                          'preservation': {'one': {'conclusion': 'N/A',
                              'reason': 'one.sql:1: no existing row mutation'}}})
    query_result = {key: unit[key] for key in ('unit_id', 'source_path', 'source_revision', 'source_hash')}
    query_result.update(query_sha256=hashlib.sha256(b'SELECT 1;').hexdigest(),
                        expected=1, actual=1, passed=True)
    def executor(**kwargs):
        raw = _non_mutating_executor(**kwargs)
        raw['checks'] = {'transaction': raw['checks'], 'validation_queries': [dict(query_result)]}
        return raw
    args.update(fixture_source=fixture, fixture_manifest=manifest, validation_options={
        'executor': executor, 'adapter_provenance': 'recorded/1', 'provider_version': 'sql/1',
        'tool_version': 'tool/1', 'command': ['recorded', '--isolated'], 'sql_profile': profile})
    produced = produce_release(**args)
    run, output = args['run_root'], args['output_dir']
    evidence = json.loads((run / 'localdb_validation.json').read_text())
    assert evidence['status'] == 'passed'
    assert evidence['expected_assertions'] == [] and evidence['fixture_seed_rows'] == []
    assert all(row['preserved_data_summary'] == {} and row['data_checks'] == []
               for row in evidence['rounds'].values())
    assert (output / '01_部署SQL.sql').read_bytes() == produced.artifact.path.read_bytes()
    assert 'LocalDB：通過' in (output / '00_上線指引.md').read_text(encoding='utf-8')
    current = (tmp_path, output, run, args['analysis'].source_scope)
    record, _, _, fingerprint = record_for(current)
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    record['unresolved'] = [{'domain': 'business_data_validation', 'reason': 'Formal rows unavailable'}]
    write_semantic_review(run, record)
    findings = api().validate_release_output(output, run, repo=tmp_path)
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') == '通過'
    assert next(f['status'] for f in findings if f['code'] == 'deployment_validation_status') == '通過'
    report = api().write_review_report(run, findings, fingerprint, repo=tmp_path, output_dir=output)
    text = report.read_text(encoding='utf-8')
    assert 'SQL 內容審核：通過' in text and '部署驗證：通過' in text
    assert 'validation SQL 執行：通過' in text
    for name in ('validate_only', 'commit', 'rerun', 'injected_failure'):
        assert f'- {name}：通過' in text
    assert '- business_data_validation [business_data_validation；待確認；非阻塞]' in text

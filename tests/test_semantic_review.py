import copy
import json
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs-review/scripts'))
from test_release_review import release, api


def record_for(release):
    repo, output, run, scope = release
    fingerprint = api('review_fingerprint').review_fingerprint(repo, output, run, scope)
    source = json.loads((run / 'source_unit_metadata.json').read_text())
    exclusions = json.loads((run / 'lifecycle_exclusion_manifest.json').read_text())['exclusions']
    excluded = {uid for entry in exclusions for uid in entry['unit_ids']}
    record = {'schema_version': 1, 'evidence_fingerprint': fingerprint.sha256,
              'method': 'read pinned sources and compare actual execution bytes',
              'scope_review': {'conclusion': 'passed', 'reason': 'All included and excluded units checked'},
              'parameter_review': {'conclusion': 'passed', 'reason': 'No parameter changes confirmed'},
              'unresolved': [], 'conclusion': 'passed', 'unit_reviews': []}
    for unit in source['units']:
        if unit['unit_id'] not in excluded:
            item = {key: unit[key] for key in ('unit_id', 'source_path', 'source_revision', 'source_hash')}
            item.update(conclusion='passed', checks={name: {'conclusion': 'passed', 'reason': 'Compared pinned definition and source conditions'}
                        for name in ('definition', 'preconditions', 'rerun', 'dependencies', 'preservation')})
            item['checks']['preservation']['reason'] = (
                f"無既有資料列異動；來源 {unit['source_path']}:{unit['source_line']}")
            record['unit_reviews'].append(item)
    return record, source, exclusions, fingerprint


@pytest.mark.parametrize('conclusion', ['passed', 'N/A'])
def test_non_mutating_preservation_accepts_explicit_reason(release, conclusion):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = conclusion
    assert validate_semantic_review(record, source, exclusions, fingerprint.sha256) == []


@pytest.mark.parametrize('reason', ['', 'Compared pinned definition',
                                  '無既有資料列異動', '來源 customer.sql:1',
                                  '無既有資料列異動；來源 customer.sql:12345'])
def test_non_mutating_preservation_requires_explanation_and_source(release, reason):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['reason'] = reason
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result and result[0]['domain'] == 'sql_correctness'
    assert result[0]['status'] == '待確認'


@pytest.mark.parametrize('sql', ['UPDATE dbo.Customer SET Id = 2;',
                               'DELETE FROM dbo.Customer;',
                               'MERGE dbo.Customer AS t USING dbo.Other AS s ON t.Id = s.Id '
                               'WHEN MATCHED THEN UPDATE SET Id = s.Id;'])
@pytest.mark.parametrize('damage', ['missing', 'N/A'])
def test_mutation_preservation_missing_evidence_cannot_pass(release, sql, damage):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = sql
    checks = record['unit_reviews'][0]['checks']
    if damage == 'missing':
        del checks['preservation']
    else:
        checks['preservation']['conclusion'] = 'N/A'
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result and result[0]['domain'] == 'sql_correctness'
    assert result[0]['status'] != '通過'


def test_mutation_preservation_retains_normal_review_evidence(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = 'UPDATE dbo.Customer SET Id = 2;'
    record['unit_reviews'][0]['checks']['preservation']['reason'] = (
        'Compared fixture before/after with expected assertions and preserved-data summary')
    assert validate_semantic_review(record, source, exclusions, fingerprint.sha256) == []


def test_mutation_preservation_cannot_claim_no_existing_row_mutation(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = 'UPDATE dbo.Customer SET Id = 2;'
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result and result[0]['status'] == '待確認'


@pytest.mark.parametrize('sql', [
    'ALTER TABLE dbo.Customer ADD Count int NOT NULL DEFAULT 0;',
    'ALTER TABLE dbo.Customer ADD Count int NOT NULL CONSTRAINT DF_Count DEFAULT (0);',
    'ALTER TABLE [dbo].[Customer] ADD [Count] int CONSTRAINT [DF_Count] DEFAULT (0) NOT NULL;',
    'ALTER TABLE dbo.Customer ADD Note int NULL, Count int NOT NULL DEFAULT 0;',
    'ALTER TABLE dbo.Customer ADD Count int DEFAULT 0;',
])
def test_review_fix_default_backfill_preservation_na_cannot_pass(release, sql):
    from semantic_review import classify_data_impact, validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = sql
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result and result[0]['domain'] == 'sql_correctness'
    assert classify_data_impact(source['units'][0]) in ('mutation', 'unknown')


@pytest.mark.parametrize('sql', [
    'ALTER TABLE dbo.Customer ADD Note int NULL, Count int DEFAULT 0;',
    'ALTER TABLE dbo.Customer ADD Count int DEFAULT NULL;',
    'ALTER TABLE dbo.Customer ADD Count int CONSTRAINT DF_Count DEFAULT (NULL);',
])
def test_review_fix_default_expression_does_not_prove_nullable_preservation(sql):
    assert api('semantic_review').classify_data_impact({'sql': sql}) == 'unknown'


@pytest.mark.parametrize('failed_check, preservation_conclusion, reason', [
    ('definition', 'passed', 'Compared pinned definition'),
    ('definition', 'N/A', 'N/A without source explanation'),
    ('preservation', 'failed', 'Preservation is not N/A; fixture assertions failed'),
    ('preservation', 'failed', 'No existing row mutation; fixture assertion failed'),
])
@pytest.mark.parametrize('sql', ['CREATE TABLE dbo.T (Id int);', 'UPDATE dbo.T SET Id = 2;'])
def test_review_fix_failed_preservation_and_definition_remain_blocking(
        release, failed_check, preservation_conclusion, reason, sql):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = sql
    checks = record['unit_reviews'][0]['checks']
    checks['preservation'] = {'conclusion': preservation_conclusion, 'reason': reason}
    checks[failed_check]['conclusion'] = 'failed'
    assert validate_semantic_review(record, source, exclusions, fingerprint.sha256) == [
        {'code': 'semantic_sql_defect', 'domain': 'sql_correctness',
         'blocking': True, 'status': '未通過'}]


def test_review_fix_failed_definition_does_not_bypass_stale_preservation_identity(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['definition']['conclusion'] = 'failed'
    record['unit_reviews'][0]['source_hash'] = '0' * 64
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result[0]['code'] == 'semantic_review_pending'
    assert result[0]['blocking'] is False


def test_failed_definition_survives_malformed_preservation_sibling(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['definition']['conclusion'] = 'failed'
    for sibling in ({'conclusion': 'passed', 'reason': ''},
                    {'conclusion': 'passed'},
                    {'conclusion': '', 'reason': 'Compared source'},
                    {'conclusion': [], 'reason': 'Compared source'}, None):
        damaged = copy.deepcopy(record)
        damaged['unit_reviews'][0]['checks']['preservation'] = sibling
        assert validate_semantic_review(damaged, source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_sql_defect', 'domain': 'sql_correctness',
             'blocking': True, 'status': '未通過'}]


def test_failed_preservation_survives_malformed_definition_sibling(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation'] = {
        'conclusion': 'failed', 'reason': 'Fixture preservation assertion failed'}
    for sibling in ({'conclusion': 'passed', 'reason': ''},
                    {'conclusion': 'passed'},
                    {'conclusion': '', 'reason': 'Compared source'},
                    {'conclusion': [], 'reason': 'Compared source'}, None):
        damaged = copy.deepcopy(record)
        damaged['unit_reviews'][0]['checks']['definition'] = sibling
        assert validate_semantic_review(damaged, source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_sql_defect', 'domain': 'sql_correctness',
             'blocking': True, 'status': '未通過'}]


def test_preservation_failure_dominance_covers_trusted_record_conclusions(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['reason'] = ''
    for location in ('record', 'unit', 'scope_review', 'parameter_review'):
        damaged = copy.deepcopy(record)
        target = (damaged if location == 'record' else damaged['unit_reviews'][0]
                  if location == 'unit' else damaged[location])
        target['conclusion'] = 'failed'
        assert validate_semantic_review(damaged, source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_sql_defect', 'domain': 'sql_correctness',
             'blocking': True, 'status': '未通過'}]


def test_preservation_failure_dominance_requires_all_current_identities(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['definition']['conclusion'] = 'failed'
    record['unit_reviews'][0]['checks']['preservation']['reason'] = ''
    for damage in ('fingerprint', 'schema', 'method', 'coverage', 'source_hash', 'later_unit'):
        damaged, current_source = copy.deepcopy(record), copy.deepcopy(source)
        if damage == 'fingerprint':
            damaged['evidence_fingerprint'] = '0' * 64
        elif damage == 'schema':
            damaged['schema_version'] = 2
        elif damage == 'method':
            damaged['method'] = ''
        elif damage == 'coverage':
            damaged['unit_reviews'] = []
        elif damage == 'source_hash':
            damaged['unit_reviews'][0]['source_hash'] = '0' * 64
        else:
            later_source = copy.deepcopy(next(u for u in source['units']
                                             if u['unit_id'] == record['unit_reviews'][0]['unit_id']))
            later_review = copy.deepcopy(record['unit_reviews'][0])
            later_source['unit_id'] = later_review['unit_id'] = 'later-unit'
            later_review['source_hash'] = '0' * 64
            current_source['units'].append(later_source)
            damaged['unit_reviews'].append(later_review)
        assert validate_semantic_review(damaged, current_source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_review_pending', 'domain': 'sql_correctness',
             'blocking': False, 'status': '待確認'}]


@pytest.mark.parametrize('review_name', ['scope_review', 'parameter_review'])
@pytest.mark.parametrize('failed_location', ['record', 'unit', 'definition', 'preservation'])
def test_failed_semantic_conclusion_requires_well_formed_top_level_reviews(
        release, review_name, failed_location):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    target = (record if failed_location == 'record' else record['unit_reviews'][0]
              if failed_location == 'unit' else record['unit_reviews'][0]['checks'][failed_location])
    target['conclusion'] = 'failed'
    for damage in ('missing', None, {}, 'not a review',
                   {'conclusion': 'passed'},
                   {'conclusion': 'passed', 'reason': ''},
                   {'conclusion': 'passed', 'reason': '   '},
                   {'conclusion': 'passed', 'reason': []},
                   {'conclusion': '', 'reason': 'Compared source'},
                   {'conclusion': [], 'reason': 'Compared source'}):
        damaged = copy.deepcopy(record)
        if damage == 'missing':
            del damaged[review_name]
        else:
            damaged[review_name] = damage
        assert validate_semantic_review(damaged, source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_review_pending', 'domain': 'sql_correctness',
             'blocking': False, 'status': '待確認'}]


def test_malformed_preservation_without_trusted_failure_remains_pending(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    for sibling in ({'conclusion': 'passed', 'reason': ''},
                    {'conclusion': [], 'reason': 'Compared source'}, None):
        damaged = copy.deepcopy(record)
        damaged['unit_reviews'][0]['checks']['preservation'] = sibling
        assert validate_semantic_review(damaged, source, exclusions, fingerprint.sha256) == [
            {'code': 'semantic_review_pending', 'domain': 'sql_correctness',
             'blocking': False, 'status': '待確認'}]


@pytest.mark.parametrize('sql', ['ALTER TABLE dbo.Customer DROP CONSTRAINT DF_Count;',
                               'ALTER TABLE [dbo].[Customer] DROP CONSTRAINT [DF_Count];'])
def test_review_fix_direct_drop_constraint_preservation_accepts_na(release, sql):
    from semantic_review import classify_data_impact, validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition']['sql'] = sql
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    assert classify_data_impact(source['units'][0]) == 'non_mutating'
    assert validate_semantic_review(record, source, exclusions, fingerprint.sha256) == []


@pytest.mark.parametrize('sql, expected', [
    ('ALTER TABLE dbo.T ADD Count int NULL CONSTRAINT DF_Count DEFAULT 0;', 'non_mutating'),
    ('DROP CONSTRAINT DF_Count;', 'unknown'),
    ('ALTER TABLE dbo.T DROP CONSTRAINT DF_Count; UPDATE dbo.T SET Id = 2;', 'mutation'),
    ('ALTER TABLE dbo.T DROP CONSTRAINT DF_Count; DROP TABLE dbo.T;', 'mutation'),
    ('ALTER TABLE dbo.T DROP CONSTRAINT DF_Count; ALTER TABLE dbo.T DROP COLUMN Id;', 'mutation'),
])
def test_review_fix_constraint_and_default_domain_safety(sql, expected):
    assert api('semantic_review').classify_data_impact({'sql': sql}) == expected


@pytest.mark.parametrize('sql', [None, 'EXEC dbo.UnknownProcedure;', 'INSERT INTO dbo.Customer VALUES (1);'])
def test_unknown_data_impact_preservation_remains_pending(release, sql):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition'] = {'sql': sql}
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result and result[0]['domain'] == 'sql_correctness'
    assert result[0]['status'] == '待確認'


@pytest.mark.parametrize('unit, expected', [
    ({'target_definition': {'sql': 'CREATE TABLE dbo.T (Id int);'}}, 'non_mutating'),
    ({'target_definition': {'sql': 'ALTER TABLE dbo.T ADD Name nvarchar(20) NULL;'}}, 'non_mutating'),
    ({'sql': 'CREATE UNIQUE INDEX IX_T ON dbo.T (Id);'}, 'non_mutating'),
    ({'sql': 'ALTER TABLE dbo.T ADD CONSTRAINT FK_T FOREIGN KEY (Id) REFERENCES dbo.P (Id) '
             'ON DELETE CASCADE ON UPDATE CASCADE;'}, 'non_mutating'),
    ({'sql': "-- UPDATE dbo.T\nSELECT 'DELETE FROM dbo.T', [UPDATE] FROM dbo.T;"}, 'non_mutating'),
    ({'sql': 'UPDATE [dbo].[T] SET Id = 2;'}, 'mutation'),
    ({'sql': 'TRUNCATE TABLE dbo.T;'}, 'mutation'),
    ({'sql': 'ALTER TABLE dbo.T DROP COLUMN Name;'}, 'mutation'),
    ({'sql': 'ALTER TABLE dbo.T ALTER COLUMN Id bigint;'}, 'mutation'),
    ({'sql': 'ALTER TABLE dbo.T ADD Count int DEFAULT 0 WITH VALUES;'}, 'mutation'),
    ({'source_path': 'create-index.sql', 'phase': 'SCHEMA', 'data_impact': 'non_mutating'}, 'unknown'),
    ({'sql': 'SELECT * INTO dbo.Copy FROM dbo.T;'}, 'unknown'),
    ({'sql': "EXEC sys.sp_executesql N'UPDATE dbo.T SET Id = 2';"}, 'unknown'),
    ({'sql': 'CREATE TABLE dbo.T (Id int); EXEC dbo.UnknownProcedure;'}, 'unknown'),
    ({'sql': 'SELECT 1; RECONFIGURE;'}, 'unknown'),
    ({'sql': '/* unfinished'}, 'unknown'),
    ({'provider_kind': 'metadata'}, 'unknown'),
    ({'provider_kind': 'metadata', 'sql': "EXEC sys.sp_addextendedproperty N'MS_Description', N'UPDATE';"}, 'non_mutating'),
    ({'provider_kind': 'metadata', 'sql': "EXEC sys.sp_addextendedproperty N'MS_Description', N'text'; UPDATE dbo.T SET Id = 2;"}, 'mutation'),
    ({'provider_kind': 'metadata', 'sql': 'EXEC dbo.UnknownProcedure;'}, 'unknown'),
])
def test_data_impact_domain_uses_authoritative_sql(unit, expected):
    assert api('semantic_review').classify_data_impact(unit) == expected


def test_dynamic_ddl_provider_domain_needs_recognized_execution_body():
    from metadata_provider import render_dynamic_drop_constraint_provider
    unit = {'provider_kind': 'dynamic_ddl', 'sql': render_dynamic_drop_constraint_provider()}
    assert api('semantic_review').classify_data_impact(unit) == 'non_mutating'
    unit['sql'] = 'EXEC sys.sp_executesql @Unknown;'
    assert api('semantic_review').classify_data_impact(unit) == 'unknown'


def test_unknown_preservation_keeps_failed_sql_review_blocking(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    source['units'][0]['target_definition'] = {}
    record['unit_reviews'][0]['checks']['definition']['conclusion'] = 'failed'
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result[0]['domain'] == 'sql_correctness'
    assert result[0]['blocking'] is True


def test_business_data_unresolved_does_not_make_semantic_review_pending(release):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unresolved'] = [{'domain': 'business_data_validation', 'reason': '正式資料列不可取得'}]
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert result == [{'code': 'business_data_validation', 'domain': 'business_data_validation',
                       'blocking': False, 'status': '待確認'}]


@pytest.mark.parametrize('code', [[], 'semantic_sql_defect', 'baseline_model_conflict'])
def test_business_data_unresolved_cannot_hide_invalid_or_sql_evidence(release, code):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    record['unresolved'] = [{'domain': 'business_data_validation', 'reason': 'unresolved', 'code': code}]
    result = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert any(f['domain'] == 'sql_correctness' and f['status'] == '待確認' for f in result)


def test_static_success_without_semantic_record_is_pending(release):
    findings = api().validate_release_output(release[1], release[2])
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') == '待確認'


@pytest.mark.parametrize('runtime_complete', [False, True])
def test_current_complete_semantic_record_requires_runtime_for_pass(release, runtime_complete):
    from semantic_review import write_semantic_review
    from test_release_review import report_query_evidence, update_metadata
    if runtime_complete:
        update_metadata(release, localdb_validation=report_query_evidence(release))
    record, _, _, _ = record_for(release)
    write_semantic_review(release[2], record)
    findings = api().validate_release_output(release[1], release[2], repo=release[0])
    expected = '通過' if runtime_complete else '待確認'
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') == expected
    assert not any(f['code'] == 'semantic_review_pending' for f in findings)
    assert any(f['code'] == 'validation_sql_pending' for f in findings) == (not runtime_complete)
    fingerprint = record_for(release)[3]
    report = api().write_review_report(release[2], findings, fingerprint, repo=release[0], output_dir=release[1])
    assert 'SQL 內容審核：' + expected in report.read_text(encoding='utf-8')


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unknown', 'empty_reason', 'stale'])
def test_incomplete_semantic_record_cannot_pass(release, damage):
    from semantic_review import validate_semantic_review
    record, source, exclusions, fingerprint = record_for(release)
    if damage == 'missing': record['unit_reviews'] = []
    elif damage == 'duplicate': record['unit_reviews'] *= 2
    elif damage == 'unknown': record['unit_reviews'][0]['unit_id'] = 'unknown'
    elif damage == 'empty_reason': record['unit_reviews'][0]['checks']['rerun']['reason'] = ''
    else: record['evidence_fingerprint'] = '0' * 64
    findings = validate_semantic_review(record, source, exclusions, fingerprint.sha256)
    assert findings and all(f['status'] != '通過' for f in findings)


def test_record_and_report_do_not_change_content_fingerprint(release):
    from semantic_review import write_semantic_review
    record, _, _, fingerprint = record_for(release)
    write_semantic_review(release[2], record)
    api().write_review_report(release[2], api().validate_release_output(release[1], release[2], repo=release[0]), fingerprint)
    assert record_for(release)[3].sha256 == fingerprint.sha256
    with pytest.raises(ValueError, match='immutable'):
        write_semantic_review(release[2], {**record, 'method': 'different'})


def test_modified_operator_bytes_invalidate_record(release):
    from semantic_review import write_semantic_review
    record, source, exclusions, _ = record_for(release)
    write_semantic_review(release[2], record)
    path = release[1] / '00_上線指引.md'
    path.write_bytes(path.read_bytes() + b'\nchanged\n')
    from semantic_review import validate_semantic_review
    current = record_for(release)[3]
    assert validate_semantic_review(record, source, exclusions, current.sha256)


def test_zero_units_requires_scope_and_parameter_review():
    from semantic_review import validate_semantic_review
    record = {'schema_version': 1, 'evidence_fingerprint': 'a' * 64, 'method': 'read source',
              'unit_reviews': [], 'unresolved': [], 'conclusion': 'passed'}
    assert validate_semantic_review(record, {'units': []}, [], 'a' * 64)


def test_report_writer_cannot_upgrade_without_semantic_record(release):
    fingerprint = record_for(release)[3]
    supplied = [{'code': 'sql_content_status', 'domain': 'sql_content', 'blocking': False, 'status': '通過'},
                {'code': 'deployment_validation_status', 'domain': 'deployment_validation', 'blocking': False, 'status': '通過'}]
    path = api().write_review_report(release[2], supplied, fingerprint)
    assert 'SQL 內容審核：待確認' in path.read_text(encoding='utf-8')
    assert '部署驗證：通過' in path.read_text(encoding='utf-8')


def test_report_writer_requires_current_identity_even_with_record(release):
    from semantic_review import write_semantic_review
    record, _, _, fingerprint = record_for(release)
    write_semantic_review(release[2], record)
    path = release[1] / '00_上線指引.md'
    path.write_bytes(path.read_bytes() + b'\nchanged\n')
    supplied = [{'code': 'sql_content_status', 'status': '通過', 'blocking': False}]
    report = api().write_review_report(release[2], supplied, fingerprint)
    assert 'SQL 內容審核：待確認' in report.read_text(encoding='utf-8')


def test_fingerprint_cli_preserves_extended_scope(release):
    path = release[2] / 'source_unit_metadata.json'
    source = json.loads(path.read_text())
    source['source_scope']['diff_mode'] = 'direct'
    source['source_scope']['workspace_policy'] = 'excluded'
    path.write_text(json.dumps(source), encoding='utf-8')
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'skills/release-docs-review/scripts/review_fingerprint.py'),
        '--repo', str(release[0]), '--output-dir', str(release[1]), '--run-root', str(release[2]),
        '--base', release[3]['base_sha'], '--target', release[3]['target_sha']], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)['sha256']) == 64

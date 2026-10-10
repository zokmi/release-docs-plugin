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
            record['unit_reviews'].append(item)
    return record, source, exclusions, fingerprint


def test_static_success_without_semantic_record_is_pending(release):
    findings = api().validate_release_output(release[1], release[2])
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') == '待確認'


def test_current_complete_semantic_record_allows_pass(release):
    from semantic_review import write_semantic_review
    record, _, _, _ = record_for(release)
    write_semantic_review(release[2], record)
    findings = api().validate_release_output(release[1], release[2], repo=release[0])
    assert next(f['status'] for f in findings if f['code'] == 'sql_content_status') == '通過'
    fingerprint = record_for(release)[3]
    report = api().write_review_report(release[2], findings, fingerprint, repo=release[0], output_dir=release[1])
    assert 'SQL 內容審核：通過' in report.read_text(encoding='utf-8')


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

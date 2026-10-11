"""Durable workflow checkpoints use real owned lifecycle runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/release-docs/scripts'
sys.path.insert(0, str(SCRIPTS))
from artifact_lifecycle import initialize
from workflow_state import (initialize_workflow_state, invalidate_from,
                            load_workflow_state, record_stage, resume_checkpoint)

STAGES = ('source_collected', 'fixture_ready', 'local_validation_passed',
          'semantic_review_passed', 'report_finalized', 'delivery_finalized')


@pytest.fixture
def run(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    (repo / '.gitignore').write_text('/.release-docs/\n/docs/release-artifacts/\n')
    result = initialize(repo)
    return repo / result['run_path']


def test_schema_and_atomic_creation(run):
    state = load_workflow_state(run)
    assert state['schema_version'] == 2
    assert state['run_id'] == run.name
    assert state['workflow_fingerprint']
    assert state['stages'] == list(STAGES)
    assert state['current_stage'] == STAGES[0]
    assert state['status'] == 'running'
    assert state['attempts'] == {stage: 0 for stage in STAGES}
    assert state['created_at'] and state['updated_at']
    assert list(run.glob('workflow_state.json.*')) == []
    with pytest.raises(ValueError):
        initialize_workflow_state(run, run.name, 'different', STAGES)
    assert load_workflow_state(run) == state


def test_order_attempt_hash_and_invalidation(run):
    output = run / 'source.sql'
    output.write_text('SELECT 1')
    with pytest.raises(ValueError):
        record_stage(run, STAGES[1], status='completed', input_fingerprint='b')
    state = record_stage(run, STAGES[0], status='running', input_fingerprint='a')
    assert state['attempts'][STAGES[0]] == 1
    state = record_stage(run, STAGES[0], status='completed', input_fingerprint='a', output_files=[output])
    assert state['attempts'][STAGES[0]] == 1
    assert state['stage_records'][STAGES[0]]['output_files'] == {
        'source.sql': hashlib.sha256(b'SELECT 1').hexdigest()}
    assert resume_checkpoint(run, state['workflow_fingerprint']) == STAGES[1]
    record_stage(run, STAGES[1], status='completed', input_fingerprint='b')
    state = invalidate_from(run, STAGES[0], 'source changed')
    assert state['current_stage'] == STAGES[0]
    assert state['stage_records'][STAGES[1]]['status'] == 'invalidated'
    state = record_stage(run, STAGES[0], status='completed', input_fingerprint='new', output_files=[output])
    assert state['attempts'][STAGES[0]] == 2
    output.write_text('SELECT 2')
    assert resume_checkpoint(run, state['workflow_fingerprint']) == STAGES[0]


def test_resume_invalidates_changed_workflow_and_rejects_legacy(run):
    assert resume_checkpoint(run, 'changed') == STAGES[0]
    assert load_workflow_state(run)['workflow_fingerprint'] == 'changed'
    (run / 'workflow_state.json').unlink()
    with pytest.raises(ValueError):
        resume_checkpoint(run, 'anything')


def test_missing_lock_finalized_and_unsafe_outputs(run, tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('keep')
    with pytest.raises(ValueError):
        record_stage(run, STAGES[0], status='completed', input_fingerprint='a', output_files=[outside])
    with pytest.raises(ValueError):
        record_stage(run, STAGES[0], status='completed', input_fingerprint='a', output_files=['../outside'])
    (run / '.lock').unlink()
    with pytest.raises(ValueError):
        resume_checkpoint(run, load_workflow_state(run)['workflow_fingerprint'])


def test_invalid_schema_stage_and_status_are_rejected(run):
    path = run / 'workflow_state.json'
    state = json.loads(path.read_text())
    state['schema_version'] = 99
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        load_workflow_state(run)
    state['schema_version'] = 2
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        record_stage(run, 'unknown', status='completed', input_fingerprint='a')
    with pytest.raises(ValueError):
        record_stage(run, STAGES[0], status='unknown', input_fingerprint='a')


def test_atomic_update_preserves_old_state_if_replace_fails(run, monkeypatch):
    before = load_workflow_state(run)
    def fail_replace(*_args):
        raise OSError('replace unavailable')
    monkeypatch.setattr('workflow_state.os.replace', fail_replace)
    with pytest.raises(OSError):
        record_stage(run, STAGES[0], status='running', input_fingerprint='a')
    assert load_workflow_state(run) == before
    assert list(run.glob('workflow_state.json.*.tmp')) == []


def test_tampered_output_path_and_unknown_record_are_rejected(run):
    path = run / 'workflow_state.json'
    state = load_workflow_state(run)
    state['stage_records'][STAGES[0]]['output_files'] = {'../outside': 'a' * 64}
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        load_workflow_state(run)
    state['stage_records'][STAGES[0]]['output_files'] = {}
    state['stage_records']['unknown'] = state['stage_records'][STAGES[0]]
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        load_workflow_state(run)


def test_finalized_state_refuses_more_work(run):
    from workflow_state import mark_workflow_status
    for stage in STAGES:
        record_stage(run, stage, status='completed', input_fingerprint=stage)
    mark_workflow_status(run, 'finalized')
    with pytest.raises(ValueError):
        resume_checkpoint(run, load_workflow_state(run)['workflow_fingerprint'])
    with pytest.raises(ValueError):
        record_stage(run, STAGES[-1], status='completed', input_fingerprint=STAGES[-1])


def test_changed_upstream_output_blocks_advancement_and_invalidates_downstream(run):
    output = run / 'source.sql'
    output.write_text('SELECT 1')
    record_stage(run, STAGES[0], status='completed', input_fingerprint='source', output_files=[output])
    record_stage(run, STAGES[1], status='completed', input_fingerprint='fixture')
    output.write_text('SELECT 2')
    with pytest.raises(ValueError):
        record_stage(run, STAGES[2], status='running', input_fingerprint='validation')
    state = load_workflow_state(run)
    assert state['current_stage'] == STAGES[0]
    assert all(record['status'] == 'invalidated' for record in state['stage_records'].values())


def test_completed_stage_reuse_and_changed_input_invalidate_downstream(run):
    output = run / 'source.sql'
    output.write_text('SELECT 1')
    record_stage(run, STAGES[0], status='completed', input_fingerprint='source', output_files=[output])
    before = record_stage(run, STAGES[1], status='completed', input_fingerprint='fixture')
    assert record_stage(run, STAGES[0], status='completed', input_fingerprint='source', output_files=[output]) == before
    state = record_stage(run, STAGES[0], status='running', input_fingerprint='changed')
    assert state['attempts'][STAGES[0]] == 2
    assert all(state['stage_records'][stage]['status'] == 'invalidated' for stage in STAGES[1:])


def test_invalidation_keeps_first_incomplete_stage_as_checkpoint(run):
    state = invalidate_from(run, STAGES[3], 'review changed')
    assert state['current_stage'] == STAGES[0]
    assert resume_checkpoint(run, state['workflow_fingerprint']) == STAGES[0]


@pytest.mark.parametrize('field,value', [('input_fingerprint', None), ('error_summary', []),
                                        ('started_at', 123), ('completed_at', 123)])
def test_incompatible_stage_record_rejected(run, field, value):
    state = load_workflow_state(run)
    state['stage_records'][STAGES[0]][field] = value
    (run / 'workflow_state.json').write_text(json.dumps(state))
    with pytest.raises(ValueError):
        load_workflow_state(run)


def test_failed_initial_atomic_replace_leaves_no_partial_state(run, monkeypatch):
    (run / 'workflow_state.json').unlink()
    def fail_replace(*_args):
        raise OSError('replace unavailable')
    monkeypatch.setattr('workflow_state.os.replace', fail_replace)
    with pytest.raises(OSError):
        initialize_workflow_state(run, run.name, 'source', STAGES)
    assert not (run / 'workflow_state.json').exists()
    assert list(run.glob('workflow_state.json.*.tmp')) == []


@pytest.mark.parametrize('output', ['.', 'run.json', '.lock', 'workflow_state.json'])
def test_non_evidence_output_rejected(run, output):
    with pytest.raises(ValueError):
        record_stage(run, STAGES[0], status='completed', input_fingerprint='source', output_files=[output])


def test_traversal_is_rejected(run):
    with pytest.raises(ValueError):
        resume_checkpoint(run / '..' / run.name, 'source')


def test_hardlinked_state_is_rejected_when_supported(run):
    import os
    try:
        os.link(run / 'workflow_state.json', run / 'alias.json')
    except OSError as exc:
        pytest.skip(f'hardlink creation is unavailable: {exc}')
    with pytest.raises(ValueError):
        record_stage(run, STAGES[0], status='running', input_fingerprint='source')

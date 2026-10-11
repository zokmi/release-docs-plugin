from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/release-docs/scripts'
sys.path.insert(0, str(SCRIPTS))
from artifact_lifecycle import initialize
from produce_release import ProductionError
from workflow_state import STAGES, load_workflow_state


@pytest.fixture
def owned_run(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    (repo / '.gitignore').write_text('/.release-docs/\n/docs/release-artifacts/\n')
    initialized = initialize(repo)
    return repo, repo / initialized['run_path']


def adapters_for(run, calls, *, fail_once=None):
    failures = {fail_once} if fail_once else set()

    def adapter(stage):
        def execute(run_root, stage_inputs):
            calls[stage] = calls.get(stage, 0) + 1
            if stage in failures:
                failures.remove(stage)
                raise RuntimeError('connection password=DO_NOT_STORE')
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(str(stage_inputs['value']), encoding='utf-8')
            return {'output_files': [output], 'value': stage_inputs['value']}
        return execute

    return {stage: adapter(stage) for stage in STAGES}


@pytest.mark.parametrize('failure_stage', STAGES[:3])
def test_resume_reuses_completed_stages_and_retries_first_incomplete(owned_run, failure_stage):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    adapters = adapters_for(run, calls, fail_once=failure_stage)
    with pytest.raises(ProductionError) as first:
        resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    assert first.value.stage == failure_stage

    result = resume_release(repo, run, current_inputs=inputs, adapters=adapters)

    first_index = STAGES.index(failure_stage)
    assert all(calls[stage] == 1 for stage in STAGES[:first_index])
    assert calls[failure_stage] == 2
    assert all(calls[stage] == 1 for stage in STAGES[first_index + 1:])
    assert result.run_root == run
    assert load_workflow_state(run)['stage_records'][failure_stage]['status'] == 'completed'


def test_changed_stage_input_invalidates_downstream_receipts(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    adapters = adapters_for(run, calls)
    resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    inputs['fixture_ready']['value'] = 'changed fixture'

    resume_release(repo, run, current_inputs=inputs, adapters=adapters)

    assert calls['source_collected'] == 1
    assert calls['fixture_ready'] == 2
    assert all(calls[stage] == 2 for stage in STAGES[2:])


def test_retryable_failure_metadata_is_sanitized_and_never_passed(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    adapters = adapters_for(run, calls, fail_once='local_validation_passed')
    with pytest.raises(ProductionError):
        resume_release(repo, run, current_inputs=inputs, adapters=adapters)

    state = load_workflow_state(run)
    failed = state['stage_records']['local_validation_passed']
    assert failed['status'] in ('failed', 'interrupted')
    assert failed['error_summary']
    assert 'DO_NOT_STORE' not in failed['error_summary']
    assert state['stage_records']['semantic_review_passed']['status'] == 'pending'
    result = resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    assert result.delivery_eligible is False
    assert not any(finding.get('code') == 'sql_content_status'
                   and finding.get('status') == 'passed' for finding in result.findings)


def test_output_hash_change_restarts_at_corrupted_stage(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    adapters = adapters_for(run, calls)
    resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    (run / 'evidence/source_collected.json').write_text('tampered', encoding='utf-8')

    resume_release(repo, run, current_inputs=inputs, adapters=adapters)

    assert calls['source_collected'] == 2
    assert all(calls[stage] == 2 for stage in STAGES[1:])

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

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
    from produce_release import ProductionResult
    result = ProductionResult(
        run, SimpleNamespace(output_dir=run / 'deliverables', files={}),
        SimpleNamespace(path=run / 'evidence' / 'deployment.sql', sha256='b' * 64,
                        release_id='release-1', transaction_mode='transactional',
                        unit_mapping=[], findings=[]),
        {}, [], SimpleNamespace(sha256='c' * 64, components={}, schema_version=1))

    def adapter(stage):
        def execute(run_root, stage_inputs):
            calls[stage] = calls.get(stage, 0) + 1
            if stage in failures:
                failures.remove(stage)
                raise RuntimeError('connection password=DO_NOT_STORE')
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(str(stage_inputs['value']), encoding='utf-8')
            return {'output_files': [output], 'value': stage_inputs.get('value'), 'result': result}
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


@pytest.mark.parametrize('inputs', [
    {'source_collected': {}},
    {**{stage: {} for stage in STAGES}, 'unknown_stage': {}},
])
def test_resume_requires_exactly_one_input_mapping_per_stage(owned_run, inputs):
    from resume_release import resume_release

    repo, run = owned_run
    with pytest.raises(ProductionError) as error:
        resume_release(repo, run, current_inputs=inputs)
    assert error.value.stage == 'preflight'
    assert error.value.code == 'production_contract_violation'


def test_stage_cannot_complete_without_durable_output_files(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    adapters = adapters_for(run, calls)
    adapters['source_collected'] = lambda *_args: {'value': 'not durable'}

    with pytest.raises(ProductionError) as error:
        resume_release(repo, run, current_inputs={stage: {} for stage in STAGES},
                       adapters=adapters)

    assert error.value.stage == STAGES[0]
    assert load_workflow_state(run)['stage_records'][STAGES[0]]['status'] == 'failed'


def test_stage_cannot_complete_with_empty_output_file_generator(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    adapters = adapters_for(run, calls)
    adapters['source_collected'] = lambda *_args: {'output_files': iter(())}

    with pytest.raises(ProductionError) as error:
        resume_release(repo, run, current_inputs={stage: {} for stage in STAGES},
                       adapters=adapters)

    assert error.value.stage == STAGES[0]
    assert load_workflow_state(run)['stage_records'][STAGES[0]]['status'] == 'failed'


def test_invalidated_stage_result_is_not_returned_when_adapter_is_missing(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    adapters = adapters_for(run, calls)
    resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    inputs[STAGES[0]]['value'] = 'changed source input'

    with pytest.raises(ProductionError) as error:
        resume_release(repo, run, current_inputs=inputs)

    assert error.value.stage == STAGES[0]
    assert error.value.code == 'stage_adapter_unavailable'


def test_durable_result_replacement_uses_atomic_replace_and_cleans_temp_on_failure(
        owned_run, monkeypatch):
    import os
    import resume_release as resume_module
    from produce_release import ProductionResult

    _repo, run = owned_run
    result = ProductionResult(
        run, SimpleNamespace(output_dir=run / 'deliverables', files={'guide.md': 'a' * 64}),
        SimpleNamespace(path=run / 'evidence.sql', sha256='b' * 64,
                        release_id='release-1', transaction_mode='transactional',
                        unit_mapping=[], findings=[]),
        {}, [], SimpleNamespace(sha256='c' * 64, components={}, schema_version=1))
    path = run / 'production_result.json'
    path.write_text('{"inventory": {}}', encoding='utf-8')
    replace_observations = []
    fsync_calls = []
    real_fsync = os.fsync

    def observe_fsync(descriptor):
        fsync_calls.append(descriptor)
        return real_fsync(descriptor)

    def observe_replace(source, destination):
        source_path = Path(source)
        replace_observations.append((source_path.parent, source_path.read_bytes(), Path(destination)))
        raise OSError('simulated replace failure')

    monkeypatch.setattr(os, 'replace', observe_replace)
    monkeypatch.setattr(os, 'fsync', observe_fsync)
    with pytest.raises(OSError, match='simulated replace failure'):
        resume_module._save_result(run, result, producer_stage=STAGES[0],
                                   input_fingerprint='d' * 64)

    assert replace_observations
    assert replace_observations[0][0] == run
    assert replace_observations[0][1].startswith(b'{')
    assert replace_observations[0][2] == path
    assert fsync_calls
    assert path.read_text(encoding='utf-8') == '{"inventory": {}}'
    assert not list(run.glob('production_result.json.*.tmp'))


def test_resume_can_enter_the_existing_production_pipeline_without_adapters(owned_run, monkeypatch):
    import resume_release as resume_module
    from produce_release import ProductionResult

    repo, run = owned_run
    for name in ('source_unit_metadata.json', 'lifecycle_exclusion_manifest.json',
                 'localdb_validation.json'):
        path = run / name
        path.write_text('{}', encoding='utf-8')
    expected = ProductionResult(
        run, SimpleNamespace(output_dir=repo / 'output', files={}),
        SimpleNamespace(path=run / 'evidence.sql', sha256='b' * 64, release_id='release-1',
                        transaction_mode='transactional', unit_mapping=[], findings=[]),
        {}, [], SimpleNamespace(sha256='c' * 64, components={}, schema_version=1))
    request = {'repo': repo, 'evidence': object(), 'analysis': object(), 'release_id': 'release-1',
               'run_root': run, 'output_dir': repo / 'output',
               'baseline_source': repo / 'baseline.sql'}
    calls = []

    def pipeline(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(resume_module, 'produce_release', pipeline)
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}

    result = resume_module.resume_release(repo, run, current_inputs=inputs)

    assert calls == [request]
    assert isinstance(result, ProductionResult)
    assert load_workflow_state(run)['stage_records'][STAGES[0]]['status'] == 'completed'


def test_resume_runs_existing_production_pipeline_and_reconstructs_its_result(owned_run):
    import importlib.util
    from resume_release import resume_release

    repo, run = owned_run
    fixture_path = Path(__file__).with_name('test_produce_release.py')
    spec = importlib.util.spec_from_file_location('task3_production_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    request = fixture.inputs(repo)
    request['run_root'] = run
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}

    first = resume_release(repo, run, current_inputs=inputs)
    resumed = resume_release(repo, run, current_inputs=inputs)

    assert first.artifact.sha256
    assert first.inventory.files
    assert first.fingerprint.sha256
    assert resumed.artifact.sha256 == first.artifact.sha256
    assert resumed.inventory.files == first.inventory.files
    assert resumed.fingerprint.sha256 == first.fingerprint.sha256
    assert resumed.delivery_eligible is False
    statuses = load_workflow_state(run)['stage_records']
    assert all(statuses[stage]['status'] == 'completed' for stage in STAGES[:3])
    assert statuses[STAGES[3]]['status'] == 'pending'


def test_resumed_result_reconstructs_production_fields_from_durable_result(owned_run):
    from resume_release import resume_release
    from produce_release import ProductionResult

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    result_data = {
        'inventory': SimpleNamespace(output_dir=repo / 'deliverables', files={'guide.md': 'a' * 64}),
        'artifact': SimpleNamespace(path=run / 'evidence' / 'deployment.sql', sha256='b' * 64,
                                    release_id='release-1', transaction_mode='transactional',
                                    unit_mapping=[], findings=[]),
        'fingerprint': SimpleNamespace(sha256='c' * 64, components={'source_scope': 'd' * 64},
                                       schema_version=1),
    }

    def adapter(stage):
        def execute(run_root, _stage_inputs):
            calls[stage] = calls.get(stage, 0) + 1
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(stage, encoding='utf-8')
            result = ProductionResult(run, result_data['inventory'], result_data['artifact'],
                                      {}, [], result_data['fingerprint'])
            return {'output_files': [output], 'result': result}
        return execute

    adapters = {stage: adapter(stage) for stage in STAGES}
    resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    resumed = resume_release(repo, run, current_inputs=inputs)

    assert resumed.inventory.files == {'guide.md': 'a' * 64}
    assert resumed.artifact.sha256 == 'b' * 64
    assert resumed.fingerprint.sha256 == 'c' * 64

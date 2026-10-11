from pathlib import Path
import hashlib
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


def durable_result(run, output_dir, *, unit_mapping=None, findings=None):
    from produce_release import ProductionResult

    output_dir.mkdir(parents=True, exist_ok=True)
    document = output_dir / 'guide.md'
    document.write_bytes(b'guide')
    artifact_path = run / 'evidence' / 'deployment.sql'
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b'sql')
    return ProductionResult(
        run, SimpleNamespace(output_dir=output_dir,
                             files={'guide.md': hashlib.sha256(b'guide').hexdigest()}),
        SimpleNamespace(path=artifact_path, sha256=hashlib.sha256(b'sql').hexdigest(),
                        release_id='release-1', transaction_mode='transactional',
                        unit_mapping=unit_mapping or [], findings=findings or []),
        {}, [], SimpleNamespace(sha256='c' * 64, components={}, schema_version=1))


def adapters_for(run, calls, *, fail_once=None):
    failures = {fail_once} if fail_once else set()
    result = durable_result(run, run / 'deliverables')

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
    result = durable_result(run, run / 'deliverables')
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
    expected = durable_result(run, repo / 'output')
    for name in ('source_unit_metadata.json', 'lifecycle_exclusion_manifest.json',
                 'localdb_validation.json'):
        (run / name).write_text('{}', encoding='utf-8')
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


def test_builtin_resume_redacts_production_request_secret_from_durable_result(owned_run, monkeypatch):
    import json
    import resume_release as resume_module

    repo, run = owned_run
    result = durable_result(
        run, repo / 'output',
        findings=[{'message': 'provider returned request-only-secret'}])
    for name in ('source_unit_metadata.json', 'lifecycle_exclusion_manifest.json',
                 'localdb_validation.json'):
        (run / name).write_text('{}', encoding='utf-8')
    request = {'repo': repo, 'evidence': {}, 'analysis': {}, 'release_id': 'release-1',
               'run_root': run, 'output_dir': repo / 'output',
               'baseline_source': repo / 'baseline.sql',
               'secrets': ('request-only-secret',)}
    monkeypatch.setattr(resume_module, 'produce_release', lambda **_kwargs: result)
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}

    resume_module.resume_release(repo, run, current_inputs=inputs)

    result_path = run / 'production_result.json'
    payload = json.loads(result_path.read_text(encoding='utf-8'))
    assert payload['artifact']['findings'][0]['message'] == 'provider returned [REDACTED]'
    assert 'request-only-secret' not in result_path.read_text(encoding='utf-8')


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


def test_builtin_production_resumes_from_partial_stage_receipts(owned_run, monkeypatch):
    import resume_release as resume_module
    from produce_release import ProductionResult
    from workflow_state import record_stage

    repo, run = owned_run
    request = {'repo': repo, 'evidence': {}, 'analysis': {}, 'release_id': 'release-1',
               'run_root': run, 'output_dir': repo / 'output',
               'baseline_source': repo / 'baseline.sql'}
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}
    for stage, filename in zip(STAGES[:2], ('source_unit_metadata.json',
                                             'lifecycle_exclusion_manifest.json')):
        receipt = run / filename
        receipt.write_text('{}', encoding='utf-8')
        record_stage(run, stage, status='completed',
                     input_fingerprint=resume_module._stage_fingerprint(stage, inputs[stage]),
                     output_files=[receipt])

    result = durable_result(run, repo / 'output')
    calls = []

    def pipeline(**kwargs):
        calls.append(kwargs)
        for name in ('source_unit_metadata.json', 'lifecycle_exclusion_manifest.json',
                     'localdb_validation.json'):
            (run / name).write_text('{}', encoding='utf-8')
        return result

    monkeypatch.setattr(resume_module, 'produce_release', pipeline)
    resumed = resume_module.resume_release(repo, run, current_inputs=inputs)

    assert calls == [request]
    assert isinstance(resumed, ProductionResult)
    assert all(load_workflow_state(run)['stage_records'][stage]['status'] == 'completed'
               for stage in STAGES[:3])


@pytest.mark.parametrize('damage', ['changed', 'deleted'])
def test_changed_generated_document_forces_builtin_restart(owned_run, damage):
    from resume_release import resume_release

    repo, run = owned_run
    fixture_path = Path(__file__).with_name('test_produce_release.py')
    import importlib.util
    spec = importlib.util.spec_from_file_location('task3_stale_inventory_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    request = fixture.inputs(repo)
    request['run_root'] = run
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}
    first = resume_release(repo, run, current_inputs=inputs)
    generated = first.inventory.output_dir / next(iter(first.inventory.files))
    if damage == 'deleted':
        generated.unlink()
    else:
        generated.write_text('tampered generated document', encoding='utf-8')

    if damage == 'changed':
        with pytest.raises(ProductionError):
            resume_release(repo, run, current_inputs=inputs)
        assert generated.read_text(encoding='utf-8') == 'tampered generated document'
    else:
        resumed = resume_release(repo, run, current_inputs=inputs)
        assert generated.is_file()
        assert resumed.inventory.files == first.inventory.files
        assert hashlib.sha256(generated.read_bytes()).hexdigest() == first.inventory.files[generated.name]


def test_changed_artifact_evidence_is_rejected_and_never_returned(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    fixture_path = Path(__file__).with_name('test_produce_release.py')
    import importlib.util
    spec = importlib.util.spec_from_file_location('task3_stale_artifact_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    request = fixture.inputs(repo)
    request['run_root'] = run
    inputs = {stage: {} for stage in STAGES}
    inputs[STAGES[0]] = {'production_request': request}
    first = resume_release(repo, run, current_inputs=inputs)
    first.artifact.path.write_text('tampered evidence', encoding='utf-8')

    with pytest.raises(ProductionError):
        resume_release(repo, run, current_inputs=inputs)


def test_durable_result_redacts_findings_and_unit_mapping_before_write(owned_run):
    import json
    import resume_release as resume_module
    _repo, run = owned_run
    result = durable_result(
        run, run / 'deliverables', unit_mapping=[{'source': 'password=MAP_SECRET'}],
        findings=[{'message': 'token=FINDING_SECRET'}])

    path = resume_module._save_result(run, result, producer_stage=STAGES[0],
                                      input_fingerprint='d' * 64)
    persisted = json.loads(path.read_text(encoding='utf-8'))

    encoded = path.read_text(encoding='utf-8')
    assert 'MAP_SECRET' not in encoded
    assert 'FINDING_SECRET' not in encoded
    assert persisted['artifact']['unit_mapping'][0]['source'] == 'password=[REDACTED]'
    assert persisted['artifact']['findings'][0]['message'] == 'token=[REDACTED]'


def test_durable_result_replaces_known_unlabelled_secrets(owned_run):
    import json
    import resume_release as resume_module
    _repo, run = owned_run
    result = durable_result(run, run / 'deliverables',
                            findings=[{'message': 'runner failed with known-secret'}])

    path = resume_module._save_result(run, result, producer_stage=STAGES[0],
                                      input_fingerprint='e' * 64,
                                      secrets=('known-secret',))

    persisted = json.loads(path.read_text(encoding='utf-8'))
    assert persisted['artifact']['findings'][0]['message'] == 'runner failed with [REDACTED]'
    assert 'known-secret' not in path.read_text(encoding='utf-8')


def test_resume_api_redacts_supplied_unlabelled_secret_from_durable_result(owned_run):
    import json
    from resume_release import resume_release

    repo, run = owned_run
    inputs = {stage: {'value': stage} for stage in STAGES}
    result = durable_result(run, repo / 'deliverables',
                            findings=[{'message': 'runner returned opaque-resume-secret'}])

    def adapter(stage):
        def execute(run_root, _stage_inputs):
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(stage, encoding='utf-8')
            return {'output_files': [output], 'result': result}
        return execute

    resume_release(repo, run, current_inputs=inputs,
                   adapters={stage: adapter(stage) for stage in STAGES},
                   secrets=('opaque-resume-secret',))

    payload = json.loads((run / 'production_result.json').read_text(encoding='utf-8'))
    assert payload['artifact']['findings'][0]['message'] == 'runner returned [REDACTED]'
    assert 'opaque-resume-secret' not in (run / 'production_result.json').read_text(encoding='utf-8')


def test_resume_reuses_generator_secrets_across_checkpoints_and_result_write(owned_run):
    import json
    from resume_release import resume_release

    repo, run = owned_run
    inputs = {stage: {'value': stage} for stage in STAGES}
    result = durable_result(run, repo / 'deliverables',
                            findings=[{'message': 'runner returned generator-resume-secret'}])

    def adapter(stage):
        def execute(run_root, _stage_inputs):
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(stage, encoding='utf-8')
            return {'output_files': [output], 'result': result}
        return execute

    resume_release(repo, run, current_inputs=inputs,
                   adapters={stage: adapter(stage) for stage in STAGES},
                   secrets=(secret for secret in ['generator-resume-secret']))

    stored = (run / 'production_result.json').read_text(encoding='utf-8')
    assert 'generator-resume-secret' not in stored
    payload = json.loads(stored)
    assert payload['artifact']['findings'][0]['message'] == 'runner returned [REDACTED]'


def test_resumed_result_reconstructs_production_fields_from_durable_result(owned_run):
    from resume_release import resume_release

    repo, run = owned_run
    calls = {}
    inputs = {stage: {'value': stage} for stage in STAGES}
    result = durable_result(run, repo / 'deliverables')
    result.fingerprint = SimpleNamespace(sha256='c' * 64, components={'source_scope': 'd' * 64},
                                         schema_version=1)

    def adapter(stage):
        def execute(run_root, _stage_inputs):
            calls[stage] = calls.get(stage, 0) + 1
            output = run_root / 'evidence' / f'{stage}.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(stage, encoding='utf-8')
            return {'output_files': [output], 'result': result}
        return execute

    adapters = {stage: adapter(stage) for stage in STAGES}
    resume_release(repo, run, current_inputs=inputs, adapters=adapters)
    resumed = resume_release(repo, run, current_inputs=inputs)

    assert resumed.inventory.files == {'guide.md': hashlib.sha256(b'guide').hexdigest()}
    assert resumed.artifact.sha256 == hashlib.sha256(b'sql').hexdigest()
    assert resumed.fingerprint.sha256 == 'c' * 64

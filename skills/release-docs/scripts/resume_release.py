"""Resume an owned release production run from its first incomplete stage."""
from dataclasses import asdict, is_dataclass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from produce_release import ProductionError, ProductionResult, produce_release
from workflow_state import (STAGES, invalidate_from, load_workflow_state,
                            record_stage, resume_checkpoint)


def _canonical(value):
    if isinstance(value, Path):
        if value.is_file():
            return {'path': str(value), 'sha256': hashlib.sha256(value.read_bytes()).hexdigest()}
        return {'path': str(value)}
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {'type': type(value).__name__}


def _stage_fingerprint(stage, stage_inputs):
    encoded = json.dumps({'stage': stage, 'inputs': _canonical(stage_inputs)},
                         sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _result_value(outputs):
    for value in reversed(outputs):
        if isinstance(value, dict) and isinstance(value.get('result'), ProductionResult):
            return value['result']
    return None


def _result_path(run):
    return run / 'production_result.json'


def _artifact_outputs_match(payload):
    try:
        inventory = payload['inventory']
        output_dir = Path(inventory['output_dir'])
        files = inventory['files']
        if not output_dir.is_absolute() or not isinstance(files, dict):
            return False
        expected = set()
        for name, digest in files.items():
            if (not isinstance(name, str) or Path(name).name != name
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(char not in '0123456789abcdef' for char in digest)):
                return False
            path = output_dir / name
            if path.is_symlink() or not path.is_file():
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return False
            expected.add(name)
        actual = set()
        for path in output_dir.iterdir():
            if path.is_symlink() or not path.is_file():
                return False
            actual.add(path.name)
        if actual != expected:
            return False
        artifact = payload['artifact']
        artifact_path = Path(artifact['path'])
        artifact_digest = artifact['sha256']
        return (artifact_path.is_file() and not artifact_path.is_symlink()
                and isinstance(artifact_digest, str) and len(artifact_digest) == 64
                and all(char in '0123456789abcdef' for char in artifact_digest)
                and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact_digest)
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _result_outputs_match(result):
    try:
        return _artifact_outputs_match({
            'inventory': {'output_dir': str(result.inventory.output_dir),
                          'files': result.inventory.files},
            'artifact': {'path': str(result.artifact.path),
                         'sha256': result.artifact.sha256},
        })
    except (AttributeError, TypeError, ValueError):
        return False


def _sanitize_result_value(value, secrets=()):
    from evidence_redaction import redact_text

    if isinstance(value, str):
        return redact_text(value, secrets=secrets)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Production result metadata must be finite JSON data')
        return value
    if isinstance(value, list):
        return [_sanitize_result_value(item, secrets=secrets) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('Production result metadata keys must be strings')
        return {_sanitize_result_value(key, secrets=secrets): _sanitize_result_value(item, secrets=secrets)
                for key, item in value.items()}
    raise ValueError('Production result metadata must be JSON data')


def _result_is_current(run, payload):
    producer = payload.get('producer')
    if not isinstance(producer, dict):
        return False
    stage = producer.get('stage')
    input_fingerprint = producer.get('input_fingerprint')
    if stage not in STAGES or not isinstance(input_fingerprint, str):
        return False
    try:
        state = load_workflow_state(run)
    except (ValueError, OSError, KeyError, TypeError):
        return False
    record = state['stage_records'][stage]
    if record['status'] != 'completed' or record['input_fingerprint'] != input_fingerprint:
        return False
    result_path = _result_path(run)
    try:
        relative = result_path.relative_to(run).as_posix()
        digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False
    return any(stage_record['status'] == 'completed'
               and stage_record['output_files'].get(relative) == digest
               for stage_record in state['stage_records'].values())


def _save_result(run, result, *, producer_stage, input_fingerprint, secrets=()):
    if not isinstance(result, ProductionResult) or result.run_root.resolve() != run.resolve():
        raise ValueError('Production result does not belong to this run')
    if producer_stage not in STAGES or not isinstance(input_fingerprint, str) or not input_fingerprint:
        raise ValueError('Production result requires a producing stage fingerprint')
    inventory = result.inventory
    artifact = result.artifact
    fingerprint = result.fingerprint
    if inventory is None or artifact is None or fingerprint is None:
        raise ValueError('Production result is incomplete')
    payload = {
        'inventory': {'output_dir': str(inventory.output_dir),
                      'files': _sanitize_result_value(inventory.files, secrets=secrets)},
        'artifact': {key: getattr(artifact, key) for key in
                     ('path', 'sha256', 'release_id', 'transaction_mode', 'unit_mapping', 'findings')},
        'fingerprint': {key: getattr(fingerprint, key) for key in
                        ('sha256', 'components', 'schema_version')},
    }
    payload['artifact']['unit_mapping'] = _sanitize_result_value(payload['artifact']['unit_mapping'], secrets=secrets)
    payload['artifact']['findings'] = _sanitize_result_value(payload['artifact']['findings'], secrets=secrets)
    payload['producer'] = {'stage': producer_stage, 'input_fingerprint': input_fingerprint}
    payload['artifact']['path'] = str(payload['artifact']['path'])
    if not _artifact_outputs_match(payload):
        raise ValueError('Production result output evidence is stale')
    from evidence_redaction import assert_safe_evidence, redact_mapping
    payload = redact_mapping(payload, secrets=secrets)
    assert_safe_evidence(payload, secrets=secrets)
    path = _result_path(run)
    encoded = (json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf-8')
    if path.exists():
        old_payload = json.loads(path.read_text(encoding='utf-8'))
        old_result = {key: value for key, value in old_payload.items() if key != 'producer'}
        new_result = {key: value for key, value in payload.items() if key != 'producer'}
        old_is_current = _result_is_current(run, old_payload)
        if old_result != new_result and old_is_current:
            raise ValueError('Durable production result is immutable')
        if old_result == new_result and old_is_current:
            return path
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=run)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def _load_result(run, current_inputs):
    path = _result_path(run)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not _artifact_outputs_match(payload):
        return None
    producer = payload.get('producer')
    state = load_workflow_state(run)
    receipt_stages = [stage for stage in STAGES
                      if path.relative_to(run).as_posix()
                      in state['stage_records'][stage]['output_files']]
    if (not _result_is_current(run, payload)
            or any(state['stage_records'][stage]['input_fingerprint']
                   != _stage_fingerprint(stage, current_inputs[stage])
                   for stage in [producer['stage'], *receipt_stages])):
        return None
    from assemble_deployment_sql import ArtifactRecord
    from render_release_documents import OutputInventory
    fingerprint_module_path = Path(__file__).parents[2] / 'release-docs-review/scripts/review_fingerprint.py'
    spec = importlib.util.spec_from_file_location('release_docs_resume_fingerprint', fingerprint_module_path)
    fingerprint_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fingerprint_module
    spec.loader.exec_module(fingerprint_module)
    inventory_data = payload['inventory']
    artifact_data = payload['artifact']
    fingerprint_data = payload['fingerprint']
    return ProductionResult(
        run, OutputInventory(Path(inventory_data['output_dir']), inventory_data['files']),
        ArtifactRecord(Path(artifact_data['path']), artifact_data['sha256'],
                       artifact_data['release_id'], artifact_data['transaction_mode'],
                       artifact_data['unit_mapping'], artifact_data['findings']),
        {}, [], fingerprint_module.FingerprintRecord(
            fingerprint_data['sha256'], fingerprint_data['components'], fingerprint_data['schema_version']),
        delivery_eligible=False, resumable=True)


def _builtin_production_outputs(run):
    return [run / name for name in ('source_unit_metadata.json',
                                    'lifecycle_exclusion_manifest.json',
                                    'localdb_validation.json')]


def _builtin_production(repo, run, inputs, input_fingerprint, secrets=()):
    request = inputs.get('production_request')
    if not isinstance(request, dict) or request.get('run_root') is None or request.get('repo') is None:
        raise ValueError('A production_request with repo and run_root is required')
    if Path(request['run_root']).resolve() != run.resolve() or Path(request['repo']).resolve() != repo.resolve():
        raise ValueError('Production request ownership mismatch')
    request = dict(request)
    has_request_secrets = 'secrets' in request
    request_secrets = request.get('secrets', ())
    if isinstance(request_secrets, str):
        request_secrets = (request_secrets,)
    if isinstance(secrets, str):
        secrets = (secrets,)
    combined_secrets = (*request_secrets, *secrets)
    if has_request_secrets or request_secrets or secrets:
        request['secrets'] = combined_secrets
    result = produce_release(**request)
    result_file = _save_result(run, result, producer_stage=STAGES[0],
                               input_fingerprint=input_fingerprint, secrets=combined_secrets)
    outputs = _builtin_production_outputs(run)
    if any(not path.is_file() for path in outputs):
        raise ValueError('Production pipeline omitted durable stage evidence')
    outputs.append(result_file)
    return result, outputs


def resume_release(repo, run_root, *, current_inputs, adapters=None, secrets=()) -> ProductionResult:
    """Resume through ``produce_release`` or explicit stage adapters.

    ``current_inputs`` must contain exactly the six workflow stages. The built-in
    production path is selected by ``current_inputs['source_collected']`` containing
    ``production_request``: keyword arguments for the existing ``produce_release``
    API, including the same repository and owned run root. It checkpoints the
    source metadata, fixture/exclusion manifest, and LocalDB receipt produced by
    that safety-checked pipeline and can recover any partial checkpoint within
    those first three stages. Later review/finalization stages can use ``adapters``.

    Each adapter must return non-empty durable ``output_files``. At least one
    completed stage must also return a complete ``ProductionResult`` so the
    resumed return value can reconstruct inventory, artifact, and fingerprint.
    """
    run = Path(run_root).absolute()
    repository = Path(repo).resolve(strict=True)
    if (run.parent.name != 'runs' or run.parent.parent.name != '.release-docs'
            or run.parent.parent.parent.resolve(strict=True) != repository):
        raise ProductionError('preflight', 'production_contract_violation')
    if not isinstance(current_inputs, dict) or set(current_inputs) != set(STAGES):
        raise ProductionError('preflight', 'production_contract_violation')
    if any(not isinstance(current_inputs[stage], dict) for stage in STAGES):
        raise ProductionError('preflight', 'production_contract_violation')
    handlers = adapters or {}
    if not isinstance(handlers, dict):
        raise ProductionError('preflight', 'production_contract_violation')
    try:
        state = load_workflow_state(run)
        stage = resume_checkpoint(run, state['workflow_fingerprint'])
        state = load_workflow_state(run)
        checkpoint = STAGES.index(stage)
        completed = {name for name in STAGES[:checkpoint]
                     if state['stage_records'][name]['status'] == 'completed'}
        # A fingerprint change at a completed stage invalidates that stage and
        # downstream state before its adapter is called.
        for name in STAGES:
            stage_inputs = current_inputs[name]
            fingerprint = _stage_fingerprint(name, stage_inputs)
            record = state['stage_records'][name]
            if name in completed and record['input_fingerprint'] != fingerprint:
                state = invalidate_from(run, name, 'Stage input fingerprint changed', secrets=secrets)
                checkpoint = STAGES.index(name)
                completed = {prior for prior in STAGES[:checkpoint]
                             if state['stage_records'][prior]['status'] == 'completed'}
                break

        if ('production_request' in current_inputs[STAGES[0]]
                and _result_path(run).exists()
                and _load_result(run, current_inputs) is None):
            state = invalidate_from(run, STAGES[0], 'Production result evidence changed', secrets=secrets)
            completed.clear()

        if (all(state['stage_records'][name]['status'] == 'completed' for name in STAGES)
                and all(state['stage_records'][name]['input_fingerprint']
                        == _stage_fingerprint(name, current_inputs[name])
                        for name in STAGES)):
            statuses = {name: 'completed' for name in STAGES}
            result = _load_result(run, current_inputs)
            if result is None:
                state = invalidate_from(run, STAGES[0], 'Production result evidence changed', secrets=secrets)
                completed.clear()
            else:
                result.stage_statuses = statuses
                return result

        results = []
        for name in STAGES:
            state = load_workflow_state(run)
            if state['stage_records'][name]['status'] == 'completed':
                continue
            if name in completed:
                continue
            stage = name
            stage_inputs = current_inputs[name]
            fingerprint = _stage_fingerprint(name, stage_inputs)
            if (name in STAGES[:3]
                    and 'production_request' in current_inputs[STAGES[0]]):
                if state['stage_records'][name]['status'] != 'completed':
                    record_stage(run, name, status='running', input_fingerprint=fingerprint,
                                 secrets=secrets)
                try:
                    result, outputs = _builtin_production(
                        repository, run, current_inputs[STAGES[0]],
                        _stage_fingerprint(STAGES[0], current_inputs[STAGES[0]]), secrets=secrets)
                    for pipeline_stage, output in zip(STAGES[:2], outputs[:2]):
                        pipeline_state = load_workflow_state(run)
                        if pipeline_state['stage_records'][pipeline_stage]['status'] == 'completed':
                            continue
                        record_stage(run, pipeline_stage, status='completed',
                                     input_fingerprint=_stage_fingerprint(
                                         pipeline_stage, current_inputs[pipeline_stage]),
                                     output_files=[output], secrets=secrets)
                    pipeline_state = load_workflow_state(run)
                    if pipeline_state['stage_records'][STAGES[2]]['status'] != 'completed':
                        record_stage(run, STAGES[2], status='completed',
                                     input_fingerprint=_stage_fingerprint(
                                         STAGES[2], current_inputs[STAGES[2]]),
                                     output_files=outputs[2:], secrets=secrets)
                    results.append({'result': result})
                    continue
                except Exception as error:
                    if load_workflow_state(run)['stage_records'][name]['status'] != 'completed':
                        record_stage(run, name, status='failed', input_fingerprint=fingerprint,
                                     error_summary='stage_execution_failed', secrets=secrets)
                    if isinstance(error, ProductionError):
                        raise
                    raise ProductionError(name, 'production_contract_violation') from error
            handler = handlers.get(name)
            if not callable(handler):
                saved_result = _result_value(results) or _load_result(run, current_inputs)
                if saved_result is not None:
                    if not _result_outputs_match(saved_result):
                        invalidate_from(run, STAGES[0], 'Production result evidence changed', secrets=secrets)
                        raise ProductionError('preflight', 'durable_production_result_missing')
                    state = load_workflow_state(run)
                    statuses = {stage_name: state['stage_records'][stage_name]['status']
                                for stage_name in STAGES}
                    findings = ([{'code': 'semantic_review_pending', 'status': '待確認'}]
                                if statuses[STAGES[3]] != 'completed' else [])
                    saved_result.stage_statuses = statuses
                    saved_result.findings = findings
                    return saved_result
                raise ProductionError(name, 'stage_adapter_unavailable')
            record_stage(run, name, status='running', input_fingerprint=fingerprint,
                         secrets=secrets)
            try:
                output = handler(run, stage_inputs)
                if not isinstance(output, dict):
                    raise ValueError('Invalid stage result')
                files = output.get('output_files', ())
                if isinstance(files, (str, Path)):
                    files = (files,)
                files = tuple(files)
                if not files:
                    raise ValueError('A completed stage requires durable output files')
                output_result = output.get('result')
                if output_result is not None:
                    result_file = _save_result(run, output_result, producer_stage=name,
                                               input_fingerprint=fingerprint, secrets=secrets)
                    files = (*files, result_file)
                record_stage(run, name, status='completed', input_fingerprint=fingerprint,
                             output_files=files, secrets=secrets)
                results.append(output)
            except Exception as error:
                # External exception text can contain credentials or SQL literals.
                record_stage(run, name, status='failed', input_fingerprint=fingerprint,
                             error_summary='stage_execution_failed', secrets=secrets)
                if isinstance(error, ProductionError):
                    raise
                raise ProductionError(name, 'production_contract_violation') from error

        state = load_workflow_state(run)
        prior_result = _result_value(results) or _load_result(run, current_inputs)
        statuses = {name: state['stage_records'][name]['status'] for name in STAGES}
        findings = ([{'code': 'semantic_review_pending', 'status': '待確認'}]
                    if statuses['semantic_review_passed'] != 'completed' else [])
        if prior_result is None:
            raise ProductionError(stage, 'durable_production_result_missing')
        if not _result_outputs_match(prior_result):
            invalidate_from(run, STAGES[0], 'Production result evidence changed', secrets=secrets)
            raise ProductionError('preflight', 'durable_production_result_missing')
        return ProductionResult(run, prior_result.inventory, prior_result.artifact, statuses,
                                findings or prior_result.findings, prior_result.fingerprint,
                                delivery_eligible=False, resumable=True)
    except ProductionError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        raise ProductionError(stage if 'stage' in locals() else 'preflight',
                              'production_contract_violation') from error

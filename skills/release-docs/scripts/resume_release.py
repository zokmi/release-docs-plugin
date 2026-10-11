"""Resume an owned release production run from its first incomplete stage."""
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path

from produce_release import ProductionError, ProductionResult
from workflow_state import STAGES, load_workflow_state, record_stage, resume_checkpoint


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


def resume_release(repo, run_root, *, current_inputs, adapters=None) -> ProductionResult:
    """Run each incomplete stage in order, reusing only verified durable outputs.

    ``current_inputs`` maps stage names to their fingerprinted input mappings.
    ``adapters`` maps stage names to ``(run_root, stage_inputs)`` callables that
    return a mapping with ``output_files`` and optional ``result`` values.
    """
    run = Path(run_root).absolute()
    repository = Path(repo).resolve(strict=True)
    if (run.parent.name != 'runs' or run.parent.parent.name != '.release-docs'
            or run.parent.parent.parent.resolve(strict=True) != repository):
        raise ProductionError('preflight', 'production_contract_violation')
    if not isinstance(current_inputs, dict) or not current_inputs:
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
            stage_inputs = current_inputs.get(name, {})
            fingerprint = _stage_fingerprint(name, stage_inputs)
            record = state['stage_records'][name]
            if name in completed and record['input_fingerprint'] != fingerprint:
                from workflow_state import invalidate_from
                state = invalidate_from(run, name, 'Stage input fingerprint changed')
                checkpoint = STAGES.index(name)
                completed = {prior for prior in STAGES[:checkpoint]
                             if state['stage_records'][prior]['status'] == 'completed'}
                break

        if (all(state['stage_records'][name]['status'] == 'completed' for name in STAGES)
                and all(state['stage_records'][name]['input_fingerprint']
                        == _stage_fingerprint(name, current_inputs.get(name, {}))
                        for name in STAGES)):
            statuses = {name: 'completed' for name in STAGES}
            return ProductionResult(run, None, None, statuses, [],
                                    delivery_eligible=False, resumable=True)

        results = []
        for name in STAGES:
            if name in completed:
                continue
            stage = name
            stage_inputs = current_inputs.get(name, {})
            fingerprint = _stage_fingerprint(name, stage_inputs)
            handler = handlers.get(name)
            if not callable(handler):
                raise ProductionError(name, 'stage_adapter_unavailable')
            record_stage(run, name, status='running', input_fingerprint=fingerprint)
            try:
                output = handler(run, stage_inputs)
                if not isinstance(output, dict):
                    raise ValueError('Invalid stage result')
                files = output.get('output_files', ())
                if isinstance(files, (str, Path)):
                    files = (files,)
                record_stage(run, name, status='completed', input_fingerprint=fingerprint,
                             output_files=files)
                results.append(output)
            except Exception as error:
                # External exception text can contain credentials or SQL literals.
                record_stage(run, name, status='failed', input_fingerprint=fingerprint,
                             error_summary='stage_execution_failed')
                if isinstance(error, ProductionError):
                    raise
                raise ProductionError(name, 'production_contract_violation') from error

        state = load_workflow_state(run)
        prior_result = _result_value(results)
        statuses = {name: state['stage_records'][name]['status'] for name in STAGES}
        findings = ([{'code': 'semantic_review_pending', 'status': '待確認'}]
                    if statuses['semantic_review_passed'] != 'completed' else [])
        if prior_result is None:
            return ProductionResult(run, None, None, statuses, findings,
                                    delivery_eligible=False, resumable=True)
        return ProductionResult(run, prior_result.inventory, prior_result.artifact, statuses,
                                findings or prior_result.findings, prior_result.fingerprint,
                                delivery_eligible=False, resumable=True)
    except ProductionError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        raise ProductionError(stage if 'stage' in locals() else 'preflight',
                              'production_contract_violation') from error

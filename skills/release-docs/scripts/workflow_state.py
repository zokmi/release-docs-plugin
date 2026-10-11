"""Atomic, owned checkpoints for a release evidence run."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

STAGES = ('source_collected', 'fixture_ready', 'local_validation_passed',
          'semantic_review_passed', 'report_finalized', 'delivery_finalized')
SCHEMA_VERSION = 2
FILE = 'workflow_state.json'
STAGE_STATUSES = {'pending', 'running', 'completed', 'failed', 'interrupted', 'invalidated'}
RUN_STATUSES = {'running', 'failed', 'interrupted', 'finalized'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _owned(run_root, *, require_lock=True):
    from artifact_lifecycle import owned
    run = Path(run_root).absolute()
    if '..' in Path(run_root).parts or len(run.parents) < 3:
        raise ValueError('Unsafe run path')
    _, run, manifest = owned(run.parents[2], run)
    if manifest['status'] == 'finalized':
        raise ValueError('Finalized run')
    if require_lock and not (run / '.lock').is_file():
        raise ValueError('Missing run lock')
    return run, manifest


def _write(run, state):
    encoded = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix=FILE + '.', suffix='.tmp', dir=run)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, run / FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(run):
    path = run / FILE
    if not path.is_file():
        raise ValueError('Compatible workflow state required')
    state = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(state, dict) or state.get('schema_version') != SCHEMA_VERSION
            or state.get('run_id') != run.name or state.get('stages') != list(STAGES)
            or state.get('status') not in RUN_STATUSES
            or state.get('current_stage') not in STAGES
            or not isinstance(state.get('workflow_fingerprint'), str)
            or not state['workflow_fingerprint']):
        raise ValueError('Incompatible workflow schema')
    records = state.get('stage_records')
    attempts = state.get('attempts')
    if (not isinstance(records, dict) or not isinstance(attempts, dict)
            or set(records) != set(STAGES) or set(attempts) != set(STAGES)):
        raise ValueError('Incompatible workflow schema')
    for stage in STAGES:
        record = records.get(stage)
        if (not isinstance(record, dict) or record.get('status') not in STAGE_STATUSES
                or not isinstance(record.get('output_files'), dict)
                or not isinstance(record.get('input_fingerprint'), str)
                or not isinstance(record.get('error_summary'), str)
                or any(record.get(key) is not None and not isinstance(record[key], str)
                       for key in ('started_at', 'completed_at'))
                or type(attempts.get(stage)) is not int or attempts[stage] < 0):
            raise ValueError('Incompatible workflow schema')
        for name, digest in record['output_files'].items():
            if not isinstance(name, str) or not name or not isinstance(digest, str):
                raise ValueError('Invalid output inventory')
            relative = Path(name)
            if (relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name
                    or name in (FILE, 'run.json', '.lock')
                    or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('Invalid output inventory')
    return state


def initialize_workflow_state(run_root, run_id, workflow_fingerprint, stages):
    run, _ = _owned(run_root)
    if (run_id != run.name or list(stages) != list(STAGES)
            or not isinstance(workflow_fingerprint, str) or not workflow_fingerprint):
        raise ValueError('Invalid workflow identity or stages')
    if (run / FILE).exists():
        raise ValueError('Workflow state already exists')
    now = _now()
    state = {'schema_version': SCHEMA_VERSION, 'run_id': run_id,
             'workflow_fingerprint': workflow_fingerprint, 'status': 'running',
             'current_stage': STAGES[0], 'stages': list(STAGES),
             'attempts': {stage: 0 for stage in STAGES},
             'created_at': now, 'updated_at': now,
             'stage_records': {stage: {'status': 'pending', 'input_fingerprint': '',
                                       'output_files': {}, 'error_summary': '',
                                       'started_at': None, 'completed_at': None}
                               for stage in STAGES}}
    _write(run, state)
    return state


def load_workflow_state(run_root):
    run, _ = _owned(run_root, require_lock=False)
    return _read(run)


def _hash_output(run, output):
    requested = Path(output)
    if '..' in requested.parts:
        raise ValueError('Unsafe output path')
    path = requested if requested.is_absolute() else run / requested
    try:
        relative = path.relative_to(run)
    except ValueError:
        raise ValueError('Output outside owned run')
    if relative.as_posix() in (FILE, 'run.json', '.lock'):
        raise ValueError('Invalid output path')
    for candidate in (path, *path.parents):
        if candidate == run.parent:
            break
        if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
            raise ValueError('Linked output path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Output must be an unaliased regular file')
    return relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def _invalidate(state, stage, reason):
    for name in STAGES[STAGES.index(stage):]:
        record = state['stage_records'][name]
        record.update(status='invalidated', output_files={}, error_summary=reason,
                      completed_at=None)
    state['current_stage'] = next(name for name in STAGES
                                  if state['stage_records'][name]['status'] != 'completed')
    state['status'] = 'running'
    state['updated_at'] = _now()


def invalidate_from(run_root, stage, reason):
    run, _ = _owned(run_root)
    state = _read(run)
    if state['status'] == 'finalized' or stage not in STAGES or not isinstance(reason, str):
        raise ValueError('Invalid stage or finalized run')
    _invalidate(state, stage, reason)
    _write(run, state)
    return state


def record_stage(run_root, stage, *, status, input_fingerprint, output_files=(), error_summary=''):
    run, _ = _owned(run_root)
    state = _read(run)
    if (state['status'] == 'finalized' or stage not in STAGES
            or status not in {'running', 'completed', 'failed', 'interrupted'}
            or not isinstance(error_summary, str)
            or not isinstance(input_fingerprint, str) or not input_fingerprint):
        raise ValueError('Invalid stage transition')
    index = STAGES.index(stage)
    if any(state['stage_records'][prior]['status'] != 'completed' for prior in STAGES[:index]):
        raise ValueError('Earlier stage incomplete')
    for prior in STAGES[:index]:
        if not _outputs_match(run, state['stage_records'][prior]):
            _invalidate(state, prior, 'Output hash changed')
            _write(run, state)
            raise ValueError('Earlier stage output changed')
    outputs = dict(_hash_output(run, output) for output in output_files)
    record = state['stage_records'][stage]
    if record['status'] == 'completed':
        if (record['input_fingerprint'] == input_fingerprint
                and record['output_files'] == outputs and status == 'completed'):
            return state
        _invalidate(state, stage, 'Stage input or output changed')
        record = state['stage_records'][stage]
    if record['status'] != 'running':
        state['attempts'][stage] += 1
        record['started_at'] = _now()
    elif record['input_fingerprint'] != input_fingerprint:
        raise ValueError('Running stage input changed')
    record.update(status=status, input_fingerprint=input_fingerprint,
                  output_files=outputs, error_summary=error_summary,
                  completed_at=_now() if status == 'completed' else None)
    state['status'] = 'running' if status in {'running', 'completed'} else status
    state['current_stage'] = (STAGES[index + 1] if status == 'completed' and index + 1 < len(STAGES)
                              else stage)
    state['updated_at'] = _now()
    _write(run, state)
    return state


def _outputs_match(run, record):
    try:
        return dict(_hash_output(run, name) for name in record['output_files']) == record['output_files']
    except (OSError, ValueError):
        return False


def resume_checkpoint(run_root, current_fingerprint):
    run, _ = _owned(run_root)
    state = _read(run)
    if state['status'] == 'finalized' or not isinstance(current_fingerprint, str) or not current_fingerprint:
        raise ValueError('Finalized run or invalid fingerprint')
    if state['workflow_fingerprint'] != current_fingerprint:
        _invalidate(state, STAGES[0], 'Workflow fingerprint changed')
        state['workflow_fingerprint'] = current_fingerprint
        _write(run, state)
        return STAGES[0]
    for stage in STAGES:
        record = state['stage_records'][stage]
        if record['status'] != 'completed':
            return stage
        if not _outputs_match(run, record):
            _invalidate(state, stage, 'Output hash changed')
            _write(run, state)
            return stage
    return STAGES[-1]


def mark_workflow_status(run_root, status):
    run, _ = _owned(run_root)
    state = _read(run)
    if status not in {'failed', 'interrupted', 'finalized'} or state['status'] == 'finalized':
        raise ValueError('Invalid workflow status')
    if status == 'finalized' and state['stage_records'][STAGES[-1]]['status'] != 'completed':
        raise ValueError('Delivery stage incomplete')
    if status in {'failed', 'interrupted'}:
        record = state['stage_records'][state['current_stage']]
        if record['status'] != 'completed':
            record['status'] = status
    state['status'] = status
    state['updated_at'] = _now()
    _write(run, state)
    return state

"""Controlled production sequence; never manufactures semantic or deployment success."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
import subprocess
import importlib.util
import sys
from pathlib import Path

from assemble_deployment_sql import assemble_deployment_sql, _validate_units
from lifecycle_store import write_lifecycle_run
from parameter_metadata import sanitize_parameter_changes
from render_release_documents import render_release_documents, _plain_path, KINDS, OutputInventory
from run_local_validation import run_local_validation
from derived_sources import verify_source


class ProductionError(ValueError):
    def __init__(self, stage, code):
        self.stage = stage
        self.code = code
        super().__init__(f'{stage}: {code}')


@dataclass
class ProductionResult:
    run_root: Path
    inventory: OutputInventory
    artifact: object
    stage_statuses: dict
    findings: list
    fingerprint: object = None
    delivery_eligible: bool = False


def _immutable_copy(source, destination):
    source, destination = _plain_path(source), _plain_path(destination)
    if not source.is_file():
        raise ValueError('Missing permanent input')
    data = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError('Immutable evidence differs; create a new run')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(data)
    return destination


def produce_release(repo, evidence, analysis, *, release_id, run_root, output_dir,
                    baseline_source, fixture_source=None, fixture_manifest=None,
                    validation_options=None, parent_run_id=None):
    stage = 'preflight'
    try:
        repo, run, output = _plain_path(repo), _plain_path(run_root), _plain_path(output_dir)
        if (run.parent.name != 'runs' or run.parent.parent.name != '.release-docs'
                or not run.is_relative_to(repo)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run.name)):
            raise ValueError('Invalid run')
        if ('.release-docs' in [p.casefold() for p in output.parts]
                or any([p.casefold() for p in output.parts][i:i+2] == ['docs', 'release-artifacts']
                       for i in range(len(output.parts)))):
            raise ValueError('Invalid operator output')
        if output.exists() and (not output.is_dir() or any(
                _plain_path(p).name not in ('00_上線指引.md', '01_部署SQL.sql', '02_參數異動.md')
                or not p.is_file() for p in output.iterdir())):
            raise ValueError('Undeclared output')
        if analysis.blocked:
            raise ValueError('Blocked analysis')
        scope = analysis.source_scope
        if (any(scope.get(k) != evidence.get(k) for k in scope)
                or any(not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', str(scope.get(k, '')))
                       for k in ('base_sha', 'target_sha'))
                or scope.get('diff_mode') not in ('direct', 'merge-base')
                or scope.get('workspace_policy') != 'excluded'):
            raise ValueError('Unconfirmed scope; worktree inclusion requires pinned evidence')
        clean = deepcopy(analysis)
        for revision in (scope['base_sha'], scope['target_sha']):
            resolved = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}'],
                                      capture_output=True, check=True).stdout.decode().strip()
            if resolved != revision:
                raise ValueError('Pinned revision mismatch')
        for unit in clean.units:
            path = unit.get('source_path', '')
            if (not isinstance(path, str) or not path or '\\' in path or ':' in path
                    or Path(path).is_absolute() or '..' in Path(path).parts
                    or unit.get('source_revision') not in (scope['base_sha'], scope['target_sha'])):
                raise ValueError('Unpinned source unit')
            if unit.get('source_type') == 'derived_artifact':
                raw = verify_source(repo, run, unit, scope)
            else:
                raw = subprocess.run(['git', '-C', str(repo), 'show', unit['source_revision'] + ':' + path],
                                     capture_output=True, check=True).stdout
            if hashlib.sha256(raw).hexdigest() != unit.get('source_hash'):
                raise ValueError('Source hash mismatch')
        clean.parameter_changes = sanitize_parameter_changes(clean.parameter_changes)
        if type(clean.parameters_applicable) is not bool or clean.parameters_applicable != bool(clean.parameter_changes):
            raise ValueError('Unknown or conflicting parameter applicability')
        if parent_run_id is not None and (not isinstance(parent_run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', parent_run_id)):
            raise ValueError('Invalid parent run')
        excluded = {uid for entry in clean.exclusions for uid in entry['unit_ids']}
        ids = {u['unit_id'] for u in clean.units}
        if not excluded <= ids:
            raise ValueError('Unknown excluded unit')
        included = [u for u in clean.units if u['unit_id'] not in excluded]
        _validate_units(included)
        for unit in included:
            if unit['phase'] in ('SCHEMA', 'REPAIR'):
                descriptions = [c for c in clean.structure_changes if c.get('unit_id') == unit['unit_id']]
                descriptions += unit.get('structure_changes', [])
                if not descriptions or any(c.get('kind') not in KINDS or any(
                        not isinstance(c.get(k), str) or not c[k].strip()
                        for k in ('name', 'description', 'impact')) for c in descriptions):
                    raise ValueError('Missing structure explanation')
            if unit['phase'] == 'DATA':
                assertions = unit.get('expected_assertions')
                if (not isinstance(assertions, list) or not assertions
                        or any(not isinstance(a, dict) or not a.get('id') or not a.get('seed_row_id')
                               or not a.get('case') or not isinstance(a.get('expected_by_round'), dict)
                               or any(not isinstance(a['expected_by_round'].get(r), dict)
                                      or set(a['expected_by_round'][r]) != {'before', 'after'}
                                      for r in ('validate_only', 'commit', 'rerun', 'injected_failure')) for a in assertions)
                        or len({a['id'] for a in assertions}) != len(assertions)):
                    raise ValueError('Missing DATA expectations')
        baseline = _plain_path(baseline_source)
        if not baseline.is_file() or baseline.suffix.lower() != '.sql':
            raise ValueError('A materialized baseline SQL is required')
        if clean.baseline.get('source_hash') != hashlib.sha256(baseline.read_bytes()).hexdigest():
            raise ValueError('Baseline identity mismatch')
        for source, suffix in ((fixture_source, '.sql'), (fixture_manifest, '.json')):
            if source is not None and (not _plain_path(source).is_file() or Path(source).suffix.lower() != suffix):
                raise ValueError('Missing fixture input')
        options = dict(validation_options or {})
        allowed = {'executor', 'command', 'provider_version', 'tool_version', 'adapter_provenance'}
        if set(options) - allowed:
            raise ValueError('Unsupported validation options')
        if options.get('executor') is not None and (run / 'lifecycle_metadata.json').exists():
            raise ValueError('New validation requires a new run')
        stage = 'assembly'
        # Assemble in owned scratch; an existing permanent artifact is never overwritten.
        scratch = _plain_path(run / 'temporary/assembly/01_部署SQL.sql')
        artifact = assemble_deployment_sql(included, scratch, {'release_id': release_id})
        artifact.path = _immutable_copy(artifact.path, run / 'assembly/01_部署SQL.sql')
        stage = 'permanent_inputs'
        baseline = _immutable_copy(baseline, run / 'baseline.sql')
        fixture = _immutable_copy(fixture_source, run / 'fixture.sql') if fixture_source else None
        manifest = _immutable_copy(fixture_manifest, run / 'fixture.json') if fixture_manifest else None
        clean.baseline['source_path'] = str(baseline)
        stage = 'validation'
        localdb = run_local_validation(artifact.path, server='(localdb)\\MSSQLLocalDB', database=release_id,
                    baseline_source=str(baseline), fixture_source=str(fixture or ''),
                    fixture_manifest=manifest, data_units=[u for u in included if u['phase'] == 'DATA'], **options)
        stage = 'lifecycle'
        lifecycle = write_lifecycle_run(run, clean, localdb_validation=localdb,
                    execution_artifact={'path': 'assembly/01_部署SQL.sql', 'sha256': artifact.sha256},
                    operator_contract={'parameters_applicable': clean.parameters_applicable},
                    parent_run_id=parent_run_id)
        stage = 'render'
        inventory = render_release_documents(clean, artifact, lifecycle, output)
        stage = 'fingerprint'
        spec = importlib.util.spec_from_file_location('release_docs_production_fingerprint',
                    Path(__file__).parents[2] / 'release-docs-review/scripts/review_fingerprint.py')
        review = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = review
        spec.loader.exec_module(review)
        fingerprint = review.review_fingerprint(repo, output, run, clean.source_scope)
        return ProductionResult(run, inventory, artifact,
                    {'production': 'produced', 'semantic_review': 'pending', 'deployment_validation': localdb['status']},
                    [{'code': 'semantic_review_pending', 'status': '待確認'}], fingerprint)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError) as error:
        raise ProductionError(stage, 'production_contract_violation') from error

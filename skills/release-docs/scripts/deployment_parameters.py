"""Bounded deployment discovery from caller-pinned JSON/dotenv bytes.

No disk reads, shell evaluation, YAML guessing, logging or proof verification.
Callers must verify provider proof hashes against pinned consumer code before
calling discovery, persist its provider role, and revalidate before producing.
An absent baseline is explicitly {} with source_reference.base=None; omission
or None is unknown. Raw literal values are retained only in returned memory.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import PurePath
import re


@dataclass
class DeploymentDiscoveryResult:
    changes: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)


def _fail():
    raise ValueError('Deployment evidence is unsupported, ambiguous or nonliteral')


def _variables(items):
    result = {}
    for name, value in items:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            _fail()
        if not isinstance(value, str) or '$' in value or '`' in value or '\x00' in value:
            _fail()
        if name in result and result[name] != value:
            _fail()
        result[name] = value
    # Logical keys are case-insensitive; ancestors cannot also be leaves.
    logical = []
    spellings = {}
    for name in result:
        if '__' not in name:
            continue
        parts = name.split('__')
        if any(not part or ':' in part for part in parts):
            _fail()
        key = tuple(part.casefold() for part in parts)
        for index, part in enumerate(parts):
            prefix = key[:index + 1]
            if prefix in spellings and spellings[prefix] != part:
                _fail()
            spellings[prefix] = part
        if any(key == old or key[:len(old)] == old or old[:len(key)] == key for old in logical):
            _fail()
        logical.append(key)
    return {name: value for name, value in result.items() if '__' in name}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def _environment(value):
    if isinstance(value, dict):
        return _variables(value.items())
    if isinstance(value, list):
        pairs = []
        for item in value:
            if not isinstance(item, str) or '=' not in item:
                _fail()
            pairs.append(item.split('=', 1))
        return _variables(pairs)
    _fail()


def _select(items, service):
    if not items or not all(isinstance(item, dict) for item in items):
        _fail()
    if service is not None:
        items = [item for item in items if item.get('name') == service]
    if len(items) != 1:
        _fail()
    return items[0]


def parse_deployment_source(source):
    """Return only __ assignments from a path plus pinned content/bytes/data.

    JSON supports a direct variable map, Compose services.environment, and
    Kubernetes spec[.template.spec].containers.env. A service can select one
    explicitly named container/service; otherwise multiple owners block.
    Selected owners with env_file, extends or envFrom fail closed, including empty values.
    Unsupported inputs raise ValueError without echoing content.
    """
    try:
        if not isinstance(source, dict) or not isinstance(source.get('path'), str):
            _fail()
        path = PurePath(source['path'])
        content = source.get('content', source.get('bytes', source.get('data')))
        if isinstance(content, bytes):
            content = content.decode('utf-8-sig')
        if not isinstance(content, str):
            _fail()
        if path.name == '.env' or path.name.startswith('.env.'):
            pairs = []
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)', line)
                if not match:
                    _fail()
                name, value = match.groups()
                if value.startswith(('"', "'")):
                    quote = value[0]
                    quoted = re.fullmatch(re.escape(quote) + '(.*?)' + re.escape(quote) + r'\s*(?:#.*)?', value)
                    if not quoted or '\\' in quoted[1]:
                        _fail()
                    value = quoted[1]
                else:
                    value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
                    if re.search(r'[\s\'";|&<>\\]', value):
                        _fail()
                pairs.append((name, value))
            return _variables(pairs)
        if path.suffix.lower() != '.json':
            _fail()
        document = json.loads(content, object_pairs_hook=_pairs)
        if not isinstance(document, dict):
            _fail()
        if 'services' in document:
            services = document['services']
            if not isinstance(services, dict):
                _fail()
            owners = [dict(value, name=name) for name, value in services.items() if isinstance(value, dict)]
            if len(owners) != len(services):
                _fail()
            owner = _select(owners, source.get('service'))
            if 'env_file' in owner or 'extends' in owner:
                _fail()
            return _environment(owner['environment'])
        if 'spec' in document:
            spec = document['spec']
            if 'template' in spec:
                spec = spec['template']['spec']
            containers = spec['containers']
            if not isinstance(containers, list):
                _fail()
            owner = _select(containers, source.get('service'))
            if 'envFrom' in owner:
                _fail()
            env = owner['env']
            if not isinstance(env, list):
                _fail()
            pairs = []
            for item in env:
                if not isinstance(item, dict) or set(item) != {'name', 'value'}:
                    _fail()
                pairs.append((item['name'], item['value']))
            return _variables(pairs)
        return _environment(document)
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        raise ValueError('Deployment evidence is unsupported, ambiguous or nonliteral') from None


def _reference(value):
    return isinstance(value, dict) and all(isinstance(value.get(key), str) and value[key].strip()
                                         for key in ('path', 'revision', 'source_hash'))


def discover_deployment_changes(deployment_sources, consumer_sources=()):
    """Compare reviewed literal maps, blocking unknown baselines/proof/scope.

    Provider precedence accepts the reviewed proof shape, never a boolean.
    Findings contain fixed reasons only. Every blocked source emits no changes.
    """
    result = DeploymentDiscoveryResult()
    for source in deployment_sources:
        try:
            if not isinstance(source, dict):
                _fail()
            proof = source.get('provider_precedence')
            if not (isinstance(proof, dict) and proof.get('conclusion') == 'passed'
                    and isinstance(proof.get('reason'), str) and proof['reason'].strip()
                    and _reference(proof.get('source_reference'))):
                raise ValueError('Reviewed provider precedence proof is missing')
            before = source.get('base_environment_variables')
            after = source.get('environment_variables')
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValueError('Known baseline and target variable maps are required')
            before, after = _variables(before.items()), _variables(after.items())
            # Check aliases across revisions too, rather than interpreting a rename.
            _variables([(name, '') for name in set(before) | set(after)])
            refs = source.get('source_reference')
            if not isinstance(refs, dict) or not all(role in refs for role in ('base', 'target')):
                raise ValueError('Pinned base and target references are required')
            for role, variables in (('base', before), ('target', after)):
                if refs[role] is None:
                    if variables:
                        raise ValueError('Absent source cannot contain assignments')
                elif not _reference(refs[role]):
                    raise ValueError('Pinned source metadata is incomplete')
            if not isinstance(source.get('path'), str) or not source['path'].strip():
                raise ValueError('Deployment source path is required')
            matches = [c for c in consumer_sources if c.get('path') == source['path']]
            scope = {}
            for key in ('environment', 'service'):
                candidates = {s[key] for s in [source, *matches]
                              if isinstance(s.get(key), str) and s[key].strip()}
                if len(candidates) != 1:
                    raise ValueError('Deployment scope is missing or conflicting')
                scope[key] = candidates.pop()
            for variable in sorted(set(before) | set(after)):
                if variable in before and variable in after and before[variable] == after[variable]:
                    continue
                parts = variable.split('__')
                config = {}
                if variable in after:
                    config = after[variable]
                    for part in reversed(parts):
                        config = {part: config}
                descriptor = dict(scope, key=':'.join(parts), key_segments=parts,
                                  configuration_provider='environment', environment_variable=variable,
                                  target_config=config, source_reference=deepcopy(refs),
                                  provider_precedence=deepcopy(proof),
                                  change='add' if variable not in before else 'remove' if variable not in after else 'update')
                if variable in before:
                    descriptor['old_value'] = before[variable]
                if variable in after:
                    descriptor['new_value'] = after[variable]
                result.changes.append(descriptor)
        except (ValueError, TypeError, AttributeError):
            result.findings.append({'blocking': True,
                                    'message': 'Deployment evidence unresolved: proof, baseline, scope or literal syntax requires review'})
    return result

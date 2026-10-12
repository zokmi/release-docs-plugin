"""Compare caller-pinned configuration sources and retain their provenance."""
from dataclasses import dataclass, field
from copy import deepcopy
import json
import re
import xml.etree.ElementTree as ET
from deployment_parameters import discover_deployment_changes


_MISSING = object()


@dataclass
class ParameterDiscoveryResult:
    changes: list[dict] = field(default_factory=list)
    checked_sources: list[dict] = field(default_factory=list)
    applicable: bool | None = None
    findings: list[dict] = field(default_factory=list)


def _flatten(value, prefix=()):
    if isinstance(value, dict):
        if not value and prefix:
            yield prefix, value
        for key in sorted(value):
            yield from _flatten(value[key], (*prefix, key))
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for index, item in enumerate(value):
            yield from _flatten(item, (*prefix, index))
    else:
        yield prefix, value


def _logical_key(segments):
    return ':'.join(str(part) for part in segments)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate configuration key: {key}')
        result[key] = value
    return result


def _xml_document(text):
    if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('DTD and entity declarations are unsupported')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError(f'Invalid XML: {error}') from error
    if any('}' in element.tag or ':' in element.tag for element in root.iter()):
        raise ValueError('Qualified XML configuration tags are unsupported')
    local = lambda tag: tag
    if local(root.tag) != 'configuration' or root.attrib:
        raise ValueError('Expected an unqualified configuration root without attributes')
    result = {}
    sections = set()
    for section in root:
        name = local(section.tag)
        if name not in ('appSettings', 'connectionStrings') or name in sections or section.attrib:
            raise ValueError('Unsupported or duplicate XML configuration section / external source')
        sections.add(name)
        values = {}
        key_attr, value_attr = ('key', 'value') if name == 'appSettings' else ('name', 'connectionString')
        for entry in section:
            operation = local(entry.tag)
            if len(entry) or (entry.text and entry.text.strip()):
                raise ValueError('Unsupported XML dictionary entry content')
            if operation in ('clear', 'remove'):
                raise ValueError('XML clear/remove inheritance semantics are unsupported without inherited configuration evidence')
            allowed = {key_attr, value_attr} | ({'providerName'} if name == 'connectionStrings' else set())
            if operation != 'add' or not {key_attr, value_attr} <= set(entry.attrib) or not set(entry.attrib) <= allowed:
                raise ValueError('Unsupported XML dictionary operation or attributes')
            key = entry.attrib[key_attr]
            if any(candidate.casefold() == key.casefold() for candidate in values):
                raise ValueError(f'Duplicate configuration key: {key}')
            if name == 'connectionStrings':
                values[key] = {'ConnectionString': entry.attrib[value_attr]}
                if 'providerName' in entry.attrib:
                    values[key]['ProviderName'] = entry.attrib['providerName']
            else:
                values[key] = entry.attrib[value_attr]
        if (section.text and section.text.strip()) or any(entry.tail and entry.tail.strip() for entry in section):
            raise ValueError('Unsupported XML section text')
        if name == 'appSettings':
            if any(key.casefold() == existing.casefold() for key in values for existing in result):
                raise ValueError('Duplicate XML configuration key')
            result.update(values)
        elif values:
            if any(key.casefold() == 'connectionstrings' for key in result):
                raise ValueError('Duplicate ConnectionStrings key')
            result['ConnectionStrings'] = values
    if (root.text and root.text.strip()) or any(section.tail and section.tail.strip() for section in root):
        raise ValueError('Unsupported XML configuration text')
    return result


def _provider(source):
    value = source.get('content', source.get('bytes', source.get('data')))
    if isinstance(value, bytes):
        value = value.decode('utf-8-sig')
    return 'xml' if str(source.get('path', '')).lower().endswith('.config') or isinstance(value, str) and value.lstrip('\ufeff \t\r\n').startswith('<') else 'json'


def parse_configuration_source(source):
    """Parse pinned JSON or XML appSettings/connectionStrings add entries.

    External sections and clear/remove inheritance operations fail closed.
    """
    if source is None:
        raise ValueError("source is absent")
    value = source.get("content", source.get("bytes", source.get("data")))
    if value is None:
        raise ValueError("source content is missing")
    if isinstance(value, bytes):
        value = value.decode("utf-8-sig")
    if isinstance(value, str):
        value = _xml_document(value) if _provider(source) == 'xml' else json.loads(value, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("source content must be a configuration object")
    seen = set()
    def validate(node, segments=()):
        if segments:
            logical = _logical_key(segments).casefold()
            if logical in seen:
                raise ValueError(f'Duplicate logical configuration key: {_logical_key(segments)}')
            seen.add(logical)
        if isinstance(node, (dict, list)):
            items = node.items() if isinstance(node, dict) else enumerate(node)
            for key, child in items:
                if isinstance(node, dict) and not isinstance(key, str):
                    raise ValueError('Configuration object keys must be strings')
                validate(child, (*segments, key))
    validate(value)
    return value


def _document(source):
    return parse_configuration_source(source)


def _containers(value, prefix=()):
    if isinstance(value, (dict, list)):
        yield prefix, value
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            yield from _containers(child, (*prefix, key))


def _source_ref(source):
    return dict(source)


def _scope(source, consumer_sources):
    matching = [consumer for consumer in consumer_sources
                if consumer.get("path") == source.get("path")]
    values = {}
    conflicts = []
    for field_name in ("environment", "service"):
        candidates = {item.get(field_name) for item in [source, *matching]
                      if isinstance(item.get(field_name), str) and item[field_name].strip()}
        values[field_name] = next(iter(candidates)) if len(candidates) == 1 else None
        if len(candidates) > 1:
            conflicts.append(field_name)
    return values["environment"], values["service"], conflicts


def _same_json_value(left, right):
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _target_config(document, key):
    """Retain typed ancestors and the complete outermost target array."""
    def fragment(value, parts):
        if isinstance(value, list) or not parts:
            return deepcopy(value)
        if not isinstance(value, dict) or parts[0] not in value:
            return _MISSING
        child = fragment(value[parts[0]], parts[1:])
        return _MISSING if child is _MISSING else {parts[0]: child}
    result = fragment(document, key)
    return {} if result is _MISSING else result


def discover_parameter_changes(base_sources: list[dict], target_sources: list[dict], *,
                               consumer_sources: list[dict] | None = None,
                               deployment_sources: list[dict] | None = None) -> ParameterDiscoveryResult:
    consumers = consumer_sources or []
    deployments = deployment_sources or []
    result = ParameterDiscoveryResult()
    result.checked_sources = [dict(role=role, **_source_ref(source))
                              for role, sources in (("base", base_sources), ("target", target_sources),
                                                    ("consumer", consumers), ("deployment", deployments))
                              for source in sources]
    for role, sources in (("base", base_sources), ("target", target_sources)):
        paths = [source.get('path') for source in sources]
        if len(paths) != len(set(paths)):
            result.findings.append({'blocking': True,
                                    'message': f'Duplicate pinned {role} configuration sources'})
            result.applicable = None
            return result
    base_by_path = {source.get("path"): source for source in base_sources}
    target_by_path = {source.get("path"): source for source in target_sources}
    detected = False
    unresolved = False

    for path in sorted(set(base_by_path) | set(target_by_path)):
        before_source = base_by_path.get(path)
        after_source = target_by_path.get(path)
        try:
            before_document = _document(before_source) if before_source else {}
            before = dict(_flatten(before_document)) if before_source else {}
            target_document = _document(after_source) if after_source else {}
            after = dict(_flatten(target_document)) if after_source else {}
            old_containers = dict(_containers(before_document))
            new_containers = dict(_containers(target_document))
            replaced = [segments for segments in old_containers.keys() & new_containers.keys()
                        if type(old_containers[segments]) is not type(new_containers[segments])]
            physical_keys = {}
            for segments in [*dict(_containers(before_document)), *before,
                             *dict(_containers(target_document)), *after]:
                if any(len(segments) > len(parent) and segments[:len(parent)] == parent
                       for parent in replaced):
                    continue
                logical = _logical_key(segments).casefold()
                if logical in physical_keys and physical_keys[logical] != segments:
                    raise ValueError(f'Ambiguous physical paths for logical key: {_logical_key(segments)}')
                physical_keys[logical] = segments
        except (ValueError, TypeError, UnicodeError) as error:
            unresolved = True
            result.findings.append({"blocking": True, "source": path,
                                    "message": f"Unable to parse pinned configuration source: {error}"})
            continue
        before_containers = dict(_containers(before_document))
        after_containers = dict(_containers(target_document))
        type_changes = sorted((key for key in before_containers.keys() & after_containers.keys()
                              if type(before_containers[key]) is not type(after_containers[key])), key=_logical_key)
        # Report the outermost replaced container once, retaining its typed values.
        type_changes = [key for key in type_changes if not any(
            key[:len(parent)] == parent for parent in type_changes if parent != key)]
        for key in type_changes:
            before = {path: value for path, value in before.items()
                      if not (len(path) > len(key) and path[:len(key)] == key)}
            after = {path: value for path, value in after.items()
                     if not (len(path) > len(key) and path[:len(key)] == key)}
            before[key], after[key] = before_containers[key], after_containers[key]
        changed_keys = sorted((key for key in set(before) | set(after)
                              if not _same_json_value(before.get(key, _MISSING),
                                                      after.get(key, _MISSING))), key=_logical_key)
        for key in changed_keys:
            detected = True
            old = before.get(key, _MISSING)
            new = after.get(key, _MISSING)
            kind = "add" if old is _MISSING else "remove" if new is _MISSING else "update"
            owner = after_source or before_source
            environment, service, scope_conflicts = _scope(owner, consumers)
            descriptor = {"environment": environment, "service": service, "key": _logical_key(key),
                          "key_segments": list(key), "configuration_provider": _provider(owner),
                          "target_config": _target_config(target_document, key),
                          "change": kind, "source_reference": {
                              "base": _source_ref(before_source) if before_source else None,
                              "target": _source_ref(after_source) if after_source else None}}
            if old is not _MISSING:
                descriptor["old_value"] = old
            if new is not _MISSING:
                descriptor["new_value"] = new
            result.changes.append(descriptor)
            missing = [field for field in ("environment", "service", "key")
                       if not isinstance(descriptor[field], str) or not descriptor[field].strip()]
            if missing:
                unresolved = True
                result.findings.append({"blocking": True, "source": path, "key": _logical_key(key),
                                        "missing": missing,
                                        "message": "Parameter descriptor is incomplete"})
            if scope_conflicts:
                unresolved = True
                result.findings.append({"blocking": True, "source": path, "key": _logical_key(key),
                                        "missing": ["scope"], "conflicts": scope_conflicts,
                                        "message": "Conflicting consumer scope evidence"})

    for source in deployments:
        deployment_result = discover_deployment_changes([source], consumers)
        result.changes.extend(deployment_result.changes)
        result.findings.extend(deployment_result.findings)
        detected = detected or bool(deployment_result.changes)
        unresolved = unresolved or any(finding.get('blocking') for finding in deployment_result.findings)
        if not deployment_result.findings:
            continue
        variables = source.get("environment_variables", {})
        if not isinstance(variables, dict):
            continue
        for variable in sorted(key for key in variables if isinstance(key, str)):
            if "__" not in variable:
                continue
            detected = True
            key = variable.replace("__", ":")
            environment, service, scope_conflicts = _scope(source, consumers)
            unresolved = True
            missing = [field for field, field_value in (("environment", environment), ("service", service))
                       if not isinstance(field_value, str) or not field_value.strip()]
            proof = source.get('provider_precedence')
            if not isinstance(proof, dict) or proof.get('conclusion') != 'passed':
                missing.append('provider_precedence')
            if not isinstance(source.get('base_environment_variables'), dict):
                missing.append('base_value')
            result.findings.append({"blocking": True, "source": source.get("path"), "key": key,
                                    "missing": missing,
                                    "conflicts": scope_conflicts,
                                    "message": "Environment variable mapping found; deployment evidence unresolved"})

    if detected:
        result.applicable = None if unresolved else True
    else:
        result.applicable = False if not result.findings else None
    return result

"""Compare caller-pinned configuration sources and retain their provenance."""
from dataclasses import dataclass, field
from copy import deepcopy
import json


_MISSING = object()


@dataclass
class ParameterDiscoveryResult:
    changes: list[dict] = field(default_factory=list)
    checked_sources: list[dict] = field(default_factory=list)
    applicable: bool | None = None
    findings: list[dict] = field(default_factory=list)


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        if not value:
            yield prefix, value
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}:{key}" if prefix else str(key))
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}:{index}" if prefix else str(index))
    else:
        yield prefix, value


def _document(source):
    if source is None:
        raise ValueError("source is absent")
    value = source.get("content", source.get("bytes", source.get("data")))
    if value is None:
        raise ValueError("source content is missing")
    if isinstance(value, bytes):
        value = value.decode("utf-8-sig")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("source content must be a JSON object")
    return value


def _containers(value, prefix=""):
    if isinstance(value, (dict, list)):
        yield prefix, value
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            yield from _containers(child, f"{prefix}:{key}" if prefix else str(key))


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
    result = fragment(document, key.split(":"))
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
        except (ValueError, TypeError, UnicodeError) as error:
            unresolved = True
            result.findings.append({"blocking": True, "source": path,
                                    "message": f"Unable to parse pinned JSON source: {error}"})
            continue
        before_containers = dict(_containers(before_document))
        after_containers = dict(_containers(target_document))
        type_changes = sorted(key for key in before_containers.keys() & after_containers.keys()
                              if type(before_containers[key]) is not type(after_containers[key]))
        # Report the outermost replaced container once, retaining its typed values.
        type_changes = [key for key in type_changes if not any(
            key.startswith(parent + ':') for parent in type_changes if parent != key)]
        for key in type_changes:
            before = {path: value for path, value in before.items()
                      if not path.startswith(key + ':')}
            after = {path: value for path, value in after.items()
                     if not path.startswith(key + ':')}
            before[key], after[key] = before_containers[key], after_containers[key]
        changed_keys = sorted(key for key in set(before) | set(after)
                              if not _same_json_value(before.get(key, _MISSING),
                                                      after.get(key, _MISSING)))
        for key in changed_keys:
            detected = True
            old = before.get(key, _MISSING)
            new = after.get(key, _MISSING)
            kind = "add" if old is _MISSING else "remove" if new is _MISSING else "update"
            owner = after_source or before_source
            environment, service, scope_conflicts = _scope(owner, consumers)
            descriptor = {"environment": environment, "service": service, "key": key,
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
                result.findings.append({"blocking": True, "source": path, "key": key,
                                        "missing": missing,
                                        "message": "Parameter descriptor is incomplete"})
            if scope_conflicts:
                unresolved = True
                result.findings.append({"blocking": True, "source": path, "key": key,
                                        "missing": ["scope"], "conflicts": scope_conflicts,
                                        "message": "Conflicting consumer scope evidence"})

    for source in deployments:
        variables = source.get("environment_variables", {})
        for variable, value in sorted(variables.items()):
            if "__" not in variable:
                continue
            detected = True
            key = variable.replace("__", ":")
            environment, service, scope_conflicts = _scope(source, consumers)
            unresolved = True
            missing = [field for field, field_value in (("environment", environment), ("service", service))
                       if not isinstance(field_value, str) or not field_value.strip()]
            result.findings.append({"blocking": True, "source": source.get("path"), "key": key,
                                    "missing": missing + ["provider_precedence", "base_value"],
                                    "conflicts": scope_conflicts,
                                    "message": "Environment variable mapping found; provider or base evidence unresolved"})

    if detected:
        result.applicable = None if unresolved else True
    else:
        result.applicable = False if not result.findings else None
    return result

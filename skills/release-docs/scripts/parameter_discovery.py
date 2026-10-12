"""Compare caller-pinned configuration sources and retain their provenance."""
from dataclasses import dataclass, field
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
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}:{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}:{index}" if prefix else str(index))
    else:
        yield prefix, value


def _document(source):
    value = source.get("content", source.get("bytes", source.get("data")))
    if isinstance(value, bytes):
        value = value.decode("utf-8-sig")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _source_ref(source):
    return dict(source)


def _scope(source, consumer_sources):
    environment = source.get("environment")
    service = source.get("service")
    for consumer in consumer_sources:
        if consumer.get("path") == source.get("path"):
            environment = environment or consumer.get("environment")
            service = service or consumer.get("service")
    return environment, service


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
            before = dict(_flatten(_document(before_source))) if before_source else {}
            after = dict(_flatten(_document(after_source))) if after_source else {}
        except (ValueError, TypeError, UnicodeError) as error:
            unresolved = True
            result.findings.append({"blocking": True, "source": path,
                                    "message": f"Unable to parse pinned JSON source: {error}"})
            continue
        changed_keys = sorted(key for key in set(before) | set(after)
                              if before.get(key, _MISSING) != after.get(key, _MISSING))
        for key in changed_keys:
            detected = True
            old = before.get(key, _MISSING)
            new = after.get(key, _MISSING)
            kind = "add" if old is _MISSING else "remove" if new is _MISSING else "update"
            owner = after_source or before_source
            environment, service = _scope(owner, consumers)
            descriptor = {"environment": environment, "service": service, "key": key,
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

    for source in deployments:
        variables = source.get("environment_variables", {})
        for variable, value in sorted(variables.items()):
            if "__" not in variable:
                continue
            detected = True
            key = variable.replace("__", ":")
            environment, service = _scope(source, consumers)
            missing = [field for field, field_value in (("environment", environment), ("service", service))
                       if not isinstance(field_value, str) or not field_value.strip()]
            unresolved = True
            result.changes.append({"environment": environment, "service": service, "key": key,
                                   "new_value": value, "change": "add",
                                   "source_reference": {"deployment": _source_ref(source)}})
            result.findings.append({"blocking": True, "source": source.get("path"), "key": key,
                                    "missing": missing or ["provider_precedence", "base_value"],
                                    "message": "Environment variable mapping found; provider or base evidence unresolved"})

    if detected:
        result.applicable = None if unresolved else True
    else:
        result.applicable = False if not result.findings else None
    return result

#!/usr/bin/env python3
"""Identify Entity Framework evidence from immutable Git objects."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


@dataclass
class EFDetection:
    framework: str | None = None
    version: str | None = None
    provider: str | None = None
    contexts: list[str] = field(default_factory=list)
    migration_paths: list[str] = field(default_factory=list)
    database_identity: str | None = None
    evidence: list[dict] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    blocking: bool = False


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Unable to read pinned Git source evidence")
    return result.stdout


def _source_paths(repo, revision):
    raw = _git(repo, "ls-tree", "-r", "--name-only", "-z", revision)
    return set(filter(None, raw.decode("utf-8", errors="surrogateescape").split("\0")))


def _candidate(path):
    name = path.lower()
    return name.endswith((".csproj", ".props", ".config", ".cs", ".json")) and (
        not name.endswith(".json") or name.endswith(("project.assets.json", "packages.lock.json"))
        or Path(name).name.startswith("appsettings")
    )


_CS_TOKENS = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.M)


def _cs_code(content, mask_strings):
    """Mask comments, and optionally literals, without shifting source offsets."""
    def replace(match):
        token = match.group()
        if token.startswith(("//", "/*")) or mask_strings:
            return re.sub(r"[^\n]", " ", token)
        return token
    return _CS_TOKENS.sub(replace, content)


def _normalize_database(connection_string):
    settings = {}
    for part in connection_string.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            settings[key.strip().lower()] = value.strip().strip('"\'').lower()
    server = next((settings[key] for key in ("server", "data source", "address", "addr", "network address") if settings.get(key)), None)
    database = next((settings[key] for key in ("database", "initial catalog") if settings.get(key)), None)
    if not server or not database:
        return None
    return f"server={server};database={database}"


def _connection_definitions(path, content):
    definitions = {}
    try:
        if path.lower().endswith(".json") and Path(path).name.lower().startswith("appsettings"):
            values = json.loads(content).get("ConnectionStrings", {})
            for name, value in values.items():
                if isinstance(value, str):
                    definitions.setdefault(name, set()).add(_normalize_database(value))
        elif path.lower().endswith(".config"):
            root = ET.fromstring(content)
            for item in root.findall(".//connectionStrings/add"):
                name = item.get("name")
                value = item.get("connectionString")
                if name and value:
                    definitions.setdefault(name, set()).add(_normalize_database(value))
    except (ValueError, ET.ParseError, AttributeError):
        return {}
    return definitions


def _package_entries(path, content):
    entries = []
    if path.lower().endswith((".csproj", ".props", ".config")):
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return entries
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1].lower() not in ("packagereference", "package"):
                continue
            package = item.get("Include") or item.get("id")
            version = item.get("Version") or item.get("version")
            if not version:
                version = next((child.text for child in item if child.tag.rsplit("}", 1)[-1].lower() == "version"), None)
            if package and version:
                entries.append((package, version))
    if path.lower().endswith(".json"):
        try:
            document = json.loads(content)
        except json.JSONDecodeError:
            return entries
        if path.lower().endswith("project.assets.json"):
            for package_version in document.get("libraries", {}):
                if "/" in package_version:
                    entries.append(tuple(package_version.split("/", 1)))
        else:
            for framework_packages in document.get("dependencies", {}).values():
                for package, details in framework_packages.items():
                    if isinstance(details, dict) and isinstance(details.get("resolved"), str):
                        entries.append((package, details["resolved"]))
    return entries


def _has_ef6_sqlserver_reference(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False
    return any(item.tag.rsplit("}", 1)[-1] == "Reference" and
               (item.get("Include") or "").split(",", 1)[0] == "EntityFramework.SqlServer"
               for item in root.iter())


def detect_entity_framework(repo: Path, source_scope: dict) -> EFDetection:
    """Read only blobs in source_scope['revision']; never read checkout files."""
    revision = source_scope["revision"]
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        raise ValueError("Source revision must be a resolved commit hash")
    paths = _source_paths(repo, revision)
    requested = source_scope.get("paths", sorted(paths))
    if not set(requested) <= paths:
        raise ValueError("Source scope includes paths outside pinned revision")
    result = EFDetection()
    frameworks, versions, providers = set(), set(), set()
    identities = {}
    definitions = {}
    contexts = set()
    snapshots = set()
    migration_metadata = {}
    for path in sorted(set(requested)):
        if not _candidate(path):
            continue
        raw = _git(repo, "show", f"{revision}:{path}")
        content = raw.decode("utf-8", errors="replace")
        uncommented = _cs_code(content, False) if path.lower().endswith(".cs") else content
        code = _cs_code(content, True) if path.lower().endswith(".cs") else ""
        configuration_code = bool(re.search(r'\bAddDbContext\s*<|\bOnConfiguring\s*\(', code))
        recognized = False
        for name, values in _connection_definitions(path, content).items():
            definitions.setdefault(name, set()).update(values)
            recognized = True
        for package, version in _package_entries(path, content):
            if package.lower().startswith("microsoft.entityframeworkcore"):
                frameworks.add("EF Core")
                if re.fullmatch(r"\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.]+)?", version):
                    versions.add(version)
                recognized = True
            elif package.lower() == "entityframework":
                frameworks.add("EF6")
                if re.fullmatch(r"\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.]+)?", version):
                    versions.add(version)
                recognized = True
            if package.lower().endswith(".sqlserver") or package.lower() == "entityframework.sqlserver":
                providers.add("SQL Server")
            elif package.lower().endswith((".sqlite", ".npgsql", ".mysql", ".oracle")):
                providers.add(package.rsplit(".", 1)[-1])
        if (path.lower().endswith((".csproj", ".props")) and _has_ef6_sqlserver_reference(content)) or (configuration_code and re.search(r'\bUseSqlServer\s*\(', code)):
            providers.add("SQL Server")
            recognized = True
        for method, provider in (("UseSqlite", "SQLite"), ("UseNpgsql", "PostgreSQL"), ("UseMySql", "MySQL"), ("UseOracle", "Oracle")):
            if configuration_code and re.search(r'\b' + method + r'\s*\(', code):
                providers.add(provider)
                recognized = True
        found_contexts = re.findall(r'\bclass\s+(\w+)\s*:\s*(?:[\w<> ,]+,\s*)?DbContext\b', code)
        contexts.update(found_contexts)
        if found_contexts:
            recognized = True
        for context, name in re.findall(
            r'\b(\w+)\s*\([^)]*\)\s*:\s*base\s*\(\s*"name=([^" ]+)"\s*\)', uncommented,
        ):
            identities.setdefault(context, set()).add(name)
            recognized = True
        for context, name in re.findall(r'AddDbContext\s*<\s*(\w+)\s*>[\s\S]{0,300}?UseSqlServer\s*\(\s*\w+\.GetConnectionString\s*\(\s*"([^"]+)"', uncommented):
            identities.setdefault(context, set()).add(name)
            recognized = True
        if re.search(r'\bclass\s+\w+\s*:\s*(?:DbMigration|Migration)\b', code):
            result.migration_paths.append(path)
            recognized = True
        if re.search(r'\bclass\s+\w+\s*:\s*ModelSnapshot\b', code):
            match = re.search(r'\bDbContext\s*\(\s*typeof\s*\(\s*(\w+)\s*\)', code)
            if match:
                snapshots.add(match.group(1))
            else:
                snapshot_class = re.search(r'\bclass\s+(\w+)ModelSnapshot\s*:\s*ModelSnapshot\b', code)
                if snapshot_class:
                    snapshots.add(snapshot_class.group(1))
            recognized = True
        if path.lower().endswith(".designer.cs"):
            context_match = re.search(r'\bDbContext\s*\(\s*typeof\s*\(\s*(\w+)\s*\)', code)
            id_match = re.search(r'\bMigration\s*\(\s*"([^"]+)"', uncommented)
            if not id_match:
                id_match = re.search(r'\bId\s*=>\s*"([^"]+)"', uncommented)
            if context_match and id_match:
                migration_metadata[path[:-len(".Designer.cs")]] = (context_match.group(1), id_match.group(1))
                recognized = True
        if recognized:
            result.evidence.append({"path": path, "revision": revision, "sha256": hashlib.sha256(raw).hexdigest()})
    result.contexts = sorted(contexts)
    result.migration_paths.sort()
    if len(frameworks) == 1:
        result.framework = next(iter(frameworks))
    elif len(frameworks) > 1:
        result.findings.append("Conflicting EF framework evidence")
    if len(versions) == 1:
        result.version = next(iter(versions))
    elif len(versions) > 1:
        result.findings.append("Conflicting EF version evidence")
    if len(providers) == 1:
        result.provider = next(iter(providers))
    elif len(providers) > 1:
        result.findings.append("Conflicting EF provider evidence")
    if not frameworks and not contexts and not result.migration_paths:
        result.findings.append("EF framework, context and migration evidence are unknown")
    if not result.framework:
        result.findings.append("EF framework is unknown")
    if not result.version:
        result.findings.append("EF version is unknown")
    if not result.provider:
        result.findings.append("EF provider is unknown")
    if result.provider and result.provider != "SQL Server":
        result.findings.append("Provider is not SQL Server")
    if not contexts:
        result.findings.append("DbContext is unknown")
    resolved = set()
    identity_proven = bool(contexts)
    for context in contexts:
        names = identities.get(context, set())
        if len(names) != 1:
            identity_proven = False
            continue
        values = definitions.get(next(iter(names)), set())
        if len(values) != 1 or None in values:
            identity_proven = False
        else:
            resolved.update(values)
    if identity_proven and len(resolved) == 1:
        result.database_identity = next(iter(resolved))
    else:
        result.findings.append("Context database identity cannot be proven as a single database")
    migration_contexts = set()
    chain_complete = bool(result.migration_paths)
    seen_ids = set()
    for path in result.migration_paths:
        key = path[:-len(".cs")]
        metadata = migration_metadata.get(key)
        if not metadata or metadata[1] != Path(key).name or metadata[1] in seen_ids:
            chain_complete = False
        else:
            seen_ids.add(metadata[1])
            migration_contexts.add(metadata[0])
    if set(migration_metadata) != {path[:-len(".cs")] for path in result.migration_paths}:
        chain_complete = False
    if migration_contexts != contexts or (result.framework == "EF Core" and snapshots != contexts):
        chain_complete = False
    if not chain_complete:
        result.findings.append("Migration chain is incomplete")
    result.blocking = bool(result.findings)
    return result

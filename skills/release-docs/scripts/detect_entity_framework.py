#!/usr/bin/env python3
"""Identify Entity Framework evidence from immutable Git objects."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess


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
    )


def _package_entries(path, content):
    entries = []
    for package, version in re.findall(
        r'<(?:PackageReference|package)\b[^>]*?\b(?:Include|id)\s*=\s*["\']([^"\']+)["\'][^>]*?\b(?:Version|version)\s*=\s*["\']([^"\']+)["\']',
        content, re.I,
    ):
        entries.append((package, version))
    # PackageReference can have a nested Version element.
    for package, version in re.findall(
        r'<PackageReference\b[^>]*?Include\s*=\s*["\']([^"\']+)["\'][^>]*>\s*<Version>([^<]+)</Version>',
        content, re.I,
    ):
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
    contexts = set()
    snapshots = set()
    for path in sorted(set(requested)):
        if not _candidate(path):
            continue
        raw = _git(repo, "show", f"{revision}:{path}")
        content = raw.decode("utf-8", errors="replace")
        recognized = False
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
        if "EntityFramework.SqlServer" in content or "UseSqlServer(" in content:
            providers.add("SQL Server")
            recognized = True
        for method, provider in (("UseSqlite", "SQLite"), ("UseNpgsql", "PostgreSQL"), ("UseMySql", "MySQL"), ("UseOracle", "Oracle")):
            if method + "(" in content:
                providers.add(provider)
                recognized = True
        found_contexts = re.findall(r'\bclass\s+(\w+)\s*:\s*(?:[\w<> ,]+,\s*)?DbContext\b', content)
        contexts.update(found_contexts)
        if found_contexts:
            recognized = True
        for context, name in re.findall(
            r'\b(\w+)\s*\([^)]*\)\s*:\s*base\s*\(\s*"name=([^" ]+)"\s*\)', content,
        ):
            identities.setdefault(context, set()).add(name)
            recognized = True
        for context, name in re.findall(
            r'AddDbContext\s*<\s*(\w+)\s*>[\s\S]{0,300}?UseSqlServer\s*\(\s*\w+\.GetConnectionString\s*\(\s*"([^"]+)"', content,
        ):
            identities.setdefault(context, set()).add(name)
            recognized = True
        if re.search(r'\bclass\s+\w+\s*:\s*(?:DbMigration|Migration)\b', content):
            result.migration_paths.append(path)
            recognized = True
        if re.search(r'\bclass\s+\w+\s*:\s*ModelSnapshot\b', content):
            snapshots.add(path)
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
    if frameworks or contexts or result.migration_paths:
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
        all_identities = set().union(*(identities.get(context, set()) for context in contexts)) if contexts else set()
        if len(all_identities) == 1 and all(len(identities.get(context, set())) == 1 for context in contexts):
            result.database_identity = next(iter(all_identities))
        else:
            result.findings.append("Context database identity cannot be proven as a single database")
        if not result.migration_paths or (result.framework == "EF Core" and not snapshots):
            result.findings.append("Migration chain is incomplete")
    result.blocking = bool(result.findings)
    return result

"""Discover pinned release sources and local production capabilities.

This module is deliberately read-only. It inventories evidence and tools; it
never executes project scripts or treats a missing tool as a missing source.
"""
from dataclasses import dataclass, field, asdict
import hashlib
from pathlib import Path
import shutil
import subprocess

from detect_entity_framework import detect_entity_framework


@dataclass(frozen=True)
class ProductionInputs:
    repo: Path
    baseline: Path
    base: str
    target: str
    exclusion_intent: tuple = ()
    diff_mode: str = "direct"
    workspace_policy: str = "excluded"


@dataclass
class DiscoveryResult:
    schema_version: int = 1
    repo_root: str = ""
    base_sha: str = ""
    target_sha: str = ""
    sources: list = field(default_factory=list)
    provider_evidence: dict = field(default_factory=dict)
    migration_chain: list = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                            check=True)
    return result.stdout


def _resolve(repo, revision):
    return _git(repo, "rev-parse", "--verify", "--end-of-options",
                revision + "^{commit}").decode("ascii").strip()


def _sources(repo, revision):
    paths = _git(repo, "ls-tree", "-r", "--name-only", revision).decode(
        "utf-8", errors="surrogateescape").splitlines()
    markers = (".sql", ".sqlproj", ".dacpac", "migration", "snapshot",
               "verify", "publish", "appsettings", ".csproj", ".props")
    result = []
    for path in paths:
        lower = path.casefold()
        if not any(marker in lower for marker in markers):
            continue
        raw = _git(repo, "show", f"{revision}:{path}")
        result.append({"path": path, "revision": revision,
                       "sha256": hashlib.sha256(raw).hexdigest()})
    return result


def _capabilities():
    names = ("dotnet", "MSBuild", "SqlPackage", "sqlcmd", "SqlLocalDB")
    result = {}
    for name in names:
        path = shutil.which(name)
        item = {"available": bool(path), "path": path}
        if path:
            probe = subprocess.run([path, "--version"], capture_output=True,
                                   text=False, check=False, timeout=10)
            raw = probe.stdout or probe.stderr or b""
            item["version"] = raw.decode("utf-8", errors="replace").strip()[:300]
        result[name] = item
    return result


def discover_release_sources(inputs: ProductionInputs) -> DiscoveryResult:
    repo = Path(inputs.repo).resolve()
    result = DiscoveryResult(repo_root=str(repo))
    result.base_sha = _resolve(repo, inputs.base)
    result.target_sha = _resolve(repo, inputs.target)
    result.sources = _sources(repo, result.target_sha)
    scope = {"revision": result.target_sha,
             "paths": [item["path"] for item in result.sources]}
    try:
        detection = detect_entity_framework(repo, scope)
        result.provider_evidence = asdict(detection)
        result.migration_chain = list(detection.migration_paths)
        result.findings.extend(detection.findings)
    except (OSError, ValueError) as error:
        result.findings.append(f"framework discovery failed: {error}")
    result.capabilities = _capabilities()
    return result


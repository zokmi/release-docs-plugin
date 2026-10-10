"""Immutable provenance for SQL generated from pinned source evidence."""
import hashlib
import json
from pathlib import Path
import re

from path_safety import is_linked_path


SCHEMA_VERSION = 2
SOURCE_TYPES = {"pinned_git", "derived_artifact"}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _safe_run_file(run_root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Derived source path must be run-relative")
    path = (Path(run_root) / relative).resolve()
    root = Path(run_root).resolve()
    if not path.is_relative_to(root) or any(is_linked_path(p) for p in (root, path, *path.parents)):
        raise ValueError("Derived source path is unsafe")
    return path


def register_derived_source(run_root, sql_bytes, provenance):
    if not isinstance(sql_bytes, bytes) or not isinstance(provenance, dict):
        raise ValueError("Invalid derived source")
    required = ("scope", "baseline_sha256", "inputs", "method", "tool", "mapping")
    if any(key not in provenance for key in required):
        raise ValueError("Incomplete derived provenance")
    root = Path(run_root).resolve()
    if root.parent.name != "runs" or root.parent.parent.name != ".release-docs":
        raise ValueError("Derived source must be inside lifecycle run")
    relative = "evidence/derived-execution.sql"
    path = _safe_run_file(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != sql_bytes:
        raise ValueError("Derived source is immutable")
    if not path.exists():
        path.write_bytes(sql_bytes)
    inputs = provenance["inputs"]
    if not isinstance(inputs, list) or not inputs or any(
        not isinstance(item, dict) or not all(item.get(k) for k in ("path", "revision", "sha256"))
        for item in inputs
    ):
        raise ValueError("Incomplete derived inputs")
    record = {
        "schema_version": SCHEMA_VERSION,
        "source_type": "derived_artifact",
        "path": relative,
        "sha256": _sha(sql_bytes),
        "provenance": provenance,
    }
    metadata = root / "derived_source.json"
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    if metadata.exists() and metadata.read_bytes() != encoded:
        raise ValueError("Derived provenance is immutable")
    if not metadata.exists():
        metadata.write_bytes(encoded)
    return record


def verify_source(repo, run_root, source, scope):
    if not isinstance(source, dict) or source.get("source_type") not in SOURCE_TYPES:
        raise ValueError("Unknown source type")
    source_type = source["source_type"]
    if source_type == "pinned_git":
        revision = source.get("source_revision")
        path = source.get("source_path")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
            raise ValueError("Invalid pinned source revision")
        if revision not in (scope.get("base_sha"), scope.get("target_sha")):
            raise ValueError("Source revision is outside scope")
        import subprocess
        raw = subprocess.run(["git", "-C", str(repo), "show", f"{revision}:{path}"],
                             capture_output=True, check=True).stdout
    else:
        raw = _safe_run_file(run_root, source.get("path", "")).read_bytes()
        provenance = source.get("provenance") or {}
        if provenance.get("scope", {}).get("base_sha") != scope.get("base_sha"):
            raise ValueError("Derived scope mismatch")
        if provenance.get("scope", {}).get("target_sha") != scope.get("target_sha"):
            raise ValueError("Derived scope mismatch")
        if not provenance.get("inputs") or not provenance.get("mapping"):
            raise ValueError("Incomplete derived provenance")
    if _sha(raw) != source.get("sha256"):
        raise ValueError("Source hash mismatch")
    return raw


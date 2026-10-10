"""Write immutable, content-free evidence inside the release lifecycle only."""
import json
from pathlib import Path
import os
import re
import shutil
from path_safety import is_linked_path
from parameter_metadata import sanitize_parameter_changes


def write_lifecycle_run(run_root, analysis_result, localdb_validation=None,
                        execution_artifact=None, operator_contract=None, parent_run_id=None):
    """Persist deterministic metadata, rejecting operator paths and replacement."""
    requested = Path(run_root)
    if ".." in requested.parts:
        raise ValueError("Traversal is not permitted in lifecycle paths")
    root = requested.absolute()
    if (root.parent.name != "runs" or root.parent.parent.name != ".release-docs"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", root.name)):
        raise ValueError("Run must be inside lifecycle .release-docs/runs/<run-id>")
    if any(is_linked_path(p) for p in (root, *root.parents)):
        raise ValueError("Linked lifecycle paths are not permitted")
    applicable = getattr(analysis_result, 'parameters_applicable', None)
    changes = sanitize_parameter_changes(getattr(analysis_result, 'parameter_changes', []))
    if applicable is not None and (type(applicable) is not bool or applicable != bool(changes)):
        raise ValueError('Parameter applicability conflicts with analysis')
    declared = (operator_contract or {}).get('parameters_applicable')
    if applicable is not None and declared is not None and declared != applicable:
        raise ValueError('Parameter applicability conflicts with operator contract')
    lifecycle_metadata = {
            "schema_version": 1, "run_id": root.name,
            "retention": {"failed_days": 7, "cleanup_after_success": True},
            "cleanup_status": "pending_success", "review_status": "pending",
            "analysis_status": "blocked" if analysis_result.blocked else "ready",
        }
    if localdb_validation is not None:
        if not isinstance(localdb_validation, dict) or localdb_validation.get("schema_version") != 1:
            raise ValueError("Invalid LocalDB validation evidence")
        lifecycle_metadata["localdb_validation"] = localdb_validation
    if execution_artifact is not None:
        lifecycle_metadata["execution_artifact"] = execution_artifact
    if operator_contract is not None:
        lifecycle_metadata["operator_contract"] = operator_contract
    if parent_run_id is not None:
        if not isinstance(parent_run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', parent_run_id):
            raise ValueError('Invalid parent run')
        lifecycle_metadata['parent_run_id'] = parent_run_id
    documents = {
        "lifecycle_exclusion_manifest.json": {"schema_version": 1, "exclusions": analysis_result.exclusions},
        "source_unit_metadata.json": {
            "schema_version": 1, "source_scope": analysis_result.source_scope,
            "baseline": analysis_result.baseline, "sources": analysis_result.sources,
            "units": [{k: v for k, v in u.items() if k != "sql"} for u in analysis_result.units],
            "findings": analysis_result.findings,
            "structure_changes": getattr(analysis_result, 'structure_changes', []),
            "parameter_changes": changes,
            "parameters_applicable": applicable,
        },
        "lifecycle_metadata.json": lifecycle_metadata,
    }
    if localdb_validation is not None:
        # Keep the full fixture and round evidence as a permanent review input.
        documents["localdb_validation.json"] = localdb_validation
    encoded = {name: (json.dumps(document, sort_keys=True, ensure_ascii=True,
                                indent=2) + "\n").encode("utf-8")
               for name, document in documents.items()}
    # Preflight every existing file before writing anything; no mixed generations.
    for name, data in encoded.items():
        destination = root / name
        if destination.is_symlink() or (destination.exists() and os.stat(destination).st_nlink != 1):
            raise ValueError("Linked lifecycle files are not permitted")
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("Lifecycle evidence is immutable; create a new run")
    root.parent.mkdir(parents=True, exist_ok=True)
    # Sweep only expired, explicitly owned temporary material at run start;
    # permanent lifecycle evidence is retained.
    sweep_expired_lifecycle_runs(root.parent.parent)
    root.mkdir(parents=True, exist_ok=True)
    ignore = root.parent.parent / ".gitignore"
    if is_linked_path(ignore) or (ignore.exists() and os.stat(ignore).st_nlink != 1):
        raise ValueError("Lifecycle ignore file is linked")
    existing_ignore = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "runs/" not in {line.strip() for line in existing_ignore.splitlines()}:
        suffix = "" if not existing_ignore or existing_ignore.endswith("\n") else "\n"
        ignore.write_text(existing_ignore + suffix + "runs/\n", encoding="utf-8")
    for name, data in encoded.items():
        destination = root / name
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(data)
    return root / "lifecycle_exclusion_manifest.json"


def cleanup_lifecycle_run(run_root, *, outcome):
    """Apply retention policy to one lifecycle run after review/deployment.

    Successful runs remove only owned temporary material; immutable manifests,
    review records and execution evidence remain available for traceability.
    Failed runs remain available for the configured seven-day retention job.
    """
    requested = Path(run_root)
    if ".." in requested.parts:
        raise ValueError("Traversal is not permitted in lifecycle paths")
    root = requested.absolute()
    if (root.parent.name != "runs" or root.parent.parent.name != ".release-docs"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", root.name)):
        raise ValueError("Run must be inside lifecycle .release-docs/runs/<run-id>")
    if any(is_linked_path(p) for p in (root, *root.parents)):
        raise ValueError("Linked lifecycle paths are not permitted")
    if outcome != "success":
        return False
    if not root.exists():
        return False
    removed = False
    for name in ("temporary", ".tmp"):
        child = root / name
        if child.is_dir() and not is_linked_path(child):
            shutil.rmtree(child)
            removed = True
    return removed


def finalize_lifecycle_run(run_root, *, review_status, delivery_status):
    """Finalize after review and delivery, then clean owned temp material."""
    if review_status != "success" or delivery_status != "success":
        return False
    return cleanup_lifecycle_run(run_root, outcome="success")


def sweep_expired_lifecycle_runs(lifecycle_root, *, now=None, retention_days=7):
    """Remove only expired failed/temporary lifecycle runs under ``runs``."""
    base = Path(lifecycle_root).absolute()
    runs = base / "runs"
    if base.name != ".release-docs" or is_linked_path(runs) or not runs.is_dir():
        raise ValueError("Lifecycle root must contain a regular runs directory")
    if any(is_linked_path(p) for p in (base, *base.parents)):
        raise ValueError("Linked lifecycle paths are not permitted")
    cutoff = (now.timestamp() if now is not None else __import__("time").time()) - retention_days * 86400
    removed = []
    for child in runs.iterdir():
        if (not child.is_dir() or is_linked_path(child)
                or child.stat().st_mtime > cutoff):
            continue
        # Permanent manifests and review records are never swept. Only an
        # explicitly owned temporary directory can expire.
        temporary = child / "temporary"
        if temporary.is_dir() and not is_linked_path(temporary):
            shutil.rmtree(temporary)
            removed.append(child.name)
    return removed

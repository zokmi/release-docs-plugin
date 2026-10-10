"""Opt-in, disposable LocalDB validation and lifecycle evidence writer.

The runner deliberately accepts an executor instead of opening a database itself.
Production deployment is therefore impossible through this module; integrations
must supply a disposable LocalDB executor and report structured checks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import argparse
import sys
from typing import Any, Callable, Sequence

ROUNDS = ("validate_only", "commit", "rerun", "injected_failure")
_LOCALDB = re.compile(r"^\(localdb\)(?:\\[A-Za-z0-9_.-]+)?$", re.IGNORECASE)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_path(value: str | os.PathLike[str] | None, label: str) -> Path | None:
    if not value:
        return None
    original = Path(value).absolute()
    if any(part.is_symlink() or (part.exists() and part.is_junction())
           for part in (original, *original.parents)):
        raise ValueError(f"{label} must be a regular, non-linked file")
    if original.is_file() and os.stat(original).st_nlink != 1:
        raise ValueError(f"{label} must be a regular, non-linked file")
    return original if original.is_file() else None


def _base_round(name: str, *, server: str, database: str, baseline: str,
                fixture: str, baseline_sha256: str, fixture_sha256: str,
                command: str | list[str], provider: str, tool: str,
                manifest: str, manifest_sha256: str,
                preserved_summary: dict[str, Any], artifact_sha256: str) -> dict[str, Any]:
    return {
        "status": "not_run", "exit_code": None, "server": server,
        "database": database, "provider_version": provider,
        "tool_version": tool, "baseline_source": baseline,
        "baseline_sha256": baseline_sha256, "baseline_usage": "",
        "fixture_source": fixture, "fixture_sha256": fixture_sha256,
        "fixture_manifest": manifest, "fixture_manifest_sha256": manifest_sha256,
        "fixture_usage": "", "expected_preserved_data_summary": preserved_summary,
        "command": command, "checks": [], "data_checks": [], "error_output_summary": "",
        "database_id": "", "session_id": "", "committed_state": "",
        "round": name, "artifact_sha256": artifact_sha256,
        "preserved_data_summary": {},
    }


def run_local_validation(
    artifact_path: str | os.PathLike[str], *,
    server: str,
    database: str,
    baseline_source: str = "",
    fixture_source: str = "",
    fixture_manifest: str | os.PathLike[str] | None = None,
    data_units: Sequence[dict[str, Any]] = (),
    command: str | list[str] = "",
    provider_version: str = "unknown",
    tool_version: str = "release-docs-localdb-runner/1",
    adapter_provenance: str = "",
    executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run four isolated checks or return explicit ``not_run`` evidence.

    ``executor`` is an injected disposable LocalDB adapter. Every invocation is
    marked as a fresh session; the adapter reports database/session identity. It
    must report checks and an error summary; it never receives production
    credentials or a production server because the server is checked here.
    """
    artifact = _source_path(artifact_path, "Deployment artifact")
    if artifact is None:
        raise ValueError("Deployment artifact must be a regular file")
    if not isinstance(server, str) or not _LOCALDB.fullmatch(server):
        raise ValueError("LocalDB validation requires a (localdb) server; production is forbidden")
    if not isinstance(database, str) or not database.strip():
        raise ValueError("Disposable LocalDB database is required")
    digest = _digest(artifact)
    baseline = _source_path(baseline_source, "baseline_source")
    fixture = _source_path(fixture_source, "fixture_source")
    manifest = _source_path(fixture_manifest, "fixture_manifest")
    baseline_sha256 = _digest(baseline) if baseline else ""
    fixture_sha256 = _digest(fixture) if fixture else ""
    manifest_sha256 = _digest(manifest) if manifest else ""
    manifest_data: dict[str, Any] = {}
    if manifest_sha256:
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            manifest_data = {}
    if not isinstance(manifest_data, dict):
        manifest_data = {}
    expected_assertions = list(manifest_data.get("assertions", [])) if isinstance(manifest_data.get("assertions", []), list) else []
    for unit in data_units:
        if isinstance(unit, dict) and isinstance(unit.get("expected_assertions"), list):
            expected_assertions.extend({**item, "unit_id": unit.get("unit_id")}
                                       for item in unit["expected_assertions"] if isinstance(item, dict))
    preserved_summary = manifest_data.get("expected_preserved_data_summary", {})
    if not preserved_summary:
        preserved_summary = {unit["unit_id"]: unit["expected_preserved_data_summary"]
                             for unit in data_units if isinstance(unit, dict)
                             and unit.get("unit_id") and unit.get("expected_preserved_data_summary")}
    fixture_usage = manifest_data.get("usage", "") or "; ".join(
        str(unit.get("fixture_usage", "")) for unit in data_units if isinstance(unit, dict))
    rounds = {
        name: _base_round(name, server=server, database=database,
                           baseline=baseline_source, fixture=fixture_source,
                           baseline_sha256=baseline_sha256, fixture_sha256=fixture_sha256,
                           command=command, provider=provider_version,
                           tool=tool_version, manifest=str(fixture_manifest or ""),
                           manifest_sha256=manifest_sha256, preserved_summary=preserved_summary,
                           artifact_sha256=digest)
        for name in ROUNDS
    }
    result: dict[str, Any] = {
        "schema_version": 1, "status": "not_run", "reason": "",
        "artifact_sha256": digest, "server": server, "database": database,
        "provider_version": provider_version, "tool_version": tool_version,
        "adapter_provenance": adapter_provenance,
        "fixture_source": fixture_source, "fixture_sha256": fixture_sha256,
        "fixture_manifest": str(fixture_manifest or ""),
        "fixture_manifest_sha256": manifest_sha256,
        "fixture_usage": fixture_usage,
        "expected_preserved_data_summary": preserved_summary,
        "expected_assertions": expected_assertions,
        "fixture_seed_rows": manifest_data.get("seed_rows", []),
        "rounds": rounds,
    }
    if executor is None:
        result["reason"] = "未提供隔離 LocalDB runner；未執行資料庫驗證"
        return result
    if not callable(executor):
        raise ValueError("executor must be callable")
    if not adapter_provenance.strip():
        raise ValueError("Actual LocalDB validation requires adapter provenance")
    if not provider_version.strip() or provider_version == "unknown":
        raise ValueError("Actual LocalDB validation requires provider version")
    if not tool_version.strip() or tool_version == "unknown":
        raise ValueError("Actual LocalDB validation requires tool version")
    if not baseline_sha256 or not fixture_sha256:
        if data_units:
            result["reason"] = "資料異動缺少 baseline 或 fixture 來源；待確認"
            return result
        raise ValueError("baseline_source and fixture_source must be existing regular files")
    if data_units:
        unit_ids = {unit.get("unit_id") for unit in data_units if isinstance(unit, dict) and unit.get("unit_id")}
        seed_rows = manifest_data.get("seed_rows", [])
        valid_seed_rows = [row for row in seed_rows if isinstance(row, dict)
                           and row.get("unit_id") in unit_ids and row.get("row_id")
                           and row.get("purpose")] if isinstance(seed_rows, list) else []
        seed_purposes = {(row["unit_id"], row["row_id"]): row["purpose"] for row in valid_seed_rows}
        valid_assertions = [item for item in expected_assertions
                            if isinstance(item, dict) and item.get("unit_id") in unit_ids
                            and item.get("id") and item.get("case")
                            and seed_purposes.get((item["unit_id"], item.get("seed_row_id"))) == item["case"]
                            and isinstance(item.get("expected_by_round"), dict)
                            and all(isinstance(item["expected_by_round"].get(round_name), dict)
                                    and set(item["expected_by_round"][round_name]) == {"before", "after"}
                                    for round_name in ROUNDS)]
        covered = {item["unit_id"] for item in valid_assertions}
        def consistent_rounds(item: dict[str, Any]) -> bool:
            expected = item["expected_by_round"]
            before = expected["commit"]["before"]
            after = expected["commit"]["after"]
            return (expected["validate_only"] == {"before": before, "after": before}
                    and expected["rerun"] == {"before": after, "after": after}
                    and expected["injected_failure"] == {"before": before, "after": before})
        preserved = [item for item in valid_assertions if item["case"] == "preserved_data"
                     and item["expected_by_round"]["commit"]["before"] ==
                     item["expected_by_round"]["commit"]["after"]]
        changed_units = {item["unit_id"] for item in valid_assertions
                         if item["case"] == "existing_value" and
                         item["expected_by_round"]["commit"]["before"] !=
                         item["expected_by_round"]["commit"]["after"]}
        relevant = {row["unit_id"] for row in valid_seed_rows}
        if (len(unit_ids) != len(data_units) or covered != unit_ids or relevant != unit_ids
                or not preserved or {item["unit_id"] for item in preserved} != unit_ids
                or changed_units != unit_ids or not all(consistent_rounds(item) for item in valid_assertions)
                or not preserved_summary or not fixture_usage or not manifest_sha256):
            result["reason"] = "資料異動缺少 fixture 用途、保留資料摘要或前後預期查核；待確認"
            return result
        expected_assertions = valid_assertions
        result["expected_assertions"] = expected_assertions

    failures: list[str] = []
    sql = artifact.read_text(encoding="utf-8")
    committed_state = ""
    committed_database_id = ""
    seen_sessions: set[str] = set()
    seen_checks: set[str] = set()
    fresh_databases: set[str] = set()
    for index, name in enumerate(ROUNDS):
        evidence = rounds[name]
        evidence["baseline_usage"] = ("committed database; new session" if name == "rerun"
                                      else f"fresh disposable baseline/session #{index + 1}")
        evidence["fixture_usage"] = ("fixture loaded during commit round" if name == "rerun"
                                     else fixture_usage or "loaded into disposable LocalDB")
        if name == "rerun" and not committed_state:
            evidence["error_output_summary"] = "Commit round did not return committed state"
            failures.append("rerun:committed_state_pending")
            continue
        try:
            raw = executor(
                sql=sql, artifact_path=str(artifact), round_name=name,
                validate_only=(name == "validate_only"),
                inject_failure=(name == "injected_failure"),
                fresh_session=True, fresh_database=(name != "rerun"),
                committed_state=committed_state if name == "rerun" else "",
                baseline_source=str(baseline), fixture_source=str(fixture),
                fixture_manifest=str(manifest) if manifest else "",
                server=server, database=database,
            )
            if not isinstance(raw, dict):
                raise ValueError("executor result must be an object")
            for key in ("status", "exit_code", "checks", "data_checks", "error_output_summary",
                        "database_id", "session_id", "committed_state", "preserved_data_summary"):
                if key in raw:
                    evidence[key] = raw[key]
            if "provider_version" in raw:
                evidence["provider_version"] = raw["provider_version"]
            if "tool_version" in raw:
                evidence["tool_version"] = raw["tool_version"]
            if "command" in raw:
                evidence["command"] = raw["command"]
            if evidence.get("provider_version") in (None, "", "unknown") or evidence.get("tool_version") in (None, "", "unknown"):
                failures.append(f"{name}:version_evidence")
            if evidence["status"] != "passed" or evidence["exit_code"] != 0:
                failures.append(name)
            if not isinstance(evidence["checks"], (list, dict)) or not evidence["checks"]:
                failures.append(f"{name}:checks")
            else:
                checks_key = json.dumps(evidence["checks"], sort_keys=True, ensure_ascii=True)
                if checks_key in seen_checks:
                    evidence["status"] = "not_run"
                    failures.append(f"{name}:distinct_checks_pending")
                seen_checks.add(checks_key)
            if (not isinstance(preserved_summary, dict) or not preserved_summary
                    or evidence["preserved_data_summary"] != preserved_summary):
                evidence["status"] = "not_run"
                failures.append(f"{name}:preserved_data_pending")
            for source, expected_hash in ((artifact, digest), (baseline, baseline_sha256),
                                           (fixture, fixture_sha256), (manifest, manifest_sha256)):
                if source is not None and _digest(source) != expected_hash:
                    evidence["status"] = "failed"
                    failures.append(f"{name}:input_changed")
            if not isinstance(evidence["error_output_summary"], str):
                failures.append(f"{name}:error_output_summary")
            session_id = evidence["session_id"]
            database_id = evidence["database_id"]
            if not isinstance(session_id, str) or not session_id or session_id in seen_sessions:
                failures.append(f"{name}:fresh_session_evidence")
            else:
                seen_sessions.add(session_id)
            if not isinstance(database_id, str) or not database_id:
                failures.append(f"{name}:database_identity")
            elif name == "rerun":
                if database_id != committed_database_id or evidence["committed_state"] != committed_state:
                    failures.append("rerun:committed_state_mismatch")
            elif database_id in fresh_databases:
                failures.append(f"{name}:fresh_database_evidence")
            else:
                fresh_databases.add(database_id)
            if data_units:
                actual = evidence["data_checks"]
                actual_ids = {(item.get("unit_id"), item.get("id")) for item in actual
                              if isinstance(item, dict) and item.get("passed") is True
                              and "before" in item and "after" in item} if isinstance(actual, list) else set()
                expected_ids = {(item["unit_id"], item["id"]) for item in expected_assertions}
                if not expected_ids.issubset(actual_ids):
                    evidence["status"] = "not_run"
                    failures.append(f"{name}:data_checks_pending")
                else:
                    observations = {(item["unit_id"], item["id"]): item for item in actual
                                    if isinstance(item, dict) and item.get("unit_id") and item.get("id")}
                    if any(observations[(item["unit_id"], item["id"])].get("seed_row_id") != item["seed_row_id"]
                           or any(observations[(item["unit_id"], item["id"])][field] !=
                                  item["expected_by_round"][name][field]
                                  for field in ("before", "after"))
                           for item in expected_assertions):
                        evidence["status"] = "failed"
                        failures.append(f"{name}:data_assertion_mismatch")
            if name == "commit":
                handle = evidence["committed_state"]
                if (isinstance(handle, str) and handle.strip() and evidence["status"] == "passed"
                        and evidence["exit_code"] == 0 and isinstance(database_id, str) and database_id):
                    committed_state = handle
                    committed_database_id = database_id
                else:
                    failures.append("commit:committed_state_pending")
            if name == "injected_failure":
                semantic = " ".join(map(str, [evidence["checks"], evidence["error_output_summary"]])).lower()
                required = ("expected" in semantic and "error" in semantic,
                            "rollback" in semantic,
                            "throw" in semantic,
                            ("later" in semantic and ("not execute" in semantic or "did not execute" in semantic or "stopped" in semantic)))
                if not all(required):
                    failures.append(f"{name}:rollback_throw_stop_contract")
        except Exception as exc:  # evidence must explain adapter failures
            evidence.update(status="failed", exit_code=1, checks=["runner exception"],
                            error_output_summary=f"{type(exc).__name__}: {exc}")
            failures.append(name)
    result["status"] = ("not_run" if failures and all("pending" in item for item in failures)
                        else "failed" if failures else "passed")
    if failures:
        result["reason"] = "；".join(failures)
    else:
        result["reason"] = "四輪隔離 LocalDB 驗證完成"
    return result


def write_localdb_evidence(run_root: str | os.PathLike[str], evidence: dict[str, Any]) -> Path:
    """Write runner evidence only below ``.release-docs/runs/<run-id>``."""
    root = Path(run_root).absolute()
    if ".." in root.parts or root.parent.name != "runs" or root.parent.parent.name != ".release-docs":
        raise ValueError("LocalDB evidence must be inside lifecycle .release-docs/runs/<run-id>")
    if any(p.is_symlink() or (p.exists() and p.is_junction()) for p in (root, *root.parents)):
        raise ValueError("Linked lifecycle paths are not permitted")
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("Invalid LocalDB evidence")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "localdb_validation.json"
    data = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()
    if destination.exists() and destination.read_bytes() != data:
        raise ValueError("LocalDB evidence is immutable; create a new run")
    if not destination.exists():
        with destination.open("xb") as stream:
            stream.write(data)
    return destination


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; without an adapter it records an explicit not_run result."""
    parser = argparse.ArgumentParser(description="Run isolated LocalDB release validation")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--baseline", default="")
    parser.add_argument("--fixture", default="")
    parser.add_argument("--fixture-manifest")
    parser.add_argument("--run-root", type=Path, required=True,
                        help=".release-docs/runs/<run-id> lifecycle directory")
    args = parser.parse_args(argv)
    evidence = run_local_validation(args.artifact, server=args.server,
                                    database=args.database,
                                    baseline_source=args.baseline,
                                    fixture_source=args.fixture, fixture_manifest=args.fixture_manifest)
    path = write_localdb_evidence(args.run_root, evidence)
    print(json.dumps({"status": evidence["status"], "evidence": str(path)}, ensure_ascii=True))
    return 0 if evidence["status"] in ("passed", "not_run") else 1


if __name__ == "__main__":
    sys.exit(main())

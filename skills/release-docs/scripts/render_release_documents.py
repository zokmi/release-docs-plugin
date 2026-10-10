"""Project lifecycle evidence into a strictly bounded operator directory.

SQL is verified against ArtifactRecord.sha256 and copied byte for byte. This
module neither regenerates SQL nor infers structure semantics from SQL text.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
from parameter_metadata import sanitize_parameter_changes

GUIDE = "00_上線指引.md"
SQL = "01_部署SQL.sql"
PARAMETERS = "02_參數異動.md"
KINDS = {"table": "Table", "column": "Column", "index": "Index",
         "fk": "FK", "constraint": "Constraint", "extended_property": "Extended property"}
SENSITIVE = re.compile(r"password|passwd|pwd|token|secret|credential|connection.?string|api.?key|private.?key", re.I)


@dataclass
class OutputInventory:
    output_dir: Path
    files: dict


def _plain_path(value):
    path = Path(value)
    segments = [part for part in path.parts if part != path.anchor]
    if any(part.endswith((".", " ")) or ":" in part for part in segments):
        raise ValueError("Path traversal or alternate stream is not permitted")
    path = path.absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Linked paths are not permitted")
        if item.exists():
            info = item.stat()
            if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise ValueError("Reparse paths are not permitted")
            if item.is_file() and info.st_nlink != 1:
                raise ValueError("Hardlinked files are not permitted")
    return path


def _json(path):
    path = _plain_path(path)
    if not path.is_file():
        raise ValueError("Lifecycle evidence is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid lifecycle evidence") from None
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Invalid lifecycle evidence schema")
    return value


def _lifecycle(record):
    # Directly consumes the manifest Path returned by write_lifecycle_run.
    manifest = _plain_path(record)
    if manifest.is_dir():
        manifest = manifest / "lifecycle_exclusion_manifest.json"
    run = manifest.parent
    if (manifest.name != "lifecycle_exclusion_manifest.json"
            or run.parent.name != "runs" or run.parent.parent.name != ".release-docs"):
        raise ValueError("Lifecycle evidence must be inside its run")
    evidence = _json(manifest)
    exclusions = evidence.get("exclusions")
    if not isinstance(exclusions, list):
        raise ValueError("Lifecycle exclusions are missing")
    for exclusion in exclusions:
        if (not isinstance(exclusion, dict)
                or any(not isinstance(exclusion.get(k), list) or
                       any(not isinstance(v, str) for v in exclusion[k])
                       for k in ("issues", "unit_ids", "objects", "reinstatement_conditions"))
                or any(not isinstance(exclusion.get(k), str) or not exclusion[k].strip()
                       for k in ("reason", "operator_action"))):
            raise ValueError("Incomplete lifecycle exclusion")
    metadata = _json(run / "lifecycle_metadata.json")
    return exclusions, metadata


def _text(value):
    text = str(value)
    # Mask URL userinfo and credential assignments in examples and descriptions.
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text, flags=re.I)
    text = re.sub(r"((?:" + SENSITIVE.pattern + r")\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)",
                  r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"[0-9a-fA-F]{64}\b", "[INTERNAL HASH OMITTED]", text)
    return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|").replace("`", "\\`")


def _structure(analysis, excluded):
    included_units = [unit for unit in analysis.units if unit["unit_id"] not in excluded]
    included_ids = {unit["unit_id"] for unit in included_units}
    changes = getattr(analysis, "structure_changes", None)
    if changes is None:
        changes = []
    if not isinstance(changes, list):
        raise ValueError("Structure changes must be explicit descriptors")
    changes = list(changes)
    for unit in included_units:
        for change in unit.get("structure_changes", []):
            if not isinstance(change, dict):
                raise ValueError("Invalid structure change descriptor")
            descriptor = {**change, "unit_id": unit["unit_id"]}
            if descriptor not in changes:
                changes.append(descriptor)
    grouped = {kind: [] for kind in KINDS}
    unproven_scope = False
    for change in changes:
        if not isinstance(change, dict) or change.get("kind") not in KINDS:
            raise ValueError("Invalid structure change descriptor")
        if any(not isinstance(change.get(k), str) or not change[k].strip() for k in ("name", "description", "impact")):
            raise ValueError("Structure change requires scope, description and impact")
        unit_id = change.get("unit_id")
        if isinstance(unit_id, str) and unit_id in excluded:
            continue
        if not isinstance(unit_id, str) or unit_id not in included_ids:
            unproven_scope = True
            continue
        grouped[change["kind"]].append("- " + _text(change["name"]) + "：" + _text(change["description"]) + "；影響：" + _text(change["impact"]))
    lines = []
    for kind, label in KINDS.items():
        lines.append("### " + label + "\n\n" + ("\n".join(grouped[kind]) or "未提供此類結構異動範圍，待確認。"))
    if unproven_scope:
        lines.append("結構異動說明待確認：忽略缺少或無效單位來源的描述。")
    if not any(grouped.values()) and any(u["phase"] in ("SCHEMA", "REPAIR") for u in included_units):
        objects = sorted({obj for u in included_units if u["phase"] in ("SCHEMA", "REPAIR") for obj in u.get("objects", [])})
        lines.append("結構異動說明待確認；來源宣告物件：" + ("、".join(_text(obj) for obj in objects) or "待確認"))
    return "\n\n".join(lines)


def _exclusion_summary(exclusions):
    if not exclusions:
        return "Lifecycle 證據確認本次沒有排除範圍。"
    blocks = []
    for exclusion in exclusions:
        blocks.append("- 排除名稱：" + "、".join(_text(i) for i in exclusion["issues"]) +
                      "；原因：" + _text(exclusion["reason"]) +
                      "；影響範圍：" + "、".join(_text(o) for o in exclusion["objects"]) +
                      "；正式環境保留與操作：" + _text(exclusion["operator_action"]) +
                      "；重新納入前置條件：" + "、".join(_text(c) for c in exclusion["reinstatement_conditions"]))
    return "\n".join(blocks)


def _status(metadata, artifact, data_ids=()):
    validation = metadata.get("localdb_validation")
    status = "未執行"
    if isinstance(validation, dict):
        status = "未執行" if validation.get("status") == "not_run" else "待確認"
        if validation.get("status") == "failed":
            status = "未通過" if validation.get("artifact_sha256") == artifact.sha256 else "待確認"
        if (validation.get("status") == "passed" and validation.get("artifact_sha256") == artifact.sha256
                and _current_evidence_hash(validation.get("fixture_source"), validation.get("fixture_sha256"))
                and _current_evidence_hash(validation.get("fixture_manifest"), validation.get("fixture_manifest_sha256"))):
            rounds = validation.get("rounds", {})
            assertions = validation.get("expected_assertions")
            required = set()
            if data_ids:
                if isinstance(assertions, list) and assertions and all(
                        isinstance(item, dict) and item.get("unit_id") in data_ids
                        and isinstance(item.get("id"), str) and item["id"] for item in assertions) and {
                            item["unit_id"] for item in assertions} == data_ids:
                    required = {(item["unit_id"], item["id"]) for item in assertions}
                else:
                    rounds = {}
            fields = ("server", "database", "provider_version", "tool_version", "baseline_source",
                      "fixture_source", "command", "checks")
            preserved = validation.get("expected_preserved_data_summary")
            if (isinstance(rounds, dict) and all(
                    isinstance(rounds.get(name), dict) and rounds[name].get("status") == "passed"
                    and type(rounds[name].get("exit_code")) is int and rounds[name]["exit_code"] == 0
                    and isinstance(rounds[name].get("error_output_summary"), str)
                    and rounds[name].get("provider_version") not in ("unknown", "")
                    and rounds[name].get("tool_version") not in ("unknown", "")
                    and (name != "injected_failure" or bool(rounds[name]["error_output_summary"].strip()))
                    and all(rounds[name].get(k) for k in fields)
                    and isinstance(rounds[name].get("checks"), (list, dict))
                    and isinstance(preserved, dict) and bool(preserved)
                    and rounds[name].get("preserved_data_summary") == preserved
                    and rounds[name].get("fixture_source") == validation["fixture_source"]
                    and rounds[name].get("fixture_sha256") == validation["fixture_sha256"]
                    and rounds[name].get("fixture_manifest") == validation["fixture_manifest"]
                    and rounds[name].get("fixture_manifest_sha256") == validation["fixture_manifest_sha256"]
                    and rounds[name].get("artifact_sha256") == artifact.sha256
                    and _current_evidence_hash(rounds[name].get("baseline_source"), rounds[name].get("baseline_sha256"))
                    and (not required or required.issubset({(item.get("unit_id"), item.get("id"))
                         for item in (rounds[name].get("data_checks") if isinstance(rounds[name].get("data_checks"), list) else []) if isinstance(item, dict)
                         and isinstance(item.get("unit_id"), str) and isinstance(item.get("id"), str)
                         and item.get("passed") is True and "before" in item and "after" in item}))
                    for name in ("validate_only", "commit", "rerun", "injected_failure"))
                    and len({json.dumps(rounds[name]["checks"], sort_keys=True, ensure_ascii=True)
                             for name in ("validate_only", "commit", "rerun", "injected_failure")}) == 4
                    and _valid_round_identity(rounds)):
                status = "通過（隔離 evidence 已記錄）"
    return "SQL 內容審核：待確認（由獨立審核結果確認）。\n\nLocalDB：" + status + "。"


def _valid_round_identity(rounds):
    names = ("validate_only", "commit", "rerun", "injected_failure")
    sessions = [rounds[name].get("session_id") for name in names]
    databases = [rounds[name].get("database_id") for name in names]
    committed = rounds["commit"].get("committed_state")
    return (all(isinstance(value, str) and value.strip() for value in sessions + databases)
            and len(set(sessions)) == len(names)
            and len({databases[0], databases[1], databases[3]}) == 3
            and databases[2] == databases[1]
            and isinstance(committed, str) and bool(committed.strip())
            and rounds["rerun"].get("committed_state") == committed)


def _current_evidence_hash(source, expected):
    if (not isinstance(source, str) or not source or not isinstance(expected, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        return False
    try:
        path = _plain_path(source)
        return path.suffix.lower() in (".sql", ".dacpac", ".json") and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
    except (ValueError, OSError):
        return False


def _parameters(changes):
    if not isinstance(changes, list):
        raise ValueError("Parameter changes must be explicit descriptors")
    rows = ["| 環境 | 服務 | 完整設定鍵 | 格式範例 | 套用方式 | 重新載入要求 | 驗證 |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for change in sanitize_parameter_changes(changes):
        values = [change['environment'], change['service'], change['key'],
                  change.get('format_example', '待確認'), change.get('apply', '待確認'),
                  change.get('reload', '待確認'), change.get('validation', '待確認')]
        rows.append('| ' + ' | '.join(_text(value) for value in values) + ' |')
    return "\n".join(rows)


def _template(name, replacements):
    text = (Path(__file__).parents[1] / "assets" / name).read_text(encoding="utf-8")
    # One substitution pass keeps caller content from becoming template syntax.
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda match: replacements[match[1]], text).encode("utf-8")


def render_release_documents(analysis, deployment_artifact, lifecycle_record, output_dir) -> OutputInventory:
    """Render human documents and copy verified SQL, with preflight before writes.

    Optional analysis.structure_changes (or units[].structure_changes) contains
    kind/name/description/impact dictionaries; parameter_changes contains
    environment/service/key/format_example/apply/reload/validation dictionaries.
    Raw old/new/value fields are never output. lifecycle_record is Task 2's
    manifest Path or its run directory; exclusions are read from disk only.
    OutputInventory.files maps the delivered filenames to their SHA-256 hashes.
    """
    output = _plain_path(output_dir)
    parts = [p.casefold() for p in output.parts]
    if ".release-docs" in parts or any(parts[i:i + 2] == ["docs", "release-artifacts"] for i in range(len(parts) - 1)):
        raise ValueError("Operator output cannot use lifecycle or legacy artifact directories")
    if output.exists() and not output.is_dir():
        raise ValueError("Operator output must be a directory")
    if analysis.blocked or any(f.get("blocking") for f in deployment_artifact.findings):
        raise ValueError("Blocking findings prevent operator delivery")
    exclusions, metadata = _lifecycle(lifecycle_record)
    source = _plain_path(deployment_artifact.path)
    if source.name != SQL or not source.is_file():
        raise ValueError("Deployment artifact is missing or incorrectly named")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != deployment_artifact.sha256:
        raise ValueError("Deployment artifact fingerprint changed")
    excluded = {uid for exclusion in exclusions for uid in exclusion["unit_ids"]}
    expected = {u["unit_id"]: u for u in analysis.units if u["unit_id"] not in excluded}
    mappings = deployment_artifact.unit_mapping
    if (len(mappings) != len(expected) or {m["unit_id"] for m in mappings} != set(expected)
            or any(m["source_hash"] != expected[m["unit_id"]]["source_hash"] or
                   m["sql_hash"] != expected[m["unit_id"]]["sql_hash"] for m in mappings)):
        raise ValueError("Deployment artifact does not match included analysis units")
    scope = analysis.source_scope
    scope_text = ("Release：" + _text(deployment_artifact.release_id) + "\n\n來源 revision：" +
                  _text(str(scope.get("base_sha", "待確認"))[:12]) + " → " +
                  _text(str(scope.get("target_sha", "待確認"))[:12]) + "\n\n舊版結構來源：" +
                  _text(str(analysis.baseline.get("source_path", "待確認")).replace("\\", "/").rsplit("/", 1)[-1]))
    documents = {SQL: data, GUIDE: _template(GUIDE, {
        "SCOPE": scope_text, "STRUCTURE": _structure(analysis, excluded),
        "EXCLUSIONS": _exclusion_summary(exclusions),
        "MODE": ("ValidateOnly=1（未設定 SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly') 時）；"
                 "只有在同一新 session 執行 `EXEC sys.sp_set_session_context "
                 "@key = N'ReleaseDocs.ValidateOnly', @value = 0;` 才可提交"),
        "STATUS": _status(metadata, deployment_artifact,
                          {uid for uid, unit in expected.items() if unit.get("phase") == "DATA"})})}
    changes = getattr(analysis, "parameter_changes", [])
    parameters = _parameters(changes)
    if changes:
        documents[PARAMETERS] = _template(PARAMETERS, {"PARAMETERS": parameters})
    if output.exists():
        for path in output.iterdir():
            _plain_path(path)
            if path.name not in documents or not path.is_file():
                raise ValueError("Undeclared files or directories in operator output")
    # Check every destination before any write. Do not replace or follow links.
    for name in documents:
        destination = _plain_path(output / name)
        if destination.exists() and destination.read_bytes() != documents[name]:
            raise ValueError("Existing operator files differ; use a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    for name, content in documents.items():
        destination = output / name
        if destination.exists():
            if destination.read_bytes() != content:
                raise ValueError("Existing operator files differ; use a fresh output directory")
        else:
            with destination.open("xb") as stream:
                stream.write(content)
    return OutputInventory(output.resolve(), {name: hashlib.sha256(content).hexdigest() for name, content in documents.items()})

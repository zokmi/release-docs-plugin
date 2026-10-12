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
from parameter_metadata import redact_text, sanitize_parameter_changes, SENSITIVE as PARAMETER_SENSITIVE
from evidence_redaction import redact_text as redact_evidence_text, normalize_secrets, _BEARER

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
            # Non-mutating units have no row snapshot to repeat in each round.
            # Accept that explicit N/A contract only when the runner recorded
            # per-unit impact and source-located preservation evidence.
            impacts = validation.get("data_impact")
            preservation = validation.get("preservation")
            na_preservation = (
                isinstance(impacts, dict) and bool(impacts)
                and all(value == "non_mutating" for value in impacts.values())
                and isinstance(preservation, dict)
                and set(preservation) == set(impacts)
                and all(isinstance(item, dict) and item.get("conclusion") == "N/A"
                        and isinstance(item.get("reason"), str)
                        and re.search(r"no existing (?:persistent )?rows? mutations?|無既有資料列異動",
                                      item["reason"], re.I)
                        and re.search(r"[^\s:]+:\d+", item["reason"])
                        for item in preservation.values())
            )
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
                    and (rounds[name].get("preserved_data_summary") == preserved
                         or (na_preservation and rounds[name].get("preserved_data_summary") in ({}, None)))
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


def _safe_parameter_key(value, secrets=()):
    # Configuration identifiers such as Auth:JwtSecret are not assignments.
    return _BEARER.sub(lambda match: match.group(1) + '[REDACTED]',
                       redact_text(value, secrets))


def _safe_parameter_value(value, secrets=()):
    """Keep JSON types while removing credentials from every output surface."""
    if isinstance(value, str):
        value = redact_evidence_text(redact_text(value, secrets), secrets)
        return re.sub(r"([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@",
                      r"\1[REDACTED]@", value, flags=re.I)
    if isinstance(value, list):
        return [_safe_parameter_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_safe_parameter_key(key, secrets):
                ("[REDACTED]" if PARAMETER_SENSITIVE.search(str(key)) else
                 _safe_parameter_value(item, secrets))
                for key, item in value.items()}
    return value


def _nested_parameter_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if PARAMETER_SENSITIVE.search(str(key)) and isinstance(item, str) and item:
                yield item
            else:
                yield from _nested_parameter_secrets(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_parameter_secrets(item)


def _source_reference(value, secrets):
    if not isinstance(value, dict):
        return _safe_parameter_value(value, secrets) if value is not None else "待確認"
    # Discovery references can carry full source bytes. Only provenance belongs here.
    return {role: ({field: _safe_parameter_value(source[field], secrets)
                    for field in ("path", "revision", "line") if field in source}
                   if isinstance(source, dict) else None)
            for role, source in value.items() if role in ("base", "target")}


def _parameter_projection(changes, secrets=()):
    if not isinstance(changes, list):
        raise ValueError("Parameter changes must be explicit descriptors")
    supplied_secrets = normalize_secrets(secrets)
    secrets = {value for item in changes if isinstance(item, dict)
               and (PARAMETER_SENSITIVE.search(str(item.get("key", ""))) or item.get("sensitive") is True)
               for field in ("value", "raw_value", "old_value", "new_value", "format_example")
               for value in [item.get(field)] if isinstance(value, str) and value}
    secrets.update(supplied_secrets)
    secrets.update(secret for item in changes if isinstance(item, dict)
                   for field in ("value", "raw_value", "old_value", "new_value", "target_config")
                   for secret in _nested_parameter_secrets(item.get(field)))
    safe_input = [{key: value for key, value in item.items() if key != "source_reference"}
                  if isinstance(item, dict) else item for item in changes]
    base = sanitize_parameter_changes(safe_input)
    projected = []
    for raw, clean in zip(changes, base):
        item = {key: (_safe_parameter_key(value, secrets) if key == 'key'
                      else _safe_parameter_value(value, secrets)) for key, value in clean.items()}
        item["change"] = _safe_parameter_value(raw.get("change", "待確認"), secrets)
        item["source_reference"] = _source_reference(raw.get("source_reference"), secrets)
        if "target_config" in raw:
            if not isinstance(raw["target_config"], dict):
                raise ValueError("Target configuration context must be a JSON object")
            item["target_config"] = _safe_parameter_value(raw["target_config"], secrets)
        for field in ("old_value", "new_value"):
            if field in raw:
                item[field] = ("[REDACTED]" if item["sensitive"]
                               else _safe_parameter_value(raw[field], secrets))
        if "new_value" not in item and "value" in raw and item["change"] != "remove":
            item["new_value"] = ("[REDACTED]" if item["sensitive"]
                                 else _safe_parameter_value(raw["value"], secrets))
        for field in ("parameter_group", "business_context", "module", "users", "impact",
                      "environment_variable"):
            value = raw.get(field)
            item[field] = (_safe_parameter_value(value, secrets)
                           if isinstance(value, str) and value.strip() else "待確認")
        projected.append(item)
    return projected


def _source_label(reference):
    if isinstance(reference, str):
        return reference
    return "; ".join(f"{role}:{source.get('path', '待確認')}:{source.get('line', '待確認')}"
                     for role, source in reference.items() if source) or "待確認"


def _json_block(value):
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


_ARRAY_GAP = object()


def _insert_config(root, key, value):
    parts = key.split(":")
    cursor = root
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        slot = int(part) if isinstance(cursor, list) else part
        if isinstance(cursor, list):
            while len(cursor) <= slot:
                cursor.append(_ARRAY_GAP)
        if last:
            cursor[slot] = value
        else:
            # Legacy paths cannot prove whether a numeric segment is an array index.
            following = {}
            if isinstance(cursor, list):
                if cursor[slot] is _ARRAY_GAP:
                    cursor[slot] = following
            else:
                cursor.setdefault(slot, following)
            cursor = cursor[slot]


def _safe_config_shape(value):
    """Expose sparse arrays by index without suggesting null padding is deployable."""
    if isinstance(value, dict):
        children = {key: _safe_config_shape(item) for key, item in value.items()}
        return {key: item for key, (item, _) in children.items()}, any(
            pending for _, pending in children.values())
    if isinstance(value, list):
        sparse = _ARRAY_GAP in value
        children = [(index, _safe_config_shape(item)) for index, item in enumerate(value)
                    if item is not _ARRAY_GAP]
        pending = sparse or any(flag for _, (_, flag) in children)
        if sparse:
            return {str(index): item for index, (item, _) in children}, pending
        return [item for _, (item, _) in children], pending
    return value, False


def _merge_config(root, fragment):
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(root.get(key), dict):
            _merge_config(root[key], value)
        else:
            root[key] = value


def _parameters(changes, analysis, artifact):
    descriptors = _parameter_projection(changes)
    paths = sorted({source["path"] for item in descriptors
                    if isinstance(item["source_reference"], dict)
                    for source in item["source_reference"].values()
                    if source and isinstance(source.get("path"), str)})
    scope = analysis.source_scope
    source_scope = ("Release：" + _text(artifact.release_id) + "；base → target：" +
                    _text(scope.get("base_sha", "待確認")) + " → " +
                    _text(scope.get("target_sha", "待確認")) + "\n\n設定來源：" +
                    ("、".join(_text(path) for path in paths) or "待確認"))
    mapping = ["| 參數區塊 | 使用業務情境 | 使用模組／功能 | 主要使用者 | 異動影響 |",
               "| --- | --- | --- | --- | --- |"]
    groups = {}
    for item in descriptors:
        identity = (item["environment"], item["service"], item["parameter_group"])
        groups.setdefault(identity, []).append(item)
    def label(identity):
        return json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    for identity, items in groups.items():
        mapping.append("| " + " | ".join(_text(value) for value in (
            label(identity), items[0]["business_context"], items[0]["module"],
            items[0]["users"], items[0]["impact"])) + " |")
    rows = ["| 環境 | 服務 | 完整設定鍵 | 異動類型 | 前值 → 後值 | 格式範例 | 套用方式 | 重新載入要求 | 驗證 | 來源 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in descriptors:
        before = item.get("old_value", "—")
        after = item.get("new_value", "—")
        rows.append("| " + " | ".join(_text(value) for value in (
            item["environment"], item["service"], item["key"], item["change"],
            f"{before} → {after}", item.get("format_example", "待確認"),
            item.get("apply", "待確認"), item.get("reload", "待確認"),
            item.get("validation", "待確認"), _source_label(item["source_reference"]))) + " |")
    sections = ["\n".join(rows)]
    checklist = ["1. 核對 release、base/target 與設定來源，確認完整設定鍵及異動類型。"]
    for number, (identity, items) in enumerate(groups.items(), 2):
        name = label(identity)
        config = {}
        legacy_numeric = False
        for item in items:
            if "target_config" in item:
                _merge_config(config, item["target_config"])
            elif item["change"] != "remove":
                _insert_config(config, item["key"], item.get("new_value", "[待確認]"))
                legacy_numeric |= any(part.isdigit() for part in item["key"].split(":"))
        config, partial = _safe_config_shape(config)
        summary = "；".join(_text(item["change"] + " " + item["key"]) for item in items)
        instructions = "\n".join("- " + _text(item["key"]) + "：用途／行為影響 " +
                                 _text(item["impact"]) + "；套用 " +
                                 _text(item.get("apply", "待確認")) + "；重新載入／重啟 " +
                                 _text(item.get("reload", "待確認")) + "；驗證 " +
                                 _text(item.get("validation", "待確認"))
                                 for item in items)
        env = [item["environment_variable"] + "=" + str(item.get("new_value", "[待確認]"))
               for item in items if item["environment_variable"] != "待確認"
               and item["change"] != "remove"]
        config_note = ("部分設定 JSON：原始容器型別與完整陣列待確認，以索引物件顯示；不可直接套用，亦不可取代陣列，"
                       "請核對完整陣列後再設定。" if legacy_numeric else
                      "部分設定 JSON：陣列索引不連續，缺少的項目待確認；此區塊不可直接套用，"
                       "請核對完整陣列後再設定。" if partial else
                       "可複製設定 JSON（remove 項請從設定來源刪除）：")
        section = ("### " + _text(name) + "\n\n異動摘要：" + summary +
                   "\n\n完整設定鍵、用途與操作：\n\n" + instructions +
                   "\n\n" + config_note + "\n\n" + _json_block(config))
        if env:
            section += "\n\n環境變數／部署平台覆寫範例：\n\n```text\n" + "\n".join(env) + "\n```"
        sections.append(section)
        checklist.append(str(number) + ". 核對 " + _text(name) + " 的設定來源與機密值注入；依上節 reload／重啟要求操作，逐項執行驗證。")
    checklist.append(str(len(checklist) + 1) + ". 未核准或待確認的值維持安全預設／暫不套用；保存不含機密原值的驗證紀錄。")
    return {"SCOPE": source_scope, "MAPPING": "\n".join(mapping),
            "PARAMETERS": "\n\n".join(sections), "CHECKLIST": "\n".join(checklist),
            "DESCRIPTORS": _json_block(descriptors)}


def _change_tables(analysis, excluded):
    """Render auditable structure/data effect tables from explicit descriptors."""
    structure = ["| 物件／欄位 | 異動類型 | 異動前 → 異動後 | 目的與功能影響 | 資料保留／相依注意事項 | 來源定位 |",
                 "| --- | --- | --- | --- | --- | --- |"]
    included = {unit["unit_id"] for unit in analysis.units if unit["unit_id"] not in excluded}
    structure_changes = list(getattr(analysis, "structure_changes", []) or [])
    data_changes = list(getattr(analysis, "data_changes", []) or [])
    for unit in analysis.units:
        if unit["unit_id"] in included:
            structure_changes.extend({**change, "unit_id": unit["unit_id"]}
                                     for change in unit.get("structure_changes", []))
            data_changes.extend({**change, "unit_id": unit["unit_id"]}
                                for change in unit.get("data_changes", []))
    for change in structure_changes:
        if change.get("unit_id") not in included:
            continue
        structure.append("| " + " | ".join(_text(change.get(key, "待確認")) for key in (
            "name", "kind", "before_after", "impact", "preservation", "source_location")) + " |")
    if len(structure) == 2:
        structure.append("| 待確認 | 待確認 | 待確認 | 尚未取得可核對的結構異動描述 | 待確認 | 待確認 |")
    data = ["| 資料對象 | 操作與觸發條件 | 異動前 → 預期異動後 | 保留／清除範圍與風險 | 部署後查核 | 來源定位 |",
            "| --- | --- | --- | --- | --- | --- |"]
    for change in data_changes:
        if change.get("unit_id") not in included:
            continue
        data.append("| " + " | ".join(_text(change.get(key, "待確認")) for key in (
            "object", "operation_condition", "before_after", "preservation", "validation", "source_location")) + " |")
    if len(data) == 2:
        data.append("| 待確認 | 尚未取得可核對的持久資料異動描述 | 待確認 | 待確認 | 待確認 | 待確認 |")
    return "\n".join(structure), "\n".join(data)


def _template(name, replacements):
    text = (Path(__file__).parents[1] / "assets" / name).read_text(encoding="utf-8")
    # One substitution pass keeps caller content from becoming template syntax.
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda match: replacements[match[1]], text).encode("utf-8")


def render_release_documents(analysis, deployment_artifact, lifecycle_record, output_dir) -> OutputInventory:
    """Render human documents and copy verified SQL, with preflight before writes.

    Optional analysis.structure_changes (or units[].structure_changes) contains
    kind/name/description/impact dictionaries; parameter_changes contains
    environment/service/key/format_example/apply/reload/validation dictionaries.
    Old/new/value fields are redacted before output. lifecycle_record is Task 2's
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
    structure_table, data_table = _change_tables(analysis, excluded)
    documents = {SQL: data, GUIDE: _template(GUIDE, {
        "SCOPE": scope_text, "STRUCTURE": _structure(analysis, excluded),
        "STRUCTURE_TABLE": structure_table, "DATA_TABLE": data_table,
        "EXCLUSIONS": _exclusion_summary(exclusions),
        "MODE": ("database_tool_minimal（由受控資料庫工具傳入 validate-only／commit，SQL 不含 session SET）；"
                 "framework fallback 才使用 ValidateOnly=1／ValidateOnly=0、SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly') "
                 "及 `sp_set_session_context`"
                 if getattr(deployment_artifact, "transaction_mode", "framework") == "database_tool_minimal"
                 else "framework fallback：ValidateOnly=1（未設定 SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly') 時）；"
                 "ValidateOnly=0 僅在同一新 session 明確設定後允許提交；"
                 "只有在同一新 session 執行 `EXEC sys.sp_set_session_context "
                 "@key = N'ReleaseDocs.ValidateOnly', @value = 0;` 才可提交"),
        "STATUS": _status(metadata, deployment_artifact,
                          {uid for uid, unit in expected.items() if unit.get("phase") == "DATA"})})}
    changes = getattr(analysis, "parameter_changes", [])
    if changes:
        documents[PARAMETERS] = _template(PARAMETERS, _parameters(changes, analysis, deployment_artifact))
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

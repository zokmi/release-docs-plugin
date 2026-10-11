"""Review operator inventory against lifecycle truth; never execute SQL.

Returns findings followed by SQL-content and deployment-validation status
records. Static passing does not establish provider compatibility or runtime
rollback, commit, convergence or data preservation. LocalDB evidence is separate.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile

_fingerprint_path = Path(__file__).with_name("review_fingerprint.py")
_fingerprint_spec = importlib.util.spec_from_file_location("release_docs_review_fingerprint", _fingerprint_path)
_fingerprint = importlib.util.module_from_spec(_fingerprint_spec)
sys.modules[_fingerprint_spec.name] = _fingerprint
_fingerprint_spec.loader.exec_module(_fingerprint)
OPERATOR_FILES = _fingerprint.OPERATOR_FILES
execution_path = _fingerprint.execution_path
file_hash = _fingerprint.file_hash
lifecycle_root = _fingerprint.lifecycle_root
plain_path = _fingerprint.plain_path
read_json = _fingerprint.read_json

# Load the assembler's public static validator, including when invoked directly.
sys.path.insert(0, str(Path(__file__).parents[2] / "release-docs/scripts"))
from assemble_deployment_sql import (PHASES, _dynamic_ddl_provider_sql, _generated_units,
                                     _lex, _metadata_provider_sql, validate_sql_contract)

Finding = dict
STATUSES = ("通過", "待確認", "未通過")
REPORT_CODES = frozenset("""
undeclared_output missing_operator_file unsafe_review_path missing_lifecycle_evidence
invalid_lifecycle_exclusions missing_parameter_document unexpected_parameter_document
parameter_applicability_unknown conflicting_parameter_applicability unreadable_operator_file
missing_execution_artifact_evidence execution_artifact_mismatch unsafe_or_missing_execution_artifact
invalid_unit_evidence blocking_source_analysis excluded_dependency unresolved_dependency
missing_or_unordered_phases excluded_object_in_sql invalid_unit_mapping excluded_unit_in_sql
unexpected_or_duplicate_unit unit_dependency_order unit_mapping_mismatch unit_phase_mismatch
incomplete_unit_mapping missing_unit_context unit_context_mismatch unit_sql_hash_mismatch
unit_sql_descriptor_mismatch
rerun_risk included_unit_mapping_mismatch duplicate_column guide_exclusion_mismatch
missing_data_expectations
incomplete_deployment_evidence unsupported_deployment_pass_claim deployment_proved_sql_defect
semantic_review_pending semantic_sql_defect invalid_finding
batch_separator non_transactional_sql batch_only_sql early_exit database_switch opaque_execution
cross_database_reference
unit_transaction_control reserved_context_mutation implicit_transactions_enabled xact_abort_disabled
execution_disabled malformed_sql_lexeme silent_catch raiserror_without_throw missing_xact_abort
missing_try_catch transaction_count missing_implicit_transactions_off unconditional_transaction_start
validate_only_rollback deploy_commit missing_throw transaction_scope error_rollback missing_error_context
missing_transaction_action unmapped_sql invalid_exclusion_provenance
invalid_runtime_mode sql_profile_mismatch invalid_sql_profile nonessential_set_statement
business_data_validation validation_sql_defect validation_sql_pending
transaction_validation_pending fixture_assertion_defect fixture_assertion_pending
""".split())
SQL_CORRECTNESS_CODES = REPORT_CODES - {
    "business_data_validation", "incomplete_deployment_evidence", "unsupported_deployment_pass_claim"
} | frozenset("""
duplicate_unit_id phase_dependency_conflict dependency_cycle_or_missing_unit
unresolved_exclusion partial_exclusion unresolved_ef_detection missing_pinned_source_scope
incomplete_migration_chain stale_ef_detection model_drift_without_migration missing_model_snapshot
baseline_model_conflict unsupported_migration_operation missing_baseline_schema
unsupported_migration_definition partial_execution_artifact missing_authoritative_sql
deleted_source_requires_execution_artifact incomplete_unit
""".split())


def _finding(code, blocking=True, domain="sql_correctness", status=None):
    if isinstance(code, str) and code in SQL_CORRECTNESS_CODES or domain == "sql_content":
        domain = "sql_correctness"
    if domain == "business_data_validation":
        blocking = False
        status = "通過" if status == "通過" else "待確認"
    return {"code": code, "blocking": blocking, "domain": domain,
            "status": status or ("未通過" if blocking else "待確認")}


def _summary(findings, deployment="待確認", semantic_complete=False):
    findings = [{**f, **_finding(f["code"], f["blocking"], f["domain"], f.get("status"))} for f in findings]
    sql = [f for f in findings if f["domain"] == "sql_correctness"]
    status = "未通過" if any(f["blocking"] for f in sql) else "待確認" if sql else "通過"
    static_status = status
    if status == "通過" and not semantic_complete:
        status = "待確認"
    return findings + [_finding("static_sql_status", static_status == "未通過", status=static_status),
                       _finding("sql_content_status", status == "未通過", status=status),
                       _finding("deployment_validation_status", deployment == "未通過",
                                domain="deployment_validation", status=deployment)]


ROUND_NAMES = ("validate_only", "commit", "rerun", "injected_failure")


def _non_mutating_preservation(units, summary, preservation):
    """N/A is an explicit per-unit source review, never an actual data result."""
    from semantic_review import classify_data_impact, _preservation
    if (not isinstance(units, (list, tuple)) or not units
            or any(not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str)
                   or not unit["unit_id"] for unit in units)):
        return False
    ids = {unit["unit_id"] for unit in units}
    for unit in units:
        candidates = []
        if isinstance(unit.get("sql"), str):
            candidates.append(unit["sql"])
        definition = unit.get("target_definition")
        if isinstance(definition, dict) and isinstance(definition.get("sql"), str):
            candidates.append(definition["sql"])
        declared = unit.get("sql_hash")
        if isinstance(declared, str) and any(
                declared not in {hashlib.sha256(value.encode("utf-8")).hexdigest(),
                                 hashlib.sha256(value.replace("\r\n", "\n").encode("utf-8")).hexdigest()}
                for value in candidates):
            return False
    return (len(ids) == len(units) and summary == {uid: "N/A" for uid in ids}
            and isinstance(preservation, dict) and set(preservation) == ids
            and all(classify_data_impact(unit) == "non_mutating"
                    and isinstance(preservation[unit["unit_id"]], dict)
                    and preservation[unit["unit_id"]].get("conclusion") == "N/A"
                    and _preservation(preservation[unit["unit_id"]], unit, "non_mutating")
                    for unit in units))


def _data_expectations(source, exclusions, units_override=None):
    from semantic_review import classify_data_impact
    excluded = {uid for item in exclusions for uid in item["unit_ids"]}
    units = units_override if units_override is not None else source.get("units", [])
    if not isinstance(units, list):
        return {}, False
    expected = {}
    for unit in units:
        if not isinstance(unit, dict):
            return {}, False
        descriptors = []
        if isinstance(unit.get("sql"), str):
            descriptors.append(unit["sql"])
        definition = unit.get("target_definition")
        if isinstance(definition, dict) and isinstance(definition.get("sql"), str):
            descriptors.append(definition["sql"])
        if len(descriptors) > 1 and any(descriptors[0].replace("\r\n", "\n")
                                       != value.replace("\r\n", "\n") for value in descriptors[1:]):
            return {}, False
        impact = classify_data_impact(unit)
        if impact == "non_mutating" or (impact != "mutation" and unit.get("phase") != "DATA"):
            continue
        uid = unit.get("unit_id")
        if not isinstance(uid, str):
            return {}, False
        if uid in excluded:
            continue
        rows = unit.get("expected_assertions")
        if not isinstance(rows, list) or not rows:
            return {}, False
        if (any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows)
                or len({row["id"] for row in rows}) != len(rows)):
            return {}, False
        expected[uid] = rows
        for row in rows:
            by_round = row.get("expected_by_round") if isinstance(row, dict) else None
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                    or not isinstance(row.get("seed_row_id"), str) or not row["seed_row_id"]
                    or not isinstance(by_round, dict) or set(by_round) != set(ROUND_NAMES)
                    or any(not isinstance(by_round[name], dict)
                           or "before" not in by_round[name] or "after" not in by_round[name]
                           for name in ROUND_NAMES)):
                return {}, False
    return expected, True


def _authenticated_units(sql, source, exclusions, profile):
    """Return source units whose SQL is the authenticated artifact body."""
    generated, _ = _artifact_units(sql, profile)
    bodies = {mapping.get("unit_id"): body for mapping, body in generated}
    excluded = {uid for item in exclusions for uid in item["unit_ids"]}
    result = []
    for unit in source.get("units", []):
        uid = unit.get("unit_id") if isinstance(unit, dict) else None
        if uid in excluded or uid not in bodies:
            continue
        result.append({**unit, "sql": bodies[uid]})
    return result


def _deployment(metadata, digest, source=None, exclusions=(), run=None, execution_units=None):
    validation = metadata.get("localdb_validation")
    if not isinstance(validation, dict):
        return "待確認"
    if validation.get("artifact_sha256") != digest:
        return "待確認"
    if validation.get("status") == "failed":
        return "未通過"
    if validation.get("status") != "passed":
        return "待確認"
    fixture = validation.get("fixture_source")
    fixture_hash = validation.get("fixture_sha256")
    fixture_manifest = validation.get("fixture_manifest")
    fixture_manifest_hash = validation.get("fixture_manifest_sha256")
    if (not _current_evidence_hash(fixture, fixture_hash, run)
            or not isinstance(fixture_manifest, str) or not fixture_manifest.lower().endswith(".json")
            or not _current_evidence_hash(fixture_manifest, fixture_manifest_hash, run)):
        return "待確認"
    rounds = validation.get("rounds")
    if not isinstance(rounds, dict):
        return "待確認"
    data_units, valid_expectations = _data_expectations(source, exclusions)
    if not valid_expectations:
        return "待確認"
    excluded = {uid for item in exclusions for uid in item["unit_ids"]}
    included = execution_units if execution_units is not None else [
        unit for unit in source.get("units", []) if unit.get("unit_id") not in excluded]
    assertions = validation.get("expected_assertions")
    if data_units and (not isinstance(assertions, list) or not assertions
                       or any(not isinstance(item, dict) or item.get("unit_id") not in data_units
                              or not isinstance(item.get("id"), str) or not item["id"] for item in assertions)
                       or {item["unit_id"] for item in assertions} != set(data_units)):
        return "待確認"
    required = {(item["unit_id"], item["id"]): item for item in assertions} if data_units else {}
    if data_units:
        if len(required) != len(assertions):
            return "待確認"
        for uid, rows in data_units.items():
            for row in rows:
                actual = required.get((uid, row["id"]))
                if (not isinstance(actual, dict) or any(actual.get(key) != row.get(key)
                                                       for key in ("seed_row_id", "expected_by_round"))):
                    return "待確認"
        if any(not isinstance(item.get("seed_row_id"), str) or not item["seed_row_id"]
               or not isinstance(item.get("expected_by_round"), dict)
               or set(item["expected_by_round"]) != set(ROUND_NAMES)
               or any(not isinstance(item["expected_by_round"].get(name), dict)
                      or "before" not in item["expected_by_round"][name]
                      or "after" not in item["expected_by_round"][name] for name in ROUND_NAMES)
               for item in assertions):
            return "待確認"
    text_fields = ("server", "database", "provider_version", "tool_version", "baseline_source", "fixture_source")
    sessions, databases, check_sets = set(), {}, set()
    for name in ROUND_NAMES:
        evidence = rounds.get(name)
        if (not isinstance(evidence, dict) or evidence.get("status") != "passed"
                or type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0
                or any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in text_fields)
                or not isinstance(evidence.get("command"), (str, list)) or not evidence["command"]
                or not isinstance(evidence.get("checks"), (list, dict)) or not evidence["checks"]
                or not isinstance(evidence.get("error_output_summary"), str)
                or evidence.get("provider_version") in (None, "", "unknown")
                or evidence.get("tool_version") in (None, "", "unknown")
                or (name == "injected_failure" and not evidence["error_output_summary"].strip())):
            return "待確認"
        if (evidence.get("fixture_source") != fixture
                or evidence.get("fixture_sha256") != fixture_hash
                or evidence.get("fixture_manifest") != fixture_manifest
                or evidence.get("fixture_manifest_sha256") != fixture_manifest_hash
                or evidence.get("artifact_sha256") != digest
                or not _current_evidence_hash(evidence.get("baseline_source"), evidence.get("baseline_sha256"), run)
                or evidence.get("round") != name
                or not isinstance(evidence.get("session_id"), str) or not evidence["session_id"]
                or evidence["session_id"] in sessions
                or not isinstance(evidence.get("database_id"), str) or not evidence["database_id"]):
            return "待確認"
        summary = evidence.get("expected_preserved_data_summary")
        if (not _non_mutating_preservation(included, summary, evidence.get("preservation"))
                and (not isinstance(summary, dict) or not summary
                     or any(value == "N/A" for value in summary.values())
                     or evidence.get("preserved_data_summary") != summary)):
            return "待確認"
        sessions.add(evidence["session_id"])
        databases[name] = evidence["database_id"]
        checks_key = json.dumps(evidence["checks"], sort_keys=True, ensure_ascii=True)
        if checks_key in check_sets:
            return "待確認"
        check_sets.add(checks_key)
        if data_units:
            checks = evidence.get("data_checks")
            observed = {(item.get("unit_id"), item.get("id")): item for item in checks
                        if isinstance(item, dict) and isinstance(item.get("unit_id"), str)
                        and isinstance(item.get("id"), str)} if isinstance(checks, list) else {}
            if any((key not in observed or observed[key].get("passed") is not True
                    or observed[key].get("seed_row_id") != expectation["seed_row_id"]
                    or any(observed[key].get(field) != expectation["expected_by_round"][name][field]
                           for field in ("before", "after"))) for key, expectation in required.items()):
                return "待確認"
    if (databases["rerun"] != databases["commit"]
            or len({databases["validate_only"], databases["commit"], databases["injected_failure"]}) != 3
            or not isinstance(rounds["commit"].get("committed_state"), str)
            or not rounds["commit"]["committed_state"]
            or rounds["rerun"].get("committed_state") != rounds["commit"]["committed_state"]):
        return "待確認"
    return "通過"


def _current_evidence_hash(source, expected, run):
    if not isinstance(source, str) or not source or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    try:
        path = plain_path(source)
        if run is None or not path.is_relative_to(run) or path.suffix.lower() not in (".sql", ".dacpac", ".json"):
            return False
        return file_hash(path) == expected
    except (ValueError, OSError):
        return False


def _visible_sql(text):
    """Preserve quoted identifiers while masking comments and string values."""
    code, _ = _lex(text)
    chars = list(code)
    # Only restore bracket names when the bracket occurs in code, not a string
    # or comment. A small scanner determines lexical context independently.
    pattern = r'''--[^\r\n]*|/\*|N?'(?:''|[^'])*'|\[(?:\]\]|[^\]])*\]|"(?:""|[^"])*"'''
    index = 0
    while index < len(text):
        match = re.search(pattern, text[index:], re.I)
        if match is None:
            break
        start, end = index + match.start(), index + match.end()
        token = text[start:end]
        if token == "/*":
            depth, end = 1, end
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif text.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
        elif token.startswith(("[", '"')):
            restored = " " + token[1:-1].replace("]]", "]").replace('""', '"') + " "
            # Identifiers are limited by unit metadata to simple ASCII names.
            if len(restored) == end - start:
                chars[start:end] = restored.upper()
        index = end
    return "".join(chars)


def _projection(exclusions):
    # Same public operator fields as Task 4, independently checked here.
    from render_release_documents import _text
    lines = []
    for item in exclusions:
        lines.append("- 排除名稱：" + "、".join(_text(v) for v in item["issues"]) +
                     "；原因：" + _text(item["reason"]) +
                     "；影響範圍：" + "、".join(_text(v) for v in item["objects"]) +
                     "；正式環境保留與操作：" + _text(item["operator_action"]) +
                     "；重新納入前置條件：" + "、".join(_text(v) for v in item["reinstatement_conditions"]))
    return "\n".join(lines) if lines else "Lifecycle 證據確認本次沒有排除範圍。"


def _rerun_risk(body):
    code, _ = _lex(body)
    guards = (
        (r"\bCREATE\s+TABLE\b", r"\bIF\s+(?:OBJECT_ID\s*\([^;]*?\)\s+IS\s+NULL|NOT\s+EXISTS\s*\([^;]*?\bSYS\s*\.\s*TABLES\b)"),
        (r"\bCREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\b", r"\bIF\s+NOT\s+EXISTS\s*\([^;]*?\bSYS\s*\.\s*INDEXES\b"),
        (r"\bALTER\s+TABLE\b[^;]*\bADD\b", r"\bIF\s+(?:COL_LENGTH\s*\([^;]*?\)\s+IS\s+NULL|NOT\s+EXISTS\s*\([^;]*?\bSYS\s*\.\s*(?:COLUMNS|FOREIGN_KEYS|KEY_CONSTRAINTS|CHECK_CONSTRAINTS|DEFAULT_CONSTRAINTS)\b)"),
        (r"\bINSERT\s+(?:INTO\s+)?", r"\bIF\s+NOT\s+EXISTS\s*\("),
    )
    return any(re.search(mutation, code) and not re.search(guard, code) for mutation, guard in guards)


def _minimal_units(sql):
    """Parse comment-delimited units emitted by database_tool_minimal."""
    findings, parsed, current_phase, seen = [], [], None, set()
    lines = sql.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        phase = re.fullmatch(r"-- PHASE: ([^\r\n]+)\r?\n?", line)
        if phase:
            current_phase = phase.group(1)
            index += 1
            continue
        if line.startswith("-- Unified deployment:") or not line.strip():
            index += 1
            continue
        if not line.startswith("-- UNIT: "):
            findings.append(_finding("unmapped_sql"))
            index += 1
            continue
        try:
            mapping = json.loads(line[len("-- UNIT: "):].strip())
            required = {"unit_id", "phase", "source_path", "source_revision", "source_hash",
                        "sql_hash", "source_line", "source_end_line", "depends_on"}
            if (not isinstance(mapping, dict) or not required.issubset(mapping)
                    or set(mapping) - required - {"provider_kind"}
                    or mapping["phase"] != current_phase or mapping["unit_id"] in seen):
                raise ValueError()
        except (ValueError, TypeError, json.JSONDecodeError):
            findings.append(_finding("invalid_unit_mapping"))
            index += 1
            continue
        index += 1
        body = []
        terminator = "-- END UNIT: " + mapping["unit_id"] + "\n"
        while index < len(lines) and lines[index] != terminator:
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            findings.append(_finding("unmapped_sql"))
            break
        source = "".join(body)
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != mapping.get("sql_hash"):
            findings.append(_finding("unit_sql_hash_mismatch"))
        if mapping.get("source_end_line") != mapping.get("source_line", 0) + len(source.splitlines()) - 1:
            findings.append(_finding("unit_sql_hash_mismatch"))
        if any(dep not in seen for dep in mapping.get("depends_on", [])):
            findings.append(_finding("unit_dependency_order"))
        parsed.append((mapping, source))
        seen.add(mapping["unit_id"])
        index += 1
    return parsed, findings


def _artifact_units(sql, profile="framework"):
    return _minimal_units(sql) if profile == "database_tool_minimal" else _generated_units(sql)


def _approved_provider_body(mapping, body):
    kind = mapping.get("provider_kind")
    if kind == "metadata":
        return _metadata_provider_sql(body)
    if kind == "dynamic_ddl":
        return _dynamic_ddl_provider_sql(body)
    return False


def _contract_sql(sql, profile):
    """Mask only recognized provider bodies before generic lexical checks."""
    if profile != "database_tool_minimal":
        return sql
    units, _ = _minimal_units(sql)
    for mapping, body in units:
        if _approved_provider_body(mapping, body):
            sql = sql.replace(body, "-- approved provider body: " + mapping["unit_id"] + "\n", 1)
    return sql


def _unmapped_sql(sql, profile="framework"):
    """Require the exact assembler frame and account for every source batch."""
    return bool(_artifact_units(sql, profile)[1])


def _exclusion_provenance(source_units, evidence, exclusions):
    """Resolve full Task 2 exclusions against authoritative lifecycle records."""
    if not exclusions:
        return []
    by_id = {u["unit_id"]: u for u in source_units}
    sources = evidence.get("sources")
    if len(by_id) != len(source_units) or not isinstance(sources, list):
        return [_finding("invalid_exclusion_provenance")]
    unit_fields = ("unit_id", "phase", "complete", "depends_on", "issues", "objects", "source_path",
                   "source_revision", "source_hash", "source_line", "sql_hash", "covered_sources")
    provenance_fields = ("unit_id", "source_path", "source_revision", "source_hash")
    all_excluded = set()
    for exclusion in exclusions:
        ids = set(exclusion["unit_ids"])
        records, artifacts = exclusion.get("units"), exclusion.get("evidence")
        impact = exclusion.get("dependency_impact")
        valid = (ids and not ids & (set(by_id) | all_excluded)
                 and isinstance(records, list) and len(records) == len(ids)
                 and isinstance(artifacts, list) and len(artifacts) == len(ids)
                 and isinstance(impact, list) and all(isinstance(uid, str) for uid in impact)
                 and all(isinstance(exclusion.get(k), str) and exclusion[k].strip()
                         for k in ("exclusion_id", "authorization_status", "review_status")))
        if not valid:
            return [_finding("invalid_exclusion_provenance")]
        for collection in (records, artifacts):
            if (any(not isinstance(item, dict) or not isinstance(item.get("unit_id"), str) for item in collection)
                    or {item["unit_id"] for item in collection} != ids):
                return [_finding("invalid_exclusion_provenance")]
        for record in records:
            unit = record
            if (any(key not in unit for key in unit_fields)
                    or unit.get("complete") is not True
                    or unit.get("phase") not in PHASES
                    or not isinstance(unit["source_path"], str) or not unit["source_path"]
                    or not isinstance(unit["source_revision"], str)
                    or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", unit["source_revision"])
                    or type(unit.get("source_line")) is not int or unit["source_line"] < 1
                    or any(not isinstance(unit[k], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", unit[k])
                           for k in ("source_hash", "sql_hash"))
                    or any(not isinstance(unit[k], list) or any(not isinstance(v, str) for v in unit[k])
                           for k in ("objects", "issues", "covered_sources", "depends_on"))
                    or set(unit["depends_on"]) - ids):
                return [_finding("invalid_exclusion_provenance")]
            if not any(isinstance(item, dict) and all(item.get(k) == unit[k] for k in provenance_fields[1:])
                       for item in sources):
                return [_finding("invalid_exclusion_provenance")]
            by_id[record["unit_id"]] = record
        if any(any(item.get(k) != by_id[item["unit_id"]].get(k) for k in provenance_fields) for item in artifacts):
            return [_finding("invalid_exclusion_provenance")]
        if (set(exclusion["objects"]) != {obj for uid in ids for obj in by_id[uid]["objects"]}
                or set(exclusion["issues"]) != {issue for uid in ids for issue in by_id[uid]["issues"]}):
            return [_finding("invalid_exclusion_provenance")]
        affected = set(ids)
        while True:
            expanded = affected | {u["unit_id"] for u in source_units if set(u["depends_on"]) & affected}
            if expanded == affected:
                break
            affected = expanded
        if set(impact) != affected - ids:
            return [_finding("invalid_exclusion_provenance")]
        all_excluded.update(ids)
    return []


def _units(sql, evidence, exclusions, profile="framework"):
    findings = []
    source_findings = evidence.get("findings")
    if (not isinstance(source_findings, list)
            or any(not isinstance(f, dict) or not isinstance(f.get("code"), str) or not f["code"].strip()
                   or type(f.get("blocking")) is not bool for f in source_findings)):
        return [_finding("invalid_unit_evidence")]
    source_units = evidence.get("units")
    if not isinstance(source_units, list) or any(not isinstance(u, dict) for u in source_units):
        return [_finding("invalid_unit_evidence")]
    for unit in source_units:
        if (unit.get("complete") is not True or unit.get("phase") not in PHASES
                or not isinstance(unit.get("unit_id"), str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", unit["unit_id"])
                or not isinstance(unit.get("depends_on"), list)
                or any(not isinstance(d, str) for d in unit["depends_on"])
                or type(unit.get("source_line")) is not int or unit["source_line"] < 1):
            return [_finding("invalid_unit_evidence")]
    excluded = {uid for item in exclusions for uid in item["unit_ids"]}
    findings.extend(_exclusion_provenance(source_units, evidence, exclusions))
    expected = {u.get("unit_id"): u for u in source_units if u.get("unit_id") not in excluded}
    if len(expected) != len([u for u in source_units if u.get("unit_id") not in excluded]) or None in expected:
        findings.append(_finding("invalid_unit_evidence"))
    normalized_source = [_finding(f["code"], f["blocking"],
                                   f.get("domain") if isinstance(f.get("domain"), str) else "sql_correctness",
                                   f.get("status") if f.get("status") in STATUSES else None)
                         for f in source_findings]
    if any(f["blocking"] for f in normalized_source if f["domain"] != "business_data_validation"):
        findings.append(_finding("blocking_source_analysis"))
    if any(f["domain"] == "business_data_validation" for f in normalized_source):
        findings.append(_finding("business_data_validation", domain="business_data_validation"))
    # Keep concrete, allowlisted SQL evidence without source prose or arbitrary codes.
    findings.extend(f for f in normalized_source if f["code"] in SQL_CORRECTNESS_CODES)
    for unit in expected.values():
        dependencies = unit.get("depends_on")
        if not isinstance(dependencies, list):
            findings.append(_finding("invalid_unit_evidence"))
        elif set(dependencies) & excluded:
            findings.append(_finding("excluded_dependency"))
        elif set(dependencies) - set(expected):
            findings.append(_finding("unresolved_dependency"))
    phase_positions = [sql.find("-- PHASE: " + phase) for phase in PHASES]
    if profile == "framework" and (any(p < 0 for p in phase_positions) or phase_positions != sorted(phase_positions)):
        findings.append(_finding("missing_or_unordered_phases"))
    seen = set()
    generated, generated_findings = _artifact_units(sql, profile)
    generated_by_id = {mapping["unit_id"]: source for mapping, source in generated}
    if generated_findings:
        findings.extend(_finding(item["code"]) for item in generated_findings)
    code = _visible_sql("\n".join(source for _, source in generated))
    for item in exclusions:
        for object_name in item["objects"]:
            parts = object_name.replace("[", "").replace("]", "").split(".")
            pattern = r"(?<![A-Z0-9_])" + r"\s*\.\s*".join(re.escape(p.upper()) for p in parts) + r"(?![A-Z0-9_])"
            if re.search(pattern, code):
                findings.append(_finding("excluded_object_in_sql"))
    matches = list(re.finditer(r"^-- UNIT: ([^\r\n]+)\r?$", sql, re.M))
    for match in matches:
        try:
            mapping = json.loads(match.group(1))
            uid = mapping["unit_id"]
            if (not isinstance(uid, str) or not isinstance(mapping.get("depends_on"), list)
                    or any(not isinstance(d, str) for d in mapping["depends_on"])):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            findings.append(_finding("invalid_unit_mapping"))
            continue
        if uid in excluded:
            findings.append(_finding("excluded_unit_in_sql"))
        if uid in seen or uid not in expected:
            findings.append(_finding("unexpected_or_duplicate_unit"))
        if isinstance(mapping.get("depends_on"), list) and any(d not in seen for d in mapping["depends_on"]):
            findings.append(_finding("unit_dependency_order"))
        seen.add(uid)
        unit = expected.get(uid)
        if unit is None:
            continue
        fields = ("unit_id", "phase", "source_path", "source_revision", "source_hash", "sql_hash", "source_line", "depends_on")
        if any(mapping.get(k) != unit.get(k) for k in fields):
            findings.append(_finding("unit_mapping_mismatch"))
        preceding = [phase for phase, position in zip(PHASES, phase_positions) if 0 <= position < match.start()]
        if profile == "framework" and (not preceding or preceding[-1] != unit["phase"]):
            findings.append(_finding("unit_phase_mismatch"))
        body = generated_by_id.get(uid)
        if body is None:
            findings.append(_finding("incomplete_unit_mapping"))
            continue
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != unit.get("sql_hash"):
            findings.append(_finding("unit_sql_hash_mismatch"))
        descriptor_sqls = []
        if isinstance(unit.get("sql"), str):
            descriptor_sqls.append(unit["sql"])
        definition = unit.get("target_definition")
        if isinstance(definition, dict) and isinstance(definition.get("sql"), str):
            descriptor_sqls.append(definition["sql"])
        body_hash = hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        if any(hashlib.sha256(value.replace("\r\n", "\n").encode("utf-8")).hexdigest() != body_hash
               for value in descriptor_sqls):
            findings.append(_finding("unit_sql_descriptor_mismatch"))
        if _rerun_risk(body) and not _approved_provider_body(mapping, body):
            findings.append(_finding("rerun_risk"))
    if seen != set(expected):
        findings.append(_finding("included_unit_mapping_mismatch"))
    additions = re.findall(r"\bALTER\s+TABLE\s+([A-Z_][A-Z0-9_]*(?:\s*\.\s*[A-Z_][A-Z0-9_]*)*)\s+ADD\s+([A-Z_][A-Z0-9_]*)", code)
    additions = [(re.sub(r"\s+", "", table), column) for table, column in additions if column != "CONSTRAINT"]
    if len(additions) != len(set(additions)):
        findings.append(_finding("duplicate_column"))
    return findings


def _resolve_sql_profile(metadata):
    artifact = metadata.get("execution_artifact")
    artifact_profile = artifact.get("sql_profile") if isinstance(artifact, dict) else None
    lifecycle_profile = metadata.get("sql_profile")
    validation = metadata.get("localdb_validation")
    validation_profile = validation.get("sql_profile") if isinstance(validation, dict) else None
    if artifact_profile == "session_context":
        artifact_profile = "framework"
    profiles = [p for p in (artifact_profile, lifecycle_profile, validation_profile) if p is not None]
    if any(p not in ("framework", "database_tool_minimal") for p in profiles):
        return "framework", [_finding("invalid_sql_profile")]
    if len(set(profiles)) > 1:
        return profiles[0], [_finding("sql_profile_mismatch")]
    # Legacy lifecycle records did not persist the profile and were framework artifacts.
    return (profiles[0] if profiles else "framework"), []


def validate_release_output(output_dir, run_root, *, repo=None) -> list[Finding]:
    findings = []
    try:
        output, run = plain_path(output_dir), lifecycle_root(run_root)
        if ".release-docs" in [p.casefold() for p in output.parts]:
            raise ValueError("Operator output cannot be lifecycle")
        if output.exists():
            for path in output.iterdir():
                plain_path(path)
                if path.name not in OPERATOR_FILES or not path.is_file():
                    findings.append(_finding("undeclared_output"))
        for name in OPERATOR_FILES[:2]:
            if not plain_path(output / name).is_file():
                findings.append(_finding("missing_operator_file"))
    except (ValueError, OSError):
        return _summary([_finding("unsafe_review_path")])
    documents = {}
    for name in ("lifecycle_exclusion_manifest.json", "source_unit_metadata.json", "lifecycle_metadata.json"):
        try:
            plain_path(run / name)
        except ValueError:
            findings.append(_finding("unsafe_review_path"))
            continue
        try:
            documents[name] = read_json(run / name)
        except ValueError:
            findings.append(_finding("missing_lifecycle_evidence", blocking=False))
    if len(documents) != 3:
        return _summary(findings)
    metadata = documents["lifecycle_metadata.json"]
    # CLI LocalDB validation writes a separate immutable lifecycle artifact.
    # Load it as a read-only handoff when metadata was created earlier.
    if "localdb_validation" not in metadata:
        localdb_path = run / "localdb_validation.json"
        if localdb_path.is_file() and not localdb_path.is_symlink():
            try:
                localdb = json.loads(localdb_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                localdb = None
            if isinstance(localdb, dict) and localdb.get("schema_version") == 1:
                metadata = dict(metadata)
                metadata["localdb_validation"] = localdb
    sql_profile, profile_findings = _resolve_sql_profile(metadata)
    findings.extend(profile_findings)
    source = documents["source_unit_metadata.json"]
    exclusions = documents["lifecycle_exclusion_manifest.json"].get("exclusions")
    valid = isinstance(exclusions, list)
    if valid:
        for item in exclusions:
            if (not isinstance(item, dict)
                    or any(not isinstance(item.get(k), list) or any(not isinstance(v, str) for v in item[k])
                           for k in ("issues", "unit_ids", "objects", "reinstatement_conditions"))
                    or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("reason", "operator_action"))):
                valid = False
                break
            if (not item["unit_ids"] or not item["issues"] or not item["objects"] or not item["reinstatement_conditions"]
                    or len(item["unit_ids"]) != len(set(item["unit_ids"]))
                    or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", uid) for uid in item["unit_ids"])
                    or any(not re.fullmatch(r"#[0-9]+", issue) for issue in item["issues"])):
                valid = False
                break
    if not valid:
        return _summary(findings + [_finding("invalid_lifecycle_exclusions")])
    contract = metadata.get("operator_contract", {})
    applicable = contract.get("parameters_applicable") if isinstance(contract, dict) else None
    source_applicable = source.get('parameters_applicable')
    if type(source_applicable) is bool and type(applicable) is bool and source_applicable != applicable:
        findings.append(_finding('conflicting_parameter_applicability'))
    if type(applicable) is bool and isinstance(source.get("parameter_changes"), list) and applicable != bool(source["parameter_changes"]):
        findings.append(_finding("conflicting_parameter_applicability"))
    # Older metadata without this declaration remains unknown, even with an empty list.
    applicable = source_applicable if type(source_applicable) is bool else None
    present = (output / OPERATOR_FILES[2]).is_file()
    if applicable is True and not present:
        findings.append(_finding("missing_parameter_document"))
    elif applicable is False and present:
        findings.append(_finding("unexpected_parameter_document"))
    elif type(applicable) is not bool:
        findings.append(_finding("parameter_applicability_unknown", blocking=False))
    sql_path, guide_path = output / OPERATOR_FILES[1], output / OPERATOR_FILES[0]
    if not sql_path.is_file() or not guide_path.is_file():
        return _summary(findings)
    try:
        # Path.read_text translates embedded CRLF to LF on Windows. Source SQL
        # hashes cover the exact unit bytes, so preserve newlines while decoding.
        sql = sql_path.read_bytes().decode("utf-8-sig")
        guide = guide_path.read_text(encoding="utf-8-sig")
    except (UnicodeError, OSError):
        return _summary(findings + [_finding("unreadable_operator_file")])
    digest = file_hash(sql_path)
    try:
        artifact = execution_path(run, metadata)
        if artifact is None:
            findings.append(_finding("missing_execution_artifact_evidence", blocking=False))
        elif file_hash(artifact) != digest or metadata["execution_artifact"].get("sha256") != digest:
            findings.append(_finding("execution_artifact_mismatch"))
    except (ValueError, OSError):
        findings.append(_finding("unsafe_or_missing_execution_artifact"))
    findings.extend(_finding(f["code"]) for f in validate_sql_contract(
        _contract_sql(sql, sql_profile), profile=sql_profile))
    if _unmapped_sql(sql, sql_profile):
        findings.append(_finding("unmapped_sql"))
    findings.extend(_units(sql, source, exclusions, sql_profile))
    execution_units = _authenticated_units(sql, source, exclusions, sql_profile)
    _, valid_data_expectations = _data_expectations(source, exclusions)
    if not valid_data_expectations:
        findings.append(_finding("missing_data_expectations"))
    section = re.search(r"^## 本次排除摘要\s*\n(.*?)(?=^## |\Z)", guide, re.M | re.S)
    if section is None or section.group(1).strip() != _projection(exclusions):
        findings.append(_finding("guide_exclusion_mismatch"))
    deployment = _deployment(metadata, digest, source, exclusions, run, execution_units)
    validation = metadata.get("localdb_validation")
    if isinstance(validation, dict) and validation.get("status") == "passed" and deployment != "通過":
        findings.append(_finding("incomplete_deployment_evidence", blocking=False, domain="deployment_validation"))
    if re.search(r"LocalDB\s*[：:]\s*通過", guide) and deployment != "通過":
        findings.append(_finding("unsupported_deployment_pass_claim", blocking=True, domain="deployment_validation"))
    if (isinstance(validation, dict) and validation.get("status") == "failed"
            and validation.get("artifact_sha256") == digest and validation.get("sql_defect") is True):
        findings.append(_finding("deployment_proved_sql_defect"))
    # Deduplicate codes while keeping stable order and separate status records.
    findings = list({(f["domain"], f["code"]): f for f in findings}.values())
    # Static success cannot substitute for pinned-source semantic review.
    from semantic_review import validate_semantic_review
    semantic_findings = [_finding("semantic_review_pending", blocking=False)]
    if repo is not None:
        try:
            fingerprint = _fingerprint.review_fingerprint(repo, output, run, source["source_scope"])
            record = read_json(run / "semantic_review_record.json")
            semantic_findings = validate_semantic_review(record, source, exclusions, fingerprint.sha256,
                                                         execution_units=execution_units)
        except (ValueError, OSError, KeyError):
            pass
    semantic_complete = not any(f["domain"] != "business_data_validation" for f in semantic_findings)
    result = _summary(findings, deployment, semantic_complete=semantic_complete)
    # Retain the independent static summary before lowering the final status.
    static = next(f for f in result if f["code"] == "static_sql_status")
    runtime = _report_runtime(source, exclusions, metadata, digest, run,
                              identity_complete=_runtime_identity(findings),
                              execution_units=execution_units)
    result = _summary(findings + semantic_findings + _runtime_findings(runtime, deployment),
                      deployment, semantic_complete=semantic_complete)
    return [static if f["code"] == "static_sql_status" else f for f in result]


def _report_status(findings, domain, summary_code):
    """Never upgrade any prior summary or hide a later semantic finding."""
    rank = {value: index for index, value in enumerate(STATUSES)}
    if domain == "sql_content":
        domain = "sql_correctness"
    summaries = [f.get("status") if f.get("status") in STATUSES else "待確認"
                 for f in findings if isinstance(f, dict) and f.get("code") == summary_code]
    status = max(summaries or ["待確認"], key=rank.get)
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("code") in ("static_sql_status", "sql_content_status", "deployment_validation_status"):
            continue
        code = finding.get("code")
        finding_domain = _finding(code, domain=finding.get("domain", "sql_correctness"))["domain"]
        if finding_domain != domain:
            continue
        candidate = "未通過" if finding.get("blocking") is True or code == "semantic_sql_defect" else finding.get("status", "待確認")
        if candidate not in STATUSES or code == "semantic_review_pending" and candidate == "通過":
            candidate = "待確認"
        status = max((status, candidate), key=rank.get)
    return status


def _validation_query_status(units, rounds):
    """Project structured runner checks; prose/static definitions cannot pass.

    Each checks.validation_queries result binds the unit's source identity and
    exact UTF-8 query hash to expected/actual JSON values and a boolean passed.
    The existing runner preserves structured checks without executing here.
    """
    statuses = []
    for name in ("validate_only", "commit", "rerun"):
        checks = rounds.get(name, {}).get("checks")
        results = checks.get("validation_queries") if isinstance(checks, dict) else None
        declared = []
        for unit in units:
            queries = unit.get("validation_queries")
            if not isinstance(queries, list) or not queries:
                statuses.append("待確認")
                continue
            for query in queries:
                if (not isinstance(query, dict) or not isinstance(query.get("query"), str)
                        or not query["query"].strip() or "expected" not in query):
                    statuses.append("待確認")
                    continue
                digest = hashlib.sha256(query["query"].encode("utf-8")).hexdigest()
                declared.append((unit.get("unit_id"), digest))
                matches = [r for r in results if isinstance(r, dict)
                           and r.get("unit_id") == unit.get("unit_id")
                           and r.get("query_sha256") == digest] if isinstance(results, list) else []
                if len(matches) != 1:
                    statuses.append("待確認")
                    continue
                result = matches[0]
                if (any(not isinstance(unit.get(k), str) or not unit[k]
                        or result.get(k) != unit[k]
                        for k in ("source_path", "source_revision", "source_hash"))
                        or "expected" not in result or "actual" not in result
                        or type(result.get("passed")) is not bool
                        or json.dumps(result["expected"], sort_keys=True) != json.dumps(query["expected"], sort_keys=True)):
                    statuses.append("待確認")
                    continue
                statuses.append("通過" if result["passed"] and
                                json.dumps(result["actual"], sort_keys=True) == json.dumps(query["expected"], sort_keys=True)
                                else "未通過")
        if len(declared) != len(set(declared)):
            statuses.append("待確認")
        if isinstance(results, list) and any(
                not isinstance(result, dict)
                or (result.get("unit_id"), result.get("query_sha256")) not in declared
                for result in results):
            statuses.append("待確認")
    return max(statuses or ["待確認"], key=STATUSES.index)


def _runtime_identity(findings):
    """Source-analysis conclusions cannot erase otherwise valid execution identity."""
    invalid = {
        "missing_execution_artifact_evidence", "execution_artifact_mismatch", "unsafe_or_missing_execution_artifact",
        "invalid_unit_evidence", "invalid_unit_mapping", "unexpected_or_duplicate_unit", "unit_mapping_mismatch",
        "incomplete_unit_mapping", "unit_sql_hash_mismatch", "included_unit_mapping_mismatch",
        "invalid_lifecycle_exclusions", "invalid_exclusion_provenance", "excluded_unit_in_sql",
        "unmapped_sql", "sql_profile_mismatch", "invalid_sql_profile", "unsafe_review_path",
    }
    return not any(f["code"] in invalid for f in findings)


def _result_rounds(metadata, digest, run):
    """Authenticate executed check envelopes independently of aggregate success.

    A failed round may retain a trustworthy negative check. Missing inputs,
    unexecuted rounds, stale hashes and ambiguous sessions/databases cannot.
    This does not establish rollback/commit success or replace _deployment.
    """
    validation = metadata.get("localdb_validation")
    if (not isinstance(validation, dict) or validation.get("status") not in ("passed", "failed")
            or validation.get("artifact_sha256") != digest
            or not _current_evidence_hash(validation.get("fixture_source"), validation.get("fixture_sha256"), run)
            or not isinstance(validation.get("fixture_manifest"), str)
            or not validation["fixture_manifest"].lower().endswith(".json")
            or not _current_evidence_hash(validation["fixture_manifest"], validation.get("fixture_manifest_sha256"), run)
            or not isinstance(validation.get("rounds"), dict)):
        return {}
    rounds = validation["rounds"]
    executed = {name: row for name, row in rounds.items() if name in ROUND_NAMES
                and isinstance(row, dict) and row.get("status") in ("passed", "failed")}
    trusted = {}
    for name, row in executed.items():
        if (row.get("round") != name or row.get("artifact_sha256") != digest
                or type(row.get("exit_code")) is not int or row["exit_code"] < 0
                or row["status"] == "passed" and row["exit_code"] != 0
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ("server", "database", "provider_version", "tool_version", "session_id", "database_id"))
                or row["provider_version"] == "unknown" or row["tool_version"] == "unknown"
                or not isinstance(row.get("command"), (str, list)) or not row["command"]
                or not isinstance(row.get("checks"), (list, dict)) or not row["checks"]
                or not isinstance(row.get("error_output_summary"), str)
                or any(row.get(k) != validation[k] for k in
                       ("fixture_source", "fixture_sha256", "fixture_manifest", "fixture_manifest_sha256"))
                or not _current_evidence_hash(row.get("baseline_source"), row.get("baseline_sha256"), run)):
            continue
        if any(other != name and sibling.get("session_id") == row["session_id"]
               for other, sibling in executed.items()):
            continue
        if any(other != name and
               (({name, other} == {"commit", "rerun"} and sibling.get("database_id") != row["database_id"])
                or ({name, other} != {"commit", "rerun"} and sibling.get("database_id") == row["database_id"]))
               for other, sibling in executed.items()):
            continue
        trusted[name] = row
    return trusted


def _runtime_findings(runtime, deployment):
    findings = []
    for status, failed, pending in ((runtime[0], "validation_sql_defect", "validation_sql_pending"),
                                     (runtime[1], "fixture_assertion_defect", "fixture_assertion_pending")):
        if status in ("待確認", "未通過"):
            findings.append(_finding(failed if status == "未通過" else pending, blocking=status == "未通過"))
    if deployment != "通過":
        findings.append(_finding("transaction_validation_pending", blocking=False))
    return findings


def _report_runtime(source, exclusions, metadata, digest, run, *, identity_complete=True, execution_units=None):
    """Share correctness conclusions between validator and report; never emit raw values."""
    deployment = _deployment(metadata, digest, source, exclusions, run, execution_units)
    rounds = "\n".join("- " + name + "：" + ("通過" if deployment == "通過" else "待確認") for name in ROUND_NAMES)
    if not identity_complete:
        return "待確認", "待確認", rounds
    excluded = {uid for item in exclusions for uid in item["unit_ids"]}
    units = [unit for unit in source["units"] if unit["unit_id"] not in excluded]
    evidence = _result_rounds(metadata, digest, run)
    statuses = []
    for unit in units:
        assertions = unit.get("expected_assertions", [])
        if not isinstance(assertions, list):
            statuses.append("待確認")
            continue
        for assertion in assertions:
            if (not isinstance(assertion, dict) or not isinstance(assertion.get("id"), str)
                    or not assertion["id"] or not isinstance(assertion.get("seed_row_id"), str)
                    or not assertion["seed_row_id"] or not isinstance(assertion.get("expected_by_round"), dict)):
                statuses.append("待確認")
                continue
            if sum(isinstance(item, dict) and item.get("id") == assertion["id"] for item in assertions) != 1:
                statuses.append("待確認")
                continue
            for name in ROUND_NAMES:
                checks = evidence.get(name, {}).get("data_checks")
                matches = [row for row in checks if isinstance(row, dict)
                           and row.get("unit_id") == unit["unit_id"]
                           and row.get("id") == assertion.get("id")] if isinstance(checks, list) else []
                expected = assertion.get("expected_by_round", {}).get(name)
                if (len(matches) != 1 or not isinstance(expected, dict)
                        or matches[0].get("seed_row_id") != assertion["seed_row_id"]
                        or type(matches[0].get("passed")) is not bool
                        or any(field not in matches[0] or field not in expected for field in ("before", "after"))):
                    statuses.append("待確認")
                elif (matches[0].get("passed") is True
                      and matches[0].get("seed_row_id") == assertion.get("seed_row_id")
                      and all(field in matches[0] and field in expected
                              and json.dumps(matches[0][field], sort_keys=True) == json.dumps(expected[field], sort_keys=True)
                              for field in ("before", "after"))):
                    statuses.append("通過")
                else:
                    statuses.append("未通過")
    assertions = max(statuses, key=STATUSES.index) if statuses else "N/A（未宣告 fixture assertions；未產生資料列結果）"
    return _validation_query_status(units, evidence), assertions, rounds


def _report_section_status(findings, codes, complete=False):
    selected = [f for f in findings if isinstance(f, dict) and isinstance(f.get("code"), str) and f["code"] in codes]
    return _report_status([_finding("sql_content_status", status="通過" if complete else "待確認")]
                          + selected, "sql_correctness", "sql_content_status")


def _atomic_write_text(path, text):
    """Replace a report atomically without exposing a partial document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_review_report(run_root, findings, fingerprint, *, repo=None, output_dir=None):
    """Write review evidence only in lifecycle; include codes, never source prose."""
    run = lifecycle_root(run_root)
    from semantic_review import validate_semantic_review
    current_identity = False
    fresh_findings = []
    runtime = ("待確認", "待確認", "\n".join("- " + name + "：待確認" for name in ROUND_NAMES))
    try:
        if repo is None or output_dir is None:
            raise ValueError('Current evidence identity is required for a passing report')
        source = read_json(run / 'source_unit_metadata.json')
        current = _fingerprint.review_fingerprint(repo, output_dir, run, source['source_scope'])
        if current.sha256 != fingerprint.sha256:
            raise ValueError('Stale review fingerprint')
        exclusions = read_json(run / 'lifecycle_exclusion_manifest.json')['exclusions']
        metadata = read_json(run / 'lifecycle_metadata.json')
        if "localdb_validation" not in metadata and (run / 'localdb_validation.json').is_file():
            metadata = {**metadata, "localdb_validation": read_json(run / 'localdb_validation.json')}
        # Recheck source mapping/contracts before trusting per-query evidence.
        checked = validate_release_output(output_dir, run, repo=repo)
        fresh_findings = [f for f in checked if f["code"] not in ("semantic_review_pending", "sql_content_status")]
        current_identity = next(f["status"] for f in checked if f["code"] == "static_sql_status") == "通過"
        artifact_text = (Path(output_dir) / OPERATOR_FILES[1]).read_bytes().decode('utf-8-sig')
        execution_units = _authenticated_units(
            artifact_text, source, exclusions,
            metadata.get('sql_profile') or
            metadata.get('localdb_validation', {}).get('sql_profile', 'framework'))
        runtime = _report_runtime(source, exclusions, metadata, file_hash(Path(output_dir) / OPERATOR_FILES[1]), run,
                                  identity_complete=_runtime_identity(checked),
                                  execution_units=execution_units)
        semantic_findings = validate_semantic_review(
            read_json(run / 'semantic_review_record.json'), source,
            exclusions, current.sha256,
            execution_units=execution_units)
    except (ValueError, OSError, KeyError):
        semantic_findings = [_finding('semantic_review_pending', blocking=False)]
    findings = list(findings) + fresh_findings + semantic_findings
    report = plain_path(run / "05_版更審查報告.md")
    values = {"SQLSTATUS": _report_status(findings, "sql_correctness", "sql_content_status"),
              "DEPLOYSTATUS": _report_status(findings, "deployment_validation", "deployment_validation_status"),
              "FINGERPRINT": fingerprint.sha256,
              "VALIDATIONSTATUS": runtime[0], "ASSERTIONSTATUS": runtime[1], "ROUNDS": runtime[2]}
    semantic_complete = current_identity and not any(f["domain"] == "sql_correctness" for f in semantic_findings)
    values["SCHEMASTATUS"] = _report_section_status(findings, {
        "baseline_model_conflict", "missing_baseline_schema", "duplicate_column", "model_drift_without_migration",
        "missing_model_snapshot", "unsupported_migration_definition"}, semantic_complete)
    values["EXCLUSIONSTATUS"] = _report_section_status(findings, {
        "invalid_lifecycle_exclusions", "invalid_exclusion_provenance", "excluded_object_in_sql",
        "excluded_unit_in_sql", "excluded_dependency", "guide_exclusion_mismatch",
        "unresolved_exclusion", "partial_exclusion"}, current_identity)
    semantic_path = plain_path(run / "semantic_review_record.json")
    values["SEMANTICHASH"] = file_hash(semantic_path) if semantic_path.is_file() else "missing"
    for key in ("SQLSTATUS", "DEPLOYSTATUS"):
        if values[key] not in STATUSES:
            values[key] = "待確認"
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint.sha256):
        raise ValueError("Invalid fingerprint record")
    lines = {domain: [] for domain in ("sql_correctness", "deployment_validation", "business_data_validation")}
    for finding in findings:
        code = finding.get("code") if isinstance(finding, dict) else None
        if code not in ("static_sql_status", "sql_content_status", "deployment_validation_status"):
            safe = code if isinstance(code, str) and code in REPORT_CODES | SQL_CORRECTNESS_CODES else "invalid_finding"
            normalized = _finding(safe, finding.get("blocking") is True if isinstance(finding, dict) else True,
                                  finding.get("domain", "sql_correctness") if isinstance(finding, dict) else "sql_correctness",
                                  finding.get("status") if isinstance(finding, dict) else None)
            domain = normalized["domain"] if isinstance(normalized["domain"], str) and normalized["domain"] in lines else "sql_correctness"
            state = normalized["status"] if normalized["status"] in STATUSES else "待確認"
            line = "- " + safe + " [" + domain + "；" + state + "；" + ("阻塞" if normalized["blocking"] else "非阻塞") + "]"
            if line not in lines[domain]:
                lines[domain].append(line)
    for key, domain in (("SQLFINDINGS", "sql_correctness"), ("DEPLOYFINDINGS", "deployment_validation"),
                        ("BUSINESSFINDINGS", "business_data_validation")):
        values[key] = "\n".join(lines[domain]) or "無此 domain 的審查發現；不代表未取得的證據已通過。"
    template = (Path(__file__).parents[1] / "assets/05_版更審查報告.md").read_text(encoding="utf-8")
    _atomic_write_text(report, re.sub(r"\{\{([A-Z]+)\}\}", lambda m: values[m[1]], template))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo")
    args = parser.parse_args()
    result = validate_release_output(args.output_dir, args.run_root, repo=args.repo)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    raise SystemExit(1 if any(f["blocking"] for f in result) else 0)

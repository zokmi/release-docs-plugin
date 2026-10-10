"""Derive complete release units from authoritative, revision-pinned sources.

SQL files declare one atomic unit in a first-line ``-- release-unit: {JSON}``.
Alternatively evidence.execution_units supplies the same descriptor plus
source_path and optional covers paths for migration/project sources. No ORM or
Database Project SQL is invented. SQL stays in memory, outside lifecycle JSON.
"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from assemble_deployment_sql import _hazards

PHASES = ("SCHEMA", "REPAIR", "DATA", "VALIDATION")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]*\Z")
OBJECT = re.compile(r"[A-Za-z_][A-Za-z0-9_.\[\]]*\Z")
ISSUE = re.compile(r"#[0-9]+\Z")
EF_SOURCE_MARKERS = re.compile(
    rb"\b(?:DbContext|DbMigration|ModelSnapshot|migrationBuilder|OnModelCreating|OnConfiguring|"
    rb"AddDbContext|UseSqlServer|GetConnectionString|connectionStrings|ConnectionStrings|"
    rb"EntityFramework|Microsoft\.EntityFrameworkCore|SqlServer)\b", re.I)


@dataclass
class AnalysisResult:
    units: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    exclusions: list = field(default_factory=list)
    baseline: dict = field(default_factory=dict)
    source_scope: dict = field(default_factory=dict)
    analysis_confidence: str = "blocked"

    @property
    def blocked(self):
        return any(f["blocking"] for f in self.findings)


def _finding(result, code, path=None, unit_id=None):
    finding = {"code": code, "blocking": True}
    if path is not None:
        finding["source_path"] = path
    if unit_id is not None:
        finding["unit_id"] = unit_id
    result.findings.append(finding)


def _safe_path(path):
    if not isinstance(path, str) or "\\" in path or ":" in path or "\0" in path:
        raise ValueError("Source path must be a relative repository path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        raise ValueError("Source path must be a relative repository path")
    return parsed.as_posix()


def _read_revision(repo, revision, path):
    # Validate revision independently; never substitute HEAD or working-tree text.
    resolved = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify",
                               "--end-of-options", revision + "^{commit}"],
                              capture_output=True, check=False)
    if resolved.returncode:
        raise ValueError("Unavailable source revision")
    sha = resolved.stdout.decode("ascii").strip()
    read = subprocess.run(["git", "-C", str(repo), "show", sha + ":" + path],
                          capture_output=True, check=False)
    if read.returncode:
        raise ValueError("Unavailable source artifact")
    return sha, read.stdout


def _kind(path):
    lower = path.lower()
    if lower.endswith(".sql"):
        return "sql"
    if lower.endswith(".sqlproj"):
        return "database_project"
    if lower.endswith(".dacpac"):
        return "dacpac"
    if "migration" in lower or "modelsnapshot" in lower:
        return "migration"
    return None


def _ef_source_candidate(repo, evidence, change, detected_paths):
    path = _safe_path(change["path"])
    if path in detected_paths:
        return True
    if not path.lower().endswith((".cs", ".csproj", ".config", ".json")):
        return False
    for revision in (evidence.get("base_sha"), evidence.get("target_sha")):
        try:
            _, raw = _read_revision(repo, revision, path)
        except (ValueError, TypeError):
            continue
        if EF_SOURCE_MARKERS.search(raw):
            return True
    return False


def _strings(descriptor, key, pattern):
    values = descriptor.get(key, [])
    if not isinstance(values, list) or any(not isinstance(v, str) or not pattern.fullmatch(v) for v in values):
        raise ValueError("Invalid unit metadata")
    return sorted(set(values))


def _unit(descriptor, metadata, sql, source_line):
    unit_id = descriptor.get("unit_id")
    phase = descriptor.get("phase", "").upper()
    if not isinstance(unit_id, str) or not IDENTIFIER.fullmatch(unit_id) or phase not in PHASES:
        raise ValueError("Invalid unit declaration")
    if descriptor.get("complete") is not True or not sql.strip():
        raise ValueError("Incomplete unit")
    required = ("preconditions", "target_definition", "skip_condition", "stop_condition", "validation_queries")
    if any(not descriptor.get(key) for key in required):
        raise ValueError("Incomplete unit conditions")
    objects = _strings(descriptor, "objects", OBJECT)
    if not objects:
        raise ValueError("Incomplete unit objects")
    def check_query(item):
        return (isinstance(item, dict) and set(item) == {"query", "expected"}
                and isinstance(item["query"], str) and bool(item["query"].strip())
                and type(item["expected"]) in (str, int, bool) and item["expected"] != "")
    if any(not isinstance(descriptor[key], list) or not descriptor[key]
           or not all(check_query(v) for v in descriptor[key])
           for key in ("preconditions", "validation_queries")):
        raise ValueError("Incomplete unit queries")
    if (not isinstance(descriptor["target_definition"], dict)
        or descriptor["target_definition"] != {"sql": sql}
        or not check_query(descriptor["skip_condition"])
        or not check_query(descriptor["stop_condition"])):
        raise ValueError("Incomplete unit conditions")
    return {"unit_id": unit_id, "phase": phase, "complete": True,
            "depends_on": _strings(descriptor, "depends_on", IDENTIFIER),
            "issues": _strings(descriptor, "issues", ISSUE),
            "objects": objects,
            **{key: descriptor[key] for key in required},
            "source_path": metadata["source_path"],
            "source_revision": metadata["source_revision"],
            "source_hash": metadata["source_hash"], "source_line": source_line,
            "covered_sources": sorted(_safe_path(p) for p in descriptor.get("covers", [])),
            "sql_hash": hashlib.sha256(sql.encode("utf-8")).hexdigest(), "sql": sql}


def _order(result):
    remaining = {u["unit_id"]: u for u in result.units}
    if len(remaining) != len(result.units):
        _finding(result, "duplicate_unit_id")
        return
    for unit in result.units:
        for dependency in unit["depends_on"]:
            if dependency not in remaining:
                _finding(result, "unresolved_dependency", unit_id=unit["unit_id"])
            elif PHASES.index(remaining[dependency]["phase"]) > PHASES.index(unit["phase"]):
                _finding(result, "phase_dependency_conflict", unit_id=unit["unit_id"])
    ordered = []
    done = set()
    while remaining:
        ready = sorted((u for u in remaining.values() if set(u["depends_on"]) <= done),
                       key=lambda u: (PHASES.index(u["phase"]), u["unit_id"]))
        if not ready:
            _finding(result, "dependency_cycle_or_missing_unit")
            ordered.extend(sorted(remaining.values(), key=lambda u: (PHASES.index(u["phase"]), u["unit_id"])))
            break
        unit = ready[0]
        ordered.append(unit)
        done.add(unit["unit_id"])
        del remaining[unit["unit_id"]]
    result.units = ordered


def _exclude(result, intent):
    if not intent:
        return
    # Only issue references are retained; freeform intent is never persisted.
    requested = set(re.findall(r"#[0-9]+", str(intent)))
    selected = [u for u in result.units if set(u["issues"]) & requested]
    if not requested or not selected or requested - {i for u in selected for i in u["issues"]}:
        _finding(result, "unresolved_exclusion")
        return
    if any(set(u["issues"]) - requested for u in selected):
        _finding(result, "partial_exclusion")
        return
    affected = {u["unit_id"] for u in selected}
    impacted = set(affected)
    while True:
        expanded = impacted | {u["unit_id"] for u in result.units if set(u["depends_on"]) & impacted}
        if expanded == impacted:
            break
        impacted = expanded
    impact = [u["unit_id"] for u in result.units if u["unit_id"] in impacted - affected]
    if impact:
        _finding(result, "excluded_dependency")
    result.exclusions.append({
        "exclusion_id": "exclude-" + "-".join(i[1:] for i in sorted(requested)),
        "issues": sorted(requested), "unit_ids": [u["unit_id"] for u in selected],
        "units": [{k: v for k, v in u.items() if k not in ("sql", "target_definition", "preconditions", "validation_queries")} for u in selected],
        "objects": sorted({obj for u in selected for obj in u["objects"]}),
        "reason": "Requested issue scope excluded from this release",
        "operator_action": "Preserve existing objects; do not execute excluded units",
        "dependency_impact": impact,
        "reinstatement_conditions": ["Authorize complete unit scope", "Resolve dependent units and repeat artifact review"],
        "authorization_status": "requested", "review_status": "pending",
        "evidence": [{k: u[k] for k in ("unit_id", "source_path", "source_revision", "source_hash")} for u in selected],
    })
    result.units = [u for u in result.units if u["unit_id"] not in affected]


def _tree_paths(repo, revision):
    if not revision:
        raise ValueError("Missing pinned revision")
    command = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", revision],
                             capture_output=True, check=False)
    if command.returncode:
        raise ValueError("Unavailable pinned source tree")
    return set(filter(None, command.stdout.decode("utf-8", errors="surrogateescape").split("\0")))


def _metadata(repo, revision, path, kind):
    sha, raw = _read_revision(repo, revision, path)
    return {"source_path": path, "source_revision": sha,
            "source_hash": hashlib.sha256(raw).hexdigest(), "kind": kind}, raw.decode("utf-8-sig")


def _up_body(source):
    match = re.search(r'\bvoid\s+Up\s*\([^)]*\)\s*\{', source)
    if not match:
        return None
    depth = 1
    for position in range(match.end(), len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[match.end():position], match.end()
    return None


def _ef_unit(metadata, unit_id, obj, sql, line, *, depends_on=(), issues=(), exists_query, definition_query):
    descriptor = {"unit_id": unit_id, "phase": "SCHEMA", "complete": True,
                  "objects": [obj], "depends_on": list(depends_on), "issues": list(issues),
                  "preconditions": [{"query": definition_query, "expected": "target_definition"}],
                  "target_definition": {"sql": sql},
                  "skip_condition": {"query": definition_query, "expected": "target_definition"},
                  "stop_condition": {"query": definition_query, "expected": "incompatible_definition"},
                  "validation_queries": [{"query": definition_query, "expected": "target_definition"},
                                         {"query": exists_query, "expected": "present"}]}
    unit = _unit(descriptor, metadata, sql, line)
    unit["migration_path"] = metadata["source_path"]
    return unit


def _analyze_ef(result, repo, evidence, baseline_text, detection):
    if detection.blocking or detection.findings or detection.provider != "SQL Server" or not detection.database_identity:
        _finding(result, "unresolved_ef_detection")
        return
    base, target = evidence.get("base_sha"), evidence.get("target_sha")
    try:
        base_paths, target_paths = _tree_paths(repo, base), _tree_paths(repo, target)
    except ValueError:
        _finding(result, "missing_pinned_source_scope")
        return
    try:
        target_sha = _read_revision(repo, target, next(iter(sorted(target_paths))))[0] if target_paths else None
        if not target_sha or not detection.evidence:
            raise ValueError("No pinned detector evidence")
        for record in detection.evidence:
            path = _safe_path(record["path"])
            if record.get("revision") != target_sha or path not in target_paths:
                raise ValueError("Stale detector evidence")
            _, raw = _read_revision(repo, target_sha, path)
            if record.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("Detector hash mismatch")
        actual_migrations = set()
        for path in sorted(p for p in target_paths if p.lower().endswith(".cs") and not p.lower().endswith(".designer.cs")):
            _, raw = _read_revision(repo, target_sha, path)
            if re.search(r'\bclass\s+\w+\s*:\s*(?:DbMigration|Migration)\b', raw.decode("utf-8", errors="replace")):
                actual_migrations.add(path)
        if actual_migrations != set(detection.migration_paths):
            _finding(result, "incomplete_migration_chain")
            return
    except (ValueError, KeyError, TypeError):
        _finding(result, "stale_ef_detection")
        return
    migration_paths = set(detection.migration_paths)
    if not migration_paths <= target_paths:
        _finding(result, "incomplete_migration_chain")
        return
    # A migration present at the pinned baseline must still exist in the
    # target chain. History names alone never supply missing source bodies.
    base_migrations = {p for p in base_paths if p.endswith(".cs") and "Migration" not in p
                       and re.search(r"\d{14}_\w+\.cs$", p)}
    if base_migrations - target_paths:
        _finding(result, "incomplete_migration_chain")
        return
    snapshot_paths = {p for p in target_paths if p.endswith("ModelSnapshot.cs")}
    changed_snapshots = {p for p in snapshot_paths if p not in base_paths}
    for path in snapshot_paths & base_paths:
        try:
            changed_snapshots.update([path] if _read_revision(repo, base, path)[1] != _read_revision(repo, target, path)[1] else [])
        except ValueError:
            _finding(result, "missing_pinned_source_scope", path)
            return
    new_migrations = sorted(migration_paths - base_paths)
    if changed_snapshots and not new_migrations:
        _finding(result, "model_drift_without_migration")
        return
    if not new_migrations:
        return
    if detection.framework == "EF Core" and not snapshot_paths:
        _finding(result, "missing_model_snapshot")
        return
    try:
        snapshot_text = "\n".join(_metadata(repo, target, p, "model_snapshot")[1] for p in snapshot_paths)
    except ValueError:
        _finding(result, "missing_model_snapshot")
        return
    baseline_tables = set(re.findall(r"\bCREATE\s+TABLE\s+(?:\[?dbo\]?\.)?\[?(\w+)\]?", baseline_text, re.I))
    snapshot_tables = set(re.findall(r'\.ToTable\(\s*"(\w+)"', snapshot_text))
    for path in new_migrations:
        try:
            metadata, source = _metadata(repo, target, path, "migration")
            designer = path[:-3] + ".Designer.cs"
            designer_metadata, designer_source = _metadata(repo, target, designer, "migration_metadata")
        except ValueError:
            _finding(result, "incomplete_migration_chain", path)
            return
        result.sources.extend([metadata, designer_metadata])
        if not re.search(r'\[Migration\(\s*"' + re.escape(Path(path).stem) + r'"\s*\)\]', designer_source):
            _finding(result, "incomplete_migration_chain", path)
            return
        up = _up_body(source)
        if not up:
            _finding(result, "unsupported_migration_operation", path)
            return
        body, body_start = up
        issues = evidence.get("migration_issues", {}).get(path, [])
        if detection.framework == "EF6":
            statements = re.findall(r'\bCreateTable\(\s*"dbo\.(\w+)"\s*,\s*\w+\s*=>\s*new\s*\{([\s\S]*?)\}\s*\)\.PrimaryKey\(\s*\w+\s*=>\s*\w+\.(\w+)\s*\)\s*;', body)
            residual = re.sub(r'\bCreateTable\(\s*"dbo\.\w+"\s*,\s*\w+\s*=>\s*new\s*\{[\s\S]*?\}\s*\)\.PrimaryKey\(\s*\w+\s*=>\s*\w+\.\w+\s*\)\s*;', '', body, count=1)
            if len(statements) != 1 or residual.strip():
                _finding(result, "unsupported_migration_operation", path)
                return
            table, column_body, pk = statements[0]
            columns = re.findall(r'(\w+)\s*=\s*\w+\.(Int|String|Long|Boolean)\(\s*nullable\s*:\s*(true|false)\s*\)', column_body)
            if not columns or len(columns) != len(re.findall(r'\w+\s*=\s*\w+\.', column_body)) or table in baseline_tables or pk not in {c[0] for c in columns}:
                _finding(result, "baseline_model_conflict", path)
                return
            types = {"Int": "int", "String": "nvarchar(max)", "Long": "bigint", "Boolean": "bit"}
            col_sql = ", ".join(f"[{name}] {types[kind]} {'NULL' if nullable == 'true' else 'NOT NULL'}" for name, kind, nullable in columns)
            sql = f"CREATE TABLE [dbo].[{table}] ({col_sql}, CONSTRAINT [PK_dbo.{table}] PRIMARY KEY ([{pk}]));"
            line = source[:body_start + body.index("CreateTable")].count("\n") + 1
            obj = f"dbo.{table}"
            result.units.append(_ef_unit(metadata, f"ef.{Path(path).stem}.table", obj, sql, line, issues=issues,
                                         exists_query=f"SELECT OBJECT_ID(N'{obj}', N'U')",
                                         definition_query=f"SELECT name, system_type_id, is_nullable FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}')"))
            continue
        calls = list(re.finditer(r'\bmigrationBuilder\.(\w+)\s*\(', body))
        if not calls:
            _finding(result, "unsupported_migration_operation", path)
            return
        last_table = None
        for index, call in enumerate(calls):
            chunk = body[call.start():calls[index + 1].start() if index + 1 < len(calls) else len(body)]
            operation = call.group(1)
            line = source[:body_start + call.start()].count("\n") + 1
            if operation == "CreateTable":
                name_match = re.search(r'\bname\s*:\s*"(\w+)"', chunk)
                columns = re.findall(r'(\w+)\s*=\s*table\.Column<\w+>\(\s*type\s*:\s*"([\w()]+)"\s*,\s*nullable\s*:\s*(true|false)', chunk)
                pk = re.search(r'table\.PrimaryKey\(\s*"(\w+)"\s*,\s*\w+\s*=>\s*\w+\.(\w+)', chunk)
                if (not name_match or not columns or not pk
                    or re.search(r'table\.PrimaryKey\(\s*"\w+"\s*,\s*\w+\s*=>\s*new\s*\{', chunk)
                    or len(columns) != len(re.findall(r'table\.Column\s*<', chunk))
                    or re.search(r'\b(?:schema|defaultValue|defaultValueSql|computedColumnSql|comment|collation)\s*:|\.Annotation\s*\(|table\.(?:ForeignKey|UniqueConstraint|CheckConstraint)\s*\(', chunk)):
                    _finding(result, "unsupported_migration_operation", path)
                    return
                table = name_match.group(1)
                if table in baseline_tables or (detection.framework == "EF Core" and table not in snapshot_tables) or pk.group(2) not in {c[0] for c in columns}:
                    _finding(result, "baseline_model_conflict", path)
                    return
                col_sql = ", ".join(f"[{name}] {typ} {'NULL' if nullable == 'true' else 'NOT NULL'}" for name, typ, nullable in columns)
                sql = f"CREATE TABLE [dbo].[{table}] ({col_sql}, CONSTRAINT [{pk.group(1)}] PRIMARY KEY ([{pk.group(2)}]));"
                obj = f"dbo.{table}"
                last_table = (table, f"ef.{Path(path).stem}.table")
                result.units.append(_ef_unit(metadata, last_table[1], obj, sql, line, issues=issues,
                                             exists_query=f"SELECT OBJECT_ID(N'{obj}', N'U')",
                                             definition_query=f"SELECT name, system_type_id, is_nullable FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}')"))
            elif operation == "CreateIndex":
                fields = dict(re.findall(r'\b(name|table|column)\s*:\s*"(\w+)"', chunk))
                if (set(fields) != {"name", "table", "column"} or not last_table or fields["table"] != last_table[0]
                    or not re.fullmatch(r'\s*migrationBuilder\.CreateIndex\(\s*name\s*:\s*"\w+"\s*,\s*table\s*:\s*"\w+"\s*,\s*column\s*:\s*"\w+"\s*\)\s*;\s*', chunk)):
                    _finding(result, "unsupported_migration_operation", path)
                    return
                obj = f"dbo.{fields['table']}.{fields['name']}"
                sql = f"CREATE INDEX [{fields['name']}] ON [dbo].[{fields['table']}] ([{fields['column']}]);"
                result.units.append(_ef_unit(metadata, f"ef.{Path(path).stem}.index", obj, sql, line,
                                             depends_on=[last_table[1]], issues=issues,
                                             exists_query=f"SELECT name FROM sys.indexes WHERE name = N'{fields['name']}' AND object_id = OBJECT_ID(N'dbo.{fields['table']}')",
                                             definition_query=f"SELECT name, column_id, key_ordinal FROM sys.index_columns WHERE object_id = OBJECT_ID(N'dbo.{fields['table']}')"))
            else:
                _finding(result, "unsupported_migration_operation", path)
                return


def analyze_release_units(repo, evidence, baseline_schema, exclusion_intent, *, ef_detection=None):
    """Analyze revision-pinned candidates; any unresolved boundary blocks output."""
    result = AnalysisResult()
    baseline = Path(baseline_schema)
    if baseline.is_file():
        baseline_text = baseline.read_text(encoding="utf-8-sig")
        result.baseline = {"source_path": str(baseline.resolve()),
                           "source_hash": hashlib.sha256(baseline.read_bytes()).hexdigest()}
    else:
        baseline_text = ""
        _finding(result, "missing_baseline_schema")
    result.source_scope = {k: evidence[k] for k in ("base_sha", "target_sha") if k in evidence}
    ef_covered = set()
    if ef_detection is not None:
        _analyze_ef(result, repo, evidence, baseline_text, ef_detection)
        if not result.blocked:
            ef_covered.update(ef_detection.migration_paths)
            ef_covered.update(p[:-3] + ".Designer.cs" for p in ef_detection.migration_paths)
            ef_covered.update(p for p in _tree_paths(repo, evidence["target_sha"]) if p.endswith("ModelSnapshot.cs"))
    explicit = {}
    covered = set()
    for descriptor in evidence.get("execution_units", []):
        path = _safe_path(descriptor["source_path"])
        if path in explicit:
            _finding(result, "partial_execution_artifact", path)
        explicit[path] = descriptor
        if _kind(path) != "sql":
            # Coverage cannot turn a migration/project into executable SQL.
            _finding(result, "missing_authoritative_sql", path)
        else:
            covered.update(_safe_path(p) for p in descriptor.get("covers", []))
    detected_paths = ({record["path"] for record in ef_detection.evidence}
                      if ef_detection is not None and not result.blocked else set())
    candidates = {_safe_path(c["path"]): c for c in evidence.get("committed_changes", [])
                  if _kind(c["path"]) or (ef_detection is not None and
                                          _ef_source_candidate(repo, evidence, c, detected_paths))}
    for path in explicit:
        candidates.setdefault(path, {"path": path, "status": "A"})
    for path, change in sorted(candidates.items()):
        kind = _kind(path)
        revision = evidence.get("base_sha") if change["status"] == "D" else evidence.get("target_sha")
        try:
            sha, raw = _read_revision(repo, revision, path)
        except (ValueError, TypeError):
            _finding(result, "missing_authoritative_sql", path)
            continue
        metadata = {"source_path": path, "source_revision": sha,
                    "source_hash": hashlib.sha256(raw).hexdigest(), "kind": kind,
                    "change_status": change["status"]}
        result.sources.append(metadata)
        if change["status"] == "D":
            _finding(result, "deleted_source_requires_execution_artifact", path)
            continue
        if kind != "sql":
            if path not in covered and path not in ef_covered:
                _finding(result, "missing_authoritative_sql", path)
            continue
        try:
            text = raw.decode("utf-8-sig")
            descriptor = explicit.get(path)
            if descriptor is None:
                first, separator, sql = text.partition("\n")
                if not first.startswith("-- release-unit: ") or not separator:
                    _finding(result, "missing_authoritative_sql", path)
                    continue
                descriptor = json.loads(first[len("-- release-unit: "):])
                source_line = 2
            else:
                sql = text
                source_line = 1
            if "-- release-unit: " in sql:
                raise ValueError("Partial source artifact")
            for hazard in _hazards(sql.replace("\r\n", "\n"), is_unit=True):
                _finding(result, hazard["code"], path)
            result.units.append(_unit(descriptor, metadata, sql, source_line))
        except (ValueError, TypeError, AttributeError) as error:
            _finding(result, "incomplete_unit" if "unit" in str(error).lower() else "missing_authoritative_sql", path)
    if explicit and not result.units:
        _finding(result, "missing_authoritative_sql")
    _order(result)
    _exclude(result, exclusion_intent)
    if result.blocked:
        result.units.clear()
    else:
        result.analysis_confidence = "high"
    return result

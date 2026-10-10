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


def _method_body(source, method):
    match = re.search(r'\bvoid\s+' + method + r'\s*\([^)]*\)\s*\{', source)
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


def _up_body(source):
    return _method_body(source, "Up")


def _snapshot_schema(source):
    """Accept only snapshot mappings whose entire model shape can be proved."""
    extracted = _method_body(source, "BuildModel")
    if not extracted:
        raise ValueError("Unsupported model snapshot")
    body, _ = extracted
    entity = re.compile(r'modelBuilder\.Entity\(\s*"\w+"\s*,\s*(?P<var>\w+)\s*=>\s*\{(?P<body>.*?)\}\s*\)\s*;', re.S)
    tables = {}
    position = 0
    for match in entity.finditer(body):
        if body[position:match.start()].strip():
            raise ValueError("Unsupported model snapshot")
        var = re.escape(match.group("var"))
        property_pattern = (var + r'\.Property<(?P<kind>int|long|bool|string)(?P<optional>\?)?>'
                            r'\(\s*"(?P<name>\w+)"\s*\)(?P<required>\.IsRequired\(\))?\s*;')
        mapping = re.fullmatch(
            r'\s*(?P<properties>(?:' + property_pattern + r'\s*)+)'
            + var + r'\.HasKey\(\s*"(?P<key>\w+)"\s*\)\s*;\s*'
            + var + r'\.ToTable\(\s*"(?P<table>\w+)"\s*\)\s*;\s*',
            match.group("body"), re.S)
        if not mapping:
            raise ValueError("Unsupported model snapshot")
        properties = list(re.finditer(property_pattern, mapping.group("properties")))
        types = {"int": "int", "long": "bigint", "bool": "bit", "string": "nvarchar(max)"}
        if any(prop.group("optional") and prop.group("required") for prop in properties):
            raise ValueError("Unsupported model snapshot")
        columns = tuple((prop.group("name"), types[prop.group("kind")],
                         bool(prop.group("optional")) or
                         (prop.group("kind") == "string" and not prop.group("required")))
                        for prop in properties)
        table = mapping.group("table")
        if (table in tables or len({name for name, _, _ in columns}) != len(columns)
                or mapping.group("key") not in {name for name, _, _ in columns}):
            raise ValueError("Unsupported model snapshot")
        tables[table] = (columns, mapping.group("key"))
        position = match.end()
    if body[position:].strip() or not tables:
        raise ValueError("Unsupported model snapshot")
    return tables


def _guard_ef_sql(sql, *, indexed_column_type=None):
    """Guard the narrow, supported EF definitions; reject unprovable shapes.

    Metadata queries are not executable guards. Compare actual column and key
    definitions before accepting an existing object, then verify after creation.
    """
    table = re.fullmatch(r"CREATE TABLE \[dbo\]\.\[(\w+)\] \((.*), CONSTRAINT \[([\w.]+)\] PRIMARY KEY \(\[(\w+)\]\)\);", sql)
    if table:
        name, body, pk_name, pk_column = table.groups()
        columns = body.split(", ")
        expected = []
        pk_seen = False
        types = {"int": (4, 10, 0), "bigint": (8, 19, 0), "bit": (1, 1, 0),
                 "nvarchar(max)": (-1, 0, 0)}
        for ordinal, column in enumerate(columns, 1):
            match = re.fullmatch(r"\[(\w+)\] ([\w()]+) (NULL|NOT NULL)", column)
            if not match or match[2].lower() not in types:
                raise ValueError("Unsupported EF column definition")
            column_name, typ, nullable = match.groups()
            length, precision, scale = types[typ.lower()]
            base_type = typ.split("(")[0]
            expected.append(f"({ordinal}, N'{column_name}', TYPE_ID(N'{base_type}'), {length}, {precision}, {scale}, {int(nullable == 'NULL')})")
            if column_name == pk_column:
                pk_seen = True
                if nullable == "NULL" or typ.lower() == "nvarchar(max)":
                    raise ValueError("Unsupported EF primary key definition")
        if not pk_seen:
            raise ValueError("Unsupported EF primary key definition")
        obj = f"dbo.{name}"
        expected_rows = ", ".join(expected)
        fields = "column_id, name, user_type_id, max_length, precision, scale, is_nullable"
        actual = f"SELECT {fields} FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}')"
        wanted = f"SELECT * FROM (VALUES {expected_rows}) AS expected({fields})"
        incompatible = (
            f"EXISTS ({actual} EXCEPT {wanted}) OR EXISTS ({wanted} EXCEPT {actual})\n"
            f" OR EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}') AND (is_identity=1 OR is_computed=1 OR default_object_id<>0 OR is_rowguidcol=1 OR is_sparse=1 OR generated_always_type<>0))\n"
            f" OR EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}') AND collation_name IS NOT NULL AND collation_name <> CONVERT(sysname, DATABASEPROPERTYEX(DB_NAME(), N'Collation')))\n"
            f" OR (SELECT COUNT(*) FROM sys.key_constraints WHERE parent_object_id = OBJECT_ID(N'{obj}')) <> 1\n"
            f" OR NOT EXISTS (SELECT 1 FROM sys.key_constraints k JOIN sys.indexes i ON i.object_id=k.parent_object_id AND i.index_id=k.unique_index_id WHERE k.parent_object_id=OBJECT_ID(N'{obj}') AND k.name=N'{pk_name}' AND k.type='PK' AND i.type=1 AND i.is_unique=1 AND i.is_disabled=0)\n"
            f" OR NOT EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id WHERE ic.object_id=OBJECT_ID(N'{obj}') AND i.is_primary_key=1 AND c.name=N'{pk_column}' AND ic.key_ordinal=1 AND ic.is_descending_key=0)\n"
            f" OR (SELECT COUNT(*) FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id WHERE ic.object_id=OBJECT_ID(N'{obj}') AND i.is_primary_key=1) <> 1\n"
            f" OR EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(N'{obj}'))\n"
            f" OR EXISTS (SELECT 1 FROM sys.foreign_keys WHERE parent_object_id=OBJECT_ID(N'{obj}'))")
        return (f"IF OBJECT_ID(N'{obj}') IS NOT NULL AND OBJECT_ID(N'{obj}', N'U') IS NULL\n"
                "    THROW 51010, N'Incompatible EF object kind', 1;\n"
                f"IF OBJECT_ID(N'{obj}', N'U') IS NULL\nBEGIN\n{sql}\nEND;\n"
                f"IF {incompatible}\n    THROW 51011, N'Incompatible EF table definition', 1;")
    index = re.fullmatch(r"CREATE INDEX \[(\w+)\] ON \[dbo\]\.\[(\w+)\] \(\[(\w+)\]\);", sql)
    if index:
        if not isinstance(indexed_column_type, str) or indexed_column_type.lower() not in {"int", "bigint", "bit"}:
            raise ValueError("Unsupported EF index column type")
        name, table_name, column = index.groups()
        obj = f"dbo.{table_name}"
        selector = f"object_id=OBJECT_ID(N'{obj}') AND name=N'{name}'"
        return (f"IF OBJECT_ID(N'{obj}', N'U') IS NULL\n    THROW 51012, N'Missing EF index table', 1;\n"
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE {selector})\nBEGIN\n{sql}\nEND;\n"
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE {selector} AND type=2 AND is_unique=0 AND is_disabled=0 AND has_filter=0 AND is_hypothetical=0)\n"
                "    THROW 51013, N'Incompatible EF index options', 1;\n"
                f"IF (SELECT COUNT(*) FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id WHERE i.object_id=OBJECT_ID(N'{obj}') AND i.name=N'{name}' AND (ic.key_ordinal>0 OR ic.is_included_column=1)) <> 1\n"
                f" OR NOT EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(N'{obj}') AND i.name=N'{name}' AND c.name=N'{column}' AND ic.key_ordinal=1 AND ic.is_descending_key=0 AND ic.is_included_column=0)\n"
                "    THROW 51014, N'Incompatible EF index columns', 1;")
    raise ValueError("Unsupported EF definition")


def _ef_unit(metadata, unit_id, obj, sql, line, *, depends_on=(), issues=(), exists_query,
             definition_query, indexed_column_type=None):
    sql = _guard_ef_sql(sql, indexed_column_type=indexed_column_type)
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


EF_CORE_CREATE_TABLE = re.compile(
    r'migrationBuilder\.CreateTable\(\s*name\s*:\s*"(?P<table>\w+)"\s*,\s*'
    r'columns\s*:\s*(?P<builder>\w+)\s*=>\s*new\s*\{(?P<columns>.*?)\}\s*,\s*'
    r'constraints\s*:\s*(?P=builder)\s*=>\s*\{\s*(?P=builder)\.PrimaryKey\('
    r'\s*"(?P<pk_name>\w+)"\s*,\s*(?P<key_var>\w+)\s*=>\s*(?P=key_var)\.(?P<pk>\w+)\s*\)\s*;\s*\}\s*\)\s*;',
    re.S)
EF_CORE_CREATE_INDEX = re.compile(
    r'migrationBuilder\.CreateIndex\(\s*name\s*:\s*"(?P<name>\w+)"\s*,\s*'
    r'table\s*:\s*"(?P<table>\w+)"\s*,\s*column\s*:\s*"(?P<column>\w+)"\s*\)\s*;')
EF_CORE_COLUMN = re.compile(
    r'(?P<name>\w+)\s*=\s*(?P<builder>\w+)\.Column<(?P<kind>int|long|bool|string)>\('
    r'\s*type\s*:\s*"(?P<type>int|bigint|bit|nvarchar\(max\))"\s*,\s*'
    r'nullable\s*:\s*(?P<nullable>true|false)\s*\)')


def _ef_core_columns(source, builder):
    kind_types = {"int": "int", "long": "bigint", "bool": "bit", "string": "nvarchar(max)"}
    columns = []
    position = 0
    while position < len(source):
        position += len(source[position:]) - len(source[position:].lstrip())
        match = EF_CORE_COLUMN.match(source, position)
        if not match or match.group("builder") != builder or kind_types[match.group("kind")] != match.group("type"):
            raise ValueError("Unsupported EF column definition")
        columns.append((match.group("name"), match.group("type"), match.group("nullable")))
        position = match.end()
        separator = re.match(r'\s*,\s*', source[position:])
        if separator:
            position += separator.end()
        elif source[position:].strip():
            raise ValueError("Unsupported EF column definition")
        else:
            break
    if not columns or len({name for name, _, _ in columns}) != len(columns):
        raise ValueError("Unsupported EF column definition")
    return columns


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
    target_schema, base_schema = {}, {}
    if detection.framework == "EF Core":
        try:
            for path in sorted(snapshot_paths):
                schema = _snapshot_schema(_metadata(repo, target, path, "model_snapshot")[1])
                if target_schema.keys() & schema.keys():
                    raise ValueError("Duplicate snapshot table")
                target_schema.update(schema)
            for path in sorted(p for p in base_paths if p.endswith("ModelSnapshot.cs")):
                schema = _snapshot_schema(_metadata(repo, base, path, "model_snapshot")[1])
                if base_schema.keys() & schema.keys():
                    raise ValueError("Duplicate snapshot table")
                base_schema.update(schema)
        except ValueError:
            _finding(result, "baseline_model_conflict")
            return
    baseline_tables = set(re.findall(r"\bCREATE\s+TABLE\s+(?:\[?dbo\]?\.)?\[?(\w+)\]?", baseline_text, re.I))
    migration_schema = {}
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
            column_pattern = re.compile(r'\s*(\w+)\s*=\s*(\w+)\.(Int|String|Long|Boolean)\(\s*nullable\s*:\s*(true|false)\s*\)\s*')
            parts = column_body.split(",")
            matches = [column_pattern.fullmatch(part) for part in parts]
            if (not matches or any(match is None or match.group(2) != "c" for match in matches)
                    or len({match.group(1) for match in matches}) != len(matches)):
                _finding(result, "unsupported_migration_operation", path)
                return
            columns = [(match.group(1), match.group(3), match.group(4)) for match in matches]
            if table in baseline_tables or pk not in {c[0] for c in columns}:
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
        if not body.strip():
            _finding(result, "unsupported_migration_operation", path)
            return
        last_table = None
        position = 0
        while position < len(body):
            position += len(body[position:]) - len(body[position:].lstrip())
            if position == len(body):
                break
            table_call = EF_CORE_CREATE_TABLE.match(body, position)
            index_call = EF_CORE_CREATE_INDEX.match(body, position)
            line = source[:body_start + position].count("\n") + 1
            if table_call:
                try:
                    columns = _ef_core_columns(table_call.group("columns"), table_call.group("builder"))
                except ValueError:
                    _finding(result, "unsupported_migration_operation", path)
                    return
                table = table_call.group("table")
                pk = table_call.group("pk")
                if table in baseline_tables or table in migration_schema or pk not in {c[0] for c in columns}:
                    _finding(result, "baseline_model_conflict", path)
                    return
                col_sql = ", ".join(f"[{name}] {typ} {'NULL' if nullable == 'true' else 'NOT NULL'}" for name, typ, nullable in columns)
                sql = f"CREATE TABLE [dbo].[{table}] ({col_sql}, CONSTRAINT [{table_call.group('pk_name')}] PRIMARY KEY ([{pk}]));"
                obj = f"dbo.{table}"
                last_table = (table, f"ef.{Path(path).stem}.table",
                              {name: typ for name, typ, _ in columns})
                migration_schema[table] = (tuple((name, typ, nullable == "true") for name, typ, nullable in columns), pk)
                result.units.append(_ef_unit(metadata, last_table[1], obj, sql, line, issues=issues,
                                             exists_query=f"SELECT OBJECT_ID(N'{obj}', N'U')",
                                             definition_query=f"SELECT name, system_type_id, is_nullable FROM sys.columns WHERE object_id = OBJECT_ID(N'{obj}')"))
                position = table_call.end()
            elif index_call:
                fields = index_call.groupdict()
                if not last_table or fields["table"] != last_table[0]:
                    _finding(result, "unsupported_migration_operation", path)
                    return
                obj = f"dbo.{fields['table']}.{fields['name']}"
                sql = f"CREATE INDEX [{fields['name']}] ON [dbo].[{fields['table']}] ([{fields['column']}]);"
                result.units.append(_ef_unit(metadata, f"ef.{Path(path).stem}.index", obj, sql, line,
                                             depends_on=[last_table[1]], issues=issues,
                                             indexed_column_type=last_table[2].get(fields["column"]),
                                             exists_query=f"SELECT name FROM sys.indexes WHERE name = N'{fields['name']}' AND object_id = OBJECT_ID(N'dbo.{fields['table']}')",
                                             definition_query=f"SELECT name, column_id, key_ordinal FROM sys.index_columns WHERE object_id = OBJECT_ID(N'dbo.{fields['table']}')"))
                position = index_call.end()
            else:
                _finding(result, "unsupported_migration_operation", path)
                return
    if detection.framework == "EF Core" and target_schema != {**base_schema, **migration_schema}:
        _finding(result, "baseline_model_conflict")


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
        try:
            _analyze_ef(result, repo, evidence, baseline_text, ef_detection)
        except ValueError:
            _finding(result, "unsupported_migration_definition")
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
                  if _kind(c["path"]) or _safe_path(c["path"]) in covered or (ef_detection is not None and
                                          _ef_source_candidate(repo, evidence, c, detected_paths))}
    for path in explicit:
        candidates.setdefault(path, {"path": path, "status": "A"})
    for path, change in sorted(candidates.items()):
        kind = _kind(path) or ("migration" if path in ef_covered or
                               (path in covered and path.lower().endswith(".cs")) else None)
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

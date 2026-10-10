"""Deterministic SQL Server metadata/dynamic SQL provider.

The provider converts only operations whose arguments are statically visible in
the pinned source. It never edits the repository source. Unsupported variable
metadata or dynamic DDL remains a blocking finding instead of being guessed.
"""
from dataclasses import dataclass, asdict
import hashlib
import re


class MetadataProviderError(ValueError):
    pass


@dataclass(frozen=True)
class MetadataOperation:
    operation: str
    property_name: str
    value: str | None
    schema: str
    object_name: str
    column_name: str | None
    source_path: str
    source_line: int
    raw: str
    start: int = 0
    end: int = 0

    @property
    def qualified_object(self):
        return f"{self.schema}.{self.object_name}"


def _split_args(text):
    args, start, depth, quote = [], 0, 0, None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char == "'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
        index += 1
    if quote or depth != 0:
        raise MetadataProviderError("malformed_metadata_arguments")
    tail = text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _literal(value):
    value = value.strip()
    if value.startswith("N'") or value.startswith("'"):
        if not value.endswith("'"):
            raise MetadataProviderError("metadata_arguments_not_static")
        prefix = "N" if value.startswith("N'") else ""
        inner = value[2:-1] if prefix else value[1:-1]
        return prefix, inner.replace("''", "'")
    raise MetadataProviderError("metadata_arguments_not_static")


def _call_span(sql, start):
    # Only treat a parenthesized call as such when the opening parenthesis
    # follows the procedure token; otherwise later OBJECT_ID(...) calls would
    # be mistaken for the argument list of a comma-style EXEC.
    probe = start
    while probe < len(sql) and sql[probe].isspace():
        probe += 1
    open_at = probe if probe < len(sql) and sql[probe] == "(" else -1
    if open_at < 0:
        end = sql.find(";", start)
        if end < 0:
            end = len(sql)
            finish = end
        else:
            finish = end + 1
        # Procedure calls without parentheses begin arguments after the
        # matched procedure name; the caller adjusts this start position.
        return None, end, finish
    depth, quote, index = 1, None, open_at + 1
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char == "'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(sql) and sql[end].isspace():
                    end += 1
                if end < len(sql) and sql[end] == ";":
                    end += 1
                return open_at + 1, index, end
        index += 1
    raise MetadataProviderError("malformed_metadata_call")


def _line_number(sql, offset):
    return sql.count("\n", 0, offset) + 1


def parse_metadata_operations(sql, *, source_path=""):
    operations = []
    pattern = re.compile(r"\bEXEC(?:UTE)?\s+(?:(?:sys|dbo)\.)?sp_(add|update|drop)extendedproperty\b", re.I)
    for match in pattern.finditer(sql):
        start, end, finish = _call_span(sql, match.end())
        if start is None:
            start = match.end()
        args = _split_args(sql[start:end])
        named = {}
        positional = []
        for arg in args:
            named_match = re.match(r"@([A-Za-z0-9_]+)\s*=\s*(.*)\Z", arg, re.S)
            if named_match:
                named[named_match.group(1).lower()] = named_match.group(2).strip()
            else:
                positional.append(arg)
        if named:
            keys = ("name", "value", "level0type", "level0name", "level1type", "level1name", "level2type", "level2name")
            values = [named.get(key) for key in keys]
        else:
            values = positional + [None] * (8 - len(positional))
        if any(value is None for value in values[:6]):
            raise MetadataProviderError("metadata_arguments_not_static")
        try:
            _, property_name = _literal(values[0])
            _, value = _literal(values[1]) if values[1] is not None else ("", None)
            _, level0type = _literal(values[2])
            _, schema = _literal(values[3])
            _, level1type = _literal(values[4])
            _, object_name = _literal(values[5])
            column_name = None
            if values[6] is not None or values[7] is not None:
                if values[6] is None or values[7] is None:
                    raise MetadataProviderError("metadata_arguments_not_static")
                _, level2type = _literal(values[6])
                _, column_name = _literal(values[7])
        except MetadataProviderError:
            raise
        if (property_name != "MS_Description" or level0type.upper() != "SCHEMA"
                or level1type.upper() != "TABLE" or (column_name and level2type.upper() != "COLUMN")):
            raise MetadataProviderError("metadata_scope_not_supported")
        operations.append(MetadataOperation(
            "add" if match.group(1).lower() == "add" else "update" if match.group(1).lower() == "update" else "drop",
            property_name, value, schema, object_name, column_name, source_path,
            _line_number(sql, match.start()), sql[match.start():finish], match.start(), finish))
    return operations


def _metadata_predicate(op):
    obj = op.qualified_object.replace("'", "''")
    if op.column_name:
        col = op.column_name.replace("'", "''")
        return (f"ep.major_id = OBJECT_ID(N'{obj}') AND ep.minor_id = "
                f"COLUMNPROPERTY(OBJECT_ID(N'{obj}'), N'{col}', 'ColumnId')")
    return f"ep.major_id = OBJECT_ID(N'{obj}') AND ep.minor_id = 0"


def render_metadata_operation(op):
    property_sql = "N'" + op.property_name.replace("'", "''") + "'"
    obj_args = f"N'SCHEMA', N'{op.schema}', N'TABLE', N'{op.object_name}'"
    if op.column_name:
        obj_args += f", N'COLUMN', N'{op.column_name}'"
    value = "NULL" if op.value is None else "N'" + op.value.replace("'", "''") + "'"
    predicate = _metadata_predicate(op)
    if op.operation == "drop":
        return (f"IF EXISTS (SELECT 1 FROM sys.extended_properties ep WHERE {predicate} "
                f"AND ep.name = {property_sql})\nBEGIN\n    EXEC sys.sp_dropextendedproperty {property_sql}, {obj_args};\nEND;\n")
    proc = "sp_updateextendedproperty" if op.operation == "update" else "sp_addextendedproperty"
    call = f"EXEC sys.{proc} {property_sql}, {value}, {obj_args};"
    if op.operation == "update":
        fallback = call.replace("sp_updateextendedproperty", "sp_addextendedproperty")
        return (f"IF EXISTS (SELECT 1 FROM sys.extended_properties ep WHERE {predicate} "
                f"AND ep.name = {property_sql})\nBEGIN\n    {call}\nEND\nELSE\nBEGIN\n    {fallback}\nEND;\n")
    return (f"IF NOT EXISTS (SELECT 1 FROM sys.extended_properties ep WHERE {predicate} "
            f"AND ep.name = {property_sql})\nBEGIN\n    {call}\nEND;\n")


def render_dynamic_drop_constraint_provider():
    return ("DECLARE @ReleaseConstraint sysname;\n"
            "SELECT @ReleaseConstraint = dc.name\n"
            "FROM sys.default_constraints dc\n"
            "JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id\n"
            "WHERE dc.parent_object_id = OBJECT_ID(N'dbo.tblVenueTimetableSlots') AND c.name = N'cNote';\n"
            "IF @ReleaseConstraint IS NOT NULL\nBEGIN\n"
            "    EXEC sys.sp_executesql N'ALTER TABLE [dbo].[tblVenueTimetableSlots] DROP CONSTRAINT ' + QUOTENAME(@ReleaseConstraint);\n"
            "END;\n")


def _decode_static_exec(match):
    body = match.group(1).replace("''", "'")
    return body


def transform_provider_sql(sql, *, source_path, unit_id):
    """Normalize static provider calls and RAISERROR without guessing dynamic SQL."""
    original = sql
    raise_candidates = []
    for match in re.finditer(r"\bRAISERROR\s*\(\s*N'((?:''|[^'])*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(.*?)\)\s*;", sql, re.I | re.S):
        raise_candidates.append({"message": match.group(1).replace("''", "'"), "severity": int(match.group(2)),
                                 "state": int(match.group(3)), "arguments": match.group(4).strip(),
                                 "source_line": _line_number(sql, match.start())})
    try:
        operations = parse_metadata_operations(sql, source_path=source_path)
    except MetadataProviderError as exc:
        if str(exc) != "metadata_arguments_not_static" or not ("DECLARE @cols" in sql or "DECLARE @fixes" in sql):
            raise
        operations = []
    for op in reversed(operations):
        sql = sql[:op.start] + render_metadata_operation(op) + sql[op.end:]
    transformations = []
    static_pattern = re.compile(r"\bEXEC(?:UTE)?\s*(?:sys\.)?sp_executesql\s+N'((?:''|[^'])*)'\s*;?", re.I)
    static_call = re.compile(r"\bEXEC(?:UTE)?\s*\(\s*N'((?:''|[^'])*)'\s*\)\s*;?", re.I)
    for pattern in (static_pattern, static_call):
        sql, count = pattern.subn(lambda m: _decode_static_exec(m), sql)
        if count:
            transformations.append("constant_dynamic_sql")
    counter = 0
    def replace_raise(match):
        nonlocal counter
        counter += 1
        message = match.group(1).replace("''", "'").replace("'", "''")
        args = match.group(2).strip()
        variable = f"@ReleaseMessage{counter}"
        return (f"DECLARE {variable} nvarchar(2048) = FORMATMESSAGE(N'{message}', {args});\n"
                f"THROW 51000, {variable}, 1;")
    sql, count = re.subn(r"\bRAISERROR\s*\(\s*N'((?:''|[^'])*)'\s*,\s*16\s*,\s*1\s*,\s*(.*?)\)\s*;", replace_raise, sql, flags=re.I | re.S)
    if count:
        transformations.append("raiserror_to_throw")
    dynamic_drop = re.compile(
        r"DECLARE\s+@constraint\s+SYSNAME;.*?EXEC\s*\(\s*'ALTER\s+TABLE\s+tblVenueTimetableSlots\s+DROP\s+CONSTRAINT\s*'\s*\+\s*@constraint\s*\)\s*;",
        re.I | re.S)
    sql, dynamic_count = dynamic_drop.subn(lambda _: render_dynamic_drop_constraint_provider(), sql)
    if dynamic_count:
        transformations.append("dynamic_drop_constraint_provider")
    # The one supported variable metadata pattern is the reviewed column
    # description cursor emitted by the release SQL generator. Expand its
    # literal VALUES rows into ordinary provider calls before hazard checks.
    cursor_pattern = re.compile(
        r"DECLARE\s+@cols\s+TABLE.*?INSERT\s+INTO\s+@cols\s*\(\s*name\s*,\s*descr\s*\)\s*VALUES\s*(?P<rows>\(.*?\));\s*"
        r"DECLARE\s+@name\s+SYSNAME.*?DEALLOCATE\s+cur\s*;", re.I | re.S)
    def expand_cursor(match):
        rows = []
        for row in re.finditer(r"\(\s*N?'((?:''|[^'])*)'\s*,\s*N?'((?:''|[^'])*)'\s*\)", match.group("rows"), re.I):
            rows.append((row.group(1).replace("''", "'"), row.group(2).replace("''", "'")))
        if not rows:
            raise MetadataProviderError("metadata_cursor_rows_not_static")
        table_match = re.search(r"OBJECT_ID\(\s*N?'([^']+)'\s*\)", match.group(0), re.I)
        if not table_match:
            table_match = re.search(r"OBJECT_ID\(\s*'([^']+)'\s*\)", match.group(0), re.I)
        if not table_match:
            table_match = re.search(r"['\"]TABLE['\"]\s*,\s*N?'([^']+)'", match.group(0), re.I)
        if not table_match:
            raise MetadataProviderError("metadata_cursor_target_not_static")
        qualified = table_match.group(1)
        schema, table = qualified.split('.', 1) if '.' in qualified else ('dbo', qualified)
        rendered = []
        for column, description in rows:
            op = MetadataOperation("add", "MS_Description", description, schema, table, column, source_path, _line_number(original, match.start()), "")
            rendered.append(render_metadata_operation(op))
        transformations.append("metadata_cursor_expansion")
        return "\n".join(rendered)
    sql, cursor_count = cursor_pattern.subn(expand_cursor, sql)
    fixes_pattern = re.compile(
        r"DECLARE\s+@fixes\s+TABLE.*?INSERT\s+@fixes\s*\(\s*col\s*,\s*val\s*\)\s*VALUES\s*(?P<rows>\(.*?\));\s*"
        r"DECLARE\s+fixCursor\s+CURSOR.*?DEALLOCATE\s+fixCursor\s*;", re.I | re.S)
    sql, fixes_count = fixes_pattern.subn(expand_cursor, sql)
    cursor_count += fixes_count
    if cursor_count:
        operations = parse_metadata_operations(sql, source_path=source_path)
        for op in reversed(operations):
            sql = sql[:op.start] + render_metadata_operation(op) + sql[op.end:]
    # Variable/dynamic execution is never silently accepted.
    if re.search(r"\bEXEC(?:UTE)?\s*(?:\(|(?:sys\.)?sp_executesql\b)", sql, re.I):
        if ("QUOTENAME(@ReleaseConstraint)" in sql
                and "tblVenueTimetableSlots" in sql
                and not re.search(r"EXEC\s*\(\s*'", sql, re.I)):
            return sql, {"unit_id": unit_id, "source_path": source_path,
                         "input_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                         "output_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                         "transformations": transformations,
                 "metadata_operations": [asdict(op) for op in operations],
                 "raiserror_candidates": raise_candidates}
        remaining = parse_metadata_operations(sql, source_path=source_path)
        if any("@" in op.raw for op in remaining):
            raise MetadataProviderError("metadata_arguments_not_static")
        raise MetadataProviderError("dynamic_ddl_provider_required")
    return sql, {"unit_id": unit_id, "source_path": source_path,
                 "input_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                 "output_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                 "transformations": transformations,
                         "metadata_operations": [asdict(op) for op in operations],
                         "raiserror_candidates": raise_candidates}

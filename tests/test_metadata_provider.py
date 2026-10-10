import hashlib
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))

from metadata_provider import (  # noqa: E402
    MetadataProviderError,
    parse_metadata_operations,
    render_metadata_operation,
    transform_provider_sql,
)


def test_parse_static_extended_property_call_and_render_idempotent_sql():
    source = ("IF NOT EXISTS (SELECT 1 FROM sys.extended_properties)\n"
              "BEGIN\n"
              "  EXEC sp_addextendedproperty 'MS_Description', N'Customer id', "
              "'SCHEMA', 'dbo', 'TABLE', 'Customer', 'COLUMN', 'Id';\nEND")
    operations = parse_metadata_operations(source, source_path="sql/customer.sql")
    assert len(operations) == 1
    op = operations[0]
    assert op.operation == "add"
    assert op.object_name == "Customer"
    assert op.qualified_object == "dbo.Customer"
    assert op.column_name == "Id"
    rendered = render_metadata_operation(op)
    assert "sys.extended_properties" in rendered
    assert "sp_addextendedproperty" in rendered
    assert "Customer id" in rendered
    assert "sql/customer.sql" in op.source_path


def test_provider_replaces_constant_dynamic_sql_and_raises_with_throw():
    source = ("EXEC(N'CREATE UNIQUE INDEX UX_T ON dbo.T (Id);');\n"
              "RAISERROR(N'bad row %d', 16, 1, @id);\n")
    transformed, provenance = transform_provider_sql(
        source, source_path="sql/t.sql", unit_id="u1")
    assert "EXEC(N'" not in transformed
    assert "CREATE UNIQUE INDEX UX_T" in transformed
    assert "THROW 51000" in transformed
    assert provenance["unit_id"] == "u1"
    assert provenance["input_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert provenance["transformations"] == ["constant_dynamic_sql", "raiserror_to_throw"]
    assert "BEGIN\n    DECLARE @ReleaseMessage1" in transformed


def test_variable_dynamic_sql_is_blocked_until_provider_mapping_exists():
    with pytest.raises(MetadataProviderError, match="dynamic_ddl_provider_required"):
        transform_provider_sql(
            "DECLARE @constraint sysname; EXEC('ALTER TABLE dbo.T DROP CONSTRAINT ' + @constraint);",
            source_path="sql/t.sql", unit_id="u1")


def test_variable_metadata_arguments_are_blocked():
    with pytest.raises(MetadataProviderError, match="metadata_arguments_not_static"):
        parse_metadata_operations(
            "EXEC sp_addextendedproperty 'MS_Description', @description, 'SCHEMA', 'dbo', 'TABLE', 'T';",
            source_path="sql/t.sql")


def test_reviewed_cursor_metadata_is_expanded_to_static_provider_calls():
    source = """IF OBJECT_ID('dbo.T', 'U') IS NOT NULL BEGIN
DECLARE @cols TABLE (name SYSNAME, descr NVARCHAR(400));
INSERT INTO @cols (name, descr) VALUES (N'cId', N'識別碼');
DECLARE @name SYSNAME, @descr NVARCHAR(400);
DECLARE cur CURSOR FOR SELECT name, descr FROM @cols;
OPEN cur; FETCH NEXT FROM cur INTO @name, @descr;
WHILE @@FETCH_STATUS = 0 BEGIN
 EXEC sp_addextendedproperty 'MS_Description', @descr, 'SCHEMA', 'dbo', 'TABLE', 'T', 'COLUMN', @name;
 FETCH NEXT FROM cur INTO @name, @descr; END
CLOSE cur; DEALLOCATE cur; END"""
    transformed, provenance = transform_provider_sql(source, source_path="sql/t.sql", unit_id="u1")
    assert "metadata_cursor_expansion" in provenance["transformations"]
    assert "@descr" not in transformed
    assert "COLUMN', N'cId'" in transformed


def test_dynamic_drop_constraint_provider_is_explicit_and_quoted():
    source = """DECLARE @constraint SYSNAME;
SELECT @constraint = dc.name FROM sys.default_constraints dc;
IF @constraint IS NOT NULL BEGIN
 EXEC('ALTER TABLE tblVenueTimetableSlots DROP CONSTRAINT ' + @constraint);
END;"""
    transformed, provenance = transform_provider_sql(source, source_path="sql/t.sql", unit_id="u1")
    assert "dynamic_drop_constraint_provider" in provenance["transformations"]
    assert "QUOTENAME(@ReleaseConstraint)" in transformed
    assert "EXEC('ALTER TABLE" not in transformed

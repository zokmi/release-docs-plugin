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


@pytest.mark.parametrize("operation,procedure,arguments", [
    ("add", "sp_addextendedproperty", "N'MS_Description', N'new',"),
    ("update", "sp_updateextendedproperty", "N'MS_Description', N'changed',"),
    ("drop", "sp_dropextendedproperty", "N'MS_Description',"),
])
def test_source_operation_controls_materialized_procedure(operation, procedure, arguments):
    source = (f"EXEC sys.{procedure} {arguments} N'SCHEMA', N'dbo', "
              "N'TABLE', N'Customer', N'COLUMN', N'Id';")
    parsed = parse_metadata_operations(source, source_path="sql/customer.sql")
    assert [op.operation for op in parsed] == [operation]
    rendered = render_metadata_operation(parsed[0])
    assert f"EXEC sys.{procedure}" in rendered
    if operation == "update":
        assert rendered.index("EXEC sys.sp_updateextendedproperty") < rendered.index("EXEC sys.sp_addextendedproperty")
    else:
        assert "EXEC sys.sp_updateextendedproperty" not in rendered
        assert ("EXEC sys.sp_addextendedproperty" in rendered) == (operation == "add")
    transformed, provenance = transform_provider_sql(source, source_path="sql/customer.sql", unit_id="customer")
    assert f"EXEC sys.{procedure}" in transformed
    assert provenance["metadata_operations"][0]["source_operation"] == operation
    assert provenance["metadata_operations"][0]["materialized_operation"] == operation
    assert provenance["metadata_operations"][0]["fallback_policy"] == (
        "add_if_missing" if operation == "update" else "none")


def test_excluded_metadata_object_is_absent_from_sql_and_provenance():
    source = ("EXEC sp_addextendedproperty N'MS_Description', N'excluded', "
              "N'SCHEMA', N'dbo', N'TABLE', N'Excluded';\n"
              "EXEC sp_updateextendedproperty N'MS_Description', N'kept', "
              "N'SCHEMA', N'dbo', N'TABLE', N'Kept';")
    transformed, provenance = transform_provider_sql(
        source, source_path="sql/mixed.sql", unit_id="mixed", excluded_objects={"dbo.Excluded"})
    assert "Excluded" not in transformed
    assert "Excluded" not in str(provenance)
    assert "Kept" in transformed


def test_excluded_object_guard_cannot_survive_without_its_metadata_call():
    source = ("IF OBJECT_ID(N'dbo.Excluded', 'U') IS NOT NULL BEGIN\n"
              "EXEC sp_addextendedproperty N'MS_Description', N'excluded', "
              "N'SCHEMA', N'dbo', N'TABLE', N'Excluded';\nEND;")
    with pytest.raises(MetadataProviderError, match="excluded_object_remains"):
        transform_provider_sql(source, source_path="sql/mixed.sql", unit_id="mixed",
                               excluded_objects={"dbo.Excluded"})


def test_excluded_cursor_target_cannot_reappear_after_expansion():
    source = """IF OBJECT_ID(N'dbo.Excluded', 'U') IS NOT NULL BEGIN
DECLARE @cols TABLE (name SYSNAME, descr NVARCHAR(400));
INSERT INTO @cols (name, descr) VALUES (N'Id', N'excluded');
DECLARE @name SYSNAME, @descr NVARCHAR(400);
DECLARE cur CURSOR FOR SELECT name, descr FROM @cols;
OPEN cur; FETCH NEXT FROM cur INTO @name, @descr;
WHILE @@FETCH_STATUS = 0 BEGIN
 EXEC sp_addextendedproperty 'MS_Description', @descr, 'SCHEMA', 'dbo', 'TABLE', 'Excluded', 'COLUMN', @name;
 FETCH NEXT FROM cur INTO @name, @descr; END
CLOSE cur; DEALLOCATE cur; END"""
    with pytest.raises(MetadataProviderError, match="excluded_object_remains"):
        transform_provider_sql(source, source_path="sql/cursor.sql", unit_id="cursor",
                               excluded_objects={"dbo.Excluded"})


@pytest.mark.parametrize("unrelated_text", [
    "-- dbo.Excluded is documented here\n",
    "/* dbo.Excluded is documented here */\n",
    "SELECT N'dbo.Excluded' AS Note;\n",
])
def test_excluded_name_in_unrelated_text_does_not_block(unrelated_text):
    source = (unrelated_text + "EXEC sp_addextendedproperty N'MS_Description', N'kept', "
              "N'SCHEMA', N'dbo', N'TABLE', N'Kept';")
    transformed, provenance = transform_provider_sql(
        source, source_path="sql/kept.sql", unit_id="kept", excluded_objects={"dbo.Excluded"})
    assert unrelated_text in transformed
    assert "EXEC sys.sp_addextendedproperty" in transformed
    assert [op["object_name"] for op in provenance["metadata_operations"]] == ["Kept"]

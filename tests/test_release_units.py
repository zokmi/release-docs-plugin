"""Real Git/source fixtures for complete unit and lifecycle boundaries."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

EF_FIXTURES = Path(__file__).parent / "fixtures/ef"


def ef_case(tmp_path, *, migration=True, snapshot=True, base_migration=False):
    root = tmp_path / "ef repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    baseline = root / "baseline.sql"
    baseline.write_text("CREATE TABLE dbo.Existing (Id int NOT NULL);", encoding="utf-8")
    for name in ("efcore_project.csproj", "efcore_context.cs"):
        (root / name).write_bytes((EF_FIXTURES / name).read_bytes())
    if base_migration:
        (root / "20250101000000_Old.cs").write_text("public class Old : Migration { protected override void Up(MigrationBuilder b) { } }", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    base = git(root, "rev-parse", "HEAD")
    if base_migration:
        (root / "20250101000000_Old.cs").unlink()
    names = []
    if migration:
        names += ["20260101000000_AddWidget.cs", "20260101000000_AddWidget.Designer.cs"]
    if snapshot:
        names += ["AppDbContextModelSnapshot.cs"]
    for name in names:
        (root / name).write_bytes((EF_FIXTURES / name).read_bytes())
    git(root, "add", ".")
    git(root, "commit", "--allow-empty", "-qm", "target")
    target = git(root, "rev-parse", "HEAD")
    from detect_entity_framework import EFDetection
    detection = EFDetection(framework="EF Core", version="8.0.4", provider="SQL Server",
                            contexts=["AppDbContext"], database_identity="server=.;database=app",
                            migration_paths=["20260101000000_AddWidget.cs"] if migration else [],
                            blocking=False)
    detection.evidence = [{"path": name, "revision": target,
                           "sha256": hashlib.sha256(subprocess.run(["git", "-C", str(root), "show", target + ":" + name], capture_output=True, check=True).stdout).hexdigest()}
                          for name in ["efcore_project.csproj", "efcore_context.cs", *names]]
    changes = [{"status": "A", "path": n} for n in names]
    return root, {"base_sha": base, "target_sha": target, "committed_changes": changes}, baseline, detection


def refresh_detection(root, evidence, detection):
    detection.evidence = [{"path": item["path"], "revision": evidence["target_sha"],
                           "sha256": hashlib.sha256(subprocess.run(["git", "-C", str(root), "show", evidence["target_sha"] + ":" + item["path"]], capture_output=True, check=True).stdout).hexdigest()}
                          for item in detection.evidence]


def test_derives_units_from_ef_migration_operations(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert not result.blocked, result.findings
    assert result.analysis_confidence == "high"
    assert {u["objects"][0] for u in result.units} >= {"dbo.Widgets", "dbo.Widgets.IX_Widgets_Id"}
    assert all(all(u.get(k) for k in ("preconditions", "target_definition", "skip_condition",
                                      "stop_condition", "validation_queries", "source_hash", "sql_hash"))
               for u in result.units)


def test_derives_ef6_create_table_without_ignoring_column_definition(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path, migration=False, snapshot=False)
    (root / "20260101000000_AddWidgetEf6.cs").write_bytes((EF_FIXTURES / "20260101000000_AddWidgetEf6.cs").read_bytes())
    (root / "20260101000000_AddWidgetEf6.Designer.cs").write_bytes((EF_FIXTURES / "20260101000000_AddWidgetEf6.Designer.cs").read_bytes())
    git(root, "add", ".")
    git(root, "commit", "-qm", "ef6 migration")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    detection.framework = "EF6"
    detection.migration_paths = ["20260101000000_AddWidgetEf6.cs"]
    detection.evidence = [{"path": p, "revision": evidence["target_sha"],
                           "sha256": hashlib.sha256(subprocess.run(["git", "-C", str(root), "show", evidence["target_sha"] + ":" + p], capture_output=True, check=True).stdout).hexdigest()}
                          for p in ("efcore_project.csproj", "efcore_context.cs", "20260101000000_AddWidgetEf6.cs",
                                    "20260101000000_AddWidgetEf6.Designer.cs")]
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert not result.blocked, result.findings
    assert len(result.units) == 1
    assert "[Id] int NOT NULL" in result.units[0]["target_definition"]["sql"]


def test_unsupported_ef_operation_never_yields_partial_units(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    path = root / "20260101000000_AddWidget.cs"
    path.write_text(path.read_text().replace('migrationBuilder.CreateIndex', 'migrationBuilder.Sql("DROP TABLE dbo.Existing");\n        migrationBuilder.CreateIndex'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "opaque operation")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "unsupported_migration_operation" in {f["code"] for f in result.findings}


def test_ef_index_options_cannot_be_silently_dropped(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    path = root / "20260101000000_AddWidget.cs"
    path.write_text(path.read_text().replace('column: "Id");', 'column: "Id", unique: true);'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "unique index")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "unsupported_migration_operation" in {f["code"] for f in result.findings}


def test_mixed_ef_and_uncovered_sql_blocks(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    (root / "patch.sql").write_text("ALTER TABLE dbo.Existing ADD Code int;", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "extra sql")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"].append({"status": "A", "path": "patch.sql"})
    detection.evidence = [{"path": p, "revision": evidence["target_sha"],
                           "sha256": hashlib.sha256(subprocess.run(["git", "-C", str(root), "show", evidence["target_sha"] + ":" + p], capture_output=True, check=True).stdout).hexdigest()}
                          for p in ("efcore_project.csproj", "efcore_context.cs", "20260101000000_AddWidget.cs",
                                    "20260101000000_AddWidget.Designer.cs", "AppDbContextModelSnapshot.cs")]
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "missing_authoritative_sql" in {f["code"] for f in result.findings}


def test_mixed_ef_and_complete_sql_preserves_both_units(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    sql = "CREATE TABLE dbo.Extra (Id int NOT NULL);"
    declaration = {"unit_id": "extra", "phase": "SCHEMA", "complete": True,
                   "objects": ["dbo.Extra"], "depends_on": [],
                   "preconditions": [{"query": "SELECT 1", "expected": 1}],
                   "target_definition": {"sql": sql},
                   "skip_condition": {"query": "SELECT 1", "expected": 1},
                   "stop_condition": {"query": "SELECT 0", "expected": 1},
                   "validation_queries": [{"query": "SELECT 1", "expected": 1}]}
    (root / "patch.sql").write_text("-- release-unit: " + json.dumps(declaration) + "\n" + sql, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "complete extra sql")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"].append({"status": "A", "path": "patch.sql"})
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert not result.blocked, result.findings
    assert {unit["unit_id"] for unit in result.units} == {"extra", "ef.20260101000000_AddWidget.table", "ef.20260101000000_AddWidget.index"}


def test_changed_ef_context_without_executable_unit_blocks(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    path = root / "efcore_context.cs"
    path.write_text(path.read_text() + "\n// changed mapping\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "context change")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"].append({"status": "M", "path": "efcore_context.cs"})
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "missing_authoritative_sql" in {f["code"] for f in result.findings}


def test_unrelated_application_changes_do_not_block_ef_units(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    unrelated = {
        "Greeting.cs": "public class Greeting { public string Text => \"Hello\"; }",
        "client.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>',
        "client.config": "<configuration><appSettings /></configuration>",
        "client.json": '{"theme": "blue"}',
    }
    for path, contents in unrelated.items():
        (root / path).write_text(contents, encoding="utf-8")
        evidence["committed_changes"].append({"status": "A", "path": path})
    git(root, "add", ".")
    git(root, "commit", "-qm", "unrelated application changes")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert not result.blocked, result.findings
    assert len(result.units) == 2
    assert not {item["source_path"] for item in result.sources} & set(unrelated)


def test_migration_like_application_filenames_do_not_count_as_ef_sources(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    ordinary = {"MigrationStatus.cs": "public class MigrationStatus { public string Label; }",
                "ModelSnapshotViewModel.cs": "public class ModelSnapshotViewModel { public int Count; }"}
    for path, contents in ordinary.items():
        (root / path).write_text(contents, encoding="utf-8")
        evidence["committed_changes"].append({"status": "A", "path": path})
    git(root, "add", ".")
    git(root, "commit", "-qm", "ordinary names")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert not result.blocked, result.findings
    sources = {item["source_path"]: item["kind"] for item in result.sources}
    assert not set(ordinary) & set(sources)
    assert sources["20260101000000_AddWidget.cs"] == "migration"
    assert sources["AppDbContextModelSnapshot.cs"] == "migration"


def test_stale_detection_revision_blocks(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    detection.evidence = [{"path": "20260101000000_AddWidget.cs", "revision": evidence["base_sha"], "sha256": "0" * 64}]
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "stale_ef_detection" in {f["code"] for f in result.findings}


def test_unlisted_target_migration_blocks(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    (root / "20260102000000_Extra.cs").write_text("public class Extra : Migration { protected override void Up(MigrationBuilder b) { b.RenameTable(name: \"Widgets\", newName: \"Renamed\"); } }", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "unlisted migration")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"].append({"status": "A", "path": "20260102000000_Extra.cs"})
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "incomplete_migration_chain" in {f["code"] for f in result.findings}


def test_composite_primary_key_blocks_incomplete_sql(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    path = root / "20260101000000_AddWidget.cs"
    path.write_text(path.read_text().replace("x => x.Id);", "x => new { x.Id, x.Code });"), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "composite key")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "unsupported_migration_operation" in {f["code"] for f in result.findings}


def test_ef6_unknown_operation_blocks(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path, migration=False, snapshot=False)
    source = (EF_FIXTURES / "20260101000000_AddWidgetEf6.cs").read_text()
    (root / "20260101000000_AddWidgetEf6.cs").write_text(source.replace("    }\n}", '        RenameTable("dbo.Widgets", "dbo.Renamed");\n    }\n}'), encoding="utf-8")
    (root / "20260101000000_AddWidgetEf6.Designer.cs").write_bytes((EF_FIXTURES / "20260101000000_AddWidgetEf6.Designer.cs").read_bytes())
    git(root, "add", ".")
    git(root, "commit", "-qm", "ef6 rename")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    refresh_detection(root, evidence, detection)
    detection.framework = "EF6"
    detection.migration_paths = ["20260101000000_AddWidgetEf6.cs"]
    detection.evidence = [{"path": p, "revision": evidence["target_sha"],
                           "sha256": hashlib.sha256(subprocess.run(["git", "-C", str(root), "show", evidence["target_sha"] + ":" + p], capture_output=True, check=True).stdout).hexdigest()}
                          for p in ("efcore_project.csproj", "efcore_context.cs", "20260101000000_AddWidgetEf6.cs",
                                    "20260101000000_AddWidgetEf6.Designer.cs")]
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "unsupported_migration_operation" in {f["code"] for f in result.findings}


@pytest.mark.parametrize("replacement", ['"objects": []', '"preconditions": "SELECT 1"', '"stop_condition": ["ok"]'])
def test_rejects_unstructured_unit_fields(fixture, replacement):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/table.sql"
    text = path.read_text()
    if replacement.startswith('"objects"'):
        text = text.replace('"objects": ["dbo.Core"]', replacement)
    elif replacement.startswith('"preconditions"'):
        text = text.replace('"preconditions": [{"query": "SELECT 1", "expected": 1}]', replacement)
    else:
        text = text.replace('"stop_condition": {"query": "SELECT 0", "expected": 1}', replacement)
    path.write_text(text, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "invalid unit")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert result.blocked and not result.units
    assert "incomplete_unit" in {f["code"] for f in result.findings}


def test_unsafe_source_sql_blocks_before_return(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/table.sql"
    path.write_text(path.read_text() + "\nGO\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "batch separator")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert result.blocked and not result.units
    assert "batch_separator" in {f["code"] for f in result.findings}


def test_blocks_model_drift_without_migration(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path, migration=False)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "model_drift_without_migration" in {f["code"] for f in result.findings}


def test_blocks_incomplete_migration_chain(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path, base_migration=True)
    result = analyzer.analyze_release_units(root, evidence, baseline, None, ef_detection=detection)
    assert result.blocked and not result.units
    assert "incomplete_migration_chain" in {f["code"] for f in result.findings}


def test_requires_complete_unit_conditions_and_validation(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/table.sql"
    path.write_text(path.read_text().replace('"validation_queries": [{"query": "SELECT 1", "expected": 1}]', '"validation_queries": []'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "incomplete")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert result.blocked and not result.units
    assert "incomplete_unit" in {f["code"] for f in result.findings}


def test_blocks_transitive_exclusion_impact(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    result = analyzer.analyze_release_units(root, evidence, baseline, "#5005")
    assert result.blocked and not result.units
    assert "excluded_dependency" in {f["code"] for f in result.findings}


def test_blocks_partial_migration_exclusion(tmp_path):
    analyzer, _ = api()
    root, evidence, baseline, detection = ef_case(tmp_path)
    evidence["migration_issues"] = {"20260101000000_AddWidget.cs": ["#5005", "#6006"]}
    result = analyzer.analyze_release_units(root, evidence, baseline, "#5005", ef_detection=detection)
    assert result.blocked and not result.units
    assert "partial_exclusion" in {f["code"] for f in result.findings}

SCRIPTS = Path(__file__).parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))


def api():
    assert (SCRIPTS / "analyze_release_units.py").exists(), "unit analyzer is missing"
    assert (SCRIPTS / "lifecycle_store.py").exists(), "lifecycle store is missing"
    return importlib.import_module("analyze_release_units"), importlib.import_module("lifecycle_store")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout.decode().strip()


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "中文 source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    baseline = root / "baseline.sql"
    baseline.write_text("CREATE TABLE dbo.Existing (Id int);", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    base = git(root, "rev-parse", "HEAD")
    specs = [
        ("table", "SCHEMA", [], ["#5005"], "CREATE TABLE dbo.Core (Id int);"),
        ("column", "REPAIR", ["table"], ["#5005"], "ALTER TABLE dbo.Core ADD Code int;"),
        ("index", "REPAIR", ["column"], ["#5005"], "CREATE INDEX IX_Code ON dbo.Core(Code);"),
        ("fk", "REPAIR", ["table"], ["#5005"], "ALTER TABLE dbo.Core ADD CONSTRAINT FK_Core FOREIGN KEY(Id) REFERENCES dbo.Existing(Id);"),
        ("data", "DATA", ["column"], [], "INSERT INTO dbo.Core VALUES (1, 2); -- NEVER_STORE_SECRET"),
        ("validate", "VALIDATION", ["data"], [], "SELECT COUNT(*) FROM dbo.Core;"),
    ]
    changes = []
    for unit, phase, deps, issues, sql in specs:
        path = "sql/" + unit + ".sql"
        (root / "sql").mkdir(exist_ok=True)
        declaration = {"unit_id": unit, "phase": phase, "depends_on": deps,
                       "issues": issues, "objects": ["dbo.Core"], "complete": True,
                       "preconditions": [{"query": "SELECT 1", "expected": 1}],
                       "target_definition": {"sql": sql},
                       "skip_condition": {"query": "SELECT 1", "expected": 1},
                       "stop_condition": {"query": "SELECT 0", "expected": 1},
                       "validation_queries": [{"query": "SELECT 1", "expected": 1}]}
        (root / path).write_text("-- release-unit: " + json.dumps(declaration) + "\n" + sql,
                                encoding="utf-8")
        changes.append({"status": "A", "path": path})
    git(root, "add", ".")
    git(root, "commit", "-qm", "units")
    evidence = {"base_sha": base, "target_sha": git(root, "rev-parse", "HEAD"),
                "committed_changes": changes, "release_id": "fixture-release"}
    return root, evidence, baseline


def test_ordered_units_exclusion_contains_whole_units_and_transitive_impact(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    result = analyzer.analyze_release_units(root, evidence, baseline, "#5005")
    assert not result.units
    exclusion = result.exclusions[0]
    assert exclusion["unit_ids"] == ["table", "column", "fk", "index"]
    assert exclusion["dependency_impact"] == ["data", "validate"]
    assert exclusion["reinstatement_conditions"]
    assert exclusion["review_status"] == "pending"
    assert "excluded_dependency" in {f["code"] for f in result.findings}
    assert exclusion["units"][0]["source_revision"] == evidence["target_sha"]
    assert exclusion["units"][0]["source_hash"] == hashlib.sha256((root / "sql/table.sql").read_bytes()).hexdigest()


def test_requested_revision_does_not_read_current_worktree(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    (root / "sql/table.sql").write_text("BAD WORKTREE SQL", encoding="utf-8")
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert "CREATE TABLE" in result.units[0]["sql"]
    assert "BAD WORKTREE" not in result.units[0]["sql"]


def test_missing_authoritative_sql_blocks_database_project_inference(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    (root / "db.sqlproj").write_text("<Project />", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "missing SQL")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"].append({"status": "A", "path": "db.sqlproj"})
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert any(f["code"] == "missing_authoritative_sql" and f["blocking"] for f in result.findings)


def test_partial_issue_ownership_blocks_exclusion_instead_of_splitting(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/table.sql"
    path.write_text(path.read_text().replace('["#5005"]', '["#5005", "#6006"]'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "shared unit")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, "#5005")
    assert any(f["code"] == "partial_exclusion" and f["blocking"] for f in result.findings)
    assert not result.exclusions


def test_lifecycle_is_deterministic_immutable_and_contains_no_source_contents(fixture, tmp_path):
    analyzer, store = api()
    root, evidence, baseline = fixture
    result = analyzer.analyze_release_units(root, evidence, baseline, "#5005")
    run = tmp_path / ".release-docs/runs/run-1"
    manifest = store.write_lifecycle_run(run, result)
    assert manifest == run / "lifecycle_exclusion_manifest.json"
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    store.write_lifecycle_run(run, result)
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
    text = b"".join(before.values()).decode()
    assert "NEVER_STORE_SECRET" not in text and "CREATE TABLE" not in text
    document = json.loads(manifest.read_text())
    assert document["exclusions"][0]["unit_ids"] == ["table", "column", "fk", "index"]
    policy = json.loads((run / "lifecycle_metadata.json").read_text())
    assert policy["retention"]["failed_days"] == 7
    assert policy["retention"]["cleanup_after_success"] is True
    assert policy["cleanup_status"] == "pending_success"
    result.exclusions.clear()
    with pytest.raises(ValueError, match="immutable"):
        store.write_lifecycle_run(run, result)


def test_lifecycle_rejects_operator_output_path_without_creating_files(fixture, tmp_path):
    analyzer, store = api()
    result = analyzer.analyze_release_units(*fixture, None)
    output = tmp_path / "release-output"
    with pytest.raises(ValueError, match="lifecycle"):
        store.write_lifecycle_run(output, result)
    assert not output.exists()


def test_unknown_exclusion_and_unresolved_dependency_block(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/data.sql"
    path.write_text(path.read_text().replace('["column"]', '["missing"]'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "bad dependency")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, "#9999")
    assert {"unresolved_dependency", "unresolved_exclusion"} <= {f["code"] for f in result.findings if f["blocking"]}


def test_explicit_deployment_artifact_covers_project_and_migration_without_inference(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    for path in ("db.sqlproj", "snapshot.dacpac", "migration.cs"):
        (root / path).write_bytes(b"SOURCE_SECRET_DO_NOT_EMIT")
        evidence["committed_changes"].append({"status": "A", "path": path})
    (root / "deployment.sql").write_text("SELECT 1; -- DEPLOYMENT_SECRET", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "deployment mapping")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["execution_units"] = [{"unit_id": "mapped", "phase": "VALIDATION", "complete": True,
                                    "source_path": "deployment.sql", "covers": ["db.sqlproj", "snapshot.dacpac", "migration.cs"],
                                    "objects": ["dbo.Core"],
                                    "preconditions": [{"query": "SELECT 1", "expected": 1}],
                                    "target_definition": {"sql": "SELECT 1; -- DEPLOYMENT_SECRET"},
                                    "skip_condition": {"query": "SELECT 1", "expected": 1},
                                    "stop_condition": {"query": "SELECT 0", "expected": 1},
                                    "validation_queries": [{"query": "SELECT 1", "expected": 1}],
                                    "token": "IGNORED_SECRET"}]
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert not result.blocked
    unit = next(u for u in result.units if u["unit_id"] == "mapped")
    assert unit["source_line"] == 1
    assert unit["covered_sources"] == ["db.sqlproj", "migration.cs", "snapshot.dacpac"]
    assert "IGNORED_SECRET" not in json.dumps(unit)
    assert {"database_project", "dacpac", "migration"} <= {s["kind"] for s in result.sources}


def test_dependency_cycle_blocks_instead_of_returning_ready_units(fixture):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    path = root / "sql/column.sql"
    path.write_text(path.read_text().replace('["table"]', '["index"]'), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "cycle")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert result.blocked
    assert "dependency_cycle_or_missing_unit" in {f["code"] for f in result.findings}


def test_operator_directory_hardlink_cannot_be_overwritten_through_lifecycle(fixture, tmp_path):
    analyzer, store = api()
    result = analyzer.analyze_release_units(*fixture, None)
    run = tmp_path / ".release-docs/runs/hardlink"
    run.mkdir(parents=True)
    operator = tmp_path / "operator.json"
    operator.write_text("operator file", encoding="utf-8")
    try:
        (run / "lifecycle_exclusion_manifest.json").hardlink_to(operator)
    except PermissionError:
        pytest.skip("Current Windows sandbox disallows hardlink creation")
    with pytest.raises(ValueError, match="Linked"):
        store.write_lifecycle_run(run, result)
    assert operator.read_text() == "operator file"


@pytest.mark.parametrize("source", ["migration.cs", "db.sqlproj"])
def test_non_sql_execution_descriptor_cannot_cover_itself_and_be_ready(fixture, source):
    analyzer, _ = api()
    root, evidence, baseline = fixture
    (root / source).write_text("NOT EXECUTABLE SQL", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "self coverage")
    evidence["target_sha"] = git(root, "rev-parse", "HEAD")
    evidence["committed_changes"] = [{"status": "A", "path": source}]
    evidence["execution_units"] = [{"unit_id": "pretend", "phase": "SCHEMA", "complete": True,
                                    "source_path": source, "covers": [source]}]
    result = analyzer.analyze_release_units(root, evidence, baseline, None)
    assert result.blocked, "A non-SQL descriptor with zero executable units must block"
    assert not result.units
    assert "missing_authoritative_sql" in {f["code"] for f in result.findings}


@pytest.mark.parametrize("unsafe", ["..", "../escape", "nested/run", "nested\\run", "/absolute"])
def test_unsafe_run_id_is_rejected_before_any_lifecycle_write(fixture, tmp_path, unsafe):
    analyzer, store = api()
    result = analyzer.analyze_release_units(*fixture, None)
    root = tmp_path / ".release-docs/runs" / unsafe
    with pytest.raises(ValueError, match="lifecycle"):
        store.write_lifecycle_run(root, result)
    assert not list(tmp_path.rglob("lifecycle_exclusion_manifest.json"))


def test_traversal_before_lifecycle_root_is_rejected(fixture, tmp_path):
    analyzer, store = api()
    result = analyzer.analyze_release_units(*fixture, None)
    root = tmp_path / "nominal/../outside/.release-docs/runs/run-1"
    with pytest.raises(ValueError, match="lifecycle"):
        store.write_lifecycle_run(root, result)
    assert not (tmp_path / "outside").exists()

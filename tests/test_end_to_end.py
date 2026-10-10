"""Git-to-review integration; recorded adapter responses do not execute SQL Server."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
import sys
import pytest

PLUGIN = Path(__file__).parents[1]
sys.path.insert(0, str(PLUGIN / "skills/release-docs/scripts"))
sys.path.insert(0, str(PLUGIN / "skills/release-docs-review/scripts"))
ROUNDS = ("validate_only", "commit", "rerun", "injected_failure")
PRESERVED = {"dbo.Customer": "Id=2 Flag=7; Id=3 Flag=NULL; Id=4 Flag=1; Id=5 Flag=-1"}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _expectations():
    rows = []
    for key, case, before, after in (
        ("changed", "existing_value", "Id=1 Flag=0", "Id=1 Flag=1"),
        ("preserved", "preserved_data", "Id=2 Flag=7", "Id=2 Flag=7"),
        ("null", "null_boundary", "Id=3 Flag=NULL", "Id=3 Flag=NULL"),
        ("existing", "duplicate_candidate", "Id=4 Flag=1", "Id=4 Flag=1"),
        ("boundary", "value_boundary", "Id=5 Flag=-1", "Id=5 Flag=-1"),
        ("empty", "empty_set", "count=0", "count=0"),
        ("count", "row_count", "count=5", "count=5"),
    ):
        rows.append({"id": key, "case": case, "seed_row_id": "Customer/" + key,
                     "expected_by_round": {
                         "validate_only": {"before": before, "after": before},
                         "commit": {"before": before, "after": after},
                         "rerun": {"before": after, "after": after},
                         "injected_failure": {"before": before, "after": before}}})
    return rows


def _recorded_adapter(**kwargs):
    """Independent hand-written observations; never an executable SQL adapter."""
    name = kwargs["round_name"]
    committed = name in ("commit", "rerun")
    observations = {
        "changed": ("Id=1 Flag=1" if name == "rerun" else "Id=1 Flag=0",
                    "Id=1 Flag=1" if committed else "Id=1 Flag=0"),
        "preserved": ("Id=2 Flag=7", "Id=2 Flag=7"), "null": ("Id=3 Flag=NULL", "Id=3 Flag=NULL"),
        "existing": ("Id=4 Flag=1", "Id=4 Flag=1"), "boundary": ("Id=5 Flag=-1", "Id=5 Flag=-1"),
        "empty": ("count=0", "count=0"), "count": ("count=5", "count=5"),
    }
    checks = {
        "validate_only": ["fresh baseline", "schema/data checked then rollback", "excluded scope preserved"],
        "commit": ["fresh baseline", "schema/data committed", "excluded scope preserved"],
        "rerun": ["new session on committed database", "schema/data converged", "excluded scope preserved"],
        "injected_failure": ["expected unit error", "rollback", "THROW", "later units did not execute"],
    }
    return {"status": "passed", "exit_code": 0,
            "database_id": {"validate_only": "db-v", "commit": "db-c", "rerun": "db-c", "injected_failure": "db-f"}[name],
            "session_id": "session-" + name, "committed_state": "state-c" if committed else "",
            "checks": checks[name], "preserved_data_summary": dict(PRESERVED),
            "data_checks": [{"unit_id": "backfill", "id": key, "seed_row_id": "Customer/" + key,
                             "passed": True, "before": before, "after": after}
                            for key, (before, after) in observations.items()],
            "error_output_summary": "Expected error 51099 in backfill; rollback; THROW; later units did not execute"
                                    if name == "injected_failure" else ""}


def _pipeline(tmp_path, adapter=_recorded_adapter, parameters=False, unguarded_ef=False):
    from analyze_release_units import analyze_release_units
    from assemble_deployment_sql import assemble_deployment_sql
    from collect_release_evidence import collect_release_evidence
    from detect_entity_framework import detect_entity_framework
    from lifecycle_store import write_lifecycle_run
    from render_release_documents import render_release_documents
    from run_local_validation import run_local_validation

    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    baseline = repo / "baseline.sql"
    _write(baseline, "CREATE TABLE dbo.Customer (Id int NOT NULL PRIMARY KEY, Flag int NULL);\n")
    for name in ("efcore_project.csproj", "efcore_context.cs"):
        _write(repo / name, (PLUGIN / "tests/fixtures/ef" / name).read_text())
    with (repo / "efcore_context.cs").open("a", encoding="utf-8") as stream:
        stream.write('services.AddDbContext<AppDbContext>(o => o.UseSqlServer(configuration.GetConnectionString("MainDb")));')
    _write(repo / "appsettings.json", '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb;Password=SOURCE_SECRET"}}')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    base = _git(repo, "rev-parse", "HEAD")
    for name in ("20260101000000_AddWidget.cs", "20260101000000_AddWidget.Designer.cs", "AppDbContextModelSnapshot.cs"):
        _write(repo / name, (PLUGIN / "tests/fixtures/ef" / name).read_text())
    descriptors = []
    for uid, phase, obj, sql, issues, dependencies in (
        ("backfill", "DATA", "dbo.Customer", "UPDATE dbo.Customer SET Flag=1 WHERE Id=1 AND Flag=0;", [], []),
        ("deferred", "SCHEMA", "dbo.Deferred", "CREATE TABLE dbo.Deferred (Id int);", ["#5005"], []),
        ("verify", "VALIDATION", "dbo.Customer", "IF EXISTS (SELECT 1 FROM dbo.Customer WHERE Id=1 AND Flag<>1) THROW 51099, N'Backfill failed', 1;", [], ["backfill"]),
    ):
        path = uid + ".sql"
        _write(repo / path, sql)
        descriptors.append({"unit_id": uid, "phase": phase, "complete": True,
                            "source_path": path, "objects": [obj], "issues": issues, "depends_on": dependencies,
                            "preconditions": [{"query": "SELECT 1", "expected": 1}], "target_definition": {"sql": sql},
                            "skip_condition": {"query": "SELECT 1", "expected": 1},
                            "stop_condition": {"query": "SELECT 0", "expected": 1},
                            "validation_queries": [{"query": "SELECT 1", "expected": 1}]})
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "migration and data change")
    target = _git(repo, "rev-parse", "HEAD")
    evidence = collect_release_evidence(repo, base, target)
    evidence["execution_units"] = descriptors
    detection = detect_entity_framework(repo, evidence["source_scope"])
    assert not detection.blocking, detection.findings
    analysis = analyze_release_units(repo, evidence, baseline, "exclude #5005", ef_detection=detection)
    assert not analysis.blocked, analysis.findings
    if unguarded_ef:
        # Model a stale pre-integration EF artifact. Review must not accept it.
        unit = next(unit for unit in analysis.units if unit["unit_id"].endswith(".table"))
        unit["sql"] = "CREATE TABLE [dbo].[Widgets] ([Id] int NOT NULL, CONSTRAINT [PK_Widgets] PRIMARY KEY ([Id]));"
        unit["sql_hash"] = hashlib.sha256(unit["sql"].encode()).hexdigest()
        unit["target_definition"] = {"sql": unit["sql"]}
    data_unit = next(unit for unit in analysis.units if unit["unit_id"] == "backfill")
    data_unit["expected_assertions"] = _expectations()
    analysis.structure_changes = [{"unit_id": unit["unit_id"], "kind": "table", "name": unit["objects"][0],
                                   "description": "EF migration structure", "impact": "Widget storage"}
                                  for unit in analysis.units if unit["phase"] == "SCHEMA"]
    if parameters:
        analysis.parameter_changes = [{"environment": "test", "service": "app", "key": "ApiPassword",
                                       "sensitive": True, "new_value": "PARAMETER_SECRET", "format_example": "PARAMETER_SECRET",
                                       "apply": "secret store", "reload": "restart app", "validation": "health check"}]
    analysis.parameters_applicable = parameters
    run = repo / ".release-docs/runs/e2e"
    run.mkdir(parents=True)
    fixture = run / "fixture.sql"
    _write(run / "baseline.sql", baseline.read_text())
    _write(fixture, "INSERT INTO dbo.Customer VALUES (1,0),(2,7),(3,NULL),(4,1),(5,-1);\n")
    fixture_manifest = run / "fixture.json"
    _write(fixture_manifest, json.dumps({"usage": "Backfill target, preserved rows, NULL, existing target, boundary and row counts",
        "expected_preserved_data_summary": PRESERVED,
        "coverage": {"backfill": {case: True for case in ("existing_value", "preserved_data", "duplicate_candidate", "null_boundary", "value_boundary", "empty_set", "row_count")}},
        "seed_rows": [{"unit_id": "backfill", "row_id": row["seed_row_id"], "purpose": row["case"]} for row in _expectations()]}))
    excluded = {uid for entry in analysis.exclusions for uid in entry["unit_ids"]}
    artifact = assemble_deployment_sql([u for u in analysis.units if u["unit_id"] not in excluded], run / "01_部署SQL.sql", {"release_id": "e2e"})
    calls = []

    def recording_adapter(**kwargs):
        calls.append(kwargs)
        return adapter(**kwargs)

    localdb = run_local_validation(artifact.path, server="(localdb)\\MSSQLLocalDB", database="e2e_release",
        baseline_source=str(run / "baseline.sql"), fixture_source=str(fixture), fixture_manifest=fixture_manifest,
        data_units=[data_unit], adapter_provenance="recorded-test-double/1", provider_version="fixture-sqlserver/1",
        tool_version="fixture-tool/1", command=["recorded-adapter", "--fresh-session"],
        executor=recording_adapter if adapter else None)
    manifest = write_lifecycle_run(run, analysis, localdb_validation=localdb,
        operator_contract={"parameters_applicable": parameters},
        execution_artifact={"path": str(artifact.path), "sha256": artifact.sha256})
    output = repo / "operator"
    render_release_documents(analysis, artifact, manifest, output)
    return repo, run, output, analysis, localdb, calls


@pytest.mark.parametrize("parameters", [False, True])
def test_collection_to_review_preserves_allowlist_and_localdb_evidence(tmp_path, parameters):
    from lifecycle_store import finalize_lifecycle_run
    from validate_release_output import validate_release_output
    repo, run, output, analysis, localdb, calls = _pipeline(tmp_path, parameters=parameters)
    assert localdb["status"] == "passed", localdb["reason"]
    findings = validate_release_output(output, run)
    assert {item["code"]: item["status"] for item in findings if item["code"].endswith("_status")} == {
        "static_sql_status": "通過", "sql_content_status": "待確認", "deployment_validation_status": "通過"}, findings
    assert {p.name for p in output.iterdir()} == ({"00_上線指引.md", "01_部署SQL.sql"}
                                                | ({"02_參數異動.md"} if parameters else set()))
    assert (output / "01_部署SQL.sql").read_bytes() == (run / "01_部署SQL.sql").read_bytes()
    sql = (output / "01_部署SQL.sql").read_text()
    assert "dbo.Deferred" not in sql
    assert "Widgets" in sql and "UPDATE dbo.Customer" in sql
    assert [call["round_name"] for call in calls] == list(ROUNDS)
    assert [call["fresh_database"] for call in calls] == [True, True, False, True]
    assert all(call["fresh_session"] for call in calls)
    assert calls[2]["committed_state"] == "state-c"
    assert [call["validate_only"] for call in calls] == [True, False, False, False]
    assert [call["inject_failure"] for call in calls] == [False, False, False, True]
    for row in localdb["rounds"].values():
        assert row["artifact_sha256"] == hashlib.sha256((run / "01_部署SQL.sql").read_bytes()).hexdigest()
        for source, digest in (("baseline_source", "baseline_sha256"), ("fixture_source", "fixture_sha256"),
                               ("fixture_manifest", "fixture_manifest_sha256")):
            assert row[digest] == hashlib.sha256(Path(row[source]).read_bytes()).hexdigest()
        assert row["preserved_data_summary"] == PRESERVED
    delivered = "\n".join(path.read_text() for path in output.iterdir())
    for forbidden in ("SOURCE_SECRET", "PARAMETER_SECRET", "lifecycle_exclusion_manifest.json", str(tmp_path),
                      ".release-docs/runs", "recorded-adapter"):
        assert forbidden not in delivered
    exclusion = json.loads((run / "lifecycle_exclusion_manifest.json").read_text())["exclusions"][0]
    assert exclusion["unit_ids"] == ["deferred"] and exclusion["dependency_impact"] == []
    assert exclusion["units"][0]["source_revision"] == analysis.source_scope["target_sha"]
    _write(run / "temporary/adapter.log", "temporary trace")
    assert finalize_lifecycle_run(run, review_status="success", delivery_status="success")
    assert not (run / "temporary").exists()
    assert (run / "fixture.sql").is_file() and (run / "localdb_validation.json").is_file()
    assert validate_release_output(output, run) == findings
    # Generation and review both ship a review_fingerprint.py; load the
    # review implementation by path so test collection order cannot swap it.
    review_path = PLUGIN / "skills/release-docs-review/scripts/review_fingerprint.py"
    spec = importlib.util.spec_from_file_location("e2e_release_review_fingerprint", review_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    review_fingerprint = module.review_fingerprint
    before = review_fingerprint(repo, output, run, analysis.source_scope)
    _write(run / "fixture.sql", "INSERT INTO dbo.Customer VALUES (9,99);\n")
    assert review_fingerprint(repo, output, run, analysis.source_scope).sha256 != before.sha256
    assert next(f["status"] for f in validate_release_output(output, run)
                if f["code"] == "deployment_validation_status") == "待確認"


@pytest.mark.parametrize("damage", ["missing_preserved", "wrong_preserved", "same_checks", "missing_adapter"])
def test_incomplete_adapter_evidence_cannot_claim_deployment_pass(tmp_path, damage):
    from validate_release_output import validate_release_output
    def adapter(**kwargs):
        raw = _recorded_adapter(**kwargs)
        if damage == "missing_preserved":
            raw.pop("preserved_data_summary")
        elif damage == "wrong_preserved":
            raw["preserved_data_summary"] = {"dbo.Customer": "Id=2 Flag=0"}
        elif damage == "same_checks":
            raw["checks"] = ["expected error rollback THROW later units did not execute"]
        return raw
    _, run, output, _, _, _ = _pipeline(tmp_path, adapter=None if damage == "missing_adapter" else adapter)
    findings = validate_release_output(output, run)
    assert next(f["status"] for f in findings if f["code"] == "deployment_validation_status") == "待確認"
    assert next(f["status"] for f in findings if f["code"] == "sql_content_status") == "待確認"
    assert "LocalDB：通過" not in (output / "00_上線指引.md").read_text()


def test_deliberate_adapter_failure_is_retained_without_deployment_success(tmp_path):
    from validate_release_output import validate_release_output
    def adapter(**kwargs):
        if kwargs["round_name"] == "injected_failure":
            raise RuntimeError("failure probe did not capture rollback evidence")
        return _recorded_adapter(**kwargs)
    _, run, output, _, localdb, _ = _pipeline(tmp_path, adapter=adapter)
    assert localdb["status"] == "failed"
    assert "failure probe" in localdb["rounds"]["injected_failure"]["error_output_summary"]
    findings = validate_release_output(output, run)
    assert next(f["status"] for f in findings if f["code"] == "deployment_validation_status") == "未通過"
    assert next(f["status"] for f in findings if f["code"] == "sql_content_status") == "待確認"


def test_unguarded_ef_create_cannot_pass_content_review(tmp_path):
    from validate_release_output import validate_release_output
    _, run, output, _, _, _ = _pipeline(tmp_path, unguarded_ef=True)
    findings = validate_release_output(output, run)
    assert any(f["code"] == "rerun_risk" and f["blocking"] for f in findings)
    assert next(f["status"] for f in findings if f["code"] == "sql_content_status") == "未通過"


def test_unprovable_ef_column_definition_blocks_before_assembly(tmp_path):
    from test_release_units import ef_case, refresh_detection
    from analyze_release_units import analyze_release_units
    repo, evidence, baseline, detection = ef_case(tmp_path)
    migration = repo / "20260101000000_AddWidget.cs"
    _write(migration, migration.read_text().replace('type: "int"', 'type: "datetime2"'))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "unsupported column shape")
    evidence["target_sha"] = _git(repo, "rev-parse", "HEAD")
    refresh_detection(repo, evidence, detection)
    analysis = analyze_release_units(repo, evidence, baseline, None, ef_detection=detection)
    assert analysis.blocked and not analysis.units
    assert "unsupported_migration_operation" in {item["code"] for item in analysis.findings}

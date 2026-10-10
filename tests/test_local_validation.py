"""Contract tests for the opt-in isolated LocalDB validation runner."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills/release-docs/scripts/run_local_validation.py"
spec = importlib.util.spec_from_file_location("run_local_validation", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_missing_runner_returns_not_run_with_all_rounds(tmp_path):
    artifact = tmp_path / "01_部署SQL.sql"
    artifact.write_text("SELECT 1;\n", encoding="utf-8")
    result = module.run_local_validation(artifact, server="(localdb)\\MSSQLLocalDB", database="release_test")
    assert result["status"] == "not_run"
    assert result["reason"]
    assert result["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert set(result["rounds"]) == {"validate_only", "commit", "rerun", "injected_failure"}
    assert all(r["status"] == "not_run" for r in result["rounds"].values())


def test_production_server_is_rejected_before_executor(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("SELECT 1;", encoding="utf-8")
    calls = []
    try:
        module.run_local_validation(artifact, server="prod-sql", database="release", executor=lambda **kw: calls.append(kw))
    except ValueError as exc:
        assert "LocalDB" in str(exc)
    else:
        raise AssertionError("production server must be rejected")
    assert calls == []


def test_localdb_server_must_be_anchored_and_named_instance(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("SELECT 1;", encoding="utf-8")
    for server in ("prod(localdb)\\MSSQLLocalDB", "prefix(localdb)\\MSSQLLocalDB", "(localdb)\\MSSQLLocalDB extra"):
        try:
            module.run_local_validation(artifact, server=server, database="test", executor=lambda **kw: {})
        except ValueError as exc:
            assert "LocalDB" in str(exc)
        else:
            raise AssertionError(server)


def test_four_rounds_use_fresh_sessions_and_expected_transaction_contract(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("-- artifact\n", encoding="utf-8")
    baseline = tmp_path / "old-schema.sql"
    fixture = tmp_path / "test-data.sql"
    baseline.write_text("CREATE TABLE old_table (id int);", encoding="utf-8")
    fixture.write_text("INSERT INTO old_table VALUES (1);", encoding="utf-8")
    calls = []

    def executor(**kwargs):
        calls.append(kwargs)
        if kwargs["round_name"] == "injected_failure":
            return {"exit_code": 0, "status": "passed", "checks": [
                "expected THROW observed", "rollback confirmed", "later units did not execute"
            ], "error_output_summary": "Expected SQL error 51000; rollback and stop confirmed"}
        return {"exit_code": 0, "status": "passed", "checks": [
            "fresh baseline", "new session", "transaction checks passed"
        ], "error_output_summary": ""}

    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="release_test",
        baseline_source=str(baseline), fixture_source=str(fixture),
        executor=executor, command=["sqlcmd", "-S", "(localdb)\\MSSQLLocalDB"],
        adapter_provenance="fake-disposable-adapter/1",
        provider_version="sqlcmd-localdb/1", tool_version="mssql/1",
    )
    assert result["status"] == "passed"
    assert len(calls) == 4
    assert [c["round_name"] for c in calls] == ["validate_only", "commit", "rerun", "injected_failure"]
    assert all(c["fresh_session"] is True for c in calls)
    assert calls[0]["validate_only"] is True and calls[1]["validate_only"] is False
    assert calls[3]["inject_failure"] is True
    assert len({c["baseline_source"] for c in calls if c["round_name"] != "rerun"}) == 3
    assert "committed-from=commit" in calls[2]["baseline_source"]
    assert all(r["provider_version"] and r["tool_version"] for r in result["rounds"].values())
    assert all(r["baseline_sha256"] and r["fixture_sha256"] for r in result["rounds"].values())


def test_executor_failure_is_structured_and_never_claims_pass(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("SELECT 1;", encoding="utf-8")
    baseline = tmp_path / "old.sql"
    fixture = tmp_path / "data.sql"
    baseline.write_text("old", encoding="utf-8")
    fixture.write_text("data", encoding="utf-8")

    def executor(**kwargs):
        return {"status": "failed", "exit_code": 1, "checks": ["rollback attempted"],
                "error_output_summary": "SQL ERROR_NUMBER=50001 phase=DATA"}

    result = module.run_local_validation(artifact, server="(localdb)\\MSSQLLocalDB", database="test",
                                         baseline_source=str(baseline), fixture_source=str(fixture),
                                         adapter_provenance="fake/1", provider_version="sqlcmd/1",
                                         tool_version="mssql/1", executor=executor)
    assert result["status"] == "failed"
    assert result["rounds"]["validate_only"]["exit_code"] == 1
    assert "SQL ERROR_NUMBER" in result["rounds"]["validate_only"]["error_output_summary"]


def test_executor_requires_real_fixture_paths_and_adapter_provenance(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("SELECT 1;", encoding="utf-8")
    for kwargs in ({"adapter_provenance": ""}, {"adapter_provenance": "fake/1", "baseline_source": "missing", "fixture_source": "missing"}):
        try:
            module.run_local_validation(artifact, server="(localdb)\\MSSQLLocalDB", database="test",
                                        executor=lambda **kw: {}, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid adapter or fixture must block a pass")


def test_evidence_can_be_written_inside_lifecycle_only(tmp_path):
    artifact = tmp_path / "01.sql"
    artifact.write_text("SELECT 1;", encoding="utf-8")
    lifecycle = tmp_path / ".release-docs" / "runs" / "run-1"
    lifecycle.mkdir(parents=True)
    result = module.run_local_validation(artifact, server="(localdb)\\MSSQLLocalDB", database="test")
    path = module.write_localdb_evidence(lifecycle, result)
    assert path == lifecycle / "localdb_validation.json"
    assert path.exists()
    assert "not_run" in path.read_text(encoding="utf-8")
    try:
        module.write_localdb_evidence(tmp_path / "operator", result)
    except ValueError as exc:
        assert "lifecycle" in str(exc)
    else:
        raise AssertionError("operator evidence path must be rejected")


def test_success_cleanup_removes_only_temporary_material(tmp_path):
    lifecycle_spec = importlib.util.spec_from_file_location(
        "lifecycle_store_cleanup", ROOT / "skills/release-docs/scripts/lifecycle_store.py")
    lifecycle = importlib.util.module_from_spec(lifecycle_spec)
    lifecycle_spec.loader.exec_module(lifecycle)
    run = tmp_path / ".release-docs" / "runs" / "run-cleanup"
    (run / "temporary").mkdir(parents=True)
    (run / "temporary" / "sqlcmd.log").write_text("trace", encoding="utf-8")
    (run / "lifecycle_metadata.json").write_text("audit", encoding="utf-8")
    assert lifecycle.finalize_lifecycle_run(
        run, review_status="success", delivery_status="success") is True
    assert (run / "lifecycle_metadata.json").exists()
    assert not (run / "temporary").exists()


def _data_case(tmp_path, *, manifest=True):
    artifact = tmp_path / "01.sql"
    baseline = tmp_path / "baseline.sql"
    fixture = tmp_path / "fixture.sql"
    artifact.write_text("UPDATE dbo.Customer SET Flag=1 WHERE Id=1;", encoding="utf-8")
    baseline.write_text("CREATE TABLE dbo.Customer (Id int, Flag int);", encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Customer VALUES (1,0),(2,0);", encoding="utf-8")
    expectations = tmp_path / "fixture.json"
    expectations.write_text(json.dumps({
        "usage": "existing and preserved customer rows",
        "expected_preserved_data_summary": {"dbo.Customer": "Id=2, Flag=0"},
        "assertions": [
            {"unit_id": "customer-data", "id": "changed-row", "case": "existing_value", "before": "Id=1 Flag=0", "after": "Id=1 Flag=1"},
            {"unit_id": "customer-data", "id": "preserved-row", "case": "preserved_data", "before": "Id=2 Flag=0", "after": "Id=2 Flag=0"},
            {"unit_id": "customer-data", "id": "unique-edge", "case": "duplicate_candidate", "before": "count=0", "after": "count=0"},
            {"unit_id": "customer-data", "id": "null-edge", "case": "null_boundary", "before": "count=1", "after": "count=1"},
        ],
    }), encoding="utf-8")
    return artifact, baseline, fixture, expectations


def _data_executor(**kwargs):
    values = {"changed-row": ("Id=1 Flag=0", "Id=1 Flag=1"),
              "preserved-row": ("Id=2 Flag=0", "Id=2 Flag=0"),
              "unique-edge": ("count=0", "count=0"),
              "null-edge": ("count=1", "count=1")}
    checks = [{"unit_id": "customer-data", "id": key, "passed": True,
               "before": before, "after": after}
              for key, (before, after) in values.items()]
    if kwargs["round_name"] == "injected_failure":
        return {"status": "passed", "exit_code": 0, "checks": ["expected error", "rollback", "THROW", "later units did not execute"],
                "data_checks": checks, "error_output_summary": "Expected error; rollback; THROW; later units did not execute"}
    return {"status": "passed", "exit_code": 0, "checks": ["schema", "row count", "preserved data", "excluded scope", "unit result"],
            "data_checks": checks, "error_output_summary": ""}


def test_data_fixture_covers_existing_and_preserved_rows(tmp_path):
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=_data_executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert result["status"] == "passed"
    assert result["fixture_sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert result["fixture_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert result["expected_preserved_data_summary"] == {"dbo.Customer": "Id=2, Flag=0"}
    assert all(len(row["data_checks"]) == 4 for row in result["rounds"].values())


def test_data_unit_without_expected_assertions_is_pending(tmp_path):
    artifact, baseline, fixture, _ = _data_case(tmp_path)
    calls = []
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture),
        data_units=[{"unit_id": "customer-data"}], executor=lambda **kw: calls.append(kw),
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert result["status"] == "not_run"
    assert calls == []
    assert all(row["status"] == "not_run" for row in result["rounds"].values())


def test_data_check_without_before_after_is_pending(tmp_path):
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    def incomplete_executor(**kwargs):
        raw = _data_executor(**kwargs)
        raw["data_checks"][0].pop("before")
        return raw
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=incomplete_executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert result["status"] == "not_run"
    assert all(row["status"] == "not_run" for row in result["rounds"].values())


def test_data_check_with_wrong_preserved_value_cannot_pass(tmp_path):
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    def wrong_executor(**kwargs):
        raw = _data_executor(**kwargs)
        raw["data_checks"][1]["after"] = "Id=2 Flag=1"
        return raw
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=wrong_executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert result["status"] != "passed"


def test_fixture_records_boundary_and_constraint_cases(tmp_path):
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=_data_executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert {item["case"] for item in result["expected_assertions"]} >= {"duplicate_candidate", "null_boundary"}
    assert all(row["fixture_manifest_sha256"] == result["fixture_manifest_sha256"] for row in result["rounds"].values())


def test_rerun_uses_committed_state_in_new_session(tmp_path):
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    calls = []
    def executor(**kwargs):
        calls.append(kwargs)
        return _data_executor(**kwargs)
    result = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    assert result["status"] == "passed"
    assert all(calls[i]["fresh_session"] for i in range(4))
    assert len({calls[i]["baseline_source"] for i in (0, 1, 3)}) == 3
    assert "committed-from=commit" in calls[2]["baseline_source"]
    assert all(calls[i]["fixture_manifest"] == str(manifest) for i in range(4))


def test_lifecycle_persists_fixture_evidence_immutably(tmp_path):
    lifecycle_spec = importlib.util.spec_from_file_location(
        "lifecycle_store_fixture", ROOT / "skills/release-docs/scripts/lifecycle_store.py")
    lifecycle = importlib.util.module_from_spec(lifecycle_spec)
    lifecycle_spec.loader.exec_module(lifecycle)
    artifact, baseline, fixture, manifest = _data_case(tmp_path)
    evidence = module.run_local_validation(
        artifact, server="(localdb)\\MSSQLLocalDB", database="test",
        baseline_source=str(baseline), fixture_source=str(fixture), fixture_manifest=manifest,
        data_units=[{"unit_id": "customer-data"}], executor=_data_executor,
        adapter_provenance="fixture/1", provider_version="sql/1", tool_version="tool/1")
    class Analysis:
        blocked = False
        exclusions = []
        source_scope = {}
        baseline = {}
        sources = []
        units = []
        findings = []
    run = tmp_path / ".release-docs" / "runs" / "fixture-evidence"
    lifecycle.write_lifecycle_run(run, Analysis(), localdb_validation=evidence)
    stored = json.loads((run / "localdb_validation.json").read_text(encoding="utf-8"))
    assert stored["fixture_manifest_sha256"] == evidence["fixture_manifest_sha256"]
    assert stored["expected_preserved_data_summary"] == evidence["expected_preserved_data_summary"]
    changed = {**evidence, "fixture_sha256": "tampered"}
    try:
        lifecycle.write_lifecycle_run(run, Analysis(), localdb_validation=changed)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("must reject replacement fixture evidence")

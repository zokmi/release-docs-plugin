"""Real lifecycle, SQL, operator and Git evidence boundaries for independent review."""
import ast
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).parents[1]
sys.path.insert(0, str(PLUGIN / "skills/release-docs/scripts"))
REVIEW = PLUGIN / "skills/release-docs-review/scripts"
sys.path.insert(0, str(REVIEW))


def api(name="validate_release_output"):
    assert (REVIEW / (name + ".py")).exists(), "Lifecycle review tool is missing"
    if name == "review_fingerprint":
        spec = importlib.util.spec_from_file_location("release_docs_review_fingerprint", REVIEW / "review_fingerprint.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(name)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout.decode().strip()


@pytest.fixture
def release(tmp_path):
    from analyze_release_units import analyze_release_units
    from assemble_deployment_sql import assemble_deployment_sql
    from lifecycle_store import write_lifecycle_run
    from render_release_documents import render_release_documents

    repo = tmp_path / "中文 source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    sql = "IF OBJECT_ID(N'dbo.Customer', N'U') IS NULL\nBEGIN\nCREATE TABLE dbo.Customer (Id int);\nEND;\n"
    (repo / "customer.sql").write_bytes(sql.encode("utf-8"))
    (repo / "core.sql").write_bytes(b"INSERT INTO dbo.Core VALUES (1);\n")
    (repo / ".env").write_text("PASSWORD=NEVER_READ_SECRET", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    revision = git(repo, "rev-parse", "HEAD")
    scope = {"base_sha": revision, "target_sha": revision}
    baseline = repo / "old.sql"
    baseline.write_bytes(b"CREATE TABLE dbo.Existing (Id int);\n")
    def complete_unit(unit_id, phase, source_path, objects, issues, sql):
        return {"unit_id": unit_id, "phase": phase, "complete": True,
                "source_path": source_path, "objects": objects, "issues": issues, "depends_on": [],
                "preconditions": [{"query": "SELECT 1;", "expected": 1}],
                "target_definition": {"sql": sql},
                "skip_condition": {"query": "SELECT 0;", "expected": 0},
                "stop_condition": {"query": "SELECT 0;", "expected": 0},
                "validation_queries": [{"query": "SELECT 1;", "expected": 1}]}
    evidence = {**scope, "committed_changes": [{"path": "customer.sql", "status": "A"},
                                               {"path": "core.sql", "status": "A"}],
                "execution_units": [
                    complete_unit("customer", "SCHEMA", "customer.sql", ["dbo.Customer"], [], sql),
                    complete_unit("core", "DATA", "core.sql", ["dbo.Core"], ["#5005"],
                                  "INSERT INTO dbo.Core VALUES (1);\n")]}
    analysis = analyze_release_units(repo, evidence, baseline, "#5005")
    assert not analysis.blocked
    analysis.parameters_applicable = False
    run = tmp_path / ".release-docs/runs/review-1"
    manifest = write_lifecycle_run(run, analysis)
    excluded = {uid for item in analysis.exclusions for uid in item["unit_ids"]}
    artifact = assemble_deployment_sql([u for u in analysis.units if u["unit_id"] not in excluded],
                                       run / "assembly/01_部署SQL.sql")
    output = tmp_path / "operator"
    render_release_documents(analysis, artifact, manifest, output)
    metadata = json.loads((run / "lifecycle_metadata.json").read_text())
    metadata.update({"operator_contract": {"parameters_applicable": False},
                     "execution_artifact": {"path": "assembly/01_部署SQL.sql", "sha256": artifact.sha256}})
    write_json(run / "lifecycle_metadata.json", metadata)
    return repo, output, run, scope


def findings(release):
    return api().validate_release_output(release[1], release[2])


def codes(release):
    return {item["code"] for item in findings(release)}


def status(release, code):
    return next(item["status"] for item in findings(release) if item["code"] == code)


def update_metadata(release, **fields):
    path = release[2] / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    metadata.update(fields)
    write_json(path, metadata)


def replace_sql(release, sql):
    """Keep artifact evidence current so defects exercise SQL review, not drift."""
    _, output, run, _ = release
    (output / "01_部署SQL.sql").write_bytes(sql.encode("utf-8"))
    (run / "assembly/01_部署SQL.sql").write_bytes(sql.encode("utf-8"))
    update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql",
                    "sha256": hashlib.sha256(sql.encode()).hexdigest()})


def test_valid_operator_contract_has_separate_static_and_deployment_statuses(release):
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"
    assert status(release, "deployment_validation_status") == "待確認"
    assert not any(f["blocking"] for f in findings(release))


@pytest.mark.parametrize('state', ['待確認', '未通過'])
def test_business_data_domain_cannot_block_sql_summary(state):
    module = api()
    business = module._finding('business_data_validation', blocking=True,
                               domain='business_data_validation', status=state)
    result = module._summary([business], semantic_complete=True)
    assert result[0]['blocking'] is False
    assert result[0]['status'] == '待確認'
    assert next(f['status'] for f in result if f['code'] == 'sql_content_status') == '通過'
    assert next(f['status'] for f in result if f['code'] == 'static_sql_status') == '通過'


def test_business_data_domain_normalizes_supplied_findings():
    supplied = {'code': 'business_data_validation', 'blocking': True,
                'domain': 'business_data_validation', 'status': '未通過'}
    result = api()._summary([supplied], semantic_complete=True)
    assert result[0]['blocking'] is False
    assert result[0]['status'] == '待確認'
    assert supplied['blocking'] is True


@pytest.mark.parametrize('domain', ['sql_correctness', 'sql_content', 'business_data_validation'])
def test_sql_defects_stay_in_sql_correctness_domain(domain):
    module = api()
    finding = module._finding('opaque_execution', domain=domain)
    assert finding['domain'] == 'sql_correctness'
    result = module._summary([finding], semantic_complete=True)
    assert next(f['status'] for f in result if f['code'] == 'sql_content_status') == '未通過'


def test_business_data_source_finding_does_not_lower_sql_status(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    path = release[2] / 'source_unit_metadata.json'
    source = json.loads(path.read_text())
    source['findings'].append({'code': 'formal_rows_unavailable', 'domain': 'business_data_validation',
                               'blocking': True, 'status': '未通過'})
    write_json(path, source)
    update_metadata(release, localdb_validation=report_query_evidence(release))
    record, _, _, fingerprint = record_for(release)
    record['unit_reviews'][0]['checks']['preservation']['conclusion'] = 'N/A'
    record['unresolved'] = [{'domain': 'business_data_validation', 'reason': '正式 before/after 不可取得'}]
    write_semantic_review(release[2], record)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    assert next(f['status'] for f in result if f['code'] == 'sql_content_status') == '通過'
    business = [f for f in result if f['domain'] == 'business_data_validation']
    assert business and all(f['blocking'] is False for f in business)
    assert not any(f['code'] == 'semantic_review_pending' for f in result)
    report = api().write_review_report(release[2], result, fingerprint,
                                      repo=release[0], output_dir=release[1])
    assert 'SQL 內容審核：通過' in report.read_text(encoding='utf-8')


def test_business_data_domain_cannot_hide_source_schema_conflict(release):
    path = release[2] / 'source_unit_metadata.json'
    source = json.loads(path.read_text())
    source['findings'].append({'code': 'baseline_model_conflict', 'domain': 'business_data_validation',
                               'blocking': True})
    write_json(path, source)
    result = findings(release)
    assert any(f['code'] == 'blocking_source_analysis' and f['blocking'] for f in result)
    assert next(f['status'] for f in result if f['code'] == 'sql_content_status') == '未通過'


@pytest.mark.parametrize('code', ['semantic_sql_defect', 'opaque_execution'])
def test_business_data_domain_cannot_hide_sql_defect_in_report(code):
    result = [{'code': 'sql_content_status', 'domain': 'sql_correctness', 'status': '通過'},
              {'code': code, 'domain': 'business_data_validation', 'blocking': True}]
    assert api()._report_status(result, 'sql_correctness', 'sql_content_status') == '未通過'


def test_business_data_domain_is_ignored_by_report_status():
    result = [{'code': 'sql_content_status', 'domain': 'sql_correctness', 'status': '通過'},
              {'code': 'business_data_validation', 'domain': 'business_data_validation',
               'blocking': True, 'status': '未通過'}]
    assert api()._report_status(result, 'sql_correctness', 'sql_content_status') == '通過'


def sql_contract_codes():
    """Discover the assembler's emitted codes independently of review's registry."""
    tree = ast.parse((PLUGIN / 'skills/release-docs/scripts/assemble_deployment_sql.py').read_text(encoding='utf-8'))
    codes = {node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == '_finding' and node.args
             and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    hazards = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_hazards')
    tables = [node.value for node in ast.walk(hazards) if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'checks' for target in node.targets)]
    tables.extend(node.args[0] for node in ast.walk(hazards) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == 'checks' and node.func.attr == 'extend')
    codes.update(row.elts[0].value for table in tables for row in table.elts)
    return sorted(codes)


@pytest.mark.parametrize('code', sql_contract_codes())
def test_review_fix_business_domain_protects_all_sql_contract_paths(code):
    from semantic_review import validate_semantic_review
    module = api()
    supplied = {'code': code, 'domain': 'business_data_validation', 'blocking': True}
    constructed = module._finding(**supplied)
    assert constructed['domain'] == 'sql_correctness'
    assert constructed['blocking'] is True
    summaries = module._summary([supplied], semantic_complete=True)
    assert next(f['status'] for f in summaries if f['code'] == 'sql_content_status') == '未通過'
    source_findings = module._units('', {'units': [], 'findings': [supplied]}, [], 'database_tool_minimal')
    assert any(f['code'] == 'blocking_source_analysis' and f['blocking'] for f in source_findings)
    record = {'schema_version': 1, 'evidence_fingerprint': 'a' * 64, 'method': 'read pinned sources',
              'unit_reviews': [], 'conclusion': 'passed',
              'scope_review': {'conclusion': 'passed', 'reason': 'No included units'},
              'parameter_review': {'conclusion': 'passed', 'reason': 'No parameter changes'},
              'unresolved': [{**supplied, 'reason': 'Unresolved SQL contract failure'}]}
    unresolved = validate_semantic_review(record, {'units': []}, [], 'a' * 64)
    assert any(f['code'] == 'semantic_review_pending' and f['domain'] == 'sql_correctness' for f in unresolved)
    report_findings = [{'code': 'sql_content_status', 'status': '通過'}, supplied]
    assert module._report_status(report_findings, 'sql_correctness', 'sql_content_status') == '未通過'


def test_review_fix_business_domain_cannot_hide_nonessential_set_in_report(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    record, _, _, fingerprint = record_for(release)
    write_semantic_review(release[2], record)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    result.append({'code': 'nonessential_set_statement', 'domain': 'business_data_validation', 'blocking': True})
    report = api().write_review_report(release[2], result, fingerprint,
                                      repo=release[0], output_dir=release[1])
    text = report.read_text(encoding='utf-8')
    assert 'SQL 內容審核：未通過' in text
    assert '- nonessential_set_statement' in text


def test_review_uses_database_tool_minimal_lifecycle_profile(release):
    """A minimal artifact must not be checked against the legacy wrapper contract."""
    _, output, run, _ = release
    source = (release[0] / "customer.sql").read_text(encoding="utf-8")
    metadata = json.loads((run / "source_unit_metadata.json").read_text(encoding="utf-8"))
    unit = next(item for item in metadata["units"] if item["unit_id"] == "customer")
    mapping = {key: unit[key] for key in ("unit_id", "phase", "source_path", "source_revision",
                                          "source_hash", "sql_hash", "source_line", "depends_on")}
    mapping["source_end_line"] = unit["source_line"] + len(source.splitlines()) - 1
    sql = ("-- Unified deployment: database tool owns transaction and session settings.\n\n"
           "-- PHASE: SCHEMA\n-- UNIT: " + json.dumps(mapping, sort_keys=True) + "\n" + source
           + "-- END UNIT: customer\n")
    replace_sql(release, sql)
    update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql",
                                                  "sha256": hashlib.sha256(sql.encode()).hexdigest(),
                                                  "sql_profile": "database_tool_minimal"})
    result = findings(release)
    codes_found = {item["code"] for item in result}
    assert "invalid_runtime_mode" not in codes_found
    assert "missing_try_catch" not in codes_found
    assert status(release, "static_sql_status") == "通過"


def test_review_blocks_mismatched_localdb_sql_profile(release):
    update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql",
                                                  "sha256": hashlib.sha256(
                                                      (release[1] / "01_部署SQL.sql").read_bytes()).hexdigest(),
                                                  "sql_profile": "framework"},
                    localdb_validation={"schema_version": 1, "status": "passed",
                                        "sql_profile": "database_tool_minimal"})
    assert "sql_profile_mismatch" in codes(release)


def test_minimal_review_preserves_approved_metadata_provider_execution():
    module = api()
    source = ("IF NOT EXISTS (SELECT 1 FROM sys.extended_properties)\n"
              "BEGIN\n"
              "EXEC sp_addextendedproperty 'MS_Description', N'欄位描述', "
              "'SCHEMA', 'dbo', 'TABLE', 'Customer', 'COLUMN', 'Name';\nEND\n")
    mapping = {"unit_id": "metadata", "phase": "SCHEMA", "source_path": "metadata.sql",
               "source_revision": "a", "source_hash": "b", "sql_hash": "c", "source_line": 1,
               "source_end_line": 5, "depends_on": [], "provider_kind": "metadata"}
    assert module._approved_provider_body(mapping, source)
    artifact = ("-- Unified deployment: database tool owns transaction and session settings.\n"
                "-- PHASE: SCHEMA\n-- UNIT: " + json.dumps(mapping) + "\n" + source
                + "-- END UNIT: metadata\n")
    checked = module._contract_sql(artifact, "database_tool_minimal")
    assert not any(item["code"] == "opaque_execution"
                   for item in module.validate_sql_contract(checked, profile="database_tool_minimal"))


def test_unapproved_minimal_execution_remains_opaque():
    module = api()
    source = "EXEC dbo.UnreviewedProvider;\n"
    assert not module._approved_provider_body({"provider_kind": "metadata"}, source)
    assert any(item["code"] == "opaque_execution"
               for item in module.validate_sql_contract(source, profile="database_tool_minimal"))


@pytest.mark.parametrize("provider", ["metadata", "dynamic_ddl"])
@pytest.mark.parametrize("damage", [None, "descriptor", "mapping", "hash", "rerun"])
def test_provider_review_requires_descriptor_mapping_hash_and_rerun(release, provider, damage):
    """Pinned provider SQL plus recorded runtime checks; no database execution."""
    from assemble_deployment_sql import assemble_deployment_sql
    from metadata_provider import render_dynamic_drop_constraint_provider
    from semantic_review import write_semantic_review
    from test_semantic_review import record_for

    repo, output, run, _ = release
    sql = ("IF NOT EXISTS (SELECT 1 FROM sys.extended_properties)\nBEGIN\n"
           "EXEC sys.sp_addextendedproperty N'MS_Description', N'Name', "
           "N'SCHEMA', N'dbo', N'TABLE', N'Customer', N'COLUMN', N'Name';\nEND;\n"
           if provider == "metadata" else render_dynamic_drop_constraint_provider())
    (repo / "customer.sql").write_bytes(sql.encode("utf-8"))
    git(repo, "add", "customer.sql")
    git(repo, "commit", "-qm", "pinned provider fixture")
    revision = git(repo, "rev-parse", "HEAD")
    source_path = run / "source_unit_metadata.json"
    source = json.loads(source_path.read_text())
    source["source_scope"]["target_sha"] = revision
    unit = source["units"][0]
    digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    unit.update(sql=sql, target_definition={"sql": sql}, provider_kind=provider,
                source_revision=revision, source_hash=digest, sql_hash=digest)
    unit["objects"] = ["dbo.Customer" if provider == "metadata" else "dbo.tblVenueTimetableSlots"]
    for item in source["sources"]:
        if item["source_path"] == "customer.sql":
            item.update(source_revision=revision, source_hash=digest)
    write_json(source_path, source)
    artifact = assemble_deployment_sql([unit], run / "assembly/01_部署SQL.sql",
                                      {"profile": "database_tool_minimal"})
    artifact_sql = artifact.path.read_bytes().decode("utf-8")
    replace_sql(release, artifact_sql)
    update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql",
                    "sha256": artifact.sha256, "sql_profile": "database_tool_minimal"})
    evidence, _ = _na_localdb_evidence(release)
    queries = report_query_evidence(release)
    for name, row in evidence["rounds"].items():
        row["checks"] = queries["rounds"][name]["checks"]
    if damage in ("descriptor", "mapping", "hash"):
        mapping = json.loads(next(line[9:] for line in artifact_sql.splitlines()
                                  if line.startswith("-- UNIT: ")))
        altered = dict(mapping)
        if damage == "descriptor":
            del altered["provider_kind"]
        elif damage == "mapping":
            altered["source_hash"] = "0" * 64
        else:
            altered["sql_hash"] = "0" * 64
        artifact_sql = artifact_sql.replace(json.dumps(mapping, sort_keys=True),
                                            json.dumps(altered, sort_keys=True))
        replace_sql(release, artifact_sql)
        artifact_hash = hashlib.sha256(artifact_sql.encode("utf-8")).hexdigest()
        update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql",
                        "sha256": artifact_hash, "sql_profile": "database_tool_minimal"})
        evidence["artifact_sha256"] = artifact_hash
        for row in evidence["rounds"].values():
            row["artifact_sha256"] = artifact_hash
    elif damage == "rerun":
        evidence["rounds"]["rerun"]["committed_state"] = "wrong-state"
    update_metadata(release, localdb_validation=evidence)
    current = (repo, output, run, source["source_scope"])
    record, _, _, fingerprint = record_for(current)
    record["unit_reviews"][0]["checks"]["preservation"]["conclusion"] = "N/A"
    write_semantic_review(run, record)
    result = api().validate_release_output(output, run, repo=repo)
    states = {f["code"]: f["status"] for f in result if f["code"].endswith("_status")}
    expected = "通過" if damage is None else "待確認" if damage == "rerun" else "未通過"
    assert states["sql_content_status"] == expected
    expected_code = {"descriptor": "opaque_execution", "mapping": "unit_mapping_mismatch",
                     "hash": "unit_sql_hash_mismatch", "rerun": "transaction_validation_pending"}
    if damage:
        assert expected_code[damage] in {f["code"] for f in result}
        assert any(f["blocking"] for f in result) == (damage != "rerun")
    else:
        assert states["deployment_validation_status"] == "通過"
        assert not {"opaque_execution", "rerun_risk"} & {f["code"] for f in result}
    report = api().write_review_report(run, result, fingerprint, repo=repo, output_dir=output)
    assert "SQL 內容審核：" + expected in report.read_text(encoding="utf-8")


def test_review_distinguishes_generated_execution_from_opaque_source(release):
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    assert "EXEC sys.sp_executesql N'" in sql
    assert "opaque_execution" not in codes(release)
    replace_sql(release, sql.replace("CREATE TABLE dbo.Customer", "EXEC dbo.Unknown; CREATE TABLE dbo.Customer"))
    assert "opaque_execution" in codes(release)
    assert status(release, "sql_content_status") == "未通過"


def test_review_rejects_stale_controlled_unit_content(release):
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    replace_sql(release, sql.replace("CREATE TABLE dbo.Customer", "CREATE TABLE dbo.StaleCustomer"))
    assert "unit_sql_hash_mismatch" in codes(release)


def test_review_preserves_crlf_source_bytes_when_hashing(release):
    from assemble_deployment_sql import _generated_units
    sql_path = release[1] / "01_部署SQL.sql"
    sql = sql_path.read_bytes().decode("utf-8")
    generated, errors = _generated_units(sql)
    assert not errors and len(generated) == 1
    old_source = generated[0][1]
    crlf_source = old_source.replace("\n", "\r\n")
    old_hash = hashlib.sha256(old_source.encode("utf-8")).hexdigest()
    new_hash = hashlib.sha256(crlf_source.encode("utf-8")).hexdigest()
    sql = sql.replace("EXEC sys.sp_executesql N'" + old_source.replace("'", "''") + "';",
                      "EXEC sys.sp_executesql N'" + crlf_source.replace("'", "''") + "';")
    sql = sql.replace('"sql_hash": "' + old_hash + '"', '"sql_hash": "' + new_hash + '"')
    source_path = release[2] / "source_unit_metadata.json"
    metadata = json.loads(source_path.read_text(encoding="utf-8"))
    metadata["units"][0]["sql_hash"] = new_hash
    write_json(source_path, metadata)
    replace_sql(release, sql)
    assert "unit_sql_hash_mismatch" not in codes(release)
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"


@pytest.mark.parametrize("name", ["02_資料SQL.sql", "03_例外排除.json", "04_參數異動.md",
                                    "lifecycle_exclusion_manifest.json", "source_unit_metadata.json", "unknown.txt", "nested"])
def test_undeclared_operator_files_and_directories_block_review(release, name):
    path = release[1] / name
    path.mkdir() if name == "nested" else path.write_text("PASSWORD=NEVER_EMIT_SECRET")
    assert "undeclared_output" in codes(release)
    assert status(release, "sql_content_status") == "未通過"
    assert "NEVER_EMIT_SECRET" not in json.dumps(findings(release))


@pytest.mark.parametrize("name", ["00_上線指引.md", "01_部署SQL.sql"])
def test_required_operator_documents_cannot_be_omitted(release, name):
    (release[1] / name).unlink()
    assert "missing_operator_file" in codes(release)


def test_parameter_document_follows_declared_applicability(release):
    source_path = release[2] / 'source_unit_metadata.json'
    source = json.loads(source_path.read_text())
    source['parameters_applicable'] = True
    source['parameter_changes'] = [{'environment': 'test', 'service': 'api', 'key': 'Cache:TTL'}]
    write_json(source_path, source)
    update_metadata(release, operator_contract={"parameters_applicable": True})
    assert "missing_parameter_document" in codes(release)
    (release[1] / "02_參數異動.md").write_text("設定鍵與遮罩格式")
    assert "missing_parameter_document" not in codes(release)
    source['parameters_applicable'] = False
    source['parameter_changes'] = []
    write_json(source_path, source)
    update_metadata(release, operator_contract={"parameters_applicable": False})
    assert "unexpected_parameter_document" in codes(release)


def test_missing_parameter_declaration_with_present_document_is_pending(release):
    source_path = release[2] / 'source_unit_metadata.json'
    source = json.loads(source_path.read_text())
    source.pop('parameters_applicable')
    write_json(source_path, source)
    update_metadata(release, operator_contract={})
    (release[1] / "02_參數異動.md").write_text("設定鍵與遮罩格式")
    assert "parameter_applicability_unknown" in codes(release)
    assert status(release, "sql_content_status") == "待確認"


@pytest.mark.parametrize("name", ["lifecycle_exclusion_manifest.json", "source_unit_metadata.json", "lifecycle_metadata.json"])
def test_missing_lifecycle_evidence_never_assumes_no_exclusions(release, name):
    (release[2] / name).unlink()
    assert "missing_lifecycle_evidence" in codes(release)
    assert status(release, "sql_content_status") != "通過"


@pytest.mark.parametrize("damage", ["excluded_unit", "excluded_object", "quoted_excluded_object", "missing_unit", "changed_mapping", "guide", "extra_guide"])
def test_lifecycle_sql_guide_exclusion_mismatch_blocks_review(release, damage):
    output = release[1]
    sql = (output / "01_部署SQL.sql").read_text(encoding="utf-8")
    if damage == "excluded_unit":
        sql = sql.replace('"unit_id": "customer"', '"unit_id": "core"')
    elif damage == "excluded_object":
        sql = sql.replace("CREATE TABLE dbo.Customer", "CREATE TABLE [dbo].[Core]")
    elif damage == "quoted_excluded_object":
        sql = sql.replace("CREATE TABLE dbo.Customer", 'CREATE TABLE "dbo"."Core"')
    elif damage == "missing_unit":
        sql = sql.replace("-- UNIT:", "-- LOST:")
    elif damage == "changed_mapping":
        sql = sql.replace('"source_line": 1', '"source_line": 2')
    else:
        path = output / "00_上線指引.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("#5005", "#9999") if damage == "guide" else text.replace("## 本次排除摘要", "## 本次排除摘要\n\n- 排除名稱：#9999；原因：新增範圍")
        path.write_text(text, encoding="utf-8")
    if damage not in ("guide", "extra_guide"):
        replace_sql(release, sql)
    if damage in ("excluded_object", "quoted_excluded_object"):
        assert "excluded_object_in_sql" in codes(release)
    assert any(f["blocking"] for f in findings(release))
    assert status(release, "sql_content_status") == "未通過"


@pytest.mark.parametrize("defect, expected", [("commit", "unit_transaction_control"), ("throw", "missing_throw"),
                                              ("unguarded", "rerun_risk"), ("duplicate_column", "duplicate_column"),
                                              ("partial_exclusion", "excluded_dependency")])
def test_deliberate_sql_and_dependency_defects_are_blocking(release, defect, expected):
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    if defect == "commit":
        sql = sql.replace("CREATE TABLE dbo.Customer", "COMMIT; CREATE TABLE dbo.Customer")
    elif defect == "throw":
        sql = sql.replace("THROW;", "PRINT N'failure';")
    elif defect == "unguarded":
        sql = sql.replace("IF OBJECT_ID(N''dbo.Customer'', N''U'') IS NULL", "")
    elif defect == "duplicate_column":
        sql = sql.replace("CREATE TABLE dbo.Customer (Id int);", "CREATE TABLE dbo.Customer (Id int);\nALTER TABLE dbo.Customer ADD Code int;\nALTER TABLE dbo.Customer ADD Code int;")
    else:
        path = release[2] / "source_unit_metadata.json"
        metadata = json.loads(path.read_text())
        metadata["units"][0]["depends_on"] = ["core"]
        write_json(path, metadata)
    replace_sql(release, sql)
    assert expected in codes(release)
    assert status(release, "sql_content_status") == "未通過"


def localdb_evidence(release):
    run = release[2]
    baseline = run / "baseline.sql"
    fixture = run / "fixture.sql"
    fixture_manifest = run / "fixture.json"
    baseline.write_text("CREATE TABLE dbo.Existing (Id int);\n", encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Existing VALUES (1);\n", encoding="utf-8")
    fixture_manifest.write_text('{"usage":"seed disposable database"}', encoding="utf-8")
    baseline_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    fixture_manifest_hash = hashlib.sha256(fixture_manifest.read_bytes()).hexdigest()
    artifact_hash = hashlib.sha256((release[1] / "01_部署SQL.sql").read_bytes()).hexdigest()
    evidence = {"status": "passed", "exit_code": 0, "server": "(localdb)\\release-test",
                "database": "disposable", "provider_version": "test provider", "tool_version": "test runner",
                "baseline_source": str(baseline), "baseline_sha256": baseline_hash,
                "fixture_source": str(fixture), "fixture_sha256": fixture_hash,
                "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": fixture_manifest_hash,
                "command": ["runner", "--isolated"],
                "error_output_summary": "", "checks": ["checks passed"]}
    rounds = {}
    for index, name in enumerate(("validate_only", "commit", "rerun", "injected_failure")):
        rounds[name] = {**evidence, "round": name, "artifact_sha256": artifact_hash,
                        "session_id": f"session-{index}",
                        "database_id": f"db-{index if name != 'rerun' else 1}",
                        "expected_preserved_data_summary": {"dbo.Existing": "Id=1"},
                        "preserved_data_summary": {"dbo.Existing": "Id=1"},
                        "checks": [f"{name} checks"],
                        "committed_state": "state-1" if name in ("commit", "rerun") else ""}
    rounds["injected_failure"]["error_output_summary"] = "Expected failure rollback and stop confirmed"
    return {"status": "passed", "artifact_sha256": artifact_hash,
            "fixture_source": str(fixture), "fixture_sha256": fixture_hash,
            "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": fixture_manifest_hash,
            "rounds": rounds}


def _na_localdb_evidence(release):
    evidence = localdb_evidence(release)
    source = json.loads((release[2] / "source_unit_metadata.json").read_text())
    unit = source["units"][0]
    uid = unit["unit_id"]
    preservation = {uid: {"conclusion": "N/A", "reason":
                         f"{unit['source_path']}:{unit['source_line']}: no existing row mutation"}}
    evidence.update(data_impact={uid: "non_mutating"}, preservation=preservation)
    for row in evidence["rounds"].values():
        row.update(expected_preserved_data_summary={uid: "N/A"}, preservation=preservation)
        row.pop("preserved_data_summary")
    return evidence, source


@pytest.mark.parametrize("phase", ["SCHEMA", "DATA"])
def test_localdb_non_mutating_preservation_na_needs_no_formal_rows(release, phase):
    evidence, source = _na_localdb_evidence(release)
    source["units"][0]["phase"] = phase
    assert api()._deployment({"localdb_validation": evidence}, evidence["artifact_sha256"],
                             source, run=release[2]) == "通過"
    assert api()._data_expectations(source, ()) == ({}, True)
    if phase == "SCHEMA":
        update_metadata(release, localdb_validation=evidence)
        assert status(release, "deployment_validation_status") == "通過"
        assert "missing_data_expectations" not in codes(release)
        assert status(release, "static_sql_status") == "通過"


def test_localdb_preservation_na_runner_and_review_use_mapped_artifact_units(release):
    from run_local_validation import run_local_validation
    from test_local_validation import _non_mutating_executor
    evidence, source = _na_localdb_evidence(release)
    manifest = Path(evidence["fixture_manifest"])
    write_json(manifest, {"expected_preserved_data_summary": {"customer": "N/A"},
                          "preservation": evidence["preservation"]})
    result = run_local_validation(
        release[2] / "assembly/01_部署SQL.sql", server="(localdb)\\release-test", database="test",
        baseline_source=evidence["rounds"]["commit"]["baseline_source"],
        fixture_source=evidence["fixture_source"], fixture_manifest=manifest,
        executor=_non_mutating_executor, adapter_provenance="fixture/1",
        provider_version="sql/1", tool_version="tool/1", command=["runner", "--isolated"])
    assert result["status"] == "passed"
    assert result["data_impact"] == {"customer": "non_mutating"}
    update_metadata(release, localdb_validation=result)
    assert status(release, "deployment_validation_status") == "通過"


def test_localdb_mixed_preservation_cannot_skip_schema_phase_mutation(release):
    evidence = localdb_evidence(release)
    source = json.loads((release[2] / "source_unit_metadata.json").read_text())
    mutation = {**source["units"][0], "unit_id": "backfill", "phase": "SCHEMA",
                "sql": "UPDATE dbo.Customer SET Id=2 WHERE Id=1;", "data_impact": "non_mutating"}
    source["units"].append(mutation)
    assert api()._deployment({"localdb_validation": evidence}, evidence["artifact_sha256"],
                             source, run=release[2]) == "待確認"


@pytest.mark.parametrize("damage", ["unknown", "mutation", "blank_reason", "wrong_source", "missing_na",
                                    "same_session", "same_database", "rerun_database", "rerun_state",
                                    "duplicate_checks", "wrong_hash", "error_output", "provider"])
def test_localdb_preservation_na_retains_round_and_identity_gates(release, damage):
    evidence, source = _na_localdb_evidence(release)
    row = evidence["rounds"]["commit"]
    if damage in ("unknown", "mutation"):
        source["units"][0]["sql"] = "EXEC dbo.Custom;" if damage == "unknown" else "UPDATE dbo.Customer SET Id=2;"
    elif damage == "blank_reason":
        row["preservation"]["customer"]["reason"] = " "
    elif damage == "wrong_source":
        row["preservation"]["customer"]["reason"] = "other.sql:1: no existing row mutation"
    elif damage == "missing_na":
        row.pop("expected_preserved_data_summary")
    elif damage == "same_session":
        evidence["rounds"]["rerun"]["session_id"] = row["session_id"]
    elif damage == "same_database":
        evidence["rounds"]["injected_failure"]["database_id"] = row["database_id"]
    elif damage == "rerun_database":
        evidence["rounds"]["rerun"]["database_id"] = "different-db"
    elif damage == "rerun_state":
        evidence["rounds"]["rerun"]["committed_state"] = "different-state"
    elif damage == "duplicate_checks":
        evidence["rounds"]["rerun"]["checks"] = row["checks"]
    elif damage == "wrong_hash":
        row["artifact_sha256"] = "0" * 64
    elif damage == "error_output":
        evidence["rounds"]["injected_failure"]["error_output_summary"] = ""
    else:
        row["provider_version"] = "unknown"
    assert api()._deployment({"localdb_validation": evidence}, evidence["artifact_sha256"],
                             source, run=release[2]) == "待確認"


@pytest.mark.parametrize("damage", ["missing_fixture_hash", "changed_fixture", "changed_baseline", "wrong_round_hash"])
def test_deployment_pass_requires_current_fixture_and_baseline_hashes(release, damage):
    evidence = localdb_evidence(release)
    if damage == "missing_fixture_hash":
        del evidence["fixture_sha256"]
    elif damage == "changed_fixture":
        Path(evidence["fixture_source"]).write_text("INSERT INTO dbo.Existing VALUES (2);\n")
    elif damage == "changed_baseline":
        Path(evidence["rounds"]["commit"]["baseline_source"]).write_text("SELECT 2;\n")
    else:
        evidence["rounds"]["commit"]["fixture_sha256"] = "0" * 64
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == "待確認"
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"


@pytest.mark.parametrize("damage", ["missing_manifest", "missing_manifest_hash", "changed_manifest",
                                    "round_missing_manifest", "round_missing_manifest_hash",
                                    "round_wrong_manifest_hash", "external_manifest"])
def test_deployment_pass_requires_current_lifecycle_fixture_manifest(release, tmp_path, damage):
    evidence = localdb_evidence(release)
    if damage == "missing_manifest":
        del evidence["fixture_manifest"]
    elif damage == "missing_manifest_hash":
        del evidence["fixture_manifest_sha256"]
    elif damage == "changed_manifest":
        Path(evidence["fixture_manifest"]).write_text('{"usage":"changed"}', encoding="utf-8")
    elif damage == "round_missing_manifest":
        del evidence["rounds"]["commit"]["fixture_manifest"]
    elif damage == "round_missing_manifest_hash":
        del evidence["rounds"]["commit"]["fixture_manifest_sha256"]
    elif damage == "round_wrong_manifest_hash":
        evidence["rounds"]["commit"]["fixture_manifest_sha256"] = "0" * 64
    else:
        external = tmp_path / "external.json"
        external.write_bytes(Path(evidence["fixture_manifest"]).read_bytes())
        evidence["fixture_manifest"] = str(external)
        for row in evidence["rounds"].values():
            row["fixture_manifest"] = str(external)
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == "待確認"


def test_fingerprint_changes_when_fixture_or_localdb_evidence_changes(release):
    evidence = localdb_evidence(release)
    update_metadata(release, localdb_validation=evidence)
    module = api("review_fingerprint")
    first = module.review_fingerprint(*release)
    Path(evidence["fixture_source"]).write_text("INSERT INTO dbo.Existing VALUES (2);\n")
    assert first.sha256 != module.review_fingerprint(*release).sha256
    second = module.review_fingerprint(*release)
    write_json(release[2] / "localdb_validation.json", {"schema_version": 1, **evidence})
    assert second.sha256 != module.review_fingerprint(*release).sha256


def test_data_unit_deployment_pass_requires_fixture_data_checks(release):
    evidence = localdb_evidence(release)
    source_path = release[2] / "source_unit_metadata.json"
    source = json.loads(source_path.read_text())
    source["units"][0]["phase"] = "DATA"
    source["units"][0]["sql"] = "UPDATE dbo.Customer SET Id=2 WHERE Id=1;"
    write_json(source_path, source)
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == "待確認"
    assert "missing_data_expectations" in codes(release)
    assert status(release, "sql_content_status") == "未通過"


def test_data_expectation_missing_before_or_after_blocks_sql_content(release):
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["units"][0]["phase"] = "DATA"
    source["units"][0]["sql"] = "UPDATE dbo.Customer SET Id=2 WHERE Id=1;"
    source["units"][0]["expected_assertions"] = [{"id": "changed", "before": "1"}]
    write_json(path, source)
    assert "missing_data_expectations" in codes(release)
    assert status(release, "sql_content_status") == "未通過"


def test_duplicate_data_expectation_ids_block_sql_content(release):
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["units"][0]["phase"] = "DATA"
    source["units"][0]["sql"] = "UPDATE dbo.Customer SET Id=2 WHERE Id=1;"
    assertion = {"id": "same", "seed_row_id": "Customer/1", "expected_by_round":
                 {name: {"before": "0", "after": "1"} for name in ("validate_only", "commit", "rerun", "injected_failure")}}
    source["units"][0]["expected_assertions"] = [assertion, dict(assertion)]
    write_json(path, source)
    assert "missing_data_expectations" in codes(release)


def test_complete_data_expectations_and_round_observations_can_validate_deployment(release):
    evidence = localdb_evidence(release)
    per_round = {name: {"before": "0", "after": "1"} for name in evidence["rounds"]}
    source_assertion = {"id": "changed", "seed_row_id": "Customer/1", "expected_by_round": per_round}
    source_path = release[2] / "source_unit_metadata.json"
    source = json.loads(source_path.read_text())
    source["units"][0]["phase"] = "DATA"
    source["units"][0]["sql"] = "UPDATE dbo.Customer SET Id=2 WHERE Id=1;"
    source["units"][0]["expected_assertions"] = [source_assertion]
    write_json(source_path, source)
    evidence["expected_assertions"] = [{"unit_id": "customer", **source_assertion}]
    for row in evidence["rounds"].values():
        row["data_checks"] = [{"unit_id": "customer", "id": "changed", "seed_row_id": "Customer/1",
                               "passed": True, "before": "0", "after": "1"}]
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == "通過"


@pytest.mark.parametrize("damage", ["wrong_observation", "wrong_round_hash", "same_session", "same_database", "missing_preserved", "wrong_preserved", "duplicate_checks"])
def test_deployment_rounds_need_matching_observations_and_distinct_evidence(release, damage):
    evidence = localdb_evidence(release)
    artifact_hash = evidence["artifact_sha256"]
    for index, name in enumerate(("validate_only", "commit", "rerun", "injected_failure")):
        row = evidence["rounds"][name]
        row.update(artifact_sha256=artifact_hash, database_id=f"db-{index if name != 'rerun' else 1}",
                   session_id=f"session-{index}", round=name,
                   expected_preserved_data_summary={"dbo.Customer": "unchanged"},
                   checks=[f"{name} checked"])
    evidence["rounds"]["commit"]["committed_state"] = "committed-1"
    evidence["rounds"]["rerun"]["committed_state"] = "committed-1"
    if damage == "wrong_observation":
        evidence["expected_assertions"] = [{"unit_id": "customer", "id": "changed", "seed_row_id": "Customer/1", "expected_by_round":
                                            {name: {"before": "0", "after": "1"} for name in evidence["rounds"]}}]
        for row in evidence["rounds"].values():
            row["data_checks"] = [{"unit_id": "customer", "id": "changed", "seed_row_id": "Customer/1", "passed": True, "before": "0", "after": "2"}]
        source_path = release[2] / "source_unit_metadata.json"
        source = json.loads(source_path.read_text())
        source["units"][0]["phase"] = "DATA"
        source["units"][0]["sql"] = "UPDATE dbo.Customer SET Id=2 WHERE Id=1;"
        source["units"][0]["expected_assertions"] = evidence["expected_assertions"]
        write_json(source_path, source)
    elif damage == "wrong_round_hash":
        evidence["rounds"]["commit"]["artifact_sha256"] = "0" * 64
    elif damage == "same_session":
        evidence["rounds"]["rerun"]["session_id"] = "session-1"
    elif damage == "same_database":
        evidence["rounds"]["injected_failure"]["database_id"] = "db-1"
    elif damage == "missing_preserved":
        del evidence["rounds"]["commit"]["expected_preserved_data_summary"]
    elif damage == "wrong_preserved":
        evidence["rounds"]["commit"]["preserved_data_summary"] = {"dbo.Existing": "Id=2"}
    else:
        evidence["rounds"]["commit"]["checks"] = ["validate_only checked"]
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == "待確認"


def test_stale_failed_localdb_evidence_cannot_poison_current_sql(release):
    update_metadata(release, localdb_validation={"status": "failed", "sql_defect": True,
                                                  "artifact_sha256": "0" * 64})
    assert status(release, "deployment_validation_status") == "待確認"
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"
    assert "deployment_proved_sql_defect" not in codes(release)


def test_fingerprint_rejects_external_fixture_and_mismatched_scope(release, tmp_path):
    module = api("review_fingerprint")
    outside = tmp_path / "external.sql"
    outside.write_text("PASSWORD=DO_NOT_READ", encoding="utf-8")
    evidence = localdb_evidence(release)
    evidence["fixture_source"] = str(outside)
    update_metadata(release, localdb_validation=evidence)
    with pytest.raises(ValueError, match="validation evidence path"):
        module.review_fingerprint(*release)
    assert "DO_NOT_READ" not in repr(module)
    del evidence["fixture_source"]
    update_metadata(release, localdb_validation=evidence)
    with pytest.raises(ValueError, match="Source scope"):
        module.review_fingerprint(release[0], release[1], release[2],
                                  {**release[3], "target_sha": "0" * 40})
    with pytest.raises(ValueError, match="Source scope"):
        module.review_fingerprint(release[0], release[1], release[2],
                                  {**release[3], "diff_mode": "direct"})


def test_fingerprint_rejects_external_execution_and_baseline_files(release, tmp_path):
    module = api("review_fingerprint")
    outside = tmp_path / "01_部署SQL.sql"
    outside.write_text("PASSWORD=DO_NOT_READ", encoding="utf-8")
    update_metadata(release, execution_artifact={"path": str(outside), "sha256": "0" * 64})
    with pytest.raises(ValueError, match="Execution artifact"):
        module.review_fingerprint(*release)
    update_metadata(release, execution_artifact={"path": "assembly/01_部署SQL.sql", "sha256": "0" * 64})
    source_path = release[2] / "source_unit_metadata.json"
    source = json.loads(source_path.read_text())
    source["baseline"]["source_path"] = str(outside)
    write_json(source_path, source)
    with pytest.raises(ValueError, match="Baseline"):
        module.review_fingerprint(*release)


@pytest.mark.parametrize("damage", [None, "missing_round", "missing_field", "wrong_hash", "bad_exit", "error_summary", "empty_checks"])
def test_deployment_pass_requires_structured_current_artifact_evidence(release, damage):
    evidence = localdb_evidence(release)
    if damage == "missing_round":
        del evidence["rounds"]["rerun"]
    elif damage == "missing_field":
        del evidence["rounds"]["commit"]["provider_version"]
    elif damage == "wrong_hash":
        evidence["artifact_sha256"] = "0" * 64
    elif damage == "bad_exit":
        evidence["rounds"]["commit"]["exit_code"] = 2
    elif damage == "error_summary":
        evidence["rounds"]["injected_failure"]["error_output_summary"] = ""
    elif damage == "empty_checks":
        evidence["rounds"]["validate_only"]["checks"] = []
    update_metadata(release, localdb_validation=evidence)
    assert status(release, "deployment_validation_status") == ("通過" if damage is None else "待確認")
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"


def test_guide_claiming_localdb_pass_without_evidence_is_rejected(release):
    path = release[1] / "00_上線指引.md"
    path.write_text(path.read_text(encoding="utf-8").replace("LocalDB：未執行", "LocalDB：通過"), encoding="utf-8")
    assert "unsupported_deployment_pass_claim" in codes(release)
    assert status(release, "deployment_validation_status") == "待確認"


def test_deployment_failure_does_not_prove_sql_defect_without_evidence(release):
    digest = hashlib.sha256((release[1] / "01_部署SQL.sql").read_bytes()).hexdigest()
    update_metadata(release, localdb_validation={"status": "failed", "sql_defect": False, "artifact_sha256": digest})
    assert status(release, "deployment_validation_status") == "未通過"
    assert status(release, "static_sql_status") == "通過"
    assert status(release, "sql_content_status") == "待確認"
    update_metadata(release, localdb_validation={"status": "failed", "sql_defect": True, "artifact_sha256": digest})
    assert status(release, "sql_content_status") == "未通過"


@pytest.mark.parametrize("surface", ["guide", "sql", "parameters", "manifest", "source", "source_revision", "execution", "metadata"])
def test_fingerprint_changes_for_every_covered_source_or_output(release, surface):
    module = api("review_fingerprint")
    repo, output, run, scope = release
    original = module.review_fingerprint(repo, output, run, scope)
    assert original.sha256 == module.review_fingerprint(repo, output, run, scope).sha256
    paths = {"guide": output / "00_上線指引.md", "sql": output / "01_部署SQL.sql",
             "manifest": run / "lifecycle_exclusion_manifest.json", "source": repo / "customer.sql",
             "execution": run / "assembly/01_部署SQL.sql", "metadata": run / "source_unit_metadata.json"}
    if surface == "parameters":
        (output / "02_參數異動.md").write_text("遮罩參數")
    elif surface == "source_revision":
        (repo / "customer.sql").write_text("SELECT 2;")
        git(repo, "add", "customer.sql")
        git(repo, "commit", "-qm", "source change")
        scope = {**scope, "target_sha": git(repo, "rev-parse", "HEAD")}
        with pytest.raises(ValueError, match="Source scope"):
            module.review_fingerprint(repo, output, run, scope)
        source_path = run / "source_unit_metadata.json"
        source = json.loads(source_path.read_text())
        source["source_scope"] = scope
        write_json(source_path, source)
    else:
        with paths[surface].open("ab") as stream:
            stream.write(b"\n ")
    changed = module.review_fingerprint(repo, output, run, scope)
    assert original.sha256 != changed.sha256
    assert "NEVER_READ_SECRET" not in repr(changed)


def test_fingerprint_ignores_unrelated_secret_worktree_values(release):
    module = api("review_fingerprint")
    first = module.review_fingerprint(*release)
    (release[0] / ".env").write_text("PASSWORD=OTHER_SECRET")
    second = module.review_fingerprint(*release)
    assert first.sha256 == second.sha256
    assert "OTHER_SECRET" not in repr(second)


def test_execution_drift_is_detected_independently_from_sql_contract(release):
    with (release[1] / "01_部署SQL.sql").open("ab") as stream:
        stream.write(b"\n-- drift")
    assert "execution_artifact_mismatch" in codes(release)


@pytest.mark.parametrize("surface", ["output", "lifecycle"])
def test_linked_review_files_do_not_read_external_contents(release, tmp_path, surface):
    target = tmp_path / "external"
    target.write_text("TOKEN=NEVER_EMIT_SECRET")
    path = release[1] / "00_上線指引.md" if surface == "output" else release[2] / "lifecycle_exclusion_manifest.json"
    path.unlink()
    try:
        os.link(target, path)
    except OSError as error:
        pytest.skip("Sandbox cannot create hardlinks: " + str(error.winerror))
    assert "unsafe_review_path" in codes(release)
    with pytest.raises(ValueError, match="[Ll]ink|[Hh]ard"):
        api("review_fingerprint").review_fingerprint(*release)


def test_review_report_stays_inside_lifecycle_and_omits_untrusted_values(release):
    module = api()
    record = api("review_fingerprint").review_fingerprint(*release)
    report = module.write_review_report(release[2], findings(release), record)
    assert report.parent == release[2]
    text = report.read_text(encoding="utf-8")
    assert "SQL 內容審核：待確認" in text
    assert "部署驗證：待確認" in text
    assert record.sha256 in text
    assert {p.name for p in release[1].iterdir()} == {"00_上線指引.md", "01_部署SQL.sql"}
    untrusted = [{"code": "TOKEN=NEVER_EMIT_SECRET", "blocking": True, "status": "未通過"}]
    module.write_review_report(release[2], untrusted, record)
    assert "NEVER_EMIT_SECRET" not in report.read_text(encoding="utf-8")


@pytest.mark.parametrize("damage", ["malformed_unit", "invalid_dependency", "wrong_phase", "false_guard", "altered_context"])
def test_review_rejects_unproven_unit_scope_and_guards(release, damage):
    path = release[2] / "source_unit_metadata.json"
    evidence = json.loads(path.read_text())
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    if damage == "malformed_unit":
        evidence["units"][0]["depends_on"] = [None]
        write_json(path, evidence)
    elif damage == "invalid_dependency":
        evidence["units"][0]["complete"] = False
        write_json(path, evidence)
    elif damage == "wrong_phase":
        block = sql[sql.index("-- UNIT:"):sql.index("-- END UNIT: customer") + len("-- END UNIT: customer")]
        sql = sql.replace(block, "").replace("-- PHASE: VALIDATION", block + "\n-- PHASE: VALIDATION")
        replace_sql(release, sql)
    elif damage == "false_guard":
        sql = sql.replace("IF OBJECT_ID(N''dbo.Customer'', N''U'') IS NULL", "IF 1=1")
        source_sql = (release[0] / "customer.sql").read_text(encoding="utf-8").replace("IF OBJECT_ID(N'dbo.Customer', N'U') IS NULL", "IF 1=1")
        old_hash = evidence["units"][0]["sql_hash"]
        new_hash = hashlib.sha256(source_sql.encode()).hexdigest()
        evidence["units"][0]["sql_hash"] = new_hash
        write_json(path, evidence)
        sql = sql.replace(old_hash, new_hash)
        replace_sql(release, sql)
    else:
        sql = sql.replace("SET @UnitId = N'customer';", "SET @UnitId = N'other';")
        replace_sql(release, sql)
    result = findings(release)
    expected = {"malformed_unit": "invalid_unit_evidence", "invalid_dependency": "invalid_unit_evidence",
                "wrong_phase": "unit_phase_mismatch", "false_guard": "rerun_risk", "altered_context": "unit_context_mismatch"}
    assert expected[damage] in {f["code"] for f in result}
    assert any(f["blocking"] for f in result)
    assert status(release, "sql_content_status") == "未通過"


def test_fingerprint_covers_old_schema_source_changes(release):
    module = api("review_fingerprint")
    baseline = release[0] / "old.sql"
    baseline.write_text("CREATE TABLE dbo.Old (Id int);", encoding="utf-8")
    path = release[2] / "source_unit_metadata.json"
    evidence = json.loads(path.read_text())
    evidence["baseline"] = {"source_path": str(baseline), "source_hash": hashlib.sha256(baseline.read_bytes()).hexdigest()}
    write_json(path, evidence)
    first = module.review_fingerprint(*release)
    baseline.write_text("CREATE TABLE dbo.Old (Id bigint);", encoding="utf-8")
    assert first.sha256 != module.review_fingerprint(*release).sha256


@pytest.mark.parametrize("name", ["lifecycle_exclusion_manifest.json", "source_unit_metadata.json", "lifecycle_metadata.json"])
def test_invalid_json_is_pending_without_dumping_raw_secret(release, name):
    (release[2] / name).write_text("PASSWORD=RAW_SECRET", encoding="utf-8")
    result = findings(release)
    assert next(f["status"] for f in result if f["code"] == "sql_content_status") == "待確認"
    assert "RAW_SECRET" not in repr(result)


def test_fingerprint_rejects_source_path_escape_without_reading_target(release):
    path = release[2] / "source_unit_metadata.json"
    evidence = json.loads(path.read_text())
    evidence["sources"][0]["source_path"] = "../external.sql"
    write_json(path, evidence)
    with pytest.raises(ValueError, match="source path"):
        api("review_fingerprint").review_fingerprint(*release)


def test_source_and_parameter_applicability_conflict_is_blocking(release):
    path = release[2] / "source_unit_metadata.json"
    evidence = json.loads(path.read_text())
    evidence["parameter_changes"] = [{"key": "Cache:TTL"}]
    write_json(path, evidence)
    assert "conflicting_parameter_applicability" in codes(release)


def test_review_report_does_not_invalidate_its_own_fingerprint(release):
    module = api("review_fingerprint")
    first = module.review_fingerprint(*release)
    api().write_review_report(release[2], findings(release), first)
    assert first.sha256 == module.review_fingerprint(*release).sha256


def test_report_does_not_echo_a_secret_disguised_as_a_finding_code(release):
    module = api()
    fingerprint = api("review_fingerprint").review_fingerprint(*release)
    report = module.write_review_report(release[2], [{"code": "password_is_supersecret", "status": "未通過", "blocking": True}], fingerprint)
    assert "password_is_supersecret" not in report.read_text(encoding="utf-8")


def test_empty_excluded_unit_scope_cannot_pass(release):
    path = release[2] / "lifecycle_exclusion_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["exclusions"][0]["unit_ids"] = []
    write_json(path, manifest)
    assert "invalid_lifecycle_exclusions" in codes(release)


def test_sql_outside_declared_units_is_rejected_even_when_artifact_hash_matches(release):
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    sql = sql.replace("-- PHASE: DATA", "DELETE FROM dbo.Other;\n-- PHASE: DATA")
    replace_sql(release, sql)
    assert "execution_artifact_mismatch" not in codes(release)
    assert "unmapped_sql" in codes(release)


def test_malformed_unit_mapping_returns_finding_instead_of_crashing(release):
    sql = (release[1] / "01_部署SQL.sql").read_text(encoding="utf-8")
    sql = sql.replace('"depends_on": []', '"depends_on": [[]]')
    replace_sql(release, sql)
    assert "invalid_unit_mapping" in codes(release)


@pytest.mark.parametrize("code, blocking, expected", [
    ("semantic_sql_defect", True, "未通過"),
    ("semantic_sql_defect", False, "未通過"),
    ("semantic_review_pending", False, "待確認"),
    ("duplicate_column", True, "未通過"),
])
def test_report_merges_sql_findings_instead_of_preserving_a_stale_pass(release, code, blocking, expected):
    module = api()
    merged = findings(release) + [{"code": code, "blocking": blocking, "domain": "sql_content"}]
    report = module.write_review_report(release[2], merged, api("review_fingerprint").review_fingerprint(*release))
    text = report.read_text(encoding="utf-8")
    assert "SQL 內容審核：" + expected in text
    assert "SQL 內容審核：通過" not in text
    assert "部署驗證：待確認" in text


def test_report_preserves_worst_summary_when_later_summary_claims_pass(release):
    merged = findings(release) + [{"code": "sql_content_status", "status": "未通過", "domain": "sql_content", "blocking": True},
                                 {"code": "sql_content_status", "status": "通過", "domain": "sql_content", "blocking": False}]
    report = api().write_review_report(release[2], merged, api("review_fingerprint").review_fingerprint(*release))
    assert "SQL 內容審核：未通過" in report.read_text(encoding="utf-8")


def test_report_merging_sql_defect_preserves_successful_deployment_evidence(release):
    update_metadata(release, localdb_validation=localdb_evidence(release))
    merged = findings(release) + [{"code": "semantic_sql_defect", "blocking": True, "domain": "sql_content"}]
    report = api().write_review_report(release[2], merged, api("review_fingerprint").review_fingerprint(*release))
    text = report.read_text(encoding="utf-8")
    assert "SQL 內容審核：未通過" in text
    assert "部署驗證：通過" in text


def report_text(release, extra=()):
    fingerprint = api("review_fingerprint").review_fingerprint(*release)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    return api().write_review_report(release[2], result + list(extra), fingerprint,
                                     repo=release[0], output_dir=release[1]).read_text(encoding="utf-8")


def report_query_evidence(release):
    evidence = localdb_evidence(release)
    source = json.loads((release[2] / "source_unit_metadata.json").read_text())
    unit = source["units"][0]
    query = unit["validation_queries"][0]
    result = {key: unit[key] for key in ("unit_id", "source_path", "source_revision", "source_hash")}
    result.update(query_sha256=hashlib.sha256(query["query"].encode()).hexdigest(),
                  expected=query["expected"], actual=query["expected"], passed=True)
    for name, row in evidence["rounds"].items():
        row["checks"] = {"transaction": name + " checked", "validation_queries": [dict(result)]}
    return evidence


def test_report_has_six_evidence_sections_and_domain_separated_findings(release):
    text = report_text(release, [
        {"code": "business_data_validation", "domain": "business_data_validation", "blocking": True,
         "status": "未通過", "reason": "SECRET_FORMAL_ROW"},
        {"code": "opaque_execution", "domain": "business_data_validation", "blocking": True},
    ])
    for heading in ("SQL 正確性驗證結果", "validation SQL 執行結果", "LocalDB 四輪交易結果",
                    "正式 schema 對照結果", "#5005 排除結果", "非阻塞性的正式資料／業務資料驗證限制"):
        assert "## " + heading in text
    assert "- opaque_execution [sql_correctness；未通過；阻塞]" in text
    assert "- business_data_validation [business_data_validation；待確認；非阻塞]" in text
    assert "SECRET_FORMAL_ROW" not in text
    assert "SQL 內容審核：未通過" in text


@pytest.mark.parametrize("damage, expected", [
    (None, "通過"), ("missing", "待確認"), ("static_only", "待確認"),
    ("wrong_query", "待確認"), ("wrong_source", "待確認"), ("duplicate", "待確認"),
    ("wrong_expected", "待確認"), ("wrong_actual", "未通過"), ("false_passed", "未通過"),
    ("wrong_artifact", "待確認"), ("missing_round", "待確認"),
    ("injected_queries_not_run", "通過"),
])
def test_report_validation_sql_maps_only_current_executed_results(release, damage, expected):
    evidence = report_query_evidence(release)
    row = evidence["rounds"]["commit"]
    result = row["checks"]["validation_queries"][0]
    if damage == "missing":
        del row["checks"]["validation_queries"]
    elif damage == "static_only":
        row["checks"] = ["validation SQL passed"]
    elif damage == "wrong_query":
        result["query_sha256"] = "0" * 64
    elif damage == "wrong_source":
        result["source_hash"] = "0" * 64
    elif damage == "duplicate":
        row["checks"]["validation_queries"].append(dict(result))
    elif damage == "wrong_expected":
        result["expected"] = 2
    elif damage == "wrong_actual":
        result["actual"] = 2
    elif damage == "false_passed":
        result["passed"] = False
    elif damage == "wrong_artifact":
        evidence["artifact_sha256"] = "0" * 64
    elif damage == "missing_round":
        del evidence["rounds"]["rerun"]
    elif damage == "injected_queries_not_run":
        del evidence["rounds"]["injected_failure"]["checks"]["validation_queries"]
    update_metadata(release, localdb_validation=evidence)
    text = report_text(release)
    assert "validation SQL 執行：" + expected in text
    assert "SELECT 1" not in text
    assert "session-" not in text and "db-1" not in text


def test_report_business_limitations_preserve_sql_and_localdb_success(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    update_metadata(release, localdb_validation=report_query_evidence(release))
    record, _, _, _ = record_for(release)
    record["unresolved"] = [{"domain": "business_data_validation", "reason": "SECRET_PRODUCTION_VALUES"}]
    write_semantic_review(release[2], record)
    text = report_text(release)
    assert "SQL 內容審核：通過" in text
    assert "部署驗證：通過" in text
    assert "validation SQL 執行：通過" in text
    assert "business_data_validation；待確認；非阻塞" in text
    assert "- semantic_review_pending" not in text and "SECRET_PRODUCTION_VALUES" not in text
    for name in ("validate_only", "commit", "rerun", "injected_failure"):
        assert "- " + name + "：通過" in text


def test_report_schema_and_5005_findings_are_not_hidden_by_business_domain(release):
    text = report_text(release, [
        {"code": "baseline_model_conflict", "domain": "business_data_validation", "blocking": True},
        {"code": "excluded_object_in_sql", "domain": "business_data_validation", "blocking": True},
    ])
    assert "schema／來源定義審查：未通過" in text
    assert "#5005 排除審查：未通過" in text
    assert "- baseline_model_conflict [sql_correctness；未通過；阻塞]" in text


def test_report_validation_assertions_show_results_without_raw_values(release):
    evidence = report_query_evidence(release)
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    assertion = {"id": "SECRET_ASSERTION_ID", "seed_row_id": "SECRET_ROW_ID",
                 "expected_by_round": {name: {"before": "SECRET_BEFORE", "after": "SECRET_AFTER"}
                                       for name in evidence["rounds"]}}
    source["units"][0]["expected_assertions"] = [assertion]
    write_json(path, source)
    evidence["expected_assertions"] = [{"unit_id": "customer", **assertion}]
    for row in evidence["rounds"].values():
        row["data_checks"] = [{"unit_id": "customer", "id": assertion["id"],
                               "seed_row_id": assertion["seed_row_id"], "passed": True,
                               "before": "SECRET_BEFORE", "after": "SECRET_AFTER"}]
    update_metadata(release, localdb_validation=evidence)
    text = report_text(release)
    assert "fixture assertion 查核：通過" in text
    assert "SECRET_" not in text


@pytest.mark.parametrize("assertions", [None, [None], [{"id": "unsafe", "expected_by_round": None}]])
def test_report_malformed_non_mutating_assertions_remain_pending(release, assertions):
    evidence = report_query_evidence(release)
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["units"][0]["expected_assertions"] = assertions
    write_json(path, source)
    update_metadata(release, localdb_validation=evidence)
    assert "fixture assertion 查核：待確認" in report_text(release)


def test_report_overall_localdb_failure_does_not_fabricate_four_failed_rounds(release):
    evidence = report_query_evidence(release)
    evidence["status"] = "failed"
    update_metadata(release, localdb_validation=evidence)
    text = report_text(release)
    assert "部署驗證：未通過" in text
    assert "- validate_only：未通過" not in text
    assert "- commit：未通過" not in text


def test_report_semantic_sql_failure_keeps_independent_current_localdb_results(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    update_metadata(release, localdb_validation=report_query_evidence(release))
    record, _, _, _ = record_for(release)
    record["unit_reviews"][0]["checks"]["definition"]["conclusion"] = "failed"
    write_semantic_review(release[2], record)
    text = report_text(release)
    assert "SQL 內容審核：未通過" in text
    assert "部署驗證：通過" in text
    assert "- commit：通過" in text


def test_report_query_defect_lowers_only_sql_correctness(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    evidence = report_query_evidence(release)
    evidence["rounds"]["commit"]["checks"]["validation_queries"][0]["actual"] = 2
    update_metadata(release, localdb_validation=evidence)
    record, _, _, _ = record_for(release)
    write_semantic_review(release[2], record)
    text = report_text(release)
    assert "SQL 內容審核：未通過" in text
    assert "部署驗證：通過" in text
    assert "validation_sql_defect [sql_correctness；未通過；阻塞]" in text


def test_report_malformed_finding_identity_is_safe_and_non_executable(release):
    text = report_text(release, [{"code": ["SECRET_MALFORMED"], "domain": ["SECRET_DOMAIN"],
                                 "blocking": True, "status": "SECRET_STATUS"}])
    assert "SECRET_" not in text
    assert "invalid_finding [sql_correctness；待確認；阻塞]" in text


def complete_report_review(release):
    from test_semantic_review import record_for
    from semantic_review import write_semantic_review
    record, _, _, fingerprint = record_for(release)
    record["unresolved"] = [{"domain": "business_data_validation", "reason": "SECRET_FORMAL_ROWS_UNAVAILABLE"}]
    write_semantic_review(release[2], record)
    return fingerprint


def assert_runtime_review(release, sql_status, query_status, deployment_status):
    fingerprint = complete_report_review(release)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    assert next(f["status"] for f in result if f["code"] == "sql_content_status") == sql_status
    assert next(f["status"] for f in result if f["code"] == "deployment_validation_status") == deployment_status
    assert next(f["status"] for f in result if f["code"] == "static_sql_status") == "通過"
    assert not any(f["code"] == "semantic_review_pending" for f in result)
    business = [f for f in result if f["domain"] == "business_data_validation"]
    assert business and all(not f["blocking"] for f in business)
    text = api().write_review_report(release[2], result, fingerprint,
                                    repo=release[0], output_dir=release[1]).read_text(encoding="utf-8")
    assert "SQL 內容審核：" + sql_status in text
    assert "validation SQL 執行：" + query_status in text
    assert "部署驗證：" + deployment_status in text
    assert "SECRET_" not in text and "SELECT 1" not in text
    return result, text


@pytest.mark.parametrize("missing", ["all_localdb", "commit_query", "failure_round", "fixture_identity"])
def test_report_review_missing_runtime_correctness_prevents_sql_pass(release, missing):
    evidence = report_query_evidence(release)
    if missing == "commit_query":
        del evidence["rounds"]["commit"]["checks"]["validation_queries"]
    elif missing == "failure_round":
        del evidence["rounds"]["injected_failure"]
    elif missing == "fixture_identity":
        evidence["fixture_manifest_sha256"] = "0" * 64
    if missing != "all_localdb":
        update_metadata(release, localdb_validation=evidence)
    query_status = "通過" if missing == "failure_round" else "待確認"
    deployment = "通過" if missing == "commit_query" else "待確認"
    result, _ = assert_runtime_review(release, "待確認", query_status, deployment)
    pending = [f for f in result if f["domain"] == "sql_correctness" and f["status"] == "待確認"]
    assert pending and all(not f["blocking"] for f in pending)


def test_report_review_query_defect_is_consistent_in_api_cli_and_report(release):
    evidence = report_query_evidence(release)
    evidence["rounds"]["commit"]["checks"]["validation_queries"][0]["actual"] = 2
    update_metadata(release, localdb_validation=evidence)
    result, _ = assert_runtime_review(release, "未通過", "未通過", "通過")
    assert any(f["code"] == "validation_sql_defect" and f["domain"] == "sql_correctness" and f["blocking"] for f in result)
    command = [sys.executable, "-B", str(REVIEW / "validate_release_output.py"),
               "--repo", str(release[0]), "--output-dir", str(release[1]), "--run-root", str(release[2])]
    cli = subprocess.run(command, capture_output=True, text=True, check=False)
    assert cli.returncode == 1
    cli_result = json.loads(cli.stdout)
    assert next(f["status"] for f in cli_result if f["code"] == "sql_content_status") == "未通過"
    assert any(f["code"] == "validation_sql_defect" and f["blocking"] for f in cli_result)


@pytest.mark.parametrize("damage", [None, "not_run", "round_hash", "source_hash", "baseline_hash", "session", "fixture_hash"])
def test_report_review_failed_localdb_retains_only_trusted_negative_query(release, damage):
    evidence = report_query_evidence(release)
    evidence["status"] = "failed"
    row = evidence["rounds"]["commit"]
    row.update(status="failed", exit_code=1, error_output_summary="SECRET_EXPECTED_QUERY_FAILURE")
    row["checks"]["validation_queries"][0]["actual"] = 2
    if damage == "not_run":
        row["status"] = "not_run"
    elif damage == "round_hash":
        row["artifact_sha256"] = "0" * 64
    elif damage == "source_hash":
        row["checks"]["validation_queries"][0]["source_hash"] = "0" * 64
    elif damage == "baseline_hash":
        row["baseline_sha256"] = "0" * 64
    elif damage == "session":
        row["session_id"] = evidence["rounds"]["validate_only"]["session_id"]
    elif damage == "fixture_hash":
        evidence["fixture_sha256"] = "0" * 64
    update_metadata(release, localdb_validation=evidence)
    state = "未通過" if damage is None else "待確認"
    result, text = assert_runtime_review(release, state, state, "未通過")
    assert (any(f["code"] == "validation_sql_defect" and f["blocking"] for f in result)) == (damage is None)
    assert "- validate_only：未通過" not in text and "- rerun：未通過" not in text


@pytest.mark.parametrize("damage, expected", [("actual", "未通過"), ("negative", "未通過"),
                                             ("seed_identity", "待確認"), ("missing", "待確認")])
def test_report_review_declared_fixture_assertion_contributes_sql_correctness(release, damage, expected):
    evidence = report_query_evidence(release)
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    assertion = {"id": "SECRET_ASSERTION", "seed_row_id": "SECRET_SEED",
                 "expected_by_round": {name: {"before": 1, "after": 1} for name in evidence["rounds"]}}
    source["units"][0]["expected_assertions"] = [assertion]
    write_json(path, source)
    evidence["expected_assertions"] = [{"unit_id": "customer", **assertion}]
    for row in evidence["rounds"].values():
        row["data_checks"] = [{"unit_id": "customer", "id": assertion["id"], "seed_row_id": assertion["seed_row_id"],
                               "passed": True, "before": 1, "after": 1}]
    observed = evidence["rounds"]["commit"]["data_checks"][0]
    if damage == "actual":
        observed["after"] = 2
    elif damage == "negative":
        observed["passed"] = False
    elif damage == "seed_identity":
        observed["seed_row_id"] = "SECRET_DIFFERENT_SEED"
    elif damage == "missing":
        evidence["rounds"]["commit"]["data_checks"] = []
    update_metadata(release, localdb_validation=evidence)
    result, text = assert_runtime_review(release, expected, "通過", "通過")
    assert "fixture assertion 查核：" + expected in text
    fixture = [f for f in result if f["code"].startswith("fixture_assertion_")]
    assert fixture and all(f["domain"] == "sql_correctness" for f in fixture)
    assert any(f["blocking"] for f in fixture) == (expected == "未通過")


@pytest.mark.parametrize("code, section", [("baseline_model_conflict", "schema／來源定義審查"),
                                          ("partial_exclusion", "#5005 排除審查")])
def test_report_review_concrete_source_findings_survive_actual_metadata(release, code, section):
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["findings"].extend([
        {"code": code, "blocking": True, "domain": "business_data_validation", "reason": "SELECT SECRET_SCHEMA_VALUE"},
        {"code": "SECRET_UNKNOWN_CODE", "blocking": True, "reason": "SECRET_REASON"},
        {"code": "SECRET_BUSINESS_CODE", "blocking": True, "domain": "business_data_validation"},
    ])
    write_json(path, source)
    update_metadata(release, localdb_validation=report_query_evidence(release))
    fingerprint = complete_report_review(release)
    result = api().validate_release_output(release[1], release[2], repo=release[0])
    concrete = [f for f in result if f["code"] == code]
    assert concrete and concrete[0]["domain"] == "sql_correctness" and concrete[0]["blocking"]
    assert "SECRET_" not in repr(result)
    text = api().write_review_report(release[2], result, fingerprint,
                                    repo=release[0], output_dir=release[1]).read_text(encoding="utf-8")
    assert section + "：未通過" in text
    assert "- " + code + " [sql_correctness；未通過；阻塞]" in text
    assert "SQL 內容審核：未通過" in text and "部署驗證：通過" in text
    assert "- commit：通過" in text
    assert "SECRET_" not in text and "SELECT " not in text


def test_report_review_business_limits_and_non_mutating_na_keep_complete_sql_pass(release):
    evidence, _ = _na_localdb_evidence(release)
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["findings"].append({"code": "formal_rows_unavailable", "domain": "business_data_validation",
                               "blocking": True, "status": "未通過", "reason": "SECRET_FORMAL_VALUES"})
    write_json(path, source)
    queries = report_query_evidence(release)
    for name, row in evidence["rounds"].items():
        row["checks"] = queries["rounds"][name]["checks"]
    update_metadata(release, localdb_validation=evidence)
    result, text = assert_runtime_review(release, "通過", "通過", "通過")
    assert "fixture assertion 查核：N/A" in text
    assert not any(f["blocking"] for f in result)


@pytest.mark.parametrize("damage", ["unknown_id", "missing_units", "missing_evidence", "wrong_hash",
                                    "wrong_revision", "wrong_objects", "wrong_issues", "wrong_dependency",
                                    "wrong_evidence", "missing_impact", "missing_source_unit"])
def test_exclusion_requires_complete_matching_task2_source_provenance(release, damage):
    path = release[2] / "lifecycle_exclusion_manifest.json"
    manifest = json.loads(path.read_text())
    exclusion = manifest["exclusions"][0]
    if damage == "unknown_id":
        exclusion["unit_ids"] = ["nonexistent_unit"]
    elif damage == "missing_units":
        del exclusion["units"]
    elif damage == "missing_evidence":
        del exclusion["evidence"]
    elif damage == "missing_impact":
        del exclusion["dependency_impact"]
    elif damage == "missing_source_unit":
        source_path = release[2] / "source_unit_metadata.json"
        source = json.loads(source_path.read_text())
        source["sources"] = [s for s in source["sources"] if s["source_path"] != "core.sql"]
        write_json(source_path, source)
    elif damage == "wrong_evidence":
        exclusion["evidence"][0]["source_hash"] = "0" * 64
    else:
        fields = {"wrong_hash": ("source_hash", "0" * 64), "wrong_revision": ("source_revision", "0" * 40),
                  "wrong_objects": ("objects", ["dbo.Other"]), "wrong_issues": ("issues", ["#9999"]),
                  "wrong_dependency": ("depends_on", ["customer"])}
        key, value = fields[damage]
        exclusion["units"][0][key] = value
    write_json(path, manifest)
    result = findings(release)
    assert any(f["code"] == "invalid_exclusion_provenance" and f["blocking"] for f in result)
    assert status(release, "sql_content_status") == "未通過"


@pytest.mark.parametrize("value", [None, {}, "RAW_SECRET", [None], ["RAW_SECRET"], [{}],
                                    [{"code": "unsafe", "blocking": "false"}]])
def test_malformed_source_findings_returns_safe_blocking_finding(release, value):
    path = release[2] / "source_unit_metadata.json"
    source = json.loads(path.read_text())
    source["findings"] = value
    write_json(path, source)
    result = findings(release)
    assert any(f["code"] == "invalid_unit_evidence" and f["blocking"] for f in result)
    assert status(release, "sql_content_status") == "未通過"
    assert "RAW_SECRET" not in repr(result)

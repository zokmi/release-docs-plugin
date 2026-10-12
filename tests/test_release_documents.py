"""Operator delivery boundary and evidence-based document projection."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))


def api():
    assert (SCRIPTS / "render_release_documents.py").exists(), "Document renderer is missing"
    return importlib.import_module("render_release_documents")


def inputs(tmp_path):
    from analyze_release_units import AnalysisResult
    from assemble_deployment_sql import assemble_deployment_sql
    from lifecycle_store import write_lifecycle_run

    sql = "CREATE TABLE dbo.Customer (Id int);\r\n"
    unit = {"unit_id": "customer", "phase": "SCHEMA", "complete": True,
            "depends_on": [], "issues": ["#4000"], "objects": ["dbo.Customer"],
            "source_path": "sql/customer.sql", "source_revision": "a" * 40,
            "source_hash": "b" * 64, "source_line": 2,
            "sql_hash": hashlib.sha256(sql.encode()).hexdigest(), "sql": sql}
    exclusion = {"exclusion_id": "exclude-5005", "issues": ["#5005"],
                 "unit_ids": ["core"], "objects": ["dbo.Core"],
                 "reason": "核心 DB 本次不上線", "operator_action": "保留 dbo.Core 既有物件",
                 "dependency_impact": ["internal-graph-node"],
                 "reinstatement_conditions": ["完整單位重新授權與審查"],
                 "evidence": [{"source_hash": "c" * 64}]}
    analysis = AnalysisResult(units=[unit], exclusions=[exclusion],
                              source_scope={"base_sha": "d" * 40, "target_sha": "a" * 40},
                              baseline={"source_path": "baseline/old.sql", "source_hash": "e" * 64})
    analysis.structure_changes = [
        {"kind": "table", "name": "dbo.Customer", "description": "建立客戶主檔", "impact": "提供客戶查詢"},
        {"kind": "column", "name": "dbo.Customer.Id", "description": "建立識別欄位", "impact": "識別客戶"},
        {"kind": "index", "name": "IX_Customer", "description": "加速查詢", "impact": "增加寫入成本"},
        {"kind": "fk", "name": "FK_Customer", "description": "維持參照完整性", "impact": "檢查既有資料"},
        {"kind": "constraint", "name": "CK_Customer", "description": "限制識別值", "impact": "阻擋無效資料"},
        {"kind": "extended_property", "name": "dbo.Customer.MS_Description", "description": "補充欄位說明", "impact": "更新中繼資料"},
    ]
    for change in analysis.structure_changes:
        change["unit_id"] = "customer"
    manifest = write_lifecycle_run(tmp_path / ".release-docs/runs/run-1", analysis)
    artifact = assemble_deployment_sql(analysis.units, tmp_path / "assembly/01_部署SQL.sql", {"release_id": "release-42"})
    return analysis, artifact, manifest


def render(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = tmp_path / "operator"
    inventory = module.render_release_documents(analysis, artifact, manifest, output)
    return analysis, artifact, manifest, output, inventory


def test_output_has_only_operator_files_and_preserves_sql_bytes(tmp_path):
    _, artifact, _, output, inventory = render(tmp_path)
    assert {p.name for p in output.iterdir()} == {"00_上線指引.md", "01_部署SQL.sql"}
    assert (output / "01_部署SQL.sql").read_bytes() == artifact.path.read_bytes()
    assert inventory.output_dir == output.resolve()
    assert set(inventory.files) == {"00_上線指引.md", "01_部署SQL.sql"}
    assert inventory.files["01_部署SQL.sql"] == artifact.sha256


def test_review_report_keeps_internal_evidence_out_of_operator_delivery(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import importlib.util
    review_path = SCRIPTS.parents[1] / "release-docs-review/scripts/validate_release_output.py"
    monkeypatch.syspath_prepend(str(review_path.parent))
    spec = importlib.util.spec_from_file_location("task3_document_review", review_path)
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    _, artifact, manifest, output, _ = render(tmp_path)
    run = manifest.parent
    evidence_bytes = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    operator_bytes = {p.name: p.read_bytes() for p in output.iterdir()}
    text = review.write_review_report(run, [], SimpleNamespace(sha256="a" * 64)).read_text(encoding="utf-8")
    assert "## SQL 正確性驗證結果" in text
    assert "## 非阻塞性的正式資料／業務資料驗證限制" in text
    assert "validation SQL 執行：待確認" in text
    assert {p.name: p.read_bytes() for p in output.iterdir()} == operator_bytes
    assert (output / "01_部署SQL.sql").read_bytes() == artifact.path.read_bytes()
    assert all((run / name).read_bytes() == data for name, data in evidence_bytes.items())
    for forbidden in ("internal-graph-node", "source_hash", "dependency_impact", "CREATE TABLE", "baseline/old.sql"):
        assert forbidden not in text


def test_guide_projects_structure_and_lifecycle_scope_without_internal_evidence(tmp_path):
    _, _, _, output, _ = render(tmp_path)
    text = (output / "00_上線指引.md").read_text(encoding="utf-8")
    for expected in ("release-42", "dddddddddddd", "aaaaaaaaaaaa", "old.sql", "dbo.Customer",
                     "建立客戶主檔", "建立識別欄位", "加速查詢", "維持參照完整性",
                     "限制識別值", "補充欄位說明", "#5005", "核心 DB 本次不上線",
                     "保留 dbo.Core 既有物件", "完整單位重新授權與審查"):
        assert expected in text
    for internal in ("c" * 64, "e" * 64, "internal-graph-node", "lifecycle_exclusion_manifest.json", "depends_on"):
        assert internal not in text


def test_missing_structure_description_is_pending_instead_of_invented(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    del analysis.structure_changes
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    assert "dbo.Customer" in text and "結構異動說明待確認" in text
    assert "建立客戶主檔" not in text


def test_exclusions_come_from_manifest_not_in_memory_analysis(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.exclusions = []
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    assert "#5005" in (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")


def test_guide_has_safe_execution_error_reporting_and_unexecuted_localdb_status(tmp_path):
    _, _, _, output, _ = render(tmp_path)
    text = (output / "00_上線指引.md").read_text(encoding="utf-8")
    for token in ("結構異動表格說明", "資料異動表格說明", "DBA 工具", "ValidateOnly=1",
                  "ValidateOnly=0", "COMMIT", "ROLLBACK", "備份", "baseline",
                  "LocalDB：未執行", "table", "column", "index", "constraint"):
        assert token in text


def test_parameter_document_is_optional_and_masks_secret_values(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [
        {"environment": "Production", "service": "CustomerAPI", "key": "Auth:ApiToken",
         "value": "SUPER_SECRET", "format_example": "SUPER_SECRET", "apply": "由機密儲存更新",
         "reload": "重新啟動服務", "validation": "登入檢查"},
        {"environment": "Production", "service": "CustomerAPI", "key": "Cache:TTL",
         "value": "120", "format_example": "整數，例如 120", "apply": "設定檔更新",
         "reload": "重新載入", "validation": "檢查快取期限"},
        {"environment": "Production", "service": "CustomerAPI", "key": "Service:Url",
         "format_example": "https://user:URL_PASSWORD@example.test/?token=QUERY_SECRET",
         "apply": "設定檔更新", "reload": "重新載入", "validation": "健康檢查"},
    ]
    inventory = module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    for expected in ("Production", "CustomerAPI", "Auth:ApiToken", "Cache:TTL", "整數，例如 120",
                     "由機密儲存更新", "重新啟動服務", "登入檢查", "[REDACTED]"):
        assert expected in text
    for secret in ("SUPER_SECRET", "URL_PASSWORD", "QUERY_SECRET"):
        assert secret not in text
    assert '### ["Production","CustomerAPI","待確認"]' in text
    assert "### Auth" not in text
    assert set(inventory.files) == {"00_上線指引.md", "01_部署SQL.sql", "02_參數異動.md"}


def test_parameter_document_template_order_and_copyable_grouped_json(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    common = {"environment": "Production", "service": "CustomerAPI",
              "parameter_group": "Endpoints", "business_context": "對外查詢",
              "module": "查詢服務", "users": "客服", "impact": "切換查詢端點",
              "apply": "更新設定來源", "reload": "重啟 CustomerAPI",
              "validation": "檢查健康端點", "source_reference": "target:appsettings.json:12"}
    analysis.parameter_changes = [
        dict(common, key="Endpoints:0:Url", change="update", old_value="https://old.test/",
             new_value="https://new.test/", format_example="URL",
             environment_variable="Endpoints__0__Url"),
        dict(common, key="Endpoints:0:Enabled", change="add", new_value=False,
             format_example="布林值"),
        dict(common, key="Endpoints:1:Url", change="remove", old_value="https://retired.test/"),
        {**common, "parameter_group": "Cache", "business_context": "", "module": "",
         "users": "", "impact": "", "key": "Cache:TTL", "change": "update",
         "old_value": 60, "new_value": 120},
    ]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    ordered = ["# 參數異動", "## 來源範圍", "## 安全與套用前提",
               "## 業務情境與模組對照", "## 參數區塊", "## 參數部署查核",
               "## 脫敏異動 descriptor JSON"]
    assert [content.index(item) for item in ordered] == sorted(content.index(item) for item in ordered)
    assert "| 參數區塊 | 使用業務情境 | 使用模組／功能 | 主要使用者 | 異動影響 |" in content
    assert '| ["Production","CustomerAPI","Cache"] | 待確認 | 待確認 | 待確認 | 待確認 |' in content
    assert content.count('### ["Production","CustomerAPI","Endpoints"]') == 1
    assert "1. " in content.split("## 參數部署查核", 1)[1]
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", content, re.S)]
    assert blocks[0] == {"Endpoints": [{"Url": "https://new.test/", "Enabled": False}]}
    assert blocks[1] == {"Cache": {"TTL": 120}}
    descriptors = blocks[-1]
    assert [(item["key"], item["change"]) for item in descriptors] == [
        ("Endpoints:0:Url", "update"), ("Endpoints:0:Enabled", "add"),
        ("Endpoints:1:Url", "remove"), ("Cache:TTL", "update")]
    assert descriptors[0]["old_value"] == "https://old.test/"
    assert descriptors[0]["new_value"] == blocks[0]["Endpoints"][0]["Url"]
    assert descriptors[0]["source_reference"] == "target:appsettings.json:12"
    assert "Endpoints__0__Url=https://new.test/" in content
    assert "```text\n" in content
    assert "| Production | CustomerAPI | Endpoints:0:Url | update | https://old.test/ → https://new.test/ |" in content


def test_same_parameter_group_in_different_scopes_has_separate_sections(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [
        {"environment": environment, "service": service, "parameter_group": "Cache",
         "key": "Cache:TTL", "change": "update", "new_value": value,
         "business_context": context}
        for environment, service, value, context in (
            ("Production", "API", 120, "線上查詢"),
            ("Staging", "API", 30, "測試查詢"),
            ("Production", "Worker", 60, "批次作業"))]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    labels = ['["Production","API","Cache"]', '["Staging","API","Cache"]',
              '["Production","Worker","Cache"]']
    for label in labels:
        assert content.count("### " + label) == 1
    assert '| ' + labels[0] + ' | 線上查詢 |' in content
    assert '| ' + labels[1] + ' | 測試查詢 |' in content
    assert '| ' + labels[2] + ' | 批次作業 |' in content
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", content, re.S)]
    assert blocks[:3] == [{"Cache": {"TTL": 120}}, {"Cache": {"TTL": 30}},
                          {"Cache": {"TTL": 60}}]


def test_parameter_labels_are_injective_when_group_contains_scope_separator(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [
        {"environment": environment, "service": service, "parameter_group": group,
         "key": key, "change": "update", "new_value": value,
         "business_context": context}
        for environment, service, group, key, value, context in (
            ("Production", "API", "Cache", "Cache:TTL", 120, "API cache"),
            ("Staging", "API", "Cache", "Cache:TTL", 30, "Staging cache"),
            ("Development", "Worker", "Production / API / Cache",
             "Production / API / Cache:TTL", 10, "Literal separator group"))]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    labels = ['["Production","API","Cache"]', '["Staging","API","Cache"]',
              '["Development","Worker","Production / API / Cache"]']
    for label in labels:
        assert content.count("### " + label) == 1
        assert content.count("| " + label + " |") == 1


def test_sparse_array_index_is_pending_partial_json_without_null_padding(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [{
        "environment": "Production", "service": "API", "parameter_group": "Endpoints",
        "key": "Endpoints:3:Url", "change": "add", "new_value": "https://new.test/"}]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    assert "待確認" in content.split('### ["Production","API","Endpoints"]', 1)[1].split("## 參數部署查核", 1)[0]
    assert "不可直接套用" in content
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", content, re.S)]
    assert blocks[0] == {"Endpoints": {"3": {"Url": "https://new.test/"}}}
    assert blocks[-1][0]["key"] == "Endpoints:3:Url"


def test_parameter_json_and_environment_examples_redact_known_secrets(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [
        {"environment": "Production", "service": "CustomerAPI", "key": "Auth:JwtSecret",
         "change": "update", "old_value": "OLD_PRIVATE", "new_value": "NEW_PRIVATE",
         "format_example": "NEW_PRIVATE", "environment_variable": "Auth__JwtSecret",
         "apply": "由機密儲存注入 NEW_PRIVATE", "reload": "重啟", "validation": "驗證登入"},
        {"environment": "Production", "service": "CustomerAPI", "key": "Service:Url",
         "change": "add", "new_value": "https://user:URL_PASSWORD@example.test/?api_key=QUERY_SECRET",
         "environment_variable": "Service__Url", "source_reference": "target:settings.json:4"},
    ]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    for secret in ("OLD_PRIVATE", "NEW_PRIVATE", "URL_PASSWORD", "QUERY_SECRET"):
        assert secret not in content
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", content, re.S)]
    assert blocks[0]["Auth"]["JwtSecret"] == "[REDACTED]"
    assert blocks[-1][0]["old_value"] == blocks[-1][0]["new_value"] == "[REDACTED]"
    assert blocks[-1][1]["new_value"] == blocks[0]["Service"]["Url"]
    assert "Auth__JwtSecret=[REDACTED]" in content
    assert "待確認" in content


def test_nested_configuration_secret_and_source_payload_never_reach_document(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [{
        "environment": "Production", "service": "CustomerAPI", "key": "Provider",
        "change": "add", "new_value": {"endpoint": "postgres://user:DB_PASSWORD@db.test/main",
                                        "password": "NESTED_SECRET", "enabled": True},
        "source_reference": {"target": {"path": "settings.json", "revision": "a" * 40,
                                        "content": "SOURCE_PAYLOAD_SECRET"}},
    }]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    content = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    for secret in ("DB_PASSWORD", "NESTED_SECRET", "SOURCE_PAYLOAD_SECRET"):
        assert secret not in content
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", content, re.S)]
    assert blocks[0]["Provider"]["password"] == "[REDACTED]"
    assert blocks[0]["Provider"]["enabled"] is True
    assert blocks[-1][0]["source_reference"]["target"] == {
        "path": "settings.json", "revision": "a" * 40}


@pytest.mark.parametrize("name", ["lifecycle_exclusion_manifest.json", "source_unit_metadata.json", "surprise.txt", "02_資料SQL.sql"])
def test_undeclared_output_is_rejected_before_any_write(tmp_path, name):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = tmp_path / "operator"
    output.mkdir()
    (output / name).write_text("sentinel")
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, output)
    assert list(output.iterdir()) == [output / name]
    assert (output / name).read_text() == "sentinel"


@pytest.mark.parametrize("suffix", ["docs/release-artifacts", "docs/RELEASE-ARTIFACTS/new", "operator/../escaped", ".release-docs/runs/operator"])
def test_unsafe_output_path_is_rejected_without_creating_it(tmp_path, suffix):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, tmp_path / suffix)
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "docs").exists()


@pytest.mark.parametrize("damage", ["missing_manifest", "wrong_manifest_name", "invalid_manifest", "changed_sql", "blocked", "excluded_mapping"])
def test_invalid_evidence_cannot_produce_operator_files(tmp_path, damage):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    if damage == "missing_manifest":
        manifest.unlink()
    elif damage == "wrong_manifest_name":
        manifest = manifest.parent / "source_unit_metadata.json"
    elif damage == "invalid_manifest":
        manifest.write_text("{}")
    elif damage == "changed_sql":
        artifact.path.write_bytes(b"tampered SQL")
    elif damage == "blocked":
        analysis.findings.append({"code": "unresolved_exclusion", "blocking": True})
    else:
        artifact.unit_mapping[0]["unit_id"] = "core"
    output = tmp_path / "operator"
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, output)
    assert not output.exists()


def test_existing_sql_in_output_can_be_preserved_and_documents_are_deterministic(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = artifact.path.parent
    first = module.render_release_documents(analysis, artifact, manifest, output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    second = module.render_release_documents(analysis, artifact, manifest, output)
    assert first.files == second.files
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_stale_optional_document_is_rejected_instead_of_delivered(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = tmp_path / "operator"
    output.mkdir()
    (output / "02_參數異動.md").write_text("stale")
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, output)
    assert {p.name for p in output.iterdir()} == {"02_參數異動.md"}


@pytest.mark.parametrize("surface", ["output_file", "artifact", "manifest"])
def test_hardlinks_are_rejected_without_touching_link_target(tmp_path, surface):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = tmp_path / "operator"
    output.mkdir()
    target = tmp_path / "target"
    if surface == "output_file":
        target.write_bytes(b"sentinel")
        link = output / "00_上線指引.md"
    elif surface == "artifact":
        target.write_bytes(artifact.path.read_bytes())
        artifact.path.unlink()
        link = artifact.path
    else:
        target.write_bytes(manifest.read_bytes())
        manifest.unlink()
        link = manifest
    original = target.read_bytes()
    try:
        os.link(target, link)
    except OSError as error:
        pytest.skip("Sandbox cannot create hardlinks: " + str(error.winerror))
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, output)
    assert target.read_bytes() == original


def test_output_directory_link_is_rejected(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "operator"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip("Sandbox cannot create symlinks: " + str(error.winerror))
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, link)
    assert not list(target.iterdir())


def test_localdb_pass_requires_complete_evidence_and_remains_separate_from_sql_review(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    metadata_path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["localdb_validation"] = {"status": "passed"}
    metadata_path.write_text(json.dumps(metadata))
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    assert "LocalDB：待確認" in text
    assert "SQL 內容審核：待確認" in text


def test_conflicting_existing_document_blocks_all_writes(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    output = tmp_path / "operator"
    output.mkdir()
    guide = output / "00_上線指引.md"
    guide.write_text("unrelated existing guide")
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, output)
    assert list(output.iterdir()) == [guide]
    assert guide.read_text() == "unrelated existing guide"


def test_secret_original_values_are_redacted_from_parameter_instructions(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.parameter_changes = [{"environment": "Production", "service": "CustomerAPI",
                                   "key": "Auth:Secret", "old_value": "OLD_SECRET", "new_value": "NEW_SECRET",
                                   "format_example": "NEW_SECRET", "apply": "將 OLD_SECRET 改成 NEW_SECRET",
                                   "reload": "reload using NEW_SECRET", "validation": "check NEW_SECRET"}]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    assert "OLD_SECRET" not in text and "NEW_SECRET" not in text
    assert "將 [REDACTED] 改成 [REDACTED]" in text


def test_localdb_status_accepts_only_complete_current_artifact_evidence(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    baseline = tmp_path / "baseline.sql"
    fixture = tmp_path / "fixture.sql"
    fixture_manifest = tmp_path / "fixture.json"
    baseline.write_text("CREATE TABLE dbo.Existing (Id int);", encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Existing VALUES (1);", encoding="utf-8")
    fixture_manifest.write_text("{}", encoding="utf-8")
    evidence = {"status": "passed", "exit_code": 0, "server": "(localdb)\\test",
                "database": "disposable", "provider_version": "SQL Server test",
                "tool_version": "runner test", "baseline_source": str(baseline),
                "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "fixture_source": str(fixture), "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": hashlib.sha256(fixture_manifest.read_bytes()).hexdigest(),
                "artifact_sha256": artifact.sha256,
                "command": "isolated runner", "checks": ["all checks passed"],
                "error_output_summary": ""}
    preserved = {"dbo.Existing": "Id=1"}
    rounds = {name: dict(evidence, database_id={"validate_only": "db-v", "commit": "db-c", "rerun": "db-c", "injected_failure": "db-f"}[name],
                         session_id="session-" + name,
                         checks=[name + " verified"], preserved_data_summary=preserved,
                         committed_state="committed-handle" if name in ("commit", "rerun") else "")
              for name in ("validate_only", "commit", "rerun", "injected_failure")}
    metadata["localdb_validation"] = {"status": "passed", "artifact_sha256": artifact.sha256,
                                     "fixture_source": str(fixture), "fixture_sha256": evidence["fixture_sha256"],
                                     "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": evidence["fixture_manifest_sha256"],
                                     "expected_preserved_data_summary": preserved,
                                     "rounds": rounds}
    metadata["localdb_validation"]["rounds"]["injected_failure"]["error_output_summary"] = "Expected THROW 51000, rollback and later-unit stop confirmed"
    path.write_text(json.dumps(metadata))
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "complete")
    assert "LocalDB：通過" in (tmp_path / "complete/00_上線指引.md").read_text(encoding="utf-8")
    for damage in ("missing_preserved", "wrong_preserved", "duplicate_checks"):
        altered = json.loads(json.dumps(metadata))
        if damage == "missing_preserved":
            altered["localdb_validation"]["rounds"]["commit"].pop("preserved_data_summary")
        elif damage == "wrong_preserved":
            altered["localdb_validation"]["rounds"]["commit"]["preserved_data_summary"] = {"dbo.Existing": "Id=2"}
        else:
            altered["localdb_validation"]["rounds"]["commit"]["checks"] = ["validate_only verified"]
        path.write_text(json.dumps(altered), encoding="utf-8")
        output = tmp_path / damage
        module.render_release_documents(analysis, artifact, manifest, output)
        assert "LocalDB：待確認" in (output / "00_上線指引.md").read_text(encoding="utf-8")
    metadata["localdb_validation"]["artifact_sha256"] = "f" * 64
    path.write_text(json.dumps(metadata))
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "stale")
    assert "LocalDB：待確認" in (tmp_path / "stale/00_上線指引.md").read_text(encoding="utf-8")
    valid = metadata["localdb_validation"]
    valid["artifact_sha256"] = artifact.sha256
    for index, (round_name, field) in enumerate((
            (None, "fixture_manifest_sha256"), ("commit", "artifact_sha256"),
            ("validate_only", "session_id"), ("rerun", "database_id"),
            ("commit", "committed_state"))):
        altered = json.loads(json.dumps(valid))
        selected = altered if round_name is None else altered["rounds"][round_name]
        selected.pop(field)
        metadata["localdb_validation"] = altered
        path.write_text(json.dumps(metadata), encoding="utf-8")
        output = tmp_path / f"incomplete-{index}"
        module.render_release_documents(analysis, artifact, manifest, output)
        assert "LocalDB：待確認" in (output / "00_上線指引.md").read_text(encoding="utf-8")


def test_guide_requires_current_fixture_and_data_checks_for_data_units(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    baseline = tmp_path / "baseline.sql"
    fixture = tmp_path / "fixture.sql"
    fixture_manifest = tmp_path / "fixture.json"
    baseline.write_text("CREATE TABLE dbo.Existing (Id int);", encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Existing VALUES (1);", encoding="utf-8")
    fixture_manifest.write_text("{}", encoding="utf-8")
    path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    round_evidence = {"status": "passed", "exit_code": 0, "server": "(localdb)\\test", "database": "disposable",
                      "provider_version": "SQL Server test", "tool_version": "runner test",
                      "baseline_source": str(baseline), "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                      "fixture_source": str(fixture), "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                      "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": hashlib.sha256(fixture_manifest.read_bytes()).hexdigest(),
                      "artifact_sha256": artifact.sha256,
                      "command": "isolated runner", "checks": ["all checks passed"], "error_output_summary": ""}
    preserved = {"dbo.Existing": "Id=1"}
    rounds = {name: dict(round_evidence, database_id={"validate_only": "db-v", "commit": "db-c", "rerun": "db-c", "injected_failure": "db-f"}[name],
                         session_id="session-" + name,
                         checks=[name + " verified"], preserved_data_summary=preserved,
                         committed_state="committed-handle" if name in ("commit", "rerun") else "")
              for name in ("validate_only", "commit", "rerun", "injected_failure")}
    rounds["injected_failure"]["error_output_summary"] = "Expected error rollback and stop"
    metadata["localdb_validation"] = {"status": "passed", "artifact_sha256": artifact.sha256,
                                      "fixture_source": str(fixture), "fixture_sha256": round_evidence["fixture_sha256"],
                                      "fixture_manifest": str(fixture_manifest), "fixture_manifest_sha256": round_evidence["fixture_manifest_sha256"],
                                      "expected_preserved_data_summary": preserved,
                                      "rounds": rounds}
    path.write_text(json.dumps(metadata), encoding="utf-8")
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "current")
    assert "LocalDB：通過" in (tmp_path / "current/00_上線指引.md").read_text(encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Existing VALUES (2);", encoding="utf-8")
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "changed")
    assert "LocalDB：待確認" in (tmp_path / "changed/00_上線指引.md").read_text(encoding="utf-8")
    fixture.write_text("INSERT INTO dbo.Existing VALUES (1);", encoding="utf-8")
    analysis.units[0]["phase"] = "DATA"
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "data")
    assert "LocalDB：待確認" in (tmp_path / "data/00_上線指引.md").read_text(encoding="utf-8")


def test_guide_treats_stale_failed_localdb_evidence_as_pending(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    metadata["localdb_validation"] = {"status": "failed", "artifact_sha256": "0" * 64}
    path.write_text(json.dumps(metadata), encoding="utf-8")
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    guide = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    assert "LocalDB：待確認" in guide


@pytest.mark.parametrize("filename", ["01_部署SQL.sql", "lifecycle_exclusion_manifest.json"])
def test_linked_input_files_are_rejected(tmp_path, filename):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    path = artifact.path if filename.endswith(".sql") else manifest
    target = tmp_path / "target"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError as error:
        pytest.skip("Sandbox cannot create symlinks: " + str(error.winerror))
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    assert not (tmp_path / "operator").exists()


def test_excluded_units_do_not_reappear_in_structure_change_scope(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    excluded = dict(analysis.units[0], unit_id="core", objects=["dbo.Core"],
                    structure_changes=[{"kind": "table", "name": "dbo.Core", "description": "建立排除核心表", "impact": "排除影響"}])
    analysis.units.append(excluded)
    analysis.structure_changes.append({"kind": "column", "unit_id": "core", "name": "dbo.Core.Id",
                                       "description": "新增排除欄位", "impact": "排除影響"})
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "explicit")
    text = (tmp_path / "explicit/00_上線指引.md").read_text(encoding="utf-8")
    assert "新增排除欄位" not in text
    del analysis.structure_changes
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "unit-descriptions")
    text = (tmp_path / "unit-descriptions/00_上線指引.md").read_text(encoding="utf-8")
    assert "建立排除核心表" not in text


@pytest.mark.parametrize("suffix", ["operator/.. /escaped", "docs./release-artifacts", "operator/folder. "])
def test_windows_ambiguous_segments_cannot_escape_path_checks(tmp_path, suffix):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    with pytest.raises(ValueError):
        module.render_release_documents(analysis, artifact, manifest, tmp_path / suffix)
    assert not (tmp_path / "operator").exists()


@pytest.mark.parametrize("field", ["format_example", "apply", "reload", "validation"])
@pytest.mark.parametrize("assignment", ["credential", "private_key"])
def test_sensitive_assignments_in_nonsensitive_parameter_prose_are_redacted(tmp_path, field, assignment):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    change = {"environment": "Production", "service": "CustomerAPI", "key": "Service:Url",
              "format_example": "https://example.test/", "apply": "更新設定", "reload": "reload", "validation": "healthy"}
    change[field] = "https://example.test/?" + assignment + "=LEAKED_VALUE&mode=test"
    analysis.parameter_changes = [change]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/02_參數異動.md").read_text(encoding="utf-8")
    assert "LEAKED_VALUE" not in text
    assert assignment + "=[REDACTED]&mode=test" in text


def test_sensitive_assignments_in_guide_descriptions_are_redacted(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    analysis.structure_changes[0]["description"] = "credential='LEAKED CREDENTIAL'; private_key=LEAKED_KEY"
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    assert "LEAKED CREDENTIAL" not in text and "LEAKED_KEY" not in text
    assert "credential=[REDACTED]" in text and "private_key=[REDACTED]" in text


@pytest.mark.parametrize("unit_id", [None, "unknown"])
def test_unproven_top_level_structure_scope_cannot_reintroduce_excluded_objects(tmp_path, unit_id):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    change = {"kind": "table", "name": "dbo.Core", "description": "建立排除核心表", "impact": "排除影響"}
    if unit_id is not None:
        change["unit_id"] = unit_id
    analysis.structure_changes.append(change)
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    structure = text.split("## 結構異動範圍與說明", 1)[1].split("## 本次排除摘要", 1)[0]
    assert "dbo.Core" not in structure and "建立排除核心表" not in structure
    assert "待確認" in structure
    assert "建立客戶主檔" in structure


def test_unit_level_structure_description_inherits_its_included_source_unit(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    del analysis.structure_changes
    analysis.units[0]["structure_changes"] = [{"kind": "table", "name": "dbo.Customer",
                                               "description": "建立客戶主檔", "impact": "提供客戶查詢"}]
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    assert "建立客戶主檔" in (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("round_name", ["validate_only", "commit", "rerun", "injected_failure"])
@pytest.mark.parametrize("summary", [None, 123])
def test_localdb_round_without_explicit_error_output_summary_remains_pending(tmp_path, round_name, summary):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    evidence = {"status": "passed", "exit_code": 0, "server": "(localdb)\\test", "database": "disposable",
                "provider_version": "SQL Server test", "tool_version": "runner test", "baseline_source": "old.sql",
                "fixture_source": "fixture.sql", "command": "isolated runner", "checks": ["all checks passed"],
                "error_output_summary": ""}
    rounds = {name: dict(evidence) for name in ("validate_only", "commit", "rerun", "injected_failure")}
    rounds["injected_failure"]["error_output_summary"] = "Expected unit error, rollback and stop confirmed"
    if summary is None:
        del rounds[round_name]["error_output_summary"]
    else:
        rounds[round_name]["error_output_summary"] = summary
    metadata["localdb_validation"] = {"status": "passed", "artifact_sha256": artifact.sha256, "rounds": rounds}
    path.write_text(json.dumps(metadata))
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    text = (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")
    assert "LocalDB：待確認" in text and "LocalDB：通過" not in text


def test_injected_failure_without_recorded_expected_error_remains_pending(tmp_path):
    module = api()
    analysis, artifact, manifest = inputs(tmp_path)
    path = manifest.parent / "lifecycle_metadata.json"
    metadata = json.loads(path.read_text())
    evidence = {"status": "passed", "exit_code": 0, "server": "(localdb)\\test", "database": "disposable",
                "provider_version": "SQL Server test", "tool_version": "runner test", "baseline_source": "old.sql",
                "fixture_source": "fixture.sql", "command": "isolated runner", "checks": ["all checks passed"],
                "error_output_summary": ""}
    metadata["localdb_validation"] = {"status": "passed", "artifact_sha256": artifact.sha256,
                                     "rounds": {name: dict(evidence) for name in ("validate_only", "commit", "rerun", "injected_failure")}}
    path.write_text(json.dumps(metadata))
    module.render_release_documents(analysis, artifact, manifest, tmp_path / "operator")
    assert "LocalDB：待確認" in (tmp_path / "operator/00_上線指引.md").read_text(encoding="utf-8")

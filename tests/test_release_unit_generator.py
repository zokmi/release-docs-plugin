import hashlib
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))

import release_unit_generator
from release_unit_generator import generate_release_artifacts
from data_evidence import build_data_evidence


def test_generator_materializes_twenty_descriptors(tmp_path):
    repair = tmp_path / "repair"
    repair.mkdir()
    units = []
    for i in range(20):
        name = f"u{i}.sql"
        (repair / name).write_text("SELECT 1;\n", encoding="utf-8")
        units.append({"unit_id": f"u{i}", "phase": "SCHEMA", "source_path": f"src/{name}",
                      "source_revision": "a" * 40, "source_hash": "b" * 64,
                      "source_line": 1, "depends_on": [], "repair_source": f"repair-source/units/{name}"})
    descriptor = tmp_path / "input.json"
    descriptor.write_text(json.dumps({"units": units}), encoding="utf-8")
    result = generate_release_artifacts(descriptor, repair, tmp_path / "out")
    assert len(result["units"]) == 20
    assert (tmp_path / "out/formal-release-unit-descriptors.json").exists()


def test_data_evidence_requires_all_four_rounds(tmp_path):
    analysis = tmp_path / "analysis.json"
    analysis.write_text(json.dumps({"units": [{"unit_id": f"u{i}"} for i in range(5)]}), encoding="utf-8")
    validation = tmp_path / "validation.json"
    validation.write_text(json.dumps({"data_checks": []}), encoding="utf-8")
    result = build_data_evidence(analysis, validation, tmp_path / "evidence.json")
    assert result["status"] == "blocked_missing_authoritative_evidence"
    assert len(result["missing_units"]) == 5


def test_generator_preserves_source_order_and_records_original_phase(tmp_path):
    repair = tmp_path / "repair"
    repair.mkdir()
    (repair / "Links.sql").write_text("CREATE TABLE dbo.Links (Id int);\n", encoding="utf-8")
    (repair / "Device.sql").write_text("-- 需先執行 Links.sql\nALTER TABLE dbo.Links ADD Name nvarchar(10);\n", encoding="utf-8")
    descriptor = tmp_path / "input.json"
    descriptor.write_text(json.dumps({"units": [
        {"unit_id": "Links", "phase": "DATA", "source_path": "src/Links.sql", "source_revision": "a" * 40, "source_hash": "b" * 64, "source_line": 1, "depends_on": [], "repair_source": "repair-source/units/Links.sql"},
        {"unit_id": "Device", "phase": "SCHEMA", "source_path": "src/Device.sql", "source_revision": "a" * 40, "source_hash": "b" * 64, "source_line": 1, "depends_on": [], "repair_source": "repair-source/units/Device.sql"},
    ] * 10}), encoding="utf-8")
    result = generate_release_artifacts(descriptor, repair, tmp_path / "out")
    links = next(u for u in result["units"] if u["unit_id"] == "Links")
    device = next(u for u in result["units"] if u["unit_id"] == "Device")
    assert result["units"][0]["unit_id"] == "Links"
    assert device["original_phase"] == "SCHEMA"
    assert device["depends_on"] == ["Links"]


def _metadata_input(tmp_path):
    repair = tmp_path / "repair"
    repair.mkdir()
    procedures = ("add", "update", "drop")
    units = []
    for index in range(20):
        operation = procedures[index] if index < 3 else None
        name = f"u{index}.sql"
        if operation:
            value = "N'description', " if operation != "drop" else ""
            sql = (f"EXEC sys.sp_{operation}extendedproperty N'MS_Description', {value}"
                   f"N'SCHEMA', N'dbo', N'TABLE', N'T{index}';\n")
        else:
            sql = "SELECT 1;\n"
        (repair / name).write_text(sql, encoding="utf-8")
        units.append({"unit_id": f"u{index}", "phase": "SCHEMA", "source_path": f"src/{name}",
                      "source_revision": "a" * 40, "source_hash": hashlib.sha256(sql.encode()).hexdigest(),
                      "source_line": 1, "depends_on": [], "repair_source": f"repair-source/units/{name}"})
    descriptor = tmp_path / "input.json"
    descriptor.write_text(json.dumps({"profile": "database_tool_minimal", "units": units}), encoding="utf-8")
    return descriptor, repair, units


def test_metadata_descriptor_provenance_and_bytes_are_deterministic(tmp_path):
    descriptor, repair, _ = _metadata_input(tmp_path)
    first = generate_release_artifacts(descriptor, repair, tmp_path / "first")
    second = generate_release_artifacts(descriptor, repair, tmp_path / "second")
    assert (tmp_path / "first/formal-release-unit-descriptors.json").read_bytes() == (
        tmp_path / "second/formal-release-unit-descriptors.json").read_bytes()
    for operation, index in (("add", 0), ("update", 1), ("drop", 2)):
        entry = first["units"][index]
        body = (tmp_path / "first" / entry["execution_body"]).read_bytes()
        assert body == (tmp_path / "second" / entry["execution_body"]).read_bytes()
        assert entry == second["units"][index]
        assert entry["source_operation"] == operation
        assert entry["materialized_operation"] == operation
        assert entry["provenance"]["source_operation"] == operation
        assert entry["provenance"]["materialized_operation"] == operation
        assert entry["provenance"]["fallback_policy"] == (
            "add_if_missing" if operation == "update" else "none")
        assert entry["provenance"]["provider_version"] == "metadata-provider/1"
        assert entry["provenance"]["source_input_sha256"] == entry["repair_hash"]
        assert entry["provenance"]["materialized_body_sha256"] == entry["sql_hash"]
        assert entry["provenance"]["artifact_sha256"] == hashlib.sha256(body).hexdigest()
        release_unit_generator.validate_provider_contract(entry, body)


def test_metadata_contract_rejects_operation_and_hash_mismatch(tmp_path):
    descriptor, repair, _ = _metadata_input(tmp_path)
    entry = generate_release_artifacts(descriptor, repair, tmp_path / "out")["units"][1]
    body = (tmp_path / "out" / entry["execution_body"]).read_bytes()
    for changed in ("descriptor", "provenance", "procedure", "hash", "fallback"):
        damaged = json.loads(json.dumps(entry))
        damaged_body = body
        if changed == "descriptor":
            damaged["materialized_operation"] = "add"
        elif changed == "provenance":
            damaged["provenance"]["source_operation"] = "add"
        elif changed == "procedure":
            damaged_body = body.replace(b"sp_updateextendedproperty", b"sp_dropextendedproperty", 1)
        elif changed == "fallback":
            damaged["provenance"]["fallback_policy"] = "none"
        else:
            damaged["provenance"]["artifact_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="provider_contract_failure"):
            release_unit_generator.validate_provider_contract(damaged, damaged_body)


@pytest.mark.parametrize("legacy_hash", ["input_sha256", "output_sha256"])
def test_metadata_contract_rejects_conflicting_legacy_hash(legacy_hash, tmp_path):
    descriptor, repair, _ = _metadata_input(tmp_path)
    entry = generate_release_artifacts(descriptor, repair, tmp_path / "out")["units"][1]
    body = (tmp_path / "out" / entry["execution_body"]).read_bytes()
    entry["provenance"][legacy_hash] = "0" * 64
    with pytest.raises(ValueError, match="provider_contract_failure"):
        release_unit_generator.validate_provider_contract(entry, body)


def test_5005_units_are_excluded_before_provider_materialization(tmp_path):
    descriptor, repair, units = _metadata_input(tmp_path)
    units[0]["issues"] = ["#5005"]
    descriptor.write_text(json.dumps({"units": units}), encoding="utf-8")
    result = generate_release_artifacts(descriptor, repair, tmp_path / "out")
    assert all(unit["unit_id"] != "u0" for unit in result["units"])
    assert not (tmp_path / "out/execution/u0.sql").exists()
    assert "T0" not in json.dumps(result)


def test_5005_rerun_removes_previously_generated_execution_body(tmp_path):
    descriptor, repair, units = _metadata_input(tmp_path)
    output = tmp_path / "out"
    generate_release_artifacts(descriptor, repair, output)
    stale = output / "execution/u0.sql"
    assert stale.is_file()
    units[0]["issues"] = ["#5005"]
    descriptor.write_text(json.dumps({"units": units}), encoding="utf-8")
    result = generate_release_artifacts(descriptor, repair, output)
    assert not stale.exists()
    assert "u0" not in [unit["unit_id"] for unit in result["units"]]

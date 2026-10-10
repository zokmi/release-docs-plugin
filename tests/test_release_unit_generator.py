import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))

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

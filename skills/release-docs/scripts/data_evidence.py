"""Validate and normalize four-round DATA evidence without fabricating values."""
from __future__ import annotations

import json
from pathlib import Path

CASES = ("preserved_data", "existing_value", "boundary", "missing_reference")


def build_data_evidence(analysis_path: Path, validation_path: Path, output_path: Path) -> dict:
    analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    validation = json.loads(Path(validation_path).read_text(encoding="utf-8"))
    expected_units = {u["unit_id"] for u in analysis.get("units", [])}
    if len(expected_units) != 5:
        raise ValueError(f"expected five DATA units, got {len(expected_units)}")
    checks = validation.get("data_checks", [])
    by_unit = {item.get("unit_id"): item for item in checks if isinstance(item, dict)}
    rounds = []
    missing = []
    for unit_id in sorted(expected_units):
        item = by_unit.get(unit_id, {})
        actual = item.get("rounds", {})
        unit_rounds = {case: actual.get(case) for case in CASES}
        if any(value is None for value in unit_rounds.values()):
            missing.append(unit_id)
        rounds.append({"unit_id": unit_id, "rounds": unit_rounds,
                       "status": "passed" if unit_id not in missing else "missing_authoritative_evidence"})
    result = {"schema_version": 1,
              "status": "passed" if not missing else "blocked_missing_authoritative_evidence",
              "required_cases": list(CASES), "units": rounds,
              "missing_units": missing,
              "source": {"analysis": str(analysis_path), "validation": str(validation_path)}}
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

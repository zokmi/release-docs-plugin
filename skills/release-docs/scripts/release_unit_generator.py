"""Materialize traceable release-unit descriptors and execution bodies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from metadata_provider import transform_provider_sql


PHASES = ("SCHEMA", "REPAIR", "DATA", "VALIDATION")
PROVIDER_VERSION = "metadata-provider/1"


def generate_release_artifacts(descriptor_path: Path, repair_root: Path, output_root: Path) -> dict:
    descriptor_path = Path(descriptor_path)
    repair_root = Path(repair_root)
    output_root = Path(output_root)
    source = json.loads(descriptor_path.read_text(encoding="utf-8"))
    units = source.get("units", [])
    if len(units) != 20:
        raise ValueError(f"expected 20 units, got {len(units)}")
    output_root.mkdir(parents=True, exist_ok=True)
    materialized = []
    for item in units:
        unit_id = item["unit_id"]
        relative = Path(item["repair_source"]).relative_to("repair-source/units")
        repair_path = repair_root / relative
        raw = repair_path.read_text(encoding="utf-8")
        repair_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if item.get("repair_hash") and repair_hash != item["repair_hash"]:
            raise ValueError(f"repair hash mismatch: {unit_id}")
        execution, provenance = transform_provider_sql(raw, source_path=item["source_path"], unit_id=unit_id)
        body_path = output_root / "execution" / f"{unit_id}.sql"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(execution if execution.endswith("\n") else execution + "\n", encoding="utf-8")
        entry = {key: item[key] for key in ("unit_id", "phase", "source_path", "source_revision", "source_hash", "source_line", "depends_on")}
        if entry["phase"] not in PHASES:
            raise ValueError(f"unsupported phase: {entry['phase']}")
        missing_contract = [key for key in ("preconditions", "target_definition", "skip_condition", "stop_condition", "validation_queries") if key not in item]
        entry.update({"complete": True, "sql": execution,
                      "sql_hash": hashlib.sha256(execution.encode("utf-8")).hexdigest(),
                      "repair_source": item["repair_source"], "repair_hash": repair_hash,
                      "provider_kind": "metadata" if provenance["metadata_operations"] or any(x.startswith("metadata") for x in provenance["transformations"]) else None,
                      "execution_body": str(body_path.relative_to(output_root)),
                      "provenance": {**provenance, "provider_version": PROVIDER_VERSION,
                                     "baseline_sha": source.get("base_sha"),
                                     "source_revision": item["source_revision"],
                                     "mapping": provenance["transformations"]},
                      "preconditions": item.get("preconditions", []),
                      "target_definition": item.get("target_definition", {"sql": execution}),
                      "skip_condition": item.get("skip_condition"),
                      "stop_condition": item.get("stop_condition"),
                      "validation_queries": item.get("validation_queries", []),
                      "descriptor_status": "blocked_missing_contract" if missing_contract else "complete",
                      "missing_contract": missing_contract})
        if "dynamic_drop_constraint_provider" in provenance["transformations"]:
            entry["provider_kind"] = "dynamic_ddl"
        materialized.append(entry)
    materialized.sort(key=lambda x: (PHASES.index(x["phase"]), x["unit_id"]))
    seen = set()
    for item in materialized:
        unknown = [dep for dep in item["depends_on"] if dep not in seen]
        if unknown:
            raise ValueError(f"dependency is not ordered or missing: {item['unit_id']}: {unknown}")
        seen.add(item["unit_id"])
    result = {"schema_version": 2, "status": "materialized", "base_sha": source.get("base_sha"),
              "target_sha": source.get("target_sha"), "units": materialized}
    (output_root / "formal-release-unit-descriptors.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("repair_root", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    result = generate_release_artifacts(args.descriptor, args.repair_root, args.output_root)
    print(json.dumps({"status": result["status"], "units": len(result["units"])}, ensure_ascii=False))

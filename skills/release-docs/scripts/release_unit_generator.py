"""Materialize traceable release-unit descriptors and execution bodies."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from metadata_provider import transform_provider_sql


PHASES = ("SCHEMA", "REPAIR", "DATA", "VALIDATION")
PROVIDER_VERSION = "metadata-provider/1"


def validate_provider_contract(entry: dict, artifact: bytes) -> None:
    """Reject a materialized metadata unit whose operation or receipt diverges."""
    provenance = entry.get("provenance", {})
    operations = provenance.get("metadata_operations", [])
    if not operations:
        return
    expected = []
    source_operations = []
    for op in operations:
        source = op.get("source_operation")
        if source not in ("add", "update", "drop") or op.get("operation") != source:
            raise ValueError("provider_contract_failure: source operation")
        if op.get("materialized_operation") != source:
            raise ValueError("provider_contract_failure: materialized operation")
        if op.get("fallback_policy") != ("add_if_missing" if source == "update" else "none"):
            raise ValueError("provider_contract_failure: fallback policy")
        if not re.search(rf"\bsp_{source}extendedproperty\b", op.get("raw", ""), re.I):
            raise ValueError("provider_contract_failure: source procedure")
        source_operations.append(source)
        expected.append(source)
        if source == "update":
            expected.append("add")
    actual = re.findall(rb"\bEXEC\s+sys\.sp_(add|update|drop)extendedproperty\b", artifact, re.I)
    if [value.decode("ascii").lower() for value in actual] != expected:
        raise ValueError("provider_contract_failure: materialized procedure")
    operation_value = source_operations[0] if len(source_operations) == 1 else source_operations
    body = entry.get("sql", "").encode("utf-8")
    if (entry.get("source_operation") != operation_value
            or entry.get("materialized_operation") != operation_value
            or provenance.get("source_operation") != operation_value
            or provenance.get("materialized_operation") != operation_value
            or provenance.get("fallback_policy") != (
                "add_if_missing" if "update" in source_operations else "none")
            or provenance.get("provider_version") != PROVIDER_VERSION
            or provenance.get("source_input_sha256") != entry.get("repair_hash")
            or provenance.get("input_sha256") != provenance.get("source_input_sha256")
            or provenance.get("materialized_body_sha256") != hashlib.sha256(body).hexdigest()
            or provenance.get("output_sha256") != provenance.get("materialized_body_sha256")
            or entry.get("sql_hash") != hashlib.sha256(body).hexdigest()
            or provenance.get("artifact_sha256") != hashlib.sha256(artifact).hexdigest()
            or artifact != (body if body.endswith(b"\n") else body + b"\n")):
        raise ValueError("provider_contract_failure: descriptor or hash")


def generate_release_artifacts(descriptor_path: Path, repair_root: Path, output_root: Path) -> dict:
    descriptor_path = Path(descriptor_path)
    repair_root = Path(repair_root)
    output_root = Path(output_root)
    source = json.loads(descriptor_path.read_text(encoding="utf-8"))
    units = source.get("units", [])
    if len(units) != 20:
        raise ValueError(f"expected 20 units, got {len(units)}")
    output_root.mkdir(parents=True, exist_ok=True)
    descriptor_output = output_root / "formal-release-unit-descriptors.json"
    previous_units = {}
    if descriptor_output.is_file():
        previous_units = {unit["unit_id"]: unit.get("execution_body")
                          for unit in json.loads(descriptor_output.read_text(encoding="utf-8")).get("units", [])}
    stale_paths = []
    materialized = []
    for item in units:
        if "#5005" in item.get("issues", []):
            unit_id = item["unit_id"]
            stale = output_root / "execution" / f"{unit_id}.sql"
            if (stale.name != f"{unit_id}.sql"
                    or stale.parent.resolve() != (output_root / "execution").resolve()):
                raise ValueError("excluded artifact path is unsafe")
            if stale.exists() or stale.is_symlink():
                if (previous_units.get(unit_id) is None
                        or Path(previous_units[unit_id]) != Path("execution") / f"{unit_id}.sql"
                        or stale.is_symlink() or not stale.is_file()):
                    raise ValueError("excluded artifact is not an owned generated file")
                stale_paths.append(stale)
            continue
        unit_id = item["unit_id"]
        relative = Path(item["repair_source"]).relative_to("repair-source/units")
        repair_path = repair_root / relative
        raw = repair_path.read_text(encoding="utf-8")
        repair_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if item.get("repair_hash") and repair_hash != item["repair_hash"]:
            raise ValueError(f"repair hash mismatch: {unit_id}")
        execution, provenance = transform_provider_sql(
            raw, source_path=item["source_path"], unit_id=unit_id,
            excluded_objects=item.get("excluded_objects", ()))
        body_path = output_root / "execution" / f"{unit_id}.sql"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = (execution if execution.endswith("\n") else execution + "\n").encode("utf-8")
        body_path.write_bytes(artifact)
        entry = {key: item[key] for key in ("unit_id", "phase", "source_path", "source_revision", "source_hash", "source_line", "depends_on")}
        if entry["phase"] not in PHASES:
            raise ValueError(f"unsupported phase: {entry['phase']}")
        missing_contract = [key for key in ("preconditions", "target_definition", "skip_condition", "stop_condition", "validation_queries") if key not in item]
        inferred_dependencies = list(item.get("depends_on", []))
        for prior in materialized:
            if prior["unit_id"] in inferred_dependencies:
                continue
            prior_stem = Path(prior["repair_source"]).stem
            prior_alias = prior_stem[3:] if prior_stem.startswith("EF_") else prior_stem
            if (prior["unit_id"] in raw or f"{prior['unit_id']}.sql" in raw
                    or f"{prior_stem}.sql" in raw or f"{prior_alias}.sql" in raw):
                inferred_dependencies.append(prior["unit_id"])
        entry.update({"complete": True, "sql": execution,
                      "sql_hash": hashlib.sha256(execution.encode("utf-8")).hexdigest(),
                      "repair_source": item["repair_source"], "repair_hash": repair_hash,
                      "depends_on": inferred_dependencies,
                      "original_phase": item["phase"],
                      "mixed_unit": ("CREATE TABLE" in raw.upper() and any(token in raw.upper() for token in ("ALTER TABLE", "INSERT ", "UPDATE ", "DELETE "))),
                      "provider_kind": "metadata" if provenance["metadata_operations"] or any(x.startswith("metadata") for x in provenance["transformations"]) else None,
                      "execution_body": str(body_path.relative_to(output_root)),
                      "provenance": {**provenance, "provider_version": PROVIDER_VERSION,
                                     "baseline_sha": source.get("base_sha"),
                                     "source_revision": item["source_revision"],
                                     "mapping": provenance["transformations"],
                                     "profile": source.get("profile"),
                                     "source_input_sha256": provenance["input_sha256"],
                                     "materialized_body_sha256": provenance["output_sha256"],
                                     "artifact_sha256": hashlib.sha256(artifact).hexdigest()},
                      "preconditions": item.get("preconditions", []),
                      "target_definition": item.get("target_definition", {"sql": execution}),
                      "skip_condition": item.get("skip_condition"),
                      "stop_condition": item.get("stop_condition"),
                      "validation_queries": item.get("validation_queries", []),
                      "descriptor_status": "blocked_missing_contract" if missing_contract else "complete",
                      "missing_contract": missing_contract})
        metadata_ops = provenance["metadata_operations"]
        if metadata_ops:
            source_ops = [op["source_operation"] for op in metadata_ops]
            operation_value = source_ops[0] if len(source_ops) == 1 else source_ops
            entry["source_operation"] = operation_value
            entry["materialized_operation"] = operation_value
            entry["provenance"]["source_operation"] = operation_value
            entry["provenance"]["materialized_operation"] = operation_value
            entry["provenance"]["fallback_policy"] = (
                "add_if_missing" if "update" in source_ops else "none")
            validate_provider_contract(entry, artifact)
        if "dynamic_drop_constraint_provider" in provenance["transformations"]:
            entry["provider_kind"] = "dynamic_ddl"
        materialized.append(entry)
    seen = set()
    by_id = {item["unit_id"]: item for item in materialized}
    for item in materialized:
        if any(by_id.get(dep, {}).get("original_phase") != item["original_phase"] for dep in item["depends_on"]):
            item["mixed_unit"] = True
            item["mixed_unit_reason"] = "dependency chain crosses metadata phases; source order retained"
    for item in materialized:
        unknown = [dep for dep in item["depends_on"] if dep not in seen]
        if unknown:
            raise ValueError(f"dependency is not ordered or missing: {item['unit_id']}: {unknown}")
        seen.add(item["unit_id"])
    result = {"schema_version": 2, "status": "materialized", "base_sha": source.get("base_sha"),
              "target_sha": source.get("target_sha"), "units": materialized}
    for stale in stale_paths:
        stale.unlink()
    descriptor_output.write_text(
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

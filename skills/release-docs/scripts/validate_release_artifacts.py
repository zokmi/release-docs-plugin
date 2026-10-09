"""Validate generated release artifacts without connecting to a database."""
import argparse
import json
import re
from pathlib import Path


REQUIRED = ("00_上線指引.md", "01_結構SQL.sql")
OPTIONAL = ("01_索引調整.sql", "02_資料SQL.sql", "03_例外排除.json", "04_參數異動.md")
REPORT = "05_版更審查報告.md"
ALLOWED = frozenset((*REQUIRED, *OPTIONAL, REPORT))
ARTIFACT_CLASSES = {
    "01_結構SQL.sql": "schema-deployment",
    "01_索引調整.sql": "index-adjustment",
    "02_資料SQL.sql": {"data-migration", "repair-migration", "mixed-ddl-dml"},
    "03_例外排除.json": "exclusion-manifest",
    "04_參數異動.md": "config-change",
}
EXCLUSION_FIELDS = {
    "id", "type", "units", "operator_action", "reason",
    "dependency_impact", "reinstatement_conditions", "evidence",
    "approval", "review",
}


def finding(level, code, message, path=None):
    item = {"level": level, "code": code, "message": message}
    if path:
        item["path"] = path
    return item


def artifact_class(text):
    match = re.search(r"artifact[_ -]?class\s*[:|：]\s*`?([a-z][a-z0-9-]*)", text, re.I)
    return match.group(1) if match else None


def validate(documents):
    documents = Path(documents).resolve()
    findings = []
    if documents.exists():
        for entry in documents.iterdir():
            if entry.name not in ALLOWED:
                findings.append(finding("error", "UNEXPECTED_OUTPUT", "未定義的 release 輸出", entry.name))
    for name in REQUIRED:
        if not (documents / name).is_file():
            findings.append(finding("error", "REQUIRED_MISSING", "必要文件不存在", name))

    for name in (*REQUIRED, *OPTIONAL):
        path = documents / name
        if not path.exists():
            continue
        if not path.is_file():
            findings.append(finding("error", "NOT_FILE", "文件不是一般檔案", name))
            continue
        if name == "03_例外排除.json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                findings.append(finding("error", "INVALID_JSON", str(exc), name))
                continue
            if data.get("schema_version") != 1:
                findings.append(finding("error", "SCHEMA_VERSION", "schema_version 必須為 1", name))
            if data.get("artifact_class") != "exclusion-manifest":
                findings.append(finding("error", "ARTIFACT_CLASS", "artifact_class 必須為 exclusion-manifest", name))
            exclusions = data.get("exclusions")
            if not isinstance(exclusions, list):
                findings.append(finding("error", "EXCLUSIONS_TYPE", "exclusions 必須是陣列", name))
                exclusions = []
            ids = set()
            for index, item in enumerate(exclusions):
                prefix = f"{name}:exclusions[{index}]"
                if not isinstance(item, dict):
                    findings.append(finding("error", "EXCLUSION_TYPE", "排除項目必須是物件", prefix))
                    continue
                missing = sorted(EXCLUSION_FIELDS - set(item))
                if missing:
                    findings.append(finding("error", "EXCLUSION_FIELDS", "缺少欄位：" + ", ".join(missing), prefix))
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id.strip():
                    findings.append(finding("error", "EXCLUSION_ID", "排除 ID 不得為空", prefix))
                elif item_id in ids:
                    findings.append(finding("error", "DUPLICATE_EXCLUSION_ID", "排除 ID 重複：" + item_id, prefix))
                else:
                    ids.add(item_id)
                if item.get("operator_action") not in ("skip", None):
                    findings.append(finding("error", "OPERATOR_ACTION", "operator_action 必須為 skip 或明確受控前置條件", prefix))
        else:
            text = path.read_text(encoding="utf-8")
            if name == "00_上線指引.md":
                continue  # Guide has no SQL/config artifact class.
            expected = ARTIFACT_CLASSES[name]
            actual = artifact_class(text)
            allowed = expected if isinstance(expected, set) else {expected}
            if actual not in allowed:
                findings.append(finding("error", "ARTIFACT_CLASS", f"artifact class 必須是 {sorted(allowed)}", name))
            if name.endswith(".sql") and "{{" in text:
                findings.append(finding("error", "UNFILLED_TEMPLATE", "SQL 仍含未填模板欄位", name))
            if name == "01_索引調整.sql":
                for marker in ("sys.indexes", "ValidateOnly", "XACT_ABORT"):
                    if marker not in text:
                        findings.append(finding("error", "INDEX_CONTRACT", f"索引調整 SQL 缺少 {marker}", name))
            if name == "04_參數異動.md" and "設定 ID" not in text:
                findings.append(finding("error", "CONFIG_SCHEMA", "缺少設定 ID 欄位", name))

    status = "未通過" if any(item["level"] == "error" for item in findings) else "通過"
    return {"schema_version": 1, "status": status, "documents": str(documents), "findings": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", required=True)
    args = parser.parse_args()
    result = validate(args.documents)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["status"] == "未通過" else 0)


if __name__ == "__main__":
    main()

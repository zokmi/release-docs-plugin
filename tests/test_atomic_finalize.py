import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).parents[1] / "skills/release-docs-review/scripts/validate_release_output.py"
SPEC = importlib.util.spec_from_file_location("atomic_finalize_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_atomic_report_replace_writes_complete_document(tmp_path):
    report = tmp_path / "05_review.md"
    MODULE._atomic_write_text(report, "new report\n")
    assert report.read_text(encoding="utf-8") == "new report\n"
    assert list(tmp_path.glob("05_review.md.*.tmp")) == []


def test_atomic_report_replace_preserves_previous_report_on_replace_failure(tmp_path):
    report = tmp_path / "05_review.md"
    report.write_text("old report\n", encoding="utf-8")
    with patch.object(MODULE.os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError):
            MODULE._atomic_write_text(report, "new report\n")
    assert report.read_text(encoding="utf-8") == "old report\n"
    assert list(tmp_path.glob("05_review.md.*.tmp")) == []


@pytest.mark.parametrize("finding", [
    {"code": "formal_rows_unavailable", "domain": "business_data_validation", "blocking": True},
])
def test_business_data_findings_are_nonblocking_and_do_not_lower_sql_status(finding):
    result = MODULE._summary([finding], semantic_complete=True)
    business = next(item for item in result if item["domain"] == "business_data_validation")
    assert business["blocking"] is False
    assert next(item for item in result if item["code"] == "sql_content_status")["status"] == "通過"
    assert not any(item["code"] == "semantic_review_pending" for item in result)


def test_sql_correctness_finding_remains_blocking():
    result = MODULE._summary([{"code": "opaque_execution", "domain": "sql_correctness", "blocking": True}],
                             semantic_complete=True)
    assert next(item for item in result if item["code"] == "sql_content_status")["status"] == "未通過"


def test_sql_defect_cannot_be_relabelled_as_business_data():
    result = MODULE._summary([{"code": "opaque_execution", "domain": "business_data_validation",
                               "blocking": True}], semantic_complete=True)
    assert next(item for item in result if item["code"] == "sql_content_status")["status"] == "未通過"

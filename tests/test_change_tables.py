from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from render_release_documents import _change_tables  # noqa: E402


def test_structure_and_data_tables_are_always_present_and_exclude_units():
    analysis = SimpleNamespace(
        structure_changes=[{"unit_id": "s1", "name": "dbo.T.c", "kind": "column",
                            "before_after": "NULL → NOT NULL", "impact": "required",
                            "preservation": "existing rows checked", "source_location": "x.sql:4"},
                            {"unit_id": "x", "name": "dbo.Secret", "kind": "table"}],
        data_changes=[{"unit_id": "d1", "object": "dbo.T", "operation_condition": "UPDATE when null",
                       "before_after": "NULL → 0", "preservation": "other rows retained",
                       "validation": "count", "source_location": "d.sql:8"}],
    )
    structure, data = _change_tables(analysis, {"x"})
    assert "dbo.T.c" in structure and "dbo.Secret" not in structure
    assert "dbo.T" in data and "資料對象" in data


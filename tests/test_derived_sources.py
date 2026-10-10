from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from derived_sources import register_derived_source, verify_source  # noqa: E402


def _run(tmp_path):
    root = tmp_path / ".release-docs" / "runs" / "r1"
    root.mkdir(parents=True)
    return root


def _provenance():
    return {"scope": {"base_sha": "a" * 40, "target_sha": "b" * 40},
            "baseline_sha256": "c" * 64, "inputs": [{"path": "x.sql", "revision": "b" * 40, "sha256": "d" * 64}],
            "method": "test", "tool": {"name": "tool", "version": "1"}, "mapping": [{"unit_id": "u1"}]}


def test_derived_bytes_do_not_require_git_commit(tmp_path):
    run = _run(tmp_path)
    record = register_derived_source(run, b"select 1;", _provenance())
    assert verify_source(tmp_path, run, record, _provenance()["scope"]) == b"select 1;"


def test_mutated_output_rejected(tmp_path):
    run = _run(tmp_path)
    record = register_derived_source(run, b"select 1;", _provenance())
    (run / record["path"]).write_bytes(b"select 2;")
    with pytest.raises(ValueError, match="hash"):
        verify_source(tmp_path, run, record, _provenance()["scope"])


def test_unknown_type_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        verify_source(tmp_path, _run(tmp_path), {"source_type": "remote"}, _provenance()["scope"])

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs/scripts'))
from analyze_release_units import AnalysisResult, analyze_release_units
from lifecycle_store import write_lifecycle_run


def test_analysis_metadata_roundtrip_masks_secrets(tmp_path):
    analysis = AnalysisResult()
    analysis.structure_changes = [{'unit_id': 'one', 'kind': 'table', 'name': 'dbo.One',
                                   'description': '建立', 'impact': '查詢'}]
    analysis.parameters_applicable = True
    analysis.parameter_changes = [{'environment': 'test', 'service': 'api', 'key': 'Token',
                                   'new_value': 'sensitive-value', 'format_example': 'sensitive-value',
                                   'apply': 'set sensitive-value', 'reload': 'restart', 'validation': 'health'}]
    manifest = write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis)
    raw = (manifest.parent / 'source_unit_metadata.json').read_text()
    saved = json.loads(raw)
    assert saved['structure_changes'] == analysis.structure_changes
    assert saved['parameters_applicable'] is True
    assert 'sensitive-value' not in raw
    assert 'new_value' not in raw
    assert '[REDACTED]' in saved['parameter_changes'][0]['apply']


def test_unknown_parameter_applicability_is_persisted(tmp_path):
    analysis = AnalysisResult()
    manifest = write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis)
    saved = json.loads((manifest.parent / 'source_unit_metadata.json').read_text())
    assert saved['parameters_applicable'] is None


def test_parameter_contract_conflict_is_rejected_before_write(tmp_path):
    analysis = AnalysisResult()
    analysis.parameters_applicable = True
    with pytest.raises(ValueError, match='applicability'):
        write_lifecycle_run(tmp_path / '.release-docs/runs/one', analysis,
                            operator_contract={'parameters_applicable': False})
    assert not (tmp_path / '.release-docs/runs/one').exists()


def test_scope_decisions_survive_analysis(tmp_path):
    baseline = tmp_path / 'baseline.sql'
    baseline.write_text('')
    scope = {'base_sha': 'a' * 40, 'target_sha': 'b' * 40, 'requested_base_sha': 'c' * 40,
             'diff_base_sha': 'a' * 40, 'diff_mode': 'merge-base', 'workspace_policy': 'excluded'}
    result = analyze_release_units(tmp_path, scope, baseline, None)
    assert result.source_scope == scope


def test_path_helper_supports_missing_junction_api():
    from path_safety import is_linked_path
    class LegacyPath:
        def is_symlink(self): return False
        def exists(self): return False
    assert is_linked_path(LegacyPath()) is False


def test_path_helper_rejects_reparse():
    from path_safety import is_linked_path
    class ReparsePath:
        def is_symlink(self): return False
        def exists(self): return True
        def stat(self):
            return type('Info', (), {'st_file_attributes': 1024})()
    assert is_linked_path(ReparsePath()) is True

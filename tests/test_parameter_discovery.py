import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from parameter_discovery import discover_parameter_changes


def source(content, **metadata):
    return {"path": "appsettings.json", "revision": "pinned", "content": content,
            "environment": "Production", "service": "CustomerAPI", **metadata}


def test_discovers_nested_json_add_update_remove_and_preserves_sources():
    base = [source('{"Cache":{"TTL":60,"Enabled":true},"Gone":1}')]
    target = [source('{"Cache":{"TTL":120,"Enabled":false},"New":null}')]

    result = discover_parameter_changes(base, target)

    assert [(item["key"], item["change"]) for item in result.changes] == [
        ("Cache:Enabled", "update"), ("Cache:TTL", "update"),
        ("Gone", "remove"), ("New", "add")]
    assert result.changes[0]["old_value"] is True
    assert result.changes[0]["new_value"] is False
    assert "new_value" not in result.changes[2]
    assert "old_value" not in result.changes[3]
    assert result.changes[3]["new_value"] is None
    assert result.changes[0]["source_reference"]["target"] == target[0]
    assert result.applicable is True


def test_array_indices_and_zero_are_not_treated_as_missing():
    result = discover_parameter_changes(
        [source('{"Endpoints":[{"Url":"old","Weight":0}]}')],
        [source('{"Endpoints":[{"Url":"new","Weight":1}]}')])
    assert [item["key"] for item in result.changes] == ["Endpoints:0:Url", "Endpoints:0:Weight"]
    assert result.changes[1]["old_value"] == 0


def test_no_change_retains_checked_source_evidence_and_is_not_applicable():
    base = [source('{"A":1}')]
    result = discover_parameter_changes(base, [source('{"A":1}')])
    assert result.changes == []
    assert result.applicable is False
    assert result.checked_sources


def test_environment_double_underscore_maps_to_nested_key_without_inventing_scope():
    result = discover_parameter_changes(
        [], [], deployment_sources=[{"path": "deployment.yaml", "revision": "pinned",
                                    "environment_variables": {"Foo__Bar": "value"}}])
    assert result.changes
    assert result.changes[0]["key"] == "Foo:Bar"
    assert result.applicable is None
    assert any(finding.get("blocking") for finding in result.findings)


def test_config_change_with_missing_environment_or_service_is_blocked():
    result = discover_parameter_changes(
        [source('{"A":1}', environment=None, service=None)],
        [source('{"A":2}', environment=None, service=None)])
    assert len(result.changes) == 1
    assert "environment" in result.findings[0]["missing"]
    assert "service" in result.findings[0]["missing"]
    assert result.applicable is None


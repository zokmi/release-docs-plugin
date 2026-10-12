import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from parameter_discovery import discover_parameter_changes


def source(content, **metadata):
    return {"path": "appsettings.json", "revision": "pinned", "content": content,
            "environment": "Production", "service": "CustomerAPI", **metadata}


def test_discovery_preserves_complete_target_array_context():
    result = discover_parameter_changes([source({"Items": ["old", "keep"]})],
                                        [source({"Items": ["new", "keep"]})])
    assert len(result.changes) == 1
    assert result.changes[0]["target_config"] == {"Items": ["new", "keep"]}


def test_discovery_preserves_numeric_object_key_shape():
    result = discover_parameter_changes([source({"Items": {"0": "old"}})],
                                        [source({"Items": {"0": "new"}})])
    assert result.changes[0]["target_config"] == {"Items": {"0": "new"}}


def test_removed_source_has_no_synthetic_root_addition():
    result = discover_parameter_changes([source({"Items": ["old", "keep"]})], [])
    assert [(item["key"], item["change"]) for item in result.changes] == [
        ("Items:0", "remove"), ("Items:1", "remove")]
    assert all(item["target_config"] == {} for item in result.changes)


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
    assert result.changes == []
    assert result.applicable is None
    assert any(finding.get("blocking") and finding.get("key") == "Foo:Bar"
               for finding in result.findings)


def test_config_change_with_missing_environment_or_service_is_blocked():
    result = discover_parameter_changes(
        [source('{"A":1}', environment=None, service=None)],
        [source('{"A":2}', environment=None, service=None)])
    assert len(result.changes) == 1
    assert "environment" in result.findings[0]["missing"]
    assert "service" in result.findings[0]["missing"]
    assert result.applicable is None


def test_boolean_and_number_transitions_are_distinct_json_changes():
    result = discover_parameter_changes([source('{"Value":false}')],
                                        [source('{"Value":0}')])
    assert len(result.changes) == 1
    assert result.changes[0]["change"] == "update"
    assert result.changes[0]["old_value"] is False
    assert result.changes[0]["new_value"] == 0
    assert type(result.changes[0]["new_value"]) is int


def test_missing_source_content_is_blocking_and_not_a_no_change_result():
    result = discover_parameter_changes([{"path": "appsettings.json", "revision": "base"}],
                                        [source('{"A":1}')])
    assert result.applicable is None
    assert any(finding.get("blocking") for finding in result.findings)


def test_empty_objects_and_arrays_are_preserved_as_container_changes():
    result = discover_parameter_changes([source('{"Object":{},"Array":[]}')],
                                        [source('{"Object":{"A":1},"Array":[1]}')])
    assert [(change["key"], change["change"]) for change in result.changes] == [
        ("Array", "remove"), ("Array:0", "add"), ("Object", "remove"), ("Object:A", "add")]


def test_environment_mapping_does_not_claim_an_unsupported_addition():
    result = discover_parameter_changes(
        [], [], deployment_sources=[{"path": "deployment.yaml", "revision": "pinned",
                                    "environment_variables": {"Foo__Bar": "value"}}])
    assert result.changes == []
    assert result.applicable is None
    assert any(finding.get("blocking") and finding.get("key") == "Foo:Bar"
               for finding in result.findings)


def test_conflicting_consumer_scopes_are_blocked_instead_of_order_dependent():
    consumers = [{"path": "appsettings.json", "environment": "Production", "service": "API"},
                 {"path": "appsettings.json", "environment": "Staging", "service": "Worker"}]
    result = discover_parameter_changes([source('{"A":1}', environment=None, service=None)],
                                        [source('{"A":2}', environment=None, service=None)],
                                        consumer_sources=consumers)
    assert result.changes[0]["environment"] is None
    assert result.changes[0]["service"] is None
    assert result.applicable is None
    assert any(finding.get("blocking") and "scope" in finding.get("missing", [])
               for finding in result.findings)


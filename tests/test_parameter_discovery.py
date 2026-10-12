import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from parameter_discovery import discover_parameter_changes


def source(content, **metadata):
    return {"path": "appsettings.json", "revision": "pinned", "content": content,
            "environment": "Production", "service": "CustomerAPI", **metadata}


@pytest.mark.parametrize('role', ['base', 'target'])
@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_source_paths_block_instead_of_last_wins(role, reverse):
    duplicates = [source({'A': 2}), source({'A': 1})]
    if reverse:
        duplicates.reverse()
    result = discover_parameter_changes(
        duplicates if role == 'base' else [source({'A': 1})],
        duplicates if role == 'target' else [source({'A': 1})])
    assert result.applicable is None
    assert not result.changes
    assert any(item['blocking'] for item in result.findings)


def test_qualified_xml_configuration_is_not_a_standard_source():
    xml = '<configuration xmlns="urn:custom"><appSettings><add key="Foo" value="bar"/></appSettings></configuration>'
    result = discover_parameter_changes([], [source(xml, path='Web.config')])
    assert result.applicable is None
    assert not result.changes
    assert any(item['blocking'] for item in result.findings)


def test_equal_leaves_do_not_hide_array_object_type_changes():
    for before, after in ((["same"], {"0": "same"}), ({"0": "same"}, ["same"])):
        result = discover_parameter_changes([source({"Items": before})],
                                            [source({"Items": after})])
        assert result.applicable is True
        assert [(item['key'], item['change']) for item in result.changes] == [('Items', 'update')]
        assert result.changes[0]['target_config'] == {'Items': after}


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


@pytest.mark.parametrize('document,segments,fragment', [
    ({'A:B': 'new'}, ['A:B'], {'A:B': 'new'}),
    ({'A': [{'B:C': 'new'}, 'keep']}, ['A', 0, 'B:C'],
     {'A': [{'B:C': 'new'}, 'keep']}),
    ({'A': {'0': 'new'}}, ['A', '0'], {'A': {'0': 'new'}}),
])
def test_physical_segments_preserve_literal_keys_and_array_context(document, segments, fragment):
    result = discover_parameter_changes([], [source(document)])
    change = next(item for item in result.changes if item.get('new_value') == 'new')
    assert change['key_segments'] == segments
    assert change['target_config'] == fragment
    assert change['configuration_provider'] == 'json'


@pytest.mark.parametrize('content', [
    '{"A:B":1,"A":{"B":1}}', '{"A":1,"a":1}',
    '{"A":1,"A":1}', '{"A:B":{},"a":{"b":{}}}',
])
def test_duplicate_logical_keys_block_even_identical_sources(content):
    result = discover_parameter_changes([source(content)], [source(content)])
    assert result.applicable is None
    assert result.changes == []
    assert any(item['blocking'] for item in result.findings)


def test_xml_literal_settings_connections_and_pinned_references():
    target = source('<configuration><appSettings>'
                    '<add key="A:B" value="new"/></appSettings>'
                    '<connectionStrings><add name="Main" connectionString="db" providerName="sql"/>'
                    '</connectionStrings></configuration>', path='Web.config', source_hash='pinned-hash')
    result = discover_parameter_changes([], [target])
    assert result.applicable is True
    assert [(item['key'], item['key_segments'], item['target_config']) for item in result.changes] == [
        ('A:B', ['A:B'], {'A:B': 'new'}),
        ('ConnectionStrings:Main:ConnectionString', ['ConnectionStrings', 'Main', 'ConnectionString'],
         {'ConnectionStrings': {'Main': {'ConnectionString': 'db'}}}),
        ('ConnectionStrings:Main:ProviderName', ['ConnectionStrings', 'Main', 'ProviderName'],
         {'ConnectionStrings': {'Main': {'ProviderName': 'sql'}}})]
    assert all(item['configuration_provider'] == 'xml' for item in result.changes)
    assert result.changes[0]['source_reference']['target'] == target


@pytest.mark.parametrize('xml', [
    '<wrong/>', '<configuration><custom/></configuration>',
    '<!DOCTYPE configuration [<!ENTITY x "secret">]><configuration/>',
    '<configuration><appSettings configSource="external.config"/></configuration>',
    '<configuration><appSettings file="external.config"/></configuration>',
    '<configuration><appSettings><add key="A" value="1"/><add key="A" value="1"/></appSettings></configuration>',
    '<configuration><appSettings><remove key="inherited"/></appSettings></configuration>',
])
def test_unsupported_xml_is_blocked_instead_of_no_change(xml):
    result = discover_parameter_changes([source(xml, path='Web.config')], [source(xml, path='Web.config')])
    assert result.applicable is None
    assert any(item['blocking'] for item in result.findings)


@pytest.mark.parametrize('operations', [
    '<clear/>',
    '<add key="A" value="1"/><remove key="A"/>',
    '<clear/><add key="A" value="1"/><remove key="A"/><add key="A" value="2"/>',
])
def test_shared_parser_rejects_xml_inheritance_operations(operations):
    from parameter_discovery import parse_configuration_source
    with pytest.raises(ValueError, match='inherit'):
        parse_configuration_source(source('<configuration><appSettings>' + operations +
            '</appSettings></configuration>', path='Web.config'))


@pytest.mark.parametrize('section,key_attr,value_attr', [
    ('appSettings', 'key', 'value'),
    ('connectionStrings', 'name', 'connectionString'),
])
@pytest.mark.parametrize('operation', ['<clear/>', '<remove {key_attr}="A"/>'])
def test_xml_inheritance_changes_block_instead_of_claiming_no_change(section, key_attr, value_attr, operation):
    add = f'<add {key_attr}="A" {value_attr}="same"/>'
    base = f'<configuration><{section}>{add}</{section}></configuration>'
    operations = (operation + add if operation == '<clear/>' else
                  add + operation.format(key_attr=key_attr) + add)
    target = f'<configuration><{section}>{operations}</{section}></configuration>'
    result = discover_parameter_changes([source(base, path='Web.config')],
                                        [source(target, path='Web.config')])
    assert result.applicable is None
    assert result.changes == []
    assert any(item['blocking'] and 'inherit' in item['message'] for item in result.findings)


def test_physical_alias_change_between_versions_is_blocked():
    result = discover_parameter_changes([source({'A:B': 1})], [source({'A': {'B': 1}})])
    assert result.applicable is None
    assert result.changes == []
    assert any(item['blocking'] for item in result.findings)


@pytest.mark.parametrize('sections', [
    '<connectionStrings><add name="Main" connectionString="db"/></connectionStrings>'
    '<appSettings><add key="ConnectionStrings" value="lost"/></appSettings>',
    '<appSettings><add key="ConnectionStrings" value="lost"/></appSettings>'
    '<connectionStrings><add name="Main" connectionString="db"/></connectionStrings>',
])
def test_xml_section_mapping_never_overwrites_existing_keys(sections):
    result = discover_parameter_changes([], [source('<configuration>' + sections + '</configuration>', path='Web.config')])
    assert result.applicable is None
    assert result.changes == []


@pytest.mark.parametrize('before_provider,after_provider,kind', [
    ('sql', 'other', 'update'), ('sql', None, 'remove'), (None, 'sql', 'add'),
])
def test_xml_provider_only_changes_are_discovered(before_provider, after_provider, kind):
    def config(provider):
        attribute = '' if provider is None else f' providerName="{provider}"'
        return source('<configuration><connectionStrings><add name="Main" '
                      f'connectionString="same"{attribute}/></connectionStrings></configuration>',
                      path='Web.config')
    result = discover_parameter_changes([config(before_provider)], [config(after_provider)])
    assert result.applicable is True
    assert [(item['key'], item['change']) for item in result.changes] == [
        ('ConnectionStrings:Main:ProviderName', kind)]


@pytest.mark.parametrize('content,path', [({}, 'appsettings.json'), ('<configuration/>', 'Web.config')])
@pytest.mark.parametrize('role', ['base', 'target'])
def test_empty_root_sources_do_not_generate_synthetic_changes(content, path, role):
    pinned = source(content, path=path)
    result = discover_parameter_changes([pinned] if role == 'base' else [],
                                        [pinned] if role == 'target' else [])
    assert result.changes == []
    assert result.applicable is False
    assert result.checked_sources == [dict(role=role, **pinned)]


def test_shared_xml_parser_retains_connection_entry_attributes():
    from parameter_discovery import parse_configuration_source
    assert parse_configuration_source(source('<configuration><connectionStrings>'
        '<add name="With" connectionString="db" providerName=""/>'
        '<add name="Without" connectionString="db2"/>'
        '</connectionStrings></configuration>', path='Web.config')) == {
            'ConnectionStrings': {'With': {'ConnectionString': 'db', 'ProviderName': ''},
                                  'Without': {'ConnectionString': 'db2'}}}


@pytest.mark.parametrize('unchanged', [False, True])
def test_reviewed_deployment_helper_changes_join_discovery(unchanged):
    reference = {'path': '.env', 'revision': 'pinned', 'source_hash': 'hash'}
    deployment = {'path': '.env', 'environment': 'Production', 'service': 'API',
        'base_environment_variables': {'Foo__Bar': 'same' if unchanged else 'old'},
        'environment_variables': {'Foo__Bar': 'same'},
        'source_reference': {'base': reference, 'target': reference},
        'provider_precedence': {'conclusion': 'passed', 'reason': 'reviewed',
                                'source_reference': reference}}
    result = discover_parameter_changes([], [], deployment_sources=[deployment])
    assert result.applicable is (False if unchanged else True)
    assert result.findings == []
    if unchanged:
        assert result.changes == []
    else:
        assert [(item['key'], item['old_value'], item['new_value']) for item in result.changes] == [
            ('Foo:Bar', 'old', 'same')]
        assert result.changes[0]['configuration_provider'] == 'environment'


def test_unsupported_deployment_without_variables_still_blocks():
    result = discover_parameter_changes([], [], deployment_sources=[{'path': 'unknown.yaml'}])
    assert result.applicable is None
    assert any(item['blocking'] for item in result.findings)


"""Behavior checks for bounded, literal deployment evidence (no mocks)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/release-docs/scripts'))


def api():
    import deployment_parameters
    return deployment_parameters


@pytest.mark.parametrize('extends', [None, {}, {'file': 'external.json', 'service': 'base'}])
def test_compose_inherited_configuration_is_not_treated_as_complete(extends):
    import json
    content = json.dumps({'services': {'api': {
        'extends': extends, 'environment': {'Foo__Bar': 'literal'}}}})
    with pytest.raises(ValueError):
        api().parse_deployment_source({'path': 'compose.json', 'service': 'api', 'content': content})


def source(**overrides):
    return dict(path='.env.production', environment='Production', service='API',
                base_environment_variables={'Cache__TTL': '60', 'Gone__Key': 'old'},
                environment_variables={'Cache__TTL': '120', 'New__Key': 'new'},
                source_reference={'base': {'path': '.env.production', 'revision': 'base', 'source_hash': 'a'},
                                  'target': {'path': '.env.production', 'revision': 'target', 'source_hash': 'b'}},
                provider_precedence={'conclusion': 'passed', 'reason': 'Reviewed provider ordering',
                                     'source_reference': {'path': 'Program.cs', 'revision': 'target', 'source_hash': 'c'}},
                **{}) | overrides


def test_add_update_remove_preserve_values_hierarchy_and_proof():
    result = api().discover_deployment_changes([source()])
    assert not result.findings
    assert [(c['key'], c['change']) for c in result.changes] == [
        ('Cache:TTL', 'update'), ('Gone:Key', 'remove'), ('New:Key', 'add')]
    update, removed, added = result.changes
    assert update['old_value'] == '60' and update['new_value'] == '120'
    assert update['target_config'] == {'Cache': {'TTL': '120'}}
    assert update['key_segments'] == ['Cache', 'TTL']
    assert update['environment_variable'] == 'Cache__TTL'
    assert update['configuration_provider'] == 'environment'
    assert update['provider_precedence'] == source()['provider_precedence']
    assert update['source_reference'] == source()['source_reference']
    assert removed['target_config'] == {} and 'new_value' not in removed
    assert 'old_value' not in added


def test_known_absent_and_no_change():
    s = source(base_environment_variables={}, source_reference={'base': None, 'target': source()['source_reference']['target']})
    assert all(c['change'] == 'add' for c in api().discover_deployment_changes([s]).changes)
    s['base_environment_variables'] = s['environment_variables'].copy()
    assert api().discover_deployment_changes([s]).changes == []


@pytest.mark.parametrize('override', [
    {'provider_precedence': None}, {'provider_precedence': True},
    {'provider_precedence': {'conclusion': 'passed', 'reason': 'yes'}},
    {'base_environment_variables': None}, {'environment': None},
    {'environment_variables': {'Foo__Bar': 'x', 'foo__bar': 'y'}},
    {'environment_variables': {'Foo__Bar': 'x', 'Foo__Bar__Baz': 'y'}},
    {'environment_variables': {'Foo__Bar': '${SECRET}'}},
])
def test_unverified_or_ambiguous_evidence_blocks(override):
    result = api().discover_deployment_changes([source(**override)])
    assert result.changes == []
    assert any(f['blocking'] for f in result.findings)


def test_consumer_scope_resolves_without_guessing():
    result = api().discover_deployment_changes([source(environment=None, service=None)],
        [{'path': '.env.production', 'environment': 'Production', 'service': 'API'}])
    assert not result.findings
    assert result.changes[0]['service'] == 'API'


@pytest.mark.parametrize('path,content,want', [
    ('.env.production', b'export Foo__Bar="hello world"\nPlain=x\nEmpty__Key=\n', {'Foo__Bar': 'hello world', 'Empty__Key': ''}),
    ('env.json', '{"Foo__Bar":"literal"}', {'Foo__Bar': 'literal'}),
    ('compose.json', '{"services":{"api":{"environment":["Foo__Bar=x"]}}}', {'Foo__Bar': 'x'}),
    ('compose.json', '{"services":{"api":{"environment":{"Foo__Bar":"x"}}}}', {'Foo__Bar': 'x'}),
    ('pod.json', '{"spec":{"containers":[{"name":"api","env":[{"name":"Foo__Bar","value":"x"}]}]}}', {'Foo__Bar': 'x'}),
    ('deploy.json', '{"spec":{"template":{"spec":{"containers":[{"name":"api","env":[{"name":"Foo__Bar","value":"x"}]}]}}}}', {'Foo__Bar': 'x'}),
])
def test_supported_pinned_literal_formats(path, content, want):
    assert api().parse_deployment_source({'path': path, 'content': content}) == want


@pytest.mark.parametrize('path,content', [
    ('deployment.yaml', 'env:\n  Foo__Bar: x'),
    ('.env', 'Foo__Bar=${SECRET}'), ('.env', 'Foo__Bar=$(whoami)'),
    ('.env', 'Foo__Bar=`whoami`'), ('.env', 'Foo__Bar="unterminated'),
    ('.env', 'Foo__Bar=x\nFoo__Bar=y'), ('.env', 'bad command'),
    ('env.json', '{"Foo__Bar":"x","Foo__Bar":"y"}'),
    ('env.json', '{"Foo__Bar":null}'), ('env.json', '{"unknown":{"env":[]}}'),
    ('pod.json', '{"spec":{"containers":[{"env":[{"name":"Foo__Bar","valueFrom":{}}]}]}}'),
    ('compose.json', '{"services":{"a":{"environment":{}},"b":{"environment":{}}}}'),
])
def test_unsafe_syntax_and_unknown_shapes_are_unresolved(path, content):
    with pytest.raises(ValueError):
        api().parse_deployment_source({'path': path, 'bytes': content})


def test_secret_literal_stays_in_memory_and_errors_do_not_echo_it(capsys):
    secret = 'private-literal-93821'
    assert api().parse_deployment_source({'path': '.env', 'content': 'Secret__Token=' + secret}) == {'Secret__Token': secret}
    with pytest.raises(ValueError) as exc:
        api().parse_deployment_source({'path': '.env', 'content': 'Secret__Token="' + secret})
    assert secret not in str(exc.value)
    assert capsys.readouterr() == ('', '')


def test_case_aliases_on_shared_ancestors_block():
    result = api().discover_deployment_changes([source(environment_variables={'Foo__A': 'x', 'foo__B': 'y'})])
    assert result.changes == [] and result.findings[0]['blocking']


def test_explicit_compose_service_selection():
    content = '{"services":{"a":{"environment":{"Foo__Bar":"a"}},"b":{"environment":{"Foo__Bar":"b"}}}}'
    assert api().parse_deployment_source({'path': 'compose.json', 'content': content, 'service': 'b'}) == {'Foo__Bar': 'b'}


def test_missing_baseline_is_not_known_absent():
    s = source()
    del s['base_environment_variables']
    result = api().discover_deployment_changes([s])
    assert not result.changes and result.findings[0]['blocking']


def test_consumer_scope_conflicts_block():
    result = api().discover_deployment_changes([source()], [{'path': '.env.production', 'environment': 'Staging'}])
    assert not result.changes and result.findings[0]['blocking']


@pytest.mark.parametrize('external', [None, [], '', 'external.env'])
def test_selected_compose_owner_env_file_is_rejected_even_when_empty(external):
    import json
    content = json.dumps({'services': {'api': {'environment': {}, 'env_file': external}}})
    with pytest.raises(ValueError):
        api().parse_deployment_source({'path': 'compose.json', 'content': content})


@pytest.mark.parametrize('external', [None, [], [{'secretRef': {'name': 'private-source'}}]])
@pytest.mark.parametrize('deployment', [False, True])
def test_selected_kubernetes_owner_env_from_is_rejected(external, deployment):
    import json
    spec = {'containers': [{'name': 'api', 'env': [], 'envFrom': external}]}
    if deployment:
        spec = {'template': {'spec': spec}}
    with pytest.raises(ValueError) as error:
        api().parse_deployment_source({'path': 'pod.json', 'content': json.dumps({'spec': spec})})
    assert 'private-source' not in str(error.value)


def test_unselected_owner_external_sources_do_not_block_literal_selected_owner():
    import json
    compose = {'services': {'api': {'environment': {'Foo__Bar': 'literal'}},
                            'other': {'environment': {}, 'env_file': 'external.env'}}}
    pod = {'spec': {'containers': [
        {'name': 'api', 'env': [{'name': 'Foo__Bar', 'value': 'literal'}]},
        {'name': 'other', 'env': [], 'envFrom': [{'secretRef': {'name': 'external'}}]}]}}
    for path, document in [('compose.json', compose), ('pod.json', pod)]:
        assert api().parse_deployment_source({'path': path, 'content': json.dumps(document),
                                              'service': 'api'}) == {'Foo__Bar': 'literal'}

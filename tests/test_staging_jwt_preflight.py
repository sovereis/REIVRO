"""Offline harness tests only. Fake HTTP replies are not hosted JWT evidence."""
import importlib.util
from pathlib import Path
from copy import deepcopy

import pytest

SPEC = importlib.util.spec_from_file_location('jwt_preflight', Path(__file__).parents[1] / 'ops/vercel-pilot/staging/jwt_preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
USER = '00000000-0000-4000-8000-000000000001'
ENV = {'REIVRO_STAGING_REF': preflight.STAGING, 'REIVRO_PUBLISHABLE_KEY': 'sb_publishable_fixture',
       'REIVRO_VALIDATION_JWT': 'header.payload.signature'}


def manifest(role='reviewer'):
    return {'version': 1, 'staging': preflight.STAGING, 'role': role, 'user_id': USER,
            'legacy': {'a': {'repository_id': 101, 'run_id': USER},
                       'b': {'repository_id': 102, 'run_id': USER}},
            'tasks': {name: {'repository_id': 102 if name == 'b' else 101,
                             'submission_id': f'00000000-0000-4000-8000-{i:012d}',
                             'head_sha': 'a'*40, 'digest': 'b'*64}
                      for i, name in enumerate(('a_own', 'a_other', 'b'), start=1)}}


class FakeHTTP:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        assert self.replies, 'Unexpected HTTP call'
        return self.replies.pop(0)


def auth():
    return 200, {'id': USER, 'role': 'authenticated', 'is_anonymous': False}


@pytest.mark.parametrize('role', preflight.ROLES)
def test_auth_scope_does_not_claim_authorization(role):
    http = FakeHTTP([auth()])
    report = preflight.run(ENV, manifest(role), role, 'auth', http)
    assert report['scope'] == 'auth' and report['checks'] == 1
    assert report['full_authorization_matrix'] == 'NOT_VALIDATED'
    assert report['private_alpha'] == 'BLOCKED'
    assert len(http.calls) == 1


@pytest.mark.parametrize('role', preflight.ROLES)
def test_legacy_fixed_matrix(role):
    data = manifest(role)
    replies = [auth()] + [(200, {'run': {'id': USER}} if allowed else None)
                          for allowed in preflight.LEGACY_ACCESS[role]]
    http = FakeHTTP(replies)
    assert preflight.run(ENV, data, role, 'legacy-read', http)['checks'] == 3
    assert all(path.endswith('read_run') for _, path, _ in http.calls[1:])


@pytest.mark.parametrize('role', preflight.ROLES)
def test_tasks_fixed_matrix(role):
    data = manifest(role)
    replies = [auth()]
    for name, allowed in zip(('a_own', 'a_other', 'b'), preflight.TASK_ACCESS[role]):
        item = data['tasks'][name]
        replies.append((200, {'id': item['submission_id'], 'head_sha': item['head_sha'], 'digest': item['digest']})
                       if allowed else (403, {'code': '42501'}))
    http = FakeHTTP(replies)
    assert preflight.run(ENV, data, role, 'task-read', http)['checks'] == 4
    assert all(payload['action'] == 'read' for _, _, payload in http.calls[1:])


@pytest.mark.parametrize('status', (401, 404, 405, 429, 503))
def test_transport_or_schema_failure_not_authorization_success(status):
    with pytest.raises(preflight.Blocked):
        preflight.run(ENV, manifest('no-membership'), 'no-membership', 'task-read',
                      FakeHTTP([auth(), (status, {'code': '42501'})]))


@pytest.mark.parametrize('response', ((200, {}), (403, {'code': 'PGRST999'}), (400, {'code': '42501'})))
def test_wrong_denial_not_success(response):
    with pytest.raises(preflight.Failed):
        preflight.run(ENV, manifest('no-membership'), 'no-membership', 'task-read', FakeHTTP([auth(), response]))


def test_invalid_auth_not_counted_as_rls_denial():
    with pytest.raises(preflight.Blocked):
        preflight.run(ENV, manifest(), 'reviewer', 'legacy-read', FakeHTTP([(401, {})]))


def test_user_mismatch():
    with pytest.raises(preflight.Failed):
        preflight.run(ENV, manifest(), 'reviewer', 'auth', FakeHTTP([(200, {'id': '00000000-0000-4000-8000-000000000099', 'role': 'authenticated', 'is_anonymous': False})]))


@pytest.mark.parametrize('change', ({'REIVRO_STAGING_REF': 'hnlmnswotenppgdqxvkv'},
                                    {'REIVRO_PUBLISHABLE_KEY': ''},
                                    {'REIVRO_VALIDATION_JWT': ''},
                                    {'REIVRO_REVIEWER_JWT': 'other-token'},
                                    {'REIVRO_STAGING_AUTH_ADMIN_KEY': 'fixture'},
                                    {'PGPASSWORD': 'fixture'}))
def test_configuration_blocks_before_network(change):
    http = FakeHTTP([])
    with pytest.raises(preflight.Blocked):
        preflight.run({**ENV, **change}, manifest(), 'reviewer', 'auth', http)
    assert not http.calls


def test_missing_tasks_cannot_pass():
    data = manifest()
    del data['tasks']
    http = FakeHTTP([])
    with pytest.raises(preflight.Blocked):
        preflight.run(ENV, data, 'reviewer', 'task-read', http)
    assert not http.calls


def test_head_or_digest_mismatch():
    data = manifest()
    with pytest.raises(preflight.Failed):
        preflight.run(ENV, data, 'reviewer', 'task-read', FakeHTTP([auth(), (200, {'id': USER, 'head_sha': 'c'*40, 'digest': 'b'*64})]))


def test_same_project_cannot_replace_cross_tenant_control():
    data = manifest()
    data['legacy']['b']['repository_id'] = 101
    with pytest.raises(preflight.Blocked):
        preflight.run(ENV, data, 'reviewer', 'legacy-read', FakeHTTP([]))


def test_transport_rejects_writes_and_arbitrary_paths():
    transport = preflight.Transport('sb_publishable_fixture', 'header.payload.signature')
    for path, payload in [('/rest/v1/rpc/task_dispatch', {'action': 'approve_contract', 'request': {}}),
                          ('/rest/v1/rpc/dispatch', {'action': 'claim'}),
                          ('https://example.invalid', None), ('/auth/v1/token', {})]:
        with pytest.raises(preflight.Failed):
            transport.request('POST', path, payload)


def test_redirect_does_not_forward_credentials():
    with pytest.raises(preflight.Blocked):
        preflight.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid')


def test_cli_missing_credentials_is_sanitized_and_nonzero(monkeypatch, tmp_path, capsys):
    path = tmp_path/'manifest.json'
    path.write_text(preflight.json.dumps(manifest()))
    monkeypatch.setattr(preflight.sys, 'argv', ['jwt_preflight.py', '--role', 'reviewer', '--manifest', str(path)])
    monkeypatch.delenv('REIVRO_VALIDATION_JWT', raising=False)
    assert preflight.main() == 2
    output = capsys.readouterr().out
    assert 'BLOCKED' in output and USER not in output and 'Bearer' not in output

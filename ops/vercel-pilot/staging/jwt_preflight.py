"""Per-identity hosted read checks. Never provisions fixtures or calls a write action."""
import argparse
import json
import os
import re
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
from uuid import UUID

STAGING = 'lbklqqqbmeyseeccdqog'
BASE = f'https://{STAGING}.supabase.co'
ROLES = ('agent', 'reviewer', 'worker', 'viewer', 'other-reviewer', 'no-membership')
LEGACY_ACCESS = {
    'agent': (False, False), 'reviewer': (True, False),
    'worker': (False, False), 'viewer': (True, False),
    'other-reviewer': (False, True), 'no-membership': (False, False),
}
TASK_ACCESS = {
    'agent': (True, False, False), 'reviewer': (True, True, False),
    'worker': (True, True, False), 'viewer': (True, True, False),
    'other-reviewer': (False, False, True), 'no-membership': (False, False, False),
}


class Blocked(Exception):
    pass


class Failed(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked('redirect')


class Transport:
    """Only fixed staging Auth GET and two RPC read forms are reachable."""
    def __init__(self, key, token):
        self.key, self.token = key, token
        self.opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())

    def request(self, method, path, payload=None):
        allowed = ((method, path) == ('GET', '/auth/v1/user') and payload is None)
        allowed |= ((method, path) == ('POST', '/rest/v1/rpc/read_run')
                    and isinstance(payload, dict) and set(payload) == {'p_repository_id', 'p_run_id'})
        allowed |= ((method, path) == ('POST', '/rest/v1/rpc/task_dispatch')
                    and isinstance(payload, dict) and set(payload) == {'action', 'request'}
                    and payload['action'] == 'read'
                    and isinstance(payload['request'], dict)
                    and set(payload['request']) == {'repository_id', 'id'})
        if not allowed:
            raise Failed('operation_not_read_only')
        headers = {'apikey': self.key, 'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/json'}
        if payload is not None:
            headers.update({'Content-Type': 'application/json',
                            'Content-Profile': 'reivro_checks_api',
                            'Accept-Profile': 'reivro_checks_api'})
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request = Request(BASE + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        except (URLError, OSError):
            raise Blocked('transport') from None
        with response:
            status = response.code
            raw = response.read(524289)
        if len(raw) > 524288:
            raise Blocked('response_limit')
        try:
            return status, json.loads(raw)
        except (ValueError, UnicodeError):
            raise Blocked('invalid_response') from None


def uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Blocked('invalid_manifest') from None


def fixture(value, *, task=False):
    if not isinstance(value, dict):
        raise Blocked('fixtures_missing')
    repo = value.get('repository_id')
    if type(repo) is not int or repo <= 0:
        raise Blocked('invalid_manifest')
    field = 'submission_id' if task else 'run_id'
    result = {'repository_id': repo, field: uuid(value.get(field))}
    if task:
        for key, size in (('head_sha', 40), ('digest', 64)):
            if not isinstance(value.get(key), str) or not re.fullmatch('[0-9a-f]{%d}' % size, value[key]):
                raise Blocked('invalid_manifest')
            result[key] = value[key]
    return result


def validate_config(env, manifest, role, phase):
    if role not in ROLES or phase not in ('auth', 'legacy-read', 'task-read'):
        raise Blocked('invalid_configuration')
    if not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('staging') != STAGING:
        raise Blocked('invalid_manifest')
    if manifest.get('role') != role or env.get('REIVRO_STAGING_REF') != STAGING:
        raise Blocked('scope_mismatch')
    subject = uuid(manifest.get('user_id'))
    key, token = env.get('REIVRO_PUBLISHABLE_KEY', ''), env.get('REIVRO_VALIDATION_JWT', '')
    if not key.startswith('sb_publishable_') or len(token.split('.')) != 3 or any(c.isspace() for c in token):
        raise Blocked('credentials_missing_or_invalid')
    # Do not load all role tokens into an agent-accessible process.
    if any(value and name.startswith('REIVRO_') and name.endswith('_JWT')
           and name != 'REIVRO_VALIDATION_JWT' for name, value in env.items()):
        raise Blocked('mixed_identity_context')
    if env.get('REIVRO_STAGING_AUTH_ADMIN_KEY') or env.get('PGPASSWORD'):
        raise Blocked('administrative_credential_context')
    if phase == 'auth':
        return subject, key, token, []
    names = ('a', 'b') if phase == 'legacy-read' else ('a_own', 'a_other', 'b')
    source = manifest.get('legacy' if phase == 'legacy-read' else 'tasks', {})
    if not isinstance(source, dict):
        raise Blocked('fixtures_missing')
    cases = [fixture(source.get(name), task=phase == 'task-read') for name in names]
    if cases[0]['repository_id'] == cases[-1]['repository_id']:
        raise Blocked('projects_not_distinct')
    if phase == 'task-read' and (cases[0]['repository_id'] != cases[1]['repository_id']
                               or cases[0]['submission_id'] == cases[1]['submission_id']):
        raise Blocked('invalid_task_controls')
    return subject, key, token, cases


def run(env, manifest, role, phase, transport=None):
    subject, key, token, cases = validate_config(env, manifest, role, phase)
    client = transport if transport is not None else Transport(key, token)
    status, user = client.request('GET', '/auth/v1/user')
    if status != 200 or not isinstance(user, dict):
        raise Blocked('auth_unavailable_or_invalid')
    if (user.get('role') != 'authenticated' or user.get('is_anonymous') is not False
            or uuid(user.get('id')) != subject):
        raise Failed('auth_identity_mismatch')
    checks = 1
    access = LEGACY_ACCESS[role] if phase == 'legacy-read' else TASK_ACCESS[role]
    for item, allowed in zip(cases, access):
        if phase == 'legacy-read':
            status, result = client.request('POST', '/rest/v1/rpc/read_run',
                                           {'p_repository_id': item['repository_id'], 'p_run_id': item['run_id']})
            if status != 200:
                raise Blocked('legacy_rpc_unavailable')
            valid = (isinstance(result, dict) and isinstance(result.get('run'), dict)
                     and result['run'].get('id') == item['run_id']) if allowed else result is None
        else:
            status, result = client.request('POST', '/rest/v1/rpc/task_dispatch',
                                           {'action': 'read', 'request': {'repository_id': item['repository_id'],
                                                                         'id': item['submission_id']}})
            if status in (401, 404, 405, 429) or status >= 500:
                raise Blocked('task_rpc_unavailable')
            if allowed:
                valid = status == 200 and isinstance(result, dict) and all(
                    result.get(key) == item[key] for key in ('head_sha', 'digest')) and result.get('id') == item['submission_id']
            else:
                valid = status == 403 and isinstance(result, dict) and result.get('code') == '42501'
        if not valid:
            raise Failed('unexpected_authorization_result')
        checks += 1
    return {'status': 'PASS', 'scope': phase, 'role_label': role, 'checks': checks,
            'full_authorization_matrix': 'NOT_VALIDATED', 'private_alpha': 'BLOCKED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True, choices=ROLES)
    parser.add_argument('--phase', choices=('auth', 'legacy-read', 'task-read'), default='auth')
    parser.add_argument('--manifest', type=Path, required=True, help='Operator-approved private fixture manifest, no tokens')
    args = parser.parse_args()
    try:
        with args.manifest.open('rb') as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise Blocked('manifest_limit')
        result = run(os.environ, json.loads(raw), args.role, args.phase)
        code = 0
    except Failed as error:
        result, code = {'status': 'FAIL', 'reason': str(error)}, 1
    except Blocked as error:
        result, code = {'status': 'BLOCKED', 'reason': str(error)}, 2
    except Exception:
        result, code = {'status': 'BLOCKED', 'reason': 'configuration_or_transport'}, 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())

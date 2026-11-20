"""Real loopback HTTP tests; upstream responses are fixtures unless opted in."""
from contextlib import contextmanager
import http.client
import json
import os
import tempfile
import threading
from unittest.mock import patch

import pytest
from server.scop_web import LocalServer
from server.scop_github_evidence import _Unavailable
from server.scop_pr_summary import _build_record

URL = 'https://github.com/pallets/flask/pull/5808'
FETCH = 'server.scop_github_evidence.fetch_json'


def evidence(url, _deadline):
    if '/files?' in url:
        return [{'filename': 'example.py', 'patch': '@@ -1 +1 @@\n-old\n+new',
                 'additions': 1, 'deletions': 1}]
    return {'html_url': URL, 'merged': True, 'changed_files': 1,
            'body': 'Why: <img src=x onerror=alert(1)> Improve clarity.'}


@contextmanager
def running(store=None):
    server = LocalServer(0, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def post(server, payload, route='/api/run', headers=None, raw=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=60)
    values = {'Origin': server.origin, 'X-SCOP-Token': server.token, 'Content-Type': 'application/json'}
    values.update(headers or {})
    conn.request('POST', route, body=json.dumps(payload).encode() if raw is None else raw, headers=values)
    response = conn.getresponse()
    status, body = response.status, json.loads(response.read())
    conn.close()
    return status, body


def request(record=False, permissions=None, url=URL):
    return {'request': {'pr_url': url, 'permissions': ['github:read-pr-evidence'] if permissions is None else permissions},
            'record_measurement': record, 'permissions': ['local:write-measurements'] if record else []}


def test_origin_token_and_host_block_before_dispatch():
    with running() as server, patch(FETCH) as fetch:
        for headers in ({'Origin':'https://evil.example'}, {'X-SCOP-Token':'wrong'},
                        {'Host':'evil.example'}, {'X-SCOP-Token':'é'}, {'Sec-Fetch-Site':'cross-site'}):
            assert post(server, request(), headers=headers)[0] == 403
        fetch.assert_not_called()


def test_permission_and_invalid_url_no_network_or_writes(tmp_path):
    tmp_path.chmod(0o700)
    with running(tmp_path) as server, patch(FETCH) as fetch:
        for payload, expected in ((request(permissions=[]), 'blocked'),
                                  (request(url='https://evil.example'), 'failed'),
                                  (request(permissions=['repo:write']), 'blocked')):
            status, body = post(server, payload)
            assert status == 200
            assert body['result']['workspace']['execution']['status'] == expected
        payload = request(record=True)
        payload['permissions'] = []
        assert post(server, payload)[1]['error']['code'] == 'permission_denied'
        fetch.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('raw', [b'', b'\xff', b'{}', b'[]', b'{"a":1,"a":2}', b' ' * 65537])
def test_invalid_transport(raw):
    with running() as server, patch(FETCH) as fetch:
        assert post(server, {}, raw=raw)[0] in (400, 413)
        fetch.assert_not_called()


def test_real_pipeline_record_feedback_and_missing_values(tmp_path):
    tmp_path.chmod(0o700)
    with running(tmp_path) as server, patch(FETCH, side_effect=evidence):
        _, body = post(server, request(record=True))
        run = body['result']['workspace']['execution']
        assert run['status'] == 'completed'
        assert run['references_verified'] == run['references_checked'] == 4
        assert len(run['steps']) == 4
        feedback = {'operation':'feedback', 'execution_id':run['execution_id'],
                    'evaluation':{'decision':'accepted'}, 'permissions':['local:write-measurements']}
        denied = {**feedback, 'permissions':[]}
        assert post(server, denied, '/api/measurement')[1]['error']['code'] == 'permission_denied'
        result = post(server, feedback, '/api/measurement')[1]['result']
        assert result['execution']['status'] == 'completed'
        assert result['measurement']['human_review_duration'] is None
        assert not result['measurement']['total_observed_task_time']['complete']
        assert post(server, feedback, '/api/measurement')[1]['error']['code'] == 'duplicate_feedback'
        exported = post(server, {'operation':'export'}, '/api/measurement')[1]['result']
        assert exported['aggregate']['recorded_attempts'] == 1
        assert exported['aggregate']['acceptance_rate']['value'] == 1
        assert exported['aggregate']['workflow_completion_rate']['value'] is None


def test_upstream_failure_mismatch_and_interruption():
    def corrupt(*args):
        record = _build_record(*args)
        record['verified_facts'][-1]['sources'][-1]['excerpt'] = '+absent'
        return record
    with running() as server:
        with patch(FETCH, side_effect=_Unavailable('GitHub unavailable')):
            run = post(server, request())[1]['result']['workspace']['execution']
            assert run['status'] == 'blocked' and run['summary'] is None
        with patch(FETCH, side_effect=evidence), patch('server.scop_pr_summary._build_record', side_effect=corrupt):
            run = post(server, request())[1]['result']['workspace']['execution']
            assert run['status'] == 'failed' and run['error_code'] == 'evidence_mismatch'
            assert run['summary'] is None
        with patch(FETCH, side_effect=KeyboardInterrupt):
            run = post(server, request())[1]['result']['workspace']['execution']
            assert run['status'] == 'cancelled' and run['summary'] is None


def test_safe_assets_no_cors_and_busy():
    with running() as server:
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Access-Control-Allow-Origin') is None
        assert "frame-ancestors 'none'" in response.getheader('Content-Security-Policy')
        assert server.token.encode() in response.read()
        conn.close()
        with server.operation_lock:
            assert post(server, request())[0] == 409
        with patch('server.scop_web.workspace.handle_request', side_effect=RuntimeError('SECRET')):
            status, body = post(server, request())
            assert status == 500 and 'SECRET' not in json.dumps(body)


@pytest.mark.skipif(os.getenv('SCOP_LIVE_TESTS') != '1', reason='Public GitHub opt-in')
def test_live_public_pr_over_http():
    with tempfile.TemporaryDirectory(prefix='scop-web-live-') as store, running(store) as server:
        status, body = post(server, request(record=True))
        assert status == 200
        run = body['result']['workspace']['execution']
        assert run['status'] == 'completed', run
        assert run['references_verified'] == run['references_checked'] > 0
        assert all(step['status'] == 'completed' for step in run['steps'].values())


def test_completed_readonly_execution_does_not_write_store(tmp_path):
    tmp_path.chmod(0o700)
    with running(tmp_path) as server, patch(FETCH, side_effect=evidence):
        run = post(server, request())[1]['result']['workspace']['execution']
        assert run['status'] == 'completed'
    assert list(tmp_path.iterdir()) == []

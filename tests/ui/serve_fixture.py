"""UI test server: only upstream fetch is substituted; no fabricated workflow result."""
import os
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch
from server.scop_web import LocalServer
from server.scop_github_evidence import _Unavailable
from server.scop_pr_summary import _build_record

fixture = runpy.run_path(str(Path(__file__).parents[1] / 'test_scop_web.py'))

def fetch(url, deadline):
    if '/pulls/404' in url:
        raise _Unavailable('GitHub unavailable (test fixture)')
    if '/pulls/406' in url:
        raise KeyboardInterrupt
    result = fixture['evidence'](url, deadline)
    if isinstance(result, dict) and '/pulls/405' in url:
        result['html_url'] = 'https://github.com/pallets/flask/pull/405'
    return result

def build(url, metadata, files):
    result = _build_record(url, metadata, files)
    if url.endswith('/405'):
        result['verified_facts'][-1]['sources'][-1]['excerpt'] = '+not present'
    return result

with tempfile.TemporaryDirectory(prefix='scop-ui-') as store, LocalServer(0, None if os.getenv('SCOP_UI_NO_STORE') == '1' else store) as server:
    print(server.origin, flush=True)
    if os.getenv('SCOP_UI_LIVE') == '1':
        server.serve_forever()
    else:
        with patch(fixture['FETCH'], side_effect=fetch), patch('server.scop_pr_summary._build_record', side_effect=build):
            server.serve_forever()

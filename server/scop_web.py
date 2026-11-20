"""Loopback-only, single-user HTTP adapter for Workspace and Measurement."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import threading

from . import scop_measurement as measurement
from . import scop_workspace as workspace

WEB = Path(__file__).resolve().parents[1] / 'web'
MAX_BODY = 65_536


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, port=8765, store=None):
        self.token = secrets.token_urlsafe(32)
        self.store = store
        self.slots = threading.BoundedSemaphore(8)
        self.operation_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass  # Do not log URLs, bodies, tokens, or untrusted error text.

    def reply(self, status, body, content_type='application/json'):
        raw = body if isinstance(body, bytes) else json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        for key, value in {
            'Content-Type': content_type, 'Content-Length': str(len(raw)),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'Connection': 'close',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        }.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def error(self, status, code, message):
        self.reply(status, {'error': {'code': code, 'message': message}})

    def trusted(self, post=False):
        if self.headers.get_all('Host') != [self.server.origin.removeprefix('http://')]:
            return False
        if self.headers.get('Sec-Fetch-Site') not in (None, 'none', 'same-origin'):
            return False
        origin = self.headers.get_all('Origin')
        if origin is not None and origin != [self.server.origin]:
            return False
        return not post or (origin == [self.server.origin] and
            secrets.compare_digest(self.headers.get('X-SCOP-Token', '').encode('utf-8'), self.server.token.encode()))

    def do_GET(self):
        if not self.trusted():
            return self.error(403, 'origin_denied', 'Use the local Workspace address')
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in assets:
            return self.error(404, 'not_found', 'Unknown route')
        name, mime = assets[self.path]
        raw = (WEB / name).read_bytes()
        if name == 'index.html':
            raw = raw.replace(b'__TOKEN__', self.server.token.encode())
        self.reply(200, raw, mime)

    def do_POST(self):
        if not self.trusted(post=True):
            return self.error(403, 'origin_denied', 'Local origin and session token required')
        if self.path not in ('/api/run', '/api/measurement'):
            return self.error(404, 'not_found', 'Unknown route')
        lengths = self.headers.get_all('Content-Length', [])
        if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                or len(lengths[0]) > 8 or self.headers.get('Transfer-Encoding') is not None):
            return self.error(400, 'invalid_request', 'One bounded Content-Length is required')
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            return self.error(413, 'invalid_request', 'Request must be between 1 and 65536 bytes')
        if self.headers.get('Content-Type') != 'application/json':
            return self.error(415, 'invalid_request', 'Expected application/json')
        if not self.server.operation_lock.acquire(blocking=False):
            return self.error(409, 'busy', 'Another operation is in progress; wait before retrying')
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.error(400, 'invalid_request', 'Incomplete request')
            payload = measurement._json(raw)
            if self.path == '/api/run':
                measurement._fields(payload, {'request', 'record_measurement'}, {'permissions'})
                measurement._require(type(payload['record_measurement']) is bool, 'Expected a boolean recording choice')
                if payload['record_measurement']:
                    if not self.server.store:
                        return self.error(400, 'store_unavailable', 'Start with --store-dir to enable recording')
                    command = {'operation': 'run', 'request': payload['request'],
                               'permissions': payload.get('permissions', [])}
                    _, result = measurement.handle_request_bytes(json.dumps(command).encode(), self.server.store)
                else:
                    measurement._require(payload.get('permissions', []) == [], 'Unsupported local permissions')
                    _, response = workspace.handle_request(io.BytesIO(json.dumps(payload['request']).encode()))
                    result = {'result': {'workspace': asdict(response)}, 'error': None}
            else:
                if not isinstance(payload, dict) or payload.get('operation') not in ('export', 'get', 'feedback'):
                    return self.error(400, 'invalid_request', 'Unsupported measurement operation')
                if not self.server.store:
                    return self.error(400, 'store_unavailable', 'Measurement recording is not configured')
                _, result = measurement.handle_request_bytes(raw, self.server.store)
            self.reply(200, result)
        except measurement.MeasurementError as error:
            self.error(400, error.code, str(error))
        except Exception:
            self.error(500, 'request_failed', 'Request could not complete; its outcome may be unknown')
        finally:
            self.server.operation_lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--store-dir', type=Path, help='Existing private directory outside Git; no automatic writes')
    args = parser.parse_args()
    if args.store_dir:
        with measurement._open_store(args.store_dir):
            pass
    with LocalServer(args.port, args.store_dir) as server:
        print(f'SCOP Workspace: {server.origin}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

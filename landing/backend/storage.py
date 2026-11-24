"""Durable signup adapter using a restricted Supabase RPC."""
import json
import urllib.request
from uuid import uuid4

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class SupabaseStore:
    def __init__(self, url, key, rpc_secret):
        self.url = url
        self.key = key
        self.rpc_secret = rpc_secret

    def save(self, value):
        identity = str(uuid4())
        payload = {
            'p_secret': self.rpc_secret,
            'p_id': identity,
            'p_email': value['email'],
            'p_tool': value['tool'],
            'p_problem': value['problem'],
            'p_consent': value['consent'],
            'p_consent_version': 'landing-v1',
        }
        request = urllib.request.Request(
            self.url + '/rest/v1/rpc/scop_signup_insert',
            data=json.dumps(payload).encode(), method='POST',
            headers={'apikey': self.key, 'Content-Type': 'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError('Storage acknowledgement invalid')
            if json.loads(raw) != [{'id': identity}]:
                raise ValueError('Storage acknowledgement invalid')

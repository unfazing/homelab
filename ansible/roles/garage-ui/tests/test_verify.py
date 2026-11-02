import importlib.util
import json
import pathlib
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('garage_ui_verify', pathlib.Path(__file__).parents[1] / 'files' / 'verify.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrowserFlowTests(unittest.TestCase):
    def setUp(self):
        self.config = {'proxy_address': '192.168.1.101', 'ui_hostname': 'garage.home.example.com',
                       's3_hostname': 's3.home.example.com', 'region': 'homelab', 'bucket': 'app-data',
                       'username': 'admin', 'password': 'secret-not-printed', 'key_id': 'GK' + 'a' * 24,
                       'key_secret': 'b' * 64, 'container': 'homelab-garage-ui'}
        self.deleted = False
        self.presign = 'https://s3.home.example.com/app-data/probe?sig=fixture'
        self.payload = b'Private Garage round-trip verification\n'
        self.sessions = []

    def request(self, config, hostname, method, path, body=b'', headers=None):
        headers = headers or {}
        if hostname == config['ui_hostname']:
            if path == '/auth/login':
                if json.loads(body)['password'] != config['password']:
                    return 401, b''
                return 200, b'{"token":"persisted-session"}'
            if path.endswith('/preview-url'):
                return 200, b'{"data":{"url":"/api/v1/buckets/app-data/objects/probe?pt=fixture"}}'
            if path.endswith('/presign?expires_in=60'):
                return 200, json.dumps({'data': {'url': self.presign}}).encode()
            if '?pt=' in path:
                return 200, self.payload
            token = headers.get('Authorization')
            if token:
                self.sessions.append(token)
            return (200 if token == 'Bearer persisted-session' else 401), b''
        if method == 'DELETE':
            self.deleted = True
            return 204, b''
        if method == 'PUT':
            return (403 if path.startswith('/homelab-denied-') else 200), b''
        if '?' in path or 'Authorization' in headers:
            return 200, self.payload
        return 403, b''

    def test_complete_browser_flow_and_same_session_survives_restart(self):
        self.config['restart_ui'] = True
        with mock.patch.object(module, 'request', self.request), mock.patch.object(module.subprocess, 'run') as restart:
            result = module.verify(self.config)
        self.assertTrue(result['session_survives_restart'])
        restart.assert_called_once()
        self.assertTrue(self.deleted)
        self.assertEqual(set(self.sessions), {'Bearer persisted-session'})

    def test_internal_presign_endpoint_is_rejected_and_probe_removed(self):
        self.presign = 'http://garage:3900/app-data/probe?sig=fixture'
        with mock.patch.object(module, 'request', self.request):
            with self.assertRaisesRegex(module.VerificationError, 'internal endpoint'):
                module.verify(self.config)
        self.assertTrue(self.deleted)

    def test_unrelated_presign_domain_is_rejected(self):
        self.presign = 'https://attacker.example.com/steal'
        with mock.patch.object(module, 'request', self.request):
            with self.assertRaises(module.VerificationError):
                module.verify(self.config)
        self.assertTrue(self.deleted)


if __name__ == '__main__':
    unittest.main()

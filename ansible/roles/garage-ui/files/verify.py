#!/usr/bin/python3
"""Verify private HTTPS/S3/auth boundaries; credentials enter only through stdin.

Creates and removes one randomly named probe object. Optional UI restart tests
that the same native session survives; no private signer material is read.
"""
import datetime
import hashlib
import hmac
import http.client
import json
import secrets
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


class PrivateHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address):
        super().__init__(hostname, timeout=30, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def request(config, hostname, method, path, body=b'', headers=None):
    connection = PrivateHTTPS(hostname, config['proxy_address'])
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def signed_headers(config, method, path, body):
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    digest = hashlib.sha256(body).hexdigest()
    headers = {'host': config['s3_hostname'], 'x-amz-content-sha256': digest, 'x-amz-date': stamp}
    names = ';'.join(sorted(headers))
    canonical = '\n'.join([method, path, '', ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), names, digest])
    scope = day + '/' + config['region'] + '/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n' + stamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    signing = ('AWS4' + config['key_secret']).encode()
    for part in [day, config['region'], 's3', 'aws4_request']:
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing, message.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = 'AWS4-HMAC-SHA256 Credential=' + config['key_id'] + '/' + scope + ', SignedHeaders=' + names + ', Signature=' + signature
    return headers


def verify(config):
    ui, s3 = config['ui_hostname'], config['s3_hostname']
    status, _ = request(config, ui, 'GET', '/api/v1/buckets/')
    require(status == 401, 'Anonymous UI administration must be denied')
    login = json.dumps({'username': config['username'], 'password': config['password']}).encode()
    status, result = request(config, ui, 'POST', '/auth/login', login, {'Content-Type': 'application/json'})
    require(status == 200, 'Native UI login failed')
    token = json.loads(result)['token']
    auth = {'Authorization': 'Bearer ' + token}
    status, _ = request(config, ui, 'GET', '/api/v1/buckets/', headers=auth)
    require(status == 200, 'Authenticated UI bucket listing failed')
    bad_login = json.dumps({'username': config['username'], 'password': secrets.token_hex(32)}).encode()
    status, _ = request(config, ui, 'POST', '/auth/login', bad_login, {'Content-Type': 'application/json'})
    require(status == 401, 'Invalid native credentials must be denied')
    key = 'homelab-verification-' + secrets.token_hex(16) + '.txt'
    path = '/' + urllib.parse.quote(config['bucket'], safe='') + '/' + key
    payload = b'Private Garage round-trip verification\n'
    created = False
    try:
        status, _ = request(config, s3, 'PUT', path, payload, signed_headers(config, 'PUT', path, payload))
        require(status in [200, 201], 'Signed path-style S3 upload failed')
        created = True
        status, result = request(config, s3, 'GET', path, headers=signed_headers(config, 'GET', path, b''))
        require(status == 200 and result == payload, 'Signed S3 download failed')
        status, _ = request(config, s3, 'GET', path)
        require(status in [400, 403], 'Anonymous S3 object read must be denied')
        object_route = '/api/v1/buckets/' + urllib.parse.quote(config['bucket'], safe='') + '/objects/' + key
        status, result = request(config, ui, 'GET', object_route + '/preview-url', headers=auth)
        require(status == 200, 'Authenticated UI preview URL generation failed')
        preview = json.loads(result)['data']['url']
        require(preview.startswith('/api/v1/buckets/') and not preview.startswith('//'), 'Preview must stay on the UI origin')
        status, result = request(config, ui, 'GET', preview)
        require(status == 200 and result == payload, 'Browser media preview through the UI failed')
        status, result = request(config, ui, 'GET', object_route + '/presign?expires_in=60', headers=auth)
        require(status == 200, 'UI presigned download generation failed')
        url = urllib.parse.urlsplit(json.loads(result)['data']['url'])
        require(url.scheme == 'https' and url.netloc == s3, 'Presigned URL leaked an internal endpoint')
        status, result = request(config, s3, 'GET', url.path + '?' + url.query)
        require(status == 200 and result == payload, 'Browser presigned download through Caddy failed')
        denied_bucket = '/homelab-denied-' + secrets.token_hex(8)
        status, _ = request(config, s3, 'PUT', denied_bucket, headers=signed_headers(config, 'PUT', denied_bucket, b''))
        require(status == 403, 'Application key must not create buckets')
    finally:
        if created:
            status, _ = request(config, s3, 'DELETE', path, headers=signed_headers(config, 'DELETE', path, b''))
            require(status in [200, 204], 'Verification object cleanup failed')
    if config.get('restart_ui', False):
        subprocess.run(['docker', 'restart', config['container']], check=True, capture_output=True, timeout=60)
        for _ in range(30):
            try:
                status, _ = request(config, ui, 'GET', '/api/v1/buckets/', headers=auth)
                if status == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(1)
        else:
            raise VerificationError('Native UI session did not survive container restart')
    return {'verified': ['trusted HTTPS', 'native UI authentication', 'private S3', 'signed upload/download',
                         'scoped application key', 'browser preview', 'canonical presigned download'],
            'session_survives_restart': bool(config.get('restart_ui', False))}


if __name__ == '__main__':
    try:
        print(json.dumps(verify(json.load(sys.stdin))))
    except (VerificationError, ValueError, KeyError, OSError, subprocess.SubprocessError, http.client.HTTPException) as error:
        # Exceptions from HTTP libraries may contain signed URLs: never print them.
        print('Garage HTTPS verification failed: ' + (str(error) if isinstance(error, VerificationError) else type(error).__name__), file=sys.stderr)
        raise SystemExit(1)

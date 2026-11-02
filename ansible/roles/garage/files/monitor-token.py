#!/usr/bin/python3
"""Idempotently issue an endpoint-scoped token, never printing its secret."""
import json
from pathlib import Path
import re
import sys
from reconcile import docker_api

SCOPE = ['GetClusterHealth', 'GetClusterStatistics', 'Metrics']
NAME = 'homelab-storage-observer'


def reconcile_token(api, path):
    token = path.read_text().strip()
    tokens = api('ListAdminTokens')
    matches = [t for t in tokens if t['name'] == NAME]
    changed = False
    if token:
        if not re.fullmatch(r'[A-Za-z0-9._~+/-]{20,256}={0,2}', token):
            raise ValueError('Invalid saved token')
        matches = [t for t in matches if t.get('id') and token.startswith(t['id'])]
        if len(matches) != 1:
            raise ValueError('Saved token does not match its recorded identity')
        info = api('GetAdminTokenInfo', {'id': matches[0]['id']})
        if sorted(info['scope']) != SCOPE or info.get('expiration') or info['expired']:
            api('UpdateAdminToken', {'id': info['id'], 'body': {'name': NAME, 'scope': SCOPE, 'neverExpires': True}})
            changed = True
    else:
        if matches:
            raise ValueError('Recorded token secret is missing; explicit recovery/revocation required')
        info = api('CreateAdminToken', {'name': NAME, 'scope': SCOPE, 'neverExpires': True})
        token = info['secretToken']
        if not re.fullmatch(r'[A-Za-z0-9._~+/-]{20,256}={0,2}', token):
            raise ValueError('Unexpected token format')
        # Parent directory is root-owned; Ansible precreates this mode-600 file.
        with path.open('w') as output:
            output.write(token + '\n')
            output.flush()
            import os
            os.fsync(output.fileno())
        changed = True
    return {'changed': changed}


if __name__ == '__main__':
    try:
        config = json.load(sys.stdin)
        print(json.dumps(reconcile_token(docker_api(config['container']), Path(config['path']))))
    except Exception:
        print('Scoped Garage monitoring token convergence failed; inspect locally.', file=sys.stderr)
        raise SystemExit(1)

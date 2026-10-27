#!/usr/bin/env python3
"""Provision a non-admin observer, without changing repositories or teams."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from urllib import request, error

USER = 'homepage-observer'
SCOPES = 'read:issue,read:notification,read:repository'
NAME = 'homelab-homepage-readonly'
SECRET = Path('/etc/homelab/homepage/gitea-token')
DB = 'file:/srv/homelab/gitea/gitea/gitea.db?mode=ro'

def cli_token(user, name, scopes):
    p = subprocess.run(['docker', 'exec', '--user', 'git', 'gitea', 'gitea', 'admin', 'user', 'generate-access-token',
                        '--username', user, '--token-name', name, '--scopes', scopes, '--raw'], check=True, capture_output=True, text=True)
    return p.stdout.strip()

def api(token, method, path, body=None, accepted=(200,)):
    r = request.Request('http://127.0.0.1:3000/api/v1' + path, method=method,
                        data=None if body is None else json.dumps(body).encode(),
                        headers={'Authorization': 'token ' + token, 'Content-Type': 'application/json'})
    try:
        with request.urlopen(r, timeout=15) as response:
            status, data = response.status, response.read()
    except error.HTTPError as e:
        status, data = e.code, e.read()
    if status not in accepted:
        raise RuntimeError(f'Gitea {method} {path} failed with HTTP {status}')
    return None if not data else json.loads(data)

def main():
    changed = False
    token = cli_token('homelab-admin', 'iac-homepage-' + secrets.token_hex(8), 'all')
    try:
        user = api(token, 'GET', '/users/' + USER, accepted=(200, 404))
        if not user or 'login' not in user:
            user = api(token, 'POST', '/admin/users', {
                'username': USER, 'email': USER + '@localhost.invalid', 'password': secrets.token_urlsafe(48),
                'must_change_password': False, 'send_notify': False, 'restricted': True, 'visibility': 'private'}, accepted=(201,))
            changed = True
        if user.get('is_admin') or not user.get('active'):
            raise RuntimeError('Homepage observer is privileged or inactive')
        with sqlite3.connect(DB, uri=True) as db:
            quota = db.execute('SELECT max_repo_creation, allow_create_organization, allow_git_hook, allow_import_local FROM user WHERE name=?', (USER,)).fetchone()
            rows = db.execute('SELECT scope FROM access_token WHERE uid=? AND name=?', (user['id'], NAME)).fetchall()
        if quota != (0, 0, 0, 0) or not user.get('restricted'):
            api(token, 'PATCH', '/admin/users/' + USER, {
                'admin': False, 'restricted': True, 'visibility': 'private', 'max_repo_creation': 0,
                'allow_create_organization': False, 'allow_git_hook': False, 'allow_import_local': False})
            changed = True
        if rows:
            if len(rows) != 1 or set(rows[0][0].split(',')) != set(SCOPES.split(',')) or not SECRET.is_file():
                raise RuntimeError('Homepage observer token scope or secret is inconsistent; recover or rotate explicitly')
        else:
            if SECRET.exists():
                raise RuntimeError('Orphaned Homepage token file; inspect before reissuing')
            value = cli_token(USER, NAME, SCOPES)
            fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(value)
            changed = True
        # Homepage substitutes file contents directly into YAML, without trimming.
        if SECRET.read_text() != SECRET.read_text().strip():
            SECRET.write_text(SECRET.read_text().strip())
            changed = True
        api(SECRET.read_text().strip(), 'GET', '/notifications?limit=1')
    finally:
        api(token, 'DELETE', '/token', accepted=(204,))
    print(json.dumps({'changed': changed}))

if __name__ == '__main__':
    main()

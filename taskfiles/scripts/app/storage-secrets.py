#!/usr/bin/env python3
"""Task-only controller helper: stable ignored service secrets, never printed by deploy."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SECRET_FILE = ROOT / '.generated/secrets/storage.json'
APP_FILE = ROOT / 'ansible/vars/storage-applications.json'
IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,46}')


def applications(path=APP_FILE):
    apps = json.loads(path.read_text())['postgresql_applications']
    names = set()
    for app in apps:
        if set(app) != {'database', 'owner_role', 'runtime_role', 'migration_role'}:
            raise ValueError('Unexpected database application fields')
        for value in app.values():
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value == 'homelab_monitor':
                raise ValueError('Invalid database or role identifier')
        for key in ['owner_role', 'runtime_role', 'migration_role']:
            if app[key] in names or app[key] == 'postgres':
                raise ValueError('Database roles must be distinct and application-specific')
            names.add(app[key])
    if len({a['database'] for a in apps}) != len(apps):
        raise ValueError('Database names must be unique')
    return apps


def converge(existing, apps):
    """Only add absent values; never rotate or discard existing runtime credentials."""
    data = json.loads(json.dumps(existing))
    pg = data.setdefault('postgresql', {})
    pg.setdefault('admin_password', secrets.token_urlsafe(32))
    pg.setdefault('monitor_password', secrets.token_urlsafe(32))
    for app in apps:
        credentials = pg.setdefault('applications', {}).setdefault(app['database'], {})
        credentials.setdefault('runtime_password', secrets.token_urlsafe(32))
        credentials.setdefault('migration_password', secrets.token_urlsafe(32))
    garage = data.setdefault('garage', {})
    for name in ['rpc_secret', 'admin_token', 'metrics_token', 's3_secret_key']:
        garage.setdefault(name, secrets.token_hex(32))
        if not re.fullmatch(r'[a-f0-9]{64}', garage[name]):
            raise ValueError('Existing Garage secret is invalid; explicit recovery is required')
    garage.setdefault('s3_key_id', 'GK' + secrets.token_hex(12))
    garage.setdefault('ui_username', 'admin')
    garage.setdefault('ui_password', secrets.token_urlsafe(24))
    if not re.fullmatch(r'GK[a-f0-9]{24}', garage['s3_key_id']):
        raise ValueError('Existing Garage access-key identifier is invalid')
    for value in [pg['admin_password'], pg['monitor_password'], garage['ui_password']]:
        if not isinstance(value, str) or len(value) < 24:
            raise ValueError('Existing service password is invalid; do not replace it silently')
    for credentials in pg['applications'].values():
        for name in ['runtime_password', 'migration_password']:
            if not isinstance(credentials[name], str) or len(credentials[name]) < 24:
                raise ValueError('Existing app password is invalid; do not replace it silently')
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', choices=['ensure', 'credentials'], default='ensure')
    parser.add_argument('--application', default='colouring_book_dev')
    args = parser.parse_args()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = SECRET_FILE.parent / '.storage-secrets.lock'
    fd = os.open(lock_file, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if SECRET_FILE.exists():
            s = SECRET_FILE.lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600:
                raise ValueError('Secret bundle must be an operator-owned regular mode-600 file')
            current = json.loads(SECRET_FILE.read_text())
        else:
            if args.action == 'credentials':
                raise ValueError('Prepare service credentials before displaying them')
            current = {}
        wanted = converge(current, applications())
        if wanted != current:
            if args.action == 'credentials':
                raise ValueError('New application secrets have not been prepared; run the deployment Task')
            fd, name = tempfile.mkstemp(dir=SECRET_FILE.parent)
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(wanted, f, indent=2)
                    f.write('\n')
                os.replace(name, SECRET_FILE)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        if args.action == 'credentials':
            if args.application not in wanted['postgresql']['applications']:
                raise ValueError('Application is not in the protected credential bundle')
            # Deliberate operator-only output; deploy/verify never invoke this action.
            print(json.dumps({'postgresql': {'database': args.application,
                              'admin_username': 'postgres', 'admin_password': wanted['postgresql']['admin_password'],
                              **wanted['postgresql']['applications'][args.application]},
                              'garage': {k: wanted['garage'][k] for k in ['ui_username', 'ui_password', 's3_key_id', 's3_secret_key']}}, indent=2))
        else:
            print('Protected storage credentials ready; no values displayed.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit('Storage credential preparation failed; inspect protected files without printing them.')

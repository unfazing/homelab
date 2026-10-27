#!/usr/bin/env python3
"""Private Task helper: prepare credentials without logging them."""
import os
from pathlib import Path
import secrets
import sys

root = Path('.generated/secrets')
root.mkdir(parents=True, exist_ok=True)
for name in ('homepage-dashboard-password', 'homepage-adguard-password', 'homepage-session-secret'):
    path = root / name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or path.stat().st_mode & 0o077 or not path.read_text().strip():
            raise SystemExit('Existing Homepage credential is empty or insecure')
    else:
        with os.fdopen(fd, 'w') as out:
            out.write(secrets.token_urlsafe(48 if name == 'homepage-session-secret' else 24) + '\n')
if len(sys.argv) > 1 and sys.argv[1] == 'credentials':
    print('URL: https://dashboard.home.' + os.environ['HOMELAB_DOMAIN'])
    print('Login: Homepage native password (no username)')
    print('Password: ' + (root / 'homepage-dashboard-password').read_text().strip())

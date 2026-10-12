#!/usr/bin/env python3
"""Create the ignored controller-side Hermes dashboard bootstrap credential."""

import base64
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path


def main() -> None:
    directory = Path('.generated/secrets')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / 'hermes-dashboard.json'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise SystemExit('Hermes dashboard secret must be a regular mode-0600 file')
        existing = json.loads(path.read_text(encoding='utf-8'))
        if not all(existing.get(key) for key in ('username', 'password', 'password_hash', 'session_secret')):
            raise SystemExit('Hermes dashboard secret is incomplete; inspect it before retrying')
        return

    password = secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    password_hash = (
        f'scrypt$16384$8$1${base64.b64encode(salt).decode()}$'
        f'{base64.b64encode(derived).decode()}'
    )
    material = {
        'username': 'admin',
        'password': password,
        'password_hash': password_hash,
        'session_secret': base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(material, stream)
        stream.write('\n')


if __name__ == '__main__':
    main()

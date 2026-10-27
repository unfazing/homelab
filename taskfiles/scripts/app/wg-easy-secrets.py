#!/usr/bin/env python3
"""Task-only bootstrap credential; never used by guest Ansible scripts."""
import os
from pathlib import Path
import secrets
import sys

root=Path('.generated/secrets');root.mkdir(parents=True,exist_ok=True)
path=root/'wg-easy-admin-password'
try:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
except FileExistsError:
    assert path.is_file() and not path.stat().st_mode & 0o077 and len(path.read_text().strip())>=16,'Invalid wg-easy recovery file'
else:
    with os.fdopen(fd,'w') as stream:stream.write(secrets.token_urlsafe(24)+'\n')
if len(sys.argv)>1 and sys.argv[1]=='credentials':
    print('URL: https://wireguard.home.'+os.environ['HOMELAB_DOMAIN'])
    print('Username: admin')
    print('Password: '+path.read_text().strip())

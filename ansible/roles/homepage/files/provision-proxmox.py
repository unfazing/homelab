#!/usr/bin/env python3
"""Own only Homepage's read-only Proxmox identity and private token file."""
import json
import os
from pathlib import Path
import subprocess

USER = 'homepage@pve'
TOKEN = 'dashboard'
PRINCIPAL = USER + '!' + TOKEN
SECRET = Path('/etc/homelab/homepage-observer/proxmox-token')

def run(*args):
    return json.loads(subprocess.check_output(['pveum', *args, '--output-format', 'json'], text=True))

def main():
    changed = False
    users = run('user', 'list')
    if not any(u['userid'] == USER for u in users):
        subprocess.run(['pveum', 'user', 'add', USER, '--enable', '1', '--comment', 'Homepage read-only observer'], check=True, capture_output=True)
        changed = True
    tokens = run('user', 'token', 'list', USER)
    existing = [t for t in tokens if t['tokenid'] == TOKEN]
    if existing:
        if not existing[0].get('privsep') or not SECRET.is_file():
            raise RuntimeError('Homepage token has unsafe privilege separation or its secret is missing; revoke/recover explicitly')
    else:
        if SECRET.exists():
            raise RuntimeError('An orphaned Homepage token secret exists; inspect before reissuing')
        result = run('user', 'token', 'add', USER, TOKEN, '--privsep', '1')
        SECRET.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(result['value'] + '\n')
        changed = True
    acl = run('acl', 'list')
    for kind, principal, option in [('user', USER, '--users'), ('token', PRINCIPAL, '--tokens')]:
        grants = [a for a in acl if a['type'] == kind and a['ugid'] == principal]
        if any(a['path'] != '/' or a['roleid'] != 'PVEAuditor' for a in grants):
            raise RuntimeError('Homepage observer has unexpected ACL grants')
        if not grants or not all(a.get('propagate') for a in grants):
            subprocess.run(['pveum', 'acl', 'modify', '/', option, principal, '--roles', 'PVEAuditor', '--propagate', '1'], check=True, capture_output=True)
            changed = True
    os.chmod(SECRET, 0o600)
    print(json.dumps({'changed': changed}))

if __name__ == '__main__':
    main()

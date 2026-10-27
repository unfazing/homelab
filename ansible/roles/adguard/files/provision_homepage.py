#!/usr/bin/env python3
"""Add one separately revocable normal AdGuard account, with rollback."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from rotate_password import atomic_write, compose, read_password, user_section, wait_healthy, web_healthy

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--domain', required=True)
    args = p.parse_args()
    address = '192.168.1.100'
    secret = Path('/etc/homelab/adguard/homepage-password')
    password = read_password(secret)
    if web_healthy('homepage', password, address, 3000):
        print(json.dumps({'changed': False}))
        return
    config = Path('/srv/homelab/adguard/conf/AdGuardHome.yaml')
    backup = Path('/etc/homelab/adguard/AdGuardHome.yaml.pre-homepage')
    original = config.read_bytes()
    metadata = config.stat()
    lines, start, end = user_section(original.decode())
    if any(re.match(r'^\s+- name:\s*[\"\x27]?homepage[\"\x27]?\s*$', line) for line in lines[start:end]):
        raise RuntimeError('Homepage account exists but its credential does not match; rotate/recover explicitly')
    if backup.exists():
        raise RuntimeError('A previous Homepage provisioning backup needs review')
    admin = read_password(Path('/etc/homelab/adguard/admin-password'))
    if not web_healthy('server', admin, address, 3000):
        raise RuntimeError('Existing administrator failed preflight')
    result = subprocess.run(['htpasswd', '-B', '-C', '10', '-i', '-n', 'homepage'], input=password+'\n', text=True, capture_output=True, check=True)
    hashed = result.stdout.strip().split(':', 1)[1]
    project = Path('/opt/homelab/adguard')
    try:
        compose(project, 'stop', '--timeout', '30', 'adguard')
        original = config.read_bytes()  # Read after AdGuard's final shutdown write.
        metadata = config.stat()
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(original)
        lines, start, end = user_section(original.decode())
        sample = next(line for line in lines[start:end] if re.match(r'^\s+- name:', line))
        indent = re.match(r'^\s*', sample).group()
        lines[end:end] = [f'{indent}- name: homepage\n', f'{indent}  password: {hashed}\n']
        atomic_write(config, ''.join(lines).encode(), mode=stat.S_IMODE(metadata.st_mode), uid=metadata.st_uid, gid=metadata.st_gid)
        compose(project, 'up', '--detach', '--no-deps', 'adguard')
        for username, value in [('homepage', password), ('server', admin)]:
            wait_healthy(username, value, address, 3000, address, 'gitea.home.'+args.domain, '192.168.1.101')
    except Exception:
        compose(project, 'stop', '--timeout', '30', 'adguard')
        atomic_write(config, original, mode=stat.S_IMODE(metadata.st_mode), uid=metadata.st_uid, gid=metadata.st_gid)
        compose(project, 'up', '--detach', '--no-deps', 'adguard')
        wait_healthy('server', admin, address, 3000, address, 'gitea.home.'+args.domain, '192.168.1.101')
        backup.unlink(missing_ok=True)
        raise
    backup.unlink()
    print(json.dumps({'changed': True}))

if __name__ == '__main__':
    main()

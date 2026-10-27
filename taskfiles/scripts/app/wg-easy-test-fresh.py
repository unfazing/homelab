#!/usr/bin/env python3
"""Task transport for an isolated canonical fresh-install/firewall test."""
from pathlib import Path
import re
import subprocess

remote='user@192.168.1.100'
directory='/home/user/.cache/homelab-wg-easy-fresh-test'
image=next(line.split(': ',1)[1] for line in Path('ansible/roles/wg-easy/defaults/main.yml').read_text().splitlines() if line.startswith('wg_easy_image:'))
assert re.fullmatch(r'ghcr.io/wg-easy/wg-easy:15\.5\.0@sha256:[a-f0-9]{64}',image)
subprocess.run(['ssh',remote,'install -d -m 700 '+directory],check=True)
subprocess.run(['scp','ansible/roles/wg-easy/files/configure.py','ansible/roles/wg-easy/files/start.sh',
    'ansible/roles/wg-easy/tests/integration.py',remote+':'+directory+'/'],check=True)
subprocess.run(['ssh',remote,'sudo -n python3 '+directory+'/integration.py '+image],check=True)

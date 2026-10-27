#!/usr/bin/env python3
"""Private Task helper; operator enters remote sudo password in their terminal."""
import json
import os
from pathlib import Path
import subprocess
import sys

if not sys.stdin.isatty():
    raise SystemExit('Run task apps:wireguard:export in your own interactive terminal; never put the sudo password in chat')
remote='server@192.168.1.9'
directory='/home/server/.cache/homelab-wireguard'
os.umask(0o077)
target=Path('.generated/secrets/wireguard-legacy.json');target.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['ssh',remote,'install -d -m 700 '+directory],check=True)
subprocess.run(['scp','ansible/roles/wg-easy/files/export-legacy.py',remote+':'+directory+'/export.py'],check=True)
subprocess.run(['ssh','-t',remote,'sudo python3 '+directory+'/export.py --output '+directory+'/legacy.json'],check=True)
temporary=target.with_suffix('.tmp')
try:
    subprocess.run(['scp',remote+':'+directory+'/legacy.json',str(temporary)],check=True)
    temporary.chmod(0o600)
    bundle=json.loads(temporary.read_text())
    assert bundle['version']==1 and bundle['server']['address']=='10.115.145.1/24' and bundle['peers']
    temporary.replace(target)
    subprocess.run(['ssh',remote,'rm -f '+directory+'/legacy.json'],check=True)
    print('Legacy identity stored in ignored controller recovery file; '+str(len(bundle['peers']))+' peers. No keys printed.')
finally:
    temporary.unlink(missing_ok=True)

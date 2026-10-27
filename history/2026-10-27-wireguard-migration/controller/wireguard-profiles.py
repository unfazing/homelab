#!/usr/bin/env python3
"""Private Task transport: capture profile secrets over SSH; never print them."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


def main():
    os.umask(0o077)
    target=Path('.generated/secrets/wireguard-legacy.json')
    bundle=json.loads(target.read_text())
    contract={'server_public_key':bundle['server']['public_key'],'peers':bundle['peers']}
    source=Path('ansible/roles/wg-easy/files/export-client-profiles.py').read_text()
    result=subprocess.run(['ssh','-o','BatchMode=yes','server@192.168.1.9','python3 -c '+shlex.quote(source)],
        input=json.dumps(contract),text=True,capture_output=True,timeout=30)
    if result.returncode:raise RuntimeError('Source profile collection failed; no recovery file changed')
    profiles=json.loads(result.stdout)
    assert set(profiles)=={p['public_key'] for p in bundle['peers']},'Profile identity inventory mismatch'
    backup=target.with_name('wireguard-legacy-before-profiles.json')
    if not backup.exists():
        with backup.open('x') as stream:stream.write(target.read_text())
        backup.chmod(0o600)
    bundle['client_profiles']=profiles
    bundle['client_profiles_policy']={'endpoint':'donk.live:27272','dns':['192.168.1.100']}
    fd,name=tempfile.mkstemp(prefix='.wireguard-profiles-',dir=target.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(bundle,stream)
        os.replace(name,target)
    finally:Path(name).unlink(missing_ok=True)
    for peer in bundle['peers']:
        profile=profiles[peer['public_key']]
        print(json.dumps({'name':peer['name'],**{key:profile[key] for key in
            ('source_file','address','allowed_ips','dns','persistent_keepalive','mtu','endpoint')}}))
    print(str(len(profiles))+' active profiles stored with existing private keys in ignored mode-600 recovery state; no secrets printed')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Protected profile export failed: '+type(exc).__name__)
        raise SystemExit(1)

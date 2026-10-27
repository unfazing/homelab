#!/usr/bin/env python3
"""Pinned wg-easy 15.5 supported setup/API adapter; never log private responses."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from urllib import request, error

ROOT=Path('/etc/homelab/wg-easy')
DATA=Path('/srv/homelab/wireguard')
API_URL='http://127.0.0.1:51821/api/'
CONTAINER='wg-easy'


def migration(bundle):
    now=datetime.now(timezone.utc).isoformat()
    return {'server':{'privateKey':bundle['server']['private_key'],
        'publicKey':bundle['server']['public_key'],'address':'10.115.145.1'},
        'clients':{str(index):{'name':peer['name']+('' if peer['public_key'] in bundle.get('client_profiles',{}) else ' (external private key)'),
            'address':peer['address'],'publicKey':peer['public_key'],
            'privateKey':bundle.get('client_profiles',{}).get(peer['public_key'],{}).get('private_key',''),
            'preSharedKey':peer['preshared_key'] or 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
            'createdAt':now,'updatedAt':now,'enabled':True} for index,peer in enumerate(bundle['peers'],1)}}


def main():
    raw=(ROOT/'legacy.json').read_bytes();bundle=json.loads(raw)
    password=(ROOT/'admin-password').read_text().strip()
    auth='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    def call(path, payload=None, authenticated=True):
        req=request.Request(API_URL+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json',**({'Authorization':auth} if authenticated else {})})
        with request.urlopen(req,timeout=15) as response: return json.load(response)
    for attempt in range(40):
        try:
            connection=sqlite3.connect('file:'+str(DATA/'wg-easy.db')+'?mode=ro',uri=True,timeout=2)
            step=connection.execute('SELECT setup_step FROM general_table').fetchone()[0];connection.close()
            break
        except sqlite3.Error:
            if attempt==39: raise RuntimeError('wg-easy database did not initialize')
            time.sleep(1)
    marker=DATA/'.homelab-import.json'
    changed=False
    if step==1:
        call('setup/2',{'username':'admin','password':password,'confirmPassword':password},False)
        step=3;changed=True
    if step==3:
        # Set defaults before v14 import copies them into the legacy client rows.
        defaults=call('admin/userconfig')
        for key in ('id','createdAt','updatedAt'): defaults.pop(key,None)
        defaults.update(host='donk.live',port=27272,defaultDns=['192.168.1.100'],defaultAllowedIps=['0.0.0.0/0','::/0'])
        call('admin/userconfig',defaults)
        call('setup/migrate',{'file':json.dumps(migration(bundle))},False)
        changed=True
    elif step!=0:
        raise RuntimeError('Unexpected partially configured setup state; manual recovery required')
    interface=call('admin/interface')
    if interface['publicKey']!=bundle['server']['public_key'] or interface['ipv4Cidr']!='10.115.145.0/24':
        raise RuntimeError('Server identity/subnet mismatch; refusing replacement')
    wanted={'device':'eth0','port':27272,'mtu':bundle['server']['mtu']}
    if any(interface[key]!=value for key,value in wanted.items()):
        for key in ('name','publicKey','ipv4Cidr','ipv6Cidr','createdAt','updatedAt'): interface.pop(key,None)
        interface.update(wanted);call('admin/interface',interface);changed=True
    if not marker.exists():
        if 'client_profiles' in bundle:
            profiles=bundle['client_profiles'];policy=bundle['client_profiles_policy']
            assert policy=={'endpoint':'donk.live:27272','dns':['192.168.1.100']},'Unreviewed profile normalization'
            assert set(profiles)=={p['public_key'] for p in bundle['peers']},'Incomplete profile inventory'
            for client in call('client'):
                profile=profiles[client['publicKey']]
                derived=subprocess.check_output(['docker','exec','-i',CONTAINER,'wg','pubkey'],
                    input=profile['private_key']+'\n',text=True,stderr=subprocess.DEVNULL).strip()
                assert derived==client['publicKey'],'Profile key mismatch'
                details=call('client/'+str(client['id']))
                details.update(allowedIps=profile['allowed_ips'],dns=policy['dns'],
                    persistentKeepalive=profile['persistent_keepalive'],
                    mtu=profile['mtu'] if profile['mtu'] is not None else bundle['server']['mtu'])
                call('client/'+str(client['id']),details)
        call('admin/interface/restart',{})
        peers=call('client')
        assert {p['publicKey'] for p in peers}=={p['public_key'] for p in bundle['peers']},'Imported peer inventory mismatch'
        marker.write_text(json.dumps({'source_sha256':hashlib.sha256(raw).hexdigest(),'peers':len(peers),
            'client_profiles_imported':'client_profiles' in bundle}))
        marker.chmod(0o600);changed=True
    # Kernel identity check never reads or logs a private-key dump.
    public=subprocess.check_output(['docker','exec',CONTAINER,'wg','show','wg0','public-key'],text=True).strip()
    assert public==bundle['server']['public_key'],'Running identity differs from imported identity'
    print(json.dumps({'changed':changed,'imported':True,'subnet':'10.115.145.0/24'}))


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('wg-easy bootstrap failed: '+type(exc).__name__);raise SystemExit(1)

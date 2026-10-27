#!/usr/bin/env python3
"""Canonical fresh setup and service settings; never create/manage clients."""
import base64
import json
from pathlib import Path
import time
from urllib import request,error

ROOT=Path('/etc/homelab/wg-easy')
DATA=Path('/srv/homelab/wireguard')
API_URL='http://127.0.0.1:51821/api/'


def main():
    settings=json.loads((ROOT/'settings.json').read_text())
    password=(ROOT/'admin-password').read_text().strip()
    auth='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    def call(path,payload=None,authenticated=True):
        req=request.Request(API_URL+path,data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json',**({'Authorization':auth} if authenticated else {})})
        with request.urlopen(req,timeout=15) as response:return json.load(response)
    for attempt in range(40):
        try:call('information',authenticated=False);break
        except (error.URLError,TimeoutError):
            if attempt==39:raise
            time.sleep(1)
    changed=False;restart=False
    try:interface=call('admin/interface')
    except error.HTTPError as exc:
        if exc.code not in (401,403):raise
        # Existing admin + wrong password fails setup/2 without resetting it.
        call('setup/2',{'username':'admin','password':password,'confirmPassword':password},False)
        interface=call('admin/interface');changed=True
    try:
        call('setup/4',authenticated=False)
    except error.HTTPError as exc:
        if exc.code!=400:raise
    else:
        call('setup/4',{'host':settings['endpoint'],'port':settings['port']},False);changed=True
    public=interface['publicKey']
    marker=DATA/'.homelab-ready.json'
    if marker.exists():
        assert json.loads(marker.read_text())['server_public_key']==public,'Server identity changed; restore durable state'
    if interface['ipv4Cidr']!=settings['ipv4Cidr']:
        assert not call('client'),'Refusing to renumber a live peer population'
        call('admin/interface/cidr',{'ipv4Cidr':settings['ipv4Cidr'],'ipv6Cidr':interface['ipv6Cidr']})
        changed=True;restart=True;interface=call('admin/interface')
    defaults=call('admin/userconfig')
    desired={'host':settings['endpoint'],'port':settings['port'],'defaultDns':settings['dns'],
        'defaultAllowedIps':['0.0.0.0/0','::/0']}
    if any(defaults[k]!=v for k,v in desired.items()):
        for key in ('id','createdAt','updatedAt'):defaults.pop(key,None)
        defaults.update(desired);call('admin/userconfig',defaults);changed=True
    desired={'device':'eth0','port':settings['port'],'firewallEnabled':True}
    if any(interface[k]!=v for k,v in desired.items()):
        if interface['port']!=settings['port'] or interface['device']!='eth0':restart=True
        for key in ('name','publicKey','ipv4Cidr','ipv6Cidr','createdAt','updatedAt'):interface.pop(key,None)
        interface.update(desired);call('admin/interface',interface);changed=True
    if restart:call('admin/interface/restart',{})
    assert call('admin/interface')['firewallEnabled'],'Native firewall did not stay enabled'
    if not marker.exists():
        marker.write_text(json.dumps({'server_public_key':public}));marker.chmod(0o600);changed=True
    print(json.dumps({'changed':changed,'ready':True,'firewall_enabled':True}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('wg-easy service configuration failed: '+type(exc).__name__);raise SystemExit(1)

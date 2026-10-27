#!/usr/bin/env python3
"""Read-only service acceptance; external peer connectivity remains operator UAT."""
import base64
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import sys
from urllib import request,error


def verify_kernel_peers(bundle):
    def show(field):
        return subprocess.check_output(['docker','exec','wg-easy','wg','show','wg0',field],text=True).strip()
    # Compare PSKs in memory only; never include values in output or exceptions.
    allowed=dict(line.split(None,1) for line in show('allowed-ips').splitlines())
    psks=dict(line.split(None,1) for line in show('preshared-keys').splitlines())
    for peer in bundle['peers']:
        key=peer['public_key']
        assert allowed.get(key)==peer['address']+'/32','Imported peer address mismatch'
        assert psks.get(key)==(peer['preshared_key'] or '(none)'),'Imported peer PSK mismatch'


def verify_download(text,profile,peer,bundle):
    fields={}
    for line in text.splitlines():
        if '=' in line:
            key,value=line.split('=',1);fields[key.strip()]=value.strip()
    assert fields['PrivateKey']==profile['private_key'],'Downloaded client private key mismatch'
    assert fields['PublicKey']==bundle['server']['public_key'],'Downloaded server identity mismatch'
    assert fields['PresharedKey']==(peer['preshared_key'] or 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='),'Downloaded PSK mismatch'
    routes=lambda value:[str(ipaddress.ip_network(x.strip(),strict=False)) for x in value]
    assert routes(fields['AllowedIPs'].split(','))==routes(profile['allowed_ips']),'Downloaded client routes mismatch'
    assert [x.strip() for x in fields['DNS'].split(',')]==bundle['client_profiles_policy']['dns'],'Downloaded DNS mismatch'
    assert int(fields['PersistentKeepalive'])==profile['persistent_keepalive'],'Downloaded keepalive mismatch'
    assert fields['Endpoint']==bundle['client_profiles_policy']['endpoint'],'Downloaded endpoint mismatch'
    assert fields['Address']==peer['address']+'/32','Downloaded tunnel address mismatch'
    assert int(fields['MTU'])==(profile['mtu'] if profile['mtu'] is not None else bundle['server']['mtu']),'Downloaded MTU mismatch'


def main():
    host=sys.argv[1];real=socket.getaddrinfo
    socket.getaddrinfo=lambda name,*a,**kw:real('192.168.1.101' if name==host else name,*a,**kw)
    root=Path('/etc/homelab/wg-easy');password=(root/'admin-password').read_text().strip()
    bundle=json.loads((root/'legacy.json').read_text())
    auth='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    def call(path,authenticated=True,raw=False):
        req=request.Request('https://'+host+'/api/'+path,headers={'Authorization':auth} if authenticated else {})
        with request.urlopen(req,timeout=15) as response:body=response.read()
        assert password.encode() not in body and bundle['server']['private_key'].encode() not in body,'Credential appeared in API response'
        return body.decode() if raw else json.loads(body)
    try:
        call('admin/interface',False)
        raise AssertionError('Anonymous administration accepted')
    except error.HTTPError as exc:
        assert exc.code in (401,403),'Unexpected anonymous response'
    interface=call('admin/interface')
    assert interface['publicKey']==bundle['server']['public_key'] and interface['ipv4Cidr']=='10.115.145.0/24'
    assert interface['port']==27272
    verify_kernel_peers(bundle)
    config=call('admin/userconfig')
    assert config['host']=='donk.live' and config['port']==27272 and config['defaultDns']==['192.168.1.100']
    if 'client_profiles' in bundle:
        clients={p['publicKey']:p for p in call('client')}
        for peer in bundle['peers']:
            client=clients[peer['public_key']]
            verify_download(call('client/'+str(client['id'])+'/configuration',raw=True),
                bundle['client_profiles'][peer['public_key']],peer,bundle)
            assert '<svg' in call('client/'+str(client['id'])+'/qrcode.svg',raw=True),'QR export failed'
    container=json.loads(subprocess.check_output(['docker','inspect','wg-easy']))[0]
    assert not container['HostConfig']['Privileged'] and container['HostConfig']['NetworkMode']!='host'
    assert 'SYS_MODULE' not in container['HostConfig']['CapAdd']
    assert not any('docker.sock' in m['Destination'] or m['Destination']=='/lib/modules' for m in container['Mounts'])
    rules=subprocess.check_output(['docker','exec','wg-easy','iptables','-t','raw','-S','HOMELAB_WG_PEERS'],text=True)
    assert '-s 10.115.145.7/32 -j DROP' in rules and '--dport 3000 -j RETURN' in rules
    for port in ('53','51821'):assert '--dport '+port in rules
    assert not subprocess.check_output(['docker','exec','wg-easy','wg','show','wg0','allowed-ips'],text=True).strip()==''
    print('wg-easy HTTPS login boundary, preserved server identity/range, endpoint, pre-NAT restrictions and container isolation passed; client UAT and router cutover remain pending')


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('wg-easy acceptance failed: '+type(exc).__name__,file=sys.stderr);sys.exit(1)

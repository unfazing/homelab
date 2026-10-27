#!/usr/bin/env python3
"""Verify canonical service boundaries; clients are mutable runtime data."""
import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
from urllib import request,error


def verify_forward_guard(forward,native,input_rules):
    lines=forward.splitlines()
    assert '-P FORWARD DROP' in lines,'Missing default forwarding drop'
    jump='-A FORWARD -i wg0 -j WG_CLIENTS_wg0'
    drop='-A FORWARD -i wg0 -j DROP'
    assert jump in lines and drop in lines and lines.index(jump)<lines.index(drop),'Native firewall must precede fallback drop'
    returns=[n for n,line in enumerate(lines) if '-o wg0' in line and '--ctstate' in line and '-j ACCEPT' in line]
    assert returns and all(lines.index(drop)<n for n in returns),'Peer traffic must hit fallback drop before return allowances'
    for rule in ('-A FORWARD -i wg0 -j ACCEPT','-A FORWARD -o wg0 -j ACCEPT'):
        if rule in lines:assert lines.index(drop)<lines.index(rule),'Broad accept bypasses fallback guard'
    assert native.strip().endswith('-A WG_CLIENTS_wg0 -j DROP'),'Native allowlist lacks final drop'
    assert '-A INPUT -i wg0 -j DROP' in input_rules,'Tunnel clients can reach container-local services'
    assert '--ctstate RELATED,ESTABLISHED' in forward or '--ctstate ESTABLISHED,RELATED' in forward,'Missing established return allowance'


def main():
    host=sys.argv[1];real=socket.getaddrinfo
    socket.getaddrinfo=lambda name,*a,**kw:real('192.168.1.101' if name==host else name,*a,**kw)
    root=Path('/etc/homelab/wg-easy');password=(root/'admin-password').read_text().strip()
    settings=json.loads((root/'settings.json').read_text())
    auth='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    def call(path,authenticated=True):
        req=request.Request('https://'+host+'/api/'+path,headers={'Authorization':auth} if authenticated else {})
        with request.urlopen(req,timeout=15) as response:body=response.read()
        assert password.encode() not in body,'Administrator password appeared in API response'
        return json.loads(body)
    try:
        call('admin/interface',False);raise AssertionError('Anonymous administration accepted')
    except error.HTTPError as exc:assert exc.code in (401,403),'Unexpected anonymous response'
    interface=call('admin/interface')
    assert interface['ipv4Cidr']==settings['ipv4Cidr'] and interface['port']==settings['port']
    assert interface['firewallEnabled'],'Native per-client firewall is disabled'
    assert interface['publicKey']==json.loads(Path('/srv/homelab/wireguard/.homelab-ready.json').read_text())['server_public_key'],'Server identity changed'
    config=call('admin/userconfig')
    assert config['host']==settings['endpoint'] and config['port']==settings['port'] and config['defaultDns']==settings['dns']
    container=json.loads(subprocess.check_output(['docker','inspect','wg-easy']))[0]
    assert not container['HostConfig']['Privileged'] and container['HostConfig']['NetworkMode']!='host'
    assert 'SYS_MODULE' not in container['HostConfig']['CapAdd']
    assert not any('docker.sock' in m['Destination'] or m['Destination']=='/lib/modules' for m in container['Mounts'])
    def rules(chain):return subprocess.check_output(['docker','exec','wg-easy','iptables','-S',chain],text=True)
    verify_forward_guard(rules('FORWARD'),rules('WG_CLIENTS_wg0'),rules('INPUT'))
    print('Canonical wg-easy HTTPS/auth, native per-client firewall, fail-closed guards and container isolation passed; runtime peer traffic and router cutover need operator acceptance')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('wg-easy acceptance failed: '+type(exc).__name__,file=sys.stderr);sys.exit(1)

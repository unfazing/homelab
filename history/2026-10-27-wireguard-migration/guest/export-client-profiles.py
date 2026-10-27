#!/usr/bin/env python3
"""Read-only source helper. stdout is SECRET JSON, captured only by Task."""
import ipaddress
import json
from pathlib import Path
import subprocess
import sys


def parse(text):
    sections=[]
    for raw in text.splitlines():
        line=raw.split('#',1)[0].strip()
        if not line:continue
        if line.startswith('[') and line.endswith(']'):
            sections.append((line[1:-1],{}))
        elif '=' in line and sections:
            key,value=(p.strip() for p in line.split('=',1))
            if key in sections[-1][1]:raise ValueError('Duplicate profile field')
            sections[-1][1][key]=value
        else:raise ValueError('Invalid profile syntax')
    if [name for name,_ in sections]!=['Interface','Peer']:
        raise ValueError('Only one-interface, one-peer client profiles supported')
    return sections[0][1],sections[1][1]


def collect(contract,directory=Path('/home/server/configs')):
    expected={p['public_key']:p for p in contract['peers']}
    result={}
    for path in sorted(directory.glob('*.conf')):
        if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:continue
        raw=path.read_text()
        interface,peer=parse(raw)
        private=interface['PrivateKey']
        public=subprocess.check_output(['wg','pubkey'],input=private+'\n',text=True,stderr=subprocess.DEVNULL).strip()
        if public not in expected:continue  # Never export revoked/unrelated identities.
        if public in result:raise ValueError('Multiple profiles match an active identity')
        active=expected[public]
        assert peer['PublicKey']==contract['server_public_key'],'Profile targets another server'
        assert peer.get('PresharedKey','')==active['preshared_key'],'Profile PSK mismatch'
        addresses=[x.strip() for x in interface['Address'].split(',')]
        assert len(addresses)==1 and str(ipaddress.ip_interface(addresses[0]).ip)==active['address'],'Profile address mismatch'
        assert set(interface)<= {'PrivateKey','Address','DNS','MTU'},'Unsupported interface fields require review'
        assert set(peer)<= {'PublicKey','PresharedKey','AllowedIPs','Endpoint','PersistentKeepalive'},'Unsupported peer fields require review'
        routes=[x.strip() for x in peer['AllowedIPs'].split(',')]
        for route in routes:ipaddress.ip_network(route,strict=False)
        result[public]={'source_file':path.name,'original_config':raw,'private_key':private,
            'address':addresses[0],'allowed_ips':routes,
            'dns':[x.strip() for x in interface.get('DNS','').split(',') if x.strip()],
            'persistent_keepalive':int(peer.get('PersistentKeepalive','0')),
            'mtu':int(interface['MTU']) if 'MTU' in interface else None,
            'endpoint':peer['Endpoint']}
    assert result.keys()==expected.keys(),'Some active client profiles are missing'
    return result


if __name__=='__main__':
    try:print(json.dumps(collect(json.load(sys.stdin))))
    except Exception as exc:
        print('Protected profile collection failed: '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Operator-authenticated read-only export of the live legacy VPN identity."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import subprocess


def parse(text):
    interface = {}; peers = []; section = None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if line == '[Interface]': section = interface
        elif line == '[Peer]': section = {}; peers.append(section)
        elif '=' in line and section is not None:
            key, value = line.split('=', 1); section[key.strip()] = value.strip()
    return interface, peers


def peer_names(text):
    names={};name=None
    for line in text.splitlines():
        match=re.match(r'^\s*#+\s*begin\s+(.+?)\s*#*\s*$',line,re.IGNORECASE)
        if match:name=match.group(1).strip(' #')[:64]
        elif name and line.strip().startswith('PublicKey') and '=' in line:
            names[line.split('=',1)[1].strip()]=name;name=None
    return names


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args()
    assert os.geteuid()==0,'Run through sudo in your own terminal'
    owner=pwd.getpwnam(os.environ.get('SUDO_USER','server'))
    output=Path(args.output)
    expected=Path(owner.pw_dir)/'.cache/homelab-wireguard/legacy.json'
    assert output==expected and not output.is_symlink(),'Unexpected export location'
    assert output.parent.resolve()==expected.parent,'Unexpected symlink in export directory'
    # Never print showconf/dump; they contain private keys.
    raw=subprocess.check_output(['wg','showconf','wg0'],text=True)
    interface,peers=parse(raw)
    names=peer_names(Path('/etc/wireguard/wg0.conf').read_text())
    addresses=json.loads(subprocess.check_output(['ip','-j','address','show','wg0'],text=True))
    ipv4=[a for a in addresses[0]['addr_info'] if a['family']=='inet']
    assert len(ipv4)==1 and ipv4[0]['local']=='10.115.145.1' and ipv4[0]['prefixlen']==24,'Unexpected VPN range'
    public=subprocess.check_output(['wg','pubkey'],input=interface['PrivateKey']+'\n',text=True).strip()
    result={'version':1,'server':{'private_key':interface['PrivateKey'],'public_key':public,
        'address':'10.115.145.1/24','listen_port':int(interface['ListenPort']),
        'mtu':addresses[0]['mtu']},'peers':[]}
    for number,peer in enumerate(peers,1):
        allowed=[a.strip() for a in peer['AllowedIPs'].split(',')]
        assert len(allowed)==1 and ipaddress.ip_network(allowed[0]).prefixlen==32,'Unsupported site-to-site peer; review manually'
        assert ipaddress.ip_address(allowed[0].split('/')[0]) in ipaddress.ip_network('10.115.145.0/24')
        result['peers'].append({'name':names.get(peer['PublicKey'],'legacy-peer-'+str(number)),'public_key':peer['PublicKey'],
            'preshared_key':peer.get('PresharedKey',''),'address':allowed[0].split('/')[0]})
    result['firewall']={
        'nft':json.loads(subprocess.check_output(['nft','-j','list','ruleset'],text=True)),
        'iptables_nat':subprocess.check_output(['iptables','-t','nat','-S'],text=True)}
    assert result['peers'],'No peers found; refusing empty migration export'
    temporary=output.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream: json.dump(result,stream)
    os.chown(temporary,owner.pw_uid,owner.pw_gid);os.replace(temporary,output)
    print(f'Protected export prepared: {len(peers)} peers; source VPN was not changed')


if __name__=='__main__': main()

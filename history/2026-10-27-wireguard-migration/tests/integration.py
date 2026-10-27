#!/usr/bin/env python3
"""Disposable private API test; never consumes the legacy export or real peers."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import base64
from urllib.request import Request,urlopen

assert os.geteuid()==0,'Run through Task on the disposable guest boundary'
image=sys.argv[1]
assert image.startswith('ghcr.io/wg-easy/wg-easy:15.5.0@sha256:')
source=Path(__file__).parent
for module in ('wireguard','ip_tables','iptable_filter','iptable_nat','iptable_raw'):
    subprocess.run(['modprobe',module],check=True)
name='wg-easy-import-test'
created=False
mount=Path('/srv/homelab/wireguard')
assert subprocess.check_output(['findmnt','-n','-o','SOURCE,FSTYPE','--mountpoint',str(mount)],text=True).split()==['homelab-wireguard','virtiofs']
with tempfile.TemporaryDirectory(prefix='.homelab-wg-api-test-',dir=mount) as temp:
    root=Path(temp);data=root/'data';secret=root/'secret';data.mkdir();secret.mkdir()
    def keypair():
        private=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','wg',image,'genkey'],text=True).strip()
        public=subprocess.check_output(['docker','run','--rm','-i','--network','none','--entrypoint','wg',image,'pubkey'],input=private+'\n',text=True).strip()
        return private,public
    private,public=keypair();client_private,peer=keypair();dns_private,dns_peer=keypair()
    bundle={'version':1,'server':{'private_key':private,'public_key':public,'address':'10.115.145.1/24','mtu':1420,'listen_port':27272},
            'peers':[{'name':'test-peer','public_key':peer,'address':'10.115.145.3','preshared_key':''},
                     {'name':'dns-only','public_key':dns_peer,'address':'10.115.145.5','preshared_key':''}],
            'client_profiles':{
                peer:{'private_key':client_private,'allowed_ips':['0.0.0.0/0','::0/0'],'persistent_keepalive':25,'mtu':None},
                dns_peer:{'private_key':dns_private,'allowed_ips':['192.168.1.0/24'],'persistent_keepalive':0,'mtu':None}},
            'client_profiles_policy':{'endpoint':'donk.live:27272','dns':['192.168.1.100']}}
    (secret/'legacy.json').write_text(json.dumps(bundle));(secret/'admin-password').write_text('TemporaryTestPasswordOnly123456')
    command=['docker','run','--detach','--name',name,'--read-only','--cap-drop','ALL','--cap-add','NET_ADMIN','--cap-add','NET_RAW',
             '--security-opt','no-new-privileges:true','--sysctl','net.ipv4.ip_forward=1','--sysctl','net.ipv4.conf.all.src_valid_mark=1',
             '--sysctl','net.ipv6.conf.all.disable_ipv6=1','--memory','384m','--cpus','0.5','--pids-limit','128',
             '--tmpfs','/tmp:mode=1777','--tmpfs','/run:mode=0755','--publish','127.0.0.1:51829:51821/tcp',
             '--volume',str(data)+':/etc/wireguard','--volume',str(source/'start.sh')+':/homelab-start.sh:ro',
             '--env','DISABLE_IPV6=true','--env','DEBUG=','--env','DISABLE_VERSION_CHECK=true','--entrypoint','/bin/sh',image,'/homelab-start.sh']
    try:
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL);created=True
        spec=importlib.util.spec_from_file_location('bootstrap',source/'bootstrap.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.ROOT=secret;m.DATA=data;m.API_URL='http://127.0.0.1:51829/api/';m.CONTAINER=name
        outputs=[]
        for _ in range(2):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):m.main()
            outputs.append(json.loads(stream.getvalue()))
        assert outputs[0]['changed'] and not outputs[1]['changed'],'Import is not idempotent'
        auth='Basic '+base64.b64encode(b'admin:TemporaryTestPasswordOnly123456').decode()
        def api(path):
            with urlopen(Request('http://127.0.0.1:51829/api/'+path,headers={'Authorization':auth}),timeout=10) as r:return r.read().decode()
        clients=json.loads(api('client'))
        for client in clients:
            profile=bundle['client_profiles'][client['publicKey']]
            text=api('client/'+str(client['id'])+'/configuration')
            assert 'PrivateKey = '+profile['private_key'] in text,'Client private key changed'
            assert 'AllowedIPs = '+', '.join(profile['allowed_ips']) in text,'Per-client routing changed'
            assert 'DNS = 192.168.1.100' in text and 'Endpoint = donk.live:27272' in text,'Normalization mismatch'
            assert '<svg' in api('client/'+str(client['id'])+'/qrcode.svg'),'QR generation failed'
        print('Native import, original client keys, per-client routes, normalized DNS/endpoint, QR exports and no-op repeat passed; no production peers or public ports touched')
    except Exception as exc:
        print('Private import test failed: '+type(exc).__name__)
        raise
    finally:
        if created:subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

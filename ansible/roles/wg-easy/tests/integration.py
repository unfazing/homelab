#!/usr/bin/env python3
"""Fresh install with no legacy inputs and real WireGuard packet allow/deny tests."""
import base64
import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request,urlopen

assert os.geteuid()==0
image=sys.argv[1];assert image.startswith('ghcr.io/wg-easy/wg-easy:15.5.0@sha256:')
source=Path(__file__).parent
for module in ('wireguard','ip_tables','iptable_filter','iptable_nat','xt_comment','xt_conntrack'):
    subprocess.run(['modprobe',module],check=True)
network='homelab-wg-fresh-test';server='wg-easy-fresh-test';backend='wg-easy-fresh-backend';client='wg-easy-fresh-client'
created=[];made_network=False
run=lambda *args:subprocess.check_output(list(args),text=True,stderr=subprocess.PIPE)
for name in (server,backend,client):
    assert subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0,'Disposable test container name already in use'
assert subprocess.run(['docker','network','inspect',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0,'Disposable test network name already in use'
with tempfile.TemporaryDirectory(prefix='homelab-wg-fresh-') as temp:
    root=Path(temp);root.chmod(0o700);data=root/'data';secret=root/'secret';data.mkdir();secret.mkdir()
    (secret/'admin-password').write_text('DisposableFreshTestPassword123456')
    (secret/'settings.json').write_text(json.dumps({'endpoint':'test.invalid','port':27272,'ipv4Cidr':'10.115.145.0/24','dns':['172.30.92.3']}))
    auth='Basic '+base64.b64encode(b'admin:DisposableFreshTestPassword123456').decode()
    def api(path,payload=None,raw=False):
        req=Request('http://172.30.92.2:51821/api/'+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':auth,'Content-Type':'application/json'})
        with urlopen(req,timeout=10) as response:body=response.read().decode()
        return body if raw else json.loads(body)
    def start(name,address,extra,args):
        run('docker','run','-d','--name',name,'--network',network,'--ip',address,'--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges:true','--tmpfs','/tmp','--tmpfs','/run',*extra,image,*args)
        created.append(name)
    try:
        run('docker','network','create','--internal','--subnet','172.30.92.0/29',network);made_network=True
        start(server,'172.30.92.2',['--cap-add','NET_ADMIN','--cap-add','NET_RAW','--memory','384m',
            '--sysctl','net.ipv4.ip_forward=1','--sysctl','net.ipv4.conf.all.src_valid_mark=1','--sysctl','net.ipv6.conf.all.disable_ipv6=1',
            '-v',str(data)+':/etc/wireguard','-v',str(source/'start.sh')+':/homelab-start.sh:ro',
            '-e','DISABLE_IPV6=true','-e','DISABLE_VERSION_CHECK=true','-e','DEBUG=','--entrypoint','/bin/sh'],['/homelab-start.sh'])
        spec=importlib.util.spec_from_file_location('configure',source/'configure.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.ROOT=secret;m.DATA=data;m.API_URL='http://172.30.92.2:51821/api/'
        results=[]
        for _ in range(2):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):m.main()
            results.append(json.loads(stream.getvalue()))
        assert results[0]['changed'] and not results[1]['changed'],'Fresh setup is not idempotent'
        assert api('client')==[],'Canonical install created clients'
        api('client',{'name':'restricted-test','expiresAt':None})
        p=api('client')[0];public=p['publicKey']
        p=api('client/'+str(p['id']))
        p['firewallIps']=['172.30.92.3:3000/tcp','172.30.92.3:53/tcp','172.30.92.3:53/udp']
        api('client/'+str(p['id']),p)
        exported=api('client/'+str(p['id'])+'/configuration',raw=True)
        values={line.split('=',1)[0].strip():line.split('=',1)[1].strip() for line in exported.splitlines() if '=' in line}
        (root/'client.conf').write_text('[Interface]\nPrivateKey = '+values['PrivateKey']+'\n[Peer]\nPublicKey = '+values['PublicKey']+'\nPresharedKey = '+values['PresharedKey']+'\nAllowedIPs = 0.0.0.0/0\nEndpoint = 172.30.92.2:27272\n');(root/'client.conf').chmod(0o600)
        node="const net=require('net'),d=require('dgram');for(const p of [22,53,3000])net.createServer(s=>{s.on('error',()=>{});s.end('ok')}).listen(p,'0.0.0.0');for(const p of [53,3000]){let s=d.createSocket('udp4');s.on('message',(b,r)=>s.send(b,r.port,r.address));s.bind(p,'0.0.0.0')}"
        start(backend,'172.30.92.3',['--entrypoint','node'],['-e',node])
        start(client,'172.30.92.4',['--cap-add','NET_ADMIN','--cap-add','NET_RAW','-v',str(root/'client.conf')+':/test-client.conf:ro','--entrypoint','/bin/sh'],['-c','sleep 600'])
        run('docker','exec',client,'ip','link','add','wg0','type','wireguard')
        run('docker','exec',client,'wg','setconf','wg0','/test-client.conf')
        run('docker','exec',client,'ip','address','add',p['ipv4Address']+'/32','dev','wg0')
        run('docker','exec',client,'ip','link','set','wg0','up')
        for dest in ('172.30.92.3/32','10.115.145.1/32'):run('docker','exec',client,'ip','route','add',dest,'dev','wg0')
        def probe(host,port,proto='tcp'):
            script="const h=process.argv[1],p=+process.argv[2];setTimeout(()=>process.exit(2),2200);"
            script+=("const s=require('net').createConnection(p,h);s.on('connect',()=>{s.destroy();process.exit(0)});s.on('error',()=>process.exit(2));" if proto=='tcp' else
                "const s=require('dgram').createSocket('udp4');s.on('message',()=>process.exit(0));s.on('error',()=>process.exit(2));s.send('probe',p,h);")
            return subprocess.run(['docker','exec',client,'node','-e',script,host,str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
        time.sleep(1)
        assert probe('172.30.92.3',3000),'Allowed application TCP was blocked'
        assert probe('172.30.92.3',53) and probe('172.30.92.3',53,'udp'),'Allowed DNS transports were blocked'
        assert not probe('172.30.92.3',22),'Forbidden TCP port passed'
        assert not probe('172.30.92.3',3000,'udp'),'Wrong transport passed'
        assert not probe('10.115.145.1',51821),'Tunnel bypassed container-local INPUT guard'
        i=api('admin/interface')
        for key in ('name','publicKey','ipv4Cidr','ipv6Cidr','createdAt','updatedAt'):i.pop(key,None)
        i['firewallEnabled']=False;api('admin/interface',i)
        assert not probe('172.30.92.3',3000),'Disabling native filtering failed open'
        with contextlib.redirect_stdout(io.StringIO()):m.main()
        assert probe('172.30.92.3',3000),'Native filtering did not recover'
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):m.main()
        assert not json.loads(stream.getvalue())['changed'] and api('client')[0]['publicKey']==public,'Repeat setup changed runtime clients'
        run('docker','restart',server)
        for _ in range(40):
            try:
                if api('admin/interface')['firewallEnabled'] and probe('172.30.92.3',3000):break
            except Exception:pass
            time.sleep(1)
        else:raise AssertionError('Firewall did not recover after container restart')
        assert not probe('172.30.92.3',22),'Port restriction lost after restart'
        print('Fresh setup with zero clients, no-op convergence, real WireGuard TCP/UDP allow/deny, local-input denial, fail-closed disable and restart persistence passed; production identities untouched')
    except Exception as exc:
        print('Disposable fresh/firewall test failed: '+type(exc).__name__)
        if server in created:
            state=json.loads(run('docker','inspect',server))[0]['State']
            print('Test server state:',state['Status'],'exit',state['ExitCode'])
            logs=subprocess.run(['docker','logs','--tail','18',server],capture_output=True,text=True)
            print(re.sub(r'[A-Za-z0-9+/]{43}=','[redacted]',logs.stdout+logs.stderr))
        raise
    finally:
        for name in reversed(created):subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if made_network:subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

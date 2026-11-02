"""Opt-in isolated Go/Garage tests: no production data, identities or listeners."""
import base64
import json
import os
from pathlib import Path
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('HOMELAB_STORAGE_MONITOR_INTEGRATION') == '1', 'opt-in isolated Docker/Go/Garage integration')
class ObserverIntegration(unittest.TestCase):
    def test_scoped_token_real_garage_and_collector(self):
        roles=Path(__file__).resolve().parents[2]
        bundle={name:(roles/path).read_text() for name,path in {
            'collect.go':'storage-observer/files/collect.go',
            'collect_test.go':'storage-observer/files/collect_test.go',
            'reconcile.py':'garage/files/reconcile.py',
            'monitor-token.py':'garage/files/monitor-token.py',
        }.items()}
        script=REMOTE.replace('BUNDLE_BASE64',repr(base64.b64encode(json.dumps(bundle).encode()).decode()))
        result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','server@192.168.1.9','python3 -u -'],input=script,text=True,capture_output=True,timeout=300)
        self.assertEqual(result.returncode,0,result.stdout[-2000:]+result.stderr[-2000:])
        print(result.stdout.strip())


REMOTE=r'''
import base64,io,json,pathlib,secrets,subprocess,sys,tarfile,tempfile,time,urllib.request,urllib.error
bundle=json.loads(base64.b64decode(BUNDLE_BASE64))
builder='golang:1.27.3-alpine@sha256:b8c9b82affbbb82a020bbcf998dad2ba9516944ac7e883524642a481a9505e9c'
garage='dxflrs/garage:v2.5.0@sha256:677e5b758e4425a325b811c425c026bf35a4bf42f7ddbaa773de3f4fd779a5a5'
name='homelab-observer-test-'+secrets.token_hex(5)
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,timeout=150,**kw)
 if r.returncode:raise RuntimeError('Isolated command failed: '+str(args[:3])+' '+r.stderr.decode(errors='replace')[-500:])
 return r.stdout
stream=io.BytesIO()
with tarfile.open(fileobj=stream,mode='w') as tar:
 for key in ['collect.go','collect_test.go']:
  data=bundle[key].encode();info=tarfile.TarInfo(key);info.size=len(data);tar.addfile(info,io.BytesIO(data))
run(['docker','run','--rm','--interactive','--network','none','--memory','512m','--cpus','1','-e','GOMAXPROCS=2','-e','GOMEMLIMIT=256MiB',builder,'sh','-ceu','mkdir /src; cd /src; tar xf -; GO111MODULE=off go test -v; CGO_ENABLED=0 go build -o /collector collect.go'],input=stream.getvalue())
print('Go collector parser/allowlist/limits tests and build passed',flush=True)
with tempfile.TemporaryDirectory(prefix=name) as d:
 p=pathlib.Path(d);p.chmod(0o755)
 for key in ['reconcile.py','monitor-token.py']:(p/key).write_text(bundle[key])
 sys.path.insert(0,str(p));import reconcile
 import importlib.util
 spec=importlib.util.spec_from_file_location('monitor_token',p/'monitor-token.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 config=p/'garage.toml';config.write_text('metadata_dir="/data/meta"\ndata_dir="/data/objects"\ndb_engine="lmdb"\nreplication_factor=1\nrpc_bind_addr="0.0.0.0:3901"\nrpc_public_addr="127.0.0.1:3901"\nrpc_secret="'+secrets.token_hex(32)+'"\n[s3_api]\ns3_region="homelab"\napi_bind_addr="0.0.0.0:3900"\n[admin]\napi_bind_addr="0.0.0.0:3903"\nadmin_token="'+secrets.token_hex(32)+'"\n');config.chmod(0o644)
 tokenfile=p/'monitor-token';tokenfile.touch(mode=0o600)
 try:
  run(['docker','run','--detach','--name',name,'--memory','512m','--cpus','0.5','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/data:rw,size=128m','--mount','type=bind,src='+str(config)+',dst=/etc/garage.toml,readonly',garage])
  api=reconcile.docker_api(name)
  for _ in range(60):
   try:api('GetClusterStatus');break
   except Exception:time.sleep(.5)
  fixture={'container':name,'bucket':'monitor-test','zone':'red','capacity_gib':1,'key_id':'GK'+secrets.token_hex(12),'key_secret':secrets.token_hex(32)}
  reconcile.reconcile(fixture,api)
  assert module.reconcile_token(api,tokenfile)['changed']
  assert not module.reconcile_token(api,tokenfile)['changed']
  token=tokenfile.read_text().strip()
  info=json.loads(run(['docker','inspect',name]))[0]
  address=info['NetworkSettings']['Networks']['bridge']['IPAddress']
  def call(path,method='GET',data=None):
   req=urllib.request.Request('http://'+address+':3903'+path,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method,data=json.dumps(data).encode() if data is not None else None)
   with urllib.request.urlopen(req,timeout=10) as r:return r.read()
  stats=json.loads(call('/v2/GetClusterStatistics'));assert stats['bucketCount']==1 and stats['totalObjectCount']==0
  assert json.loads(call('/v2/GetClusterHealth'))['status']=='healthy'
  metrics=call('/metrics');assert b'garage' in metrics
  for path,method,data in [('/v2/ListKeys','GET',None),('/v2/CreateBucket','POST',{'globalAlias':'must-not-exist'}),('/v2/CreateAdminToken','POST',{'name':'must-not-exist','scope':['*']})]:
   try:call(path,method,data)
   except urllib.error.HTTPError as e:assert e.code==403
   else:raise AssertionError('Scoped token authorized forbidden operation')
  print('Garage real scoped-token read/denied writes and idempotent provisioning passed',flush=True)
 finally:
  subprocess.run(['docker','rm','--force','--volumes',name],capture_output=True)
'''

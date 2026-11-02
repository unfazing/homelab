"""Opt-in actual PostgreSQL test, isolated on red with no published ports/data.

HOMELAB_POSTGRESQL_INTEGRATION=1 python3 -m unittest discover \
  -s ansible/roles/postgresql/tests -p test_integration.py -v
"""
import base64
import json
import os
import pathlib
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('HOMELAB_POSTGRESQL_INTEGRATION') == '1', 'opt-in isolated Docker/PostgreSQL integration')
class PostgreSQLIntegration(unittest.TestCase):
    def test_actual_passwords_grants_convergence_and_retention(self):
        root = pathlib.Path(__file__).parents[1]
        bundle = {name: (root / path).read_text() for name, path in {
            'reconcile.py': 'files/reconcile.py', 'verify.py': 'files/verify.py', 'monitor.py': 'files/monitor.py',
            'pg_hba.conf.j2': 'templates/pg_hba.conf.j2'}.items()}
        payload = base64.b64encode(json.dumps(bundle).encode()).decode()
        remote = REMOTE.replace('BUNDLE_BASE64', repr(payload))
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                 os.environ.get('HOMELAB_POSTGRESQL_TEST_HOST', 'server@192.168.1.9'),
                                 'python3 -u -'], input=remote, capture_output=True, text=True, timeout=240)
        self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-1000:])
        self.assertIn('postgresql integration passed', result.stdout)


REMOTE = r'''
import base64,json,os,pathlib,secrets,subprocess,tempfile,time,sys,importlib.util
import jinja2
bundle=json.loads(base64.b64decode(BUNDLE_BASE64))
image='postgres:18.6-bookworm@sha256:5c4783a8cc3f0074912164f94dfa1be4e043438f0f707cf968d7af9a0d31a2c8'
container='homelab-pg-test-'+secrets.token_hex(6)
def command(args,**kwargs):
 r=subprocess.run(args,text=True,capture_output=True,timeout=120,**kwargs)
 if r.returncode:raise RuntimeError('Isolated test command failed: '+args[0]+' '+(args[1] if len(args)>1 else ''))
 return r.stdout
with tempfile.TemporaryDirectory(prefix='homelab-postgresql-integration-') as directory:
 p=pathlib.Path(directory)
 for name,source in bundle.items():(p/name).write_text(source)
 config={'container':container,'admin_password':secrets.token_urlsafe(32),'applications':[],'monitor_password':secrets.token_urlsafe(32)}
 for name in ['book','second']:
  config['applications'].append({'database':name+'_dev','owner_role':name+'_owner','migration_role':name+'_migrator','runtime_role':name+'_app','runtime_password':secrets.token_urlsafe(32),'migration_password':secrets.token_urlsafe(32)})
 policy=p/'policy.json';policy.write_text(json.dumps(config));policy.chmod(0o600)
 admin=p/'admin';admin.write_text(config['admin_password']);admin.chmod(0o600)
 hba=p/'pg_hba.conf';hba.write_text(jinja2.Environment().from_string(bundle['pg_hba.conf.j2']).render(postgresql_applications=config['applications'],storage_monitoring_enabled=True,storage_observer_address='127.0.0.1'));hba.chmod(0o644)
 # The PostgreSQL UID needs traversal to the readonly HBA fixture; the secret
 # itself remains mode 0600 and is consumed by the initial root entrypoint.
 p.chmod(0o755)
 try:
  command(['docker','pull',image])
  command(['docker','run','--detach','--name',container,'--network','none','--read-only','--cap-drop','ALL','--cap-add','CHOWN','--cap-add','DAC_OVERRIDE','--cap-add','FOWNER','--cap-add','SETUID','--cap-add','SETGID','--security-opt','no-new-privileges:true','--memory','1g','--cpus','1','--tmpfs','/var/lib/postgresql:rw,size=384m','--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','--tmpfs','/var/run/postgresql:rw,nosuid,nodev,size=16m,mode=3775','--mount','type=bind,src='+str(hba)+',dst=/etc/postgresql/pg_hba.conf,readonly','--mount','type=bind,src='+str(admin)+',dst=/run/secrets/admin,readonly','-e','POSTGRES_PASSWORD_FILE=/run/secrets/admin','-e','POSTGRES_INITDB_ARGS=--auth-local=peer --auth-host=scram-sha-256',image,'postgres','-c','hba_file=/etc/postgresql/pg_hba.conf','-c','log_min_error_statement=panic'])
  for _ in range(50):
   r=subprocess.run(['docker','exec','--user','postgres',container,'pg_isready','--host','127.0.0.1','--quiet'],capture_output=True)
   if r.returncode==0:break
   time.sleep(0.5)
  else:raise RuntimeError('Isolated PostgreSQL did not become ready')
  inspected=json.loads(command(['docker','inspect',container]))[0]
  assert inspected['HostConfig']['CapDrop']==['ALL']
  assert {cap.removeprefix('CAP_') for cap in inspected['HostConfig']['CapAdd']}=={'CHOWN','DAC_OVERRIDE','FOWNER','SETUID','SETGID'}
  status=command(['docker','exec','--user','postgres',container,'cat','/proc/1/status'])
  assert int(next(line.split(':',1)[1].strip() for line in status.splitlines() if line.startswith('CapEff:')),16)==0
  first=json.loads(command(['python3',str(p/'reconcile.py'),'--config',str(policy)]));assert first['changed']
  second=json.loads(command(['python3',str(p/'reconcile.py'),'--config',str(policy)]));assert not second['changed'],second
  verified=json.loads(command(['python3',str(p/'verify.py'),'--config',str(policy)]));assert verified['verified'] and len(verified['applications'])==2
  sys.path.insert(0,str(p));import reconcile
  db=reconcile.Sql(container)
  app=config['applications'][0]
  db.run('CREATE TABLE public.retention_check (value integer); INSERT INTO public.retention_check VALUES (42);',app['database'],role=app['migration_role'],password=app['migration_password'])
  third=json.loads(command(['python3',str(p/'reconcile.py'),'--config',str(policy)]));assert not third['changed'],third
  result=db.run('SELECT value FROM public.retention_check;',app['database'],role=app['runtime_role'],password=app['runtime_password']);assert result.stdout.strip()=='42'
  monitoring=json.loads(command(['python3',str(p/'monitor.py'),'--config',str(policy)]));assert monitoring['changed']
  assert not json.loads(command(['python3',str(p/'monitor.py'),'--config',str(policy)]))['changed']
  result=db.run('SELECT homelab_monitor.snapshot();','postgres',role='homelab_monitor',password=config['monitor_password'])
  aggregate=json.loads(result.stdout);assert aggregate['databases']==2 and aggregate['database_bytes']>0
  db.run('CREATE TABLE public.logical_partition (id integer) PARTITION BY RANGE (id); CREATE TABLE public.physical_partition PARTITION OF public.logical_partition FOR VALUES FROM (0) TO (100);',app['database'],role=app['migration_role'],password=app['migration_password'])
  result=db.run('SELECT homelab_monitor.snapshot();',app['database'],role='homelab_monitor',password=config['monitor_password'])
  assert json.loads(result.stdout)['tables']==2,'Count logical tables once, not partitions'
  for sql in ['SELECT * FROM public.retention_check;', 'CREATE TABLE public.forbidden (x integer);','SET ROLE postgres;', 'CREATE OR REPLACE FUNCTION homelab_monitor.snapshot() RETURNS jsonb LANGUAGE sql AS $$SELECT NULL::jsonb$$;']:
   denied=db.run(sql,app['database'],role='homelab_monitor',password=config['monitor_password'],allow_failure=True);assert denied.returncode!=0
  assert db.run('SELECT homelab_monitor.snapshot();','postgres',role='homelab_monitor',password=secrets.token_urlsafe(32),allow_failure=True).returncode!=0
  assert db.value("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='homelab_monitor');")==0
  assert not json.loads(command(['python3',str(p/'monitor.py'),'--config',str(policy)]))['changed']
  print('monitor integration passed: fixed aggregates, no row/DDL/role/function writes, SCRAM denial, logical partition counts, no-op convergence')
  # Removing a contract must not drop data/roles. The parent updates HBA on a
  # real convergence; this test targets the SQL helper's non-destructive scope.
  config['applications']=config['applications'][:1];policy.write_text(json.dumps(config));policy.chmod(0o600)
  command(['python3',str(p/'reconcile.py'),'--config',str(policy)])
  assert db.value("SELECT to_json(datname) FROM pg_database WHERE datname='second_dev';")=='second_dev'
  # A source password change rotates exactly its role and then converges.
  config['applications'][0]['runtime_password']=secrets.token_urlsafe(32);policy.write_text(json.dumps(config));policy.chmod(0o600)
  rotated=json.loads(command(['python3',str(p/'reconcile.py'),'--config',str(policy)]));assert rotated['changed']
  assert not json.loads(command(['python3',str(p/'reconcile.py'),'--config',str(policy)]))['changed']
  command(['python3',str(p/'verify.py'),'--config',str(policy)])
  print('postgresql integration passed: capability drop/allowlist and zero postmaster capabilities, SCRAM, 2-app isolation, runtime DDL denial, DML/default grants, no-op convergence, data retention, rotation')
 finally:
  subprocess.run(['docker','rm','--force','--volumes',container],capture_output=True)
'''


if __name__ == '__main__':
    unittest.main()

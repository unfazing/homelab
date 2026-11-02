#!/usr/bin/python3
"""Install fixed aggregate functions; the login receives no application data grants."""
import argparse
import json
import sys
from reconcile import (Sql, ProvisionError, load_config, identifier, literal, ensure_role,
                       ensure_membership, database_acl, acl_set, PASSWORD)

ROLE = 'homelab_monitor'
SCHEMA = 'homelab_monitor'


def bodies(config):
    names = ','.join(literal(a['database']) for a in config['applications'])
    return {
        'postgres': f"""SELECT pg_catalog.jsonb_build_object(
 'databases', (SELECT count(*) FROM pg_catalog.pg_database WHERE datname IN ({names})),
 'database_bytes', (SELECT coalesce(sum(pg_catalog.pg_database_size(oid)),0) FROM pg_catalog.pg_database WHERE datname IN ({names})),
 'transactions', (SELECT coalesce(sum(xact_commit+xact_rollback),0) FROM pg_catalog.pg_stat_database WHERE datname IN ({names})),
 'reset_id', (SELECT pg_catalog.md5(coalesce(string_agg(datid::text||':'||coalesce(stats_reset::text,''),',' ORDER BY datid),'')) FROM pg_catalog.pg_stat_database WHERE datname IN ({names})),
 'connections', (SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_catalog.pg_backend_pid()),
 'active', (SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE backend_type='client backend' AND state='active' AND pid<>pg_catalog.pg_backend_pid()),
 'blocked', (SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE backend_type='client backend' AND wait_event_type='Lock' AND pid<>pg_catalog.pg_backend_pid()),
 'connection_limit', pg_catalog.current_setting('max_connections')::integer,
 'server_start', extract(epoch FROM pg_catalog.pg_postmaster_start_time())::bigint
)""",
        **{a['database']: """SELECT pg_catalog.jsonb_build_object('tables', count(*))
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p') AND NOT c.relispartition
AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_toast' AND n.nspname !~ '^pg_temp'
AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d WHERE d.classid='pg_catalog.pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')"""
           for a in config['applications']}}


def reconcile_monitor(config, db=None):
    password = config.get('monitor_password', '')
    if not PASSWORD.fullmatch(password):
        raise ProvisionError('Missing protected monitor credential')
    for app in config['applications']:
        if ROLE in [app[k] for k in ['owner_role', 'runtime_role', 'migration_role']]:
            raise ProvisionError('Monitoring identity collides with application identity')
    db = db or Sql(config['container'])
    changes = []
    ensure_role(db, ROLE, True, password, changes, connection_limit=3)
    ensure_membership(db, ROLE, None, changes)
    expected_settings = ['default_transaction_read_only=on', 'lock_timeout=1s', 'statement_timeout=3s']
    settings = db.value('SELECT to_json(rolconfig) FROM pg_roles WHERE rolname=' + literal(ROLE) + ';') or []
    if sorted(settings) != expected_settings:
        db.run('ALTER ROLE homelab_monitor RESET ALL; ALTER ROLE homelab_monitor SET default_transaction_read_only=on; ALTER ROLE homelab_monitor SET statement_timeout=\'3s\'; ALTER ROLE homelab_monitor SET lock_timeout=\'1s\';')
        changes.append('restrict monitor session')
    for database, body in bodies(config).items():
        quoted_db = '"postgres"' if database == 'postgres' else identifier(database)
        if database_acl(db, database, ROLE) != {'CONNECT'}:
            db.run('REVOKE ALL ON DATABASE ' + quoted_db + ' FROM homelab_monitor; GRANT CONNECT ON DATABASE ' + quoted_db + ' TO homelab_monitor;')
            changes.append('monitor connect ' + database)
        schema = db.value("SELECT to_json(pg_get_userbyid(nspowner)) FROM pg_namespace WHERE nspname='homelab_monitor';", database)
        if schema is None:
            db.run('CREATE SCHEMA homelab_monitor AUTHORIZATION postgres;', database)
            changes.append('monitor schema ' + database)
        elif schema != 'postgres':
            raise ProvisionError('Monitoring schema has unexpected owner; refusing adoption')
        rights = db.value("SELECT coalesce(json_agg(a.grantee::text||':'||a.privilege_type ORDER BY a.grantee,a.privilege_type),'[]'::json) FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='homelab_monitor' AND a.grantee<>n.nspowner;", database)
        monitor_oid = db.value("SELECT to_json(oid::text) FROM pg_roles WHERE rolname='homelab_monitor';")
        if rights != [monitor_oid + ':USAGE']:
            # Do not silently revoke unrelated identities: fail unexpected grants.
            if any(not r.startswith(('0:', monitor_oid + ':')) for r in rights):
                raise ProvisionError('Unexpected monitoring schema grant')
            db.run('REVOKE ALL ON SCHEMA homelab_monitor FROM PUBLIC,homelab_monitor; GRANT USAGE ON SCHEMA homelab_monitor TO homelab_monitor;', database)
            changes.append('monitor schema ACL ' + database)
        row = db.value("SELECT row_to_json(r) FROM (SELECT p.prosrc,p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner) owner FROM pg_proc p WHERE p.oid=to_regprocedure('homelab_monitor.snapshot()')) r;", database)
        if row != {'prosrc': body, 'prosecdef': True, 'proconfig': ['search_path=pg_catalog'], 'owner': 'postgres'}:
            if row and row['owner'] != 'postgres':
                raise ProvisionError('Unexpected aggregate function owner')
            db.run('CREATE OR REPLACE FUNCTION homelab_monitor.snapshot() RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS ' + literal(body) + ';', database)
            changes.append('monitor aggregate function ' + database)
        grants = db.value("SELECT coalesce(json_agg(a.grantee::text||':'||a.privilege_type ORDER BY a.grantee,a.privilege_type),'[]'::json) FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid='homelab_monitor.snapshot()'::regprocedure AND a.grantee<>p.proowner;", database)
        if grants != [monitor_oid + ':EXECUTE']:
            if any(not r.startswith(('0:', monitor_oid + ':')) for r in grants):
                raise ProvisionError('Unexpected aggregate function grant')
            db.run('REVOKE ALL ON FUNCTION homelab_monitor.snapshot() FROM PUBLIC,homelab_monitor; GRANT EXECUTE ON FUNCTION homelab_monitor.snapshot() TO homelab_monitor;', database)
            changes.append('monitor function ACL ' + database)
    return {'changed': bool(changes)}


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--config', required=True)
        args = parser.parse_args()
        print(json.dumps(reconcile_monitor(load_config(args.config))))
    except Exception:
        print('Aggregate monitoring convergence failed; inspect protected policy locally.', file=sys.stderr)
        raise SystemExit(1)

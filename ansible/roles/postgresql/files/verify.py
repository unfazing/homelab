#!/usr/bin/python3
"""Validate app auth/privileges; all object probes are rolled back."""
import argparse
import json
import secrets
import sys

from reconcile import Sql, ProvisionError, identifier, literal, load_config, role_record


def verify(config):
    db = Sql(config['container'])
    checks = []
    for app in config['applications']:
        database = app['database']
        runtime, migration, owner = (app[k] for k in ('runtime_role', 'migration_role', 'owner_role'))
        for role in (runtime, migration, owner):
            row = role_record(db, role)
            if not row or any(row[k] for k in ('rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication', 'rolbypassrls')):
                raise ProvisionError('Application role has an unexpected privileged attribute')
        for kind, role in [('runtime', runtime), ('migration', migration)]:
            result = db.run('SELECT current_user;', database, role=role, password=app[kind + '_password'])
            if result.stdout.strip() != role:
                raise ProvisionError('TCP login identity mismatch')
            denied = db.run('SELECT 1;', 'postgres', role=role, password=app[kind + '_password'], allow_failure=True)
            if denied.returncode == 0:
                raise ProvisionError('Application login unexpectedly reaches the administrator database')
        for other in config['applications']:
            if other['database'] == database:
                continue
            denied = db.run('SELECT 1;', other['database'], role=runtime, password=app['runtime_password'], allow_failure=True)
            if denied.returncode == 0:
                raise ProvisionError('Runtime unexpectedly connects to another application database')
        probe = '__homelab_verify_' + secrets.token_hex(8)
        probe_quoted = '"' + probe + '"'
        denied = db.run('BEGIN; CREATE TABLE public.' + probe_quoted + '(id integer); ROLLBACK;', database, role=runtime, password=app['runtime_password'], allow_failure=True)
        if denied.returncode == 0:
            raise ProvisionError('Runtime unexpectedly creates schema objects')
        migration_probe = 'BEGIN; CREATE TABLE public.' + probe_quoted + '(id integer); ROLLBACK;'
        db.run(migration_probe, database, role=migration, password=app['migration_password'])
        # Test the actual default grants for objects made by either permitted DDL
        # identity. PostgreSQL transactions clean up tables/sequences even on error.
        for creator in (owner, migration):
            sql = ('BEGIN; SET ROLE ' + identifier(creator) + '; CREATE TABLE public.' + probe_quoted + '(id bigint GENERATED ALWAYS AS IDENTITY, value text); RESET ROLE; SET ROLE ' + identifier(runtime) + '; INSERT INTO public.' + probe_quoted + "(value) VALUES ('probe'); UPDATE public." + probe_quoted + " SET value='updated'; SELECT value FROM public." + probe_quoted + '; DELETE FROM public.' + probe_quoted + '; ROLLBACK;')
            db.run(sql, database)
        checks.append({'database': database, 'runtime_login': True, 'migration_login': True, 'runtime_ddl_denied': True, 'cross_database_denied': True, 'default_dml_grants': True})
    return {'verified': True, 'applications': checks}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    args = p.parse_args()
    print(json.dumps(verify(load_config(args.config))))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('PostgreSQL boundary verification failed; inspect protected configuration locally.', file=sys.stderr)
        raise SystemExit(1)

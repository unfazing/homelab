#!/usr/bin/python3
"""Converge explicit PostgreSQL app roles/databases without exposing passwords.

The caller runs as the rootless Docker runtime owner. Administration uses the
postgres OS identity over its container-local Unix socket. All SQL is sent on
stdin; password changes use SCRAM verifiers, not cleartext SQL literals.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys

IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,46}')
CONTAINER = re.compile(r'[a-z][a-z0-9_.-]{0,62}')
PASSWORD = re.compile(r'[A-Za-z0-9_-]{24,128}')
TABLE_RIGHTS = {'SELECT', 'INSERT', 'UPDATE', 'DELETE'}
SEQUENCE_RIGHTS = {'USAGE', 'SELECT'}


class ProvisionError(RuntimeError):
    pass


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value.startswith('pg_') or value in ('postgres', 'public', 'template0', 'template1'):
        raise ProvisionError('Invalid or reserved managed identifier')
    return '"' + value + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def validate(config):
    if not isinstance(config, dict) or not CONTAINER.fullmatch(config.get('container', '')):
        raise ProvisionError('Invalid container identity')
    if not PASSWORD.fullmatch(config.get('admin_password', '')):
        raise ProvisionError('Administrator password must be a generated 24–128 character URL-safe ASCII secret')
    apps = config.get('applications')
    if not isinstance(apps, list) or not apps:
        raise ProvisionError('At least one explicitly configured application is required')
    seen_roles = set()
    seen_dbs = set()
    for app in apps:
        for field in ('database', 'owner_role', 'migration_role', 'runtime_role'):
            identifier(app.get(field))
            if app.get(field) == 'homelab_monitor':
                raise ProvisionError('Application identity collides with the monitoring namespace')
        if app['database'] in seen_dbs:
            raise ProvisionError('Duplicate application database')
        seen_dbs.add(app['database'])
        for field in ('owner_role', 'migration_role', 'runtime_role'):
            if app[field] in seen_roles:
                raise ProvisionError('Managed application roles must be distinct across databases')
            seen_roles.add(app[field])
        for field in ('runtime_password', 'migration_password'):
            if not PASSWORD.fullmatch(app.get(field, '')):
                raise ProvisionError('Application passwords must be generated 24–128 character URL-safe ASCII secrets')
        if app['runtime_password'] == app['migration_password'] or config['admin_password'] in (app['runtime_password'], app['migration_password']):
            raise ProvisionError('Administrator, runtime and migration credentials must differ')
    if 'monitor_password' in config:
        monitor = config['monitor_password']
        other = [config['admin_password']] + [app[k] for app in apps for k in ('runtime_password','migration_password')]
        if not isinstance(monitor, str) or not PASSWORD.fullmatch(monitor) or monitor in other:
            raise ProvisionError('Monitoring requires a separate generated credential')
    return config


def load_config(path):
    path = pathlib.Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o027:
        raise ProvisionError('Credential policy must not be writable by group or accessible by others')
    return validate(json.loads(path.read_text()))


def scram_verifier(password, salt=None):
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac('sha256', password.encode('ascii'), salt, 4096)
    stored = hashlib.sha256(hmac.digest(salted, b'Client Key', 'sha256')).digest()
    server = hmac.digest(salted, b'Server Key', 'sha256')
    b64 = lambda value: base64.b64encode(value).decode('ascii')
    return 'SCRAM-SHA-256$4096:' + b64(salt) + '$' + b64(stored) + ':' + b64(server)


def password_matches(password, verifier):
    try:
        kind, iterations_salt, keys = verifier.split('$')
        iterations, salt = iterations_salt.split(':')
        if kind != 'SCRAM-SHA-256' or int(iterations) != 4096:
            return False
        return hmac.compare_digest(scram_verifier(password, base64.b64decode(salt, validate=True)), verifier)
    except (ValueError, TypeError, AttributeError):
        return False


class Sql:
    def __init__(self, container):
        self.container = container

    def run(self, sql, database='postgres', *, role=None, password=None, allow_failure=False):
        args = ['docker', 'exec', '--interactive', '--user', 'postgres', self.container]
        if role is None:
            args += ['psql', '--no-psqlrc', '--set', 'ON_ERROR_STOP=1', '--tuples-only', '--no-align', '--username', 'postgres', '--dbname', database]
            payload = sql
        else:
            # The secret arrives on stdin, never docker -e arguments or output.
            args += ['sh', '-ceu', 'IFS= read -r PGPASSWORD; export PGPASSWORD; export PGSSLMODE=disable; exec psql --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align --host=127.0.0.1 --username="$1" --dbname="$2"', 'postgresql-auth-check', role, database]
            payload = password + '\n' + sql
        result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=45)
        if result.returncode and not allow_failure:
            raise ProvisionError('PostgreSQL operation failed; inspect protected server configuration locally')
        return result

    def value(self, sql, database='postgres'):
        output = self.run(sql, database).stdout.strip()
        return json.loads(output) if output else None


def role_record(db, name):
    return db.value("SELECT row_to_json(r) FROM (SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls,rolconnlimit,rolpassword FROM pg_authid WHERE rolname=" + literal(name) + ') r;')


def ensure_role(db, name, login, password, changes, connection_limit=10):
    quoted = identifier(name)
    row = role_record(db, name)
    options = ' NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS ' + ('LOGIN' if login else 'NOLOGIN') + ' CONNECTION LIMIT ' + (str(connection_limit) if login else '-1')
    if row is None:
        password_sql = ' PASSWORD ' + literal(scram_verifier(password)) if login else ''
        db.run('CREATE ROLE ' + quoted + ' WITH' + options + password_sql + ';')
        changes.append('create role ' + name)
    else:
        flags_ok = not any(row[k] for k in ('rolsuper', 'rolcreaterole', 'rolcreatedb', 'rolreplication', 'rolbypassrls')) and row['rolinherit'] and row['rolcanlogin'] == login and row['rolconnlimit'] == (connection_limit if login else -1)
        if not flags_ok:
            db.run('ALTER ROLE ' + quoted + ' WITH' + options + ';')
            changes.append('restrict role ' + name)
        if login and not password_matches(password, row['rolpassword']):
            db.run('ALTER ROLE ' + quoted + ' PASSWORD ' + literal(scram_verifier(password)) + ';')
            changes.append('update credential ' + name)
        if not login and row['rolpassword'] is not None:
            db.run('ALTER ROLE ' + quoted + ' PASSWORD NULL;')
            changes.append('clear owner credential ' + name)


def ensure_membership(db, member, expected_owner, changes):
    rows = db.value("SELECT coalesce(json_agg(r),'[]'::json) FROM (SELECT parent.rolname,m.admin_option,m.inherit_option,m.set_option FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=" + literal(member) + ') r;')
    valid = False
    for row in rows:
        if row['rolname'] == expected_owner and not row['admin_option'] and row['inherit_option'] and row['set_option']:
            valid = True
            continue
        db.run('REVOKE ' + '"' + row['rolname'].replace('"', '""') + '" FROM ' + identifier(member) + ';')
        changes.append('remove excess membership ' + member)
    if expected_owner and not valid:
        db.run('GRANT ' + identifier(expected_owner) + ' TO ' + identifier(member) + ';')
        changes.append('grant migration ownership ' + member)


def acl_set(db, query, database='postgres'):
    return set(db.value(query, database) or [])


def database_acl(db, name, role):
    who = '0' if role is None else '(SELECT oid FROM pg_roles WHERE rolname=' + literal(role) + ')'
    return acl_set(db, "SELECT coalesce(json_agg(privilege_type),'[]'::json) FROM pg_database d CROSS JOIN LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a WHERE d.datname=" + literal(name) + ' AND a.grantee=' + who + ';')


def default_acl(db, creator, runtime, kind, database):
    return acl_set(db, "SELECT coalesce(json_agg(privilege_type),'[]'::json) FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname=" + literal(creator) + ") AND d.defaclnamespace='public'::regnamespace AND d.defaclobjtype=" + literal(kind) + ' AND a.grantee=(SELECT oid FROM pg_roles WHERE rolname=' + literal(runtime) + ');', database)


def ensure_database(db, app, changes):
    name, owner, migration, runtime = (app[k] for k in ('database', 'owner_role', 'migration_role', 'runtime_role'))
    actual_owner = db.value('SELECT to_json(pg_get_userbyid(datdba)) FROM pg_database WHERE datname=' + literal(name) + ';')
    if actual_owner is None:
        db.run('CREATE DATABASE ' + identifier(name) + ' OWNER ' + identifier(owner) + ' TEMPLATE template0 ENCODING ' + literal('UTF8') + ';')
        changes.append('create database ' + name)
    elif actual_owner != owner:
        raise ProvisionError('Existing database has a different owner; refusing silent adoption')
    if database_acl(db, name, None):
        db.run('REVOKE ALL ON DATABASE ' + identifier(name) + ' FROM PUBLIC;')
        changes.append('restrict public database access ' + name)
    for role in (runtime, migration):
        if database_acl(db, name, role) != {'CONNECT'}:
            db.run('REVOKE ALL ON DATABASE ' + identifier(name) + ' FROM ' + identifier(role) + '; GRANT CONNECT ON DATABASE ' + identifier(name) + ' TO ' + identifier(role) + ';')
            changes.append('grant app database connection ' + role)
    public_schema = db.value("SELECT count(*) FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='public' AND a.grantee=0;", name)
    if public_schema:
        db.run('REVOKE ALL ON SCHEMA public FROM PUBLIC;', name)
        changes.append('restrict public schema ' + name)
    schema_rights = acl_set(db, "SELECT coalesce(json_agg(privilege_type),'[]'::json) FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='public' AND a.grantee=(SELECT oid FROM pg_roles WHERE rolname=" + literal(runtime) + ');', name)
    if schema_rights != {'USAGE'}:
        db.run('REVOKE ALL ON SCHEMA public FROM ' + identifier(runtime) + '; GRANT USAGE ON SCHEMA public TO ' + identifier(runtime) + ';', name)
        changes.append('grant runtime schema usage ' + name)
    for creator in (owner, migration):
        for kind, objects, rights in [('r', 'TABLES', TABLE_RIGHTS), ('S', 'SEQUENCES', SEQUENCE_RIGHTS)]:
            if default_acl(db, creator, runtime, kind, name) != rights:
                db.run('ALTER DEFAULT PRIVILEGES FOR ROLE ' + identifier(creator) + ' IN SCHEMA public REVOKE ALL ON ' + objects + ' FROM ' + identifier(runtime) + '; ALTER DEFAULT PRIVILEGES FOR ROLE ' + identifier(creator) + ' IN SCHEMA public GRANT ' + ','.join(sorted(rights)) + ' ON ' + objects + ' TO ' + identifier(runtime) + ';', name)
                changes.append('default runtime grants ' + creator + ' ' + kind)
    # Existing application objects also converge; owners keep DDL ownership.
    for kind, objects, rights in [('r', 'TABLES', TABLE_RIGHTS), ('S', 'SEQUENCES', SEQUENCE_RIGHTS)]:
        type_filter = "c.relkind IN ('r','p','v','m','f')" if kind == 'r' else "c.relkind='S'"
        rows = db.value("SELECT coalesce(json_agg(r),'[]'::json) FROM (SELECT c.relname,(SELECT coalesce(json_agg(privilege_type),'[]'::json) FROM aclexplode(coalesce(c.relacl,acldefault(" + literal(kind) + ",c.relowner))) a WHERE a.grantee=(SELECT oid FROM pg_roles WHERE rolname=" + literal(runtime) + ")) rights FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND " + type_filter + ') r;', name)
        for row in rows:
            if set(row['rights']) != rights:
                object_name = 'public."' + row['relname'].replace('"', '""') + '"'
                object_type = 'SEQUENCE' if kind == 'S' else 'TABLE'
                db.run('REVOKE ALL ON ' + object_type + ' ' + object_name + ' FROM ' + identifier(runtime) + '; GRANT ' + ','.join(sorted(rights)) + ' ON ' + object_type + ' ' + object_name + ' TO ' + identifier(runtime) + ';', name)
                changes.append('existing object grants ' + name + '.' + row['relname'])


def reconcile(config, db=None):
    validate(config)
    db = db or Sql(config['container'])
    changes = []
    # Detect an accidental name collision before touching any role/password.
    for app in config['applications']:
        actual_owner = db.value('SELECT to_json(pg_get_userbyid(datdba)) FROM pg_database WHERE datname=' + literal(app['database']) + ';')
        if actual_owner is not None and actual_owner != app['owner_role']:
            raise ProvisionError('Existing database has a different owner; refusing silent adoption')
    admin = role_record(db, 'postgres')
    if not admin or not admin['rolsuper']:
        raise ProvisionError('Expected the container-local postgres administrator')
    if not password_matches(config['admin_password'], admin['rolpassword']):
        db.run('ALTER ROLE postgres PASSWORD ' + literal(scram_verifier(config['admin_password'])) + ';')
        changes.append('administrator credential')
    for app in config['applications']:
        ensure_role(db, app['owner_role'], False, None, changes)
        ensure_role(db, app['migration_role'], True, app['migration_password'], changes)
        ensure_role(db, app['runtime_role'], True, app['runtime_password'], changes)
        ensure_membership(db, app['owner_role'], None, changes)
        ensure_membership(db, app['runtime_role'], None, changes)
        ensure_membership(db, app['migration_role'], app['owner_role'], changes)
        ensure_database(db, app, changes)
    return {'changed': bool(changes), 'changes': changes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    result = {'valid': True} if args.validate_only else reconcile(config)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('PostgreSQL configuration/convergence failed; inspect locally without disclosing credential policy.', file=sys.stderr)
        raise SystemExit(1)

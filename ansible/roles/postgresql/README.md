# PostgreSQL development service

Official `postgres:18.6-bookworm`, pinned to
`sha256:5c4783a8cc3f0074912164f94dfa1be4e043438f0f707cf968d7af9a0d31a2c8`.
The Compose project and container are both named **homelab-postgresql**. It uses
the separately prepared `homelab-storage` rootless Docker daemon, not the CI,
application-deployment or rootful daemon. All Docker operations execute as that
runtime user with `storage_runtime_environment` supplied by the shared role.

## Inputs and ownership

The parent play must provide:

* `storage_runtime_user`, `storage_runtime_uid`, `storage_runtime_environment`;
* `storage_mounts_verified: true` and an actual ext4 filesystem mounted at
  `storage_postgresql_mount` (normally `/srv/homelab/postgresql`);
* `postgresql_applications`, whose entries define `database`, `owner_role`,
  `runtime_role`, `migration_role`;
* protected `storage_secrets.postgresql.admin_password` and
  `storage_secrets.postgresql.applications[database].runtime_password` /
  `migration_password`, generated as 24–128 character URL-safe ASCII secrets.

Runtime/migrator credentials must differ from each other and the administrator
credential. The role stores them only in a root-owned, runtime-group-readable
policy file at `/etc/homelab/storage/postgresql-policy.json`, mode 0640. Docker
receives its initial administrator password through a mounted `_FILE` secret.
Neither cleartext passwords nor verifiers are emitted by the guest helpers.

The role creates only the traversable mode-0755 data **parent** below the validated mount and never
recursively changes ownership of an existing cluster. The official entrypoint
initializes mapped PostgreSQL ownership inside the rootless namespace. The
volume targets `/var/lib/postgresql`; PostgreSQL 18 puts its cluster in
mode-0700 `18/docker` beneath that path. Non-secret server/HBA files are mode
0644 so the mapped PostgreSQL UID can read them; Compose/policy/secret access
remains restricted. Compose refuses to invent a missing bind source.
Shared runtime startup must require the data mount, so a missing mount cannot
silently populate the disposable root filesystem.

## Access model

The service binds `192.168.1.9:5432`. The shared host firewall permits local-host
traffic only; no general LAN, public, IPv6 or CI access is intended. Applications
on red use a specifically permitted app-runtime egress path. Operator clients
can use `ssh -L15432:192.168.1.9:5432 server@192.168.1.9`. Initial TCP transport
stays on red, uses SCRAM-SHA-256 authentication and is not a remote TLS endpoint;
cross-host access requires a separate TLS/firewall decision. Caddy's HTTP routes
do not proxy PostgreSQL.

Each app has:

* a NOLOGIN owner role, which owns the database and application objects;
* a login migrator role that inherits/assumes that owner, without server-level
  superuser, role creation, database creation, replication or RLS bypass;
* a login runtime role with CONNECT, public-schema USAGE, table SELECT/INSERT/
  UPDATE/DELETE and sequence USAGE/SELECT. It has no owner membership, schema
  creation or privileged server attributes.

The API policy allows each app login only into its own database; all other TCP
logins are rejected except the separately credentialed administrator. PUBLIC
database/schema access is revoked. Table/sequence default privileges cover
objects created as either the owner or migrator role, so migrations can choose
to `SET ROLE` to the owner. Existing public-schema table/sequence grants also
converge. Extra memberships on these dedicated managed roles are removed.

Configuration is an allowlist, not a deletion list: removing an application from
configuration never drops its database, roles or data. It removes its HBA login
path on service convergence. Existing databases with a different owner are not
silently adopted. Extension installation and application schema migrations are
deliberate operations outside the generic provisioning role.

## Convergence, limits and verification

`reconcile.py` runs after every service convergence, not only first initialization.
It compares SCRAM verifiers against protected source passwords, rotates only
when a password differs, restricts role flags/memberships, and applies missing
database/default/object grants. SQL travels over stdin to container-local
`psql --user postgres`; TCP authentication tests read their password from stdin
inside an exec shell rather than exposing it in command arguments. The helper
emits only a public change summary. Apply tasks carrying policy remain no-log.

The container has a read-only root filesystem with bounded temporary/socket
filesystems. It drops all default capabilities and adds only CHOWN,
DAC_OVERRIDE, FOWNER, SETUID and SETGID for the official initialization/gosu
path. The running postgres process has no effective capabilities; NET_RAW is
absent. It starts at 1 GiB RAM, one CPU, 128 MiB shared memory, 30 total
connections and a 10-connection cap per app login. `fsync`, synchronous commit
and full-page writes remain enabled. The parent owns the aggregate RAM budget.
PostgreSQL configuration/HBA checksums recreate the container on relevant
changes; the persistent filesystem is retained. Ordinary convergence never
invokes `down --volumes`, deletes data, shrinks volumes or upgrades a major image.

`tasks/verify.yml` checks the live mount and executes `verify.py`. It verifies
real TCP logins, privileged role flags, rejected administrator/cross-app DB
connections, runtime DDL denial, migrator DDL access and actual default-grant
DML under role switching. Every SQL object probe is rolled back; no test table
or application fixture survives. Backups are explicitly deferred by the operator.
Container persistence is not disk-loss recovery. Before a host reinstall or
major upgrade, plan an explicit export/restore or supported migration.

Sources: [official image](https://hub.docker.com/_/postgres/),
[PostgreSQL privileges](https://www.postgresql.org/docs/18/ddl-priv.html),
[password authentication](https://www.postgresql.org/docs/18/auth-password.html).

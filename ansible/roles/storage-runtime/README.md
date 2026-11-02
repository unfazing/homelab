# Shared development storage runtime

`task apps:storage:deploy VERIFY_RESTART=true` is the first-install operator interface.
Enter red-server's sudo password only at Ansible's hidden terminal prompt. The
ordinary repeat command is `task apps:storage:deploy`; `task apps:storage:verify`
checks the existing deployment. No credentials are printed by these commands.
`task apps:storage:credentials APPLICATION=colouring_book_dev` deliberately prints
credentials in the operator terminal. Preserve the ignored, mode-600 controller
bundle `.generated/secrets/storage.json`; deleting it is not password rotation.

## State and ordering

The non-secret manifest is `ansible/vars/storage.yml`. The inspector first checks
`ubuntu-vg` free extents, LV tags/signatures, mount contents and fstab. Only missing
managed LVs are allocated: PostgreSQL 20 GiB and Garage 80 GiB. Existing volumes
are never shrunk, overwritten or automatically adopted. Empty, tagged LVs from
an interrupted first install can finish formatting. Data is on separately mounted
ext4 filesystems under `/srv/homelab`, not a container writable layer. There is no
data-destruction Task. Backups are explicitly deferred; these volumes do not
provide disk-loss recovery.

The separate `homelab-storage` rootless runtime starts only with both mounts and
its firewall active. User-manager systemd dependencies bind its lifetime to those
mounts. Ansible then prebuilds the source-pinned Garage UI image before PostgreSQL
and Garage use the runtime's 2 GiB budget. CI and application runtimes also have
2 GiB caps; lowering them fails if current use is too high. Docker CE itself is
an existing external-host prerequisite; matching rootless extras are installed
without replacing the engine.

After services start, the canonical Homepage playbook converges private AdGuard
rewrites, dashboard configuration and Caddy routes. It gives Homepage no storage
administrator, database or S3 credentials. The final acceptance checks require
trusted private HTTPS, actual SQL/S3 authentication, correct grants, UI session
persistence when requested, and LAN/CI exclusion. UI HTTP availability on Homepage
is not database/S3 health. No backup job or application schema migration is run.

## Networking and applications

- `https://garage.home.DOMAIN`: privileged Garage UI, separate native login.
- `https://s3.home.DOMAIN`: path-style S3, signed requests required. An ordinary
  browser opening the root URL may receive Access Denied; this is expected.
- PostgreSQL: `192.168.1.9:5432`, host-local only. For operator clients:
  `ssh -L15432:192.168.1.9:5432 server@192.168.1.9`, then connect to
  `127.0.0.1:15432` with the appropriate database role.

Only Caddy `.101` and host-local callers reach the S3/UI backend listeners.
Garage RPC/admin ports are unpublished. The application runtime has one narrow
local PostgreSQL exception; CI has none. S3 uses existing private Caddy HTTPS.
Host root, the storage runtime and Garage UI are trusted administrators of storage.
Do not grant application workflows the storage Docker socket or administrator keys.

For another application, add its distinct database/owner/migrator/runtime names
in `ansible/vars/storage-applications.json`, review both canonical HTML documents,
then deploy. New passwords are added without rotating existing ones; removing an
entry does not delete its database. Application repositories own schema migrations.
Garage's initial `colouring-book-dev` bucket has a scoped non-owner application
key; future buckets should receive their own keys rather than sharing this key.
See the individual PostgreSQL, Garage and UI role READMEs for limits and grants.

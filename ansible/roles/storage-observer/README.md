# Aggregate storage telemetry

This role adds no public/host listener. `prepare.yml` validates or creates the
internal `172.30.93.0/29` Docker network in homelab-storage's rootless daemon.
PostgreSQL (.2), Garage (.3) and this collector (.4) are its only intended peers.
The collector has no external network, Docker socket or application data mount.

The pinned, stdlib-only Go build runs with psql from the existing pinned PG image;
96 MiB / 0.1 CPU / 32 PIDs, read-only root, no capabilities. It samples every
minute, caps HTTP/SQL output, rejects redirects and exports an explicit allowlist.
Garage uses a three-endpoint token. PostgreSQL uses a protected pgpass file and
only fixed aggregate functions; neither password appears in arguments or JSON.

The scoped Garage token has an ignored controller recovery copy at
`.generated/secrets/garage-monitor-token` (0600); PostgreSQL uses the existing
storage secret bundle. Recovering a missing token from this file avoids duplicate
issuance after an OS rebuild; conflicting or unrecoverable credentials fail closed.

The output directory is disposable, mode 2750 with inherited homepage-monitor
read access. Each atomic snapshot is mode 0640 and contains no keys, database
records, SQL text or bucket names. Last-good component timestamps survive a
collection failure; the fixed SSH reporter and Homepage independently validate
fields, track age and turn stale samples into unknown. The Homepage collector
computes rates from two samples, detects counter decreases/PG reset or restart,
and never refreshes service age merely because SSH succeeded.

Run `task apps:storage:monitoring:deploy` for an existing installation, or the
canonical `task apps:storage:deploy` for a fresh one. Both use Ansible's hidden
red sudo prompt. No migrations/exports or data deletion are part of these Tasks.

Opt-in tests use disposable rootful Docker containers on red, no production
mounts or published ports:

```sh
HOMELAB_POSTGRESQL_INTEGRATION=1 python3 -m unittest discover -s ansible/roles/postgresql/tests -p test_integration.py -v
HOMELAB_STORAGE_MONITOR_INTEGRATION=1 python3 -m unittest discover -s ansible/roles/storage-observer/tests -v
```

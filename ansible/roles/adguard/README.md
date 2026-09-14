# AdGuard role

Planned Docker Compose configuration for `lab-access-01`. WireGuard remains a native host service; AdGuard will use a dedicated Compose project, secrets, and ZFS-backed configuration and data mounts.

The previous unpinned native installer has been retired. This role is intentionally excluded from `playbooks/site.yml` until its image version, ports, storage contract, and secret handling are defined.

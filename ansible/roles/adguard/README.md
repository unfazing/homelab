# AdGuard role

Planned Docker Compose configuration for `lab-access-01`. WireGuard remains a native host service; AdGuard will use a dedicated Compose project, secrets, and the mounted ZFS dataset at `/srv/homelab/adguard`.

The previous unpinned native installer has been retired. This role is intentionally excluded from `playbooks/site.yml` until its image version, ports, container UID ownership, and secret handling are defined.

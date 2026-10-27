# Cloudflare DDNS role

Deploys an unprivileged systemd oneshot service and timer on `lab-access-01`.
Every five minutes it discovers the public IPv4 address, derives the single
active zone visible to the token, and maintains DNS-only A records for both
the apex (`@`, used by existing WireGuard profiles) and `vpn.<zone>`.
The explicit `cloudflare_ddns_record_labels` allowlist defaults to `['@', vpn]`;
the guest environment uses space-separated `CLOUDFLARE_DDNS_RECORD_LABELS`.

The Cloudflare account ID and DDNS token come from the controller environment.
Ansible writes them to `/etc/homelab/ddns/cloudflare.env` as
`root:cloudflare-ddns` mode `0640`; neither value enters Git, Terraform state,
command arguments, or Ansible output. All selected names are preflighted before
any write. Zero/multiple zones, duplicate A records, CNAME conflicts and invalid
or duplicate labels fail closed. Other DNS records remain untouched. API/network
failure during writes can still leave a partial update; the next timer retries.

Missing A records are created; existing ones change only for IP, TTL (300) or
proxy-state drift. WireGuard records must be DNS-only (`proxied:false`). Apex
DDNS preserves clients using `donk.live:27272`; it changes no router forwarding
or WireGuard service. Use `task apps:ddns:check` and `task apps:ddns:deploy`.

Tests: `python3 -m unittest discover -s ansible/roles/cloudflare-ddns/tests`.
They run the real shell script with a fake curl and never modify public DNS.

# Cloudflare DDNS role

Deploys an unprivileged systemd oneshot service and timer on `lab-access-01`. Every five minutes it discovers the current public IPv4 address, derives the single active zone visible to the zone-scoped token, and creates or updates the DNS-only `vpn.<zone>` A record.

The Cloudflare account ID and DDNS token come from the controller environment. Ansible writes them to `/etc/homelab/ddns/cloudflare.env` as `root:cloudflare-ddns` mode `0640`; neither value enters Git, Terraform state, command arguments, or Ansible output. The updater refuses tokens that expose zero or multiple active zones and refuses duplicate A records.

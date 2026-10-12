# AdGuard role

Ansible deploys the digest-pinned official AdGuard Home image as a standalone
Compose project on `lab-access-01`. Host networking preserves original DNS
client IPs; DNS binds only to the VM's static address. The admin UI/API binds
to `192.168.1.100:3000`, while a dedicated nftables input rule admits only
Caddy at `.101` and guest-local traffic. Docker requires that firewall unit on
boot, so the backend cannot start unprotected. No router or WireGuard DNS
cutover occurs here.

The `homelab-adguard` VirtioFS dataset stores `conf/` and `work/`. The ignored
administrator password is installed separately under `/etc/homelab/adguard/`.
`reconcile.py` uses the guest-local API to bootstrap once and then converge
the source-controlled policy in `defaults/main.yml`. It never edits AdGuard's
YAML while the service is running. Rewrites are an exact desired set: removed
entries are deleted once, and an unchanged second run reports no changes.
Future rewrite policy is still open.

Use `task apps:adguard:deploy`, then `task apps:caddy:deploy-production` to
serve `https://adguard.home.<domain>/`. No client certificate or IP allowlist
is configured; AdGuard's own login is still required. The private name exists
on the new `.100` resolver only until DNS cutover. For break-glass access,
SSH-tunnel through the Caddy VM:
`ssh -L 3000:192.168.1.100:3000 user@192.168.1.101`.
`task apps:adguard:credentials` shows the new administrator password. The old
`.9` resolver remains the router's DNS until an explicit, separately verified
cutover.

For a deliberate rotation, run
`HOMELAB_CONFIRM_ADGUARD_ROTATION=yes task apps:adguard:rotate-password` during
a short DNS maintenance window. Enter and confirm your chosen password (at
least 9 characters) without echoing it, or press Enter at the first prompt to
generate a random 16-character password. Task stages an ignored candidate; the
dedicated Ansible workflow verifies the old login, stops AdGuard, updates the
durable YAML bcrypt hash, restarts and verifies the new login and private DNS,
and rolls the guest back if verification fails. Only then does Task replace its
controller secret. The rotation command is not part of ordinary convergence.
An interrupted or failed run may leave an ignored candidate password or a
root-only guest config backup for manual recovery; inspect those and the Task
lock directory before retrying.

The previous unpinned native installer has been retired. This role is invoked
by `task apps:adguard:deploy`, not the generic site playbook.

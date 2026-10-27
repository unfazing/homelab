# wg-easy replacement

Pinned stable `15.5.0`, independent Compose project on `lab-access-01`.
This replaces the old native role; the source VPN at `.9` is never modified.
Public router cutover is a separate operator action after client acceptance.

## Operator flow

1. `task apps:wireguard:export` from your interactive terminal. It asks for
   red-server sudo, exports the live identity, peer keys/addresses, optional
   PSKs, PiVPN peer names and firewall inventory into ignored mode-600
   `.generated/secrets/wireguard-legacy.json`. No keys appear in output;
   client private keys are not collected. The temporary red export is removed.
   For the approved full-profile recovery, `task apps:wireguard:profiles:export`
   separately enriches this ignored file with saved client private keys and
   original configurations, matching only active public keys. It needs no sudo
   while `/home/server/configs` is readable. Do not print the recovery JSON.
2. `task data:reconcile`, reviewed `task infra:plan` / `task infra:apply`,
   then `task config:common` attach/mount `homelab-wireguard`. These storage
   prerequisites were applied on 27 October, with no VM replacement/destruction.
3. `task apps:wireguard:test-import` exercises the real pinned setup API
   with disposable keys and a temporary child directory on the real VirtioFS
   filesystem. It exposes only loopback TCP 51829, removes its own container
   and data, and verifies identity preservation plus a no-op second import.
4. `task apps:wireguard:check`, then `task apps:wireguard:deploy`.
5. `task apps:wireguard:verify`; retrieve login only in your terminal with
   `task apps:wireguard:credentials`.
6. On home Wi-Fi, duplicate an existing owner profile, disable its original
   tunnel, and change only the copy's Endpoint to `192.168.1.100:27272`.
   Verify handshake, internet, DNS and private HTTPS. Repeat DNS-only and
   Gareth's exact allow/deny tests; check IPv6 cannot bypass full tunnelling.
7. Only after acceptance, change the existing router's public UDP 27272
   forwarding destination from `.9:51820` to `.100:27272`. Existing client
   Endpoint remains `donk.live:27272`. Test externally; roll back that
   destination if needed. Do not disable red until acceptance/recovery checks.

Deployment on 27 October preserved all four peers and optional PSKs; native
HTTPS login and direct-backend blocking passed. Repeat deployment changed
nothing on all three VMs. Device trials, reboot acceptance and public router
cutover remain operator steps. No new public port was opened.

## State and migration

State is `/srv/homelab/wireguard` on dedicated ZFS-backed VirtioFS. The exact
mounted source is checked before starting. The native database/session state
survives container recreation and is not stored in Git. Bootstrap secrets and
the legacy export live separately under `/etc/homelab/wg-easy`; recover them
from the ignored controller files. Back up the mutable database separately;
the original legacy export cannot reconstruct peers added through the UI later.

The version-pinned API adapter uses wg-easy's v14 migration shape to import
the existing server key, peer keys, addresses and PSKs. With the approved
enriched recovery file it imports original client private keys too, then uses
the client API to set each saved route list and keepalive. The real
`10.115.145.0/24` range stays. Public-only fallback imports are named as such
and cannot regenerate old private configurations. No silent rekeying occurs.
Incomplete setup or identity mismatch fails without discarding state.

The operator requested an imperative replacement of the initial staged
peers. That one-time operation preserves old staged state under a root-only
`.recovery-before-full-profiles-*` directory on the same dataset and recreates
through native setup/import; no SQL row edits or database-repair task exists.
Fresh restore uses the same normal deployment from protected recovery state.
After initialization, repeat convergence does not overwrite runtime peer edits.

The existing endpoint remains `donk.live:27272`, DNS `.100`. The new container
also listens on UDP 27272. The eventual router mapping must use `.100:27272`,
regardless of the old internal destination port. DNS-only/full-tunnel profiles
already on devices are unchanged; UI defaults apply to future downloads.
Original client AllowedIPs are retained separately from server-side tunnel
`/32` routes. In particular, the saved DNS-only profile routes the whole
`192.168.1.0/24` LAN; Gareth routes only `.9/32` and `.100/32`, with firewall
ports still enforced separately. The operator explicitly approved replacing
stale saved `donk.tech`/`.9`/public DNS values with `donk.live:27272` and only
DNS `.100`. The generator uses client Address `/32` instead of source `/24`,
and explicit MTU 1420 where the original omitted it; keepalive omission becomes
explicit 0. Therefore downloads preserve identities/routes, but are not byte
copies. Exact original files remain in protected recovery state. Download and
QR acceptance compares original private keys, PSKs, routes and normalized fields
in memory without logging them. Existing device profiles are never pushed edits.

The native administrator can now export/impersonate these client identities.
Private keys live in wg-easy's durable state and root-only controller/guest
recovery files. ZFS is currently unencrypted; do not grant this state or the
administrator login to Homepage, agents or unrelated users.
IPv6 is disabled server-side initially; full-tunnel clients must capture or
disable IPv6 rather than bypass VPN. External client UAT is still required.

## Trust boundary

Own Docker bridge `172.30.91.0/29`, container `.2`; NET_ADMIN and NET_RAW only,
no host networking, Docker socket, module mount or SYS_MODULE. Ansible loads
WireGuard and legacy iptables modules in the guest and persists them for boot.
The root filesystem is read-only; data and tmp/run are explicit writable mounts.
384 MiB / 0.5 CPU limit. Upstream verbose DEBUG is disabled to avoid private
configuration logging. The container owns only its network namespace.

The entrypoint applies its raw-table policy **before** starting WireGuard.
Gareth `.7` gets only `.9:3000/tcp` and `.100:53/tcp+udp`; other traffic drops.
This precedes NAT and all filter-chain accepts and covers local INPUT as well
as forwarding. Tunnel clients cannot directly reach the container's HTTP UI.
No global host ruleset is flushed. Other peers retain their existing routing
authority; bridge NAT hides their addresses from LAN/DNS services.

Bootstrap binds only guest loopback TCP 51821 until admin creation/import
succeeds. Afterward a guest nftables prerouting guard admits `.100:51821`
only from Caddy `.101` before Docker DNAT. HTTPS at
`wireguard.home.<domain>` retains wg-easy's native login, secure cookies and
separate random administrator password. No management UI public forwarding.
The UI administrator has full VPN/key/control authority; do not give its login
to Homepage or Hermes. API configuration uses Basic Auth and currently assumes
password-only admin login; enabling 2FA requires revisiting automation access.

## Tests and acceptance

`python3 -m unittest discover -s ansible/roles/wg-easy/tests` checks parsing,
identity/PSK preservation and semantic allow/deny behaviour of actual policy
commands. `task apps:wireguard:test-import` is the real-image database/API test.
Live acceptance verifies authenticated HTTPS, imported identity, subnet and
isolation. Device handshakes, full-tunnel internet, DNS-only, Gareth deny tests,
home Wi-Fi/hairpin behaviour and reboot persistence precede public cutover.

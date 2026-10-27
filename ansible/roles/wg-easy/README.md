# wg-easy service

Pinned `15.5.0` Compose service on `lab-access-01`, with durable state at
`/srv/homelab/wireguard` (ZFS-backed VirtioFS). The OS and container are disposable;
identities, per-client policies and sessions belong to the durable runtime store.

## Canonical operator flow

Attach the existing data mapping, configure the root environment, then run:

```sh
task apps:wireguard:check
task apps:wireguard:deploy
task apps:wireguard:verify
task apps:wireguard:credentials
```

A fresh empty dataset gets a native server identity, an `admin` account from the
ignored controller password, endpoint/domain defaults and native per-client
firewall enabled. It creates **zero clients**. No legacy export, existing client
key, migration marker or `.9` connection is required. Repeat convergence manages
service defaults and the global firewall setting, never client identities or
allowlists. Wrong admin credentials fail rather than reset the account.
The pinned native setup/API adapter performs no database reads or SQL edits.

Existing state is preserved. Restoring identities is a separate data-recovery
operation: a fresh install cannot reconstruct mutable client keys from Git.
Old migration tools are archived under
[`history/2026-10-27-wireguard-migration`](../../../history/2026-10-27-wireguard-migration/).
They have no Task hooks or active-role dependencies. Protected legacy exports
remain ignored recovery artifacts; never move those secrets into the archive.

## Network and firewall boundary

Own bridge `172.30.91.0/29`, container `.2`, NET_ADMIN/NET_RAW, read-only root,
no host network/socket, SYS_MODULE or module mount. The guest loads required
WireGuard/legacy iptables modules, including comment/conntrack, before Docker.
The container is limited to 384 MiB and 0.5 CPU.

`start.sh` is identity-free: tunnel INPUT drops; FORWARD defaults to DROP;
established responses return. Native wg-easy inserts `WG_CLIENTS_wg0` ahead of
fallback tunnel drops, so disabled/empty/rebuilding filtering cannot fall through
to wg-quick's broad ACCEPTs. Native policy filters forwarding only. It is marked
experimental upstream: test actual traffic, not just the UI toggle. Empty per-client
Firewall Allowed IPs fall back to that client's routes, which may allow all traffic.

Bootstrap publishes only guest-loopback TCP 51821. After setup, UDP 27272 binds
`.100` for LAN tests; the HTTP backend admits only Caddy `.101` before Docker
DNAT. `https://wireguard.home.<domain>` uses native login/secure cookies behind
Caddy. The only public forward remains the separately managed WireGuard UDP
mapping. Current router cutover from `.9` is still pending.

Tunnel subnet `10.115.145.0/24`; default DNS `.100`, endpoint `donk.live:27272`.
IPv6 server transport is disabled, so full-tunnel clients must block/capture IPv6.
Container and bridge NAT hide original peer addresses from LAN/AdGuard services;
enforcement must happen in the VPN namespace before NAT.

Manage identities/port allowlists in the native dashboard. See the
[per-client access runbook](../../../docs/wireguard-peer-access.md) for Gareth's
runtime example, routing versus firewall syntax and verification. His example
is not provisioned or overwritten by this role. Administrator access includes
exporting/impersonating client keys; never share it with Homepage or agents.
Basic-auth automation currently assumes password-only admin; enabling 2FA needs
an automation-access design update.

## Validation

`python3 -m unittest discover -s ansible/roles/wg-easy/tests` checks guard ordering
and identity-free configuration. `task apps:wireguard:test-fresh` uses disposable
containers, an isolated internal network and no published test ports or legacy
inputs: verify zero-client setup, no-op convergence, actual WireGuard TCP/UDP
allow/deny, local INPUT denial, fail-closed firewall disable and restart persistence.
It does not touch production peers. Runtime checks allow an empty peer population.
Real-device and guest-reboot acceptance are separate operator tests.

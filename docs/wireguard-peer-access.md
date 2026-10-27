# WireGuard per-client access

Current service: wg-easy 15.5.0 on `lab-access-01` (`192.168.1.100`).
The router still forwards the public VPN endpoint to legacy `.9` until cutover.
The [legacy host procedure](../history/2026-10-27-wireguard-migration/legacy-peer-access.md)
is historical; do not apply those host commands to the container deployment.

## Native firewall and ownership

In **Admin Panel → Interface → Traffic Filtering**, **Enable Per-Client
Firewall** is enabled. Ansible ensures this service-wide setting; each client's
identity, routes and **Firewall Allowed IPs** are runtime settings managed in
wg-easy. Fresh installs create no clients and need no old export files.

The feature is experimental in the pinned upstream release. Its allowlist is
server-enforced for forwarded traffic. A generic container guard blocks tunnel
INPUT to container-local services and drops forwarding when the native chain is
missing, disabled or being rebuilt. Established LAN responses can return.
These guards are independent of client names, addresses and keys.

**Important:** an empty Firewall Allowed IPs list falls back to client Allowed
IPs, then the default routes. A full-tunnel client with an empty firewall list
therefore has broad access. Set an explicit list for every restricted client.
Disabling native filtering makes tunnel forwarding fail closed in this deployment.

## Gareth: Inkling and DNS only

1. Open [the dashboard](https://wireguard.home.donk.live), sign in as `admin`,
   and confirm the global firewall toggle above is enabled.
2. Edit **gareth**; confirm its tunnel address is `10.115.145.7`.
3. Under **Firewall Allowed IPs**, add these three entries and save:

```text
192.168.1.9:3000/tcp
192.168.1.100:53/tcp
192.168.1.100:53/udp
```

These entries are already applied. Everything else forwarded from that peer is
blocked, including SSH, other LAN hosts, Caddy `.101:443` and internet egress.
Do not enter bare `.9` or `.100` here: that would allow every port on those hosts.

Keep the separate **Allowed IPs** routing field as:

```text
192.168.1.9/32
192.168.1.100/32
```

Use **DNS** `192.168.1.100` and **Endpoint** `donk.live:27272`. Routing Allowed
IPs select traffic sent into the VPN; they are not the security boundary, since
a client can change them. Do not put `:port/protocol` syntax in the routing field.
Firewall edits apply server-side without downloading a new client profile;
changed client routes/DNS require changing that device's profile.

This policy permits direct Inkling HTTP at `http://192.168.1.9:3000`, not
`https://inkling.home.donk.live`, which enters the shared Caddy listener at
`.101:443`. Granting that shared IP/port alone would expose every Caddy hostname
at the network layer. Design a separate listener or proxy identity policy before
promising one-application HTTPS access. Bridge NAT hides peer addresses from
LAN services, so a downstream source-IP rule cannot identify Gareth.

## Adding another restricted person

Create a dedicated identity/address; never share another person's key. Record
the client-facing destination, protocol and port, required DNS and denied paths.
Set explicit Firewall Allowed IPs, then choose convenient routing Allowed IPs.
No Task or repository entry is needed for the new identity. Keep the client
inactive until its allowlist is saved and inspect it before sharing the profile.

Examples: `192.168.1.9:3000/tcp` permits only that TCP application;
`192.168.1.100:53` permits TCP and UDP DNS; `192.168.1.0/24` permits every port
on that LAN and is a much wider grant. Avoid unintended broad CIDRs.
The generic INPUT guard deliberately prevents access to services inside the
wg-easy container itself, even if its tunnel IP appears in an allowlist; use
Caddy HTTPS for administration and the external AdGuard resolver for DNS.

## Verify and recover

Run the canonical service check:

```sh
task apps:wireguard:verify
```

For non-secret rule inspection on the access VM:

```sh
sudo docker exec wg-easy iptables -S FORWARD
sudo docker exec wg-easy iptables -S WG_CLIENTS_wg0
sudo docker exec wg-easy iptables -S INPUT
sudo docker exec wg-easy iptables -nvL WG_CLIENTS_wg0
```

From the restricted device, test the exact allowed endpoints, TCP versus UDP,
a forbidden port on each allowed host, another LAN host, public internet and
private HTTPS names. Test an unrestricted owner too. Repeat after container
restart and, during a maintenance window, guest reboot. Home Wi-Fi and external
mobile data are separate tests. DNS success does not prove an HTTPS grant.
The current server transports IPv4 only; full-tunnel clients must capture or
disable IPv6 so it cannot bypass the VPN.

Client allowlists and private keys survive container recreation in the durable
`/srv/homelab/wireguard` volume. Canonical installs do not reconstruct them;
restore that state separately when preserving identities. A native administrator
can export/impersonate client identities. Keep its login and recovery state away
from agents and dashboard integrations. Revoke a person's peer to remove access;
do not remove its restrictions while leaving an active credential behind.

## References

- [Pinned upstream client firewall syntax](https://github.com/wg-easy/wg-easy/blob/v15.5.0/docs/content/guides/clients.md#firewall-allowed-ips)
- [Pinned upstream firewall implementation](https://github.com/wg-easy/wg-easy/blob/v15.5.0/src/server/utils/firewall.ts)
- [Canonical deployment role](../ansible/roles/wg-easy/README.md)

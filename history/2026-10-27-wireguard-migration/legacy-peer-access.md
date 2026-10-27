# WireGuard peer access runbook

Use this when a person should reach only named private destinations. Sections 1–6 are a **legacy `red-server` (`192.168.1.9`) procedure**. wg-easy is now staged on `lab-access-01`; router cutover is pending. Its container policy requires the separate instructions below. The current flat LAN has no VLAN enforcement. Keep the only public ingress as the existing WireGuard UDP port.

## 1. Specify the *client-facing* path

Record these before changing the firewall:

| Input | Example / check |
| --- | --- |
| Person and dedicated WireGuard peer | Gareth; `10.115.145.7/32`. Never share another person's key or tunnel address. |
| Tunnel profile | Full tunnel or split/DNS-only; record the client's `Address`, `DNS`, and `AllowedIPs` without copying private keys into the repo. |
| Allowed service | Protocol, destination IP, and port **as reached by the client**. |
| DNS | Resolver IP and expected answer for each private name. |
| Denied destinations | Other LAN hosts, other ports on allowed hosts, other Caddy sites, and internet egress. |
| IPv6 | Check for peer IPv6 addresses/routes. The IPv4-only example below does not constrain IPv6. |

Do not confuse a backend with the client entry point. Today `inkling.home.donk.live` resolves at AdGuard `192.168.1.100:53` to Caddy `192.168.1.101:443`; Caddy then connects to `192.168.1.9:3000`. Allowing only `.9:3000` gives direct HTTP access **but not the HTTPS hostname**. Allowing the shared `.101:443` address gives network reachability to *all* Caddy hostnames, not just Inkling. Do not grant that as an apparent one-app exception. First design an isolated listener/address or a proxy-enforced client identity and verify the other routes remain denied. The legacy WireGuard NAT also hides a peer's source address from LAN services, so a Caddy source-IP rule cannot distinguish that peer without a routing/NAT change.

When a client is on home Wi-Fi with WireGuard enabled, its profile may still route private traffic through `wg0` and override Wi-Fi DNS. Test that case separately from Wi-Fi with WireGuard off.

## 2. Inspect the existing path (read-only)

On `red-server`:

```sh
sudo wg show wg0 allowed-ips
ip -br address show wg0
sudo nft list ruleset
sudo iptables -t nat -S POSTROUTING
systemctl is-enabled netfilter-persistent.service nftables.service wg-quick@wg0.service
```

Confirm the peer has a unique `/32`, `wg0` is the tunnel, and the saved `10.115.145.0/24` masquerade rule is present. Do not paste a WireGuard configuration containing private keys into a ticket or commit. If the client uses IPv6, design an equivalent IPv6 deny/allow policy before proceeding. Check the actual resolver answer from a capable client with `dig @192.168.1.100 inkling.home.donk.live` (or its equivalent).

The legacy host uses `iptables-nft` plus Docker. Its old `/etc/nftables.conf` begins with `flush ruleset`: loading it erased WireGuard NAT and Docker's rules. **Never run `nft -f /etc/nftables.conf`, stop the stock `nftables.service`, or save Docker's transient rules with `netfilter-persistent save` as a shortcut.** The peer policy below owns only its own nftables table.

## 3. Apply one peer-specific allowlist

Use a unique lowercase name for each restricted person. On `red-server`, create `/etc/nftables.d/wg-peer-NAME.nft` with `sudoedit`; replace `NAME`, `PEER_IP`, and the sample allowed endpoints. Add one rule per allowed transport and port. The final peer-specific drop is essential; do not broaden the existing subnet-wide NAT rule.

```sh
sudo install -d -m 0755 /etc/nftables.d
sudoedit /etc/nftables.d/wg-peer-NAME.nft
```

```nft
destroy table inet wg_peer_NAME

table inet wg_peer_NAME {
    chain prerouting {
        type filter hook prerouting priority -150; policy accept;

        iifname "wg0" ip saddr PEER_IP ip daddr 192.168.1.9 tcp dport 3000 counter accept
        iifname "wg0" ip saddr PEER_IP ip daddr 192.168.1.100 udp dport 53 counter accept
        iifname "wg0" ip saddr PEER_IP ip daddr 192.168.1.100 tcp dport 53 counter accept
        iifname "wg0" ip saddr PEER_IP counter drop
    }
}
```

This template describes Gareth's **direct Inkling + DNS** policy after substituting `NAME=gareth` and `PEER_IP=10.115.145.7`. It intentionally does not allow `inkling.home.donk.live`, which uses Caddy at `.101:443`. A separate table per peer prevents a future edit from replacing Gareth's rules. The `prerouting` hook checks the original destination before Docker DNAT and sees traffic both to the host and through it. It does not modify the shared NAT rule or other peers.

Validate and apply the peer's actual file:

```sh
sudo nft -c -f /etc/nftables.d/wg-peer-NAME.nft
sudo nft -f /etc/nftables.d/wg-peer-NAME.nft
sudo nft list table inet wg_peer_NAME
sudo iptables -t nat -S POSTROUTING
```

Stop if validation fails. Loading the file replaces only that table atomically; repeating it must not duplicate rules. Never use `flush ruleset` for a peer change.

## 4. Make it survive reboot, without an open startup window

On the legacy host, create a **separate** service for each restricted peer:

```sh
sudoedit /etc/systemd/system/wg-peer-NAME-acl.service
```

Replace `NAME` in this unit:

```ini
[Unit]
Description=WireGuard NAME peer access policy
After=netfilter-persistent.service
Before=wg-quick@wg0.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.d/wg-peer-NAME.nft
ExecReload=/usr/sbin/nft -f /etc/nftables.d/wg-peer-NAME.nft
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

It remains active after exit and deliberately has no `ExecStop` that could remove the restriction while the tunnel is up. Add a WireGuard unit drop-in:

```sh
sudo install -d -m 0755 /etc/systemd/system/wg-quick@wg0.service.d
sudoedit /etc/systemd/system/wg-quick@wg0.service.d/20-wg-peer-NAME-acl.conf
```

Replace `NAME` here too:

```ini
[Unit]
Requires=wg-peer-NAME-acl.service
After=wg-peer-NAME-acl.service
```

One drop-in per restricted peer is acceptable. `Requires` alone does **not** order startup; the `After` line makes a new WireGuard start wait for this policy to load successfully.

After creating those files, validate and start the service without restarting WireGuard:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now wg-peer-NAME-acl.service
sudo systemctl status wg-peer-NAME-acl.service --no-pager
systemctl show wg-quick@wg0.service -p Requires -p After
sudo nft list table inet wg_peer_NAME
```

Do not enable the stock `nftables.service` on this legacy host: its configured stop path flushes the whole ruleset. A later global flush can still remove a loaded peer policy without systemd noticing; retire the unsafe legacy config after the new policy and reboot checks pass. Rebuild this as Ansible-owned guest policy when WireGuard migrates to `lab-access-01`, retaining the peer subnet but reviewing the changed input/forwarding paths rather than copying host-specific files unchanged.

## 5. Verify, including failure cases

From the restricted peer, test every intended destination, a different port on each allowed host, one unrelated LAN host, internet access, DNS resolution, and the exact application URL. On `red-server`, inspect `sudo nft list table inet wg_peer_NAME` before and after each attempt; the rule counters should identify allow versus drop. A successful DNS lookup alone does **not** prove the HTTPS route is allowed. Repeat on home Wi-Fi with WireGuard both on and off, and from a different unrestricted peer. Confirm the generic NAT rule is still present. Reboot only during a maintenance window, then repeat the peer, NAT, Docker, and other-peer checks.

If changing the policy, edit its file, run `sudo nft -c -f /etc/nftables.d/wg-peer-NAME.nft`, then `sudo systemctl reload wg-peer-NAME-acl.service` and re-test. If the test fails, stop and restore the previous file. Do not declare the access grant complete until the allow/deny matrix and reboot test pass.

## 6. Rollback or revoke

`sudo nft destroy table inet wg_peer_NAME` removes the live restriction immediately, **broadening** that peer's access; the service or next boot can restore it. Use only as a deliberate emergency rollback. For permanent removal, revoke/remove the WireGuard peer first, then remove its systemd dependency and service and delete its dedicated table; verify that other peers and NAT remain intact. Do not remove or edit another person's table.

## After the planned network migration

For staged wg-easy, enforce restrictions in the owning Ansible role's
[`start.sh`](../ansible/roles/wg-easy/files/start.sh), inside the container's
raw PREROUTING chain before NAT. Add each restricted peer's exact allows
followed by its drop before the final unrestricted return; use its unique
tunnel address. Deploy through `task apps:wireguard:check` and
`task apps:wireguard:deploy`, then `task apps:wireguard:verify` and actual
client allow/deny tests. Do not apply the legacy host table to `.100` as a
substitute: Docker NAT changes the path and hides peer addresses from LAN
services. Creating a peer in wg-easy alone does not give it a restricted policy.
See the [replacement role and migration procedure](../ansible/roles/wg-easy/README.md).

Reuse the access worksheet and allow/deny tests, **not** the legacy `.9` host commands unchanged. D-021 was amended on 27 October 2026 to retain `10.115.145.0/24` and existing peer addresses; moving WireGuard to `lab-access-01` does not require renumbering. The first flat-LAN move uses scoped NAT, with peer restrictions enforced before translation. The later VLAN/router design adds a return route for this retained subnet and default-deny inter-zone policy; private destinations can then be routed without masquerading so router and proxy policy can identify peers. Express guest policy in Ansible and router rules in its chosen IaC mechanism. Recheck DNS, proxy and backend paths after either migration. The reported endpoint is `donk.live:27272` with DNS `192.168.1.100`; the 27 October DDNS fix now maintains both apex and `vpn.donk.live` DNS-only A records. WireGuard/router cutover remains separate.

## References

- [Netfilter hooks and priority](https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks)
- [Atomic nftables file loading and table-specific replacement](https://documentation.ubuntu.com/security/security-features/network/firewall/nftables/)
- [Docker's firewall chains](https://docs.docker.com/engine/network/firewall-iptables/)
- [WireGuard routing and DNS profile fields](https://man7.org/linux/man-pages/man8/wg-quick.8.html)

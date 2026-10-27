#!/bin/sh
set -eu
# Own only this container's raw chain; apply before the WireGuard interface starts.
# Early filtering covers local input AND forwarding, before any NAT or UI rules.
iptables -t raw -N HOMELAB_WG_PEERS 2>/dev/null || true
iptables -t raw -F HOMELAB_WG_PEERS
iptables -t raw -C PREROUTING -i wg0 -j HOMELAB_WG_PEERS 2>/dev/null ||
  iptables -t raw -I PREROUTING 1 -i wg0 -j HOMELAB_WG_PEERS
iptables -t raw -A HOMELAB_WG_PEERS -s 10.115.145.7/32 -d 192.168.1.9/32 -p tcp --dport 3000 -j RETURN
iptables -t raw -A HOMELAB_WG_PEERS -s 10.115.145.7/32 -d 192.168.1.100/32 -p tcp --dport 53 -j RETURN
iptables -t raw -A HOMELAB_WG_PEERS -s 10.115.145.7/32 -d 192.168.1.100/32 -p udp --dport 53 -j RETURN
iptables -t raw -A HOMELAB_WG_PEERS -s 10.115.145.7/32 -j DROP
# All users administer through HTTPS/Caddy, not through the tunnel's UI port.
iptables -t raw -A HOMELAB_WG_PEERS -d 10.115.145.1/32 -p tcp --dport 51821 -j DROP
iptables -t raw -A HOMELAB_WG_PEERS -d 172.30.91.2/32 -p tcp --dport 51821 -j DROP
iptables -t raw -A HOMELAB_WG_PEERS -j RETURN
exec /usr/bin/dumb-init node server/index.mjs

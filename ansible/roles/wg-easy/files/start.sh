#!/bin/sh
set -eu
# This namespace belongs only to wg-easy. No client identities or host rules.
iptables -P FORWARD DROP
iptables -I INPUT 1 -i wg0 -j DROP
# wg-easy inserts its WG_CLIENTS_wg0 jump ahead of these fallback drops.
# Empty/rebuilding/disabled native filtering therefore cannot fall through
# into wg-quick's later broad ACCEPT rules.
iptables -A FORWARD -i wg0 -j DROP
iptables -A FORWARD -o wg0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -o wg0 -j DROP
exec /usr/bin/dumb-init node server/index.mjs

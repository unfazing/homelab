# Caddy role

Builds Caddy 2.11.4 from digest-pinned official builder and runtime images with only `caddy-dns/cloudflare` v0.2.4 added. The role stores the Cloudflare token outside persistent application data, publishes TCP 443 only on the services VM address, reaches Gitea through the dedicated `homelab-proxy` Docker network, and never mounts the Docker socket.

Staging and production ACME state use separate directories below `/srv/homelab/reverse-proxy`. Use `task apps:caddy:deploy-staging` first; production issuance requires a separate explicit confirmation.

# Caddy role

Builds Caddy 2.11.7 with Go 1.27.3 from digest-pinned official builder and runtime images, updated Alpine certificate trust and only `caddy-dns/cloudflare` v0.2.4 added. The role stores the Cloudflare token outside persistent application data, publishes TCP 443 only on the services VM address, reaches Gitea through the dedicated `homelab-proxy` Docker network, and never mounts the Docker socket.

The explicit `adguard.home.<domain>` route proxies to the access VM's HTTP
backend on port 3000. The access VM firewall admits that port only from Caddy
and guest-local traffic; the HTTPS route itself has no client certificate or
client-IP allowlist, and AdGuard still requires its own login. The hostname is
published only by the replacement `.100` resolver until client DNS cutover.

The explicit `inkling.home.<domain>` route proxies to the legacy
`192.168.1.9:3000` HTTP backend. Its private DNS answer is Caddy's `.101`
address, not the backend's `.9` address. The legacy backend currently responds
at `/sources`; if it stops, the route can return a proxy error. Caddy does not
deploy or authenticate that service, and the backend is not managed by this
repository.

Staging and production ACME state use separate directories below `/srv/homelab/reverse-proxy`. Use `task apps:caddy:check-production` to preview changes to the live route without swapping to an untrusted staging certificate. Production deployment requires a separate explicit confirmation.

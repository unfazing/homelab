# Hermes role

Builds a security overlay on digest-pinned Hermes 0.22.5: fixed Node 26.12.1,
checksum-pinned brotlicffi 1.2.1.0, certifi 2026.10.23, pip 26.2.2 and updated
Debian trust. Build checks use no private data mounts. Deployment on
`lab-agents-01` seeds provider-neutral configuration and the password-gated
dashboard; operator-configured Codex and Telegram settings are preserved.
No agent API is published. The existing `homelab-hermes` VirtioFS dataset is mounted at `/opt/data`
and owned by the image's runtime UID 10000. `config.yaml` is seeded once with
SQLite DELETE journaling, the dashboard password hash, and a stable session
signing key; Hermes may subsequently maintain its own config. The plaintext
bootstrap password remains only in the ignored controller secret file.

The dashboard listens on the guest at port 9119, but an nftables pre-routing
rule admits only Caddy's address. Caddy terminates private HTTPS. The backend
firewall and management egress boundary are required before Docker starts after a reboot. No Docker socket,
Gitea credential, provider key, or CI job is granted here yet.

Run `task apps:hermes:deploy`, then reconcile Caddy and AdGuard with their
existing production deployment Tasks. Use `task apps:hermes:credentials` for
the initial login. Inspect `state.db` journal mode and memory use before
turning on model access or other agent tools.

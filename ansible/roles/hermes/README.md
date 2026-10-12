# Hermes role

Deploys the official, digest-pinned Hermes container on `lab-agents-01` with
the built-in password-gated dashboard and no model provider or published agent
API. The existing `homelab-hermes` VirtioFS dataset is mounted at `/opt/data`
and owned by the image's runtime UID 10000. `config.yaml` is seeded once with
SQLite DELETE journaling, the dashboard password hash, and a stable session
signing key; Hermes may subsequently maintain its own config. The plaintext
bootstrap password remains only in the ignored controller secret file.

The dashboard listens on the guest at port 9119, but an nftables pre-routing
rule admits only Caddy's address. Caddy terminates private HTTPS. The backend
firewall is required before Docker starts after a reboot. No Docker socket,
Gitea credential, provider key, or CI job is granted here yet.

Run `task apps:hermes:deploy`, then reconcile Caddy and AdGuard with their
existing production deployment Tasks. Use `task apps:hermes:credentials` for
the initial login. Inspect `state.db` journal mode and memory use before
turning on model access or other agent tools.

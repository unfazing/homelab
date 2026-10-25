# Homelab security campaign — 25 October 2026

Historical record of the one-time patch campaign, stored under `history/security-2026-10-25/` and excluded from the active deployment interface. This is an ordinary directory in the homelab repository, not a nested repository or submodule.

- `docs/`: baseline assessment and remediation/verification report, including unresolved findings.
- `ansible/playbooks/`, `ansible/inventories/maintenance/`, `taskfiles/security.yml`: original one-time procedures, retained as evidence, not a supported operator interface.
- `runtime-baseline/`: a snapshot of the patched application/container and permanent firewall sources that remain maintained in homelab. This may include pre-existing integration settings; it is historical context, not a clean feature diff.
- `inventory/guests.example.json`: allowlisted host addresses, SSH usernames/ports and VirtioFS metadata only.
- `manifest.json`: original source paths and SHA-256 hashes, with the source commit before cleanup.

Do not replay the dated tasks blindly: they contain old version assertions, host addresses, snapshot names and reboot/backup operations. They refer to the original homelab layout and guest-installed helpers. Any future campaign must re-review candidates, dependencies, access, backup readiness and remaining risks.

No credentials, private keys, environment files, Terraform state, generated VPN profiles or application/VM backup contents are included. Recovery data stays on the server. Archived Task definitions are historical evidence, not active deployment commands.

The active repository keeps the application version/build definitions, readiness fix and persistent management-boundary role so future deployments retain those controls. Its canonical documents describe current configuration, not this campaign's execution history.

## Persistent baseline commits

The security-only patch in `runtime-baseline/persistent-security.patch` records these homelab commits without the concurrent Homepage changes:

- `95552e2` — `fix(security): rebuild patched application and container runtimes`
- `e6781be` — `feat(security): preserve agent management isolation`

The one-time campaign files were uncommitted before archiving. They are versioned here as dated records; the supported deployment configuration remains in the active application roles.

## Original archive history

`archive-history.bundle` preserves both commits from the original standalone archive, including its original README and manifest. To inspect that independent history elsewhere:

```sh
git clone history/security-2026-10-25/archive-history.bundle /tmp/homelab-security-history
```

The original archive HEAD was `2fe583988a5dd88164e45714e2af3a439b8998ab`. There is no embedded `.git` directory.

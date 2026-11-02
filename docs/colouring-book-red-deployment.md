# Colouring-book: red deployment admission

Prepared **2 November 2026** for `lab-agents-org/colouring-book-v1`, branch
`feat/container-deployment`. The operator completed `task red-app:install`; live
checks confirmed pinned source hashes, root-owned code, protected metadata paths,
forced-command refusal of shell access and `RED_DEPLOY_ENABLED=false`. No application
deployment or data migration has run.

| Setting | Value / status |
| --- | --- |
| Runner | `red-docker-01`; workflow label `homelab-docker` |
| SSH address / port | `192.168.1.9` / `22`; use the LAN IP from job containers |
| Non-root deployment identity | Existing `homelab-deploy`, UID `1002` |
| Production Docker endpoint | `unix:///run/user/1002/docker.sock`; separate from CI UID `1001` |
| Repository variables | `RED_DEPLOY_HOST=192.168.1.9`, `RED_DEPLOY_PORT=22`, `RED_DEPLOY_USER=homelab-deploy`, **`RED_DEPLOY_ENABLED=false`** |
| Repository secrets | `RED_DEPLOY_SSH_KEY`, `RED_DEPLOY_KNOWN_HOSTS` installed; no organization-wide grant |
| Server host-key fingerprint | Ed25519 `SHA256:UEZo8c3IvqwcBCgnMow1iBEQQQRZ3CIllyZ+y4k0qWE` |
| Reviewed launcher revision | `fa70be5717ac7a744e197591419155a21629cd0e`; pinned file hashes in the installer |
| Installed deployment snapshot | `/opt/homelab/colouring-book/deployment` — root-owned code and Compose; only `.deploy/` writable by deployment user |
| Installed forced command | `/usr/local/libexec/colouring-book-deploy`; accepts only SSH command `colouring-book-deploy` and bounded release records |
| Installed runtime settings | `/etc/colouring-book/runtime.env`, root:homelab-deploy `0640`; **provider key must be entered on red** |
| Planned external gallery | `/srv/homelab/colouring-book/data`; **not created or populated by this installer** |
| Registry credential | `read:package` PAT for existing `lab-agent`; controller copy in ignored mode-600 `.generated/red-deploy/registry-credentials.json` |
| Installed registry configuration | `/var/lib/homelab-deploy/.docker/config.json`, `0600`; contains a credential, not encryption |

The host key was read over the existing trusted SSH connection and compared with
the laptop's previously pinned Ed25519 record. No unauthenticated `ssh-keyscan`
result was trusted. Local SSH key and known-hosts files are under ignored
`.generated/red-deploy/`; never paste their private contents into issues/chat.

## Install the prepared host access

From the homelab repository on your laptop:

```sh
task red-app:install
```

Ansible asks for **red's sudo password at its hidden prompt**. The task fetches only
the fixed reviewed deployment files from Gitea, verifies their SHA-256 checksums,
checks that the two rootless daemon IDs differ, then installs the snapshot,
entrypoint, daemon-ID pin, registry login and forced SSH key. The same authorized-key
template is used by the runner installer, so a later runner convergence retains
this admission. It creates deployment metadata directories, not gallery data.
It does not start containers, stop the current app, dispatch Actions or enable deploys.

The installer creates `runtime.env` only if absent and never overwrites it on
retries. Set its `OPENROUTER_API_KEY` directly on red:

```sh
ssh server@192.168.1.9
sudoedit /etc/colouring-book/runtime.env
```

The key belongs only in that server file, never in Actions. The default generation
worker count is `2` for the shared host; frontend binds `.9:3000`. The backend binds
loopback `:8000`. Both ports are currently occupied by the old native app.

After installation, from the laptop, this **negative test** must reject shell access:

```sh
ssh -T -i .generated/red-deploy/id_ed25519 \
  -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=.generated/red-deploy/known_hosts \
  homelab-deploy@192.168.1.9 whoami
```

Expected: the app entrypoint refuses the command and exits nonzero. This does not
exercise Docker deployment, data permissions or health checks. An actual workflow
still needs to prove connectivity from its disposable job container.

## Required before enabling

1. Review and merge the workflow/client onto `main`. The prepared deployment
   workflow checks out `main` and refuses feature-branch dispatches and releases
   outside main's ancestry. It currently exists only on the feature branch.
2. Arrange a maintenance window for the native app at
   `/home/server/dev/colouring-book-v1`. Preserve its catalog and images and plan
   a consistent SQLite handoff. Do not copy a live database as if it were a
   consistent snapshot or change the running checkout's ownership.
3. Prepare the external gallery path and validate container UID/GID `10000:10000`
   under the **deployment daemon's user namespace**. Those are not host UID/GID
   10000. Do not run a speculative recursive `chown` against the existing data.
   The trusted app launcher checks compatibility/access before draining.
4. Set the server provider key; test pulling both published images through the
   deployment daemon. The prepared PAT can read packages visible to `lab-agent`,
   not only this application's images, but cannot publish packages. Link private
   packages to their repository and verify access; token scope alone does not
   establish package permissions. CI must not receive this server Docker config.
5. Stop/drain the old native services, hand off ports `3000` and `8000`, and confirm
   the Caddy route still targets `.9:3000`. The installer does not do this.
6. Validate an actual runner job's SSH path, image pull, paired release, health,
   gallery persistence and explicit recovery. The app protocol includes
   `CI_DOCKER_ID` plus a three-line release manifest; **do not use the generic
   homelab JSON release example for this key**.
7. Only after acceptance, set `RED_DEPLOY_ENABLED=true` and manually dispatch with
   `confirmation=DEPLOY_RED` and the full published commit. No automatic trigger
   is added. Do not dispatch merely to test setup.

The deployment key gives workflow code authority to run admitted application images
with that application's data and server-side provider credential. The enable flag
is an operational guard, not secret isolation: protect repository workflow changes
and Actions administration. No general SSH shell, sudo, rootful Docker, Terraform
or Proxmox authority is granted. Interrupted deployments require operator inspection;
never automatically retry paid generation or assume a disconnect means failure.

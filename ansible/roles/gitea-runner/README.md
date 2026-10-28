# Temporary Docker CI/CD worker

Gitea Runner 5.2.3 runs natively on existing `red-server` (`192.168.1.9`), scoped
to **all repositories in `lab-agents-org`**. Jobs use the `homelab-docker` label.
The tool image includes Git, Docker CLI, Buildx and Compose v2. This installer
does not create repositories, switch application branches or install workflows.

## Install

Load the repository's normal environment, then run:

```sh
task apps:runner:validate
task apps:runner:deploy
```

The second task asks for **red-server's sudo password** through Ansible's hidden
terminal prompt. It uses the generated Terraform inventory plus the explicit
external-host inventory. It does not run the VM baseline against red, replace
its Docker engine, change router forwarding or touch WireGuard's rules.

The sequence is: install prerequisites → guarded rootless runtimes → boundary
checks → enable Gitea Actions → enroll once using a temporary token file → start
the worker. Persistent registration is mode 0600; retries do not enroll again.
Ansible task logs hide enrollment credentials. Gitea's Actions feature is now
enabled by its canonical configuration; workers accept jobs only after the
foundation checks pass. Each application repository must separately enable
Actions in Gitea settings. Initially run reviewed workflows manually; automatic
deployment triggers and branch protection are a separate operator policy.

RootlessKit and its setup helper come from **Docker's
`docker-ce-rootless-extras`**, pinned to the installed `docker-ce` package version.
Do not install Ubuntu's conflicting standalone `rootlesskit` package. A failed
first rollout installed that package and removed Docker's extras; the installer
now removes only the conflict and reinstalls matching extras automatically on
retry. Prerequisite installation refuses other implicit apt removals. It neither
upgrades nor replaces the existing Docker CE engine.

## Trust boundary

* `homelab-ci`: rootless Docker for disposable jobs/builds; no Docker group,
  rootful socket, host-mode label, application daemon or app data mounts.
* `homelab-deploy`: a second rootless daemon for persistent application services.
  Its SSH keys are app-specific and force a root-owned deployment command;
  shell, forwarding and arbitrary Docker commands are unavailable to workflows.
* Each whole user slice starts with 2 CPU / 3 GiB / no swap / 2048 tasks. One CI
  job at a time; a 10 GiB free-space floor pauses new job admission. Image/build
  caches can still consume disk: this admission floor is not a hard quota, and
  an active job can fill the shared root filesystem. Review CI disk use (use a
  separate quota-limited filesystem for stronger isolation) and clean only this daemon,
  never the existing rootful application daemon or persistent data.
* The dedicated nftables table permits AdGuard DNS, shared Caddy HTTPS `.101`,
  public HTTP(S) dependency/registry traffic and CI → red SSH for forced deploys.
  Other private/link-local destinations and IPv6 egress are denied for these
  two users. Return traffic for app clients is allowed. **All Caddy HTTPS routes
  share `.101:443`; this rule does not authorize individual hostnames.**
* This is shared-kernel, organization-wide execution, not tenant isolation.
  Admitted image code receives the application's data/secrets and can exfiltrate
  over allowed HTTPS. A hostile org workflow or kernel exploit is consequential;
  the later dedicated runner VM remains the stronger boundary.

No application is admitted by default. Installing the runner therefore grants
no application deployment key and creates no durable application data.

## Admit an application

The operator reviews and versions the Compose contract, then adds an entry to
`ansible/vars/runner-apps.yml` (controller paths are relative to the playbook
unless absolute). Keep secret files under ignored `.generated/secrets/`:

```yaml
gitea_runner_app_contracts:
  - name: colouring-book
    compose_file: /absolute/path/to/reviewed-compose.yaml
    runtime_env_file: /absolute/path/to/.generated/secrets/colouring-book.env
    images:
      backend:
        repository: gitea.home.example.com/lab-agents-org/colouring-book-backend
        variable: BACKEND_IMAGE
      frontend:
        repository: gitea.home.example.com/lab-agents-org/colouring-book-frontend
        variable: FRONTEND_IMAGE
    authorized_keys:
      - ssh-ed25519 PUBLIC_KEY_FROM_APP_SPECIFIC_DEPLOY_KEY
```

This is a schema example, not an admitted workload. Use the actual private
domain. Review fixed LAN bind addresses/ports, read-only root filesystems,
capability drops, resource limits, health checks, dependency ordering and volume
paths. No `build:`, Docker socket, host namespace, privileged mode, arbitrary
Compose include, writable configuration mount or Docker daemon access belongs
in an app contract. Every service image must be an admitted image variable.
Runtime settings must not override those image variables. Data paths must be
separate from CI cache and deployment release metadata. Rootless container UID
10000 is **not host UID 10000**: provision and test mapping explicitly, never
recursively chown existing data speculatively.

The existing `feat/container-deployment` branch already has the first app's
Dockerfiles/Compose/health checks. Its `run-local.sh` also implements application
maintenance/drain semantics. The generic contract wrapper waits for Docker's
graceful stop and health checks, but does not reproduce that script's custom
maintenance protocol. Review/adapt this before admitting that application with
in-flight generation jobs. Its current data location, secrets, exact reviewed
Compose snapshot and promotion policy still need to be supplied.

Generate a **different Ed25519 deployment key per app** in an ignored protected
location. Add only its public half above. Store the private half in that
application's Gitea Actions secret, never an org-wide build environment. Pin
red's SSH host key using the already trusted operator SSH connection, rather
than disabling host verification. Registry upload credentials belong only in
the publication job; private image pull credentials must separately be installed
in the deployment user's Docker config, mode 0600. Neither is provisioned by
the runner installer. Do not reuse an administrator or Hermes token.

After reapplying the installer, a job can send this bounded request using its
app-specific key and pinned known_hosts file:

```sh
ssh -T -i "$DEPLOY_KEY_FILE" -o IdentitiesOnly=yes \
  -o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS_FILE" \
  homelab-deploy@192.168.1.9 deploy < release.json
```

```json
{
  "revision": "40-character-lowercase-commit-SHA",
  "images": {
    "backend": "gitea.home.example.com/lab-agents-org/colouring-book-backend@sha256:64-hex-digest",
    "frontend": "gitea.home.example.com/lab-agents-org/colouring-book-frontend@sha256:64-hex-digest"
  }
}
```

The SSH key fixes the app name. Requests cannot add ports, mounts, services or
environment. Pull completes before replacement; unhealthy promotion attempts
restore the previous recorded release. `status` reports recorded image refs
(not a live health probe); `rollback` promotes the previous release. Operations
serialize per app and never use `compose down --volumes`. An initial failed
deployment has no prior release to restore. Automatic rollback cannot reverse
database/schema changes; app migration compatibility remains an app concern.

## Acceptance and operations

After installation, check **Organization → Settings → Actions → Runners** for
`red-docker-01`, then use the manual example in
`docs/examples/gitea-docker-smoke.yml` in an operator-managed pilot repository.
Actual Actions execution (including Docker proxy/build/test cleanup), app
health/rollback, restart persistence and a second idempotent Ansible apply must
pass before marking this rollout complete. The installer verifies tool
availability and host boundaries; syntax/unit tests alone are not that proof.

On red, inspect the services without printing their credentials:

```sh
sudo systemctl status homelab-runner-egress
sudo nft list table inet homelab_ci_egress
sudo -u homelab-ci XDG_RUNTIME_DIR=/run/user/$(id -u homelab-ci) \
  systemctl --user status gitea-runner docker
sudo -u homelab-ci XDG_RUNTIME_DIR=/run/user/$(id -u homelab-ci) \
  journalctl --user -u gitea-runner -n 50
```

To pause jobs, stop the CI user's `gitea-runner` service. Do not stop the app
daemon or delete release/data directories. Deleting a registration requires
explicit operator removal of the stale runner in Gitea before re-enrollment.

References: [runner jobs/proxy cleanup](https://docs.gitea.com/runner/jobs/),
[runner configuration](https://docs.gitea.com/runner/reference/config-example/),
[Docker rootless](https://docs.docker.com/engine/security/rootless/).

# Homepage

Deploys the private owner dashboard on `lab-services-01` at
`https://dashboard.home.<domain>/`. Use `task apps:homepage:deploy`,
`:check`, `:verify` and `:credentials`. Credentials are printed only by the
explicit operator credentials task; deployment never prints them.

The digest-pinned 2.7.0 image runs as UID/GID 10001, with a read-only root and
configuration mount, disposable logs/tmp, 512 MiB memory and 0.5 CPU limits.
Seed `custom.css` and `custom.js` before startup: upstream otherwise tries to
create them during browser requests. No Docker socket, application data mount,
host networking or published HTTP port is granted. MCP is disabled.

Ansible owns YAML under `/opt/homelab/homepage/config`; custom edits will be
reconciled. `HOMEPAGE_FILE_*` secrets under `/etc/homelab/homepage` must not
contain a trailing newline: upstream substitutes bytes directly into YAML.
Validation handles resolved secrets without logging their values. Checksums
trigger container recreation when configuration or credentials change.

## Explicit trust expansion (D-082)

- **AdGuard:** normal user `homepage`, with administrator-equivalent DNS and
  configuration authority. Native widget reads statistics, but hiding controls
  does not restrict the credential. This grant was explicitly approved.
  Provisioning stops AdGuard briefly, preserves the operator account, verifies
  both logins and DNS, and rolls back on failure. Operator password rotation
  now edits only its named account and preserves the dashboard account.
- **Caddy:** full admin API on container loopback `127.0.0.1:2019` only.
  `172.30.90.2:2020` forwards only GET `/reverse_proxy/upstreams`; no other
  paths/methods forward. Ports 2019/2020 are not host-published. `num_requests`
  describes current requests, not lifetime traffic. Acceptance checks inspect
  the active matcher instead of sending dangerous `/load` or `/stop` POSTs.
- **Proxmox:** `homepage@pve!dashboard`, privilege separation enabled, with
  PVEAuditor on both user and token at `/`. Read-only cluster/VM metadata,
  including legacy guest inventory; no VM power/configuration authority.
- **Gitea:** restricted non-admin `homepage-observer`, zero repository quota,
  read-only repository/issue/notification scopes. Repository and team grants
  are operator-managed. Zero private repositories is an expected initial view.
- **Native login:** password-only, no username; the original dashboard password
  is preserved. Protected `dashboard-password` and `session-secret` files are
  loaded inside Node before Homepage starts, not passed as Compose environment
  values. Keep both ignored controller recovery files. Replacing the signing
  secret invalidates sessions. Caddy retains HTTPS, without Basic Auth.
  Homepage never mounts Caddy secrets, ACME data or the Docker socket.

The dedicated internal `homelab-homepage` bridge is `172.30.90.0/29`, with
Caddy `.2`, Homepage `.3` and the snapshot reader `.4:8080`. The role owns its idempotent creation and
isolation checks in `tasks/network.yml`; Caddy reuses only that entry point
through `include_role` with `tasks_from: network`. Shared settings remain in
`ansible/vars/homepage.yml`. Homepage also has an egress network. Root on the
shared services VM remains trusted; Docker separation is not a separate VM.
Jellyfin is excluded. No VM, VLAN, WAN forward or application dataset was added.

## Verified TLS and recovery

Upstream 2.7.0's widget helper creates HTTPS agents with verification disabled.
`verified-tls.cjs`, preloaded via NODE_OPTIONS, forces certificate verification
before dependencies load. NODE_EXTRA_CA_CERTS adds blue's public CA, whose
certificate includes its IP. The guard was tested against an untrusted local
certificate and real widget requests; reassess on every image upgrade.

Configuration is rebuildable from Git. Dashboard password/session secret, AdGuard credentials and the Gitea
observer token have ignored controller files under `.generated/secrets/`;
blue retains the Proxmox token under `/etc/homelab/homepage-observer/`.
Back these up separately or deliberately revoke/reissue if lost. Existing
tokens with missing raw credentials fail closed instead of issuing duplicates.
Removing an identity also requires removing its desired grant before future
convergence; stopping the dashboard alone does not revoke a stolen credential.

Verification covers login/API gating, seven native widget queries, secret
redaction, private DNS, runtime privileges, Host validation, MCP denial,
verified TLS and Caddy's read-only route. Homepage shares blue/DNS/Caddy failure
modes; it is neither independent outage monitoring nor a vulnerability scanner.

## Curated infrastructure inventory (D-083)

The root-owned `homelab-homepage-observer.timer` runs `collect.py` every minute.
Its Docker access is host-administrator authority, separately trusted from
Homepage. It reads active Caddy JSON in memory and queries the existing
audit-only Proxmox token; only selected fields reach the atomic snapshot at
`/var/lib/homelab/homepage-observer/snapshot.json`. No raw config is saved.
Python's newer strict X.509 mode rejects the existing Proxmox CA's missing
key-usage extension. Only that private-CA client clears VERIFY_X509_STRICT;
certificate chain verification and IP hostname checks remain required.
Public TLS probes retain default strict validation. Revisit when blue's CA is renewed.

VM status, CPU/allocation, host-accounted RAM/VM allocation and uptime are always visible.
The memory numerator is Proxmox `memhost` (falling back to `mem`), not guest
Linux `free`/working-set usage; guest memory would require a separate guest metrics source.
Network and disk byte rates require two samples and reset after reboot or
counter reset. These are hypervisor counters, not guest filesystem usage.
VM IDs/names are the role's `homepage_observer_vms` list (1000–1002).

Exact hostnames under `home.<domain>` are discovered from active HTTPS routes,
including nested/OR matchers; wildcard/fallback routes are labelled. TLS probes
connect to Caddy with each hostname as SNI and verify its certificate, exporting
issuer, expiry/days and negotiated version. This checks currently served TLS,
not whether future renewal will succeed. At most 64 matchers are probed per run.
New routes appear within a collection/widget refresh; DNS provisioning is separate.
The Network → Caddy card combines native counters and compact route/TLS-days
rows, deduplicated shared certificate details and one freshness/error row.
Full allowlisted metadata remains in the snapshot; raw configuration is never exposed.

The non-root reader container uses the same pinned image with a small Node
entry point. It mounts only code and read-only JSON, joins only the internal
bridge, publishes no port and has no credentials or Docker access. It serves
only GET `/snapshot`. Homepage's Custom API widgets refresh every 15 seconds.
Partial failures are explicit; component data older than 180 seconds becomes
stale/unknown, retaining the old route inventory for diagnosis.

Tests: `python3 -m unittest discover -s ansible/roles/homepage/tests` and
`node --test ansible/roles/homepage/tests/test-observer.cjs`. Live verification
tests native CSRF login/logout, secure sessions, secret redaction and isolation.

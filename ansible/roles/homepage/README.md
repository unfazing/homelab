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

## Physical host statistics

The Infrastructure group includes red's physical-host CPU/load, RAM/swap,
uptime, filesystem usage and sampled LAN/disk rates. This complements Proxmox's
VM allocation/accounting statistics. Sources are explicit in
`ansible/vars/homepage.yml`: `eno1`, whole disk `sda`, root, PostgreSQL and Garage
mounts. It does not report process arguments, environment variables, application
files, Docker containers, SMART health or historical trends.

`task apps:homepage:deploy` now also provisions the observed external host and
asks for red-server's sudo password at a hidden terminal prompt. It reuses the
same deployment from `task apps:storage:deploy VERIFY_RESTART=true`; no second
Homepage rollout is needed when running that combined command.
`task apps:homepage:validate` runs local regression/syntax checks;
`:check` previews dashboard configuration without enrolling host identities;
`:verify` checks the deployed dashboard and forced SSH command.

The trusted root collector on services holds a separate key per host in
`/etc/homelab/homepage-observer`, root-only and **not mounted into Homepage**.
Red has a password-locked `homepage-monitor` account with no supplemental groups,
no sudo/Docker grant, and root-owned home, authorization policy, reporter and
configuration. Its key accepts connections only from `.101` and forces the
isolated Python reporter; `restrict` denies PTY, forwarding and user rc files.
The collector pins red's Ed25519 host key obtained over the controller's already
verified Ansible connection. There is no new daemon, listening port or API token.

The reporter runs briefly on each SSH request. Existing collection runs every
minute; the dashboard refreshes its snapshot every 15 seconds. CPU and I/O rates
need two successful samples and restart after reboot/counter reset or a gap over
180 seconds. RAM is total minus Linux `MemAvailable`, excluding reclaimable
cache. Disk figures show used/total and user-available space, not SMART status.
Missing data mounts are marked missing rather than showing the root filesystem.
Recent collection errors retain the last good sample with a visible error;
after 180 seconds every display value becomes stale/unknown.

A services-VM rebuild generates a new monitoring key and redeploys its public key
to red through the same sudo-prompted Task. An intentional red host-key change
must first be verified in the controller's SSH trust store; deployment never
uses `ssh-keyscan` or disables host-key checking. No application secrets or
persistent data are changed by monitor enrollment.

## Infrastructure layout and blue metrics

Infrastructure contains two equal host cards, three compact VM cards and a
collapsed Storage & activity group. Shared Jinja widget macros render matching
labels and refresh behavior. VM RAM remains Proxmox accounting/allocation, not
in-guest Linux application usage. Detailed per-VM I/O remains available in the
snapshot and Proxmox; the overview retains four primary fields per VM.

The existing audit token reads node status, one-hour RRD samples, storage usage
and the configured ZFS pool's metadata. No new SSH access or PVE permission is
added for blue. CPU, network, I/O wait and ARC use the latest complete one-minute
RRD average; preserve its source timestamp and reject old/future samples. Node
status and storage have independent timestamps. ZFS exports capacity, health and
an allowlisted scrub summary; raw error paths, actions and suggested commands are
never passed to Homepage. Blue's physical disk throughput is not supplied by
these endpoints. Red continues using its unchanged fixed SSH report.

After initial enrollment, `task apps:homepage:refresh` updates configuration and
the collector using installed credentials, host keys and native session state.
It reuses the same `configuration.yml` role entry point as full deployment, and
requires existing credentials/root-only telemetry trust instead of generating or
replacing identities. It runs only on services and requires no red sudo prompt.
Fresh installation/recovery still uses `task apps:homepage:deploy`.

## Storage service statistics

Storage is directly below Virtual machines. Both cards put **disk used / capacity**
first, using red's mounted-filesystem counters (including metadata/WAL). Garage's
64 GiB advertised capacity is distinct from its 80 GiB LV and formatted capacity.

The remaining Garage rows show buckets, objects, logical object bytes, S3 requests
and errors per minute, and cluster health. PostgreSQL shows manifest application
databases, logical user tables (partition parents counted once), total database
bytes, active/total/maximum client connections, transactions/sec and blocked
connections. Database sizes include indexes; connection counts are instance-wide,
excluding the reporter session. Transactions include monitoring, not queries/sec.

`storage-observer` runs a 96 MiB collector in red's rootless storage daemon on an
internal-only Docker bridge. Its Garage token has only `GetClusterStatistics`,
`GetClusterHealth` and `Metrics`. The `homelab_monitor` SQL login has no role
memberships or application-table grants; it can call zero-argument, postgres-owned
aggregate functions in the maintenance and manifest databases. No SQL text,
records, keys or raw API responses are exported.

The collector writes a bounded, allowlisted JSON cache under
`/var/lib/homelab/storage-observer/`, owner homelab-storage, reader group
homepage-monitor. The existing fixed SSH reporter reads only that cache; it gains
neither Docker nor service credentials. Homepage still receives sanitized JSON
only. Disk and service timestamps are independent; missing/stale metrics become
unknown after 180 seconds. Rates need two valid samples; resets warm up again.

Fresh installs use `task apps:storage:deploy`. Existing installations use
`task apps:storage:monitoring:deploy` (red's hidden sudo prompt), which adds the
internal bridge/HBA and briefly recreates PostgreSQL/Garage without deleting data.
The same task is repeatable; this is configuration convergence, not migration.
`task apps:homepage:refresh` only refreshes the installed dashboard and cannot
provision the red-side collector or credentials.

Network also includes a wg-easy portal link and HTTP availability. It does not
receive the VPN administrator login or infer peer/tunnel health; router ingress
remains on red until the separately planned cutover.

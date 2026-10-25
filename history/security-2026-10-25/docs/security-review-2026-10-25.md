# Homelab security review — 25 October 2026

This is the **before-update baseline**. See the [remediation report](security-remediation-2026-10-25.md) for actions subsequently taken, live verification and findings that remain open.

**Result: remediation required.** This review matched the specified October incidents and relevant vendor advisories to live versions on five machines. It is a vulnerability/exposure assessment, not certification against a named compliance framework or a forensic investigation. No packages were installed, services stopped, credentials rotated, or machines rebooted during the review.

## Coverage and inventory

Read-only SSH checks reached both physical servers and every running VM. Proxmox reported nine guest/template objects and no LXC containers.

| Machine | Observed runtime | Main findings |
| --- | --- | --- |
| `blue` / `192.168.1.10` | Debian 13; PVE manager `9.1.4`; host kernel `6.17.4-1-pve`; QEMU package `10.1.2-5` | Security package backlog, old host kernel, missing Intel microcode package, old CA bundle; Proxmox firewall reports `disabled/running`. |
| `red-server` / `192.168.1.9` | Ubuntu 24.04.5; kernel `6.8.0-147`; Docker `29.9.1`; WireGuard, Inkling, AIO controller, Jellyfin, Samba | Vulnerable PHP and Node runtimes; old Python certifi; Docker lacks the eMudhra mitigation release. Full privileged host/firewall inspection unavailable because sudo requires a password. |
| `lab-access-01` / `.100` / VM 1000 | Ubuntu 26.04.1; AdGuard `0.107.79`; Docker `29.8.1` / containerd `2.3.5` | Held container-runtime packages miss security releases; kernel `7.0.0-31` running with `7.0.0-38` installed; reboot required. |
| `lab-services-01` / `.101` / VM 1001 | Ubuntu 26.04.1; Gitea `1.27.3`; Caddy `2.11.4`; Docker `29.8.1` | Gitea advisory match, old Go builds and container trust stores; kernel `7.0.0-34` running with `7.0.0-38` installed; reboot required. |
| `lab-agents-01` / `.102` / VM 1002 | Ubuntu 26.04.1; Hermes `0.21.6`; Docker `29.8.1` | Affected Node/Brotli and certifi inside Hermes; kernel `7.0.0-31` running with `7.0.0-38` installed; reboot required. |

| Powered-off object | Name | Assessment limit |
| --- | --- | --- |
| VM 100 | `proxmox-main` | Inventory checked; guest packages not inspected. |
| VM 101 | `example-vm` | Inventory checked; guest packages not inspected. |
| VM 102 | `agent` | Inventory checked; guest packages not inspected. |
| VM 103 | `windows` | Inventory checked; Windows patch level not inspected. This is not the planned runner VM 1003. |
| Template 104 | `ubuntu-24.04-template` | Template metadata checked; offline OS patch level unknown. |
| Template 9000 | `ubuntu-26.04-template` | Template metadata checked; current clones do not establish the template's patch level. |

The stopped objects were not started or mounted. Do not treat them as cleared for reuse; inventory/update them or rebuild from a reviewed image before reconnecting workloads. Cached but unused Docker images on `.9` are also not equivalent to running services.

## Incident assessment

### 1. PHP2Shell — affected on `.9`; urgent

The running `nextcloud-aio-mastercontainer` was built on **12 November 2024** and contains **PHP 8.3.13**, confirmed with both CLI and **FPM/FastCGI** binaries. `session.upload_progress.enabled` is On. It publishes host ports 81, 8080, and 8443 on IPv4 and IPv6 wildcard listeners and mounts `/var/run/docker.sock`. A container compromise could therefore have host-level consequences through Docker. Only the AIO controller is currently running; no Nextcloud application container was present.

[PHP's 21 October advisory](https://www.php.net/archive/2026.php#2026-10-21-5) fixes CVE-2026-109618 and CVE-2026-109619 in **8.3.36** for this branch (also 8.2.35, 8.4.27, 8.5.12). The observed PHP version is affected; authentication in the application does not remove PHP request-processing exposure. Update/recreate the container from a reviewed, fixed image, or stop the obsolete controller if it is no longer needed. Updating host Ubuntu packages will not replace its bundled PHP.

The [23 October PHP advisory](https://www.php.net/archive/2026.php#2026-10-23-1) also covers CVE-2026-115560 and recommends disabling upload progress while awaiting the regular fix. This third issue additionally needs a particular serializer configuration/runtime switch, which was not established here. Treat that setting as a mitigation to review, not a substitute for updating the older PHP runtime. No exploit was attempted.

### 2. Node/Brotli CVE-2026-111497 — affected on `.9` and inside Hermes; urgent

| Location | Observed | Fixed target for this incident |
| --- | --- | --- |
| Inkling on `.9` | Node **24.22.0**, bundled Brotli **1.2.0** | Node **24.22.1 or later** supported security release; restart the actual Inkling process onto that binary. |
| Hermes container | Node **26.7.0**, bundled Brotli **1.2.0** | Node **26.12.1 or later** supported security release in a rebuilt/reviewed image. |
| Hermes Python environment | `brotlicffi` **1.2.0.2** | Fixed binding **1.2.1.0 or later** with the decoder fix. |

These versions match the [Node October security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases) and [PyPA brotlicffi advisory](https://github.com/pypa/advisory-database/blob/main/vulns/brotlicffi/PYSEC-2026-4323.yaml). The dangerous operation is decoding attacker-controlled Brotli data, including compressed HTTP responses; an agent fetching internet content is a relevant exposure path. Installed affected code is confirmed; exploitability of each application path was not tested.

The [Node 24.22.1 release](https://nodejs.org/en/blog/release/v24.22.1) also updates certificate trust. Verify the security release/build after patching: a cherry-picked fix can leave a bundled library's reported version unchanged. No Bun binary was found on the inspected Hermes PATH, and no Brotli Python package was found in the inspected `.9` project environment.

System `libbrotli1` was `1.2.0-3build1` on all three Ubuntu 26.04 guests and `1.1.0-2build2` on `.9`. [Ubuntu's tracker](https://ubuntu.com/security/CVE-2026-111497) still said “Needs evaluation” for the relevant releases. Their distro fix status remains open; “no APT upgrade available” is not evidence of a fix.

### 3. eMudhra/emSign — trust remediation incomplete

This was a compromise of **intermediate CA keys generated with inadequate randomness**, not evidence that all HTTPS cryptography or this homelab's private keys were broken. [Google's response](https://blog.google/security/protecting-chrome-and-android-users-from-compromised-emudhra-intermediate-ca-certificates/) and [Mozilla's response](https://blog.mozilla.org/security/2026/10/20/protecting-firefox-users-following-the-compromise-of-emudhra-intermediate-certificates/) describe the distrust measures.

The certificate actually served by Caddy is `*.home.donk.live`, issued by **Let's Encrypt YE1**, valid 28 September–27 December 2026. It does not require replacement merely because of this eMudhra incident. Outbound trust is a separate matter:

| Trust/runtime layer | Observed | Assessment |
| --- | --- | --- |
| `.9` and all three VM host OS bundles | Ubuntu `ca-certificates` update installed; emSign ECC G3 file absent | This root-removal check passed for the system bundle only. |
| Proxmox host OS bundle | `ca-certificates 20250419`; emSign ECC G3 still present; candidate `20250419+deb13u1` | Update required. |
| Caddy and Gitea containers | emSign ECC G3 still present; binaries built with Go **1.26.8** and **1.26.7** respectively | Rebuild/upgrade with reviewed runtime and trust-store fixes. |
| Hermes image / Python tools | OS G3 root remains; application `certifi 2026.5.20` and a pip-vendored bundle still include it | Rebuild/update both application and installer trust bundles. |
| Inkling Python environment on `.9` | `certifi 2026.7.22` | Update required. |
| Colouring-book workspace inside Hermes | Application `certifi 2026.10.19`; G3 absent | This application-bundle check passed; it does not clear Hermes's other bundles. |
| Docker on `.9` | **29.9.1**, Go **1.26.9** | Below fixed Docker **29.9.2**. |
| Docker on all three VMs | **29.8.1**, Go **1.26.8** | Below fixed Docker **29.9.2**. |

[Certifi's advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) removes the affected trust; use **2026.10.19 or later** when retaining unaffected roots. [Docker 29.9.2](https://docs.docker.com/engine/release-notes/29/#2992) includes the Go mitigation for CVE-2026-111943. Updating an OS CA package does not rewrite Python bundles, a Node runtime's bundled roots, or existing container images. An interception position is required for the certificate-forgery threat; this review found missing mitigations, not evidence of interception.

### 4. LiteLLM supply-chain compromise — not detected in inspected environments

The [vendor's incident report](https://docs.litellm.ai/blog/security-incident-oct-21-2026) identifies the malicious `litellm==1.107.0` distribution and specific compromised container artifacts on 21 October. No LiteLLM package metadata or LiteLLM container was found in the inspected Hermes runtime/workspaces, relevant guest host paths, or Inkling Python environment. Targeted filename searches also found no `cook.pth`, `cook.py`, `sitecustomize.py`, or `remote_code_loader.lock` in the searched application paths.

Metadata was read from the shell without starting pip or importing packages. This is a limited negative finding, not proof that a package was never installed and removed. If installation history later establishes use of an affected artifact, follow the vendor's rebuild and reachable-secret rotation guidance. The [final attack-chain report](https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain) supersedes early speculation about how the publisher was compromised.

### 5. Railway and Zeabur — not applicable based on confirmed non-use

The operator confirms **never using Railway**. No Railway-related homelab remediation is indicated by this incident alone. [Railway's guidance](https://blog.railway.com/p/preliminary-report-october-security-incident) applies to sensitive variables stored on its platform and any credentials reused elsewhere; it is a provider breach rather than a PHP patch to install locally.

The operator also confirms **never using Zeabur**. No Zeabur deployment reference was found in the inspected Inkling repository, and no Zeabur-related credential rotation is indicated for this homelab. [Zeabur's incident report](https://dash-new.zeabur.com/blogs/october-2026-security-incident) concerns credentials and workloads stored on its platform. Its [shutdown announcement](https://zeabur.com/blogs/zeabur-is-shutting-down) schedules wind-down in December; the service had not already permanently stopped on the audit date. The provider-use question is closed for both Railway and Zeabur.

### 6. GitLab claim — no running GitLab found; Gitea needs its own fixes

No GitLab service/container was found on the five running machines. The supplied “October GitLab 10/10 access flaw” summary could not be matched to a specific current first-party advisory; do not treat it as a vulnerability in Gitea. Stopped guests have not been cleared.

There is a separate actionable **Gitea 1.27.3** finding: the [migration/mirror SSRF advisory](https://github.com/go-gitea/gitea/security/advisories/GHSA-6g2h-xpg3-rm48) includes this version and lists **28.0.0** as patched. Plan a supported fixed release upgrade with a verified data/database backup and migration review. Registration is disabled, but authenticated accounts, including an agent identity, still need consideration.

The [built-in SSH authentication bypass](https://github.com/go-gitea/gitea/security/advisories/GHSA-8pwg-hcgm-54cp) also lists the installed version but requires the built-in SSH server and SQLite. The inspected container instead runs **OpenSSH `sshd`** for the published port, with no `START_SSH_SERVER=true` configured; this particular path is not established as exposed. Actions is disabled and `INSTALL_LOCK=true`, reducing other configuration-dependent paths. Those controls do not fix the SSRF or old runtime.

## Additional findings across the environment

**Proxmox — high priority.** Installed `pve-manager 9.1.4` and `qemu-server 9.1.3` predate published security fixes; fresh APT metadata offers `9.2.21` and `9.2.11`. Installed QEMU `10.1.2-5` also trails candidate `11.0.3-4`. The [Proxmox advisory thread](https://forum.proxmox.com/threads/proxmox-virtual-environment-security-advisories.149331/page-4) names **7.0.14-24-pve** as fixed for guest-to-host issue CVE-2026-99999; `.10` runs **6.17.4-1-pve**, and no evidence establishes that old branch as fixed. Treat it as uncleared, move to the supported fixed kernel, and reboot. The available 7.0-series candidate was `7.0.14-25`; upgrading the guests alone cannot fix a host isolation flaw.

`intel-microcode` is absent on `.10`, its current Debian sources omit `non-free-firmware`, and APT has no candidate under those sources. The kernel explicitly reports `gather_data_sampling: Vulnerable: No microcode`, `mmio_stale_data: ... no microcode; SMT vulnerable`, and `old_microcode: Vulnerable`. Review firmware/microcode with the host update. `.9` has a microcode package, though its CPU still reports residual SMT-related mitigation limitations.

**Network boundary — defense is incomplete.** From inside the Hermes container, an unauthenticated GET reached Proxmox `.10:8006` (HTTP 200) and the old AIO admin `.9:8080` (HTTP 302). No login or exploit was attempted. The flat LAN and disabled Proxmox firewall allow management reachability contrary to the target agent isolation. A compromised agent or dependency therefore has a route to other vulnerable services. Router forwarding and reachability from the public internet were not independently tested. No global IPv6 address was observed on `.9` or the three live VMs.

**Updates — installed is not always active.** All three VMs have `/var/run/reboot-required` and a newer kernel installed than running. Their Docker, containerd, Buildx, and Compose packages are held deliberately, so unattended Ubuntu updates cannot maintain those pins. Besides the eMudhra issue, [Docker 29.8.2 and 29.9.1](https://docs.docker.com/engine/release-notes/29/) contain registry/image-processing security fixes missing from the guests' 29.8.1/containerd 2.3.5 stack. Keep reviewed pins but update them through the repository.

**Useful existing controls.** Password SSH login is disabled on `.10` and all three VMs. Gitea HTTP is loopback-only, Caddy serves valid private HTTPS, and dedicated guest rules protect AdGuard/Hermes HTTP backends. The Hermes worker runs as UID 10000, is not privileged, and has no Docker socket mounted. These reduce exposure but do not patch bundled dependencies. Inkling's Next.js `16.4.2` is outside the affected range of the [October image-optimization advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw); its separate Node runtime is still affected as above. Jellyfin, Samba, and cached old images were inventoried but have not received an exhaustive product/dependency assessment in this review.

## Recommended implementation order and acceptance

1. **Contain the legacy AIO controller if unused**, preserving its data volumes; otherwise update/recreate it promptly and verify PHP-FPM is fixed. Review the upload-progress mitigation. Recheck only intended private listeners.
2. **Schedule a Proxmox maintenance window** for supported kernel/PVE/QEMU/security package and firmware/microcode updates. Review repository configuration and backup/recovery readiness first. After reboot, verify the running host kernel, CPU mitigation files, VM startup, VirtioFS, DNS, HTTPS, and Hermes state.
3. **Replace affected Node/Brotli and trust bundles**, updating the source-controlled Hermes image and Caddy builder/runtime pins; update the legacy Inkling Node process and Python environment separately. Verify security build versions, CA contents, sessions, Git, and provider/Telegram operation after recreation. Prefer reviewed images over edits made only inside a running container.
4. **Update the held Docker/containerd package pins** and upgrade Gitea to a reviewed fixed release with backup/rollback preparation. Test application health and preserve durable state. Reboot the three VMs into their installed current kernels during the coordinated window.
5. **Restrict agent-to-management access** with the planned router/VLAN policy or a reviewed interim firewall policy; retain the required Gitea, DNS, provider, and proxy paths. Validate both allowed and denied traffic.
6. **Inventory offline guests/templates before reuse** and establish periodic vendor-advisory review, image/dependency review, and reboot tracking. Follow the outstanding distro Brotli status; Railway and Zeabur provider-use questions are closed based on confirmed non-use.

No remediation above was executed or marked complete. The detailed report records versions as observed on 25 October; refresh candidates/advisories before changing packages.

## Evidence commands used

The audit used `qm list`, selected non-secret `qm config` fields, `pct list`, `pveversion -v`, `uname -r`, `dpkg-query -W`, `apt-cache policy`, `apt-mark showhold`, APT index dates, `ss -lntu`, `sshd -T`, and CPU mitigation files. Container inspection selected names, images, mounts, users, processes, and privilege flags; it did **not** dump environment variables. PHP was checked with `php-fpm -v` / `php-fpm -i`; JavaScript with `node -p` for runtime versions; Python with package `METADATA` and bundle/indicator filename checks rather than imports. The public Caddy certificate was inspected with `openssl s_client` / `openssl x509`. The two management reachability requests used certificate verification bypass only for that read-only probe, not as an application configuration change.

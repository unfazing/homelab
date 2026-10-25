# Security remediation — 25 October 2026

**Available package/application updates and immediate containment are deployed and verified. Three finding groups remain open: native distro Brotli status, CPU mitigation limitations, and offline guest/template patch levels.** This follows the [original assessment](security-review-2026-10-25.md); it is not compliance certification or proof that a compromise never occurred.

## Changes on all five live machines

| Machine | Remediation and verified result |
| --- | --- |
| **blue / `.10`** | PVE manager **9.1.4 → 9.2.21**, qemu-server **9.1.3 → 9.2.11**, QEMU **10.1.2-5 → 11.0.3-4**, Debian security packages and CA trust updated. Enabled Debian `non-free-firmware` and installed current Intel microcode. Rebooted into **7.0.14-25-pve**, above the vendor's KVM fix threshold. Early microcode changed **0xec → 0x100**; `old_microcode` is now `Not affected`. All three VMs recovered automatically and ZFS is healthy. Residual CPU findings remain below. |
| **red-server / `.9`** | Kept operator-stopped legacy AIO exited and changed restart policy to **`no`**. No listeners remain on **81/8080/8443**; volumes retained. Operator completed interactive `task security:red-system`: Ubuntu updates and Docker **29.9.2 / Go 1.26.10** verified. No reboot pending; kernel **6.8.0-147-generic**. Inkling now runs **Node 24.22.1**, certifi **2026.10.23** and pip **26.2.2**. Restarted its existing launcher on the fixed Node executable, updated nvm's default, and verified frontend/backend health. WireGuard, Samba and Jellyfin services remain active. |
| **lab-access-01 / `.100`** | Ubuntu and held container-runtime packages updated. AdGuard remains **0.107.79**, rebuilt from checksum-pinned official source/frontend with **Go 1.27.3** and updated Alpine trust, replacing Go 1.26.6. DNS, private rewrites, administrator API and DDNS timer checks pass. Fixed a startup race: reconciliation now waits for authenticated DNS readiness after the HTTP socket opens. |
| **lab-services-01 / `.101`** | Ubuntu/container-runtime updates applied. Gitea **1.27.3 → 28.2.0** addresses the migration/mirror advisory; rebuilt with **Go 1.27.3**, official embedded web assets and updated Alpine trust. Database migration, integrity, health, four CSS/JS assets and agent API/Git checks pass. Caddy **2.11.4 → 2.11.7**, rebuilt with **Go 1.27.3**, Cloudflare module **v0.2.4** and updated trust. Existing production ACME state and Let's Encrypt certificate retained. |
| **lab-agents-01 / `.102`** | Ubuntu/container-runtime updates applied. Hermes **0.21.6 → 0.22.5**, using a security overlay on the digest-pinned official image. Verified **Node 26.12.1**, **brotlicffi 1.2.1.0**, **certifi 2026.10.23**, **pip 26.2.2**, updated Debian and standalone Python/pip trust. Durable workspaces, provider configuration and Git/API identity retained. SQLite integrity passes, DELETE journaling retained, **64 sessions** present after recreation. Workspace certifi **2026.10.19** was already fixed and retained. |

All three VMs now run **7.0.0-38-generic**. Their reviewed, held pins are **Docker CE 29.9.2 (Go 1.26.10), containerd 2.4.2-3, Buildx 0.38.1 and Compose 5.6.1**. Future Docker updates must also update these repository pins.

The [Node security release](https://nodejs.org/en/blog/release/v24.22.1) contains the Brotli fix even though its bundled library still reports `1.2.0`; that string alone is not the patch test. Gitea **28.2.0** follows upstream numbering. Images use pinned base manifests and source/wheel checksums; live distro package repositories remain build inputs, so historical byte-for-byte reproducibility is not claimed.

## Persistent agent boundary

Ansible-owned independent nftables tables on `.102` and blue replace only their own tables; they **never flush** global, Docker or WireGuard rules.

- New agent-initiated guest-local and container IPv4 connections from `.102` are blocked to Proxmox `.10`, router management `.254` (DNS 53 remains allowed), and legacy `.9` except Inkling TCP 3000.
- Blue independently drops new IPv4 connections sourced from `.102`. Established/related return traffic remains allowed on both hosts, preserving inbound administration and clients NATed through red. SSH banner checks from blue and red to the agent VM verify that return path. Systemd loads agent rules before Docker; the Hermes deployment now includes this boundary. Reapply `task security:boundaries` after a blue host rebuild.
- From Hermes worker UID **10000**, blue:8006, router HTTP and red:8080 timed out as intended. Gitea HTTPS/API, Git SSH, Inkling:3000, DNS and Telegram HTTPS remained reachable, including after reboot.

This is an **interim IPv4 address-based boundary**, not VLAN isolation, a complete application allowlist or protection against a privileged VM takeover/source spoofing. Full segmentation and IPv6 policy remain planned. Router WAN forwarding was not independently audited; this work added no public application ingress.

## Recovery and maintenance effects

Completed a root-only checkpoint on blue at **`/srv/homelab/.maintenance/security-2026-10-25`**:

- `host-config.tar.gz` (0600): Proxmox, network, APT, bootloader and SSH configuration.
- Recursive **`tank/homelab@security-2026-10-25`** ZFS snapshot after stopping application containers for consistency.
- Successful compressed OS backups of VMs **1000–1002**, about **5.0, 5.0 and 6.8 GiB**, under `vms/`; `vzdump.log` and `vm-backup-complete` record success.
- Additional consistent **`tank/homelab/services/gitea@pre-gitea28-security-20261025`** snapshot before database migration. A schema rollback needs matching data and image together; reverting only the image is insufficient. No rollback was required.

The initial checkpoint kept applications stopped longer than necessary during OS copies, briefly interrupting DNS. Availability was restored and the task reordered to resume applications after the data snapshot, before per-VM OS copies. Container replacements and the host reboot also caused maintenance interruptions. Final checks passed. **Recovery copies remain on the same physical server; they are not off-host backups or a tested full restore.** Persistent application data was not deleted.

## Verification and operator tasks

Executed `task security:checkpoint`, `security:guests`, `security:proxmox`, `security:boundaries`, `security:red-apps`, `security:reboot` and `security:verify`, plus existing application deployment Tasks. The operator executed `security:red-system` at its hidden sudo prompt.

Final `task security:verify` passed across **both servers and all three VMs with zero changes/failures**, explicitly printing the unresolved CPU warnings. It checks active kernels/runtimes, ZFS, persistent firewall, DDNS, private DNS/HTTPS, the single-user Telegram gate, allowed/denied network paths and authenticated agent API/Git reads. A separate **Git push dry run** passed without creating a branch or changing the repository. Gitea retained **three users and one repository**; both Gitea and Hermes SQLite `quick_check` returned `ok`.

No model prompt or Telegram message was sent. Provider files and connectivity were retained, but a live model reply/Telegram exchange still needs an operator functional check. WireGuard's service is active; remote full-tunnel operation and privileged red-server NAT/ruleset inspection were not verified in this non-interactive session.

`task config:validate` passes for inventory and all normal/maintenance playbooks. **15 AdGuard regression tests** pass, including startup readiness. `git diff --check` passes. Application convergence was repeated for idempotence. Both HTML sources of truth and relevant role READMEs were synchronized. No commits or pushes were made.

| Deployed image | Image ID (SHA-256) |
| --- | --- |
| `homelab/adguard:0.107.79-go1.27.3-security-20261025` | `ff66c55f0ad8748e740c04219524bd81b5c0f620db88d630fc5fecbd1c2690d2` |
| `homelab/gitea:28.2.0-go1.27.3-security-20261025` | `1c3bafa0e2eb529820727c5284221518154303bf97037fa6998a7ef31bb8f972` |
| `homelab/caddy-cloudflare:2.11.7-v0.2.4-go1.27.3` | `8ff81277127ffc2389ac66bd6d0593d1f0903d31ecca677a3a3a5a345b9975bc` |
| `homelab/hermes-agent:0.22.5-security-20261025` | `7d4a181bb3b444ecb0d9c73edc6c69fdae6a23623e2363baadeeb2cdd5d32675` |

## Remaining findings — not marked fixed

1. **Native Ubuntu Brotli:** `libbrotli1` remains **1.2.0-3build1** on the guests and **1.1.0-2build2** on red. [Ubuntu's tracker](https://ubuntu.com/security/CVE-2026-111497) still lists **Needs evaluation**, with no reviewed fixed candidate. Active Node and Hermes Python decoder fixes do not clear the system library. Follow the distro advisory and apply its fix when published; no manual core-library replacement was attempted.
2. **CPU mitigations:** blue's active kernel has **`# CONFIG_MITIGATION_GDS is not set`** and reports GDS **`Vulnerable`**. Updated microcode does not close this gap. MMIO reports **`Mitigation: Clear CPU buffers; SMT vulnerable`**. Red reports GDS `Not affected` but MMIO **`Unknown: No mitigations`**; it is not cleared either. A supported kernel with GDS mitigation enabled and a CPU-hardening decision remain necessary. [GDS guidance](https://docs.kernel.org/admin-guide/hw-vuln/gather_data_sampling.html) describes microcode/AVX controls; a flag is not a substitute for compiled-out support. [MMIO guidance](https://docs.kernel.org/admin-guide/hw-vuln/processor_mmio_stale_data.html) describes SMT disabling where supported. Disabling SMT reduces blue from eight logical threads to four; disabling AVX can affect performance and binary compatibility. CPU feature changes, raw MSR writes, custom kernels and BIOS flashing were not applied.
3. **Offline objects:** VMs **100–103** and templates **104/9000** remain powered off with patch status unknown. They were not started, mounted, deleted or declared safe. Rebuild/patch and verify before reuse, including a Packer template rebuild before creating new production guests. Patching current clones does not update their source template.

The obsolete AIO image is **contained, not PHP-patched**; keep it stopped until deliberately retired or recreated from a reviewed fixed release. No LiteLLM compromise was detected in the original inspected paths, which does not prove complete historical absence. Railway and Zeabur require no incident-specific rotation based on confirmed non-use.


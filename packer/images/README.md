# Packer Templates for Proxmox

**Tested with with Proxmox 9.1.2, Packer 1.14 and Packer Proxmox Plugin v1.2.3**

Build VM Templates with Packer for Proxmox. The generated templates are meant to be used with cloud-init, they come without a User or root login.                                  |

## How to build

### Prepare Packer

First initialize the proxmox packer plugin:

```sh
packer init config.pkr.hcl
```

### Prepare your variables

The templates use a generic source builder ([generic.pkr.hcl](./generic.pkr.hcl)) that's driven by variables. The OS specific settings are only variables and preseed files.

To build packer templates you need to set some variables via file (`-var-file=my.pkrvars.hcl`), cli (`-var variablename=value`), or environment (`PKR_VAR_variablename=value`):

- proxmox_host
- proxmox_user
- proxmox_password
- proxmox_token
- node
- vmid

Other interesting variables are:

- pool
- proxmox_insecure_tls
- disk_storage_pool
- iso_storage_pool
- cloud_init_storage_pool
- iso_download
- Windows:
  - windows_edition
  - windows_language / windows_input_language
  - winrm_username / winrm_password (Win11 alway creates a user, Win Server will use Administrator)

See [variables.pkr.hcl](./variables.pkr.hcl) for all varaibles.

### Build a template

To build a template (e.g. `ubuntu-24.04`) run:

```sh
packer build -var-file="ubuntu-24.04.pkrvars.hcl" .
```

### Packer to Proxmox Build Pipeline

| Step | What Happens | Duration |
| :--- | :--- | :--- |
| **1** | Packer connects to Proxmox API using `.envrc` credentials | ~2s |
| **2** | Creates a new VM on node **blue** with next available ID | ~5s |
| **3** | Attaches ISO: `local:iso/ubuntu-24.04.3-live-server-amd64.iso` | ~2s |
| **4** | Boots VM; starts local HTTP server for `../http/ubuntu/` | ~5s |
| **5** | Sends boot command to inject **autoinstall** into GRUB | ~10s |
| **6** | Ubuntu installer runs (partitioning, packages, apt upgrade) | 10–20 min |
| **7** | VM reboots; Packer waits for SSH connection (`packer/packer`) | ~1–3 min |
| **8** | **Provisioner:** `cloud-init clean`, remove configs, delete user | ~30s |
| **9** | Packer shuts down VM and converts it to a **Proxmox Template** | ~10s |
| **10** | **Done** — Template ready for cloning via Terraform | — |

How It Works
1. Boot command (ubuntu-24.04.pkrvars.hcl) — Packer sends keystrokes to the GRUB menu to inject the autoinstall parameter, pointing to the HTTP server Packer spins up locally:
      autoinstall ds=nocloud-net;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ ---
   
2. HTTP server — Packer serves the ../http/ubuntu/ directory, which contains:
   - user_data — Your cloud-config with all the installation answers (hostname, user, password, storage layout, packages, etc.)
   - meta_data — Empty file (required by cloud-init but can be blank)
3. Ubuntu autoinstall — The installer reads user_data and performs the entire installation unattended:
   - Sets hostname to ubuntu
   - Creates the packer user
   - Uses direct disk layout (no LVM prompts)
   - Installs qemu-guest-agent and SSH server
   - Runs apt update && apt upgrade -y
4. SSH handoff — After the install completes and the VM reboots, Packer waits for SSH to become available (up to 30 minutes per your ssh_timeout), then connects as packer/packer to run the provisioner cleanup.

So the full flow is hands-off:

packer build → creates VM → boots ISO → injects autoinstall → 
Ubuntu installs itself → reboots → Packer SSHs in → 
runs cleanup → converts to template → done

## Useful Tips

### Packer Webserver Forwarding

In some cases your proxmox server might be in a datacatenter. You can ssh to the proxmox server but the proxmox server can't connect to your build computer.

Set the following variables in your configuration.

- packer_http_interface to `127.0.0.1`
- packer_http_port to `8000`

**Your Proxmox Server can be reached via ssh**

Start this in a console on your build host and keep it open during build time.

```bash
# forward 127.0.0.1:8000 to the remote proxmox to 127.0.0.1:8000
ssh -N -R 127.0.0.1:8000:127.0.0.1:8000 root@proxmox
```

**Your Proxmox Server can't be reached from the build computer via ssh**

In this case you need a 2nd computer that can be reached from the proxmox computer and the build computer acting as relais.

On the proxmox host:

```bash
ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 user@lighthouse
```

On the build computer:

```bash
ssh -N -R 127.0.0.1:8000:127.0.0.1:8000 user@lighthouse
```
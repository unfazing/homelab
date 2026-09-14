# Ubuntu 26.04 Proxmox template

This directory defines the generic `ubuntu-26.04-template` at fixed Proxmox VM ID `9000`. It uses the checksum-pinned Ubuntu Server 26.04.1 LTS ISO, 2 vCPU, 4 GiB RAM, and a 16 GiB OS disk. VM-specific sizing, identity, networking, and applications are applied later by Terraform and Ansible.

## Files

- `config.pkr.hcl` pins the Proxmox plugin.
- `generic.pkr.hcl` defines the reusable Proxmox ISO builder.
- `variables.pkr.hcl` declares the builder contract.
- `ubuntu-26.04.pkrvars.hcl` pins the Ubuntu release, checksum, template ID, and build sizing.
- `../../seed/ubuntu` contains the NoCloud autoinstall template.
- `../../../scripts/packer-image.sh` renders a temporary seed and runs validation or the build.

## Validate and build

Run from the repository root. Supply Proxmox connection values through an ignored `.envrc`; see `.envrc.example`.

```sh
task image:validate
task image:build
```

`image:build` changes Proxmox. It first refuses to continue when VM ID `9000` is occupied, then asks Proxmox to download the pinned Ubuntu ISO directly. Packer packages the generated seed as a temporary `cidata` ISO and attaches it to the build VM; no seed HTTP server is opened on the operator machine.

Every validation and build generates a new ED25519 key in `.generated/packer`, renders the public key into the seed, and removes the seed and key on exit. Password SSH is disabled. After first-boot cloud-init finishes, Packer removes installer networking, regenerates the local-disk initramfs without the unnecessary `dyn-netconf` and `systemd-networkd` modules, and removes the temporary `packer` account and sudo rule. This prevents clones from requesting DHCP with the shared installer hostname before cloud-init applies their individual identities. Dracut errors or a remaining default network profile fail the build. A successful build leaves only the non-secret `.generated/packer/manifest.json` record.

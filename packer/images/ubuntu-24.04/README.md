# Ubuntu 24.04 Proxmox template

This directory is the complete definition for the generic `ubuntu-24.04-template`. It currently uses 2 vCPU, 4 GiB RAM, and a 16 GiB OS disk during the build. VM-specific sizing, identity, networking, and applications are applied later by Terraform and Ansible.

## Files

- `config.pkr.hcl` pins the Proxmox plugin.
- `generic.pkr.hcl` defines the reusable Proxmox ISO builder.
- `variables.pkr.hcl` declares the builder contract.
- `ubuntu-24.04.pkrvars.hcl` contains Ubuntu-specific inputs.
- `../../http/ubuntu` contains the NoCloud autoinstall seed.

## Validate and build

Run from the repository root. Supply Proxmox connection values through `PKR_VAR_*` environment variables or an ignored variable file.

```sh
packer init packer/images/ubuntu-24.04
packer fmt -check -recursive packer/images/ubuntu-24.04
packer validate \
  -var-file=packer/images/ubuntu-24.04/ubuntu-24.04.pkrvars.hcl \
  packer/images/ubuntu-24.04
packer build \
  -var-file=packer/images/ubuntu-24.04/ubuntu-24.04.pkrvars.hcl \
  packer/images/ubuntu-24.04
```

The build boots the Ubuntu ISO, serves the autoinstall seed, installs the guest agent and SSH server, removes installer-specific identity, deletes the temporary `packer` account, and converts the VM to a Proxmox template.

The committed bootstrap password remains a known hardening gap. Replace it with an ephemeral credential before treating the image pipeline as production-ready; see `implementation.html` for its acceptance criteria.

# Terraform Provisioning

This directory contains the Terraform configuration for provisioning Proxmox VMs from the Packer-built Ubuntu template.

Terraform is responsible for:
- cloning the template into VM instances
- attaching the expected Proxmox hardware
- configuring baseline cloud-init fields
- injecting SSH public keys

Terraform is not responsible for application-role configuration.

For `core-network`, Terraform only creates the VM. WireGuard and AdGuard are configured afterward by remote Ansible in [ansible/README.md](/Users/lian/dev/homelab/ansible/README.md).

## Quickstart

1. Fill in your Terraform variables in [deployment.tfvars.json](/Users/lian/dev/homelab/terraform/deployment.tfvars.json).

2. Run a plan:

```bash
terraform -chdir=terraform plan -var-file=deployment.tfvars.json
```

3. Apply the changes:

```bash
terraform -chdir=terraform apply -var-file=deployment.tfvars.json
```

4. After the VMs boot, use Ansible for role-specific configuration:

```bash
ansible-playbook -i ansible/inventory/core-network.ini ansible/playbooks/core-network.yml
```

## What This Config Does

The Terraform configuration in this directory:
- reads SSH public keys from a local file
- provisions one Proxmox VM per entry in the `vms` map
- clones from your Packer template
- configures:
  - UEFI (`ovmf`)
  - `q35`
  - SCSI boot disk
  - CloudInit disk on `ide0`
  - cloud-init user `user`
  - injected SSH public keys
  - DHCP by default, with optional per-VM MAC address

## Files

- [main.tf](/Users/lian/dev/homelab/terraform/main.tf)
  Main Proxmox VM resource and outputs.

- [variables.tf](/Users/lian/dev/homelab/terraform/variables.tf)
  Terraform input variables, including the `vms` map and SSH key file path.

- [locals.tf](/Users/lian/dev/homelab/terraform/locals.tf)
  Normalized local values derived from the `vms` map.

- [providers.tf](/Users/lian/dev/homelab/terraform/providers.tf)
  Terraform and provider requirements.

- [deployment.tfvars.json](/Users/lian/dev/homelab/terraform/deployment.tfvars.json)
  Example deployment variables file.

## Tutorial

### 1. Prepare your template

Before using this Terraform config, make sure you already have a working Proxmox template built by Packer.

In this repo, the expected template is something like:

```text
ubuntu-24.04-template
```

That template should already:
- boot successfully
- include `qemu-guest-agent`
- support Proxmox cloud-init

### 2. Configure the deployment variables

Edit [deployment.tfvars.json](/Users/lian/dev/homelab/terraform/deployment.tfvars.json).

Example:

```json
{
  "ssh_public_key_file": "./keys/keys.pub",
  "debug_password": "test",
  "vms": {
    "core-network": {
      "target_node": "blue",
      "clone": "ubuntu-24.04-template",
      "cpu_cores": 2,
      "memory_mb": 4096,
      "disk_gb": 32,
      "disk_storage": "local-lvm",
      "bridge": "vmbr0",
      "ipconfig0": "ip=dhcp"
    },
    "dev-01": {
      "target_node": "blue",
      "clone": "ubuntu-24.04-template",
      "cpu_cores": 8,
      "memory_mb": 16384,
      "disk_gb": 100,
      "disk_storage": "local-lvm",
      "bridge": "vmbr0",
      "ipconfig0": "ip=dhcp"
    }
  }
}
```

Important fields:
- `ssh_public_key_file`
  Path to a public key file. Multiple public keys can be included, one per line.

- `debug_password`
  Optional temporary password for debugging console or SSH access. Remove it when you return to key-only operation.

- `vms`
  Map of VM definitions keyed by the VM name that should appear in Proxmox.

### 3. Run Terraform plan

```bash
terraform -chdir=terraform plan -var-file=deployment.tfvars.json
```

Things to look for:
- one `proxmox_vm_qemu` instance per VM in the `vms` map
- `ciuser = "user"`
- the expected clone source
- the expected disk storage
- the expected network bridge and MAC, if set

### 4. Apply the infrastructure

```bash
terraform -chdir=terraform apply -var-file=deployment.tfvars.json
```

After apply, each VM should exist in Proxmox with:
- an OS disk on `scsi0`
- a CloudInit disk on `ide2`
- an EFI disk

### 5. Verify the VM in Proxmox

For each VM, especially `core-network`, check in the Proxmox UI:
- the VM exists
- the hardware looks correct
- the VM boots
- cloud-init values are present

For `core-network`, this is the end of Terraform’s responsibility. The software role is configured afterward with Ansible.

### 6. Continue with Ansible

Once `core-network` is reachable over SSH, continue with:

[ansible/README.md](/Users/lian/dev/homelab/ansible/README.md)

That next step installs and configures:
- WireGuard
- AdGuard Home
- generated client configs and related artifacts

## Notes

- This Terraform config intentionally keeps the Packer image generic.
- Role-specific software should not be pushed into Terraform or the base image unless there is a strong reason.
- `core-network` is launched like any other VM in the `vms` map.
- All role-specific configuration for `core-network` should live in Ansible, not in Terraform variables.

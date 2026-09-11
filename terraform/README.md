# Terraform provisioning

Terraform clones the generic Packer image and owns rebuildable VM infrastructure: CPU, memory, OS disks, NICs, VLAN tags, cloud-init identity, and machine-readable outputs. Application configuration remains in Ansible.

## Layout

- `main.tf` composes one reusable module instance per entry in `var.vms`.
- `modules/proxmox-vm` owns the Proxmox VM resource.
- `outputs.tf` exposes VM identity and the non-secret Ansible inventory contract.
- `deployment.tfvars.json` is the local deployment input and must not contain committed secrets.

## VM input contract

Each `vms` entry is keyed by its workload-independent hostname. It selects the template, capacity, bridge, VLAN, network configuration, and Ansible groups. For example:

```hcl
vms = {
  lab-access-01 = {
    target_node    = "blue"
    clone          = "ubuntu-24.04-template"
    cpu_cores      = 1
    memory_mb      = 1024
    disk_gb        = 16
    disk_storage   = "local-lvm"
    bridge         = "vmbr0"
    vlan_tag       = 20
    ipconfig0      = "ip=10.73.20.10/24,gw=10.73.20.1"
    ansible_host   = "10.73.20.10"
    ansible_groups = ["access"]
  }
}
```

The approved five-VM topology and final addresses will be added after the remaining network inputs are settled.

## Flow

```sh
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan -var-file=deployment.tfvars.json
terraform -chdir=terraform apply -var-file=deployment.tfvars.json
terraform -chdir=terraform output -json ansible_inventory
```

The final output is consumed by the planned inventory generator, which will write `.generated/ansible/hosts.yml`. Continue with [the Ansible guide](/Users/lian/dev/homelab/ansible/README.md) only after Terraform apply and inventory generation succeed.

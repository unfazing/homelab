# Terraform provisioning

Terraform clones the generic Packer image and owns rebuildable VM infrastructure: CPU, memory, OS disks, NICs, VLAN tags, cloud-init identity, and machine-readable outputs. Application configuration remains in Ansible.

## Layout

- `main.tf` composes one reusable module instance per entry in `var.vms`.
- `modules/proxmox-vm` owns the Proxmox VM resource.
- `image-verification` uses that module for one linked template-test clone in an isolated local state, then automatically destroys it.
- `outputs.tf` exposes VM identity and the non-secret Ansible inventory contract.
- `deployment.tfvars.json` is the versioned, non-secret five-VM topology. Never add credentials or private keys to it.

The image-verification clone receives an explicit DHCP `ipconfig0`. The current F620 DHCP server misaddresses a second clone's Offer at Ethernet layer, so multi-clone verification is deferred until it can use excluded static test addresses or DHCP moves to the target firewall router.

## VM input contract

Each `vms` entry is keyed by its workload-independent hostname. It selects the template, capacity, bridge, VLAN, network configuration, and Ansible groups. For example:

```hcl
vms = {
  lab-access-01 = {
    target_node    = "blue"
    clone          = "ubuntu-26.04-template"
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

The temporary flat-LAN topology uses fixed VM IDs `1000`–`1004` and addresses `192.168.1.100`–`192.168.1.104`. Before applying it, reduce the F620 DHCP end address to `192.168.1.99`, then export `HOMELAB_STATIC_RANGE_RESERVED=yes`. The final VLAN deployment will replace these temporary addresses with the approved `10.73.0.0/16` plan.

## Flow

```sh
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan -var-file=deployment.tfvars.json
terraform -chdir=terraform apply -var-file=deployment.tfvars.json
terraform -chdir=terraform output -json ansible_inventory
```

The equivalent operator commands are `task infra:init`, `task infra:validate`, `task infra:plan`, `task infra:apply`, and `task infra:output`. Apply remains interactive and refuses to start without the static-range confirmation variable.

The final output is consumed by the planned inventory generator, which will write `.generated/ansible/hosts.yml`. Continue with [the Ansible guide](/Users/lian/dev/homelab/ansible/README.md) only after Terraform apply and inventory generation succeed.

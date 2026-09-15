locals {
  verification_vms = {
    a = 9900
  }
}

module "verification_vm" {
  source   = "../modules/proxmox-vm"
  for_each = local.verification_vms

  vmid               = each.value
  name               = "verify-ubuntu-26-04-${each.key}"
  target_node        = var.verification_node
  clone_id           = var.template_vmid
  full_clone         = false
  cpu_cores          = 1
  memory_mb          = 1024
  disk_gb            = 16
  disk_storage       = "local-lvm"
  bridge             = "vmbr0"
  ipv4_address       = "dhcp"
  cloud_init_user    = "verifier"
  ssh_public_key     = var.ssh_public_key
  start_at_node_boot = false
  agent_timeout      = 300
}

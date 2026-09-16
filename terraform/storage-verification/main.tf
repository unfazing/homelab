resource "proxmox_hardware_mapping_dir" "proof" {
  name    = "homelab-virtiofs-proof"
  comment = "Disposable homelab VirtioFS persistence proof."

  map = [
    {
      node = var.verification_node
      path = var.verification_path
    },
  ]
}

module "verification_vm" {
  source = "../modules/proxmox-vm"

  vmid               = 9900
  name               = "verify-virtiofs"
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

  virtiofs_mappings = [
    {
      mapping      = proxmox_hardware_mapping_dir.proof.name
      cache        = "auto"
      direct_io    = true
      expose_acl   = true
      expose_xattr = true
    },
  ]
}

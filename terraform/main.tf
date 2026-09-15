module "vm" {
  source   = "./modules/proxmox-vm"
  for_each = local.vms

  name            = each.key
  vmid            = each.value.vmid
  target_node     = each.value.target_node
  clone_id        = each.value.clone_id
  cpu_cores       = each.value.cpu_cores
  memory_mb       = each.value.memory_mb
  disk_gb         = each.value.disk_gb
  disk_storage    = each.value.disk_storage
  bridge          = each.value.bridge
  vlan_tag        = each.value.vlan_tag
  mac_address     = each.value.mac_address
  ipv4_address    = each.value.ipv4_address
  ipv4_gateway    = each.value.ipv4_gateway
  cloud_init_user = var.cloud_init_user
  debug_password  = var.debug_password
  ssh_public_key  = local.ssh_public_key
}

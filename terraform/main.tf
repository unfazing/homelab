resource "proxmox_hardware_mapping_dir" "application_data" {
  for_each = local.data_mappings

  name    = each.key
  comment = "Persistent homelab application data for ${each.value.vm_name}."

  map = [
    {
      node = each.value.node
      path = each.value.path
    },
  ]
}

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

  virtiofs_mappings = [
    for mapping_name in sort(keys(each.value.virtiofs_mappings)) : {
      mapping      = proxmox_hardware_mapping_dir.application_data[mapping_name].name
      cache        = "auto"
      direct_io    = true
      expose_acl   = true
      expose_xattr = true
    }
  ]
}

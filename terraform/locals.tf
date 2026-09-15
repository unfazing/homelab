locals {
  ssh_public_key = trimspace(file(var.ssh_public_key_file))

  vms = {
    for name, cfg in var.vms : name => {
      name           = name
      vmid           = cfg.vmid
      target_node    = cfg.target_node
      clone_id       = cfg.clone_id
      cpu_cores      = cfg.cpu_cores
      memory_mb      = cfg.memory_mb
      disk_gb        = cfg.disk_gb
      disk_storage   = cfg.disk_storage
      bridge         = cfg.bridge
      vlan_tag       = try(cfg.vlan_tag, null)
      ipv4_address   = cfg.ipv4_address
      ipv4_gateway   = try(cfg.ipv4_gateway, null)
      mac_address    = try(cfg.mac_address, null)
      ansible_host   = try(cfg.ansible_host, null)
      ansible_groups = try(cfg.ansible_groups, [])
    }
  }
}
